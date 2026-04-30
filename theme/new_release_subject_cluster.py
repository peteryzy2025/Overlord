"""
Amazon 主题指纹提取 & 拓扑聚类全链路 Pipeline
==============================================
四阶段流水线:
  Stage 1 — N-Gram 动态识别与脱水预处理 → 生成 ThemeFingerprint
  Stage 2 — TF-IDF 全局权重计算
  Stage 3 — 连通分量图算法 (倒排索引 + networkx)
  Stage 4 — 数据聚合与 DB 落盘

外部重型依赖: networkx
"""

import logging
import math
import os
import re
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
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
WORKER_CHUNK_SIZE = 500


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
        # ---------- 身份/关系词 (高频跨主题桥梁) ----------
        "love",
        "loving",
        "loved",
        "mom",
        "mama",
        "mother",
        "mommy",
        "dad",
        "daddy",
        "father",
        "papa",
        "girl",
        "boy",
        "wife",
        "husband",
        "son",
        "daughter",
        "brother",
        "sister",
        "grandpa",
        "grandma",
        "grandmother",
        "grandfather",
        "aunt",
        "uncle",
        "cousin",
        "niece",
        "nephew",
        "baby",
        "toddler",
        "infant",
        # ---------- 情感/态度泛词 ----------
        "proud",
        "pride",
        "support",
        "supporter",
        "supporting",
        "awareness",
        "brave",
        "bravery",
        "strong",
        "strength",
        "fighter",
        "fighting",
        "warrior",
        "hero",
        "superhero",
        "inspire",
        "inspired",
        "inspiring",
        "hope",
        "faith",
        "believe",
        "dream",
        "passion",
        "spirit",
        "soul",
        "heart",
        "angel",
        "blessed",
        "blessing",
        "miracle",
        # ---------- 团队/粉丝泛词 ----------
        "team",
        "fan",
        "fans",
        "lover",
        "lovers",
        "enthusiast",
        # ---------- 修饰泛词 ----------
        "world",
        "life",
        "best",
        "ever",
        "always",
        "never",
        "forever",
        "together",
        "perfect",
        "awesome",
        "amazing",
        "lovely",
        "wonderful",
        "fantastic",
        "incredible",
        "beautiful",
        "cute",
        "cool",
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
            "crazy",
            "bruh",
            "lol",
            "lmao",
            "omg",
            "wtf",
            "dope",
            "lit",
            "fire",
            "based",
            "goated",
            # ---------- 主题桥接泛词 (保留在 fingerprint, 不作为聚类核心证据) ----------
            "meme",
            "memes",
            "family",
            "families",
            "vacation",
            "vacations",
            "trip",
            "trips",
            "squad",
            "crew",
            "group",
            "matching",
            "summer",
            "welcome",
            "hello",
            "teacher",
            "teachers",
            "state",
            "city",
            "county",
            "town",
            # ---------- 英文数字词 (不进入 core_tags) ----------
            "one",
            "two",
            "three",
            "four",
            "five",
            "six",
            "seven",
            "eight",
            "nine",
            "ten",
            "eleven",
            "twelve",
            "thirteen",
            "fourteen",
            "fifteen",
            "sixteen",
            "seventeen",
            "eighteen",
            "nineteen",
            "twenty",
            "thirty",
            "forty",
            "fifty",
            "sixty",
            "seventy",
            "eighty",
            "ninety",
            "hundred",
            "thousand",
            "million",
            "first",
            "second",
            "third",
            "fourth",
            "fifth",
            "sixth",
            "seventh",
            "eighth",
            "ninth",
            "tenth",
        }
    )

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
            "cake",
            "cakes",
            "topper",
            "cupcake",
            "baking",
            "bake",
            "bakeware",
            "plate",
            "plates",
            "dish",
            "tray",
            "jar",
            "basket",
            "wreath",
            "garland",
            "ribbon",
            "bow",
            "tassel",
            "confetti",
            "streamer",
            "sparkler",
            "firework",
            "fireworks",
            "noisemaker",
            "horn",
            "whistle",
            "sash",
            "tiara",
            "crown",
            "glasses",
            "sunglasses",
            "lens",
            "frame",
            "frames",
            "photo",
            "photography",
            "album",
            "scrapbook",
            "clip",
            "clips",
            "holder",
            "stand",
            "hook",
            "hanger",
            "shelf",
            "rack",
            "organizer",
            "container",
            "box",
            "boxes",
            "package",
            "wrap",
            "wrapping",
            "envelope",
            "letter",
            "stamp",
            "seal",
            "stencil",
            "template",
            "mold",
            "mould",
            "cutter",
            "tool",
            "kit",
            "set",
        }
    )

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

    _RE_SEP = re.compile(r"[-_/]+")
    _RE_ORDINAL = re.compile(r"(\d+)(st|nd|rd|th)\b")
    _RE_JUNK = re.compile(r"[^a-z0-9\s_]")
    _RE_SPACE = re.compile(r"\s+")

    def __init__(
        self,
        pmi_threshold: float = 3.0,
        min_freq: int = 5,
        jaccard_threshold: float = 0.55,
        core_tag_count: int = 5,
        min_intersection: int = 3,
        idf_threshold: float = 1.0,
    ):
        self.pmi_threshold = pmi_threshold
        self.min_freq = min_freq
        self.jaccard_threshold = jaccard_threshold
        self.core_tag_count = core_tag_count
        self.min_intersection = min_intersection
        self.idf_threshold = idf_threshold

        self._fp_token_sets: dict[int, frozenset] = {}
        self._fp_core_tags: dict[int, list[str]] = {}
        self._token_idf: dict[str, float] = {}
        self._fp_instances: dict[int, ThemeFingerprint] = {}

        self._product_pattern = (
            r"\b(?:"
            + "|".join(
                re.escape(w) for w in sorted(self.PRODUCT_WORDS, key=len, reverse=True)
            )
            + r")\b"
        )
        self._product_re = re.compile(self._product_pattern)

        self._n_workers = min(os.cpu_count() or 1, 8)

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
        self._stage4_persistence(components, reset=reset)

        logger.info("========== Pipeline 完成 ==========")

    # ==================================================================
    #  Stage 1 — N-Gram 动态识别与脱水预处理
    # ==================================================================

    def _stage1_ngram_tokenization(self):
        logger.info("[Stage 1] N-Gram 动态识别与脱水预处理 — 开始")

        queryset = AmazonNewReleaseRank.objects.filter(denoising=False)
        total = queryset.count()
        if total == 0:
            logger.info("[Stage 1] 无待处理数据, 跳过")
            return
        logger.info("[Stage 1] 待处理 ASIN 数: %d", total)

        raw_records: list[AmazonNewReleaseRank] = []
        for record in queryset.iterator(chunk_size=BATCH_SIZE):
            raw_records.append(record)

        subjects = [rec.subject or "" for rec in raw_records]
        cleaned_texts = self._parallel_clean(subjects)

        ngram_dict = self._build_ngram_corpus(cleaned_texts)
        logger.info(
            "[Stage 1] 合格 N-Gram 短语数: %d (freq>=%d, PMI>=%.2f)",
            len(ngram_dict),
            self.min_freq,
            self.pmi_threshold,
        )

        fp_results = self._parallel_fingerprint(cleaned_texts, ngram_dict)

        fp_map: dict[str, str] = {}
        fp_key_to_records: dict[str, list[AmazonNewReleaseRank]] = defaultdict(list)

        for idx, fp_key in enumerate(fp_results):
            if fp_key is None:
                continue
            rec = raw_records[idx]
            fp_map[fp_key] = rec.subject or ""
            fp_key_to_records[fp_key].append(rec)

        logger.info("[Stage 1] 去重后指纹数: %d", len(fp_map))

        with transaction.atomic():
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

    # ----- Stage 1 并行辅助 -----

    def _parallel_clean(self, texts: list[str]) -> list[str]:
        if len(texts) < WORKER_CHUNK_SIZE:
            return [self._clean_text(t) for t in texts]

        chunks = [
            texts[i : i + WORKER_CHUNK_SIZE]
            for i in range(0, len(texts), WORKER_CHUNK_SIZE)
        ]

        def _clean_chunk(chunk):
            return [self._clean_text(t) for t in chunk]

        cleaned_chunks = []
        with ThreadPoolExecutor(max_workers=self._n_workers) as pool:
            for result in pool.map(_clean_chunk, chunks):
                cleaned_chunks.append(result)
        return [t for chunk in cleaned_chunks for t in chunk]

    def _parallel_fingerprint(
        self, cleaned_texts: list[str], ngram_dict: dict
    ) -> list[str | None]:
        if len(cleaned_texts) < WORKER_CHUNK_SIZE:
            results = []
            for t in cleaned_texts:
                replaced = self._apply_ngram_replacement(t, ngram_dict)
                tokens = self._tokenize_and_filter(replaced)
                results.append(
                    self._generate_fingerprint_key(tokens) if tokens else None
                )
            return results

        chunks = [
            cleaned_texts[i : i + WORKER_CHUNK_SIZE]
            for i in range(0, len(cleaned_texts), WORKER_CHUNK_SIZE)
        ]

        def _fp_chunk(chunk):
            results = []
            for t in chunk:
                replaced = self._apply_ngram_replacement(t, ngram_dict)
                tokens = self._tokenize_and_filter(replaced)
                results.append(
                    self._generate_fingerprint_key(tokens) if tokens else None
                )
            return results

        fp_chunks = []
        with ThreadPoolExecutor(max_workers=self._n_workers) as pool:
            for result in pool.map(_fp_chunk, chunks):
                fp_chunks.append(result)
        return [fp for chunk in fp_chunks for fp in chunk]

    # ----- Stage 1 内部工具方法 -----

    @classmethod
    def _clean_text(cls, text: str) -> str:
        text = text.lower()
        text = cls._RE_SEP.sub(" ", text)
        text = cls._RE_ORDINAL.sub(r"\1", text)

        for pattern, replacement in cls.SYNONYM_RULES:
            text = re.sub(pattern, replacement, text)

        text = cls._RE_JUNK.sub("", text)
        text = cls._RE_SPACE.sub(" ", text).strip()

        text = (
            cls._product_re.sub(" ", text)
            if hasattr(cls, "_product_re") and cls._product_re
            else text
        )
        text = cls._RE_SPACE.sub(" ", text).strip()
        return text

    def _build_ngram_corpus(self, texts: list[str]) -> dict[str, tuple[int, float]]:
        n_workers = min(self._n_workers, os.cpu_count() or 4, 8)
        chunk_size = max(1, len(texts) // n_workers)
        chunks = [texts[i : i + chunk_size] for i in range(0, len(texts), chunk_size)]

        unigram_freq: Counter = Counter()
        bigram_freq: Counter = Counter()
        trigram_freq: Counter = Counter()
        total_unigrams = 0

        if len(chunks) > 1:
            with ThreadPoolExecutor(max_workers=len(chunks)) as pool:
                results = list(pool.map(_nr_count_ngrams_worker, chunks))
            for ug, bg, tg, cnt in results:
                unigram_freq.update(ug)
                bigram_freq.update(bg)
                trigram_freq.update(tg)
                total_unigrams += cnt
        else:
            for text in texts:
                words = text.split()
                if not words:
                    continue
                total_unigrams += len(words)
                unigram_freq.update(words)
                for bg in zip(words, words[1:]):
                    bigram_freq[bg] += 1
                for tg in zip(words, words[1:], words[2:]):
                    trigram_freq[tg] += 1

        if total_unigrams == 0:
            return {}

        log_total = math.log2(total_unigrams)
        log_unigrams: dict[str, float] = {}
        for w, c in unigram_freq.items():
            log_unigrams[w] = math.log2(c)

        qualified: dict[str, tuple[int, float]] = {}

        for ngram, freq in trigram_freq.items():
            if freq < self.min_freq:
                continue
            log_f = math.log2(freq)
            pmi = log_f + 2.0 * log_total
            for w in ngram:
                lw = log_unigrams.get(w)
                if lw is None:
                    pmi = -math.inf
                    break
                pmi -= lw
            if pmi >= self.pmi_threshold:
                key = "_".join(ngram)
                qualified[key] = (freq, pmi)

        for ngram, freq in bigram_freq.items():
            if freq < self.min_freq:
                continue
            log_f = math.log2(freq)
            pmi = log_f + log_total
            for w in ngram:
                lw = log_unigrams.get(w)
                if lw is None:
                    pmi = -math.inf
                    break
                pmi -= lw
            if pmi >= self.pmi_threshold:
                key = "_".join(ngram)
                if key not in qualified:
                    qualified[key] = (freq, pmi)

        return qualified

    @staticmethod
    def _apply_ngram_replacement(
        text: str, ngram_dict: dict[str, tuple[int, float]]
    ) -> str:
        if not ngram_dict:
            return text

        sorted_phrases = sorted(
            ngram_dict.keys(), key=lambda p: p.count("_"), reverse=True
        )

        for phrase in sorted_phrases:
            pattern = r"\b" + re.escape(phrase.replace("_", " ")) + r"\b"
            text = re.sub(pattern, phrase, text)

        return text

    @classmethod
    def _has_semantic_anchor(cls, token: str) -> bool:
        parts = token.split("_") if "_" in token else [token]
        return any(
            part not in STOP_WORDS
            and part not in cls.BLACKLIST_TAGS
            and len(part) > 1
            and not part.isdigit()
            for part in parts
        )

    @classmethod
    def _is_semantic_match_token(cls, token: str) -> bool:
        if "_" in token:
            return cls._has_semantic_anchor(token)
        return (
            token not in STOP_WORDS
            and token not in cls.BLACKLIST_TAGS
            and len(token) > 1
            and not token.isdigit()
        )

    @classmethod
    def _tokenize_and_filter(cls, text: str) -> list[str]:
        tokens = text.split()

        flat: list[str] = []
        for tok in tokens:
            if "_" in tok:
                parts = [part for part in tok.split("_") if part]
                phrase = "_".join(parts)
                if phrase and cls._has_semantic_anchor(phrase):
                    flat.append(phrase)
                flat.extend(parts)
            else:
                flat.append(tok)

        filtered = []
        for tok in flat:
            if "_" in tok:
                if cls._has_semantic_anchor(tok):
                    filtered.append(tok)
            elif tok not in STOP_WORDS and len(tok) > 1 and not tok.isdigit():
                filtered.append(tok)

        if not filtered:
            for tok in flat:
                if tok.isdigit():
                    filtered.append(tok)
                    break

        seen = set()
        deduped = []
        for tok in filtered:
            if tok not in seen:
                seen.add(tok)
                deduped.append(tok)

        return deduped

    @staticmethod
    def _generate_fingerprint_key(tokens: list[str]) -> str:
        return "-".join(sorted(tokens))

    # ==================================================================
    #  Stage 2 — TF-IDF 全局权重计算
    # ==================================================================

    def _stage2_tfidf_weighting(self):
        logger.info("[Stage 2] TF-IDF 全局权重计算 — 开始")

        all_fps = list(ThemeFingerprint.objects.all().iterator(chunk_size=BATCH_SIZE))
        if not all_fps:
            logger.info("[Stage 2] 无指纹数据, 跳过")
            return

        N = len(all_fps)
        df_counter: Counter = Counter()

        for fp in all_fps:
            tokens = fp.fingerprint_key.split("-")
            token_set = frozenset(tokens)
            self._fp_token_sets[fp.id] = token_set
            self._fp_instances[fp.id] = fp
            for t in token_set:
                df_counter[t] += 1

        for token, df in df_counter.items():
            self._token_idf[token] = math.log(N / (df + 1))

        for fp_id, token_set in self._fp_token_sets.items():

            def _tag_priority(t: str) -> float:
                if t in self.BLACKLIST_TAGS:
                    return -1e9
                if "_" in t:
                    if self._has_semantic_anchor(t):
                        return 1000.0 + self._token_idf.get(t, 0.0)
                    return -1e9
                if t.isdigit():
                    return 0.0
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
        五重门槛:
          1) Jaccard 相似度 >= jaccard_threshold
          2) 交集最低词数 >= min_intersection
          3) 数字强一致性
          4) 交集词中必须包含至少一个非黑名单的强语义核心词
          5) 交集词中必须包含至少一个 IDF >= idf_threshold 的词
        """
        logger.info("[Stage 3] 连通分量图算法 — 开始")

        G = nx.Graph()

        fp_ids = list(self._fp_token_sets.keys())
        G.add_nodes_from(fp_ids)

        inverted_index: dict[str, list[int]] = defaultdict(list)
        for fp_id, core_tags in self._fp_core_tags.items():
            for tag in core_tags:
                inverted_index[tag].append(fp_id)

        logger.info(
            "[Stage 3] 倒排索引: %d 个 core_tag, %d 个节点",
            len(inverted_index),
            G.number_of_nodes(),
        )

        fp_core_sets: dict[int, frozenset] = {
            fp_id: frozenset(tags) for fp_id, tags in self._fp_core_tags.items()
        }

        fp_num_sets: dict[int, frozenset] = {
            fp_id: frozenset(t for t in tokens if t.isdigit())
            for fp_id, tokens in self._fp_token_sets.items()
        }

        tags_with_pairs = [
            (tag, cands) for tag, cands in inverted_index.items() if len(cands) >= 2
        ]

        edge_count = 0

        if len(tags_with_pairs) >= self._n_workers * 2:
            tag_chunks = [
                tags_with_pairs[i :: self._n_workers] for i in range(self._n_workers)
            ]
            with ThreadPoolExecutor(max_workers=self._n_workers) as pool:
                for edges in pool.map(
                    lambda chunk: self._generate_edges_for_tags(
                        chunk, fp_core_sets, fp_num_sets
                    ),
                    tag_chunks,
                ):
                    for i, j, w in edges:
                        G.add_edge(i, j, weight=w)
                    edge_count += len(edges)
        else:
            edges = self._generate_edges_sequential(
                tags_with_pairs,
                fp_core_sets,
                fp_num_sets,
            )
            for i, j, w in edges:
                G.add_edge(i, j, weight=w)
            edge_count = len(edges)

        logger.info("[Stage 3] 边数: %d", edge_count)

        communities = nx.community.louvain_communities(
            G, weight="weight", resolution=1.2, seed=42
        )
        components = list(communities)
        multi_components = [c for c in components if len(c) > 1]
        singleton_count = len(components) - len(multi_components)

        logger.info(
            "[Stage 3] Louvain 社区数: %d (其中有效聚类: %d, 孤立节点: %d)",
            len(components),
            len(multi_components),
            singleton_count,
        )

        return list(components)

    def _generate_edges_sequential(
        self,
        tags_with_pairs: list[tuple],
        fp_core_sets: dict[int, frozenset],
        fp_num_sets: dict[int, frozenset],
    ) -> list[tuple[int, int, float]]:
        return self._generate_edges_for_tags(tags_with_pairs, fp_core_sets, fp_num_sets)

    def _generate_edges_for_tags(
        self,
        tags: list[tuple],
        fp_core_sets: dict[int, frozenset],
        fp_num_sets: dict[int, frozenset],
    ) -> list[tuple[int, int, float]]:
        edges = []
        for tag, candidate_ids in tags:
            for i, j in combinations(candidate_ids, 2):
                ok, jaccard = self._check_edge(i, j, fp_core_sets, fp_num_sets)
                if ok:
                    edges.append((i, j, jaccard))
        return edges

    def _check_edge(
        self,
        i: int,
        j: int,
        fp_core_sets: dict[int, frozenset],
        fp_num_sets: dict[int, frozenset],
    ) -> tuple[bool, float]:
        set_i = self._fp_token_sets[i]
        set_j = self._fp_token_sets[j]

        nums_i = fp_num_sets.get(i, frozenset())
        nums_j = fp_num_sets.get(j, frozenset())
        if nums_i and nums_j and nums_i != nums_j:
            return False, 0.0

        intersection = set_i & set_j
        if not intersection:
            return False, 0.0

        semantic_intersection = {
            t for t in intersection if self._is_semantic_match_token(t)
        }

        union = set_i | set_j
        jaccard = len(intersection) / len(union)
        if jaccard < self.jaccard_threshold:
            return False, 0.0

        if len(semantic_intersection) < self.min_intersection:
            return False, 0.0

        core_i = fp_core_sets.get(i, frozenset())
        core_j = fp_core_sets.get(j, frozenset())
        strong_core = (core_i | core_j) - self.BLACKLIST_TAGS
        if not (semantic_intersection & strong_core):
            return False, 0.0

        idf_check = any(
            self._token_idf.get(t, 0.0) >= self.idf_threshold
            for t in semantic_intersection
        )
        if not idf_check:
            return False, 0.0

        top2_i = set(self._fp_core_tags.get(i, [])[:2]) - self.BLACKLIST_TAGS
        top2_j = set(self._fp_core_tags.get(j, [])[:2]) - self.BLACKLIST_TAGS
        if not (semantic_intersection & (top2_i | top2_j)):
            return False, 0.0

        return True, jaccard

    # ==================================================================
    #  Stage 4 — 数据聚合与 DB 落盘
    # ==================================================================

    def _stage4_persistence(self, components: list[set[int]], reset: bool = False):
        logger.info("[Stage 4] 数据聚合与落盘 — 开始")
        logger.info("[Stage 4] 待处理连通分量: %d", len(components))
        logger.info("[Stage 4] 模式: %s", "全量重建" if reset else "增量")

        run_timestamp = timezone.now()
        run_date = run_timestamp.date()
        seven_days_ago = run_date - timedelta(days=7)

        def _date_from_datetime(value):
            if value is None:
                return None
            if timezone.is_aware(value):
                return timezone.localtime(value).date()
            return value.date()

        existing_cluster_map: dict[str, AmazonThemeCluster] = {
            c.display_title: c
            for c in AmazonThemeCluster.objects.all()
        }
        logger.info(
            "[Stage 4] 已缓存旧 Cluster 对象快照: %d 条",
            len(existing_cluster_map),
        )

        previous_cluster_state = {
            row["display_title"]: {
                "asin_count": row["asin_count"] or 0,
                "asin_change": row["asin_change"] or 0,
                "updated_at": row["updated_at"],
            }
            for row in AmazonThemeCluster.objects.values(
                "display_title",
                "asin_count",
                "asin_change",
                "updated_at",
            )
        }

        def _calculate_asin_change(display_title: str, new_asin_count: int) -> int:
            previous = previous_cluster_state.get(display_title)
            if not previous:
                return new_asin_count

            previous_updated_date = _date_from_datetime(previous.get("updated_at"))
            if previous_updated_date == run_date:
                return previous["asin_change"]

            return new_asin_count - previous["asin_count"]

        # ---------- 遍历 components, 区分新建 / 更新 ----------
        clusters_to_create: list[AmazonThemeCluster] = []
        clusters_to_update_basic: list[AmazonThemeCluster] = []
        cluster_create_data: list[dict] = []
        cluster_update_data: list[dict] = []

        for component in components:
            if len(component) == 0:
                continue

            fp_ids = list(component)

            token_counter: Counter = Counter()
            for fid in fp_ids:
                token_counter.update(self._fp_token_sets.get(fid, frozenset()))

            top_tags = [
                word
                for word, _ in token_counter.most_common()
                if self._is_semantic_match_token(word)
            ][:10]

            best_fp_id = max(
                fp_ids,
                key=lambda fid: (
                    self._fp_instances[fid].asin_count
                    if fid in self._fp_instances
                    else 0
                ),
            )
            display_title = self._fp_instances[best_fp_id].representative_title

            if len(top_tags) <= 1:
                title_tags = [
                    w
                    for w in display_title.lower().split()
                    if w not in STOP_WORDS
                    and w not in self.BLACKLIST_TAGS
                    and len(w) > 1
                    and w.isalpha()
                ]
                top_tags = title_tags[:10]

            existing = existing_cluster_map.get(display_title) if not reset else None
            if existing:
                existing.core_tags = top_tags
                existing.fingerprint_count = len(component)
                clusters_to_update_basic.append(existing)
                cluster_update_data.append(
                    {
                        "cluster": existing,
                        "fp_ids": fp_ids,
                    }
                )
            else:
                cluster = AmazonThemeCluster(
                    display_title=display_title,
                    core_tags=top_tags,
                    fingerprint_count=len(component),
                )
                clusters_to_create.append(cluster)
                cluster_create_data.append(
                    {
                        "cluster": cluster,
                        "fp_ids": fp_ids,
                    }
                )

        logger.info(
            "[Stage 4] 新建 Cluster: %d, 更新 Cluster: %d",
            len(clusters_to_create),
            len(clusters_to_update_basic),
        )

        # ---------- 事务: 写入 DB ----------
        with transaction.atomic():
            ThemeFingerprint.objects.all().update(cluster=None)

            if reset:
                AmazonThemeCluster.objects.all().delete()
                logger.info("[Stage 4] 全量模式: 已清除旧 Cluster 数据")

            created_clusters = []
            if clusters_to_create:
                created_clusters = AmazonThemeCluster.objects.bulk_create(
                    clusters_to_create,
                    batch_size=BATCH_SIZE,
                )
                logger.info(
                    "[Stage 4] 创建 AmazonThemeCluster: %d 条",
                    len(created_clusters),
                )

            if clusters_to_update_basic:
                AmazonThemeCluster.objects.bulk_update(
                    clusters_to_update_basic,
                    ["core_tags", "fingerprint_count"],
                    batch_size=BATCH_SIZE,
                )
                logger.info(
                    "[Stage 4] 更新已有 Cluster 基础字段: %d 条",
                    len(clusters_to_update_basic),
                )

            for data, cluster in zip(cluster_create_data, created_clusters):
                batch_ids = data["fp_ids"]
                ThemeFingerprint.objects.filter(id__in=batch_ids).update(
                    cluster=cluster
                )

            for data in cluster_update_data:
                batch_ids = data["fp_ids"]
                ThemeFingerprint.objects.filter(id__in=batch_ids).update(
                    cluster=data["cluster"]
                )

            logger.info("[Stage 4] Fingerprint → Cluster 关联完成")

        # --- 事务已提交，现在并行统计 ---
        logger.info("[Stage 4] 开始统计 asin_count / burst_score")

        all_clusters_for_stats = created_clusters + clusters_to_update_basic

        def _compute_stats(cluster: AmazonThemeCluster):
            asin_qs = AmazonNewReleaseRank.objects.filter(fingerprint__cluster=cluster)
            asin_count = asin_qs.count()
            new_asin_7d = asin_qs.filter(launch_date__gte=seven_days_ago).count()
            burst_score = new_asin_7d / asin_count if asin_count > 0 else 0.0
            cluster.asin_count = asin_count
            cluster.new_asin_7d = new_asin_7d
            cluster.burst_score = round(burst_score, 4)
            cluster.asin_change = _calculate_asin_change(
                cluster.display_title,
                asin_count,
            )

            if not reset:
                old = existing_cluster_map.get(cluster.display_title)
                if old and (
                    cluster.asin_count == old.asin_count
                    and cluster.new_asin_7d == old.new_asin_7d
                    and cluster.burst_score == old.burst_score
                ):
                    cluster.updated_at = old.updated_at
                    return cluster

            cluster.updated_at = run_timestamp
            return cluster

        def _fallback_stats(cluster: AmazonThemeCluster):
            cluster.asin_count = 0
            cluster.new_asin_7d = 0
            cluster.burst_score = 0.0
            cluster.asin_change = _calculate_asin_change(
                cluster.display_title,
                0,
            )
            cluster.updated_at = run_timestamp

        clusters_to_update_stats: list[AmazonThemeCluster] = []
        n_workers = min(self._n_workers, max(1, len(all_clusters_for_stats) // 4))
        if n_workers > 1 and len(all_clusters_for_stats) > 20:
            with ThreadPoolExecutor(max_workers=n_workers) as pool:
                futures = {
                    pool.submit(_compute_stats, c): c
                    for c in all_clusters_for_stats
                }
                for future in as_completed(futures):
                    try:
                        clusters_to_update_stats.append(future.result())
                    except Exception as exc:
                        logger.warning("[Stage 4] 统计失败: %s", exc)
                        c = futures[future]
                        _fallback_stats(c)
                        clusters_to_update_stats.append(c)
        else:
            for cluster in all_clusters_for_stats:
                clusters_to_update_stats.append(_compute_stats(cluster))

        if clusters_to_update_stats:
            AmazonThemeCluster.objects.bulk_update(
                clusters_to_update_stats,
                [
                    "asin_count",
                    "new_asin_7d",
                    "burst_score",
                    "asin_change",
                    "updated_at",
                ],
                batch_size=BATCH_SIZE,
            )
            logger.info(
                "[Stage 4] 统计字段更新完成: %d 条 Cluster",
                len(clusters_to_update_stats),
            )

    # ==================================================================
    #  全量重置
    # ==================================================================

    @staticmethod
    def _reset_all_data():
        logger.info("[Reset] 开始全量重置...")

        with transaction.atomic():
            AmazonNewReleaseRank.objects.all().update(denoising=False, fingerprint=None)
            ThemeFingerprint.objects.all().delete()
            AmazonThemeCluster.objects.all().delete()

        logger.info("[Reset] 全量重置完成")


def _nr_count_ngrams_worker(
    texts: list[str],
) -> tuple[Counter, Counter, Counter, int]:
    unigram_freq: Counter = Counter()
    bigram_freq: Counter = Counter()
    trigram_freq: Counter = Counter()
    total_unigrams = 0

    for text in texts:
        words = text.split()
        if not words:
            continue
        total_unigrams += len(words)
        unigram_freq.update(words)
        for bg in zip(words, words[1:]):
            bigram_freq[bg] += 1
        for tg in zip(words, words[1:], words[2:]):
            trigram_freq[tg] += 1

    return unigram_freq, bigram_freq, trigram_freq, total_unigrams
