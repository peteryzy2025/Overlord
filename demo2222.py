#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
查看用户 ID 17 和 25 的详细信息
"""

import os
import sys
import django

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = CURRENT_DIR
sys.path.append(PROJECT_ROOT)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Overlord.settings")
django.setup()

from general.models import User, AmazonShop

def main():
    print("\n" + "="*70)
    print("查看关键用户信息")
    print("="*70 + "\n")
    
    # 查看 sync_rangking_day.py 包含的用户列表
    sync_users = User.objects.filter(
        status=User.Status.NORMAL,
        department=User.Department.OPERATION,
        company_id=1
    )
    print("sync_rangking_day.py 统计的用户列表:")
    for u in sync_users:
        print(f"  ID:{u.id} | {u.first_name or u.username}")
    print(f"  共 {sync_users.count()} 人\n")
    
    # 重点查看 ID 17 和 25
    print("="*70)
    print("重点检查用户 ID 17 和 25:")
    print("="*70)
    
    for uid in [17, 25]:
        user = User.objects.filter(id=uid).first()
        if user:
            print(f"\n用户 ID: {uid}")
            print(f"  姓名 (first_name): {user.first_name}")
            print(f"  用户名 (username): {user.username}")
            print(f"  部门 (department): {user.department}")
            print(f"  状态 (status): {user.status} (1=正常, 2=禁用/其他)")
            print(f"  公司ID (company_id): {user.company_id}")
            
            # 统计该用户负责的店铺数
            amazon_shop_count = AmazonShop.objects.filter(ops=uid, company_id=1).count()
            print(f"  负责的 Amazon 店铺数: {amazon_shop_count}")
            
            # 是否被 sync_rangking_day.py 统计
            is_in_sync = sync_users.filter(id=uid).exists()
            print(f"  是否被 sync_rangking_day.py 统计: {'是' if is_in_sync else '否'}")
        else:
            print(f"\n用户 ID {uid} 不存在")
    
    print("\n" + "="*70)
    print("结论:")
    print("  如果 ID 17 或 25 的 status 不是 1，则他们不会被 sync_rangking_day.py 统计")
    print("  但他们负责的店铺会被 Dashboard 统计，造成数据差异")
    print("="*70 + "\n")

if __name__ == "__main__":
    main()
