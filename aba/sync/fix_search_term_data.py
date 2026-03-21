#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
修复 SearchTerm 数据脚本（带实时进度统计）
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

from django.db import transaction
from django.db.models import Min, Max
from aba.models import SearchTerm, SearchTermMetric


CATEGORY_PATTERNS = [
    ('shirt', ['shirt', 'shirts', 't-shirt', 'tshirt', 'tee', 'tees', 'polo shirt']),
    ('hat', ['hat', 'hats', 'cap', 'caps', 'baseball cap', 'snapback', 'bucket hat']),
    ('sticker', ['sticker', 'stickers', 'decal', 'decals']),
    ('flag', ['flag', 'flags', 'garden flag', 'yard flag', 'banner flag']),
    ('banner', ['banner', 'banners', 'wall banner', 'hanging banner']),
    ('blanket', ['blanket', 'blankets', 'throw blanket', 'fleece blanket']),
    ('sock', ['sock', 'socks', 'crew sock', 'ankle sock']),
    ('apron', ['apron', 'aprons', 'kitchen apron', 'bbq apron']),
    ('badge', ['badge', 'badges', 'pin', 'pins', 'button pin']),
    ('makeup bag', ['makeup bag', 'makeup bags', 'cosmetic bag', 'toiletry bag']),
    ('canvas bag', ['canvas bag', 'canvas bags', 'tote bag', 'tote bags', 'shopping bag']),
    ('sign', ['sign', 'signs', 'metal sign', 'tin sign', 'vintage sign']),
    ('tapestry', ['tapestry', 'tapestries', 'wall tapestry', 'wall hanging']),
]


def format_duration(seconds):
    """格式化时长"""
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


def fix_first_last_seen(batch_size=1000):
    """修复 first_seen / last_seen（强制更新，带实时进度）"""
    print("="*70)
    print("修复 first_seen / last_seen（强制更新）")
    print("="*70)
    
    # 先获取所有ID
    print("正在获取搜索词列表...", end='', flush=True)
    term_ids = list(SearchTerm.objects.using('aba_db').values_list('id', flat=True))
    total = len(term_ids)
    print(f" 共 {total:,} 条")
    
    if total == 0:
        print("没有记录需要处理")
        return 0
    
    print(f"\n开始处理，每批 {batch_size} 条...")
    print("（首次查询可能需要几秒到几十秒，请等待）\n")
    
    processed = 0
    updated = 0
    start_time = time.time()
    batch = []
    
    try:
        for i in range(0, total, batch_size):
            batch_ids = term_ids[i:i + batch_size]
            
            # 显示当前进度（在查询前）
            elapsed = time.time() - start_time
            percent = i / total * 100
            speed = i / elapsed if elapsed > 0 else 0
            
            print(f"\r[{i:,}/{total:,} {percent:.1f}%] "
                  f"已更新 {updated:,} | "
                  f"速度 {speed:.0f}条/秒 | "
                  f"正在查询第 {i//batch_size + 1} 批统计信息...", 
                  end='', flush=True)
            
            # 从 SearchTermMetric 统计（这里可能慢）
            stats = list(SearchTermMetric.objects.using('aba_db').filter(
                search_term_id__in=batch_ids
            ).values('search_term_id').annotate(
                first=Min('report_week'),
                last=Max('report_week')
            ))
            
            stat_map = {s['search_term_id']: (s['first'], s['last']) for s in stats}
            
            # 查询当前 batch 的 SearchTerm
            terms = list(SearchTerm.objects.using('aba_db').filter(id__in=batch_ids))
            
            for term_obj in terms:
                if term_obj.id in stat_map:
                    first, last = stat_map[term_obj.id]
                    if term_obj.first_seen != first or term_obj.last_seen != last:
                        term_obj.first_seen = first
                        term_obj.last_seen = last
                        batch.append(term_obj)
                        updated += 1
            
            # 批量更新
            if batch:
                with transaction.atomic(using='aba_db'):
                    SearchTerm.objects.using('aba_db').bulk_update(
                        batch, ['first_seen', 'last_seen']
                    )
                batch = []
            
            processed = min(i + batch_size, total)
            
    except KeyboardInterrupt:
        print(f"\n\n⚠️ 用户中断，已处理 {processed:,} 条，更新 {updated:,} 条")
        return updated
    
    # 处理剩余
    if batch:
        with transaction.atomic(using='aba_db'):
            SearchTerm.objects.using('aba_db').bulk_update(
                batch, ['first_seen', 'last_seen']
            )
    
    elapsed = time.time() - start_time
    print(f"\r[{total:,}/{total:,} 100.0%] "
          f"已更新 {updated:,} | 完成！耗时 {format_duration(elapsed)}")
    print()
    return updated


def fix_category(batch_size=1000):
    """填充 category 字段（只填充空的，带实时进度）"""
    print("="*70)
    print("填充 category（只填充空值）")
    print("="*70)
    
    queryset = SearchTerm.objects.using('aba_db').filter(category='')
    total = queryset.count()
    
    if total == 0:
        print("没有空 category 需要填充")
        return 0
    
    print(f"需要处理的记录数: {total:,}\n")
    
    processed = 0
    marked = 0
    start_time = time.time()
    batch = []
    
    try:
        for term_obj in queryset.iterator(chunk_size=batch_size):
            category = detect_category(term_obj.term)
            
            if category:
                term_obj.category = category
                batch.append(term_obj)
                marked += 1
            
            processed += 1
            
            # 批量更新
            if len(batch) >= batch_size:
                with transaction.atomic(using='aba_db'):
                    SearchTerm.objects.using('aba_db').bulk_update(
                        batch, ['category']
                    )
                batch = []
            
            # 显示进度（每1000条刷新）
            if processed % 1000 == 0 or processed >= total:
                elapsed = time.time() - start_time
                percent = processed / total * 100
                speed = processed / elapsed if elapsed > 0 else 0
                remaining = (total - processed) / speed if speed > 0 else 0
                
                print(f"\r[{processed:,}/{total:,} {percent:.1f}%] "
                      f"已标记 {marked:,} | "
                      f"速度 {speed:.0f}条/秒 | "
                      f"剩余 {format_duration(remaining)}", 
                      end='', flush=True)
                
    except KeyboardInterrupt:
        if batch:
            with transaction.atomic(using='aba_db'):
                SearchTerm.objects.using('aba_db').bulk_update(
                    batch, ['category']
                )
        print(f"\n\n⚠️ 用户中断，已处理 {processed:,} 条，标记 {marked:,} 条")
        return marked
    
    # 处理剩余
    if batch:
        with transaction.atomic(using='aba_db'):
            SearchTerm.objects.using('aba_db').bulk_update(
                batch, ['category']
            )
    
    elapsed = time.time() - start_time
    print(f"\r[{total:,}/{total:,} 100.0%] "
          f"已标记 {marked:,} | 完成！耗时 {format_duration(elapsed)}")
    print()
    return marked


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
    """运行全部修复流程"""
    print(f"\n开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    fix_first_last_seen(batch_size=1000)
    fix_category(batch_size=1000)
    verify_data()
    
    print("\n" + "="*70)
    print(f"全部完成！结束时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*70)


if __name__ == '__main__':
    run()
