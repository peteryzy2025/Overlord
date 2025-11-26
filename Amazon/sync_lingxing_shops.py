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
from General.models import AmazonShop
from Api.lingxing_p.lingxing_jc1 import get_lingxing_shop


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


def lx_shop_main():
    print("开始同步店铺数据…")
    # 这里只是为了拿异步结果，用 asyncio.run 包一下就行
    resp_data = asyncio.run(get_lingxing_shop())
    sync_lingxing_shops(resp_data)
    print("完成")


if __name__ == "__main__":
    t = Timer()
    t.start()
    lx_shop_main()
    t.stop()
    print("运行时长：",t)

