# %%
import ctypes
import logging
import os
import random
import re
import sys
import time
from collections import defaultdict
from datetime import datetime

import psutil
import psycopg2
from DrissionPage import ChromiumOptions, ChromiumPage
from nltk.corpus import stopwords
from nltk.stem import PorterStemmer
from openai import OpenAI

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("amazon_crawler_2.log", mode="w", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("amazon_new_release_crawler")


DB_HOST = "192.168.110.54"
DB_PORT = "5432"
DB_NAME = "overlord_db"
DB_USER = "user1"
DB_PASS = "user555Y1"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "sk-d84933834d374be9a7d814d79cbcad6e")
OPENAI_BASE_URL = os.getenv(
    "OPENAI_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
)
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "qwen-plus")

CUSTOM_PROFILE = r"D:\software\Data\chrome_profile"
SELLER_SPRITE_HINTS = ("卖家精灵", "市场分析", "查看Top400产品", "关键词反查")

_stemmer = PorterStemmer()
try:
    _stop_words = set(stopwords.words("english"))
except Exception:
    _stop_words = set()


class DatabaseManager:
    def __init__(self):
        self.conn = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASS,
        )
        self.cursor = self.conn.cursor()

    def close(self):
        if self.cursor:
            self.cursor.close()
        if self.conn:
            self.conn.close()

    def commit(self):
        self.conn.commit()

    def rollback(self):
        self.conn.rollback()

    def get_existing_product(self, asin):
        self.cursor.execute(
            """
            SELECT asin, title_translation, subject, subject_translation
            FROM theme_amazon_new_release_rank
            WHERE asin = %s
            """,
            (asin,),
        )
        row = self.cursor.fetchone()
        if not row:
            return None
        return {
            "asin": row[0],
            "title_translation": row[1] or "",
            "subject": row[2] or "",
            "subject_translation": row[3] or "",
        }

    def insert_theme_amazon_new_release_rank(
        self,
        asin,
        title,
        title_translation,
        subject,
        subject_translation,
        category,
        image_url,
        launch_date,
        crawl_at,
        fulfillment="",
    ):
        self.cursor.execute(
            """
            INSERT INTO theme_amazon_new_release_rank (
                asin,
                title,
                title_translation,
                subject,
                subject_translation,
                category,
                image_url,
                launch_date,
                fulfillment,
                created_at,
                updated_at,
                report
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, FALSE)
            ON CONFLICT (asin) DO UPDATE SET
                title = EXCLUDED.title,
                title_translation = EXCLUDED.title_translation,
                subject = EXCLUDED.subject,
                subject_translation = EXCLUDED.subject_translation,
                category = EXCLUDED.category,
                image_url = EXCLUDED.image_url,
                launch_date = EXCLUDED.launch_date,
                fulfillment = EXCLUDED.fulfillment,
                updated_at = EXCLUDED.updated_at
            RETURNING asin
            """,
            (
                asin,
                title,
                title_translation,
                subject,
                subject_translation,
                category,
                image_url,
                launch_date,
                fulfillment,
                crawl_at,
                crawl_at,
            ),
        )
        return self.cursor.fetchone()[0]

    def insert_theme_new_daily_data(self, asin, crawl_date, rank_pairs, crawl_at):
        normalized_pairs = list(rank_pairs[:3])
        while len(normalized_pairs) < 3:
            normalized_pairs.append((None, None))

        values = [
            crawl_date,
            normalized_pairs[0][1],
            normalized_pairs[0][0],
            normalized_pairs[1][1],
            normalized_pairs[1][0],
            normalized_pairs[2][1],
            normalized_pairs[2][0],
            crawl_at,
            asin,
        ]
        self.cursor.execute(
            """
            INSERT INTO theme_new_daily_data (
                crawl_date,
                rank,
                rank_category,
                rank2,
                rank_category2,
                rank3,
                rank_category3,
                crawled_at,
                product_id,
                appear_count,
                score
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 1, 0)
            ON CONFLICT (crawl_date, product_id) DO UPDATE SET
                rank = EXCLUDED.rank,
                rank_category = EXCLUDED.rank_category,
                rank2 = EXCLUDED.rank2,
                rank_category2 = EXCLUDED.rank_category2,
                rank3 = EXCLUDED.rank3,
                rank_category3 = EXCLUDED.rank_category3,
                crawled_at = EXCLUDED.crawled_at,
                appear_count = theme_new_daily_data.appear_count + 1
            RETURNING crawl_date, product_id
            """,
            values,
        )
        return self.cursor.fetchone()

    def fetch_theme_rows_for_date(self, crawl_date):
        self.cursor.execute(
            """
            SELECT d.product_id, p.subject, p.launch_date, d.rank
            FROM theme_new_daily_data d
            JOIN theme_amazon_new_release_rank p ON p.asin = d.product_id
            WHERE d.crawl_date = %s
            """,
            (crawl_date,),
        )
        return self.cursor.fetchall()

    def update_theme_new_daily_counts_and_scores(
        self, crawl_date, asin_to_count, asin_to_score
    ):
        if not asin_to_count:
            return 0
        data = [
            (asin_to_count[asin], asin_to_score.get(asin, 0), crawl_date, asin)
            for asin in asin_to_count.keys()
        ]
        self.cursor.executemany(
            """
            UPDATE theme_new_daily_data
            SET appear_count = %s,
                score = %s
            WHERE crawl_date = %s
              AND product_id = %s
            """,
            data,
        )
        return len(data)

    def sync_summary_subjects(self):
        """
        将 theme_amazon_new_release_rank 中的 subject_translation
        归类到 theme_summary 表，相似度阈值 0.2
        """
        try:
            # 获取所有待处理的"孤儿"翻译
            self.cursor.execute("""
                SELECT subject_translation, COUNT(*) as cnt
                FROM theme_amazon_new_release_rank
                WHERE summary_subject_id IS NULL
                GROUP BY subject_translation
            """)
            orphans = self.cursor.fetchall()

            if not orphans:
                logger.info("没有发现新的待分类主题")
                return 0

            updated_count = 0
            for row in orphans:
                text = row[0]

                # 尝试在现有 theme_summary 中寻找匹配（相似度 > 0.2）
                self.cursor.execute(
                    """
                    SELECT id FROM theme_summary
                    WHERE similarity(summary_subject_title, %s) > 0.2
                    ORDER BY similarity(summary_subject_title, %s) DESC
                    LIMIT 1
                """,
                    (text, text),
                )
                match = self.cursor.fetchone()

                if match:
                    target_id = match[0]
                    logger.debug(f"匹配成功: '{text}' -> ID {target_id}")
                else:
                    # 新建聚类中心
                    self.cursor.execute(
                        """
                        INSERT INTO theme_summary (summary_subject_title, report, created_time)
                        VALUES (%s, FALSE, NOW()) RETURNING id
                    """,
                        (text,),
                    )
                    result = self.cursor.fetchone()
                    target_id = result[0]
                    logger.info(f"新建主题: '{text}' (ID {target_id})")

                # 回填关联 ID
                self.cursor.execute(
                    """
                    UPDATE theme_amazon_new_release_rank
                    SET summary_subject_id = %s
                    WHERE subject_translation = %s AND summary_subject_id IS NULL
                """,
                    (target_id, text),
                )
                updated_count += self.cursor.rowcount

            self.commit()
            logger.info(
                f"主题归类完成，共处理 {len(orphans)} 个主题，更新 {updated_count} 条记录"
            )
            return updated_count

        except Exception as e:
            self.rollback()
            logger.error(f"主题归类失败: {e}")
            raise


class ContentProcessor:
    def __init__(self):
        self.client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)

    def _call_openai(self, messages, model=OPENAI_MODEL):
        try:
            response = self.client.chat.completions.create(
                model=model, messages=messages
            )
            content = response.choices[0].message.content or ""
            return str(content).strip()
        except Exception as exc:
            logger.warning(f"OpenAI调用失败: {exc}")
            return ""

    def recognize_text_from_title(self, title):
        prompt = f"""Please extract the core thematic phrase from the product title following these rules:
1. Focus on phrases near product terms but exclude the product word itself.
2. Ignore product types, audiences, colors, materials, specifications, and printing-related terms.
3. When multiple candidates exist:
   a) choose longer phrases
   b) prioritize semantically complete phrases
   c) prefer complete sentence segments
4. Remove any remaining product terms before output.
Output only the final English phrase without explanations.

Title: {title}"""
        return self._call_openai([{"role": "user", "content": prompt}])

    def translate_subject(self, subject):
        prompt = f"""请将以下亚马逊产品主题标签从英文翻译成简洁自然的中文，不加引号，不加解释，只输出中文：

{subject}"""
        return self._call_openai([{"role": "user", "content": prompt}])

    def translate_title(self, title):
        prompt = f"""请将以下亚马逊产品标题翻译成自然、完整的中文标题，不加引号，不加解释，只输出中文：

{title}"""
        return self._call_openai([{"role": "user", "content": prompt}])

    def normalize_subject(self, subject):
        text = str(subject or "").strip()
        text = re.sub(r"[\"“”`]+", "", text)
        text = re.sub(r"\s*&\s*", " & ", text)
        text = re.sub(r"[^A-Za-z0-9\s'&/+\-#.]", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def is_invalid_subject(self, subject):
        value = str(subject or "").strip().lower()
        return value in {"", "just graphic", "no text", "识别失败", "图片获取失败"}

    def build_metadata(self, title, existing=None):
        existing = existing or {}
        title_translation = existing.get("title_translation", "").strip()
        subject = existing.get("subject", "").strip()
        subject_translation = existing.get("subject_translation", "").strip()

        if not title_translation:
            title_translation = self.translate_title(title)
        if not subject:
            subject = self.normalize_subject(self.recognize_text_from_title(title))
        if self.is_invalid_subject(subject):
            subject = self.normalize_subject(title[:200])
        if not subject_translation:
            subject_translation = self.translate_subject(subject)

        if not title_translation:
            title_translation = title[:500]
        if not subject_translation:
            subject_translation = subject[:200]

        return {
            "title_translation": title_translation[:500],
            "subject": subject[:200],
            "subject_translation": subject_translation[:200],
        }


class ThemeAnalyzer:
    def __init__(self, stemmer=_stemmer, stop_words=_stop_words):
        self.stemmer = stemmer
        self.stop_words = stop_words

    def preprocess_phrase(self, phrase, keep_stopwords=False):
        phrase = phrase.lower()
        words = re.findall(r"\b[\w'-]+\b", phrase)
        if keep_stopwords:
            keep_words = words
        else:
            filtered_words = [word for word in words if word not in self.stop_words]
            keep_words = filtered_words if filtered_words else words

        processed_words = []
        for word in keep_words:
            if word.endswith("ly"):
                word = word[:-2]
            processed_words.append(self.stemmer.stem(word))
        return set(processed_words)

    def fuzzy_match_all_themes(self, all_themes):
        theme_sets = {}
        theme_lengths = {}

        for theme in all_themes:
            words = re.findall(r"\b[\w'-]+\b", theme.lower())
            orig_len = len(words)
            theme_lengths[theme] = orig_len
            keep_stopwords = orig_len < 3
            theme_sets[theme] = self.preprocess_phrase(theme, keep_stopwords)

        inverted_index = defaultdict(list)
        for theme, words in theme_sets.items():
            for word in words:
                inverted_index[word].append(theme)

        matches_dict = {}
        for theme, words in theme_sets.items():
            candidate_themes = set()
            for word in words:
                candidate_themes.update(inverted_index[word])

            matched = []
            len_theme = len(words)
            orig_len = theme_lengths[theme]

            for cand in candidate_themes:
                if cand == theme:
                    matched.append(theme)
                    continue

                cand_set = theme_sets[cand]
                len_cand = len(cand_set)
                max_len = max(len_theme, len_cand)

                if orig_len < 3:
                    if words == cand_set:
                        matched.append(cand)
                    continue

                if max_len > 12:
                    if abs(len_theme - len_cand) > 2:
                        continue
                elif max_len > 6:
                    if abs(len_theme - len_cand) > 1:
                        continue

                intersection = len(words & cand_set)
                if max_len > 12:
                    if intersection >= max_len - 2:
                        matched.append(cand)
                elif max_len > 6:
                    if intersection >= max_len - 1:
                        matched.append(cand)
                else:
                    if words == cand_set:
                        matched.append(cand)

            matches_dict[theme] = matched

        return matches_dict

    def group_asins_by_fuzzy_theme(self, asin_subject_pairs):
        theme_to_asins = defaultdict(set)
        for asin, subject in asin_subject_pairs:
            if asin and subject:
                theme_to_asins[subject].add(asin)

        if not theme_to_asins:
            return {}

        unique_themes = list(theme_to_asins.keys())
        matches_dict = self.fuzzy_match_all_themes(unique_themes)

        adjacency = defaultdict(set)
        for theme, matched_list in matches_dict.items():
            for cand in matched_list:
                adjacency[theme].add(cand)
                adjacency[cand].add(theme)

        seen = set()
        rep_to_themes = {}
        for theme in unique_themes:
            if theme in seen:
                continue
            stack = [theme]
            component = set()
            seen.add(theme)
            while stack:
                cur = stack.pop()
                component.add(cur)
                for nxt in adjacency.get(cur, ()):
                    if nxt not in seen:
                        seen.add(nxt)
                        stack.append(nxt)

            rep = min(
                component, key=lambda item: (-len(theme_to_asins.get(item, ())), item)
            )
            rep_to_themes[rep] = component

        result = {}
        for rep, themes in rep_to_themes.items():
            asins = set()
            for theme in themes:
                asins.update(theme_to_asins.get(theme, ()))
            asin_list = sorted(asins)
            result[rep] = (asin_list, len(asin_list))
        return result

    def _parse_ymd_date(self, value):
        if not value:
            return None
        if isinstance(value, datetime):
            return value.date()
        value = str(value).strip()
        if not value:
            return None
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
            try:
                return datetime.strptime(value, fmt).date()
            except Exception:
                continue
        return None

    def calculate_score(self, count, launch_date, rank):
        try:
            count_value = int(count)
        except Exception:
            count_value = 0

        count_score = (
            5
            if count_value > 10
            else 4
            if count_value > 6
            else 3
            if count_value > 3
            else 2
            if count_value > 1
            else 1
        )

        today = datetime.now().date()
        listing_date = self._parse_ymd_date(launch_date)
        if listing_date is None:
            time_score = 1
        else:
            days_diff = (today - listing_date).days
            time_score = (
                5
                if days_diff <= 1
                else 4
                if days_diff <= 3
                else 3
                if days_diff <= 7
                else 2
                if days_diff <= 15
                else 1
            )

        rank_score = 5 if rank not in (None, "") else 0
        return count_score + time_score + rank_score


def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False


# if not is_admin():
#     ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, " ".join(sys.argv), None, 1)
#     sys.exit()


def get_created_time():
    return datetime.now()


def parse_listing_date(raw_value):
    text = str(raw_value or "").strip()
    if not text:
        return None
    match = re.search(r"(\d{4}[-/]\d{2}[-/]\d{2})", text)
    if not match:
        return None
    value = match.group(1).replace("/", "-")
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except Exception:
        return None


def normalize_rank(rank_value):
    if rank_value in (None, ""):
        return None
    try:
        return int(str(rank_value).replace(",", "").strip())
    except Exception:
        return None


def safe_text(element):
    if not element:
        return ""
    try:
        return str(element.text).strip()
    except Exception:
        return ""


def extract_asin(card):
    try:
        asin = (card.attr("data-asin") or "").strip()
        if asin:
            return asin
    except Exception:
        pass

    try:
        data_asin_ele = card.ele("css:[data-asin]", timeout=0.2)
        asin = (data_asin_ele.attr("data-asin") or "").strip()
        if asin:
            return asin
    except Exception:
        pass

    try:
        text = card.text
        match = re.search(r"ASIN[:：]\s*([A-Z0-9]{10})", text)
        return match.group(1) if match else ""
    except Exception:
        return ""


def extract_label_value(card, label):
    try:
        label_ele = card.ele(f"text:{label}", timeout=0.2)
        if label_ele:
            return safe_text(label_ele.next())
    except Exception:
        pass
    return ""


def extract_shipping_type(card):
    """
    提取配送方式：AMZ / FBA / FBM
    返回: "AMZ" | "FBA" | "FBM" | ""
    """
    try:
        offers_btn = card.ele("css:.offers-button", timeout=0.2)
        if offers_btn:
            text = offers_btn.text.strip()
            if "配送:" in text:
                shipping_type = text.replace("配送:", "").strip()
                if shipping_type in ("AMZ", "FBA", "FBM"):
                    return shipping_type
    except Exception:
        pass
    return ""


def extract_rank_pairs(card):
    pairs = []
    seen = set()

    try:
        rank_items = card.eles("css:.rank-number-box .bsr-list-item")
    except Exception:
        rank_items = []

    for rank_item in rank_items:
        text = safe_text(rank_item)
        if not text:
            continue
        match = re.search(r"#([\d,]+)\s+in\s+(.+)", text)
        if not match:
            continue
        rank_value = normalize_rank(match.group(1))
        category = match.group(2).strip()
        key = (category, rank_value)
        if key in seen:
            continue
        seen.add(key)
        pairs.append((category, rank_value))

    if not pairs:
        text = safe_text(card)
        for rank_text, category in re.findall(r"#([\d,]+)\s+in\s+([^\n]+)", text):
            rank_value = normalize_rank(rank_text)
            key = (category.strip(), rank_value)
            if key in seen:
                continue
            seen.add(key)
            pairs.append((category.strip(), rank_value))

    return pairs[:3]


def verify_seller_sprite_loaded(page, timeout=20):
    end_time = time.time() + timeout
    while time.time() < end_time:
        try:
            if page.ele("css:.quick-view.quick-view-ext", timeout=1):
                return True
            for hint in SELLER_SPRITE_HINTS:
                if page.ele(f"text:{hint}", timeout=0.5):
                    return True
        except Exception:
            pass
        time.sleep(1)
    return False


def check_amazon_error_page(page):
    try:
        error_check = page.ele(
            'xpath://img[@alt and contains(@alt, "Sorry! Something went wrong on our end")]',
            timeout=2,
        )
        if error_check:
            logger.warning("检测到亚马逊错误页")
            return True
    except Exception:
        pass
    return False


def _scroll_until_next_btn_stable(page, stable_times=3, max_wait=60):
    try:
        if page.ele(
            "text:Request was throttled. Please wait a moment and refresh the page",
            timeout=2,
        ):
            logger.warning("检测到限速提示，刷新页面")
            page.refresh()
            time.sleep(random.uniform(3, 5))

        next_btn = page.ele("css:.a-last", timeout=10)
        if not next_btn:
            for _ in range(3):
                page.scroll.to_bottom()
                time.sleep(random.uniform(1.0, 1.5))
            return

        last_y = next_btn.rect.location[1]
        stable_cnt = 0
        start_ts = time.time()
        while True:
            page.scroll.to_see(next_btn)
            time.sleep(random.uniform(1.2, 2.2))
            try:
                page.wait.eles_loaded("css:.zg-no-numbers", timeout=10)
            except Exception:
                pass
            try:
                cur_y = next_btn.rect.location[1]
            except Exception:
                break

            if abs(cur_y - last_y) <= 10:
                stable_cnt += 1
            else:
                stable_cnt = 0
            last_y = cur_y

            if stable_cnt >= stable_times or (time.time() - start_ts) > max_wait:
                break
    except Exception as exc:
        logger.error(f"滚动过程中出错: {exc}")
        for _ in range(3):
            page.scroll.to_bottom()
            time.sleep(1)


def scrape_amazon_products(page, keyword):
    if page.ele(
        "text:Request was throttled. Please wait a moment and refresh the page",
        timeout=2,
    ):
        logger.warning("触发限速，等待后刷新")
        time.sleep(random.uniform(5, 10))
        page.refresh()

    try:
        page.wait.eles_loaded("css:.zg-no-numbers", timeout=20)
    except Exception:
        logger.warning("等待基础商品卡片超时，继续尝试")

    if not verify_seller_sprite_loaded(page):
        logger.warning("未检测到卖家精灵增强元素，页面字段可能不完整")

    _scroll_until_next_btn_stable(page)

    goods_cards = page.eles("css:.zg-no-numbers")
    if not goods_cards:
        goods_cards = page.eles("css:li.zg-item-immersion")

    logger.info(f"整页加载完成，共 {len(goods_cards)} 个商品卡片")

    products = []
    for card in goods_cards:
        try:
            asin = extract_asin(card)
            if not asin:
                continue

            img_ele = card.ele("css:.a-dynamic-image", timeout=0.2)
            img_url = (img_ele.attr("src") or "").strip() if img_ele else ""
            title = (img_ele.attr("alt") or "").strip() if img_ele else ""
            if not title:
                title_ele = card.ele("tag:a", timeout=0.2)
                title = safe_text(title_ele)

            brand_name = extract_label_value(card, "品牌:")
            shop_name = extract_label_value(card, "卖家:")
            listing_time_raw = extract_label_value(card, "上架时间:")
            launch_date = parse_listing_date(listing_time_raw)
            rank_pairs = extract_rank_pairs(card)
            shipping_type = extract_shipping_type(card)

            products.append(
                {
                    "asin": asin,
                    "brand_name": brand_name,
                    "shop_name": shop_name,
                    "title": title[:500],
                    "image_url": img_url[:500],
                    "category": keyword,
                    "launch_date": launch_date,
                    "listing_time_raw": listing_time_raw,
                    "rank_pairs": rank_pairs,
                    "fulfillment": shipping_type,
                }
            )
        except Exception as exc:
            logger.error(f"处理单个商品卡片时出错: {exc}")
            continue

    return products


def wait_page_stable(page, expected_page, timeout=30):
    start = time.time()
    while time.time() - start < timeout:
        if page.ele(
            "text:Request was throttled. Please wait a moment and refresh the page",
            timeout=1,
        ):
            time.sleep(random.uniform(3, 5))
            page.refresh()
            continue

        actual = get_current_page(page)
        if actual != expected_page:
            time.sleep(0.5)
            continue

        cards = page.eles("css:.zg-no-numbers")
        if len(cards) >= 30:
            return True
        time.sleep(0.5)

    cards = page.eles("css:.zg-no-numbers")
    if len(cards) > 0:
        logger.info(f"页面加载超时，但已有{len(cards)}个商品，继续")
        return True
    return False


def go_to_next_page(page):
    try:
        next_btn = page.ele("css:.a-last", timeout=15)
        if not next_btn:
            return False
        next_page = get_current_page(page) + 1
        next_btn.click()
        time.sleep(random.uniform(2, 3))
        return wait_page_stable(page, next_page)
    except Exception as exc:
        logger.debug(f"翻页操作异常：{str(exc)[:100]}")
        return False


def get_current_page(page):
    try:
        current_page_element = page.ele("css:.a-selected", timeout=2)
        if current_page_element:
            return int(safe_text(current_page_element))
        match = re.search(r"[?&]pg=(\d+)", page.url)
        return int(match.group(1)) if match else 1
    except Exception as exc:
        logger.warning(f"获取页码失败: {exc}")
        return 1


def force_turn_page(page, current):
    try:
        url_prefix = re.sub(r"&(?:pg)=?\d+", "", page.url)
        next_page_url = f"{url_prefix}&pg={current + 1}"
        page.get(next_page_url)
        return True
    except Exception:
        return False


def smart_page_turner(page, current_page, max_retries=3):
    for retry_idx in range(max_retries):
        if go_to_next_page(page):
            return get_current_page(page)
        logger.debug(f"第{retry_idx + 1}次翻页失败，重试")
        time.sleep(random.uniform(3, 5))

    logger.info("翻页重试耗尽，尝试URL翻页")
    force_turn_page(page, current_page)
    return get_current_page(page)


def is_process_running(pid):
    try:
        psutil.Process(pid)
        return True
    except psutil.NoSuchProcess:
        return False


def terminate_chromium_by_pid(page):
    pid = page.process_id
    if is_process_running(pid):
        try:
            process = psutil.Process(pid)
            process.terminate()
            process.wait(timeout=5)
            logger.info(f"已关闭浏览器进程，PID：{pid}")
        except Exception as exc:
            logger.warning(f"关闭浏览器进程失败: {exc}")


def terminate_existing_processes(process_name):
    try:
        os.system(f"taskkill /IM {process_name} /F")
        logger.info(f"已终止所有 {process_name} 进程")
    except Exception as exc:
        logger.error(f"终止进程时出错: {exc}")


def create_browser_page(co, max_retries=5, delay=10):
    page = None
    for attempt in range(max_retries):
        try:
            page = ChromiumPage(co)
            if page is not None:
                logger.info(f"浏览器页面对象创建成功 ({attempt + 1}/{max_retries})")
                return page
        except Exception as exc:
            logger.error(f"尝试 {attempt + 1}/{max_retries} 创建浏览器失败: {exc}")
            if "port" in str(exc).lower() or "already in use" in str(exc).lower():
                terminate_existing_processes("chrome.exe")
            time.sleep(delay * (attempt + 1))
    logger.error(f"达到最大重试次数 ({max_retries})，无法创建浏览器页面对象")
    return page


def check_memory_usage(threshold=80):
    memory = psutil.virtual_memory()
    if memory.percent > threshold:
        logger.warning(f"内存使用过高 ({memory.percent}%)")
        return True
    return False


def handle_catastrophic_error(page, co):
    try:
        url = page.url
    except Exception:
        url = None

    try:
        page.quit()
        logger.warning("已关闭异常浏览器实例")
        time.sleep(3)
    except Exception as exc:
        logger.error(f"关闭浏览器异常：{exc}")
        terminate_existing_processes("chrome.exe")
        time.sleep(3)

    new_page = create_browser_page(co)
    if new_page and url:
        new_page.get(url)
        time.sleep(3)
    logger.info("浏览器实例重建完成")
    return new_page


def persist_product(db_manager, processor, product, crawl_at, crawl_date):
    existing = db_manager.get_existing_product(product["asin"])
    metadata = processor.build_metadata(product["title"], existing=existing)

    logger.info(
        f"[{crawl_at}][UPSERT] asin={product['asin']} category={product['category']} "
        f"launch_date={product['launch_date']} ranks={product['rank_pairs']}"
    )

    db_manager.insert_theme_amazon_new_release_rank(
        asin=product["asin"],
        title=product["title"],
        title_translation=metadata["title_translation"],
        subject=metadata["subject"],
        subject_translation=metadata["subject_translation"],
        category=product["category"],
        image_url=product["image_url"],
        launch_date=product["launch_date"],
        crawl_at=crawl_at,
        fulfillment=product.get("fulfillment", ""),
    )
    db_manager.insert_theme_new_daily_data(
        asin=product["asin"],
        crawl_date=crawl_date,
        rank_pairs=product["rank_pairs"],
        crawl_at=crawl_at,
    )


def crawl_one_link(page, url, keyword, page_num, co, db_manager, processor):
    max_retries = 3
    retry_count = 0
    crawl_dates = set()

    while retry_count < max_retries:
        try:
            if check_amazon_error_page(page):
                raise RuntimeError("Amazon error page detected")

            for attempt in range(3):
                try:
                    page.get(url)
                    time.sleep(5)
                    if page.url == url or "amazon.com" in page.url:
                        break
                except Exception as exc:
                    logger.warning(f"导航失败尝试 {attempt + 1}/3: {str(exc)[:100]}")
                    if attempt == 2:
                        logger.error(f"无法导航到 {keyword} 目标URL，跳过")
                        return crawl_dates, page
                    time.sleep((attempt + 1) * 3)

            if check_amazon_error_page(page):
                raise RuntimeError("Amazon error page detected after navigation")

            current_page = get_current_page(page)
            processed_pages = set()
            consecutive_failures = 0
            max_consecutive_failures = 5

            while current_page <= page_num:
                if check_amazon_error_page(page):
                    raise RuntimeError("Amazon error page detected during crawling")

                logger.info(f"开始爬取 {keyword} 第 {current_page} 页")
                products = scrape_amazon_products(page, keyword)

                if not products:
                    logger.warning(
                        f"{keyword} 第 {current_page} 页未抓到数据，刷新重试"
                    )
                    page.refresh()
                    time.sleep(random.uniform(3, 5))
                    continue

                crawl_at = get_created_time()
                crawl_date = crawl_at.date()
                crawl_dates.add(str(crawl_date))

                for product in products:
                    try:
                        persist_product(
                            db_manager, processor, product, crawl_at, crawl_date
                        )
                        db_manager.commit()
                    except Exception as exc:
                        db_manager.rollback()
                        logger.error(
                            f"产品入库失败 asin={product.get('asin')} err={exc}"
                        )

                processed_pages.add(current_page)

                now_url = page.url
                if current_page % 5 == 0 and check_memory_usage():
                    page = handle_catastrophic_error(page, co)
                    page.get(now_url)
                    time.sleep(5)

                if current_page == page_num:
                    logger.info(f"已到达目标页面 {page_num}，停止翻页")
                    current_page += 1
                    break

                previous_page = current_page
                current_page = smart_page_turner(page, current_page)

                if current_page == previous_page:
                    consecutive_failures += 1
                    logger.warning(f"连续翻页失败次数：{consecutive_failures}")
                    if consecutive_failures >= max_consecutive_failures:
                        logger.warning("触发系统级恢复")
                        page = handle_catastrophic_error(page, co)
                        current_page = get_current_page(page)
                        consecutive_failures = 0
                else:
                    consecutive_failures = 0

                if current_page in processed_pages:
                    logger.warning("检测到页码重复，强制推进")
                    page.get(
                        re.sub(r"&(?:pg)=?\d+", "", page.url)
                        + f"&pg={current_page + 1}"
                    )
                    current_page = get_current_page(page)

                logger.info(
                    f"当前进度：已处理 {len(processed_pages)} 页，正在第 {current_page} 页"
                )

            logger.info(f"爬取 {keyword} 完成")
            return crawl_dates, page

        except Exception as exc:
            if "Amazon error page detected" in str(exc):
                retry_count += 1
                logger.warning(f"遇到亚马逊错误页面，第 {retry_count} 次重试")
                try:
                    page.quit()
                except Exception:
                    terminate_existing_processes("chrome.exe")
                time.sleep(60)
                page = create_browser_page(co)
                if retry_count >= max_retries:
                    logger.error(f"爬取 {keyword} 达到最大重试次数，放弃")
                    return crawl_dates, page
            else:
                logger.error(f"爬取 {keyword} 时发生严重错误: {exc}")
                return crawl_dates, page
    return crawl_dates, page


def analyze_themes_for_dates(db_manager, crawl_dates):
    analyzer = ThemeAnalyzer()
    for crawl_date in sorted(crawl_dates):
        logger.info(f"开始更新 appear_count 和 score，crawl_date={crawl_date}")
        try:
            rows = db_manager.fetch_theme_rows_for_date(crawl_date)
        except Exception as exc:
            logger.error(f"读取主题数据失败 crawl_date={crawl_date}: {exc}")
            db_manager.rollback()
            continue

        if not rows:
            logger.info(f"crawl_date={crawl_date} 无可用主题数据")
            continue

        asin_subject_pairs = []
        asin_to_meta = {}
        for row in rows:
            asin, subject, launch_date, rank = row
            asin_to_meta[asin] = (launch_date, rank)
            if subject is None or not str(subject).strip():
                continue
            asin_subject_pairs.append((asin, str(subject).strip()))

        grouped = analyzer.group_asins_by_fuzzy_theme(asin_subject_pairs)
        if not grouped:
            logger.info(f"crawl_date={crawl_date} 无可用于计分的主题")
            continue

        asin_to_count = {}
        for _, (asin_list, count) in grouped.items():
            for asin in asin_list:
                asin_to_count[asin] = count

        asin_to_score = {}
        for asin, count in asin_to_count.items():
            launch_date, rank = asin_to_meta.get(asin, (None, None))
            asin_to_score[asin] = analyzer.calculate_score(count, launch_date, rank)

        try:
            updated = db_manager.update_theme_new_daily_counts_and_scores(
                crawl_date, asin_to_count, asin_to_score
            )
            db_manager.commit()
            logger.info(
                f"crawl_date={crawl_date} 的appear_count和score已更新，共计 {updated} 条记录"
            )
        except Exception as exc:
            db_manager.rollback()
            logger.error(
                f"crawl_date={crawl_date} 的appear_count和score更新失败: {exc}"
            )


def main():
    os.makedirs(CUSTOM_PROFILE, exist_ok=True)

    co = ChromiumOptions()
    co.set_user_data_path(CUSTOM_PROFILE)
    co.set_pref("credentials_enable_service", False)
    co.no_imgs(True)

    bootstrap_page = create_browser_page(co)
    if not bootstrap_page:
        raise RuntimeError("浏览器初始化失败")
    terminate_chromium_by_pid(bootstrap_page)
    time.sleep(5)
    page = create_browser_page(co)
    if not page:
        raise RuntimeError("浏览器重建失败")

    link_info = [
        {
            "url": "https://www.amazon.com/gp/new-releases/fashion/9056987011/ref=zg_bs_tab_t_fashion_bsnr",
            "keyword": "shirt",
            "page_num": 2,
        },
        {
            "url": "https://www.amazon.com/gp/new-releases/fashion/2474996011/ref=zg_bs_tab_t_fashion_bsnr",
            "keyword": "hat-mens",
            "page_num": 2,
        },
        {
            "url": "https://www.amazon.com/gp/new-releases/fashion/9057026011/ref=zg_bsnr_nav_fashion_6_9057019011",
            "keyword": "hat-news",
            "page_num": 2,
        },
        {
            "url": "https://www.amazon.com/gp/new-releases/fashion/9057019011/ref=zg_bs_tab_t_fashion_bsnr",
            "keyword": "pin",
            "page_num": 2,
        },
        {
            "url": "https://www.amazon.com/gp/new-releases/lawn-garden/14083111/ref=zg_bs_tab_t_lawn-garden_bsnr",
            "keyword": "sign",
            "page_num": 2,
        },
        {
            "url": "https://www.amazon.com/gp/new-releases/lawn-garden/553792/ref=zg_bsnr_nav_lawn-garden_2_14083111",
            "keyword": "flag",
            "page_num": 2,
        },
        {
            "url": "https://www.amazon.com/gp/new-releases/fashion/21557336011/ref=zg_bs_tab_t_fashion_bsnr",
            "keyword": "bag",
            "page_num": 2,
        },
        {
            "url": "https://www.amazon.com/gp/new-releases/kitchen/9302388011/ref=zg_bs_tab_t_kitchen_bsnr",
            "keyword": "cup",
            "page_num": 2,
        },
    ]

    db_manager = DatabaseManager()
    processor = ContentProcessor()
    crawl_dates = set()

    try:
        for item in link_info:
            url = item["url"]
            keyword = item["keyword"]
            page_num = item["page_num"]
            logger.info(f"开始采集 {keyword} 前 {page_num} 页")
            current_dates, page = crawl_one_link(
                page, url, keyword, page_num, co, db_manager, processor
            )
            crawl_dates.update(current_dates)

        # 主题归类：将 subject_translation 归类到 theme_summary 表
        logger.info("开始主题归类...")
        db_manager.sync_summary_subjects()

        analyze_themes_for_dates(
            db_manager, crawl_dates or {datetime.now().strftime("%Y-%m-%d")}
        )
    finally:
        try:
            page.quit()
        except Exception:
            terminate_existing_processes("chrome.exe")
        db_manager.close()


if __name__ == "__main__":
    main()
