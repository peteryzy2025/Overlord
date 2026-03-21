#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
修复 SearchTerm 数据脚本（分批极速版 - 避免死锁）

优化策略：
1. 分批处理，每批独立事务，避免长时间锁表导致死锁
2. 每批 20,000 条，平衡速度和锁竞争
3. 实时显示进度、速度、预计剩余时间

使用方法:
    cd D:\Y-Project\Overlord
    .venv\Scripts\python.exe aba\sync\fix_search_term_data_fast.py
"""
import os
import sys
import re
import time
from pathlib import Path
from datetime import datetime

# Django 环境初始化
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Overlord.settings')
import django
django.setup()

from django.db import connections, transaction
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


def fix_first_last_seen_batch(batch_size=20000):
    """
    分批修复 first_seen / last_seen（避免死锁）
    
    策略：
    1. 获取所有 search_term_id 列表
    2. 每批 batch_size 个 id
    3. 每批独立查询 SearchTermMetric 统计 + 更新
    4. 每批独立事务，及时提交释放锁
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
    
    print(f"每批处理: {batch_size:,} 条")
    print(f"预计批数: {(total + batch_size - 1) // batch_size:,} 批")
    print(f"开始处理...（按 Ctrl+C 可中断）\n")
    
    updated_total = 0
    start_time = time.time()
    
    try:
        for i in range(0, total, batch_size):
            batch_num = i // batch_size + 1
            batch_ids = term_ids[i:i + batch_size]
            batch_start = time.time()
            
            # 显示进度（在执行前）
            elapsed = time.time() - start_time
            percent = i / total * 100
            speed = i / elapsed if elapsed > 0 else 0
            remaining = (total - i) / speed if speed > 0 else 0
            
            print(f"[{i:,}/{total:,} {percent:.1f}%] "
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
                cursor.execute(sql)
                updated = cursor.rowcount
                updated_total += updated
            
            batch_elapsed = time.time() - batch_start
            print(f" | 本批更新 {updated:,} 条 ({batch_elapsed:.1f}s)")
            
    except KeyboardInterrupt:
        print(f"\n\n⚠️ 用户中断，已处理 {min(i + batch_size, total):,}/{total:,} 条，"
              f"累计更新 {updated_total:,} 条")
        return updated_total
    
    elapsed = time.time() - start_time
    print(f"\n✅ 完成！共更新 {updated_total:,} 条，耗时 {format_duration(elapsed)}")
    print(f"   平均速度: {total/elapsed:.0f}条/秒（含查询）")
    print()
    return updated_total


def fix_category_batch(batch_size=20000):
    """
    分批填充 category（避免死锁）
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
    
    # 生成 CASE WHEN SQL
    case_conditions = []
    for category, keywords in CATEGORY_PATTERNS:
        for kw in keywords:
            case_conditions.append(f"WHEN term ~* '\\y{kw}\\y' THEN '{category}'")
    case_sql = "\n                ".join(case_conditions)
    
    print(f"每批处理: {batch_size:,} 条")
    print(f"预计批数: {(total + batch_size - 1) // batch_size:,} 批")
    print(f"开始处理...（按 Ctrl+C 可中断）\n")
    
    updated_total = 0
    start_time = time.time()
    
    try:
        for i in range(0, total, batch_size):
            batch_num = i // batch_size + 1
            batch_ids = empty_ids[i:i + batch_size]
            batch_start = time.time()
            
            # 显示进度
            elapsed = time.time() - start_time
            percent = i / total * 100
            speed = i / elapsed if elapsed > 0 else 0
            remaining = (total - i) / speed if speed > 0 else 0
            
            print(f"[{i:,}/{total:,} {percent:.1f}%] "
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
                cursor.execute(sql)
                updated = cursor.rowcount
                updated_total += updated
            
            batch_elapsed = time.time() - batch_start
            print(f" | 本批更新 {updated:,} 条 ({batch_elapsed:.1f}s)")
            
    except KeyboardInterrupt:
        print(f"\n\n⚠️ 用户中断，已处理 {min(i + batch_size, total):,}/{total:,} 条，"
              f"累计更新 {updated_total:,} 条")
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
    print(f"\n开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("⚡ 分批极速模式（每批 20,000 条，避免死锁）\n")
    
    # 修复日期
    fix_first_last_seen_batch(batch_size=20000)
    
    # 填充品类
    fix_category_batch(batch_size=20000)
    
    # 验证
    verify_data()
    
    print("\n" + "="*70)
    print(f"全部完成！结束时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*70)


if __name__ == '__main__':
    run()
