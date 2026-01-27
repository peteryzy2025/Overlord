#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os
import sys
import django

# ========== Django环境初始化 ==========
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
sys.path.append(PROJECT_ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Overlord.settings")
django.setup()

# ========== 导入模型与函数 ==========
from track.models import Tracking
from api.track.track_api import get_tracking_updates


def main():
    """
    独立脚本入口：从数据库获取所有物流单号（排除已签收），调用API批量更新
    """
    # 1. 获取所有未签收的物流单号
    total_count = Tracking.objects.count()
    track_nos = list(Tracking.objects.exclude(transit_status='DELIVERED').values_list('track_no', flat=True))

    if not track_nos:
        print(f"⚠️ 数据库中没有需要更新的物流单号 (总计: {total_count}, 已签收跳过: {total_count})")
        return

    skipped_count = total_count - len(track_nos)
    print(f"📦 从数据库加载 {len(track_nos)} 个物流单号 (总计: {total_count}, 已签收跳过: {skipped_count})")

    # 2. 调用 track_api 的批量更新函数
    result = get_tracking_updates(track_nos)

    # 3. 打印执行总结
    print("\n" + "=" * 50)
    if result.get('success'):
        print(f"✅ 脚本执行完成！")
        print(f"   总计: {result['data']['total']}")
        print(f"   成功: {result['data']['success_count']}")
        print(f"   失败: {result['data']['fail_count']}")
    else:
        print(f"❌ 脚本执行失败: {result.get('message', '未知错误')}")
    print("=" * 50)


if __name__ == '__main__':
    main()