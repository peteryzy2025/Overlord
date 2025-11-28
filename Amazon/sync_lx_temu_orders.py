#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import sys
import django
import asyncio
import datetime
from decimal import Decimal, InvalidOperation
from django.db import transaction

# ====== Django 初始化（保持不变） ======
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
sys.path.append(PROJECT_ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Overlord.settings")
django.setup()

# ====== 导入模型和 API 函数 ======
from Temu.models import LingXingTemuShop, TemuOrder, TemuOrderItem
from Api.lingxing_p.lingxing_temu import get_lx_temu_orders


def _to_decimal(value, default=Decimal('0.00')):
    """安全地把字符串金额转成 Decimal"""
    if value in (None, "", "0.00", "-￥0.00", "￥0.00"):
        return default
    try:
        if isinstance(value, str):
            value = value.replace('￥', '').replace('$', '').replace('€', '').strip()
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        print(f"警告: 金额转换失败: {value}")
        return default


def _timestamp_to_datetime(ts):
    """将 Unix 时间戳转换为 UTC datetime"""
    if not ts or ts == 0:
        return None
    try:
        return datetime.datetime.fromtimestamp(int(ts), tz=datetime.timezone.utc)
    except (ValueError, TypeError):
        print(f"警告: 时间戳转换失败: {ts}")
        return None


def sync_temu_orders(data_dict):
    """
    将拉取的 Temu 订单数据批量写入数据库

    Args:
        data_dict: {store_id: [order_dict, ...], ...}
    """
    # 预加载所有店铺配置
    store_ids = list(data_dict.keys())
    shop_qs = LingXingTemuShop.objects.filter(store_id__in=store_ids)
    shop_map = {shop.store_id: shop for shop in shop_qs}

    print(f"预加载店铺数量: {len(shop_map)}")

    # 统计信息
    total_orders = 0
    created_orders = 0
    updated_orders = 0
    skipped_orders = 0
    total_items = 0

    # 大事务包裹整个同步过程
    with transaction.atomic():
        for store_id, orders in data_dict.items():
            lingxing_shop = shop_map.get(store_id)
            if not lingxing_shop:
                print(f"错误: 未找到 store_id={store_id} 的店铺配置，跳过该店铺 {len(orders)} 条订单")
                skipped_orders += len(orders)
                continue

            for raw_order in orders:
                try:
                    global_order_no = raw_order.get("global_order_no")
                    if not global_order_no:
                        print(f"警告: 订单数据缺少 global_order_no，跳过: {raw_order}")
                        skipped_orders += 1
                        continue

                    # ========== 准备订单数据 ==========
                    defaults = {
                        'lingxing_shop': lingxing_shop,
                        'reference_no': raw_order.get('reference_no'),
                        'order_from_name': raw_order.get('order_from_name'),
                        'delivery_type': raw_order.get('delivery_type'),
                        'split_type': raw_order.get('split_type'),
                        'status': raw_order.get('status'),
                        'wid': raw_order.get('wid'),
                        'warehouse_name': raw_order.get('warehouse_name'),
                        'amount_currency': raw_order.get('amount_currency'),
                        'supplier_id': raw_order.get('supplier_id'),
                        'is_delete': raw_order.get('is_delete', 0),
                        'global_purchase_time': _timestamp_to_datetime(raw_order.get('global_purchase_time')),
                        'global_payment_time': _timestamp_to_datetime(raw_order.get('global_payment_time')),
                        'global_review_time': _timestamp_to_datetime(raw_order.get('global_review_time')),
                        'global_distribution_time': _timestamp_to_datetime(raw_order.get('global_distribution_time')),
                        'global_print_time': _timestamp_to_datetime(raw_order.get('global_print_time')),
                        'global_mark_time': _timestamp_to_datetime(raw_order.get('global_mark_time')),
                        'global_delivery_time': _timestamp_to_datetime(raw_order.get('global_delivery_time')),
                        'global_create_time': raw_order.get('global_create_time'),
                        'receiver_country_code': raw_order.get('address_info', {}).get('receiver_country_code'),
                        'postal_code': raw_order.get('address_info', {}).get('postal_code'),
                        'city': raw_order.get('address_info', {}).get('city'),
                        'tracking_number': raw_order.get('logistics_info', {}).get('tracking_no'),
                        'logistics_provider_name': raw_order.get('logistics_info', {}).get('logistics_provider_name'),
                        'order_total_amount': _to_decimal(
                            raw_order.get('transaction_info', [{}])[0].get('order_total_amount')
                        ),
                        'buyer_name_masked': raw_order.get('buyers_info', {}).get('buyer_name'),
                        'buyer_email_masked': raw_order.get('buyers_info', {}).get('buyer_email'),
                        'order_tag': raw_order.get('order_tag'),
                        'pending_order_tag': raw_order.get('pending_order_tag'),
                        'exception_order_tag': raw_order.get('exception_order_tag'),
                        'buyers_info': raw_order.get('buyers_info'),
                        'address_info': raw_order.get('address_info'),
                        'platform_info': raw_order.get('platform_info'),
                        'payment_info': raw_order.get('payment_info'),
                        'logistics_info': raw_order.get('logistics_info'),
                        'transaction_info': raw_order.get('transaction_info'),
                        'order_custom_fields': raw_order.get('order_custom_fields'),
                    }

                    # ========== 更新或创建订单主表 ==========
                    order, created = TemuOrder.objects.update_or_create(
                        global_order_no=global_order_no,
                        defaults=defaults
                    )

                    if created:
                        created_orders += 1
                    else:
                        updated_orders += 1
                    total_orders += 1

                    # ========== 处理订单明细 ==========
                    item_list = raw_order.get('item_info') or []
                    if item_list:
                        TemuOrderItem.objects.filter(order=order).delete()
                        items_to_create = []
                        seen_global_item_nos = set()

                        for row in item_list:
                            global_item_no = row.get('globalItemNo')

                            if not global_item_no or global_item_no in seen_global_item_nos:
                                print(f"警告: 订单 {global_order_no} 存在重复或无效的 globalItemNo: {global_item_no}")
                                continue

                            seen_global_item_nos.add(global_item_no)
                            items_to_create.append(
                                TemuOrderItem(
                                    order=order,
                                    global_item_no=global_item_no,
                                    platform_order_no=row.get('platform_order_no'),
                                    order_item_no=row.get('order_item_no'),
                                    item_from_name=row.get('item_from_name'),
                                    msku=row.get('msku'),
                                    local_sku=row.get('local_sku'),
                                    product_no=row.get('product_no'),
                                    title=row.get('title'),
                                    variant_attr=row.get('variant_attr'),
                                    unit_price_amount=_to_decimal(row.get('unit_price_amount')),
                                    item_price_amount=_to_decimal(row.get('item_price_amount')),
                                    quantity=row.get('quantity', 0),
                                    platform_status=row.get('platform_status'),
                                    type=row.get('type'),
                                    data_json=row.get('data_json'),
                                    item_custom_fields=row.get('item_custom_fields'),
                                    is_delete=row.get('is_delete', 0),
                                )
                            )

                        if items_to_create:
                            TemuOrderItem.objects.bulk_create(items_to_create)
                            total_items += len(items_to_create)

                except Exception as e:
                    print(
                        f"错误: 处理订单失败 - store_id: {store_id}, order_no: {raw_order.get('global_order_no')}, 错误: {e}")
                    skipped_orders += 1
                    continue

    # ========== 同步统计 ==========
    print(
        f"\n同步完成 - 订单总计: {total_orders}, 新增: {created_orders}, 更新: {updated_orders}, 跳过: {skipped_orders}, 商品明细总数: {total_items}")


def temu_orders():
    """主入口函数"""
    print("=" * 50)
    print("开始同步 Temu 订单数据...")

    # 1. 获取所有店铺
    store_ids = list(LingXingTemuShop.objects.values_list('store_id', flat=True))

    if not store_ids:
        print("未找到任何 Temu 店铺配置，同步终止")
        return

    print(f"共找到 {len(store_ids)} 个店铺")

    # 2. 拉取订单数据（默认3天）
    try:
        orders_data = asyncio.run(get_lx_temu_orders(store_ids, day=7))
    except Exception as e:
        print(f"调用领星 API 失败: {e}")
        return

    if not orders_data:
        print("API 返回空数据")
        return

    print(f"API 返回数据包含 {len(orders_data)} 个店铺的订单")

    # 3. 写入数据库
    sync_temu_orders(orders_data)
    print("Temu 订单同步任务全部完成")


if __name__ == "__main__":
    temu_orders()