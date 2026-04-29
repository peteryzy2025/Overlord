#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
同步亚马逊订单详情（完整信息）到本地数据库
作用范围：最近14天内、状态为Unshipped、且详情记录不存在的订单
核心逻辑：只写入一次，永不更新，跳过已存在详情的订单
修复：支持同一订单号多店铺，避免重复写入
关键：同步更新主表 latest_ship_date 以支持索引查询
"""

import os
import sys
import django
import asyncio
import argparse
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from asgiref.sync import sync_to_async
from django.db import transaction

# ========== Django环境初始化 ==========
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
sys.path.insert(0, PROJECT_ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Overlord.settings")
django.setup()

from api.Y.y_tiem import Timer
from amazon.models import AmazonOrders, AmazonOrderFullDetail, AmazonOrderItemFullDetail, LingXingAmazonShop
from api.lingxing_p.lingxing_jc1 import get_amazon_order_detail


def parse_args():
    parser = argparse.ArgumentParser(description="同步亚马逊订单详情")
    parser.add_argument("--project-id", type=int, help="指定项目 ID 同步")
    parser.add_argument("--project-name", type=str, help="指定项目名称同步（支持模糊匹配）")
    return parser.parse_args()


# ========== 时间转换工具 ==========
def _to_datetime(value):
    """安全转换字符串为datetime（跳过None和空值）"""
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00'))
    except:
        try:
            return datetime.strptime(value, '%Y-%m-%d %H:%M:%S')
        except:
            return None


def _to_decimal(value, default=0):
    """安全转换值为Decimal"""
    if value in (None, '', 'null'):
        return Decimal(str(default))
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(str(default))


# ========== 步骤1：筛选待同步订单 ==========
@sync_to_async
def find_Unshipped_orders_without_detail(days_back=14, project_id=None, project_name=None):
    """
    查询最近N天内、状态为Unshipped、且无详情记录的订单
    返回: [(amazon_order_id, sid), ...] 元组列表
    """
    start_date = datetime.now() - timedelta(days=days_back)
    start_date = start_date.replace(hour=0, minute=0, second=0, microsecond=0)

    filters = {
        'order_status': 'Unshipped',
        'purchase_date_local__gte': start_date,
        'full_detail__isnull': True,
        'amazon_shop__project__is_active': True,
    }
    
    if project_id:
        filters['amazon_shop__project_id'] = project_id
    elif project_name:
        filters['amazon_shop__project__name__icontains'] = project_name

    # 筛选条件：Unshipped+ 14天内 + 无详情记录
    order_list = list(AmazonOrders.objects.filter(
        **filters
    ).values_list('amazon_order_id', 'lingxing_shop__sid').distinct())

    filter_desc = f"项目条件={project_id or project_name} " if (project_id or project_name) else ""
    print(f"【查询】{filter_desc}找到 {len(order_list)} 条待同步详情的Unshipped订单（最近{days_back}天）")
    if order_list:
        print(f"【样本】前3条订单: {order_list[:3]}")

    return order_list


@sync_to_async
def group_order_tuples_by_credentials(order_tuples):
    sid_set = {sid for _, sid in order_tuples if sid}
    shops = (
        LingXingAmazonShop.objects
        .filter(sid__in=sid_set)
        .select_related('amazon_shop__project')
    )
    sid_info = {}
    for shop in shops:
        project = shop.amazon_shop.project if shop.amazon_shop else None
        sid_info[shop.sid] = {
            'project_id': project.id if project else None,
            'project_name': project.name if project else None,
            'app_id': project.lingxing_app_id if project else None,
            'app_secret': project.lingxing_app_secret if project else None,
        }

    groups = {}
    skipped = []
    for order_id, sid in order_tuples:
        info = sid_info.get(sid)
        if not info or not info['project_id']:
            skipped.append((order_id, sid, '店铺未绑定项目'))
            continue
        if not info['app_id'] or not info['app_secret']:
            skipped.append((order_id, sid, f"项目 {info['project_name']} 未配置领星 API 凭证"))
            continue

        key = (str(info['app_id']).strip(), str(info['app_secret']).strip())
        if key not in groups:
            groups[key] = {
                'app_id': key[0],
                'app_secret': key[1],
                'project_names': set(),
                'tuples': [],
            }
        groups[key]['project_names'].add(info['project_name'])
        groups[key]['tuples'].append((order_id, sid))

    result = []
    for group in groups.values():
        group['project_name'] = '、'.join(sorted(group['project_names']))
        del group['project_names']
        result.append(group)

    return result, skipped


# ========== 步骤2：保存订单详情（严格过滤+重复检测） ==========
@sync_to_async
def save_order_full_details(details: list, candidate_set: set):
    """
    批量保存订单详情（严格过滤重复和多店铺）

    :param details: API返回的详情列表
    :param candidate_set: 候选订单集合，格式 {('order_id', sid), ...}
    :return: (成功数, 跳过数, 失败数, 重复报告)
    """
    if not details:
        return 0, 0, 0, {}

    success_count = 0
    skip_count = 0
    fail_count = 0

    # 跟踪已处理的组合
    processed_set = set()
    # 重复报告：key 为 order_id, value 为重复的sid列表
    duplicate_report = {}

    for detail in details:
        amazon_order_id = detail.get('amazon_order_id')
        sid = detail.get('sid')
        key = (amazon_order_id, sid)

        # 第一层过滤：必须在候选集合中
        if key not in candidate_set:
            continue

        # 第二层过滤：检测重复（同一 order_id + sid）
        if key in processed_set:
            # 记录重复
            if amazon_order_id not in duplicate_report:
                duplicate_report[amazon_order_id] = []
            duplicate_report[amazon_order_id].append(sid)
            continue

        processed_set.add(key)

        # 第三层过滤：检查详情是否已存在
        try:
            order = AmazonOrders.objects.select_related('lingxing_shop').get(
                amazon_order_id=amazon_order_id,
                lingxing_shop__sid=sid
            )

            # 检查详情是否存在
            if hasattr(order, 'full_detail') and order.full_detail:
                skip_count += 1
                continue
        except Exception as e:
            print(f"❌ 查询订单失败 {amazon_order_id} (sid={sid}): {e}")
            fail_count += 1
            continue

        # 保存逻辑...
        try:
            with transaction.atomic():
                # 1. 保存订单级详情
                order_detail = AmazonOrderFullDetail(
                    order=order,
                    sid=sid,
                    amazon_order_id=amazon_order_id,
                    fulfillment_channel=detail.get('fulfillment_channel'),
                    order_status_detail=detail.get('order_status'),
                    order_total_amount_detail=_to_decimal(detail.get('order_total_amount')),
                    currency=detail.get('currency'),
                    icon=detail.get('icon'),
                    is_assessed=detail.get('is_assessed', 0),
                    is_mcf_order=detail.get('is_mcf_order', 0),
                    is_return_order=detail.get('is_return_order', 0),
                    is_replaced_order=detail.get('is_replaced_order', 0),
                    is_replacement_order=detail.get('is_replacement_order', 0),
                    is_business_order=detail.get('is_business_order', 0),
                    is_prime=detail.get('is_prime', 0),
                    is_premium_order=detail.get('is_premium_order', 0),
                    is_promotion=detail.get('is_promotion', 0),
                    purchase_date_local_detail=_to_datetime(detail.get('purchase_date_local')),
                    last_update_date_detail=_to_datetime(detail.get('last_update_date')),
                    posted_date=_to_datetime(detail.get('posted_date')),
                    shipment_date_detail=_to_datetime(detail.get('shipment_date')),
                    earliest_ship_date=_to_datetime(detail.get('earliest_ship_date')),
                    purchase_date_utc_detail=_to_datetime(detail.get('purchase_date_local_utc')),
                    last_update_date_utc_detail=_to_datetime(detail.get('last_update_date_utc')),
                    earliest_ship_date_utc=_to_datetime(detail.get('earliest_ship_date_utc')),
                    latest_ship_date=_to_datetime(detail.get('latest_ship_date')),
                    earliest_delivery_date=_to_datetime(detail.get('earliest_delivery_date')),
                    latest_delivery_date=_to_datetime(detail.get('latest_delivery_date')),
                    ship_service_level=detail.get('ship_service_level'),
                    shipment_service_level_category=detail.get('shipment_service_level_category'),
                    number_of_items_shipped=detail.get('number_of_items_shipped', 0),
                    number_of_items_unshipped=detail.get('number_of_items_unshipped', 0),
                    sales_channel=detail.get('sales_channel'),
                    taxes_included=detail.get('taxes_included', 0),
                    payment_method=detail.get('payment_method'),
                    cba_displayable_shipping_label=detail.get('cba_displayable_shipping_label'),
                    purchase_order_number=detail.get('purchase_order_number'),
                    order_type=detail.get('order_type'),
                    buyer_name_detail=detail.get('name'),
                    buyer_phone_raw=detail.get('phone'),
                    buyer_phone_clean=detail.get('phone', '').split('ext.')[0].strip() if detail.get('phone') else '',
                    buyer_email_detail=detail.get('buyer_email'),
                    shipping_address_line1=detail.get('address_line1'),
                    shipping_address_line2=detail.get('address_line2'),
                    shipping_city=detail.get('city'),
                    shipping_state=detail.get('state_or_region'),
                    shipping_postal_code=detail.get('postal_code'),
                    shipping_country_code=detail.get('country_code'),
                    shipping_address_full=str(detail.get('shipping_address', '')),
                )
                order_detail.save()
                success_count += 1

                # 2. 同步更新主表的 latest_ship_date（关键！支持索引查询）
                if not order.latest_ship_date and order_detail.latest_ship_date:
                    order.latest_ship_date = order_detail.latest_ship_date
                    order.save(update_fields=['latest_ship_date'])
                    print(f"   🔄 同步更新主表 latest_ship_date: {order.amazon_order_id}")

                # 3. 保存商品级详情
                item_list = detail.get('item_list', [])
                if item_list:
                    item_objects = []
                    for item in item_list:
                        item_objects.append(AmazonOrderItemFullDetail(
                            order_item_id=item.get('order_item_id'),
                            order=order,
                            seller_sku=item.get('seller_sku'),
                            asin=item.get('asin'),
                            title=item.get('title'),
                            asin_url=item.get('asin_url'),
                            pic_url=item.get('pic_url'),
                            sku=item.get('sku'),
                            product_id=item.get('product_id'),
                            product_name=item.get('product_name'),
                            quantity_ordered=item.get('quantity_ordered', 1),
                            quantity_shipped=item.get('quantity_shipped', 0),
                            item_price_amount=_to_decimal(item.get('item_price_amount')),
                            item_tax_amount=_to_decimal(item.get('item_tax_amount')),
                            shipping_price_amount=_to_decimal(item.get('shipping_price_amount')),
                            shipping_tax_amount=_to_decimal(item.get('shipping_tax_amount')),
                            gift_wrap_price_amount=_to_decimal(item.get('gift_wrap_price_amount')),
                            gift_wrap_tax_amount=_to_decimal(item.get('gift_wrap_tax_amount')),
                            shipping_discount_amount=_to_decimal(item.get('shipping_discount_amount')),
                            promotion_discount_amount=_to_decimal(item.get('promotion_discount_amount')),
                            fba_shipment_amount=_to_decimal(item.get('fba_shipment_amount')),
                            commission_amount=_to_decimal(item.get('commission_amount')),
                            cod_fee_amount=_to_decimal(item.get('cod_fee_amount')),
                            other_amount=_to_decimal(item.get('other_amount')),
                            cg_price=_to_decimal(item.get('cg_price')),
                            cg_transport_costs=_to_decimal(item.get('cg_transport_costs')),
                            profit=_to_decimal(item.get('profit')),
                            fee_currency=item.get('fee_currency'),
                            fee_icon=item.get('fee_icon'),
                            fee_cost_amount=_to_decimal(item.get('fee_cost_amount')),
                            fee_cost=_to_decimal(item.get('fee_cost')),
                            sales_price_amount=_to_decimal(item.get('sales_price_amount')),
                            unit_price_amount=_to_decimal(item.get('unit_price_amount')),
                            tax_amount=_to_decimal(item.get('tax_amount')),
                            promotion_amount=_to_decimal(item.get('promotion_amount')),
                            item_discount=_to_decimal(item.get('item_discount')),
                            condition_id=item.get('condition_id'),
                            condition_subtype_id=item.get('condition_subtype_id'),
                            condition_note=item.get('condition_note'),
                            gift_message_text=item.get('gift_message_text'),
                            gift_wrap_level=item.get('gift_wrap_level'),
                            is_buyer_requested_cancel=item.get('is_buyer_requested_cancel') == 'true',
                            buyer_cancel_reason=item.get('buyer_cancel_reason'),
                            promotion_ids=item.get('promotion_ids', []),
                            points_monetary_value_amount=_to_decimal(item.get('points_monetary_value_amount')),
                            scheduled_delivery_start_date=_to_datetime(item.get('scheduled_delivery_start_date')),
                            scheduled_delivery_end_date=_to_datetime(item.get('scheduled_delivery_end_date')),
                            price_designation=item.get('price_designation'),
                            customized_json=item.get('customized_json', {}),
                            attachments=item.get('attachments', []),
                        ))

                    AmazonOrderItemFullDetail.objects.bulk_create(
                        item_objects,
                        ignore_conflicts=True
                    )

        except Exception as e:
            print(f"❌ 订单 {amazon_order_id} (sid={sid}) 保存失败: {str(e)}")
            fail_count += 1

    return success_count, skip_count, fail_count, duplicate_report


# ========== 主流程控制器 ==========
async def lx_order_info_main(project_id=None, project_name=None):
    """
    主流程：同步Unshipped订单详情
    """
    print("\n" + "=" * 96)
    print("🚀 亚马逊订单详情同步脚本启动")
    print(f"📅 目标范围：最近14天内、状态为Unshipped、且无详情记录的订单")
    print(f"🔍 API接口：get_amazon_order_detail（自动分批，每批≤190）")
    if project_id:
        print(f"📌 按项目 ID 过滤：{project_id}")
    elif project_name:
        print(f"📌 按项目名称过滤：'{project_name}'")
    print("=" * 96)

    # 步骤1：筛选订单（返回元组列表）
    print("\n【步骤1】筛选待同步的Unshipped订单...")
    order_tuples = await find_Unshipped_orders_without_detail(
        project_id=project_id, project_name=project_name
    )

    if not order_tuples:
        print("✅ 没有符合条件的订单，任务结束")
        return

    total_to_sync = len(order_tuples)

    print(f"📝 共找到 {total_to_sync} 条订单需要同步详情")

    # 步骤2：按项目分组并调用API获取详情
    print("\n【步骤2】按项目分组，调用领星API获取订单详情...")
    project_groups, skipped = await group_order_tuples_by_credentials(order_tuples)
    if skipped:
        print(f"⚠️ 跳过 {len(skipped)} 条无法获取项目凭证的订单")
        for order_id, sid, reason in skipped[:10]:
            print(f"   - {order_id} / sid={sid}: {reason}")
        if len(skipped) > 10:
            print(f"   ... 还有 {len(skipped) - 10} 条未显示")

    if not project_groups:
        print("❌ 没有可用项目凭证，任务结束")
        return

    total_details = 0
    success = 0
    skipped_save = 0
    failed = 0
    duplicates = {}
    for group in project_groups:
        group_tuples = group['tuples']
        order_ids = list(dict.fromkeys(oid for oid, _ in group_tuples))
        print(
            f"项目 [{group['project_name']}] 开始获取 {len(order_ids)} 个订单详情 "
            f"(候选记录 {len(group_tuples)} 条)"
        )
        try:
            details = await get_amazon_order_detail(
                order_ids,
                app_id=group['app_id'],
                app_secret=group['app_secret'],
            )
        except Exception as e:
            print(f"❌ 项目 [{group['project_name']}] API获取失败: {str(e)}，跳过该项目")
            failed += len(group_tuples)
            continue

        if not details:
            print(f"⚠️ 项目 [{group['project_name']}] API未返回任何详情数据")
            continue

        total_details += len(details)
        print(f"✅ 项目 [{group['project_name']}] 成功获取 {len(details)} 条订单详情")

        group_success, group_skipped, group_failed, group_duplicates = await save_order_full_details(
            details,
            set(group_tuples),
        )
        success += group_success
        skipped_save += group_skipped
        failed += group_failed
        for order_id, sid_list in group_duplicates.items():
            duplicates.setdefault(order_id, []).extend(sid_list)

    if total_details == 0:
        print("⚠️ API未返回任何详情数据")
        return

    # 步骤3：保存详情（已在各项目内保存）
    print("\n【步骤3】保存详情到数据库完成（存在则跳过）")

    # 步骤4：打印重复报告
    if duplicates:
        print("\n⚠️  检测到重复订单，详细信息：")
        print("-" * 96)
        print(f"{'订单号':<25} | {'SID':<10} | {'店铺名称':<30}")
        print("-" * 96)

        for order_id, sid_list in duplicates.items():
            for sid in sid_list:
                # 查询店铺名称
                try:
                    shop = LingXingAmazonShop.objects.get(sid=sid)
                    shop_name = shop.name or '未知'
                except:
                    shop_name = '未找到'

                print(f"{order_id:<25} | {sid:<10} | {shop_name:<30}")

        print("-" * 96)
        total_duplicates = sum(len(sids) for sids in duplicates.values())
        print(f"重复订单总数: {total_duplicates} 条")
        print("=" * 96)

    # 最终统计报告
    detail_attempted = success + skipped_save + failed
    not_in_candidate = max(total_details - detail_attempted, 0)
    print("\n" + "=" * 96)
    print("📊 任务完成！最终统计报告")
    print("=" * 96)
    print(f"📈 候选订单数: {total_to_sync}")
    print(f"🎯 API返回详情数: {total_details}")
    print(f"✅ 成功写入: {success} 条")
    print(f"⏭️  跳过（已存在）: {skipped_save} 条")
    print(f"⏭️  跳过（无项目凭证）: {len(skipped)} 条")
    print(f"⏭️  跳过（不在候选）: {not_in_candidate} 条")
    print(f"❌ 失败: {failed} 条")
    print(f"✅ 最终成功率: {(success / total_to_sync * 100):.1f}%" if total_to_sync > 0 else "0%")
    print("=" * 96)

    if failed > 0:
        print("\n💡 失败原因可能：")
        print("   - 订单在AmazonOrders主表中不存在")
        print("   - 数据格式异常导致保存失败")
        print("   - 数据库约束冲突（理论上不应发生）")


# ========== 入口 ==========
if __name__ == "__main__":
    args = parse_args()
    
    t = Timer()
    t.start()
    asyncio.run(lx_order_info_main(project_id=args.project_id, project_name=args.project_name))
    t.stop()
    print("\n⏱️  运行时长：", t)
