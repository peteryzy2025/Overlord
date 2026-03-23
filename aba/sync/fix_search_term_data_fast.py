#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
修复 SearchTerm 数据脚本（分批极速版 - 避免死锁）

优化策略：
1. 分批处理，每批独立事务，避免长时间锁表导致死锁
2. 每批 20,000 条，平衡速度和锁竞争
3. 实时显示进度、速度、预计剩余时间
4. 支持断点续传（从指定偏移量开始）
5. 死锁自动重试机制

使用方法:
    cd D:\Y-Project\Overlord
    .venv\Scripts\python.exe aba\sync\fix_search_term_data_fast.py
    
    # 从第 1,200,000 条开始（断点续传）
    .venv\Scripts\python.exe aba\sync\fix_search_term_data_fast.py --offset 1200000
"""
import os
import sys
import re
import time
import argparse
from pathlib import Path
from datetime import datetime

# Django 环境初始化
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Overlord.settings')
import django
django.setup()

from django.db import connections, transaction, OperationalError
from aba.models import SearchTerm


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


def format_duration(seconds):
    if seconds < 60:
        return f"{seconds:.0f}秒"
    elif seconds < 3600:
        return f"{seconds/60:.1f}分钟"
    else:
        return f"{seconds/3600:.1f}小时"


def detect_category(term):
    """根据搜索词判断品类（整词匹配）"""
    term_lower = term.lower()
    for category, keywords in CATEGORY_PATTERNS:
        for keyword in keywords:
            pattern = rf'(^|[^a-z]){re.escape(keyword)}([^a-z]|$)'
            if re.search(pattern, term_lower):
                return category
    return ''


def execute_with_deadlock_retry(cursor, sql, max_retries=3, retry_delay=2):
    """
    执行 SQL，遇到死锁时自动重试
    
    Args:
        cursor: 数据库 cursor
        sql: 要执行的 SQL
        max_retries: 最大重试次数
        retry_delay: 每次重试间隔（秒）
    
    Returns:
        rowcount: 更新的行数
    """
    for attempt in range(max_retries):
        try:
            cursor.execute(sql)
            return cursor.rowcount
        except OperationalError as e:
            # 检查是否是死锁错误
            error_msg = str(e).lower()
            if 'deadlock' in error_msg or '死锁' in error_msg:
                if attempt < max_retries - 1:
                    print(f"\n⚠️ 检测到死锁，第 {attempt + 1} 次重试 ({retry_delay}s)...", end='', flush=True)
                    time.sleep(retry_delay)
                    # 增加延迟时间，给数据库更多时间解决冲突
                    retry_delay = min(retry_delay * 2, 30)  # 最大延迟30秒
                    continue
                else:
                    # 重试次数用尽，返回 -1 表示失败
                    print(f"\n❌ 死锁重试 {max_retries} 次后仍失败，跳过本批")
                    return -1
            else:
                # 其他 OperationalError，直接抛出
                raise
    return -1


def fix_first_last_seen_batch(batch_size=20000, start_offset=0):
    """
    分批修复 first_seen / last_seen（避免死锁）
    
    策略：
    1. 获取所有 search_term_id 列表
    2. 每批 batch_size 个 id
    3. 每批独立查询 SearchTermMetric 统计 + 更新
    4. 每批独立事务，及时提交释放锁
    5. 支持从指定偏移量开始（断点续传）
    6. 死锁自动重试
    
    Args:
        batch_size: 每批处理的记录数
        start_offset: 从第几条记录开始（用于断点续传）
    """
    print("="*70)
    print("分批修复 first_seen / last_seen（避免死锁）")
    print("="*70)
    
    # 获取所有 ID
    print("正在获取搜索词 ID 列表...", end='', flush=True)
    term_ids = list(SearchTerm.objects.using('aba_db').values_list('id', flat=True).order_by('id'))
    total = len(term_ids)
    print(f" 共 {total:,} 条\n")
    
    if total == 0:
        print("没有记录需要处理")
        return 0
    
    # 如果指定了起始偏移量，跳过前面的
    if start_offset > 0:
        if start_offset >= total:
            print(f"⚠️ 起始偏移量 {start_offset:,} 已超过总数 {total:,}，无需处理")
            return 0
        print(f"🔄 断点续传：跳过前 {start_offset:,} 条，从第 {start_offset + 1:,} 条开始\n")
        term_ids = term_ids[start_offset:]
        processed_total = start_offset
    else:
        processed_total = 0
    
    remaining_total = len(term_ids)
    
    print(f"每批处理: {batch_size:,} 条")
    print(f"预计批数: {(remaining_total + batch_size - 1) // batch_size:,} 批")
    print(f"开始处理...（按 Ctrl+C 可中断）\n")
    
    updated_total = 0
    deadlock_skipped = 0  # 记录因死锁跳过的批次数
    start_time = time.time()
    
    try:
        for i in range(0, remaining_total, batch_size):
            batch_num = i // batch_size + 1
            batch_ids = term_ids[i:i + batch_size]
            batch_start = time.time()
            actual_processed = start_offset + i  # 实际处理进度（含跳过的）
            
            # 显示进度（在执行前）
            elapsed = time.time() - start_time
            percent = actual_processed / total * 100
            speed = actual_processed / elapsed if elapsed > 0 else 0
            remaining = (total - actual_processed) / speed if speed > 0 else 0
            
            print(f"[{actual_processed:,}/{total:,} {percent:.1f}%] "
                  f"第 {batch_num} 批 ({len(batch_ids):,} 条) | "
                  f"累计更新 {updated_total:,} | "
                  f"速度 {speed:.0f}条/秒 | "
                  f"剩余 {format_duration(remaining)}", end='', flush=True)
            
            # 执行本批更新（独立事务）
            ids_str = ','.join(str(id_) for id_ in batch_ids)
            sql = f"""
                WITH stats AS (
                    SELECT 
                        search_term_id,
                        MIN(report_week) as first_week,
                        MAX(report_week) as last_week
                    FROM search_term_metrics
                    WHERE search_term_id IN ({ids_str})
                    GROUP BY search_term_id
                )
                UPDATE search_terms
                SET 
                    first_seen = stats.first_week,
                    last_seen = stats.last_week
                FROM stats
                WHERE search_terms.id = stats.search_term_id
                  AND (search_terms.first_seen IS DISTINCT FROM stats.first_week
                       OR search_terms.last_seen IS DISTINCT FROM stats.last_week);
            """
            
            with connections['aba_db'].cursor() as cursor:
                updated = execute_with_deadlock_retry(cursor, sql, max_retries=3, retry_delay=2)
                
                if updated == -1:
                    # 死锁导致失败，记录但继续下一批
                    deadlock_skipped += 1
                    updated = 0
                else:
                    updated_total += updated
            
            batch_elapsed = time.time() - batch_start
            if deadlock_skipped > 0:
                print(f" | 本批更新 {updated:,} 条 ({batch_elapsed:.1f}s) [死锁跳过: {deadlock_skipped}批]")
            else:
                print(f" | 本批更新 {updated:,} 条 ({batch_elapsed:.1f}s)")
            
    except KeyboardInterrupt:
        actual_processed = start_offset + min(i + batch_size, remaining_total)
        print(f"\n\n⚠️ 用户中断，已处理 {actual_processed:,}/{total:,} 条，"
              f"累计更新 {updated_total:,} 条")
        if deadlock_skipped > 0:
            print(f"   死锁跳过: {deadlock_skipped} 批")
        return updated_total
    
    elapsed = time.time() - start_time
    print(f"\n✅ 完成！共更新 {updated_total:,} 条，耗时 {format_duration(elapsed)}")
    print(f"   平均速度: {total/elapsed:.0f}条/秒（含查询）")
    if deadlock_skipped > 0:
        print(f"   ⚠️ 因死锁跳过: {deadlock_skipped} 批，建议稍后单独处理这些批次")
    print()
    return updated_total


def fix_category_batch(batch_size=20000, start_offset=0):
    """
    分批填充 category（避免死锁）
    
    Args:
        batch_size: 每批处理的记录数
        start_offset: 从第几条记录开始（用于断点续传）
    """
    print("="*70)
    print("分批填充 category（只填充空值）")
    print("="*70)
    
    # 只获取 category 为空的 ID
    empty_ids = list(SearchTerm.objects.using('aba_db').filter(
        category=''
    ).values_list('id', flat=True).order_by('id'))
    
    total = len(empty_ids)
    print(f"需要处理的记录数: {total:,}\n")
    
    if total == 0:
        print("没有空 category 需要填充\n")
        return 0
    
    # 如果指定了起始偏移量，跳过前面的
    if start_offset > 0:
        if start_offset >= total:
            print(f"⚠️ 起始偏移量 {start_offset:,} 已超过总数 {total:,}，无需处理")
            return 0
        print(f"🔄 断点续传：跳过前 {start_offset:,} 条，从第 {start_offset + 1:,} 条开始\n")
        empty_ids = empty_ids[start_offset:]
        processed_offset = start_offset
    else:
        processed_offset = 0
    
    remaining_total = len(empty_ids)
    
    # 生成 CASE WHEN SQL
    case_conditions = []
    for category, keywords in CATEGORY_PATTERNS:
        for kw in keywords:
            case_conditions.append(f"WHEN term ~* '\\y{kw}\\y' THEN '{category}'")
    case_sql = "\n                ".join(case_conditions)
    
    print(f"每批处理: {batch_size:,} 条")
    print(f"预计批数: {(remaining_total + batch_size - 1) // batch_size:,} 批")
    print(f"开始处理...（按 Ctrl+C 可中断）\n")
    
    updated_total = 0
    deadlock_skipped = 0
    start_time = time.time()
    
    try:
        for i in range(0, remaining_total, batch_size):
            batch_num = i // batch_size + 1
            batch_ids = empty_ids[i:i + batch_size]
            batch_start = time.time()
            actual_processed = processed_offset + i
            
            # 显示进度
            elapsed = time.time() - start_time
            percent = actual_processed / total * 100
            speed = actual_processed / elapsed if elapsed > 0 else 0
            remaining = (total - actual_processed) / speed if speed > 0 else 0
            
            print(f"[{actual_processed:,}/{total:,} {percent:.1f}%] "
                  f"第 {batch_num} 批 ({len(batch_ids):,} 条) | "
                  f"累计更新 {updated_total:,} | "
                  f"速度 {speed:.0f}条/秒 | "
                  f"剩余 {format_duration(remaining)}", end='', flush=True)
            
            # 执行本批更新
            ids_str = ','.join(str(id_) for id_ in batch_ids)
            sql = f"""
                UPDATE search_terms
                SET category = CASE
                    {case_sql}
                    ELSE ''
                END
                WHERE id IN ({ids_str})
                  AND category = '';
            """
            
            with connections['aba_db'].cursor() as cursor:
                updated = execute_with_deadlock_retry(cursor, sql, max_retries=3, retry_delay=2)
                
                if updated == -1:
                    deadlock_skipped += 1
                    updated = 0
                else:
                    updated_total += updated
            
            batch_elapsed = time.time() - batch_start
            if deadlock_skipped > 0:
                print(f" | 本批更新 {updated:,} 条 ({batch_elapsed:.1f}s) [死锁跳过: {deadlock_skipped}批]")
            else:
                print(f" | 本批更新 {updated:,} 条 ({batch_elapsed:.1f}s)")
            
    except KeyboardInterrupt:
        actual_processed = processed_offset + min(i + batch_size, remaining_total)
        print(f"\n\n⚠️ 用户中断，已处理 {actual_processed:,}/{total:,} 条，"
              f"累计更新 {updated_total:,} 条")
        if deadlock_skipped > 0:
            print(f"   死锁跳过: {deadlock_skipped} 批")
        return updated_total
    
    elapsed = time.time() - start_time
    print(f"\n✅ 完成！共标记 {updated_total:,} 条，耗时 {format_duration(elapsed)}")
    print(f"   平均速度: {total/elapsed:.0f}条/秒\n")
    return updated_total


def verify_data():
    """验证数据"""
    print("="*70)
    print("数据验证")
    print("="*70)
    
    total = SearchTerm.objects.using('aba_db').count()
    with_category = SearchTerm.objects.using('aba_db').exclude(category='').count()
    with_dates = SearchTerm.objects.using('aba_db').exclude(first_seen__isnull=True).count()
    
    print(f"\n📊 统计:")
    print(f"  总记录数: {total:,}")
    print(f"  有品类:   {with_category:,} ({with_category/total*100:.1f}%)")
    print(f"  有日期:   {with_dates:,} ({with_dates/total*100:.1f}%)")
    
    print(f"\n📋 Category 样本（10条）:")
    for s in SearchTerm.objects.using('aba_db').exclude(category='').order_by('?')[:10]:
        print(f"  {s.term[:40]:<40} | {s.category}")
    
    print(f"\n📋 日期样本（5条）:")
    for s in SearchTerm.objects.using('aba_db').exclude(first_seen__isnull=True).order_by('?')[:5]:
        print(f"  {s.term[:35]:<35} | 首次:{s.first_seen} | 最后:{s.last_seen}")


def run():
    """运行全部修复流程（分批版）"""
    parser = argparse.ArgumentParser(description='修复 SearchTerm 数据脚本')
    parser.add_argument('--offset', type=int, default=0, 
                        help='起始偏移量，用于断点续传（从第N条开始）')
    parser.add_argument('--batch-size', type=int, default=20000,
                        help='每批处理的记录数（默认20000）')
    parser.add_argument('--skip-category', action='store_true',
                        help='跳过 category 填充步骤')
    parser.add_argument('--skip-dates', action='store_true',
                        help='跳过 first_seen/last_seen 修复步骤')
    args = parser.parse_args()
    
    print(f"\n开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"⚡ 分批极速模式（每批 {args.batch_size:,} 条，避免死锁）")
    if args.offset > 0:
        print(f"🔄 断点续传模式（从第 {args.offset:,} 条开始）")
    print()
    
    # 修复日期
    if not args.skip_dates:
        fix_first_last_seen_batch(batch_size=args.batch_size, start_offset=args.offset)
    
    # 填充品类（category 的 offset 应该单独计算，因为数据集不同）
    if not args.skip_category:
        # category 只处理空值的记录，所以 offset 逻辑不同
        # 如果需要断点续传 category，建议单独运行
        fix_category_batch(batch_size=args.batch_size, start_offset=0)
    
    # 验证
    verify_data()
    
    print("\n" + "="*70)
    print(f"全部完成！结束时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*70)


if __name__ == '__main__':
    run()
