#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import sys
import django
import asyncio
import argparse
import datetime
from decimal import Decimal, InvalidOperation
from django.db import transaction

# ====== Django 初始化（保持不变） ======
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
sys.path.insert(0, PROJECT_ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Overlord.settings")
django.setup()

# ====== 导入模型和 API 函数 ======
from temu.models import LingXingTemuShop, TemuOrder, TemuOrderItem
from api.lingxing_p.lingxing_temu import get_lx_temu_orders, check_temu_order_to_divi, shipment_order, get_wms_orders_by_order_numbers
from asgiref.sync import async_to_sync
import asyncio


def parse_args():
    parser = argparse.ArgumentParser(description="同步Temu订单数据")
    parser.add_argument("--project-id", type=int, help="指定项目 ID 同步")
    parser.add_argument("--project-name", type=str, help="指定项目名称同步（支持模糊匹配）")
    return parser.parse_args()


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


def get_temu_order_lingxing_credentials(global_order_no):
    order = (
        TemuOrder.objects
        .select_related('temu_shop__project', 'lingxing_shop__temu_shop__project')
        .filter(global_order_no=global_order_no)
        .first()
    )
    if not order:
        return None, f"未找到 Temu 订单 {global_order_no}"

    temu_shop = order.temu_shop or (order.lingxing_shop.temu_shop if order.lingxing_shop else None)
    project = temu_shop.project if temu_shop else None
    if not project:
        return None, f"订单 {global_order_no} 未绑定项目"
    if not project.lingxing_app_id or not project.lingxing_app_secret:
        return None, f"项目 {project.name}(ID:{project.id}) 未配置领星 API 凭证"

    return {
        'project_id': project.id,
        'project_name': project.name,
        'app_id': project.lingxing_app_id,
        'app_secret': project.lingxing_app_secret,
    }, None


def sync_temu_orders(data_dict):
    """
    将拉取的 Temu 订单数据批量写入数据库

    Args:
        data_dict: {store_id: [order_dict, ...], ...}
    """
    # 预加载所有店铺配置
    store_ids = list(data_dict.keys())
    shop_qs = LingXingTemuShop.objects.filter(store_id__in=store_ids).select_related('temu_shop')
    shop_map = {shop.store_id: shop for shop in shop_qs}

    print(f"预加载店铺数量: {len(shop_map)}")

    # 统计信息
    total_orders = 0
    created_orders = 0
    updated_orders = 0
    skipped_orders = 0
    total_items = 0
    
    # 收集需要检查 DIVI 状态的订单ID（已存在且 divi_order_status != 5）
    orders_to_check_divi = []
    # 收集状态为5（待发货）的订单ID
    orders_to_ship = []

    # 大事务包裹整个同步过程
    with transaction.atomic():
        for store_id, orders in data_dict.items():
            lingxing_shop = shop_map.get(store_id)
            if not lingxing_shop:
                print(f"错误: 未找到 store_id={store_id} 的店铺配置，跳过该店铺 {len(orders)} 条订单")
                skipped_orders += len(orders)
                continue

            # ========== 店铺级统计初始化 ==========
            shop_created_orders = 0
            shop_updated_orders = 0
            shop_total_items = 0
            shop_name = getattr(lingxing_shop, 'store_name', None) or store_id  # 安全获取店铺名称

            for raw_order in orders:
                try:
                    global_order_no = raw_order.get("global_order_no")
                    if not global_order_no:
                        print(f"警告: 订单数据缺少 global_order_no，跳过: {raw_order}")
                        skipped_orders += 1
                        continue

                    # ========== 准备订单数据 ==========
                    # 从 platform_info 提取 Temu 平台订单号
                    platform_info_list = raw_order.get('platform_info', [])
                    platform_order_no = None
                    if platform_info_list and isinstance(platform_info_list, list) and len(platform_info_list) > 0:
                        platform_order_no = platform_info_list[0].get('platform_order_no')
                    # 如果 platform_info 中没有，则尝试从商品明细中获取
                    if not platform_order_no:
                        item_info = raw_order.get('item_info', [])
                        if item_info and isinstance(item_info, list) and len(item_info) > 0:
                            platform_order_no = item_info[0].get('platform_order_no')
                    
                    defaults = {
                        'lingxing_shop': lingxing_shop,
                        'temu_shop': lingxing_shop.temu_shop,
                        'reference_no': platform_order_no or raw_order.get('reference_no'),
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
                        shop_created_orders += 1  # 店铺级统计
                    else:
                        updated_orders += 1
                        shop_updated_orders += 1  # 店铺级统计
                        # 如果是已存在的订单，且 DIVI 状态不是已发货(5)，则加入检查列表
                        if order.divi_order_status != 5:
                            orders_to_check_divi.append(order.global_order_no)
                        # 如果订单状态为5（待发货），则加入发货列表
                        if order.status == 5:
                            orders_to_ship.append(order.global_order_no)
                    total_orders += 1

                    # ========== 处理订单明细 ==========
                    item_list = raw_order.get('item_info') or []
                    if item_list:
                        TemuOrderItem.objects.filter(order=order).delete()
                        items_to_create = []
                        seen_global_item_nos = set()

                        for row in item_list:
                            global_item_no = row.get('global_item_no') or row.get('globalItemNo')

                            if not global_item_no or global_item_no in seen_global_item_nos:
                                print(f"警告: 订单 {global_order_no} 存在重复或无效的 global_item_no: {global_item_no}")
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
                            shop_total_items += len(items_to_create)  # 店铺级统计

                except Exception as e:
                    print(
                        f"错误: 处理订单失败 - store_id: {store_id}, order_no: {raw_order.get('global_order_no')}, 错误: {e}")
                    skipped_orders += 1
                    continue

            # ========== 打印店铺级统计 ==========
            print(f"\n【店铺: {shop_name} (ID: {store_id})】订单处理完成 - 新增: {shop_created_orders}条 | 更新: {shop_updated_orders}条 | 商品明细: {shop_total_items}条")

    # ========== 同步统计 ==========
    print(
        f"\n同步完成 - 订单总计: {total_orders}, 新增: {created_orders}, 更新: {updated_orders}, 跳过: {skipped_orders}, 商品明细总数: {total_items}")
    
    # ========== 批量检查 DIVI 状态 ==========
    if orders_to_check_divi:
        print(f"\n开始检查 {len(orders_to_check_divi)} 个订单的 DIVI 状态...")
        for sn_no in orders_to_check_divi:
            try:
                # 使用 async_to_sync 调用异步函数
                async_to_sync(check_temu_order_to_divi)(sn_no)
                print(f"  ✓ 订单 {sn_no} DIVI 状态检查完成")
            except Exception as e:
                print(f"  ✗ 订单 {sn_no} DIVI 状态检查失败: {e}")
        print("DIVI 状态检查完成")
    
    # ========== 批量处理待发货订单 ==========
    if orders_to_ship:
        print(f"\n开始处理 {len(orders_to_ship)} 个待发货订单...")
        for sn_no in orders_to_ship:
            credentials, credential_error = get_temu_order_lingxing_credentials(sn_no)
            if credential_error:
                print(f"  ✗ 订单 {sn_no} 缺少项目领星凭证: {credential_error}")
                continue

            try:
                # 先执行发货
                async_to_sync(shipment_order)(
                    sn_no,
                    app_id=credentials['app_id'],
                    app_secret=credentials['app_secret'],
                )
            except Exception as e:
                print(f"  ✗ 订单 {sn_no} 发货失败: {e}")
                continue
            
            try:
                # 再下载面单
                async_to_sync(get_wms_orders_by_order_numbers)(
                    sn_no,
                    app_id=credentials['app_id'],
                    app_secret=credentials['app_secret'],
                )
            except Exception as e:
                print(f"  ✗ 订单 {sn_no} 下载面单失败: {e}")
        print("待发货订单处理完成")

def temu_orders(project_id=None, project_name=None):
    """主入口函数"""
    print("=" * 50)
    print("开始同步 Temu 订单数据...")
    
    if project_id:
        print(f"按项目 ID 过滤：{project_id}")
    elif project_name:
        print(f"按项目名称过滤：'{project_name}'")

    # 1. 获取店铺
    qs = LingXingTemuShop.objects.select_related('temu_shop__project')
    
    # 按项目过滤（通过关联的 temu_shop -> project）
    if project_id:
        qs = qs.filter(temu_shop__project_id=project_id)
    elif project_name:
        qs = qs.filter(temu_shop__project__name__icontains=project_name)
    
    shops = list(qs)

    if not shops:
        filter_desc = f"项目条件={project_id or project_name} " if (project_id or project_name) else ""
        print(f"未找到任何{filter_desc}Temu店铺配置，同步终止")
        return

    project_shops = {}
    skipped_shops = []
    for shop in shops:
        project = shop.temu_shop.project if shop.temu_shop else None
        if not project:
            skipped_shops.append((shop.store_id, shop.store_name, '未绑定项目'))
            continue
        if not project.lingxing_app_id or not project.lingxing_app_secret:
            skipped_shops.append((shop.store_id, shop.store_name, f"项目 {project.name} 未配置领星 API 凭证"))
            continue

        if project.id not in project_shops:
            project_shops[project.id] = {
                'project': project,
                'store_ids': [],
                'shop_map': {},
            }
        project_shops[project.id]['store_ids'].append(shop.store_id)
        project_shops[project.id]['shop_map'][shop.store_id] = shop.store_name or shop.store_id

    if skipped_shops:
        print(f"跳过 {len(skipped_shops)} 个未绑定项目或缺少领星凭证的 Temu 店铺")
        for store_id, store_name, reason in skipped_shops[:10]:
            print(f"  - {store_name or store_id}({store_id}): {reason}")
        if len(skipped_shops) > 10:
            print(f"  ... 还有 {len(skipped_shops) - 10} 个未显示")

    if not project_shops:
        print("没有可用项目凭证的 Temu 店铺，同步终止")
        return

    print(f"共找到 {len(shops)} 个店铺，分布在 {len(project_shops)} 个可同步项目")

    # 2. 拉取订单数据（默认3天）
    has_data = False
    for data in project_shops.values():
        project = data['project']
        store_ids = data['store_ids']
        shop_map = data['shop_map']
        print(f"\n项目 [{project.name}] 开始同步 {len(store_ids)} 个 Temu 店铺")
        try:
            orders_data = asyncio.run(
                get_lx_temu_orders(
                    store_ids,
                    day=14,
                    shop_map=shop_map,
                    app_id=project.lingxing_app_id,
                    app_secret=project.lingxing_app_secret,
                )
            )
        except Exception as e:
            print(f"项目 [{project.name}] 调用领星 API 失败: {e}")
            continue

        if not orders_data:
            print(f"项目 [{project.name}] API 返回空数据")
            continue

        has_data = True
        print(f"项目 [{project.name}] API 返回数据包含 {len(orders_data)} 个店铺的订单")

        # 3. 写入数据库
        sync_temu_orders(orders_data)

    if not has_data:
        print("所有项目均未返回 Temu 订单数据")
        return

    print("Temu 订单同步任务全部完成")


if __name__ == "__main__":
    args = parse_args()
    temu_orders(project_id=args.project_id, project_name=args.project_name)
