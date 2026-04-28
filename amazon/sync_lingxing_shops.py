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
    for item in data_list or []:
        sid = item.get("sid")
        if not sid:
            print("跳过：没有 sid:", item)
            continue

        defaults = {
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
        }

        obj, created = LingXingAmazonShop.objects.update_or_create(
            sid=sid,
            defaults=defaults
        )

        print(f"{'新增' if created else '更新'}：LingXingAmazonShop: {obj}")

        account_name = item.get("account_name")
        amazon_shop = AmazonShop.objects.filter(shop_name=account_name).first()

        if not amazon_shop:
            print(f"  -> 未找到本地 AmazonShop.shop_name='{account_name}'，跳过绑定")
            continue

        if obj.amazon_shop_id != amazon_shop.id:
            obj.amazon_shop = amazon_shop
            obj.save(update_fields=["amazon_shop"])
            print(f"  -> 已绑定 AmazonShop(id={amazon_shop.id})")

        if amazon_shop.ling_xing_if != 1:
            amazon_shop.ling_xing_if = 1
            amazon_shop.save(update_fields=["ling_xing_if"])
            print(f"  -> AmazonShop(id={amazon_shop.id}) 标记已绑定 ling_xing_if=1")


def sync_lingxing_temu_shops(data_list):
    """把领星Temu数据写入并绑定 TemuShop"""
    for item in data_list or []:
        store_id = item.get("store_id")
        if not store_id:
            print("跳过：没有 store_id:", item)
            continue

        defaults = {
            "sid": item.get("sid"),
            "store_name": item.get("store_name"),
            "platform_code": item.get("platform_code"),
            "platform_name": item.get("platform_name"),
            "currency": item.get("currency"),
            "is_sync": item.get("is_sync"),
            "status": item.get("status"),
            "country_code": item.get("country_code"),
        }

        obj, created = LingXingTemuShop.objects.update_or_create(
            store_id=store_id,
            defaults=defaults
        )

        print(f"{'新增' if created else '更新'}：LingXingTemuShop: {obj}")

        # 提取店铺名称（格式：项目-店铺名-产品名），并去除前后空格
        store_name = item.get("store_name", "")
        shop_name_to_match = store_name.split('-')[
            1].strip() if store_name and '-' in store_name else store_name.strip()

        temu_shop = TemuShop.objects.filter(shop_name=shop_name_to_match).first()

        if not temu_shop:
            print(f"  -> 未找到本地 TemuShop.shop_name='{shop_name_to_match}'（原始：{store_name}），跳过绑定")
            continue

        if obj.temu_shop_id != temu_shop.id:
            obj.temu_shop = temu_shop
            obj.save(update_fields=["temu_shop"])
            print(f"  -> 已绑定 TemuShop(id={temu_shop.id})")


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
