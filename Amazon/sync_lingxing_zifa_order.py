#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
同步领星自发货订单号到本地数据库
用于补充 amazon_orders 表中 order_no 为空的订单（包括 NULL 和空字符串）
核心逻辑：通过 sid + platform_order_id 唯一定位订单，补全 order_no
"""

import os
import sys
import django
import asyncio
from datetime import datetime, timedelta
from asgiref.sync import sync_to_async
from django.db import transaction
from django.db.models import Q  # 正确导入路径

# ========== Django环境初始化 ==========
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
sys.path.append(PROJECT_ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Overlord.settings")
django.setup()

from Amazon.models import AmazonOrders, LingXingAmazonShop
from Api.lingxing_p.lingxing_jc1 import get_lingxing_zifa_order

# ========== 配置项 ==========
DAYS_BACK = 10  # 查询最近5天 order_no 为空的订单
API_DAYS = 10  # 调用API查询最近3天的自发货订单


@sync_to_async
def get_orders_missing_order_no(days_back=DAYS_BACK):
    """
    查询最近N天内 order_no 为空的自发货订单（包括 NULL 和空字符串）
    返回: 字典列表 [{'lingxing_shop__sid': 123, 'amazon_order_id': 'xxx'}, ...]
    """
    start_date = datetime.now() - timedelta(days=days_back)
    start_date = start_date.replace(hour=0, minute=0, second=0, microsecond=0)

    # 关键修改：同时查询 NULL 和空字符串
    orders_list = list(AmazonOrders.objects.filter(
        # 核心：使用 Q 对象组合 OR 条件
        Q(order_no__isnull=True) | Q(order_no=''),  # NULL 或 空字符串
        purchase_date_local__gte=start_date,  # 最近N天
        fulfillment_channel='MFN'  # 仅自发货订单
    ).values(
        'lingxing_shop__sid',
        'amazon_order_id'
    ).distinct())

    print(f"【查询】找到 {len(orders_list)} 条 order_no 为空的订单（最近{days_back}天）")
    if len(orders_list) > 0:
        # 打印前3条调试验证
        print(f"【样本】前3条样本数据: {orders_list[:3]}")
    return orders_list


@sync_to_async
def batch_orders_by_sid(orders_list):
    """
    将订单按 sid 分组，便于批量查询
    返回: {sid: [amazon_order_id1, amazon_order_id2, ...]}
    """
    sid_orders_map = {}
    for order in orders_list:
        sid = order['lingxing_shop__sid']
        amazon_order_id = order['amazon_order_id']
        if sid not in sid_orders_map:
            sid_orders_map[sid] = []
        sid_orders_map[sid].append(amazon_order_id)

    print(f"【分组】涉及 {len(sid_orders_map)} 个领星店铺 sid")
    for sid, order_ids in sorted(sid_orders_map.items()):
        print(f"         sid={sid}: {len(order_ids)} 个订单待更新")

    return sid_orders_map


async def fetch_zifa_orders_for_sid(sid, days=API_DAYS):
    """
    异步获取指定 sid 的自发货订单列表
    返回: API响应数据列表
    """
    try:
        print(f"【API调用】获取 sid={sid} 的自发货订单（最近{days}天）...")
        resp_data = await get_lingxing_zifa_order(sid=sid, days=days)
        return resp_data or []
    except Exception as e:
        print(f"【API错误】sid={sid} 获取失败: {e}")
        return []


def parse_zifa_order_data(zifa_data):
    """
    解析自发货订单数据，建立 platform_order_id 到 order_number 的映射
    关键：一个 order_number 可能对应多个 platform_order_id（拆单情况）
    返回: {platform_order_id: order_number}
    """
    order_map = {}
    for item in zifa_data:
        order_number = item.get('order_number')
        platform_list = item.get('platform_list', [])

        if not order_number or not platform_list:
            continue

        for platform_order_id in platform_list:
            # 建立正向映射，便于后续查找
            order_map[platform_order_id] = order_number

    print(f"【解析】从 {len(zifa_data)} 条记录中提取出 {len(order_map)} 个平台订单ID映射")
    return order_map


@sync_to_async
def update_order_no(sid, amazon_order_id, order_number):
    """
    更新指定订单的 order_no 字段（同时兼容 NULL 和空字符串）
    使用 sid + amazon_order_id 唯一定位，避免不同店铺订单号重复问题
    返回: (success: bool, message: str)
    """
    try:
        # 获取 lingxing_shop 实例
        lingxing_shop = LingXingAmazonShop.objects.filter(sid=sid).first()
        if not lingxing_shop:
            return False, f"未找到 sid={sid} 的领星店铺"

        # 使用事务确保数据一致性
        with transaction.atomic():
            # 核心：通过 lingxing_shop + amazon_order_id 唯一定位订单
            # 同时兼容 NULL 和空字符串
            updated = AmazonOrders.objects.filter(
                lingxing_shop=lingxing_shop,
                amazon_order_id=amazon_order_id,
                # 关键：同时检查 NULL 和空字符串
                order_no__isnull=True
            ).update(
                order_no=order_number,
            )

            # 如果上面的更新没生效，再尝试更新空字符串的情况
            if updated == 0:
                updated = AmazonOrders.objects.filter(
                    lingxing_shop=lingxing_shop,
                    amazon_order_id=amazon_order_id,
                    order_no=''  # 空字符串的情况
                ).update(
                    order_no=order_number,
                )

            if updated > 0:
                return True, f"成功更新 order_no={order_number}"
            else:
                # 检查是否已存在 order_no
                exists = AmazonOrders.objects.filter(
                    lingxing_shop=lingxing_shop,
                    amazon_order_id=amazon_order_id
                ).exclude(order_no__isnull=True).exclude(order_no='').exists()

                if exists:
                    return True, f"订单已存在 order_no，跳过"
                else:
                    return False, f"未找到匹配的订单记录"

    except Exception as e:
        return False, f"更新失败: {str(e)}"


async def process_sid_orders(sid, amazon_order_ids):
    """
    处理单个 sid 的所有订单
    1. 获取该 sid 的自发货订单数据
    2. 建立 platform_order_id -> order_number 映射
    3. 批量更新本地订单
    返回: (success_count, fail_count)
    """
    print(f"\n{'=' * 70}")
    print(f"【处理】sid: {sid} | 待更新订单数: {len(amazon_order_ids)}")
    print(f"{'=' * 70}")

    # 步骤1: 获取自发货订单数据
    zifa_data = await fetch_zifa_orders_for_sid(sid, days=API_DAYS)

    if not zifa_data:
        print(f"【结果】sid={sid} 未获取到任何自发货订单数据")
        return 0, len(amazon_order_ids)

    print(f"【数据】从领星获取到 {len(zifa_data)} 条自发货订单记录")

    # 步骤2: 解析映射关系
    order_map = parse_zifa_order_data(zifa_data)

    if not order_map:
        print(f"【警告】sid={sid} 未解析出任何有效的订单映射，跳过处理")
        return 0, len(amazon_order_ids)

    # 步骤3: 逐个订单更新
    success_count = 0
    fail_count = 0

    for i, amazon_order_id in enumerate(amazon_order_ids, 1):
        print(f"【更新】({i:>3}/{len(amazon_order_ids)}) {amazon_order_id}", end=" -> ")

        if amazon_order_id in order_map:
            order_number = order_map[amazon_order_id]
            success, message = await update_order_no(sid, amazon_order_id, order_number)

            if success:
                print(f"✓ 成功 (order_no={order_number})")
                success_count += 1
            else:
                print(f"✗ 失败: {message}")
                fail_count += 1
        else:
            print("⚠ 未在自发货数据中找到匹配")
            fail_count += 1

    print(f"\n【汇总】sid={sid} | 成功: {success_count} | 失败: {fail_count}")
    return success_count, fail_count


async def main():
    """主流程控制器"""
    print("\n" + "=" * 96)
    print("🚀 领星自发货订单号同步脚本启动")
    print(f"📅 目标范围：最近 {DAYS_BACK} 天内 order_no 为空的 MFN 订单")
    print(f"🔍 API查询：最近 {API_DAYS} 天的自发货数据")
    print("=" * 96)

    # 步骤1: 查询需要更新的订单
    print("\n【步骤1】查询本地数据库...")
    orders_to_update = await get_orders_missing_order_no()

    if not orders_to_update:
        print("✅ 没有需要更新的订单，任务结束")
        return

    total_orders = len(orders_to_update)
    print(f"📝 共找到 {total_orders} 条待更新订单")

    # 步骤2: 按 sid 分组
    print("\n【步骤2】按领星店铺 sid 分组订单...")
    sid_orders_map = await batch_orders_by_sid(orders_to_update)

    # 步骤3: 并发或顺序处理每个 sid
    print("\n【步骤3】开始逐店同步自发货订单号...")
    total_success = 0
    total_fail = 0

    # 注意：这里顺序处理避免API限流，如需并发可使用 asyncio.gather
    for sid, amazon_order_ids in sorted(sid_orders_map.items()):
        success, fail = await process_sid_orders(sid, amazon_order_ids)
        total_success += success
        total_fail += fail

        # 为避免触发API限流，每个sid处理后稍微等待
        await asyncio.sleep(0.5)

    # 步骤4: 最终统计报告
    print("\n" + "=" * 96)
    print("📊 任务完成！最终统计报告")
    print("=" * 96)
    print(f"📈 总订单数: {total_orders}")
    print(f"✅ 成功更新: {total_success} 条")
    print(f"❌ 失败/跳过: {total_fail} 条")
    print(f"📊 成功率: {(total_success / total_orders * 100):.1f}%" if total_orders > 0 else "0%")
    print("=" * 96)

    if total_fail > 0:
        print("\n💡 提示：失败的订单可能是因为")
        print("   - API未返回该订单（超过3天或状态不符）")
        print("   - 订单不属于自发货（MFN）")
        print("   - 店铺配置不完整")
    print("\n🎉 所有处理完成！")


if __name__ == '__main__':
    # 运行异步主函数
    asyncio.run(main())