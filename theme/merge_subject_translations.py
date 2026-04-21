"""
Theme Amazon Novelty - subject_translation 语义归并脚本（v2 重构版）

重构要点：
- 双语校验：同时使用 subject（英文）和 subject_translation（中文）进行聚合判断
- 字段回退：subject/subject_translation 为空或"识别失败"时，回退到 title/title_translation
- 硬锚点约束：年份、年龄、大写缩写、序数词不一致时禁止合并
- ASIN 精确回写：全流程携带 ASIN，最终按 ASIN 批量更新外键
- 精细化 LLM Prompt：新角色（Amazon 运营专家）+ CoT（reason 字段）+ 双语输入

使用方法：
    python theme/merge_subject_translations.py              # 增量模式（默认）
    python theme/merge_subject_translations.py --full        # 全量重新归并
    python theme/merge_subject_translations.py --resume      # 从断点续传
"""

import json
import os
import re
import sys
import threading
import time
import argparse
from dataclasses import dataclass, field
from pathlib import Path
from typing import (
    List,
    Dict,
    Any,
    Set,
    Tuple,
    Optional,
    FrozenSet,
    Sequence,
)
from concurrent.futures import ThreadPoolExecutor, as_completed

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Overlord.settings")

import django

django.setup()

from django.utils import timezone
import numpy as np
from openai import OpenAI
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from theme.models import AmazonThemeNovelty, ThemeNoveltySummary

# --------------------------- 配置 ---------------------------
LLM_MODEL = "qwen3.6-plus"
LLM_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
BATCH_SIZE = 250
MAX_WORKERS = 10
MIN_LAYER_REDUCTION = 5
UPDATE_CHUNK_SIZE = 500
CHECKPOINT_DIR = Path(__file__).parent / ".merge_checkpoints"
CHECKPOINT_VERSION = 2

LLM_API_KEY = os.environ.get("DASHSCOPE_API_KEY", "")
if not LLM_API_KEY:
    LLM_API_KEY = "sk-c3f9ddb0b5454da2b9db130228049d84"
if not LLM_API_KEY:
    try:
        from django.conf import settings as django_settings

        LLM_API_KEY = getattr(django_settings, "DASHSCOPE_API_KEY", "")
    except Exception:
        pass

if not LLM_API_KEY:
    print(
        "[ERROR] 未找到 API Key。请设置环境变量 DASHSCOPE_API_KEY "
        "或在 Django settings 中配置 DASHSCOPE_API_KEY"
    )
    sys.exit(1)

EMBEDDING_MODEL = "text-embedding-v3"
EMBEDDING_BATCH_SIZE = 10
EMBEDDING_MAX_WORKERS = 20
LAYER1_EMBEDDING_THRESHOLD = 0.90
LAYER2_EMBEDDING_THRESHOLD = 0.92

ACRONYM_STOPWORDS = frozenset(
    {
        "AND",
        "FOR",
        "THE",
        "NOT",
        "NEW",
        "OLD",
        "FUN",
        "TOP",
        "BEST",
        "HOT",
        "BIG",
        "SET",
        "BOX",
        "BAG",
        "CUP",
        "MUG",
        "ALL",
        "CAN",
        "HAS",
        "HER",
        "HIM",
        "HIS",
        "HOW",
        "ITS",
        "LET",
        "MAY",
        "NOW",
        "OUR",
        "OUT",
        "OWN",
        "PUT",
        "RED",
        "RUN",
        "SAY",
        "SEE",
        "SHE",
        "USE",
        "VIA",
        "WAY",
        "WHO",
        "WHY",
        "YES",
        "YOU",
        "ARE",
        "BUT",
        "DID",
        "GET",
        "GOT",
        "HAD",
        "ONE",
        "TWO",
        "USA",
        "DIY",
        "LED",
        "LCD",
        "GPS",
        "USB",
        "HDMI",
        "WIFI",
        "BBQ",
        "UFO",
        "ATM",
        "VIP",
        "CEO",
        "CFO",
        "PHD",
        "MBA",
        "LLC",
        "INC",
        "LTD",
        "RGB",
        "CPU",
        "GPU",
        "FAQ",
        "SEO",
        "SNS",
        "APP",
        "LOG",
        "PET",
        "CAR",
        "SUV",
        "DVD",
        "CDR",
        "MP3",
        "PDF",
        "GIF",
        "PNG",
        "JPG",
        "ZIP",
        "RAR",
        "DOC",
        "TXT",
        "CSV",
        "SQL",
        "IBM",
        "AWS",
        "API",
        "URL",
        "URI",
        "HTP",
        "SSH",
        "SSL",
        "WHO",
        "WTF",
        "OMG",
        "LOL",
        "FYI",
        "BTW",
        "ASAP",
        "IMO",
        "MR",
        "MS",
        "MRS",
        "DR",
        "JR",
        "SR",
        "I",
        "II",
        "III",
        "IV",
        "V",
        "VI",
        "VII",
        "VIII",
        "IX",
        "X",
        "XI",
        "XII",
        "XIII",
        "XIV",
        "XV",
        "XVI",
        "XVII",
        "XVIII",
        "XIX",
        "XX",
        "TO",
        "OF",
        "IN",
        "ON",
        "AT",
        "BY",
        "UP",
        "SO",
        "IT",
        "IF",
        "OR",
        "AS",
        "AN",
        "BE",
        "DO",
        "GO",
        "HE",
        "ME",
        "MY",
        "NO",
        "OK",
        "WE",
        "OK",
    }
)


# --------------------------- LLM / Embedding 初始化 ---------------------------
chat = ChatOpenAI(
    api_key=LLM_API_KEY,
    base_url=LLM_BASE_URL,
    model=LLM_MODEL,
    temperature=0,
    max_retries=3,
)

embedding_client = OpenAI(
    api_key=LLM_API_KEY,
    base_url=LLM_BASE_URL,
)


# --------------------------- 核心数据结构 ---------------------------
@dataclass(frozen=True)
class ConstraintTag:
    years: FrozenSet[str] = frozenset()
    ages: FrozenSet[str] = frozenset()
    acronyms: FrozenSet[str] = frozenset()
    ordinals: FrozenSet[str] = frozenset()

    def is_empty(self) -> bool:
        return (
            not self.years and not self.ages and not self.acronyms and not self.ordinals
        )

    def to_dict(self) -> Dict[str, List[str]]:
        return {
            "years": sorted(self.years),
            "ages": sorted(self.ages),
            "acronyms": sorted(self.acronyms),
            "ordinals": sorted(self.ordinals),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ConstraintTag":
        return cls(
            years=frozenset(d.get("years", [])),
            ages=frozenset(d.get("ages", [])),
            acronyms=frozenset(d.get("acronyms", [])),
            ordinals=frozenset(d.get("ordinals", [])),
        )


@dataclass
class SubjectItem:
    asin: str
    en: str
    zh: str
    constraints: ConstraintTag = field(default_factory=ConstraintTag)

    def embedding_text(self) -> str:
        return f"{self.en} | {self.zh}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "asin": self.asin,
            "en": self.en,
            "zh": self.zh,
            "constraints": self.constraints.to_dict(),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "SubjectItem":
        return cls(
            asin=d["asin"],
            en=d["en"],
            zh=d["zh"],
            constraints=ConstraintTag.from_dict(d.get("constraints", {})),
        )


# --------------------------- 特征提取（Fingerprinting） ---------------------------
_RE_YEAR = re.compile(r"\b(20\d{2})\b")
_RE_AGE_EN = re.compile(r"\b(\d{1,2})\s*(?:years?\s*old|yo|yr\s*old)\b", re.IGNORECASE)
_RE_AGE_ZH = re.compile(r"(\d{1,2})\s*岁")
_RE_ORDINAL = re.compile(
    r"\b(\d{1,2})(?:st|nd|rd|th)\s*(?:birthday|bday|b-day|anniversary|grade)\b",
    re.IGNORECASE,
)
_RE_ACRONYM = re.compile(r"\b([A-Z]{2,})\b")


def _is_valid_field(value: Optional[str]) -> bool:
    if not value:
        return False
    s = value.strip()
    return bool(s) and s != "识别失败"


def extract_constraints(text_en: str, text_zh: str) -> ConstraintTag:
    years: Set[str] = set()
    ages: Set[str] = set()
    acronyms: Set[str] = set()
    ordinals: Set[str] = set()

    combined = f"{text_en} {text_zh}"

    for m in _RE_YEAR.finditer(combined):
        years.add(m.group(1))

    for m in _RE_AGE_EN.finditer(text_en):
        ages.add(m.group(1))
    for m in _RE_AGE_ZH.finditer(text_zh):
        ages.add(m.group(1))

    for m in _RE_ORDINAL.finditer(text_en):
        ordinals.add(m.group(1).lower())

    for m in _RE_ACRONYM.finditer(text_en):
        token = m.group(1)
        if token not in ACRONYM_STOPWORDS:
            acronyms.add(token)

    return ConstraintTag(
        years=frozenset(years),
        ages=frozenset(ages),
        acronyms=frozenset(acronyms),
        ordinals=frozenset(ordinals),
    )


def _constraints_compatible(c1: ConstraintTag, c2: ConstraintTag) -> bool:
    for field_name in ("years", "ages", "acronyms", "ordinals"):
        s1 = getattr(c1, field_name)
        s2 = getattr(c2, field_name)
        if s1 and s2 and s1 != s2:
            return False
    return True


# --------------------------- 动态 max_tokens ---------------------------
def _estimate_max_tokens(subjects: Sequence[SubjectItem]) -> int:
    total_chars = sum(len(s.en) + len(s.zh) for s in subjects)
    return min(4000, max(400, int(total_chars * 0.7) + 300))


# --------------------------- 垃圾过滤 ---------------------------
_DIGITAL_RE = re.compile(r"^\d+$")
_PUNCT_ONLY_RE = re.compile(r"^[^\w\u4e00-\u9fff]+$")


def _is_noise_text(text: str) -> bool:
    s = text.strip()
    if not s or len(s) < 2:
        return True
    return bool(_DIGITAL_RE.fullmatch(s) or _PUNCT_ONLY_RE.fullmatch(s))


def _filter_noise_items(
    items: List[SubjectItem],
) -> Tuple[List[SubjectItem], List[SubjectItem]]:
    valid, noise = [], []
    for item in items:
        if _is_noise_text(item.en) and _is_noise_text(item.zh):
            noise.append(item)
        else:
            valid.append(item)
    return valid, noise


# --------------------------- 轻量归一化 ---------------------------
def _normalize_subject(text: str) -> str:
    s = text.strip().lower()
    s = re.sub(r"\s+", " ", s).strip()
    return s


# --------------------------- 数据提取 ---------------------------
def fetch_distinct_subjects(
    incremental: bool = False,
) -> Tuple[List[SubjectItem], Dict[str, SubjectItem], Dict[str, List[str]]]:
    """
    返回：
    - unique_items: 去 (en,zh) 重后的代表 SubjectItem 列表
    - item_pool: {asin: SubjectItem} 全量映射
    - dedup_asins: {代表asin: [该 (en,zh) 下所有 asin]} 用于 Layer 1 upstream_map 展开
    """
    qs = AmazonThemeNovelty.objects.all().only(
        "asin",
        "subject",
        "subject_translation",
        "title",
        "title_translation",
    )

    if incremental:
        already_mapped_asins = set(
            AmazonThemeNovelty.objects.filter(
                theme_novelty_summary__isnull=False
            ).values_list("asin", flat=True)
        )
        qs = qs.exclude(asin__in=already_mapped_asins)
        print(
            f"[INFO] 增量模式：已归并 {len(already_mapped_asins)} 个 ASIN，剩余待处理"
        )

    item_pool: Dict[str, SubjectItem] = {}
    dedup: Dict[Tuple[str, str], List[str]] = {}

    for row in qs.iterator(chunk_size=2000):
        en = row.subject if _is_valid_field(row.subject) else row.title
        zh = (
            row.subject_translation
            if _is_valid_field(row.subject_translation)
            else row.title_translation
        )
        if not _is_valid_field(en) and not _is_valid_field(zh):
            continue
        en = en.strip()
        zh = zh.strip() if zh else ""
        asin = row.asin
        constraints = extract_constraints(en, zh)
        item = SubjectItem(asin=asin, en=en, zh=zh, constraints=constraints)
        item_pool[asin] = item
        key = (en.lower(), zh.lower())
        dedup.setdefault(key, []).append(asin)

    print(
        f"[INFO] 共获取到 {len(item_pool)} 个 ASIN，"
        f"去重后 {len(dedup)} 个唯一 (en,zh) 对"
    )

    unique_items: List[SubjectItem] = []
    dedup_asins: Dict[str, List[str]] = {}
    for (en_l, zh_l), asin_list in dedup.items():
        rep_asin = asin_list[0]
        rep = item_pool[rep_asin]
        unique_items.append(rep)
        dedup_asins[rep_asin] = asin_list

    return unique_items, item_pool, dedup_asins


# --------------------------- 本地快速合并 ---------------------------
def _preprocess_subjects(
    items: List[SubjectItem],
    item_pool: Dict[str, SubjectItem],
) -> Tuple[List[Dict[str, Any]], List[SubjectItem]]:
    """
    轻量归一化 + 本地快速合并。
    相同 normalize(en) 的项直接合并（asin 列表合并）。

    返回：
    - local_merged: [{"canonical": str, "asin_list": List[str], "reason": str}]
    - remaining: 仍需进一步聚合的 SubjectItem 列表（去重）
    """
    norm_to_asins: Dict[str, List[str]] = {}
    norm_to_rep_item: Dict[str, SubjectItem] = {}

    for item in items:
        norm = _normalize_subject(item.en)
        if not norm:
            continue
        norm_to_asins.setdefault(norm, []).append(item.asin)
        if norm not in norm_to_rep_item:
            norm_to_rep_item[norm] = item

    local_merged: List[Dict[str, Any]] = []
    remaining: List[SubjectItem] = []

    for norm, asin_list in norm_to_asins.items():
        rep_item = norm_to_rep_item[norm]
        if len(asin_list) > 1:
            local_merged.append(
                {
                    "canonical": rep_item.zh or rep_item.en,
                    "asin_list": asin_list,
                    "reason": "归一化后英文文本完全一致",
                }
            )
        else:
            remaining.append(rep_item)

    return local_merged, remaining


# --------------------------- Embedding 聚类（带约束） ---------------------------
def _fetch_embedding_batch(batch: List[str]) -> List[List[float]]:
    resp = embedding_client.embeddings.create(model=EMBEDDING_MODEL, input=batch)
    return [d.embedding for d in resp.data]


def _cluster_by_embedding(
    items: List[SubjectItem],
    threshold: float = LAYER1_EMBEDDING_THRESHOLD,
    embed_batch_size: int = EMBEDDING_BATCH_SIZE,
    _cache: Optional[Dict[str, np.ndarray]] = None,
) -> List[List[SubjectItem]]:
    """基于 text-embedding-v3 + cosine similarity + 约束检查的聚类"""
    if not items:
        return []

    cache = _cache if _cache is not None else {}
    unique_items = list({id(item): item for item in items}.values())
    n = len(unique_items)

    to_fetch = []
    to_fetch_indices = []
    for i, item in enumerate(unique_items):
        emb_key = item.embedding_text()
        if emb_key not in cache:
            to_fetch.append(emb_key)
            to_fetch_indices.append(i)

    cached_hits = n - len(to_fetch)

    if to_fetch:
        print(
            f"[EMBEDDING] 获取 {len(to_fetch)}/{n} 个主题向量"
            f"（缓存命中 {cached_hits}）..."
        )
        texts_to_fetch = to_fetch
        batches = [
            (idx, texts_to_fetch[i : i + embed_batch_size])
            for idx, i in enumerate(range(0, len(texts_to_fetch), embed_batch_size))
        ]
        batch_results: List[Optional[List[List[float]]]] = [None] * len(batches)

        with ThreadPoolExecutor(max_workers=EMBEDDING_MAX_WORKERS) as executor:
            futures = {
                executor.submit(_fetch_embedding_batch, batch): b_idx
                for b_idx, batch in batches
            }
            completed = 0
            for future in as_completed(futures):
                b_idx = futures[future]
                try:
                    batch_results[b_idx] = future.result()
                    completed += 1
                    if completed % 50 == 0 or completed == len(batches):
                        print(f"[EMBEDDING] 进度 {completed}/{len(batches)} 批次完成")
                except Exception as e:
                    print(f"[ERROR] Embedding 批次 {b_idx} 失败: {e}")
                    raise

        all_new_embeddings = []
        for res in batch_results:
            all_new_embeddings.extend(res)

        new_embeddings = np.array(all_new_embeddings, dtype=np.float32)
        norms = np.linalg.norm(new_embeddings, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        new_embeddings = new_embeddings / norms

        for emb_key, emb in zip(to_fetch, new_embeddings):
            cache[emb_key] = emb
    else:
        print(f"[EMBEDDING] 全部 {n} 个向量已缓存，跳过 API 请求")

    embeddings = np.stack([cache[item.embedding_text()] for item in unique_items])

    print(f"[EMBEDDING] 向量就绪，开始分块计算相似度并聚类（含约束检查）...")

    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[ry] = rx

    row_chunk = min(512, n)
    total_pairs = 0
    blocked_pairs = 0
    for start in range(0, n, row_chunk):
        end = min(start + row_chunk, n)
        chunk_sim = embeddings[start:end] @ embeddings.T
        rows_idx, cols_idx = np.where(chunk_sim >= threshold)
        upper = cols_idx > (start + rows_idx)
        rows_idx, cols_idx = rows_idx[upper], cols_idx[upper]
        for ri, ci in zip(rows_idx.tolist(), cols_idx.tolist()):
            item_a = unique_items[start + ri]
            item_b = unique_items[ci]
            if not _constraints_compatible(item_a.constraints, item_b.constraints):
                blocked_pairs += 1
                continue
            union(start + ri, ci)
            total_pairs += 1
        if end % 2000 == 0 or end == n:
            print(
                f"[EMBEDDING] 相似度计算进度 {end}/{n}，"
                f"已合并 {total_pairs} 对，约束拦截 {blocked_pairs} 对"
            )
    print(
        f"[EMBEDDING] 共合并 {total_pairs} 对相似主题，"
        f"约束拦截 {blocked_pairs} 对，连通分量完成"
    )

    clusters: Dict[int, List[SubjectItem]] = {}
    for idx, item in enumerate(unique_items):
        root = find(idx)
        clusters.setdefault(root, []).append(item)

    print(f"[EMBEDDING] 聚类完成，共 {len(clusters)} 个簇")
    return list(clusters.values())


# --------------------------- 速率控制 ---------------------------
_api_semaphore = threading.Semaphore(MAX_WORKERS)


def _rate_limited_invoke(messages, max_tokens: int = 2200):
    with _api_semaphore:
        result = chat.invoke(messages, max_tokens=max_tokens)
        return result


# --------------------------- Prompt 构造 ---------------------------
SYSTEM_MESSAGE = """你是 Amazon 运营专家，负责判断主题是否能合并为同一商品变体。

判断标准：如果这些主题对应的产品出现在同一个 Amazon 搜索结果页，买家会认为它们是同一种商品的不同变体吗？如果不是，绝对不能合并。

硬约束（必须严格遵守）：
- 年份不同（如 2025 vs 2026）→ 禁止合并
- 年龄段不同（如 6岁 vs 8岁）→ 禁止合并
- 具体组织/品牌/实体不同（如 UTLA vs SEIU）→ 禁止合并
- 受众不同（如面向成人的 Launch 纪念主题 vs 面向儿童的 Cute Panda 主题）→ 禁止合并
- 职业不同（如 Teacher vs Nurse）→ 禁止合并

核心原则：
- 以英文原文(en)为主要判断依据，中文翻译(zh)仅作辅助参考
- 即使中文翻译相似，如果英文原文显示是不同的实体或受众，也必须保留为独立项
- 宁可不合并，也不能错合并
- 只输出 originals 数量 >= 2 的合并项
- 输出严格合法 JSON"""

BATCH_PROMPT_TEMPLATE = """将以下 {count} 个 Amazon 主题进行语义归并。

每个主题包含英文原文(en)、中文翻译(zh)和 ASIN。请以英文原文为主要判断依据，中文翻译作为辅助参考。

判断标准：这些主题对应的产品，买家会认为是同一种商品的不同变体吗？

待归并主题列表（共 {count} 条）：
{subjects}

输出严格合法 JSON：
```json
{{
  "merged_themes": [
    {{
      "canonical": "合并后的主题名（中文）",
      "originals": ["asin1", "asin2"],
      "reason": "简述为什么这些主题可以合并为同一变体（1-2句话）"
    }}
  ]
}}
```

只输出成功合并的项（originals 长度 >= 2），独立项不要输出。"""


def _clean_llm_response(raw: str) -> str:
    raw = raw.strip()
    raw = re.sub(r"<think[^>]*>.*?</think\s*>", "", raw, flags=re.DOTALL)
    raw = raw.strip()
    first_brace = raw.find("{")
    last_brace = raw.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        raw = raw[first_brace : last_brace + 1]
    raw = raw.strip("`")
    if raw.lower().startswith("json"):
        raw = raw[4:].strip()
    return raw


def _format_subjects_for_llm(items: List[SubjectItem]) -> str:
    lines = []
    for i, item in enumerate(items, 1):
        obj = {"en": item.en, "zh": item.zh, "asin": item.asin}
        lines.append(f"{i}. {json.dumps(obj, ensure_ascii=False)}")
    return "\n".join(lines)


def call_llm_merge(
    items: List[SubjectItem],
    retry: int = 3,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    if not items:
        return [], []

    input_asins = set(item.asin for item in items)
    content = _format_subjects_for_llm(items)
    prompt = BATCH_PROMPT_TEMPLATE.format(count=len(items), subjects=content)
    max_tokens = _estimate_max_tokens(items)

    messages = [
        SystemMessage(content=SYSTEM_MESSAGE),
        HumanMessage(content=prompt),
    ]

    for attempt in range(retry):
        try:
            response = _rate_limited_invoke(messages, max_tokens=max_tokens)
            raw = _clean_llm_response(response.content)
            data = json.loads(raw)
            merged = data.get("merged_themes", [])

            used_asins = set()
            for item_result in merged:
                origs = item_result.get("originals", [])
                if isinstance(origs, list):
                    for o in origs:
                        used_asins.add(str(o).strip())

            missing = input_asins - used_asins
            if missing:
                print(f"[WARN] LLM 遗漏 {len(missing)} 个 ASIN，由外层作为独立项处理")

            actual_merge_count = sum(
                1 for item_result in merged if len(item_result.get("originals", [])) > 1
            )
            print(
                f"[LLM] 批次完成 | 输入 {len(items)} 个主题 | "
                f"输出 {len(merged)} 个 canonical | "
                f"其中 {actual_merge_count} 组发生合并 | "
                f"遗漏 {len(missing)} 个独立项"
            )
            return merged, list(missing)

        except Exception as e:
            wait = 2**attempt
            print(f"[ERROR] 尝试 {attempt + 1}/{retry}: {e}，{wait}s 后重试...")
            if attempt < retry - 1:
                time.sleep(wait)

    print(f"[ERROR] 批次最终失败，{len(items)} 个主题交由外层兜底")
    failed_asins = [item.asin for item in items]
    return [], failed_asins


def _merge_one_batch(args):
    idx, total, batch = args
    print(f"[BATCH] 启动批次 {idx}/{total}")
    result, failed_asins = call_llm_merge(batch)
    print(
        f"[BATCH] 完成批次 {idx}/{total}，"
        f"输出 {len(result)} 个主题，失败 {len(failed_asins)} 个"
    )
    return result, failed_asins


# --------------------------- Layer Merge（核心） ---------------------------
def layer_merge(
    items: List[SubjectItem],
    item_pool: Dict[str, SubjectItem],
    batch_size: int = BATCH_SIZE,
    embedding_threshold: float = LAYER1_EMBEDDING_THRESHOLD,
    _cache: Optional[Dict[str, np.ndarray]] = None,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    if not items:
        return [], []

    valid_items, noise_items = _filter_noise_items(items)

    local_merged, remaining = _preprocess_subjects(valid_items, item_pool)

    clusters = _cluster_by_embedding(
        remaining, threshold=embedding_threshold, _cache=_cache
    )

    cluster_batches: List[List[SubjectItem]] = []
    for cluster in clusters:
        if len(cluster) <= 1:
            continue
        elif len(cluster) <= batch_size:
            cluster_batches.append(cluster)
        else:
            for i in range(0, len(cluster), batch_size):
                chunk = cluster[i : i + batch_size]
                if len(chunk) > 1:
                    cluster_batches.append(chunk)

    all_merged: List[Dict[str, Any]] = []
    all_failed_asins: List[str] = []

    for merge_item in local_merged:
        all_merged.append(merge_item)

    for noise_item in noise_items:
        all_merged.append(
            {
                "canonical": noise_item.zh or noise_item.en,
                "asin_list": [noise_item.asin],
            }
        )

    for cluster in clusters:
        if len(cluster) == 1:
            single = cluster[0]
            all_merged.append(
                {
                    "canonical": single.zh or single.en,
                    "asin_list": [single.asin],
                }
            )

    total_batches = len(cluster_batches)
    if total_batches == 0:
        print(
            f"[LAYER] 本地合并 {len(local_merged)} 组 | "
            f"Embedding 聚类 {len(clusters)} 簇 | "
            f"无 LLM batch | 噪声 {len(noise_items)} 个"
        )
        return all_merged, all_failed_asins

    print(
        f"[LAYER] 本地合并 {len(local_merged)} 组 | "
        f"Embedding 聚类 {len(clusters)} 簇 → 切分为 {total_batches} 个 batch | "
        f"噪声 {len(noise_items)} 个"
    )

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {}
        for idx, batch in enumerate(cluster_batches, 1):
            future = executor.submit(_merge_one_batch, (idx, total_batches, batch))
            futures[future] = (idx, total_batches, batch)

        for future in as_completed(futures):
            batch_idx, batch_total, batch_items = futures[future]
            try:
                result, failed_asins = future.result()
                all_merged.extend(result)
                all_failed_asins.extend(failed_asins)
                _print_batch_summary(batch_idx, batch_total, result)
            except Exception as e:
                print(f"[BATCH {batch_idx}] 运行时异常: {e}")
                batch_asins = [item.asin for item in batch_items]
                all_failed_asins.extend(batch_asins)

    return all_merged, all_failed_asins


def _print_batch_summary(idx, total, result):
    actual_merges = [item for item in result if len(item.get("originals", [])) > 1]
    single_items = [item for item in result if len(item.get("originals", [])) <= 1]

    print(f"\n" + "·" * 40)
    print(f"[BATCH {idx}/{total}] 实时快照")
    print(
        f"  - 总输出组数: {len(result)} "
        f"(合并项: {len(actual_merges)} | 独立项: {len(single_items)})"
    )

    if actual_merges:
        print(f"  - 合并细节 (展示前 5 条):")
        for i, item in enumerate(actual_merges[:5], 1):
            canon = item.get("canonical", "")
            origs = item.get("originals", [])
            reason = item.get("reason", "")
            print(
                f"    {i}. {canon} <--- "
                f"[{', '.join(str(o) for o in origs[:3])}"
                f"{'...' if len(origs) > 3 else ''}]"
            )
            if reason:
                print(f"       原因: {reason}")

    if not actual_merges and not single_items:
        print(f"  - 该 Batch 返回结果为空")

    print("·" * 40 + "\n")


# --------------------------- 断点续传 ---------------------------
def _save_checkpoint(
    layer: int,
    upstream_map: Dict[str, Set[str]],
    current_items: List[str],
    all_failed: List[str],
    item_pool: Dict[str, SubjectItem],
) -> None:
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    path = CHECKPOINT_DIR / f"layer_{layer}.json"
    data = {
        "version": CHECKPOINT_VERSION,
        "upstream_map": {k: sorted(v) for k, v in upstream_map.items()},
        "current_items": current_items,
        "all_failed": sorted(all_failed),
        "item_pool": {asin: si.to_dict() for asin, si in item_pool.items()},
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"[CHECKPOINT] Layer {layer} 中间结果已保存到 {path}")


def _load_checkpoint(
    layer: int,
) -> Optional[Tuple[Dict[str, Set[str]], List[str], List[str], Dict[str, SubjectItem]]]:
    path = CHECKPOINT_DIR / f"layer_{layer}.json"
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if data.get("version") != CHECKPOINT_VERSION:
            print(
                f"[CHECKPOINT] Layer {layer} 版本不匹配"
                f"（期望 {CHECKPOINT_VERSION}，实际 {data.get('version')}），忽略"
            )
            return None
        upstream_map = {k: set(v) for k, v in data.get("upstream_map", {}).items()}
        current_items = data.get("current_items", [])
        all_failed = data.get("all_failed", [])
        item_pool = {
            asin: SubjectItem.from_dict(d)
            for asin, d in data.get("item_pool", {}).items()
        }
        print(f"[CHECKPOINT] 从 {path} 恢复 Layer {layer} 数据")
        return upstream_map, current_items, all_failed, item_pool
    except Exception as e:
        print(f"[CHECKPOINT] 加载 Layer {layer} 失败: {e}，忽略")
        return None


def _clear_checkpoints() -> None:
    if CHECKPOINT_DIR.exists():
        for f in CHECKPOINT_DIR.glob("*.json"):
            f.unlink()
        print("[CHECKPOINT] 已清理所有断点文件")


def _list_checkpoint_layers() -> List[int]:
    if not CHECKPOINT_DIR.exists():
        return []
    layers = []
    for f in CHECKPOINT_DIR.glob("layer_*.json"):
        try:
            num = int(f.stem.replace("layer_", ""))
            layers.append(num)
        except ValueError:
            pass
    return sorted(layers)


# --------------------------- 递归分层归并 ---------------------------
def _expand_map(
    direct_map: Dict[str, Set[str]], upstream_map: Dict[str, Set[str]]
) -> Dict[str, Set[str]]:
    expanded = {}
    for c, asins in direct_map.items():
        originals = set()
        for a in asins:
            originals.update(upstream_map.get(a, {a}))
        expanded[c] = originals
    return expanded


def _check_further_merge_needed(canonicals: List[str], prev_count: int) -> bool:
    if len(canonicals) <= 1:
        return False
    if len(canonicals) >= prev_count:
        return False
    reduction = prev_count - len(canonicals)
    reduction_rate = reduction / prev_count if prev_count > 0 else 0
    print(
        f"[MERGE-CHECK] 本层 {prev_count} → {len(canonicals)}，"
        f"缩减 {reduction} 个 ({reduction_rate:.1%})"
    )
    if reduction < MIN_LAYER_REDUCTION:
        print(f"[MERGE-CHECK] 缩减量 < {MIN_LAYER_REDUCTION}，停止归并")
        return False
    return True


def recursive_merge(
    unique_items: List[SubjectItem],
    item_pool: Dict[str, SubjectItem],
    dedup_asins: Dict[str, List[str]],
    resume: bool = False,
    embedding_cache: Optional[Dict[str, np.ndarray]] = None,
) -> Dict[str, Set[str]]:
    upstream_map: Dict[str, Set[str]] = {}
    all_failed: List[str] = []
    cache = embedding_cache if embedding_cache is not None else {}
    layer = 1

    if resume:
        saved_layers = _list_checkpoint_layers()
        if saved_layers:
            latest_layer = saved_layers[-1]
            cp = _load_checkpoint(latest_layer)
            if cp:
                upstream_map, current_canonicals, all_failed, loaded_pool = cp
                item_pool.update(loaded_pool)
                current_items = [
                    item_pool[asin] for asin in current_canonicals if asin in item_pool
                ]
                layer = latest_layer + 1
                print(
                    f"[RESUME] 从 Layer {layer} 继续，"
                    f"{len(current_items)} 个待处理，"
                    f"{len(upstream_map)} 个已映射"
                )
            else:
                current_items = unique_items
        else:
            current_items = unique_items
    else:
        current_items = unique_items

    while True:
        print(
            f"\n========== Layer {layer} | 输入 {len(current_items)} 个主题 =========="
        )
        prev_count = len(current_items)
        if layer == 1:
            merged, failed_asins = layer_merge(
                current_items,
                item_pool,
                batch_size=BATCH_SIZE,
                embedding_threshold=LAYER1_EMBEDDING_THRESHOLD,
                _cache=cache,
            )
        else:
            print(f"[LAYER] 使用提高的 embedding 阈值 {LAYER2_EMBEDDING_THRESHOLD}")
            merged, failed_asins = layer_merge(
                current_items,
                item_pool,
                batch_size=BATCH_SIZE,
                embedding_threshold=LAYER2_EMBEDDING_THRESHOLD,
                _cache=cache,
            )
        all_failed.extend(failed_asins)

        for fa in failed_asins:
            if fa in item_pool:
                si = item_pool[fa]
                merged.append(
                    {
                        "canonical": si.zh or si.en,
                        "asin_list": [fa],
                    }
                )

        direct_map: Dict[str, Set[str]] = {}
        for item_result in merged:
            c = str(item_result.get("canonical", "")).strip()
            asin_list = item_result.get("asin_list", [])
            if not asin_list:
                origs = item_result.get("originals", [])
                if isinstance(origs, list):
                    asin_list = [str(o).strip() for o in origs if str(o).strip()]
            if c and asin_list:
                direct_map[c] = set(asin_list)

        if layer == 1:
            upstream_map = {}
            for c, asins in direct_map.items():
                expanded = set()
                for a in asins:
                    if a in dedup_asins:
                        expanded.update(dedup_asins[a])
                    else:
                        expanded.add(a)
                upstream_map[c] = expanded
        else:
            upstream_map = _expand_map(direct_map, upstream_map)

        canonicals = list(upstream_map.keys())
        print(f"[INFO] Layer {layer} 去重后得到 {len(canonicals)} 个 canonical 主题")

        _save_checkpoint(layer, upstream_map, canonicals, all_failed, item_pool)

        if layer >= 2:
            print(f"[INFO] Layer 2 已完成，强制停止归并")
            result = {}
            for c, asins in upstream_map.items():
                result[c] = asins
            for fa in all_failed:
                if fa not in result:
                    result[fa] = {fa}
            _clear_checkpoints()
            return result

        print(f"[INFO] Layer 1 完成，进入 Layer 2 进行独立项挂靠")

        next_items = []
        for c in canonicals:
            asins = upstream_map[c]
            rep_asin = next(iter(asins))
            if rep_asin in item_pool:
                rep_item = item_pool[rep_asin]
                next_items.append(rep_item)
            else:
                print(
                    f"[WARN] canonical '{c}' 的代表 ASIN '{rep_asin}' 不在 item_pool 中"
                )

        current_items = next_items
        layer += 1


# --------------------------- 数据库写入 ---------------------------
def persist_results(final_map: Dict[str, Set[str]]) -> None:
    total = len(final_map)
    print(f"\n[INFO] 开始写入数据库，共 {total} 个最终主题")

    canonicals = [c for c in final_map if c]
    existing_summaries = ThemeNoveltySummary.objects.filter(
        summary_subject_title__in=canonicals
    )
    summary_cache = {s.summary_subject_title: s for s in existing_summaries}

    missing_canonicals = [c for c in canonicals if c not in summary_cache]
    if missing_canonicals:
        new_objs = [
            ThemeNoveltySummary(
                summary_subject_title=c,
                created_time=timezone.now(),
            )
            for c in missing_canonicals
        ]
        ThemeNoveltySummary.objects.bulk_create(new_objs, ignore_conflicts=True)
        for s in ThemeNoveltySummary.objects.filter(
            summary_subject_title__in=missing_canonicals
        ):
            summary_cache[s.summary_subject_title] = s

    update_tasks: List[Tuple[List[str], int]] = []
    for canonical, asin_set in final_map.items():
        if not canonical or not asin_set:
            continue
        summary_obj = summary_cache.get(canonical)
        if not summary_obj:
            print(f"[WARN] 未找到 canonical '{canonical}' 的 Summary 记录，跳过")
            continue
        asin_list = list(asin_set)
        for i in range(0, len(asin_list), UPDATE_CHUNK_SIZE):
            chunk = asin_list[i : i + UPDATE_CHUNK_SIZE]
            update_tasks.append((chunk, summary_obj.pk))

    def _do_update(task: Tuple[List[str], int]) -> int:
        asin_chunk, summary_pk = task
        return AmazonThemeNovelty.objects.filter(asin__in=asin_chunk).update(
            theme_novelty_summary_id=summary_pk
        )

    total_updated = 0
    print(f"[DB] 共 {len(update_tasks)} 个更新任务，开始并发执行...")
    with ThreadPoolExecutor(max_workers=min(10, len(update_tasks) or 1)) as executor:
        futures = {executor.submit(_do_update, task): task for task in update_tasks}
        done_count = 0
        for future in as_completed(futures):
            done_count += 1
            try:
                total_updated += future.result()
            except Exception as e:
                asin_chunk, _ = futures[future]
                print(f"[ERROR] DB 更新失败 ({len(asin_chunk)} 个 ASIN): {e}")
            if done_count % 200 == 0 or done_count == len(update_tasks):
                print(
                    f"[DB] 进度 {done_count}/{len(update_tasks)}，"
                    f"已更新 {total_updated} 行"
                )

    print(f"[DB] 共更新 {total_updated} 行")
    print("[INFO] 数据库写入完成")


# --------------------------- 主流程 ---------------------------
def main():
    parser = argparse.ArgumentParser(description="subject_translation 语义归并（v2）")
    parser.add_argument(
        "--full", action="store_true", help="全量重新归并（默认增量模式）"
    )
    parser.add_argument("--resume", action="store_true", help="从断点续传")
    args = parser.parse_args()

    incremental = not args.full

    unique_items, item_pool, dedup_asins = fetch_distinct_subjects(
        incremental=incremental
    )
    if not unique_items:
        print("[WARN] 没有获取到待处理的 subject，脚本退出。")
        return

    print(f"[INFO] 待处理 {len(item_pool)} 个 ASIN，{len(unique_items)} 个唯一主题对")

    if args.resume:
        print("[INFO] 断点续传模式启动")

    final_map = recursive_merge(
        unique_items, item_pool, dedup_asins, resume=args.resume
    )
    if not final_map:
        print("[WARN] 归并未产生任何结果，脚本退出。")
        return

    print(f"\n[INFO] 最终归并出 {len(final_map)} 个主题")

    persist_results(final_map)

    total_asins = sum(len(v) for v in final_map.values())
    print(f"\n[SUCCESS] 语义归并并回填完成")
    print(f"  - 唯一主题数: {len(unique_items)}")
    print(f"  - 归并后主题数: {len(final_map)}")
    print(f"  - 涉及 ASIN 数: {total_asins}")


if __name__ == "__main__":
    main()
