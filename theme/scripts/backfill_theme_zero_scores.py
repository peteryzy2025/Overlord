import argparse
import os
import re
from collections import defaultdict
from datetime import date, datetime

import psycopg2
from nltk.corpus import stopwords
from nltk.stem import PorterStemmer


DEFAULT_DB_HOST = os.getenv("THEME_DB_HOST", "192.168.110.54")
DEFAULT_DB_PORT = os.getenv("THEME_DB_PORT", "5432")
DEFAULT_DB_NAME = os.getenv("THEME_DB_NAME", "overlord_db")
DEFAULT_DB_USER = os.getenv("THEME_DB_USER", "user1")
DEFAULT_DB_PASS = os.getenv("THEME_DB_PASS", "user555Y1")
_stemmer = PorterStemmer()
try:
    _stop_words = set(stopwords.words("english"))
except Exception:
    _stop_words = set()


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

            rep = min(component, key=lambda t: (-len(theme_to_asins.get(t, ())), t))
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
        if isinstance(value, date):
            return value
        s = str(value).strip()
        if not s:
            return None
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
            try:
                return datetime.strptime(s, fmt).date()
            except Exception:
                continue
        return None

    def calculate_score(self, count, launch_date, rank, reference_date):
        try:
            c = int(count)
        except Exception:
            c = 0

        count_score = 5 if c > 10 else 4 if c > 6 else 3 if c > 3 else 2 if c > 1 else 1

        listing_date = self._parse_ymd_date(launch_date)
        if listing_date is None:
            time_score = 1
        else:
            days_diff = (reference_date - listing_date).days
            time_score = 5 if days_diff <= 1 else 4 if days_diff <= 3 else 3 if days_diff <= 7 else 2 if days_diff <= 15 else 1

        rank_score = 5 if rank not in (None, "") else 0
        return count_score + time_score + rank_score


class ThemeScoreBackfiller:
    def __init__(self, conn):
        self.conn = conn
        self.analyzer = ThemeAnalyzer()

    def get_dates_with_zero_scores(self, include_today=False, specified_dates=None):
        if specified_dates:
            return [datetime.strptime(item, "%Y-%m-%d").date() for item in specified_dates]

        sql = """
        SELECT DISTINCT crawl_date
        FROM theme_daily_data
        WHERE score = 0
        """
        params = []
        if not include_today:
            sql += " AND crawl_date < CURRENT_DATE"
        sql += " ORDER BY crawl_date"

        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            return [row[0] for row in cur.fetchall()]

    def fetch_rows_for_date(self, crawl_date):
        sql = """
        SELECT d.product_id, n.subject, n.launch_date, d.rank
        FROM theme_daily_data d
        LEFT JOIN theme_amazon_novelty n ON n.asin = d.product_id
        WHERE d.crawl_date = %s
        """
        with self.conn.cursor() as cur:
            cur.execute(sql, (crawl_date,))
            return cur.fetchall()

    def build_counts(self, rows):
        asin_to_meta = {}
        asin_subject_pairs = []
        blank_subject_asins = []

        for row in rows:
            if not row or not row[0]:
                continue
            asin, subject, launch_date, rank = row
            asin_to_meta[asin] = (launch_date, rank)
            if subject is None or not str(subject).strip():
                blank_subject_asins.append(asin)
            else:
                asin_subject_pairs.append((asin, subject))

        grouped = {}
        if asin_subject_pairs:
            grouped.update(self.analyzer.group_asins_by_fuzzy_theme(asin_subject_pairs))

        asin_to_count = {}
        for _, (asin_list, count) in grouped.items():
            for asin in asin_list:
                asin_to_count[asin] = count

        return asin_to_count, asin_to_meta, len(blank_subject_asins)

    def update_date(self, crawl_date, dry_run=False):
        rows = self.fetch_rows_for_date(crawl_date)
        if not rows:
            return {"crawl_date": crawl_date, "row_count": 0, "updated": 0, "blank_subject_count": 0}

        asin_to_count, asin_to_meta, blank_subject_count = self.build_counts(rows)
        asin_to_score = {}
        for asin, count in asin_to_count.items():
            launch_date, rank = asin_to_meta.get(asin, (None, None))
            asin_to_score[asin] = self.analyzer.calculate_score(count, launch_date, rank, crawl_date)

        if dry_run:
            return {
                "crawl_date": crawl_date,
                "row_count": len(rows),
                "updated": len(asin_to_count),
                "blank_subject_count": blank_subject_count,
            }

        update_sql = """
        UPDATE theme_daily_data
        SET appear_count = %s, score = %s
        WHERE crawl_date = %s AND product_id = %s
        """
        data = [
            (asin_to_count[asin], asin_to_score.get(asin, 0), crawl_date, asin)
            for asin in asin_to_count.keys()
        ]
        with self.conn.cursor() as cur:
            cur.executemany(update_sql, data)

        self.conn.commit()
        return {
            "crawl_date": crawl_date,
            "row_count": len(rows),
            "updated": len(data),
            "blank_subject_count": blank_subject_count,
        }


def build_parser():
    parser = argparse.ArgumentParser(description="回填历史 score=0 的 theme_daily_data 分数。")
    parser.add_argument("--host", default=DEFAULT_DB_HOST)
    parser.add_argument("--port", default=DEFAULT_DB_PORT)
    parser.add_argument("--database", default=DEFAULT_DB_NAME)
    parser.add_argument("--user", default=DEFAULT_DB_USER)
    parser.add_argument("--password", default=DEFAULT_DB_PASS)
    parser.add_argument("--include-today", action="store_true", help="包含今天仍为 0 分的数据。")
    parser.add_argument("--dates", nargs="+", help="只处理指定日期，格式 YYYY-MM-DD。")
    parser.add_argument("--dry-run", action="store_true", help="只打印将要处理的数据，不写库。")
    return parser


def main():
    args = build_parser().parse_args()
    conn = psycopg2.connect(
        host=args.host,
        port=args.port,
        database=args.database,
        user=args.user,
        password=args.password,
    )
    backfiller = ThemeScoreBackfiller(conn)

    try:
        crawl_dates = backfiller.get_dates_with_zero_scores(
            include_today=args.include_today,
            specified_dates=args.dates,
        )
        if not crawl_dates:
            print("没有找到需要回填的日期。")
            return

        print(f"待处理日期共 {len(crawl_dates)} 个: {', '.join(str(item) for item in crawl_dates)}")
        total_rows = 0
        total_updated = 0

        for crawl_date in crawl_dates:
            result = backfiller.update_date(crawl_date, dry_run=args.dry_run)
            total_rows += result["row_count"]
            total_updated += result["updated"]
            print(
                f"crawl_date={result['crawl_date']} row_count={result['row_count']} "
                f"updated={result['updated']} blank_subject_count={result['blank_subject_count']}"
            )

        action = "预计回填" if args.dry_run else "已回填"
        print(f"{action}完成: dates={len(crawl_dates)} rows={total_rows} updated={total_updated}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
