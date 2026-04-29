#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import sys
import django
import asyncio
import argparse
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils.dateparse import parse_datetime

# ====== Django 初始化部分（照抄你原来的） ======
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
sys.path.insert(0, PROJECT_ROOT)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Overlord.settings")
django.setup()

from api.Y.y_tiem import Timer
from amazon.models import LingXingAmazonShop, AmazonOrders, AmazonOrderItem
from general.models import AmazonShop, Project
from api.lingxing_p.lingxing_jc1 import get_lingxing_orders


def parse_args():
    parser = argparse.ArgumentParser(description="同步亚马逊订单数据")
    parser.add_argument("--project-id", type=int, help="指定项目 ID 同步")
    parser.add_argument("--project-name", type=str, help="指定项目名称同步（支持模糊匹配）")
    return parser.parse_args()


def _to_decimal(value, default=None):
    """安全地把金额转成 Decimal"""
    if value in (None, ""):
        return default
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return default


def _to_datetime(value):
    """
    安全地把字符串转成 datetime
    关键：保持原始值，不做任何时区转换！
    """
    if not value:
        return None
    # 兼容 '2025-11-16 18:36:28' 和 '2025-11-16T06:36:28+00:00' 这种格式
    dt = parse_datetime(value)
    if dt is None:
        return None

    # 如果带有时区信息，转换为 naive datetime（保持原始小时值）
    # 例如：'2025-11-15T06:42:41Z' -> datetime(2025, 11, 15, 6, 42, 41)
    # 例如：'2025-11-14 22:42:41' -> datetime(2025, 11, 14, 22, 42, 41)
    if dt.tzinfo is not None:
        dt = dt.replace(tzinfo=None)

    return dt


def sync_amazon_orders(data_list):
    """
    把领星订单数据写入本地 AmazonOrders / AmazonOrderItem
    并绑定 LingXingAmazonShop、AmazonShop

    【优化点简介】：
    1. 一次性查询所有会用到的 LingXingAmazonShop，做成字典，避免 N+1 查询
    2. 用一个大的 transaction.atomic() 包住整个同步过程，减少事务开销
    3. 明细行用 bulk_create 批量插入，避免逐条 create
    """

    # ================== 预取店铺，避免 N+1 查询 ==================
    sid_set = set()
    for item in data_list:
        sid = item.get("sid")
        if not sid:
            continue
        try:
            sid_int = int(sid)
        except (TypeError, ValueError):
            continue
        sid_set.add(sid_int)

    # 一次查询所有需要的店铺，并 select_related amazon_shop
    shop_qs = (
        LingXingAmazonShop.objects
        .filter(sid__in=sid_set)
        .select_related("amazon_shop")
    )
    shop_map = {shop.sid: shop for shop in shop_qs}

    print(f"预加载领星店铺数量：{len(shop_map)}")

    # 统计信息
    total_count = 0
    created_count = 0
    updated_count = 0
    skipped_count = 0

    # ================== 一个大事务包裹整个同步 ==================
    # 如果你担心一次事务太大，可以自己按批次拆，比如每 500 条提交一次
    with transaction.atomic():
        for item in data_list:
            amazon_order_id = item.get("amazon_order_id")
            if not amazon_order_id:
                print("跳过：没有 amazon_order_id:", item)
                skipped_count += 1
                continue

            # ========== 通过 sid 从预加载字典中匹配领星店铺 ==========
            sid = item.get("sid")
            try:
                sid_int = int(sid) if sid is not None else None
            except (TypeError, ValueError):
                sid_int = None

            lingxing_shop = shop_map.get(sid_int)

            # 防御性检查：理论上不会出现，除非数据异常或该店铺没预加载到
            if not lingxing_shop:
                print(f"警告：未找到 sid={sid} 的领星店铺，跳过订单 {amazon_order_id}")
                skipped_count += 1
                continue

            # 关联的本地店铺（可能为 None）
            amazon_shop = lingxing_shop.amazon_shop

            # ========== 准备订单主表字段 ==========
            defaults = {
                "lingxing_shop": lingxing_shop,
                "amazon_shop": amazon_shop,

                "order_status": item.get("order_status"),
                "order_total_amount": _to_decimal(item.get("order_total_amount")),
                "order_total_currency_code": item.get("order_total_currency_code"),
                "fulfillment_channel": item.get("fulfillment_channel"),
                "sales_channel": item.get("sales_channel"),

                "buyer_email": item.get("buyer_email"),
                "buyer_name": item.get("buyer_name"),
                "phone": item.get("phone"),
                "address": item.get("address"),
                "postal_code": item.get("postal_code"),

                "tracking_number": item.get("tracking_number"),

                "is_return": item.get("is_return") or 0,
                "is_mcf_order": item.get("is_mcf_order") or 0,
                "is_assessed": item.get("is_assessed") or 0,
                "is_replaced_order": item.get("is_replaced_order") or 0,
                "is_replacement_order": item.get("is_replacement_order") or 0,
                "is_return_order": item.get("is_return_order") or 0,
                "refund_amount": _to_decimal(
                    item.get("refund_amount", 0),
                    default=Decimal("0")
                ),

                # 日期相关 - 关键：保持原始值不变
                "purchase_date_local": _to_datetime(item.get("purchase_date_local")),
                "purchase_date_utc": _to_datetime(
                    item.get("purchase_date_utc") or item.get("purchase_date")
                ),
                "shipment_date_local": _to_datetime(item.get("shipment_date_local")),
                "shipment_date_utc": _to_datetime(
                    item.get("shipment_date_utc") or item.get("shipment_date")
                ),
                "last_update_date_local": _to_datetime(item.get("last_update_date")),
                "last_update_date_utc": _to_datetime(item.get("last_update_date_utc")),

                "earliest_ship_date_local": _to_datetime(item.get("earliest_ship_date_local")),
                "earliest_ship_date_utc": _to_datetime(item.get("earliest_ship_date_utc")),
                "gmt_modified": _to_datetime(item.get("gmt_modified")),
                "gmt_modified_utc": _to_datetime(item.get("gmt_modified_utc")),
                "hide_time": _to_datetime(item.get("hide_time")),
            }

            # 关键：使用 lingxing_shop + amazon_order_id 作为查找条件
            # 这样不同店铺的相同订单号不会冲突
            order, created = AmazonOrders.objects.update_or_create(
                lingxing_shop=lingxing_shop,
                amazon_order_id=amazon_order_id,
                defaults=defaults
            )

            if created:
                created_count += 1
            else:
                updated_count += 1
            total_count += 1

            # ========== 同步明细 item_list，使用 bulk_create ==========
            item_list = item.get("item_list") or []

            # 简单粗暴：先删后插（DELETE 一条 SQL，后面 bulk_create 一条 SQL）
            AmazonOrderItem.objects.filter(order=order).delete()

            seen = set()
            order_items = []
            for row in item_list:
                key = (order.id, row.get("seller_sku"))
                if key in seen:
                    continue
                seen.add(key)
                order_items.append(
                    AmazonOrderItem(
                        order=order,
                        asin=row.get("asin", ""),
                        seller_sku=row.get("seller_sku") or "",
                        local_sku=row.get("local_sku") or "",
                        local_name=row.get("local_name") or "",
                        order_status=row.get("order_status") or "",
                        quantity_ordered=row.get("quantity_ordered") or 1,
                    )
                )

            if order_items:
                AmazonOrderItem.objects.bulk_create(order_items)

    # 打印汇总信息
    print(
        f"\n同步完成：总计 {total_count} 条订单，新增 {created_count} 条，更新 {updated_count} 条，跳过 {skipped_count} 条"
    )


def lx_order_main(project_id=None, project_name=None):
    print("开始同步亚马逊订单数据...")
    
    # 如果指定了项目过滤条件，先打印出来
    if project_id:
        print(f"按项目 ID 过滤：{project_id}")
    elif project_name:
        print(f"按项目名称过滤：'{project_name}'")

    # 1. 从 LingXingAmazonShop 表中获取需要同步的店铺 sid
    #    这里示例按国家="美国"筛选，你可以按需要改条件
    #    同时关联查询 amazon_shop -> project 获取领星 API 配置
    shops = (
        LingXingAmazonShop.objects
        .filter(country="美国", amazon_shop__project__is_active=True)
        .select_related("amazon_shop__project")
    )
    
    # 按项目过滤
    if project_id:
        shops = shops.filter(amazon_shop__project_id=project_id)
    elif project_name:
        shops = shops.filter(amazon_shop__project__name__icontains=project_name)

    if not shops.exists():
        filter_desc = f"项目条件={project_id or project_name} " if (project_id or project_name) else ""
        print(f"没有找到任何{filter_desc}国家为美国的领星店铺，结束。")
        return

    # 按领星凭证分组店铺（多个项目共用同一套凭证时合并请求）
    credential_shops = {}
    skipped_shops = []
    for shop in shops:
        project = shop.amazon_shop.project if shop.amazon_shop else None
        if not project:
            skipped_shops.append((shop.sid, shop.name, "未绑定项目"))
            continue
        if not project.lingxing_app_id or not project.lingxing_app_secret:
            skipped_shops.append((shop.sid, shop.name, f"项目 {project.name} 未配置领星 API 凭证"))
            continue

        key = (project.lingxing_app_id.strip(), project.lingxing_app_secret.strip())
        if key not in credential_shops:
            credential_shops[key] = {
                "app_id": key[0],
                "app_secret": key[1],
                "project_names": set(),
                "sids": [],
            }
        credential_shops[key]["project_names"].add(project.name)
        credential_shops[key]["sids"].append(shop.sid)

    if skipped_shops:
        print(f"跳过 {len(skipped_shops)} 个未绑定项目或缺少领星凭证的店铺")
        for sid, shop_name, reason in skipped_shops[:10]:
            print(f"  - {shop_name or sid}(sid={sid}): {reason}")
        if len(skipped_shops) > 10:
            print(f"  ... 还有 {len(skipped_shops) - 10} 个未显示")

    print(f"共找到 {shops.count()} 个美国店铺，合并为 {len(credential_shops)} 套领星凭证")

    all_orders = []

    # 2. 按领星凭证分组拉取订单数据
    for data in credential_shops.values():
        sids = sorted(set(data["sids"]))
        project_names = "、".join(sorted(data["project_names"]))
        print(f"领星凭证组 [{project_names}] 开始同步 {len(sids)} 个店铺...")
        
        # 用异步接口从领星批量拉取订单（内部会自动按 20 个 sid 分组请求）
        resp_data = asyncio.run(
            get_lingxing_orders(
                sids, 
                days=30,
                app_id=data["app_id"],
                app_secret=data["app_secret"]
            )
        )
        
        if resp_data:
            all_orders.extend(resp_data)
            print(f"领星凭证组 [{project_names}] 获取到 {len(resp_data)} 条订单")
        else:
            print(f"领星凭证组 [{project_names}] 未返回订单数据")

    if not all_orders:
        print("接口没有返回任何订单数据，结束。")
        return
    
    # 3. 写入本地数据库
    print(f"\n总计获取 {len(all_orders)} 条订单，开始写入数据库...")
    sync_amazon_orders(all_orders)
    print("完成同步订单")


if __name__ == "__main__":
    args = parse_args()
    
    t = Timer()
    t.start()
    lx_order_main(project_id=args.project_id, project_name=args.project_name)
    t.stop()
    print("运行时长：", t)
