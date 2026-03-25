"""
ABA 数据导入脚本

将 ABA 搜索词报告从 JSON 导入到 PostgreSQL (aba_db)
功能特性：
- 流式处理大文件（3GB+）
- 批量插入（每批 5000 条）
- 自动聚合：搜索词 -> Top 3 ASIN
- 环比排名计算
- 进度条显示
- 支持先下载后导入
- 实时更新搜索词 category
- 自动更新 AbaReportWeek 记录

使用方法：
    python sync_import_to_db.py

交互式操作：
    1. 下载最新数据并导入
    2. 直接导入现有数据
"""

import os
import sys
import json
import re
import time
import ijson
import django
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict
from typing import List, Dict, Tuple

# Setup Django
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Overlord.settings')
django.setup()

from tqdm import tqdm
from django.db import transaction
from aba.models import SearchTerm, SearchTermMetric, AbaReportWeek

# 导入下载模块
sys.path.insert(0, str(Path(__file__).parent))
from sync_aba_down import download_aba_report, JSON_DIR


# 品类匹配规则（用于实时识别搜索词品类）
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
    """根据搜索词判断品类（整词匹配）"""
    term_lower = term.lower()
    for category, keywords in CATEGORY_PATTERNS:
        for keyword in keywords:
            pattern = rf'(^|[^a-z]){re.escape(keyword)}([^a-z]|$)'
            if re.search(pattern, term_lower):
                return category
    return ''


def generate_display_label(report_week: datetime.date) -> str:
    """
    生成展示文案，格式：2026年第10周 (03.08-03.14)
    """
    year = report_week.year
    week_number = report_week.isocalendar()[1]
    start_date = report_week
    end_date = report_week + timedelta(days=6)
    
    start_str = start_date.strftime("%m.%d")
    end_str = end_date.strftime("%m.%d")
    
    return f"{year}年第{week_number}周 ({start_str}-{end_str})"


class ABAImporter:
    """ABA 数据导入器，支持流式和批量处理"""
    
    def __init__(self, report_week: str, batch_size: int = 5000):
        """
        参数：
            report_week: 周起始日期（YYYY-MM-DD）
            batch_size: 每批处理的原始记录数
        """
        self.report_week = datetime.strptime(report_week, "%Y-%m-%d").date()
        self.batch_size = batch_size
        
        # 统计信息
        self.stats = {
            'raw_records': 0,      # 原始记录数
            'search_terms': 0,     # 搜索词数
            'metrics': 0,          # 指标记录数
            'batches': 0,          # 批次数
            'errors': 0            # 错误数
        }
        
        # Cache for existing search terms {term: (id, category)}
        self.term_cache = {}
        
        # Load existing terms into cache
        self._load_term_cache()
    
    def _load_term_cache(self):
        """将现有搜索词加载到内存缓存"""
        print("📦 正在加载现有搜索词...")
        for term in SearchTerm.objects.using('aba_db').all():
            self.term_cache[term.term] = (term.id, term.category)
        print(f"   已缓存 {len(self.term_cache)} 个搜索词")
    
    def _get_last_week_rank(self, term_id: int) -> Tuple[int, int]:
        """
        获取上周排名，用于环比计算
        
        返回：
            (上周排名, 排名变化)
        """
        last_week = self.report_week - timedelta(days=7)
        
        try:
            last_metric = SearchTermMetric.objects.using('aba_db').get(
                report_week=last_week,
                search_term_id=term_id
            )
            return last_metric.search_frequency_rank, None
        except SearchTermMetric.DoesNotExist:
            return None, None  # 上周无数据
    
    def aggregate_records(self, records: List[dict]) -> Dict[str, dict]:
        """
        按搜索词聚合原始记录
        
        输入：原始 JSON 记录列表
        输出：{搜索词: {排名: int, asins: [{code, title, clickShare, conversionShare}, ...]}}
        """
        grouped = defaultdict(lambda: {
            'searchFrequencyRank': 0,
            'asins': []
        })
        
        for record in records:
            term = record.get('searchTerm', '').strip()
            if not term:
                continue
            
            # Extract data
            asin_data = {
                'code': record.get('clickedAsin', ''),
                'title': record.get('clickedItemName', ''),
                'clickShare': record.get('clickShare', 0),
                'conversionShare': record.get('conversionShare', 0),
                'clickShareRank': record.get('clickShareRank', 999)
            }
            
            grouped[term]['searchFrequencyRank'] = record.get('searchFrequencyRank', 0)
            grouped[term]['asins'].append(asin_data)
        
        # 按点击份额排序，取前 3
        for term_data in grouped.values():
            asins = term_data['asins']
            # 按点击份额降序排序
            asins.sort(key=lambda x: x['clickShare'], reverse=True)
            # 取前 3，不足补 None
            top3 = asins[:3]
            while len(top3) < 3:
                top3.append({'code': None, 'title': None, 'clickShare': None, 'conversionShare': None})
            term_data['asins'] = top3
        
        return dict(grouped)
    
    def process_batch(self, records: List[dict]) -> Tuple[List[SearchTerm], List[SearchTermMetric], List[Tuple]]:
        """
        处理一批记录
        
        返回：
            (待创建搜索词列表, 待创建指标列表, 待更新搜索词列表)
        """
        # Aggregate
        aggregated = self.aggregate_records(records)
        
        search_terms = []
        metrics = []
        terms_to_update = []  # (term_id, new_category)
        
        for term, data in aggregated.items():
            # 实时检测品类
            detected_category = detect_category(term)
            
            # 获取或创建 SearchTerm
            if term in self.term_cache:
                term_id, existing_category = self.term_cache[term]
                # 检查 category 是否需要更新（为空或发生变化都要更新）
                if detected_category != existing_category:
                    terms_to_update.append((term_id, detected_category))
                    # 更新缓存
                    self.term_cache[term] = (term_id, detected_category)
                # 更新最后出现时间
                SearchTerm.objects.using('aba_db').filter(id=term_id).update(
                    last_seen=self.report_week
                )
            else:
                # 创建新搜索词
                search_term = SearchTerm(
                    term=term,
                    category=detected_category,  # 实时计算 category
                    first_seen=self.report_week,
                    last_seen=self.report_week
                )
                search_terms.append(search_term)
                # 临时 ID，bulk_create 后更新
                term_id = None
            
            # 获取上周排名用于环比计算
            if term_id:
                last_rank, _ = self._get_last_week_rank(term_id)
            else:
                last_rank = None
            
            rank_change = None
            if last_rank and data['searchFrequencyRank']:
                rank_change = last_rank - data['searchFrequencyRank']  # 正数 = 排名上升（变好）
            
            # Create metric (without search_term_id for new terms)
            asins = data['asins']
            metric = SearchTermMetric(
                report_week=self.report_week,
                search_term_id=term_id,  # May be None for new terms, will fix later
                search_frequency_rank=data['searchFrequencyRank'],
                
                # ASIN 1
                asin_1_code=asins[0]['code'] or '',
                asin_1_title=asins[0]['title'] or '',
                asin_1_click_share=asins[0]['clickShare'] or 0,
                asin_1_conversion_share=asins[0]['conversionShare'] or 0,
                
                # ASIN 2
                asin_2_code=asins[1]['code'] or '',
                asin_2_title=asins[1]['title'] or '',
                asin_2_click_share=asins[1]['clickShare'],
                asin_2_conversion_share=asins[1]['conversionShare'],
                
                # ASIN 3
                asin_3_code=asins[2]['code'] or '',
                asin_3_title=asins[2]['title'] or '',
                asin_3_click_share=asins[2]['clickShare'],
                asin_3_conversion_share=asins[2]['conversionShare'],
                
                # Week-over-week
                last_week_rank=last_rank,
                rank_change=rank_change
            )
            metrics.append((metric, term))  # Keep term for linking
        
        return search_terms, metrics, terms_to_update
    
    def save_batch(self, search_terms: List[SearchTerm], metrics: List[Tuple], terms_to_update: List[Tuple]):
        """保存批次到数据库"""
        
        # 1. 批量创建 SearchTerms
        if search_terms:
            with transaction.atomic(using='aba_db'):
                SearchTerm.objects.using('aba_db').bulk_create(
                    search_terms, 
                    ignore_conflicts=True,
                    batch_size=1000
                )
            
            # 更新缓存获取新 ID
            for term in search_terms:
                # 重新查询获取 ID（bulk_create 配合 ignore_conflicts 不返回 ID）
                try:
                    db_term = SearchTerm.objects.using('aba_db').get(term=term.term)
                    self.term_cache[term.term] = (db_term.id, term.category)
                except SearchTerm.DoesNotExist:
                    pass
        
        # 2. 修复新搜索词的指标关联 ID
        fixed_metrics = []
        for metric, term in metrics:
            if metric.search_term_id is None and term in self.term_cache:
                metric.search_term_id = self.term_cache[term][0]
            fixed_metrics.append(metric)
        
        # 3. 使用原始 SQL 批量创建指标（managed=False 模型）
        if fixed_metrics:
            self._bulk_create_metrics_raw(fixed_metrics)
        
        # 4. 批量更新已存在搜索词的 category
        if terms_to_update:
            self._bulk_update_category(terms_to_update)
    
    def _bulk_update_category(self, terms_to_update: List[Tuple]):
        """批量更新搜索词的 category"""
        from django.db import connections
        
        if not terms_to_update:
            return
        
        # 使用 CASE WHEN 批量更新
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
    
    def _bulk_create_metrics_raw(self, metrics: List[SearchTermMetric]):
        """使用原始 SQL 插入指标（因为 managed=False）"""
        from django.db import connections
        
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
        
        with connections['aba_db'].cursor() as cursor:
            cursor.execute("SET search_path TO public")
            
            data = []
            for m in metrics:
                data.append((
                    m.report_week, m.search_term_id, m.search_frequency_rank,
                    m.asin_1_code, m.asin_1_title, m.asin_1_click_share, m.asin_1_conversion_share,
                    m.asin_2_code, m.asin_2_title, m.asin_2_click_share, m.asin_2_conversion_share,
                    m.asin_3_code, m.asin_3_title, m.asin_3_click_share, m.asin_3_conversion_share,
                    m.last_week_rank, m.rank_change
                ))
            
            cursor.executemany(sql, data)
    
    def import_file(self, filepath: str) -> int:
        """
        主导入流程 - 使用 ijson 流式解析大 JSON
        
        返回：
            实际导入的数据条数（用于更新 AbaReportWeek）
        """
        print(f"🚀 开始导入: {filepath}")
        print(f"   报告周: {self.report_week}")
        print(f"   批次大小: {self.batch_size}")
        print()
        
        # 使用 ijson 流式解析，不预统计行数（无法快速统计）
        print("📊 正在流式解析 JSON...")
        print("   （大文件处理中，请耐心等待...）\n")
        
        batch = []
        processed = 0
        
        with open(filepath, 'rb') as f:
            # ijson 流式解析 dataByDepartmentAndSearchTerm 数组
            # 这样 3GB 文件不会加载到内存
            records = ijson.items(f, 'dataByDepartmentAndSearchTerm.item')
            
            # 由于不知道总数，用简单计数器显示进度
            with tqdm(desc="处理中", unit="条") as pbar:
                for record in records:
                    batch.append(record)
                    
                    if len(batch) >= self.batch_size:
                        self._process_and_save_batch(batch)
                        batch = []
                        self.stats['batches'] += 1
                    
                    processed += 1
                    pbar.update(1)
                
                # 处理剩余记录
                if batch:
                    self._process_and_save_batch(batch)
                    self.stats['batches'] += 1
        
        print(f"\n✅ 共处理 {processed:,} 条记录")
        self._print_stats()
        
        return processed
    
    def _process_and_save_batch(self, batch: List[dict]):
        """Process and save one batch"""
        self.stats['raw_records'] += len(batch)
        
        search_terms, metrics, terms_to_update = self.process_batch(batch)
        self.save_batch(search_terms, metrics, terms_to_update)
        
        self.stats['search_terms'] += len(search_terms)
        self.stats['metrics'] += len(metrics)
    
    def _print_stats(self):
        """打印最终统计"""
        print("\n" + "="*60)
        print("✅ 导入完成！")
        print("="*60)
        print(f"   原始记录处理: {self.stats['raw_records']:,} 条")
        print(f"   搜索词创建:   {self.stats['search_terms']:,} 个")
        print(f"   指标记录创建: {self.stats['metrics']:,} 条")
        print(f"   批次数:       {self.stats['batches']}")
        print(f"   错误数:       {self.stats['errors']}")
        print("="*60)


def update_aba_report_week(report_week: datetime.date, record_count: int):
    """
    更新或创建 AbaReportWeek 记录
    
    参数：
        report_week: 数据周日期
        record_count: 导入的数据条数
    """
    from django.db import connections
    
    display_label = generate_display_label(report_week)
    
    # 使用原始 SQL，避免 Django ORM 对 id 的依赖
    with connections['aba_db'].cursor() as cursor:
        cursor.execute("SET search_path TO public")
        
        # 检查记录是否存在
        cursor.execute(
            "SELECT 1 FROM aba_report_weeks WHERE report_week = %s",
            [report_week]
        )
        exists = cursor.fetchone() is not None
        
        if exists:
            # 更新现有记录
            cursor.execute(
                """
                UPDATE aba_report_weeks 
                SET display_label = %s,
                    import_status = 'completed',
                    record_count = %s,
                    is_active = TRUE,
                    updated_at = NOW()
                WHERE report_week = %s
                """,
                [display_label, record_count, report_week]
            )
            print(f"\n📅 更新 AbaReportWeek: {display_label} (记录数: {record_count:,})")
        else:
            # 创建新记录
            cursor.execute(
                """
                INSERT INTO aba_report_weeks 
                    (report_week, display_label, import_status, record_count, is_active, created_at, updated_at)
                VALUES 
                    (%s, %s, 'completed', %s, TRUE, NOW(), NOW())
                """,
                [report_week, display_label, record_count]
            )
            print(f"\n📅 创建 AbaReportWeek: {display_label} (记录数: {record_count:,})")


def generate_weeks(start_year: int = 2025) -> List[Tuple[str, int, str, str]]:
    """
    生成从指定年份到当前日期的所有周日列表
    
    返回: [(日期字符串, 年度第几周, 开始日期MM.DD, 结束日期MM.DD), ...]
    """
    weeks = []
    today = datetime.now().date()
    
    # 找到指定年份第一个周日
    start_date = datetime(start_year, 1, 1).date()
    while start_date.weekday() != 6:  # 6 = Sunday
        start_date += timedelta(days=1)
    
    # 生成所有周日直到当前日期后一周
    current = start_date
    while current <= today + timedelta(days=7):
        # 计算年度第几周
        week_number = current.isocalendar()[1]
        # 计算该周结束日期（周六）
        end_date = current + timedelta(days=6)
        
        weeks.append((
            current.strftime("%Y-%m-%d"),  # 2026-02-15
            week_number,                    # 第7周
            current.strftime("%m.%d"),      # 02.15
            end_date.strftime("%m.%d")      # 02.21
        ))
        current += timedelta(days=7)
    
    return weeks


def show_week_selection_menu() -> List[str]:
    """
    显示周期选择菜单，返回用户选择的日期列表
    """
    weeks = generate_weeks(2025)
    
    print("\n" + "="*60)
    print("📅 请选择要下载的周期（支持多选）：")
    print("="*60)
    print()
    
    for i, (date_str, week_num, start, end) in enumerate(weeks, 1):
        year = datetime.strptime(date_str, "%Y-%m-%d").year
        print(f"{i:2d}. {year}年第{week_num}周 ({start}-{end})")
    
    print()
    print("提示：")
    print("  - 输入单个数字，如: 5")
    print("  - 输入多个数字（逗号分隔），如: 5,6,7")
    print("  - 输入 'all' 下载所有")
    print("  - 输入 'q' 取消")
    print()
    
    while True:
        choice = input("请输入编号: ").strip().lower()
        
        if choice == 'q':
            return []
        
        if choice == 'all':
            return [w[0] for w in weeks]
        
        try:
            indices = [int(x.strip()) for x in choice.split(',')]
            selected = []
            for idx in indices:
                if 1 <= idx <= len(weeks):
                    selected.append(weeks[idx-1][0])
                else:
                    print(f"❌ 编号 {idx} 超出范围，请重新输入")
                    break
            else:
                return selected
        except ValueError:
            print("❌ 输入格式错误，请重新输入")


def main():
    """
    主入口函数 - 交互式操作
    """
    print("="*60)
    print("📦 ABA 数据导入工具")
    print("="*60)
    print()
    print("请选择操作：")
    print("  1. 下载最新数据并导入")
    print("  2. 直接导入现有数据")
    print()
    
    while True:
        choice = input("请选择 (1/2): ").strip()
        
        if choice == '1':
            # 下载并导入
            selected_dates = show_week_selection_menu()
            if not selected_dates:
                print("❌ 已取消")
                return False
            
            print(f"\n🚀 共选择 {len(selected_dates)} 个周期，开始下载...\n")
            
            # 逐个下载并导入
            for date_str in selected_dates:
                print(f"\n{'='*60}")
                print(f"📅 处理周期: {date_str}")
                print(f"{'='*60}")
                
                # 下载
                json_path = download_aba_report(date_str)
                if not json_path:
                    print(f"❌ {date_str} 下载失败，跳过")
                    continue
                
                # 导入
                print(f"\n📥 开始导入 {date_str}...")
                start_time = time.time()
                importer = ABAImporter(report_week=date_str, batch_size=5000)
                record_count = importer.import_file(json_path)
                elapsed = time.time() - start_time
                print(f"⏱️  导入耗时: {elapsed:.1f}秒")
                
                # 更新 AbaReportWeek 记录
                report_week = datetime.strptime(date_str, "%Y-%m-%d").date()
                update_aba_report_week(report_week, record_count)
            
            print(f"\n{'='*60}")
            print("✅ 所有周期处理完成！")
            print(f"{'='*60}")
            return True
        
        elif choice == '2':
            # 直接导入现有数据
            json_dir = Path(__file__).parent / "json"
            
            if not json_dir.exists():
                print(f"❌ 目录不存在: {json_dir}")
                return False
            
            # 列出所有 json 文件
            json_files = sorted(json_dir.glob("*.json"))
            if not json_files:
                print(f"❌ 未找到 JSON 文件，请先下载数据")
                return False
            
            print(f"\n📁 找到 {len(json_files)} 个文件：")
            for i, f in enumerate(json_files, 1):
                size_mb = f.stat().st_size / 1024 / 1024
                print(f"  {i}. {f.name} ({size_mb:.1f} MB)")
            print()
            
            # 选择文件导入
            while True:
                file_choice = input("请输入要导入的文件编号（或文件名如 2026-02-15）: ").strip()
                
                # 尝试作为编号解析
                try:
                    idx = int(file_choice)
                    if 1 <= idx <= len(json_files):
                        selected_file = json_files[idx - 1]
                    else:
                        print("❌ 编号超出范围")
                        continue
                except ValueError:
                    # 作为文件名解析
                    selected_file = json_dir / f"{file_choice}.json"
                    if not selected_file.exists():
                        print(f"❌ 文件不存在: {selected_file}")
                        continue
                
                # 提取日期
                date_str = selected_file.stem
                
                print(f"\n📥 开始导入 {selected_file.name}...")
                start_time = time.time()
                importer = ABAImporter(report_week=date_str, batch_size=5000)
                record_count = importer.import_file(str(selected_file))
                elapsed = time.time() - start_time
                print(f"\n⏱️  总耗时: {elapsed:.1f}秒 ({elapsed/60:.1f} 分钟)")
                
                # 更新 AbaReportWeek 记录
                report_week = datetime.strptime(date_str, "%Y-%m-%d").date()
                update_aba_report_week(report_week, record_count)
                
                return True
        
        else:
            print("❌ 无效选择，请重新输入")


if __name__ == '__main__':
    try:
        result = main()
        if not result:
            sys.exit(1)
    except KeyboardInterrupt:
        print("\n\n❌ 用户取消")
        sys.exit(1)
