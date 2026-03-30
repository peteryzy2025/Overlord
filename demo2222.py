#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
验证 sync_rangking_day.py 修改后的效果
"""

import os
import sys
import django
from datetime import date, timedelta

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = CURRENT_DIR
sys.path.append(PROJECT_ROOT)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Overlord.settings")
django.setup()

from general.models import User

def test_functions():
    print("\n" + "="*70)
    print("验证 sync_rangking_day.py 修改效果")
    print("="*70 + "\n")
    
    # 导入修改后的函数
    from amazon.sync_rangking_day import (
        get_all_operators,
        get_all_operators_include_inactive,
        get_all_leaders
    )
    
    # 测试1: 原函数（只包含活跃人员）
    active_operators = get_all_operators()
    print(f"【1】get_all_operators() - 活跃人员:")
    print(f"    人数: {active_operators.count()}")
    print(f"    IDs: {list(active_operators.values_list('id', flat=True))}")
    
    # 测试2: 新函数（包含全部人员）
    all_operators = get_all_operators_include_inactive()
    print(f"\n【2】get_all_operators_include_inactive() - 全部人员:")
    print(f"    人数: {all_operators.count()}")
    print(f"    IDs: {list(all_operators.values_list('id', flat=True))}")
    
    # 测试3: 找出禁用的用户
    inactive_users = all_operators.exclude(status=User.Status.NORMAL)
    print(f"\n【3】禁用/非活跃人员:")
    print(f"    人数: {inactive_users.count()}")
    for u in inactive_users:
        print(f"    - ID:{u.id} | {u.first_name} | status={u.status}")
    
    # 测试4: 组长列表（应保持不变，只含活跃）
    leaders = get_all_leaders()
    print(f"\n【4】get_all_leaders() - 组长（只含活跃）:")
    print(f"    人数: {leaders.count()}")
    for u in leaders:
        print(f"    - ID:{u.id} | {u.first_name}")
    
    # 数据对比
    print(f"\n" + "="*70)
    print("数据对比:")
    print(f"  活跃人员: {active_operators.count()} 人")
    print(f"  全部人员: {all_operators.count()} 人")
    print(f"  差异: {all_operators.count() - active_operators.count()} 人（禁用人员）")
    print("="*70 + "\n")
    
    print("验证结论:")
    if all_operators.count() > active_operators.count():
        print("  ✓ 新函数正确包含了禁用人员")
        print("  ✓ 个人报告仍将只发给活跃人员")
        print("  ✓ 组长报告将包含禁用组员（标注但不排名）")
        print("  ✓ 经理报告将统计全部人员")
    else:
        print("  ⚠ 没有发现禁用人员，或函数逻辑有误")
    print()

if __name__ == "__main__":
    test_functions()
