"""
ABA CSV 数据导入脚本

将 ABA 搜索词报告从 CSV 导入到 PostgreSQL (aba_db)
功能特性：
- pandas 分块读取大文件（1.4GB+）
- usecols 过滤无用列，节省内存
- 噪声词过滤（AC 自动机，O(n) 匹配）
- 批量插入（每批 5000 条）
- 环比排名预计算（一次性加载上周排名）
- 品类自动识别
- 进度条显示
- 自动更新 AbaReportWeek 记录

使用方法：
    python sync_import_to_db_csv.py
"""

import os
import sys
import re
import time
import importlib
import django
from pathlib import Path
from datetime import datetime, timedelta
from decimal import Decimal
from typing import List, Dict, Tuple

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Overlord.settings')
django.setup()

import pandas as pd
from tqdm import tqdm
from django.db import transaction, connections
from aba.models import SearchTerm, SearchTermMetric, AbaReportWeek, AbaNoiseWord

CSV_DIR = Path(__file__).parent / "json"

CSV_USECOLS = [
    '搜索频率排名', '搜索词',
    '点击量最高的商品 #1：ASIN', '点击量最高的商品 #1：商品名称',
    '点击量最高的商品 #1：点击份额', '点击量最高的商品 #1：转化份额',
    '点击量最高的商品 #2：ASIN', '点击量最高的商品 #2：商品名称',
    '点击量最高的商品 #2：点击份额', '点击量最高的商品 #2：转化份额',
    '点击量最高的商品 #3：ASIN', '点击量最高的商品 #3：商品名称',
    '点击量最高的商品 #3：点击份额', '点击量最高的商品 #3：转化份额',
    '报告日期',
]

CATEGORY_PATTERNS = [
    ('shirt', ['shirt', 'shirts', 't-shirt', 'tshirt', 'tee', 'tees']),
    ('hat', ['hat', 'hats', 'cap', 'caps', 'baseball cap', 'snapback']),
    ('sticker', ['sticker', 'stickers', 'decal', 'decals']),
    ('flag', ['flag', 'flags', 'garden flag', 'yard flag']),
    ('banner', ['banner', 'banners']),
    ('blanket', ['blanket', 'blankets']),
    ('sock', ['sock', 'socks']),
    ('apron', ['apron', 'aprons']),
    ('badge', ['badge', 'badges', 'pin', 'pins']),
    ('makeup bag', ['makeup bag', 'cosmetic bag']),
    ('canvas bag', ['canvas bag', 'tote bag']),
    ('sign', ['sign', 'signs', 'metal sign']),
    ('tapestry', ['tapestry', 'tapestries']),
]


def detect_category(term: str) -> str:
    term_lower = term.lower()
    for category, keywords in CATEGORY_PATTERNS:
        for keyword in keywords:
            pattern = rf'(^|[^a-z]){re.escape(keyword)}([^a-z]|$)'
            if re.search(pattern, term_lower):
                return category
    return ''


def normalize_noise_match_text(raw_text: str) -> str:
    if not isinstance(raw_text, str):
        return ''
    return re.sub(r'\s+', ' ', raw_text.casefold()).strip()


def has_noise_word_boundaries(text: str, start_index: int, end_index: int) -> bool:
    prev_is_letter = start_index > 0 and 'a' <= text[start_index - 1] <= 'z'
    next_is_letter = end_index + 1 < len(text) and 'a' <= text[end_index + 1] <= 'z'
    return not prev_is_letter and not next_is_letter


def generate_display_label(report_week) -> str:
    year = report_week.year
    week_number = report_week.isocalendar()[1]
    start_date = report_week
    end_date = report_week + timedelta(days=6)
    start_str = start_date.strftime("%m.%d")
    end_str = end_date.strftime("%m.%d")
    return f"{year}年第{week_number}周 ({start_str}-{end_str})"


def parse_report_week_from_csv(csv_path: Path):
    import re as _re
    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        first_line = f.readline().strip()
    m = _re.search(r'(\d{4}-\d{2}-\d{2})\s*-\s*(\d{4}-\d{2}-\d{2})', first_line)
    if m:
        start_date = datetime.strptime(m.group(1), "%Y-%m-%d").date()
        if start_date.weekday() == 6:
            return start_date
        end_date = datetime.strptime(m.group(2), "%Y-%m-%d").date()
        if end_date.weekday() == 6:
            return end_date
    raise ValueError(f"无法从CSV首行解析报告周: {first_line}")


class ABACSVImporter:

    def __init__(self, report_week, batch_size=5000, chunk_size=10000):
        self.report_week = report_week
        self.batch_size = batch_size
        self.chunk_size = chunk_size
        self.stats = {
            'raw_records': 0,
            'search_terms_created': 0,
            'metrics_created': 0,
            'batches': 0,
            'errors': 0,
            'noise_words_loaded': 0,
            'filtered_by_noise': 0,
            'categories_updated': 0,
        }
        self.term_cache = {}
        self.noise_word_matcher = None
        self.last_week_ranks = {}
        self._load_term_cache()
        self._load_noise_word_matcher()
        self._load_last_week_ranks()

    def _load_term_cache(self):
        print("正在加载现有搜索词缓存...")
        qs = SearchTerm.objects.using('aba_db').values_list('id', 'term', 'category', 'first_seen').iterator()
        for term_id, term_text, category, first_seen in qs:
            self.term_cache[term_text] = (term_id, category, first_seen)
        print(f"   已缓存 {len(self.term_cache):,} 个搜索词")

    def _load_noise_word_matcher(self):
        print("正在加载去噪词库...")
        ahocorasick_spec = importlib.util.find_spec('ahocorasick')
        if ahocorasick_spec is None:
            raise RuntimeError(
                "缺少依赖 'pyahocorasick'。请先执行 `pip install pyahocorasick`"
            )
        ahocorasick = importlib.import_module('ahocorasick')
        automaton = ahocorasick.Automaton()
        seen_words = set()
        for raw_word in AbaNoiseWord.objects.using('aba_db').values_list('word', flat=True).iterator():
            normalized_word = normalize_noise_match_text(raw_word)
            if not normalized_word or normalized_word in seen_words:
                continue
            seen_words.add(normalized_word)
            automaton.add_word(normalized_word, normalized_word)
        if seen_words:
            automaton.make_automaton()
            self.noise_word_matcher = automaton
        self.stats['noise_words_loaded'] = len(seen_words)
        print(f"   已加载 {len(seen_words):,} 个去噪词")

    def _contains_noise_word(self, term: str) -> bool:
        if self.noise_word_matcher is None:
            return False
        normalized_term = normalize_noise_match_text(term)
        if not normalized_term:
            return False
        for end_index, matched_word in self.noise_word_matcher.iter(normalized_term):
            start_index = end_index - len(matched_word) + 1
            if has_noise_word_boundaries(normalized_term, start_index, end_index):
                return True
        return False

    def _load_last_week_ranks(self):
        last_week = self.report_week - timedelta(days=7)
        print(f"正在加载上周 ({last_week}) 排名数据...")
        with connections['aba_db'].cursor() as cursor:
            cursor.execute("SET search_path TO public")
            cursor.execute(
                "SELECT search_term_id, search_frequency_rank "
                "FROM search_term_metrics WHERE report_week = %s",
                [last_week]
            )
            rows = cursor.fetchall()
        self.last_week_ranks = {row[0]: row[1] for row in rows}
        print(f"   已加载 {len(self.last_week_ranks):,} 条上周排名")

    @staticmethod
    def _safe_str(val):
        if val is None or (isinstance(val, float) and val != val):
            return ''
        return str(val).strip()

    _MAX_SHARE = Decimal('0.9999')
    _HUNDRED = Decimal('100')

    @staticmethod
    def _safe_decimal(val):
        if val is None or (isinstance(val, float) and val != val):
            return None
        d = Decimal(str(val)) / ABACSVImporter._HUNDRED
        if d > ABACSVImporter._MAX_SHARE:
            return ABACSVImporter._MAX_SHARE
        return d

    @staticmethod
    def _safe_decimal_req(val):
        if val is None or (isinstance(val, float) and val != val):
            return Decimal('0')
        d = Decimal(str(val)) / ABACSVImporter._HUNDRED
        if d > ABACSVImporter._MAX_SHARE:
            return ABACSVImporter._MAX_SHARE
        return d

    def _process_chunk(self, df_chunk):
        new_terms = []
        metrics_data = []
        terms_to_update = []
        term_ids_to_update_last_seen = []
        term_ids_to_update_first_seen = []
        filtered_count = 0

        terms_series = df_chunk['搜索词']
        ranks_series = df_chunk['搜索频率排名']

        for i in range(len(df_chunk)):
            term = terms_series.iat[i]
            if term is None or (isinstance(term, float) and term != term) or not str(term).strip():
                continue
            term = str(term).strip()

            if self._contains_noise_word(term):
                filtered_count += 1
                continue

            rank = int(ranks_series.iat[i])
            detected_category = detect_category(term)

            if term in self.term_cache:
                term_id, existing_category, existing_first_seen = self.term_cache[term]
                if detected_category != existing_category:
                    terms_to_update.append((term_id, detected_category))
                    self.term_cache[term] = (term_id, detected_category, existing_first_seen)
                term_ids_to_update_last_seen.append(term_id)
                if existing_first_seen is None or self.report_week < existing_first_seen:
                    term_ids_to_update_first_seen.append(term_id)
                    self.term_cache[term] = (term_id, detected_category, self.report_week)
                last_rank = self.last_week_ranks.get(term_id)
            else:
                term_id = None
                new_terms.append(SearchTerm(
                    term=term,
                    category=detected_category,
                    first_seen=self.report_week,
                    last_seen=self.report_week,
                ))
                last_rank = None

            rank_change = None
            if last_rank is not None and rank:
                rank_change = last_rank - rank

            row = df_chunk.iloc[i]
            metrics_data.append({
                'term': term,
                'term_id': term_id,
                'search_frequency_rank': rank,
                'asin_1_code': self._safe_str(row['点击量最高的商品 #1：ASIN']),
                'asin_1_title': self._safe_str(row['点击量最高的商品 #1：商品名称']),
                'asin_1_click_share': self._safe_decimal_req(row['点击量最高的商品 #1：点击份额']),
                'asin_1_conversion_share': self._safe_decimal_req(row['点击量最高的商品 #1：转化份额']),
                'asin_2_code': self._safe_str(row['点击量最高的商品 #2：ASIN']),
                'asin_2_title': self._safe_str(row['点击量最高的商品 #2：商品名称']),
                'asin_2_click_share': self._safe_decimal(row['点击量最高的商品 #2：点击份额']),
                'asin_2_conversion_share': self._safe_decimal(row['点击量最高的商品 #2：转化份额']),
                'asin_3_code': self._safe_str(row['点击量最高的商品 #3：ASIN']),
                'asin_3_title': self._safe_str(row['点击量最高的商品 #3：商品名称']),
                'asin_3_click_share': self._safe_decimal(row['点击量最高的商品 #3：点击份额']),
                'asin_3_conversion_share': self._safe_decimal(row['点击量最高的商品 #3：转化份额']),
                'last_week_rank': last_rank,
                'rank_change': rank_change,
            })

        return new_terms, metrics_data, terms_to_update, term_ids_to_update_last_seen, term_ids_to_update_first_seen, filtered_count

    def _save_batch(self, new_terms, metrics_data, terms_to_update, term_ids_to_update_last_seen, term_ids_to_update_first_seen):
        if new_terms:
            with transaction.atomic(using='aba_db'):
                SearchTerm.objects.using('aba_db').bulk_create(
                    new_terms, ignore_conflicts=True, batch_size=1000
                )
            for t in new_terms:
                try:
                    db_term = SearchTerm.objects.using('aba_db').get(term=t.term)
                    self.term_cache[t.term] = (db_term.id, t.category, self.report_week)
                except SearchTerm.DoesNotExist:
                    pass
            self.stats['search_terms_created'] += len(new_terms)

        for m in metrics_data:
            if m['term_id'] is None and m['term'] in self.term_cache:
                m['term_id'] = self.term_cache[m['term']][0]

        valid_metrics = [m for m in metrics_data if m['term_id'] is not None]
        if valid_metrics:
            self._bulk_create_metrics_raw(valid_metrics)
            self.stats['metrics_created'] += len(valid_metrics)

        if terms_to_update:
            self._bulk_update_category(terms_to_update)
            self.stats['categories_updated'] += len(terms_to_update)

        if term_ids_to_update_last_seen:
            self._bulk_update_last_seen(term_ids_to_update_last_seen)

        if term_ids_to_update_first_seen:
            self._bulk_update_first_seen(term_ids_to_update_first_seen)

    def _bulk_update_last_seen(self, term_ids):
        if not term_ids:
            return
        ids_str = ','.join(str(tid) for tid in term_ids)
        sql = f"UPDATE search_terms SET last_seen = %s WHERE id IN ({ids_str})"
        with connections['aba_db'].cursor() as cursor:
            cursor.execute("SET search_path TO public")
            cursor.execute(sql, [self.report_week])

    def _bulk_update_first_seen(self, term_ids):
        if not term_ids:
            return
        ids_str = ','.join(str(tid) for tid in term_ids)
        sql = f"UPDATE search_terms SET first_seen = %s WHERE id IN ({ids_str})"
        with connections['aba_db'].cursor() as cursor:
            cursor.execute("SET search_path TO public")
            cursor.execute(sql, [self.report_week])

    def _bulk_create_metrics_raw(self, metrics_list):
        sql = """
            INSERT INTO search_term_metrics (
                report_week, search_term_id, search_frequency_rank,
                asin_1_code, asin_1_title, asin_1_click_share, asin_1_conversion_share,
                asin_2_code, asin_2_title, asin_2_click_share, asin_2_conversion_share,
                asin_3_code, asin_3_title, asin_3_click_share, asin_3_conversion_share,
                last_week_rank, rank_change, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (report_week, search_term_id) DO UPDATE SET
                search_frequency_rank = EXCLUDED.search_frequency_rank,
                asin_1_code = EXCLUDED.asin_1_code,
                asin_1_title = EXCLUDED.asin_1_title,
                asin_1_click_share = EXCLUDED.asin_1_click_share,
                asin_1_conversion_share = EXCLUDED.asin_1_conversion_share,
                asin_2_code = EXCLUDED.asin_2_code,
                asin_2_title = EXCLUDED.asin_2_title,
                asin_2_click_share = EXCLUDED.asin_2_click_share,
                asin_2_conversion_share = EXCLUDED.asin_2_conversion_share,
                asin_3_code = EXCLUDED.asin_3_code,
                asin_3_title = EXCLUDED.asin_3_title,
                asin_3_click_share = EXCLUDED.asin_3_click_share,
                asin_3_conversion_share = EXCLUDED.asin_3_conversion_share,
                last_week_rank = EXCLUDED.last_week_rank,
                rank_change = EXCLUDED.rank_change,
                created_at = NOW()
        """
        data = []
        rw = self.report_week
        for m in metrics_list:
            data.append((
                rw, m['term_id'], m['search_frequency_rank'],
                m['asin_1_code'], m['asin_1_title'],
                m['asin_1_click_share'], m['asin_1_conversion_share'],
                m['asin_2_code'], m['asin_2_title'],
                m['asin_2_click_share'], m['asin_2_conversion_share'],
                m['asin_3_code'], m['asin_3_title'],
                m['asin_3_click_share'], m['asin_3_conversion_share'],
                m['last_week_rank'], m['rank_change'],
            ))

        with connections['aba_db'].cursor() as cursor:
            cursor.execute("SET search_path TO public")
            cursor.executemany(sql, data)

    def _bulk_update_category(self, terms_to_update):
        if not terms_to_update:
            return
        case_conditions = []
        term_ids = []
        for term_id, new_category in terms_to_update:
            case_conditions.append(f"WHEN id = {term_id} THEN '{new_category}'")
            term_ids.append(str(term_id))
        ids_str = ','.join(term_ids)
        case_sql = '\n                    '.join(case_conditions)
        sql = f"""
            UPDATE search_terms
            SET category = CASE
                {case_sql}
                ELSE category
            END
            WHERE id IN ({ids_str});
        """
        with connections['aba_db'].cursor() as cursor:
            cursor.execute("SET search_path TO public")
            cursor.execute(sql)

    def import_csv(self, csv_path: str):
        print(f"开始导入: {csv_path}")
        print(f"   报告周: {self.report_week}")
        print(f"   分块大小: {self.chunk_size}")
        print(f"   批次大小: {self.batch_size}")
        print()

        reader = pd.read_csv(
            csv_path,
            header=1,
            usecols=CSV_USECOLS,
            chunksize=self.chunk_size,
            dtype=str,
            keep_default_na=True,
        )

        total_processed = 0
        batch_new_terms = []
        batch_metrics = []
        batch_term_updates = []
        batch_last_seen_ids = []
        batch_first_seen_ids = []
        batch_filtered = 0

        with tqdm(desc="处理中", unit="行") as pbar:
            for chunk in reader:
                chunk_len = len(chunk)
                new_terms, metrics_data, terms_to_update, last_seen_ids, first_seen_ids, filtered = self._process_chunk(chunk)

                batch_new_terms.extend(new_terms)
                batch_metrics.extend(metrics_data)
                batch_term_updates.extend(terms_to_update)
                batch_last_seen_ids.extend(last_seen_ids)
                batch_first_seen_ids.extend(first_seen_ids)
                batch_filtered += filtered

                if len(batch_metrics) >= self.batch_size:
                    self._save_batch(batch_new_terms, batch_metrics, batch_term_updates, batch_last_seen_ids, batch_first_seen_ids)
                    self.stats['batches'] += 1
                    batch_new_terms = []
                    batch_metrics = []
                    batch_term_updates = []
                    batch_last_seen_ids = []
                    batch_first_seen_ids = []

                total_processed += chunk_len
                pbar.update(chunk_len)

        if batch_metrics or batch_new_terms:
            self._save_batch(batch_new_terms, batch_metrics, batch_term_updates, batch_last_seen_ids, batch_first_seen_ids)
            self.stats['batches'] += 1

        self.stats['raw_records'] = total_processed
        self.stats['filtered_by_noise'] = batch_filtered
        print(f"\n共处理 {total_processed:,} 行")
        self._print_stats()
        return total_processed

    def _print_stats(self):
        print("\n" + "=" * 60)
        print("导入完成")
        print("=" * 60)
        print(f"   原始记录处理:   {self.stats['raw_records']:,} 行")
        print(f"   去噪词加载:     {self.stats['noise_words_loaded']:,} 个")
        print(f"   去噪拦截:       {self.stats['filtered_by_noise']:,} 个")
        print(f"   新建搜索词:     {self.stats['search_terms_created']:,} 个")
        print(f"   指标记录写入:   {self.stats['metrics_created']:,} 条")
        print(f"   品类更新:       {self.stats['categories_updated']:,} 个")
        print(f"   批次数:         {self.stats['batches']}")
        print(f"   错误数:         {self.stats['errors']}")
        print("=" * 60)


def update_aba_report_week(report_week, record_count: int):
    display_label = generate_display_label(report_week)
    with connections['aba_db'].cursor() as cursor:
        cursor.execute("SET search_path TO public")
        cursor.execute(
            "SELECT 1 FROM aba_report_weeks WHERE report_week = %s",
            [report_week]
        )
        exists = cursor.fetchone() is not None
        if exists:
            cursor.execute(
                """
                UPDATE aba_report_weeks
                SET display_label = %s,
                    import_status = 'ready',
                    record_count = %s,
                    is_active = TRUE,
                    updated_at = NOW()
                WHERE report_week = %s
                """,
                [display_label, record_count, report_week]
            )
            print(f"\n更新 AbaReportWeek: {display_label} (记录数: {record_count:,})")
        else:
            cursor.execute(
                """
                INSERT INTO aba_report_weeks
                    (report_week, display_label, import_status, record_count, is_active, created_at, updated_at)
                VALUES
                    (%s, %s, 'ready', %s, TRUE, NOW(), NOW())
                """,
                [report_week, display_label, record_count]
            )
            print(f"\n创建 AbaReportWeek: {display_label} (记录数: {record_count:,})")


def list_csv_files():
    if not CSV_DIR.exists():
        print(f"目录不存在: {CSV_DIR}")
        return []
    csv_files = sorted(CSV_DIR.glob("*.csv"))
    return csv_files


def main():
    print("=" * 60)
    print("ABA CSV 数据导入工具")
    print("=" * 60)
    print()

    csv_files = list_csv_files()
    if not csv_files:
        print("未找到 CSV 文件")
        return False

    print(f"找到 {len(csv_files)} 个 CSV 文件：\n")
    for i, f in enumerate(csv_files, 1):
        size_mb = f.stat().st_size / 1024 / 1024
        print(f"  {i}. {f.name} ({size_mb:.1f} MB)")
    print()

    while True:
        file_choice = input("请输入要导入的文件编号: ").strip()
        try:
            idx = int(file_choice)
            if 1 <= idx <= len(csv_files):
                selected_file = csv_files[idx - 1]
                break
            else:
                print("编号超出范围")
        except ValueError:
            print("请输入有效编号")

    report_week = parse_report_week_from_csv(selected_file)
    print(f"\n检测到报告周: {report_week} (周日)")

    print(f"\n开始导入 {selected_file.name}...")
    start_time = time.time()

    importer = ABACSVImporter(
        report_week=report_week,
        batch_size=5000,
        chunk_size=10000,
    )
    record_count = importer.import_csv(str(selected_file))

    elapsed = time.time() - start_time
    print(f"\n总耗时: {elapsed:.1f}秒 ({elapsed / 60:.1f} 分钟)")

    update_aba_report_week(report_week, record_count)
    return True


if __name__ == '__main__':
    try:
        result = main()
        if not result:
            sys.exit(1)
    except KeyboardInterrupt:
        print("\n\n用户取消")
        sys.exit(1)
