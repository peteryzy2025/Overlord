"""
Amazon 主题指纹提取 & 拓扑聚类全链路 Pipeline
==============================================
四阶段流水线:
  Stage 1 — N-Gram 动态识别与脱水预处理 → 生成 ThemeFingerprint
  Stage 2 — TF-IDF 全局权重计算
  Stage 3 — 连通分量图算法 (倒排索引 + networkx)
  Stage 4 — 数据聚合与 DB 落盘

唯一外部重型依赖: networkx
"""

import logging
import math
import re
from collections import Counter, defaultdict
from datetime import timedelta
from itertools import combinations

import networkx as nx
from django.db import transaction
from django.utils import timezone

from theme.models import (
    AmazonNewReleaseRank,
    AmazonThemeCluster,
    ThemeFingerprint,
)

logger = logging.getLogger(__name__)

BATCH_SIZE = 2000


# ---------------------------------------------------------------------------
#  自定义停用词表 (不依赖 nltk)
# ---------------------------------------------------------------------------
STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "but",
        "in",
        "on",
        "at",
        "to",
        "for",
        "of",
        "with",
        "by",
        "from",
        "is",
        "it",
        "its",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "shall",
        "should",
        "may",
        "might",
        "can",
        "could",
        "this",
        "that",
        "these",
        "those",
        "i",
        "you",
        "he",
        "she",
        "we",
        "they",
        "me",
        "him",
        "her",
        "us",
        "them",
        "my",
        "your",
        "his",
        "our",
        "their",
        "what",
        "which",
        "who",
        "whom",
        "how",
        "when",
        "where",
        "why",
        "not",
        "no",
        "nor",
        "so",
        "if",
        "then",
        "than",
        "too",
        "very",
        "just",
        "about",
        "above",
        "after",
        "again",
        "all",
        "also",
        "am",
        "as",
        "because",
        "before",
        "between",
        "both",
        "each",
        "few",
        "more",
        "most",
        "other",
        "own",
        "same",
        "some",
        "such",
        "up",
        "out",
        "off",
        "over",
        "under",
        "only",
        "into",
        "down",
        "here",
        "there",
        "once",
        "further",
        "any",
        "s",
        "t",
        "d",
        "ll",
        "re",
        "ve",
        "m",
        "don",
        "doesn",
        "didn",
        "won",
        "wouldn",
        "shouldn",
        "couldn",
        "wasn",
        "weren",
        "isn",
        "aren",
        "hasn",
        "haven",
        "hadn",
        # ---------- 电商场景高频泛词 ----------
        "shirt",
        "gift",
        "gifts",
        "product",
        "products",
        "item",
        "items",
        "new",
        "good",
        "great",
        "best",
        "top",
        "high",
        "quality",
        "free",
        "sale",
        "buy",
        "sell",
        "price",
        "discount",
        "cheap",
        "premium",
        "men",
        "women",
        "men's",
        "women's",
        "boys",
        "girls",
        "kid",
        "kids",
        "adult",
        "adults",
        "one",
        "two",
        "set",
        "pack",
        "piece",
        "pieces",
        "size",
        "color",
        "black",
        "white",
        "blue",
        "red",
        "green",
        # ---------- 泛节庆/情感词 (跨主题桥梁毒药) ----------
        "happy",
        "birthday",
        "party",
        "parties",
        "celebration",
        "celebrate",
        "celebrating",
        "congratulations",
        "congrats",
        "years",
        "year",
        "old",
        "age",
        "turning",
        "th",
        "nd",
        "st",
        "rd",
        "day",
        "days",
        "night",
        "tonight",
        "eve",
        "morning",
        "event",
        "season",
        "seasonal",
        "supply",
        "supplies",
        "theme",
        "themed",
        "occasion",
        "surprise",
        "idea",
        "ideas",
        "favor",
        "favors",
        "decoration",
    }
)


class AmazonThemeClusteringPipeline:
    """
    从散装 ASIN 标题提取指纹并进行拓扑聚类的全链路 Pipeline。

    用法::

        pipeline = AmazonThemeClusteringPipeline()
        pipeline.run(reset=False)   # 增量模式
        pipeline.run(reset=True)    # 全量重建模式
    """

    BLACKLIST_TAGS = frozenset(
        {
            "vintage",
            "retro",
            "classic",
            "official",
            "distressed",
            "unisex",
            "custom",
            "gift",
            "gifts",
            "funny",
            "cool",
            "cute",
            "beautiful",
            "unique",
            "original",
            "limited",
            "edition",
            "special",
            "exclusive",
            "premium",
            "deluxe",
            "standard",
            "basic",
            "essential",
            "popular",
            "trending",
            "style",
            "styled",
            "design",
            "designed",
            "printed",
            "graphic",
            "pattern",
            "logo",
            "art",
            "artwork",
            "illustration",
            "decorative",
            "ornamental",
            "fashion",
            "trendy",
            "modern",
            "elegant",
            "fancy",
            "novelty",
            "creative",
            "awesome",
            "amazing",
            "perfect",
            "lovely",
            "wonderful",
            "fantastic",
            "great",
            "super",
            "pro",
            "ultra",
            "mega",
            "mini",
        }
    )

    # ---------- 产品品类词: 在 _clean_text 最先剔除, 连单词边界匹配 ----------
    PRODUCT_WORDS = frozenset(
        {
            "shirt",
            "tshirt",
            "hoodie",
            "sweatshirt",
            "sweater",
            "tank",
            "apparel",
            "clothing",
            "garment",
            "outerwear",
            "activewear",
            "accessories",
            "jewelry",
            "necklace",
            "bracelet",
            "earring",
            "ring",
            "pendant",
            "chain",
            "watch",
            "gift",
            "present",
            "souvenir",
            "keepsake",
            "tote",
            "bag",
            "handbag",
            "purse",
            "backpack",
            "pouch",
            "cap",
            "hat",
            "beanie",
            "snapback",
            "fedora",
            "headwear",
            "flag",
            "banner",
            "bunting",
            " pennant",
            "sticker",
            "decal",
            "label",
            "patch",
            "mug",
            "cup",
            "tumbler",
            "thermos",
            "flask",
            "bottle",
            "poster",
            "print",
            "canvas",
            "wallpaper",
            "decoration",
            "decor",
            "ornament",
            "figurine",
            "statue",
            "pillow",
            "cushion",
            "blanket",
            "quilt",
            "towel",
            "apron",
            "coaster",
            "placemat",
            "cutting board",
            "keychain",
            "keyring",
            "fridge magnet",
            "magnet",
            "phone case",
            "mousepad",
            "notebook",
            "journal",
            "pin",
            "badge",
            "button",
            "lapel",
            "sock",
            "glove",
            "scarf",
            "bandana",
            "mask",
            "shoe",
            "sneaker",
            "sandal",
            "boot",
            "costume",
            "cosplay",
            "disguise",
            "balloon",
            "card",
            "invitation",
            "wrapper",
            "toy",
            "game",
            "puzzle",
            "figure",
            "sign",
            "yard sign",
            "house flag",
            "garden flag",
            "doormat",
            "welcome mat",
            "light",
            "lamp",
            "nightlight",
            "candle",
            "clock",
            "alarm",
            "thermometer",
            "earring",
            "bracelet",
            "anklet",
            "brooch",
            "wig",
            "headband",
            "hairband",
            "underwear",
            "panties",
            "bra",
            "lingerie",
            "swimsuit",
            "bikini",
            "trunks",
            "diaper",
            "bib",
            "pacifier",
            "pet",
            "collar",
            "leash",
            "tag",
            "men",
            "women",
            "boys",
            "girls",
            "kid",
            "kids",
            "adult",
            "adults",
            "toddler",
            "baby",
            "infant",
            "unisex",
            "couple",
            "family",
            "size",
            "large",
            "medium",
            "small",
            "xl",
            "xxl",
        }
    )

    # ---------- 同义词收拢: 在序数词归一化之后、产品词剔除之前执行 ----------
    # (regex_pattern, replacement)  — 按长→短顺序, 先匹配长串
    SYNONYM_RULES: list[tuple[str, str]] = [
        (r"\bsemiquincentennial\b", "250 anniversary"),
        (r"\bamerica\b", "usa"),
        (r"\bunited\s+states\s+of\s+america\b", "usa"),
        (r"\bunited\s+states\b", "usa"),
        (r"\bu\s*s\s*a\b", "usa"),
        (r"\busa\b", "usa"),
        (r"\bindependence\s+day\b", "independence_day"),
        (r"\bfourth\s+of\s+july\b", "independence_day"),
        (r"\bjuly\s+4th\b", "independence_day"),
        (r"\bmemorial\s+day\b", "memorial_day"),
        (r"\bveterans\s+day\b", "veterans_day"),
        (r"\bfathers?\s+day\b", "fathers_day"),
        (r"\bmothers?\s+day\b", "mothers_day"),
        (r"\bvalentines?\s+day\b", "valentines_day"),
        (r"\bst\s+patricks?\s+day\b", "st_patricks_day"),
        (r"\bhalloween\b", "halloween"),
        (r"\bthanksgiving\b", "thanksgiving"),
        (r"\bchristmas\b", "christmas"),
        (r"\bbirthday\b", "birthday"),
    ]

    def __init__(
        self,
        pmi_threshold: float = 3.0,
        min_freq: int = 5,
        jaccard_threshold: float = 0.4,
        core_tag_count: int = 5,
        min_intersection: int = 2,
    ):
        self.pmi_threshold = pmi_threshold
        self.min_freq = min_freq
        self.jaccard_threshold = jaccard_threshold
        self.core_tag_count = core_tag_count
        self.min_intersection = min_intersection

        # ---- 各阶段共享上下文 ----
        # {fingerprint_id: (frozenset(tokens), [core_tag, ...])}
        self._fp_token_sets: dict[int, frozenset] = {}
        self._fp_core_tags: dict[int, list[str]] = {}
        # {token: idf_value}
        self._token_idf: dict[str, float] = {}
        # {fingerprint_id: fingerprint_instance}
        self._fp_instances: dict[int, ThemeFingerprint] = {}

    # ==================================================================
    #  公共入口
    # ==================================================================

    def run(self, reset: bool = False):
        """
        执行完整四阶段流水线。

        Parameters
        ----------
        reset : bool
            True  → 清空所有 ThemeFingerprint / AmazonThemeCluster,
                    并将 AmazonNewReleaseRank.denoising 重置为 False,
                    然后全量重建。
            False → 增量模式, 只处理 denoising=False 的记录。
        """
        logger.info("========== Pipeline 启动 ==========")
        logger.info("模式: %s", "全量重建" if reset else "增量")

        if reset:
            self._reset_all_data()

        self._stage1_ngram_tokenization()
        self._stage2_tfidf_weighting()
        components = self._stage3_graph_clustering()
        self._stage4_persistence(components)

        logger.info("========== Pipeline 完成 ==========")

    # ==================================================================
    #  Stage 1 — N-Gram 动态识别与脱水预处理
    # ==================================================================

    def _stage1_ngram_tokenization(self):
        """
        阶段 1:
          1) 读取所有 denoising=False 的 ASIN subject
          2) 基础清洗 → 小写 + 剔除非字母数字
          3) 构建全局 Bigram / Trigram 语料库
          4) 计算 PMI, 筛选固定短语
          5) 将固定短语替换为下划线连接形式
          6) 停用词脱水 (保留下划线短语)
          7) 生成 fingerprint_key 并入库
        """
        logger.info("[Stage 1] N-Gram 动态识别与脱水预处理 — 开始")

        # ---------- 1.1 读取原始数据 ----------
        queryset = AmazonNewReleaseRank.objects.filter(denoising=False)
        total = queryset.count()
        if total == 0:
            logger.info("[Stage 1] 无待处理数据, 跳过")
            return
        logger.info("[Stage 1] 待处理 ASIN 数: %d", total)

        raw_records: list[AmazonNewReleaseRank] = []
        for record in queryset.iterator(chunk_size=BATCH_SIZE):
            raw_records.append(record)

        # ---------- 1.2 基础清洗 ----------
        cleaned_texts: list[str] = []
        for rec in raw_records:
            cleaned = self._clean_text(rec.subject or "")
            cleaned_texts.append(cleaned)

        # ---------- 1.3 & 1.4 构建 N-Gram 语料库 + PMI 筛选 ----------
        ngram_dict = self._build_ngram_corpus(cleaned_texts)
        logger.info(
            "[Stage 1] 合格 N-Gram 短语数: %d (freq>=%d, PMI>=%.2f)",
            len(ngram_dict),
            self.min_freq,
            self.pmi_threshold,
        )

        # ---------- 1.5 替换 → 分词 → 脱水 → 指纹 ----------
        # {fingerprint_key: representative_title}
        fp_map: dict[str, str] = {}
        # {fingerprint_key: [AmazonNewReleaseRank, ...]}
        fp_key_to_records: dict[str, list[AmazonNewReleaseRank]] = defaultdict(list)

        for rec, cleaned in zip(raw_records, cleaned_texts):
            replaced = self._apply_ngram_replacement(cleaned, ngram_dict)
            tokens = self._tokenize_and_filter(replaced)
            if not tokens:
                continue
            fp_key = self._generate_fingerprint_key(tokens)
            fp_map[fp_key] = rec.subject or ""
            fp_key_to_records[fp_key].append(rec)

        logger.info("[Stage 1] 去重后指纹数: %d", len(fp_map))

        # ---------- 1.6 批量写入 ThemeFingerprint ----------
        with transaction.atomic():
            # 查询已存在的 fingerprint_key, 避免重复创建
            existing_keys = set(
                ThemeFingerprint.objects.filter(
                    fingerprint_key__in=fp_map.keys()
                ).values_list("fingerprint_key", flat=True)
            )

            new_fps: list[ThemeFingerprint] = []
            for fp_key, title in fp_map.items():
                if fp_key in existing_keys:
                    continue
                new_fps.append(
                    ThemeFingerprint(
                        fingerprint_key=fp_key,
                        representative_title=title,
                        asin_count=len(fp_key_to_records[fp_key]),
                    )
                )

            if new_fps:
                created = ThemeFingerprint.objects.bulk_create(
                    new_fps,
                    ignore_conflicts=True,
                    batch_size=BATCH_SIZE,
                )
                logger.info("[Stage 1] 新建 ThemeFingerprint: %d 条", len(created))

            # 更新已有指纹的 asin_count
            existing_fps = ThemeFingerprint.objects.filter(
                fingerprint_key__in=fp_key_to_records.keys()
            )
            fps_to_update: list[ThemeFingerprint] = []
            for fp in existing_fps:
                new_count = len(fp_key_to_records.get(fp.fingerprint_key, []))
                if new_count > fp.asin_count:
                    fp.asin_count = new_count
                    fps_to_update.append(fp)
            if fps_to_update:
                ThemeFingerprint.objects.bulk_update(
                    fps_to_update,
                    ["asin_count"],
                    batch_size=BATCH_SIZE,
                )

        # ---------- 1.7 反向关联 ASIN → Fingerprint + 标记 denoising ----------
        all_fps = {
            fp.fingerprint_key: fp
            for fp in ThemeFingerprint.objects.filter(
                fingerprint_key__in=fp_key_to_records.keys()
            )
        }

        records_to_update: list[AmazonNewReleaseRank] = []
        for fp_key, records in fp_key_to_records.items():
            fp_instance = all_fps.get(fp_key)
            if fp_instance is None:
                continue
            for rec in records:
                rec.fingerprint = fp_instance
                rec.denoising = True
                records_to_update.append(rec)

        if records_to_update:
            with transaction.atomic():
                for i in range(0, len(records_to_update), BATCH_SIZE):
                    batch = records_to_update[i : i + BATCH_SIZE]
                    AmazonNewReleaseRank.objects.bulk_update(
                        batch,
                        ["fingerprint", "denoising"],
                        batch_size=BATCH_SIZE,
                    )
            logger.info(
                "[Stage 1] 已关联 %d 条 ASIN → Fingerprint", len(records_to_update)
            )

    # ----- Stage 1 内部工具方法 -----

    @classmethod
    def _clean_text(cls, text: str) -> str:
        """
        全链路清洗管道:
          1) 小写
          2) 将 -, _, / 替换为空格
          3) 序数词归一化: 250th → 250
          4) 同义词收拢: america → usa, semiquincentennial → 250 anniversary 等
          5) 产品品类词外科手术式剔除 (单词边界匹配)
          6) 剔除非字母数字下划线 (保留空格和下划线, 因为同义词会引入 _)
          7) 合并多余空格
        """
        text = text.lower()
        text = re.sub(r"[-_/]+", " ", text)
        text = re.sub(r"(\d+)(st|nd|rd|th)\b", r"\1", text)

        # --- 同义词收拢 (在产品词剔除前执行, 因为替换可能产生新词) ---
        for pattern, replacement in cls.SYNONYM_RULES:
            text = re.sub(pattern, replacement, text)

        # --- 产品品类词剔除 (单次正则, 逐词边界匹配) ---
        product_pattern = (
            r"\b(?:"
            + "|".join(
                re.escape(w) for w in sorted(cls.PRODUCT_WORDS, key=len, reverse=True)
            )
            + r")\b"
        )
        text = re.sub(product_pattern, " ", text)

        # 保留字母、数字、空格、下划线 (同义词 replacement 引入的下划线不能被吞掉)
        text = re.sub(r"[^a-z0-9\s_]", "", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _build_ngram_corpus(self, texts: list[str]) -> dict[str, tuple[int, float]]:
        """
        构建全局 Bigram / Trigram 语料库, 计算 PMI, 返回合格短语。

        返回值: { "he_is_risen": (freq, pmi), ... }

        PMI 计算原理 (对数差值法, 数学稳定):
        ─────────────────────────────────────
        对于 bigram (w1, w2):
            PMI = log2( P(w1,w2) / (P(w1) * P(w2)) )
                = log2( count(w1,w2) )
                  - log2( count(w1) )
                  - log2( count(w2) )
                  + log2( N_total )

        对于 trigram (w1, w2, w3):
            PMI = log2( P(w1,w2,w3) / (P(w1)*P(w2)*P(w3)) )
                = log2( count(w1,w2,w3) )
                  - log2( count(w1) )
                  - log2( count(w2) )
                  - log2( count(w3) )
                  + 2 * log2( N_total )

        使用 math.log2 差值法可以避免:
          1) 连乘导致的浮点溢出
          2) 极小概率相除带来的精度损失
        """
        # 统计 unigram 频次
        unigram_freq: Counter = Counter()
        bigram_freq: Counter = Counter()
        trigram_freq: Counter = Counter()
        total_unigrams = 0

        for text in texts:
            words = text.split()
            if len(words) == 0:
                continue

            total_unigrams += len(words)
            unigram_freq.update(words)

            for i in range(len(words) - 1):
                bg = (words[i], words[i + 1])
                bigram_freq[bg] += 1

            for i in range(len(words) - 2):
                tg = (words[i], words[i + 1], words[i + 2])
                trigram_freq[tg] += 1

        if total_unigrams == 0:
            return {}

        # --- 计算 PMI (对数差值法) ---
        log_total = math.log2(total_unigrams)
        qualified: dict[str, tuple[int, float]] = {}

        # 先处理 trigram (长匹配优先)
        for ngram, freq in trigram_freq.items():
            if freq < self.min_freq:
                continue
            # PMI = log2(freq) - log2(c_w1) - log2(c_w2) - log2(c_w3) + 2*log2(N)
            pmi = math.log2(freq)
            for w in ngram:
                pw = unigram_freq.get(w, 0)
                if pw == 0:
                    pmi = -math.inf
                    break
                pmi -= math.log2(pw)
            pmi += 2.0 * log_total

            if pmi >= self.pmi_threshold:
                key = "_".join(ngram)
                qualified[key] = (freq, pmi)

        # 再处理 bigram
        for ngram, freq in bigram_freq.items():
            if freq < self.min_freq:
                continue
            pmi = math.log2(freq)
            for w in ngram:
                pw = unigram_freq.get(w, 0)
                if pw == 0:
                    pmi = -math.inf
                    break
                pmi -= math.log2(pw)
            pmi += log_total

            if pmi >= self.pmi_threshold:
                key = "_".join(ngram)
                # trigram 优先: 如果 bigram 已被 trigram 覆盖则跳过
                if key not in qualified:
                    qualified[key] = (freq, pmi)

        return qualified

    @staticmethod
    def _apply_ngram_replacement(
        text: str, ngram_dict: dict[str, tuple[int, float]]
    ) -> str:
        """
        将文本中命中的 N-Gram 短语替换为下划线连接形式。
        按短语长度降序匹配 (trigram 优先于 bigram), 避免子串误匹配。

        示例: "he is risen from the dead" → "he_is_risen from the dead"
        """
        if not ngram_dict:
            return text

        # 按词数降序排列, 长短语优先替换
        sorted_phrases = sorted(
            ngram_dict.keys(), key=lambda p: p.count("_"), reverse=True
        )

        for phrase in sorted_phrases:
            pattern = r"\b" + re.escape(phrase.replace("_", " ")) + r"\b"
            text = re.sub(pattern, phrase, text)

        return text

    @staticmethod
    def _tokenize_and_filter(text: str) -> list[str]:
        """
        分词 → N-Gram 拆包 → 停用词脱水 + 纯数字剔除 → 去重。

        关键设计: 所有 N-Gram 打包的 token (含下划线) 在此拆包为原子词,
        然后统一按单个词过滤。这样无论 N-Gram 引擎检测到哪种组合
        (如 "250_anniversary" 或 "anniversary_usa"), 最终 key 都只取决于
        原子词集合, 保证语义相同的标题生成完全一致的 fingerprint_key。
        """
        tokens = text.split()

        # --- 拆包: 将所有含 _ 的 N-Gram token 展开为原子词 ---
        flat: list[str] = []
        for tok in tokens:
            if "_" in tok:
                flat.extend(tok.split("_"))
            else:
                flat.append(tok)

        # --- 过滤: 停用词 + 纯数字 + 单字符 ---
        filtered = [
            tok
            for tok in flat
            if tok not in STOP_WORDS and len(tok) > 1 and not tok.isdigit()
        ]

        # --- 兜底: 全部被过滤后保留第一个纯数字 ---
        if not filtered:
            for tok in flat:
                if tok.isdigit():
                    filtered.append(tok)
                    break

        # --- 去重 (同义词替换可能产生重复) ---
        seen = set()
        deduped = []
        for tok in filtered:
            if tok not in seen:
                seen.add(tok)
                deduped.append(tok)

        return deduped

    @staticmethod
    def _generate_fingerprint_key(tokens: list[str]) -> str:
        """
        将 token 按字母序 A-Z 排序, 用 '-' 拼接, 生成指纹键。

        注意: tokens 已在 _tokenize_and_filter 中被拆包为原子词并去重,
        此处只需排序拼接即可。

        示例: ["anniversary", "usa"] → "anniversary-usa"
        """
        return "-".join(sorted(tokens))

    # ==================================================================
    #  Stage 2 — TF-IDF 全局权重计算
    # ==================================================================

    def _stage2_tfidf_weighting(self):
        """
        阶段 2:
          1) 遍历所有 ThemeFingerprint
          2) 统计全局文档总数 N
          3) 统计每个 token 的文档频率 DF
          4) 计算 IDF = log(N / (DF + 1))
          5) 为每个 Fingerprint 提取 top-K 个高 IDF token 作为 core_tags
        """
        logger.info("[Stage 2] TF-IDF 全局权重计算 — 开始")

        all_fps = list(ThemeFingerprint.objects.all().iterator(chunk_size=BATCH_SIZE))
        if not all_fps:
            logger.info("[Stage 2] 无指纹数据, 跳过")
            return

        N = len(all_fps)
        df_counter: Counter = Counter()

        # --- 统计 DF ---
        for fp in all_fps:
            tokens = fp.fingerprint_key.split("-")
            token_set = frozenset(tokens)
            self._fp_token_sets[fp.id] = token_set
            self._fp_instances[fp.id] = fp
            for t in token_set:
                df_counter[t] += 1

        # --- 计算 IDF ---
        for token, df in df_counter.items():
            self._token_idf[token] = math.log(N / (df + 1))

        # --- 提取 Core Tags (黑名单过滤 + 强语义优先) ---
        for fp_id, token_set in self._fp_token_sets.items():

            def _tag_priority(t: str) -> float:
                """
                排序优先级 (越高越优先):
                  +1000  N-Gram 组合词 (含下划线, 如 independence_day)
                  +500   含数字的 token (如 250) — 暂时从 key 中被剔除,
                         但作为 core_tag 标记仍有极高聚类价值
                  +0     普通实词, 按 IDF 降序
                  -∞     黑名单词, 绝对不进 core_tags
                """
                if t in self.BLACKLIST_TAGS:
                    return -1e9
                if "_" in t:
                    return 1000.0 + self._token_idf.get(t, 0.0)
                if t.isdigit():
                    return 500.0
                return self._token_idf.get(t, 0.0)

            scored = sorted(token_set, key=_tag_priority, reverse=True)
            self._fp_core_tags[fp_id] = scored[: self.core_tag_count]

        logger.info(
            "[Stage 2] 完成: N=%d, 唯一 token 数=%d, core_tags/fp=%d",
            N,
            len(self._token_idf),
            self.core_tag_count,
        )

    # ==================================================================
    #  Stage 3 — 连通分量图算法 (倒排索引优化)
    # ==================================================================

    def _stage3_graph_clustering(self) -> list[set[int]]:
        """
        阶段 3: 基于倒排索引构建拓扑图, 提取连通分量。

        -------------------------------------------------------
        倒排索引 + 图构建 复杂度分析
        -------------------------------------------------------

        设:
          N = 指纹总数
          K = 唯一 core_tag 总数
          M = 所有指纹的 core_tag 条目总数 (M = Σ|core_tags(fp)|)
          G_avg = 每个 core_tag 下平均指纹数 = N * core_tag_count / K

        步骤 1 — 构建倒排索引:
            遍历所有指纹的 core_tags → O(M)

        步骤 2 — 生成边:
            对每个 core_tag, 其候选组大小为 g, 需要两两比较:
                worst-case = Σ C(g_i, 2) = Σ g_i*(g_i-1)/2

            由于 core_tags 是 IDF 最高的词 (具有区分度的罕见词),
            在真实的亚马逊产品数据中, 大多数罕见词只出现在极少数
            指纹中, 因此 g_i 通常很小 (平均 2~5), 远小于 N。

            实际复杂度: O(M + K * G_avg²) ≈ O(M) (当 G_avg 为常数时)

            对比暴力 O(N²): 当 N=50000 时, 暴力需要 12.5 亿次比较;
            倒排索引法只需 ~数十万次, 加速约 3 个数量级。

        步骤 3 — 连通分量:
            networkx 使用 BFS/DFS, 复杂度 O(V + E) = O(N + E)

        总体: O(M + K*G_avg² + N + E)
        -------------------------------------------------------

        四重门槛:
          1) Jaccard 相似度 >= jaccard_threshold (默认 0.4)
          2) 交集最低词数 >= min_intersection (默认 2):
             单 token 交集极易引发链式传导漂移, 必须至少共享 2 个 token
          3) 数字强一致性: 若双方都含数字但数字完全不重合, 禁止建边
          4) 交集词中必须包含至少一个"强语义核心词":
             即交集 & (core_union - BLACKLIST_TAGS) 非空。
             如果交集中仅有 vintage/retro 等弱语义词, 即使 Jaccard
             再高也严禁建立连接。
        """
        logger.info("[Stage 3] 连通分量图算法 — 开始")

        G = nx.Graph()

        fp_ids = list(self._fp_token_sets.keys())
        G.add_nodes_from(fp_ids)

        # ---------- 构建倒排索引: {core_tag: [fp_id, ...]} ----------
        inverted_index: dict[str, list[int]] = defaultdict(list)
        for fp_id, core_tags in self._fp_core_tags.items():
            for tag in core_tags:
                inverted_index[tag].append(fp_id)

        logger.info(
            "[Stage 3] 倒排索引: %d 个 core_tag, %d 个节点",
            len(inverted_index),
            G.number_of_nodes(),
        )

        # ---------- 生成边 ----------
        edge_count = 0

        # 预计算: 每个 fp 的 core_tags 的 frozenset, 用于快速判断
        fp_core_sets: dict[int, frozenset] = {
            fp_id: frozenset(tags) for fp_id, tags in self._fp_core_tags.items()
        }

        # 预计算: 每个 fp 的纯数字 token 集合, 用于数字强一致性校验
        fp_num_sets: dict[int, frozenset] = {
            fp_id: frozenset(t for t in tokens if t.isdigit())
            for fp_id, tokens in self._fp_token_sets.items()
        }

        for tag, candidate_ids in inverted_index.items():
            if len(candidate_ids) < 2:
                continue

            for i, j in combinations(candidate_ids, 2):
                set_i = self._fp_token_sets[i]
                set_j = self._fp_token_sets[j]

                intersection = set_i & set_j
                if not intersection:
                    continue

                union = set_i | set_j
                jaccard = len(intersection) / len(union)

                if jaccard < self.jaccard_threshold:
                    continue

                # 交集最低词数门槛: 截断链式传导漂移
                # 单 token 交集 (如只共享 "usa") 极易通过中间节点把
                # 不相关主题链式拉入同一 Cluster, 必须共享 >= 2 个 token
                if len(intersection) < self.min_intersection:
                    continue

                # 数字强一致性校验:
                # 如果两个指纹都含数字但数字完全不重合 → 禁止建边。
                # 例: 一个含 "250", 另一个含 "40" → 即使 Jaccard 高也不连。
                nums_i = fp_num_sets.get(i, frozenset())
                nums_j = fp_num_sets.get(j, frozenset())
                if nums_i and nums_j and not (nums_i & nums_j):
                    continue

                # 双重门槛: 交集中必须含至少一个非黑名单的强语义核心词
                core_i = fp_core_sets.get(i, frozenset())
                core_j = fp_core_sets.get(j, frozenset())
                strong_core = (core_i | core_j) - self.BLACKLIST_TAGS
                if not (intersection & strong_core):
                    continue

                G.add_edge(i, j)
                edge_count += 1

        logger.info("[Stage 3] 边数: %d", edge_count)

        # ---------- 提取连通分量 ----------
        components = list(nx.connected_components(G))
        # 过滤掉孤立节点 (只有自身一个元素的分量)
        multi_components = [c for c in components if len(c) > 1]
        singleton_count = len(components) - len(multi_components)

        logger.info(
            "[Stage 3] 连通分量总数: %d (其中有效聚类: %d, 孤立节点: %d)",
            len(components),
            len(multi_components),
            singleton_count,
        )

        # 将孤立节点也包装为单元素分量, 统一处理
        all_components = []
        for comp in components:
            all_components.append(comp)

        return all_components

    # ==================================================================
    #  Stage 4 — 数据聚合与 DB 落盘
    # ==================================================================

    def _stage4_persistence(self, components: list[set[int]]):
        """
        阶段 4:
          1) 为每个连通分量创建 AmazonThemeCluster
          2) 统计 core_tags (频次最高的词 → JSON)
          3) 命名逻辑: 取关联 ASIN 最多的指纹的 representative_title
          4) 批量更新 fingerprint.cluster_id (直接 SQL UPDATE)
          5) 计算 burst_score = new_asin_7d / asin_count
        """
        logger.info("[Stage 4] 数据聚合与落盘 — 开始")
        logger.info("[Stage 4] 待处理连通分量: %d", len(components))

        seven_days_ago = timezone.now().date() - timedelta(days=7)

        with transaction.atomic():
            # ---------- 先清除旧的 Cluster 层, 避免孤儿重复 ----------
            ThemeFingerprint.objects.all().update(cluster=None)
            AmazonThemeCluster.objects.all().delete()
            logger.info("[Stage 4] 已清除旧 Cluster 数据, 开始重建")

            clusters_to_create: list[AmazonThemeCluster] = []
            cluster_data: list[dict] = []

            for component in components:
                if len(component) == 0:
                    continue

                fp_ids = list(component)

                # --- 4.1 统计 core_tags: 分量内所有 token 的词频 ---
                token_counter: Counter = Counter()
                for fid in fp_ids:
                    token_counter.update(self._fp_token_sets.get(fid, frozenset()))

                top_tags = [word for word, _ in token_counter.most_common(10)]

                # --- 4.2 命名: 取关联 ASIN 数最多的指纹的 representative_title ---
                best_fp_id = max(
                    fp_ids,
                    key=lambda fid: (
                        self._fp_instances[fid].asin_count
                        if fid in self._fp_instances
                        else 0
                    ),
                )
                display_title = self._fp_instances[best_fp_id].representative_title

                cluster = AmazonThemeCluster(
                    display_title=display_title,
                    core_tags=top_tags,
                    fingerprint_count=len(component),
                )
                clusters_to_create.append(cluster)
                cluster_data.append(
                    {
                        "cluster": cluster,
                        "fp_ids": fp_ids,
                    }
                )

            # --- 批量创建 Cluster ---
            created_clusters = AmazonThemeCluster.objects.bulk_create(
                clusters_to_create,
                batch_size=BATCH_SIZE,
            )
            logger.info(
                "[Stage 4] 创建 AmazonThemeCluster: %d 条", len(created_clusters)
            )

            # --- 批量关联 fingerprint → cluster (直接 SQL UPDATE, 非逐个 save) ---
            for data, cluster in zip(cluster_data, created_clusters):
                batch_ids = data["fp_ids"]
                ThemeFingerprint.objects.filter(id__in=batch_ids).update(
                    cluster=cluster
                )

            logger.info("[Stage 4] Fingerprint → Cluster 关联完成")

            # --- 4.3 统计字段 + burst_score ---
            clusters_to_update: list[AmazonThemeCluster] = []

            for cluster in created_clusters:
                asin_qs = AmazonNewReleaseRank.objects.filter(
                    fingerprint__cluster=cluster
                )
                asin_count = asin_qs.count()
                new_asin_7d = asin_qs.filter(launch_date__gte=seven_days_ago).count()
                burst_score = new_asin_7d / asin_count if asin_count > 0 else 0.0

                cluster.asin_count = asin_count
                cluster.new_asin_7d = new_asin_7d
                cluster.burst_score = round(burst_score, 4)
                clusters_to_update.append(cluster)

            if clusters_to_update:
                AmazonThemeCluster.objects.bulk_update(
                    clusters_to_update,
                    ["asin_count", "new_asin_7d", "burst_score"],
                    batch_size=BATCH_SIZE,
                )
                logger.info(
                    "[Stage 4] 统计字段更新完成: %d 条 Cluster",
                    len(clusters_to_update),
                )

    # ==================================================================
    #  全量重置
    # ==================================================================

    @staticmethod
    def _reset_all_data():
        """
        清空所有指纹与聚类数据, 将 ASIN 的 denoising 标志重置。
        在 transaction.atomic() 中执行, 保证一致性。
        """
        logger.info("[Reset] 开始全量重置...")

        with transaction.atomic():
            AmazonNewReleaseRank.objects.all().update(denoising=False, fingerprint=None)
            ThemeFingerprint.objects.all().delete()
            AmazonThemeCluster.objects.all().delete()

        logger.info("[Reset] 全量重置完成")
