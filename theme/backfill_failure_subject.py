"""
重新提炼"识别失败"ASIN的主题并归并回填

功能：
1. 找出 theme_amazon_novelty 中 title_translation='识别失败' 且 subject_translation='识别失败' 的ASIN
2. 使用 qwen-plus 重新提取 subject 并翻译 title/subject
3. 更新 theme_amazon_novelty
4. 将新提炼的主题与现有合法 ThemeNoveltySummary 做靶向归并（复用 merge_subject_translations.py 逻辑，Layer1阈值0.82，Layer2阈值0.70，最多2层）
5. 优先挂靠到现有 Summary，挂不上则新建
6. 更新 theme_novelty_summary 外键
7. 删除"识别失败"Summary

运行：
    python theme/backfill_failure_subject.py
"""

import argparse
import os
import sys
import time
import threading
import numpy as np
from pathlib import Path
from typing import List, Dict, Any, Set, Tuple, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Overlord.settings")

BACKFILL_CHECKPOINT_PATH = Path(__file__).parent / "backfill_failure_checkpoint.json"

import django

django.setup()

from openai import OpenAI
from django.utils import timezone
from theme.models import AmazonThemeNovelty, ThemeNoveltySummary
from theme.merge_subject_translations import (
    recursive_merge,
    embedding_client,
    EMBEDDING_MODEL,
    EMBEDDING_SIMILARITY_THRESHOLD,
    CHECKPOINT_DIR as MERGE_CHECKPOINT_DIR,
)

# --------------------------- 配置 ---------------------------
OPENAI_API_KEY = "sk-c3f9ddb0b5454da2b9db130228049d84"
OPENAI_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
OPENAI_MODEL = "qwen-plus"
MAX_WORKERS = 10
_API_SEMAPHORE = threading.Semaphore(MAX_WORKERS)

client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)


# --------------------------- LLM 调用封装 ---------------------------
def _call_openai(messages, model=OPENAI_MODEL) -> str:
    with _API_SEMAPHORE:
        try:
            response = client.chat.completions.create(model=model, messages=messages)
            content = response.choices[0].message.content
            return content.strip()
        except Exception as e:
            print(f"[ERROR] API调用出错: {e}")
            return "识别失败"


def recognize_text_from_title(title: str) -> str:
    prompt = f"""\"Please extract the core thematic phrase from the product title following these rules:
1. **Structural Analysis**:
- Focus on phrases near product terms but exclude the product word itself
- Ignore product types (Hat/Cap), audiences (Men/Women), colors, materials,specifications and printing-related terms(Print/Printing)
2. **Cultural/Linguistic Features**:
- Preserve complete emotional expressions or humorous phrases
- Maintain cultural references/puns in their original phrase structures
3. **Selection Criteria**:
- When multiple candidates exist:
a) Choose longer phrases
b) Prioritize semantically concrete/complete expressions
c) Prefer complete sentence segments
4. **Final Validation**:
- Remove any remaining product terms before output
Examples:
Title: The Sao Tome and Principe Flag and Freedom Baseball Cap for Men Women Adjustable Breathable Mesh Trucker Hat Unisex
Extract: The Sao Tome and Principe Flag and Freedom

Title: Nufar I Don't Need Therapy I Have My Sister 11oz Fun Coffee Mugs Novelty Ceramics Cup
Extract: I Don't Need Therapy I Have My Sister
Now process this title: {title}
Output only the final English phrase without explanations"""
    messages = [{"role": "user", "content": prompt}]
    return _call_openai(messages)


def translate_subject(subject: str) -> str:
    prompt = f""""# 角色设定
你是一位专业的亚马逊电商运营专家，专门负责产品主题标签的本地化翻译。

# 任务说明
请将以下亚马逊产品主题标签/关键词从英文翻译成中文。这些通常是：
- 产品主题标签（如节日、季节、活动主题）
- 产品风格关键词
- 目标人群标签
- 使用场景标签

# 翻译原则

## 核心要求：
1. **保持简洁**：中文表达要简短有力，控制在3-10个字
2. **准确传达主题**：完整表达原文的主题概念
3. **符合中文标签习惯**：使用中文用户熟悉的表达方式
4. **保留关键信息**：不丢失任何重要的主题元素

## 具体规则：

### A. 节日/季节主题：
- 准确翻译节日名称
- 保留节日氛围
- 符合中文节日表达习惯
- 例如：Valentine's Day → 情人节主题

### B. 情感/风格主题：
- 准确传达情感色彩
- 使用地道中文表达
- 保持风格一致性
- 例如：Romantic Love → 浪漫爱情

### C. 事件/活动主题：
- 准确翻译事件名称
- 保留事件特殊性
- 添加"主题"或"风格"后缀（如适用）
- 例如：Super Bowl → 超级碗主题

### D. 人群/场景主题：
- 准确描述目标人群
- 清晰表达使用场景
- 使用市场常用术语

## 翻译示例参考：

### 输入示例：
1. "Christmas Family Reunion Theme"
2. "Beach Summer Vacation Style"
3. "Gamer RGB Lighting Setup"
4. "Office Professional Business"

### 输出示例：
1. "圣诞家庭团圆主题"
2. "海滩夏日度假风"
3. "游戏玩家RGB光效"
4. "办公商务专业款"

## 特别注意：
1. **专有名词处理**：
   - 球队名、赛事名：保留核心意思，简短翻译
   - 地名：标准中文译名
   - 品牌名：一般不翻译

2. **文化适配**：
   - 西方节日要准确但符合中文习惯
   - 体育赛事用中国用户熟悉的表达
   - 避免直译造成的生硬感

3. **格式要求**：
   - 每行一个翻译结果
   - 不加引号
   - 不加解释说明
   - 保持原始顺序
   - 不要出现英文
   - 不要出现如 "\n" 等特殊字符

## 待翻译的主题标签：
{subject}

## 请开始翻译："""
    messages = [{"role": "user", "content": prompt}]
    result = _call_openai(messages)
    return result.replace("\n", "")


def translate_title(title: str) -> str:
    prompt = f"""# 角色设定
你是一名经验丰富的亚马逊跨境电商运营专家，专门负责产品标题的本地化翻译。

# 任务说明
请将以下亚马逊产品标题从英文翻译成中文。这些标题通常包含：
1. 产品类型（T-Shirt, Hoodie, Dress等）
2. 目标人群（Women's, Men's, Kids, Baby等）
3. 设计主题/图案
4. 产品特性（材质、款式、尺寸等）
5. 品牌/授权信息

# 翻译原则

## 核心要求：
1. **信息完整性**：保留原文所有关键信息
2. **准确性第一**：技术规格、尺寸、材质必须100%准确
3. **符合中文标题结构**：使用"人群+主题+特性+产品类型"结构
4. **可读性强**：中文表达自然流畅，符合电商标题习惯

# 格式要求：
1. 不加引号
2. 直接输出中文标题

# 待翻译标题：
{title}

# 中文标题："""
    messages = [{"role": "user", "content": prompt}]
    result = _call_openai(messages)
    return result.replace("\n", "")


# --------------------------- 步骤1: 查询未聚合ASIN ---------------------------
def fetch_unsummarized_asins(
    resume: bool = False,
) -> Tuple[List[AmazonThemeNovelty], List[AmazonThemeNovelty]]:
    """
    查询 theme_novelty_summary 为 NULL 的 ASIN，分成两组返回：
    - 需要重新提炼的（subject_translation='识别失败'）
    - 已有合法 subject_translation 的（直接复用）
    """
    if resume:
        from django.db.models import Q

        qs = AmazonThemeNovelty.objects.filter(
            Q(theme_novelty_summary__isnull=True)
            | Q(theme_novelty_summary__summary_subject_title="识别失败")
        ).exclude(
            title_translation="识别失败",
            subject_translation="识别失败",
        )
        print(
            f"[INFO] 断点续传模式：共找到 {qs.count()} 个已提炼但未回填 Summary 的 ASIN"
        )
        return [], list(qs)

    base_qs = AmazonThemeNovelty.objects.filter(theme_novelty_summary__isnull=True)
    need_extract = list(base_qs.filter(subject_translation="识别失败"))
    direct_use = list(
        base_qs.exclude(subject_translation="识别失败")
        .exclude(subject_translation__isnull=True)
        .exclude(subject_translation="")
    )
    print(f"[INFO] 共找到 {base_qs.count()} 个未聚合 ASIN")
    print(f"  - 需要重新提炼: {len(need_extract)} 个")
    print(f"  - 已有合法主题直接归并: {len(direct_use)} 个")
    return need_extract, direct_use


# --------------------------- 步骤2: 单条ASIN重新提炼 ---------------------------
def process_single_asin(asin_obj: AmazonThemeNovelty) -> Tuple[str, str, str]:
    title = asin_obj.title or ""
    if not title:
        return "", "", ""

    subject_en = recognize_text_from_title(title)
    if subject_en == "识别失败" or not subject_en:
        return "识别失败", "识别失败", "识别失败"

    title_cn = translate_title(title)
    subject_cn = translate_subject(subject_en)

    return title_cn, subject_en, subject_cn


def re_extract_and_update(
    asin_objs: List[AmazonThemeNovelty],
) -> List[AmazonThemeNovelty]:
    """并发重新提炼并更新数据库，返回成功提取的ASIN对象列表"""
    total = len(asin_objs)
    success_objs: List[AmazonThemeNovelty] = []
    updated_count = 0

    print(f"[INFO] 开始并发重新提炼 {total} 个 ASIN...")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_asin = {
            executor.submit(process_single_asin, obj): obj for obj in asin_objs
        }
        for idx, future in enumerate(as_completed(future_to_asin), 1):
            obj = future_to_asin[future]
            try:
                title_cn, subject_en, subject_cn = future.result()
                if subject_cn != "识别失败":
                    obj.title_translation = title_cn
                    obj.subject = subject_en
                    obj.subject_translation = subject_cn
                    # 先切断与旧"识别失败"summary的关联
                    obj.theme_novelty_summary = None
                    obj.save(
                        update_fields=[
                            "title_translation",
                            "subject",
                            "subject_translation",
                            "theme_novelty_summary",
                            "updated_at",
                        ]
                    )
                    success_objs.append(obj)
                    updated_count += 1
                else:
                    print(f"[WARN] ASIN {obj.asin} 重新提炼失败")
            except Exception as e:
                print(f"[ERROR] ASIN {obj.asin} 处理异常: {e}")

            if idx % 10 == 0 or idx == total:
                print(f"[INFO] 进度 {idx}/{total}，成功更新 {updated_count} 个")

    print(f"[INFO] 提炼完成，成功更新 {updated_count}/{total} 个 ASIN")
    return success_objs


# --------------------------- 步骤3~5: 靶向归并并回填Summary ---------------------------
def _fetch_embedding_batch(batch: List[str]) -> List[Tuple[str, np.ndarray]]:
    """单次请求获取一批 embedding 并归一化"""
    resp = embedding_client.embeddings.create(model=EMBEDDING_MODEL, input=batch)
    results = []
    for text, emb_data in zip(batch, resp.data):
        emb = np.array(emb_data.embedding, dtype=np.float32)
        norm = np.linalg.norm(emb)
        if norm > 0:
            emb = emb / norm
        results.append((text, emb))
    return results


def _fetch_embeddings_batched(
    texts: List[str], batch_size: int = 10, max_workers: int = 20
) -> Dict[str, np.ndarray]:
    """并发批量获取 embedding 并归一化，返回 {text: normalized_embedding}"""
    batches = [
        (b_idx, texts[i : i + batch_size])
        for b_idx, i in enumerate(range(0, len(texts), batch_size))
    ]
    batch_results: List[Optional[List[Tuple[str, np.ndarray]]]] = [None] * len(batches)
    total_batches = len(batches)

    print(
        f"[EMBEDDING] 共 {len(texts)} 条文本，分 {total_batches} 个 batch，并发 {max_workers} 请求..."
    )

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
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
                if completed % 50 == 0 or completed == total_batches:
                    print(f"[EMBEDDING] 进度 {completed}/{total_batches} 批次完成")
            except Exception as e:
                print(f"[ERROR] Embedding 批次 {b_idx} 失败: {e}")
                raise

    result: Dict[str, np.ndarray] = {}
    for res in batch_results:
        for text, emb in res:
            result[text] = emb
    return result


def find_best_existing_summary(
    canonical: str,
    canonical_emb: np.ndarray,
    existing_map: Dict[str, ThemeNoveltySummary],
    existing_titles: List[str],
    existing_emb_matrix: np.ndarray,
) -> Optional[ThemeNoveltySummary]:
    """通过 exact match 或 embedding 相似度 >= 0.82 寻找最匹配的现有 Summary"""
    canonical_lower = canonical.strip().lower()
    if canonical_lower in existing_map:
        return existing_map[canonical_lower]

    if not existing_map or existing_emb_matrix is None or len(existing_titles) == 0:
        return None

    scores = existing_emb_matrix @ canonical_emb
    best_idx = int(np.argmax(scores))
    best_score = float(scores[best_idx])
    best_summary = existing_map[existing_titles[best_idx].lower()]

    if best_score >= EMBEDDING_SIMILARITY_THRESHOLD:
        print(
            f"[MATCH] '{canonical}' 通过 embedding 匹配到现有摘要 '{best_summary.summary_subject_title}' (score={best_score:.3f})"
        )
        return best_summary

    return None


def _batch_find_existing_summaries(
    canonicals: List[str],
    existing_map: Dict[str, ThemeNoveltySummary],
    existing_titles: List[str],
    existing_emb_matrix: np.ndarray,
) -> Dict[str, Optional[ThemeNoveltySummary]]:
    """一次性批量获取所有 canonical 的 embedding，用矩阵乘法批量匹配，返回 {canonical: summary_or_none}"""
    result: Dict[str, Optional[ThemeNoveltySummary]] = {}
    need_embed: List[str] = []

    for c in canonicals:
        c_lower = c.strip().lower()
        if c_lower in existing_map:
            result[c] = existing_map[c_lower]
        else:
            result[c] = None
            need_embed.append(c)

    if not need_embed or not existing_map or len(existing_titles) == 0:
        return result

    print(f"[EMBEDDING] 批量获取 {len(need_embed)} 个新 canonical 的 embedding...")
    canonical_emb_map = _fetch_embeddings_batched(need_embed, batch_size=10)
    canonical_list = list(canonical_emb_map.keys())
    if not canonical_list:
        return result
    canonical_emb_matrix = np.stack([canonical_emb_map[c] for c in canonical_list])

    sim_matrix = canonical_emb_matrix @ existing_emb_matrix.T
    best_indices = np.argmax(sim_matrix, axis=1)
    best_scores = sim_matrix[np.arange(len(canonical_list)), best_indices]

    matched_count = 0
    for i, c in enumerate(canonical_list):
        if best_scores[i] >= EMBEDDING_SIMILARITY_THRESHOLD:
            summary_obj = existing_map[existing_titles[best_indices[i]].lower()]
            result[c] = summary_obj
            matched_count += 1
        else:
            result[c] = None

    print(
        f"[EMBEDDING] 批量匹配完成：{matched_count}/{len(canonical_list)} 个新 canonical 成功挂靠现有 Summary"
    )
    return result


def merge_and_persist(
    success_objs: List[AmazonThemeNovelty], resume: bool = False
) -> None:
    if not success_objs:
        print("[WARN] 没有成功提炼的 ASIN，跳过归并步骤")
        return

    # 收集新主题
    new_subjects = sorted(
        {
            obj.subject_translation.strip()
            for obj in success_objs
            if obj.subject_translation and obj.subject_translation.strip()
        }
    )
    print(f"[INFO] 新提炼出不重复主题 {len(new_subjects)} 个")

    # 加载现有合法 Summary（不含"识别失败"）
    existing_summaries = list(
        ThemeNoveltySummary.objects.exclude(summary_subject_title="识别失败")
    )
    existing_titles = [
        s.summary_subject_title.strip()
        for s in existing_summaries
        if s.summary_subject_title and s.summary_subject_title.strip()
    ]
    existing_map = {
        s.summary_subject_title.strip().lower(): s for s in existing_summaries
    }
    print(f"[INFO] 现有合法 Summary {len(existing_titles)} 个")

    # 预缓存所有现有 Summary 标题的 embedding（避免循环内重复请求）
    print(f"[INFO] 开始预缓存 {len(existing_titles)} 个现有 Summary 的 embedding...")
    existing_embeddings = _fetch_embeddings_batched(existing_titles, batch_size=10)
    # 构建 numpy 矩阵用于批量点积，避免 3800 万次 Python 循环
    existing_title_list = existing_titles
    if existing_title_list:
        existing_emb_matrix = np.stack(
            [existing_embeddings[t] for t in existing_title_list]
        )
    else:
        existing_emb_matrix = np.empty((0, 1024), dtype=np.float32)
    print(f"[INFO] 预缓存完成")

    if resume:
        # 优先读取本脚本专属的 checkpoint（不会被 _clear_checkpoints 清理）
        if BACKFILL_CHECKPOINT_PATH.exists():
            import json

            with open(BACKFILL_CHECKPOINT_PATH, "r", encoding="utf-8") as f:
                checkpoint_data = json.load(f)
            upstream_map = checkpoint_data.get("upstream_map", {})
            final_map = {k: set(v) for k, v in upstream_map.items()}
            print(
                f"[RESUME] 从 {BACKFILL_CHECKPOINT_PATH} 加载归并结果，共 {len(final_map)} 个 canonical"
            )
        else:
            print(
                f"[WARN] 未找到断点文件 {BACKFILL_CHECKPOINT_PATH}，回退到正常归并流程"
            )
            resume = False

    if not resume:
        # 组合输入：新主题 + 现有 Summary 标题
        combined_subjects = list(dict.fromkeys(new_subjects + existing_titles))
        print(
            f"[INFO] 开始靶向归并，输入总数 {len(combined_subjects)}（新主题 {len(new_subjects)} + 现有摘要 {len(existing_titles)}）"
        )

        # 调用 recursive_merge（已内置 Layer2 阈值 0.70，最多2层）
        final_map = recursive_merge(
            combined_subjects, embedding_cache=existing_embeddings
        )
        print(f"[INFO] 归并完成，最终得到 {len(final_map)} 个 canonical")

        # 保存专属 checkpoint，防止被 recursive_merge 的 _clear_checkpoints 清理掉
        import json

        with open(BACKFILL_CHECKPOINT_PATH, "w", encoding="utf-8") as f:
            json.dump(
                {"upstream_map": {k: list(v) for k, v in final_map.items()}},
                f,
                ensure_ascii=False,
                indent=2,
            )
        print(f"[CHECKPOINT] 归并结果已保存到 {BACKFILL_CHECKPOINT_PATH}")

    # 构建 original -> canonical 映射
    original_to_canonical: Dict[str, str] = {}
    for canonical, originals in final_map.items():
        for orig in originals:
            original_to_canonical[orig.strip()] = canonical.strip()

    # 一次性批量匹配所有 canonical，替代逐个串行请求
    canonical_list = list(final_map.keys())
    total_canonicals = len(canonical_list)
    print(f"[INFO] 开始批量匹配 {total_canonicals} 个 canonical 到现有 Summary...")
    batch_match = _batch_find_existing_summaries(
        canonical_list, existing_map, existing_title_list, existing_emb_matrix
    )

    canonical_to_summary: Dict[str, ThemeNoveltySummary] = {}
    for idx, canonical in enumerate(canonical_list, 1):
        summary_obj = batch_match.get(canonical)
        if summary_obj:
            canonical_to_summary[canonical] = summary_obj
            existing_map[canonical.strip().lower()] = summary_obj
        else:
            summary_obj, _ = ThemeNoveltySummary.objects.get_or_create(
                summary_subject_title=canonical,
                defaults={"created_time": timezone.now()},
            )
            canonical_to_summary[canonical] = summary_obj
            existing_map[canonical.strip().lower()] = summary_obj
            print(f"[NEW] 新建 Summary: '{canonical}'")

        if idx % 500 == 0 or idx == total_canonicals:
            print(f"[INFO] Summary 匹配进度 {idx}/{total_canonicals}")

    # 按 canonical 分组 ASIN，批量更新外键
    canonical_to_asins: Dict[str, List[AmazonThemeNovelty]] = {}
    for obj in success_objs:
        subj = obj.subject_translation.strip()
        canon = original_to_canonical.get(subj)
        if not canon:
            print(f"[WARN] ASIN {obj.asin} 的主题 '{subj}' 未在归并结果中找到映射")
            continue
        canonical_to_asins.setdefault(canon, []).append(obj)

    total_updated = 0
    for canonical, asin_list in canonical_to_asins.items():
        summary_obj = canonical_to_summary[canonical]
        asin_values = [obj.asin for obj in asin_list]
        # 批量更新
        updated = AmazonThemeNovelty.objects.filter(asin__in=asin_values).update(
            theme_novelty_summary=summary_obj
        )
        total_updated += updated
        print(
            f"[DB] canonical='{canonical}' | 关联 ASIN {len(asin_list)} 个 | 更新行数 {updated}"
        )

    print(f"[INFO] 共更新 {total_updated} 个 ASIN 的 theme_novelty_summary")

    # 删除"识别失败" Summary
    deleted_count, _ = ThemeNoveltySummary.objects.filter(
        summary_subject_title="识别失败"
    ).delete()
    print(f"[INFO] 删除 '识别失败' Summary {deleted_count} 条")

    # 清理本脚本专属 checkpoint
    if BACKFILL_CHECKPOINT_PATH.exists():
        BACKFILL_CHECKPOINT_PATH.unlink()
        print(f"[INFO] 清理 checkpoint 文件 {BACKFILL_CHECKPOINT_PATH}")


# --------------------------- 主流程 ---------------------------
def main():
    parser = argparse.ArgumentParser(description="重新提炼未聚合ASIN主题并归并回填")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="从断点续传（跳过LLM提炼和归并，直接做Summary匹配回填）",
    )
    args = parser.parse_args()

    # 1. 拉取未聚合 ASIN
    need_extract, direct_use = fetch_unsummarized_asins(resume=args.resume)

    if args.resume:
        if not direct_use:
            print("[INFO] 没有需要处理的 ASIN，脚本退出")
            return
        print(
            f"[INFO] 断点续传模式：跳过重新提炼，直接加载 {len(direct_use)} 个已提炼的 ASIN"
        )
        success_objs = direct_use
    else:
        total = len(need_extract) + len(direct_use)
        if total == 0:
            print("[INFO] 没有需要处理的 ASIN，脚本退出")
            return

        # 2. 重新提炼需要处理的 ASIN
        extracted_objs = re_extract_and_update(need_extract) if need_extract else []
        success_objs = extracted_objs + direct_use
        print(
            f"[INFO] 待归并 ASIN 总数: {len(success_objs)}（重新提炼 {len(extracted_objs)} + 直接复用 {len(direct_use)}）"
        )

    # 3. 靶向归并并回填 Summary
    merge_and_persist(success_objs, resume=args.resume)

    print("\n[SUCCESS] 回填完成")
    if not args.resume:
        print(f"  - 重新提炼 ASIN: {len(need_extract)}")
        print(f"  - 直接复用 ASIN: {len(direct_use)}")
        print(f"  - 成功归并回填: {len(success_objs)}")


if __name__ == "__main__":
    main()
