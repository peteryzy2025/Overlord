"""
ABA 数据导入脚本

将 ABA 搜索词报告从 JSON 导入到 PostgreSQL (aba_db)
功能特性：
- 流式处理大文件（3GB+）
- 批量插入（每批 5000 条）
- 自动聚合：搜索词 -> Top 3 ASIN
- 环比排名计算
- 进度条显示

使用方法：
    python sync_import_to_db.py <报告日期>

示例：
    python sync_import_to_db.py 2026-02-15
"""

import os
import sys
import json
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
from aba.models import SearchTerm, SearchTermMetric


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
        
        # Cache for existing search terms {term: id}
        self.term_cache = {}
        
        # Load existing terms into cache
        self._load_term_cache()
    
    def _load_term_cache(self):
        """将现有搜索词加载到内存缓存"""
        print("📦 正在加载现有搜索词...")
        for term in SearchTerm.objects.using('aba_db').all():
            self.term_cache[term.term] = term.id
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
    
    def process_batch(self, records: List[dict]) -> Tuple[List[SearchTerm], List[SearchTermMetric]]:
        """
        处理一批记录
        
        返回：
            (待创建搜索词列表, 待创建指标列表)
        """
        # Aggregate
        aggregated = self.aggregate_records(records)
        
        search_terms = []
        metrics = []
        
        for term, data in aggregated.items():
            # 获取或创建 SearchTerm
            if term in self.term_cache:
                term_id = self.term_cache[term]
                # 更新最后出现时间
                SearchTerm.objects.using('aba_db').filter(id=term_id).update(
                    last_seen=self.report_week
                )
            else:
                # 创建新搜索词
                search_term = SearchTerm(
                    term=term,
                    category='',  # 可后续补充
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
        
        return search_terms, metrics
    
    def save_batch(self, search_terms: List[SearchTerm], metrics: List[Tuple]):
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
                    self.term_cache[term.term] = db_term.id
                except SearchTerm.DoesNotExist:
                    pass
        
        # 2. 修复新搜索词的指标关联 ID
        fixed_metrics = []
        for metric, term in metrics:
            if metric.search_term_id is None and term in self.term_cache:
                metric.search_term_id = self.term_cache[term]
            fixed_metrics.append(metric)
        
        # 3. 使用原始 SQL 批量创建指标（managed=False 模型）
        if fixed_metrics:
            self._bulk_create_metrics_raw(fixed_metrics)
    
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
    
    def import_file(self, filepath: str):
        """主导入流程 - 使用 ijson 流式解析大 JSON"""
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
    
    def _process_and_save_batch(self, batch: List[dict]):
        """Process and save one batch"""
        self.stats['raw_records'] += len(batch)
        
        search_terms, metrics = self.process_batch(batch)
        self.save_batch(search_terms, metrics)
        
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


def main(report_date: str = "2026-02-15"):
    """
    主入口函数
    
    参数:
        report_date: 报告日期 (YYYY-MM-DD)，默认 2026-02-15
    """
    # 验证日期格式
    try:
        datetime.strptime(report_date, "%Y-%m-%d")
    except ValueError:
        print("❌ 日期格式错误，请使用 YYYY-MM-DD")
        return False
    
    # 自动查找 json 文件
    json_dir = Path(__file__).parent / "json"
    filepath = json_dir / f"{report_date}.json"
    
    if not filepath.exists():
        print(f"❌ 文件不存在: {filepath}")
        print(f"   请先运行: python sync_aba_down.py")
        print(f"   或检查日期是否正确")
        return False
    
    print(f"📁 找到 JSON 文件: {filepath}")
    print()
    
    # 开始导入
    start_time = time.time()
    
    importer = ABAImporter(report_week=report_date, batch_size=5000)
    importer.import_file(str(filepath))
    
    elapsed = time.time() - start_time
    print(f"\n⏱️  总耗时: {elapsed:.1f}秒 ({elapsed/60:.1f} 分钟)")
    
    return True


if __name__ == '__main__':
    # 默认导入 2026-02-15 的数据
    # 如需导入其他日期，修改参数即可：main("2026-02-08")
    result = main("2026-02-22")
    if not result:
        sys.exit(1)
