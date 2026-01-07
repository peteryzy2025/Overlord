#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import sys
import django
import asyncio

from django.db import transaction
from django.utils import timezone

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
sys.path.append(PROJECT_ROOT)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Overlord.settings")
django.setup()
from Api.Y.y_tiem import Timer
from Amazon.models import LingXingAmazonShop
from Temu.models import LingXingTemuShop
from General.models import AmazonShop, TemuShop
from Api.lingxing_p.lingxing_jc1 import get_lingxing_shop
from Api.lingxing_p.lingxing_temu import get_lx_temu_shops


def sync_lingxing_shops(data_list):
    """把领星数据写入并绑定 AmazonShop"""
    for item in data_list:
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
    for item in data_list:
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


def lx_shop_main():
    print("开始同步Amazon店铺数据…")
    resp_data = asyncio.run(get_lingxing_shop())
    sync_lingxing_shops(resp_data)
    print("Amazon店铺同步完成")
    return ""


def lx_shop_main2():
    print("开始同步Temu店铺数据…")
    resp_data = asyncio.run(get_lx_temu_shops())
    sync_lingxing_temu_shops(resp_data)
    print("Temu店铺同步完成")
    return ""


if __name__ == "__main__":
    t = Timer()
    t.start()
    lx_shop_main()  # 同步Amazon店铺
    print("\n" + "=" * 50 + "\n")
    lx_shop_main2()  # 同步Temu店铺
    t.stop()
    print("总运行时长：", t)