#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import sys
import django
import asyncio
import argparse

from django.db import transaction
from django.utils import timezone

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
sys.path.insert(0, PROJECT_ROOT)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Overlord.settings")
django.setup()
from api.Y.y_tiem import Timer
from amazon.models import LingXingAmazonShop
from temu.models import LingXingTemuShop
from general.models import AmazonShop, Project, TemuShop
from api.lingxing_p.lingxing_jc1 import get_lingxing_shop
from api.lingxing_p.lingxing_temu import get_lx_temu_shops


def parse_args():
    parser = argparse.ArgumentParser(description="同步领星店铺数据")
    parser.add_argument("--project-id", type=int, help="指定项目 ID 同步")
    parser.add_argument("--project-name", type=str, help="指定项目名称同步（支持模糊匹配）")
    return parser.parse_args()


def mask_secret(value):
    if not value:
        return ""
    if len(value) <= 8:
        return "***"
    return f"{value[:4]}***{value[-4:]}"


def get_active_lingxing_credentials(project_id=None, project_name=None):
    """从启用项目中提取去重后的领星凭证。
    
    Args:
        project_id: 指定项目 ID
        project_name: 指定项目名称（模糊匹配）
    """
    credentials = []
    seen = set()
    
    qs = Project.objects.filter(is_active=True)
    
    # 如果指定了项目 ID
    if project_id:
        qs = qs.filter(id=project_id)
        print(f"按项目 ID 过滤：{project_id}")
    
    # 如果指定了项目名称（模糊匹配）
    elif project_name:
        qs = qs.filter(name__icontains=project_name)
        print(f"按项目名称过滤：'{project_name}'")
    
    projects = qs.values_list("id", "name", "lingxing_app_id", "lingxing_app_secret")

    for pid, pname, app_id, app_secret in projects:
        app_id = (app_id or "").strip()
        app_secret = (app_secret or "").strip()
        if not app_id or not app_secret:
            continue

        key = (app_id, app_secret)
        if key in seen:
            continue

        seen.add(key)
        credentials.append({
            "project_id": pid,
            "project_name": pname,
            "app_id": app_id,
            "app_secret": app_secret,
        })

    print(f"从启用项目中提取到 {len(credentials)} 套去重后的领星凭证")
    return credentials


def sync_with_lingxing_credentials(sync_name, fetch_func, sync_func, project_id=None, project_name=None):
    credentials = get_active_lingxing_credentials(project_id=project_id, project_name=project_name)
    if not credentials:
        print(f"未找到启用项目的领星 AppID/AppSecret，跳过{sync_name}店铺同步")
        return ""

    for index, credential in enumerate(credentials, start=1):
        app_id = credential["app_id"]
        print(
            f"[{sync_name}] 开始同步第 {index}/{len(credentials)} 套凭证："
            f"project={credential['project_name']}({credential['project_id']}), "
            f"app_id={app_id}, app_secret={mask_secret(credential['app_secret'])}"
        )
        try:
            resp_data = asyncio.run(fetch_func(
                app_id=app_id,
                app_secret=credential["app_secret"],
            ))
            sync_func(resp_data or [])
        except Exception as exc:
            print(f"[{sync_name}] 凭证 app_id={app_id} 同步失败，已跳过：{exc}")
            continue

    print(f"{sync_name}店铺同步完成")
    return ""


def sync_lingxing_shops(data_list):
    """把领星数据写入并绑定 AmazonShop"""
    rows = []
    skipped_no_sid = 0
    for item in data_list or []:
        sid = item.get("sid")
        if not sid:
            skipped_no_sid += 1
            continue
        try:
            sid = int(sid)
        except (TypeError, ValueError):
            skipped_no_sid += 1
            continue
        rows.append({
            "sid": sid,
            "mid": item.get("mid"),
            "name": item.get("name"),
            "seller_id": item.get("seller_id"),
            "account_name": item.get("account_name"),
            "seller_account_id": item.get("seller_account_id"),
            "region": item.get("region"),
            "country": item.get("country"),
            "marketplace_id": item.get("marketplace_id"),
            "status": item.get("status"),
            "has_ads_setting": item.get("has_ads_setting"),
        })

    if not rows:
        print(f"Amazon店铺无可同步数据，跳过无效记录 {skipped_no_sid} 条")
        return

    sid_set = {row["sid"] for row in rows}
    account_names = {row["account_name"] for row in rows if row.get("account_name")}
    # 收集 name 去掉尾缀后的备选匹配名
    fallback_names = set()
    for row in rows:
        name = row.get("name", "")
        if name and "-" in name:
            # 去掉最后一个 - 及之后的尾缀，如 "惠城项目-11李嘉华-US" -> "惠城项目-11李嘉华"
            fallback_name = name.rsplit("-", 1)[0]
            if fallback_name:
                fallback_names.add(fallback_name)

    existing_map = {
        shop.sid: shop
        for shop in LingXingAmazonShop.objects.filter(sid__in=sid_set)
    }
    amazon_shop_map = {
        shop.shop_name: shop
        for shop in AmazonShop.objects.filter(shop_name__in=account_names)
    }
    # 备选匹配：用 name 去掉尾缀后的名字
    amazon_shop_fallback_map = {
        shop.shop_name: shop
        for shop in AmazonShop.objects.filter(shop_name__in=fallback_names)
    }

    create_objs = []
    update_objs = []
    bind_count = 0
    missing_bind_count = 0
    amazon_shop_ids_to_mark = set()
    fields = [
        "mid",
        "name",
        "seller_id",
        "account_name",
        "seller_account_id",
        "region",
        "country",
        "marketplace_id",
        "status",
        "has_ads_setting",
        "amazon_shop",
    ]

    missing_bind_shops = []  # 记录未匹配的店铺
    for row in rows:
        amazon_shop = amazon_shop_map.get(row.get("account_name"))
        matched_by = "account_name"
        if not amazon_shop:
            # 备选匹配：用 name 去掉尾缀
            name = row.get("name", "")
            if name and "-" in name:
                fallback_name = name.rsplit("-", 1)[0]
                amazon_shop = amazon_shop_fallback_map.get(fallback_name)
                if amazon_shop:
                    matched_by = "name_fallback"
        if amazon_shop:
            amazon_shop_ids_to_mark.add(amazon_shop.id)
        else:
            missing_bind_count += 1
            missing_bind_shops.append({
                "sid": row["sid"],
                "account_name": row.get("account_name"),
                "name": row.get("name"),
            })

        obj = existing_map.get(row["sid"])
        if obj:
            changed = False
            previous_amazon_shop_id = obj.amazon_shop_id
            for field in fields:
                next_value = amazon_shop if field == "amazon_shop" else row.get(field)
                if getattr(obj, field) != next_value:
                    setattr(obj, field, next_value)
                    changed = True
            if changed:
                update_objs.append(obj)
                if amazon_shop and previous_amazon_shop_id != amazon_shop.id:
                    bind_count += 1
        else:
            create_objs.append(LingXingAmazonShop(
                sid=row["sid"],
                mid=row.get("mid"),
                name=row.get("name"),
                seller_id=row.get("seller_id"),
                account_name=row.get("account_name"),
                seller_account_id=row.get("seller_account_id"),
                region=row.get("region"),
                country=row.get("country"),
                marketplace_id=row.get("marketplace_id"),
                status=row.get("status"),
                has_ads_setting=row.get("has_ads_setting"),
                amazon_shop=amazon_shop,
            ))
            if amazon_shop:
                bind_count += 1

    with transaction.atomic():
        if create_objs:
            LingXingAmazonShop.objects.bulk_create(create_objs, batch_size=1000)
        if update_objs:
            LingXingAmazonShop.objects.bulk_update(update_objs, fields, batch_size=1000)
        marked_count = 0
        if amazon_shop_ids_to_mark:
            marked_count = AmazonShop.objects.filter(
                id__in=amazon_shop_ids_to_mark
            ).exclude(ling_xing_if=1).update(ling_xing_if=1)

    print(
        "Amazon店铺同步完成："
        f"新增 {len(create_objs)}，更新 {len(update_objs)}，"
        f"已绑定/保持绑定 {bind_count}，未匹配本地店铺 {missing_bind_count}，"
        f"标记 ling_xing_if {marked_count}，跳过无效记录 {skipped_no_sid}"
    )
    if missing_bind_shops:
        print("[!] 以下领星店铺未匹配到本地 AmazonShop：")
        for shop in missing_bind_shops:
            print(f"   - sid={shop['sid']}, account_name={shop['account_name']}, name={shop['name']}")


def sync_lingxing_temu_shops(data_list):
    """把领星Temu数据写入并绑定 TemuShop"""
    rows = []
    skipped_no_store_id = 0
    for item in data_list or []:
        store_id = item.get("store_id")
        if not store_id:
            skipped_no_store_id += 1
            continue
        store_name = item.get("store_name", "")
        shop_name_to_match = store_name.split('-')[1].strip() if store_name and '-' in store_name else store_name.strip()
        rows.append({
            "store_id": str(store_id),
            "sid": item.get("sid"),
            "store_name": store_name,
            "platform_code": item.get("platform_code"),
            "platform_name": item.get("platform_name"),
            "currency": item.get("currency"),
            "is_sync": item.get("is_sync"),
            "status": item.get("status"),
            "country_code": item.get("country_code"),
            "shop_name_to_match": shop_name_to_match,
        })

    if not rows:
        print(f"Temu店铺无可同步数据，跳过无效记录 {skipped_no_store_id} 条")
        return

    store_ids = {row["store_id"] for row in rows}
    shop_names = {row["shop_name_to_match"] for row in rows if row.get("shop_name_to_match")}
    existing_map = {
        shop.store_id: shop
        for shop in LingXingTemuShop.objects.filter(store_id__in=store_ids)
    }
    temu_shop_map = {
        shop.shop_name: shop
        for shop in TemuShop.objects.filter(shop_name__in=shop_names)
    }

    create_objs = []
    update_objs = []
    bind_count = 0
    missing_bind_count = 0
    fields = [
        "sid",
        "store_name",
        "platform_code",
        "platform_name",
        "currency",
        "is_sync",
        "status",
        "country_code",
        "temu_shop",
    ]

    missing_bind_shops_temu = []  # 记录未匹配的Temu店铺
    for row in rows:
        temu_shop = temu_shop_map.get(row.get("shop_name_to_match"))
        if not temu_shop:
            missing_bind_count += 1
            missing_bind_shops_temu.append({
                "store_id": row["store_id"],
                "store_name": row.get("store_name"),
                "shop_name_to_match": row.get("shop_name_to_match"),
            })

        obj = existing_map.get(row["store_id"])
        if obj:
            changed = False
            previous_temu_shop_id = obj.temu_shop_id
            for field in fields:
                next_value = temu_shop if field == "temu_shop" else row.get(field)
                if getattr(obj, field) != next_value:
                    setattr(obj, field, next_value)
                    changed = True
            if changed:
                update_objs.append(obj)
                if temu_shop and previous_temu_shop_id != temu_shop.id:
                    bind_count += 1
        else:
            create_objs.append(LingXingTemuShop(
                store_id=row["store_id"],
                sid=row.get("sid"),
                store_name=row.get("store_name"),
                platform_code=row.get("platform_code"),
                platform_name=row.get("platform_name"),
                currency=row.get("currency"),
                is_sync=row.get("is_sync"),
                status=row.get("status"),
                country_code=row.get("country_code"),
                temu_shop=temu_shop,
            ))
            if temu_shop:
                bind_count += 1

    with transaction.atomic():
        if create_objs:
            LingXingTemuShop.objects.bulk_create(create_objs, batch_size=1000)
        if update_objs:
            LingXingTemuShop.objects.bulk_update(update_objs, fields, batch_size=1000)

    print(
        "Temu店铺同步完成："
        f"新增 {len(create_objs)}，更新 {len(update_objs)}，"
        f"已绑定/保持绑定 {bind_count}，未匹配本地店铺 {missing_bind_count}，"
        f"跳过无效记录 {skipped_no_store_id}"
    )
    if missing_bind_shops_temu:
        print("[!] 以下领星Temu店铺未匹配到本地 TemuShop：")
        for shop in missing_bind_shops_temu:
            print(f"   - store_id={shop['store_id']}, store_name={shop['store_name']}, 匹配名={shop['shop_name_to_match']}")


def lx_shop_main(project_id=None, project_name=None):
    print("开始同步Amazon店铺数据…")
    return sync_with_lingxing_credentials(
        sync_name="Amazon",
        fetch_func=get_lingxing_shop,
        sync_func=sync_lingxing_shops,
        project_id=project_id,
        project_name=project_name,
    )


def lx_shop_main2(project_id=None, project_name=None):
    print("开始同步Temu店铺数据…")
    return sync_with_lingxing_credentials(
        sync_name="Temu",
        fetch_func=get_lx_temu_shops,
        sync_func=sync_lingxing_temu_shops,
        project_id=project_id,
        project_name=project_name,
    )


if __name__ == "__main__":
    args = parse_args()
    
    t = Timer()
    t.start()
    lx_shop_main(project_id=args.project_id, project_name=args.project_name)  # 同步Amazon店铺
    print("\n" + "=" * 50 + "\n")
    lx_shop_main2(project_id=args.project_id, project_name=args.project_name)  # 同步Temu店铺
    t.stop()
    print("总运行时长：", t)
