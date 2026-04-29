# %%
import logging
import re
from collections import defaultdict
from datetime import datetime

import psycopg2
from nltk.corpus import stopwords
from nltk.stem import PorterStemmer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("theme_aggregation.log", mode="a", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("theme_aggregation")

DB_HOST = "192.168.110.54"
DB_PORT = "5432"
DB_NAME = "overlord_db"
DB_USER = "user1"
DB_PASS = "user555Y1"

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
        pass


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
    db_manager = DatabaseManager()
    try:
        today_str = datetime.now().strftime("%Y-%m-%d")
        analyze_themes_for_dates(db_manager, {today_str})
    finally:
        db_manager.close()


if __name__ == "__main__":
    main()
