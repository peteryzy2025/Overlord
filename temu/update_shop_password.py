#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Temu 店铺账号密码批量更新脚本
运行一次即可更新所有店铺信息
"""

import os
import sys

# 设置 Django 环境
DJANGO_PROJECT_PATH = r"D:\Y-Project\Overlord"
os.chdir(DJANGO_PROJECT_PATH)
sys.path.insert(0, DJANGO_PROJECT_PATH)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Overlord.settings')

import django

django.setup()

from general.models import TemuShop

# 店铺数据（shop_name: {shop_account, shop_password}）
SHOP_DATA = {
    "Mingxiaooo": {"u": "19007520364", "p": "lsm123321..."},
    "Never Stop dfj": {"u": "13413101881", "p": "Aa113322."},
    "FeatherFinesse": {"u": "19022407815", "p": "Aa147258.."},
    "CrimsonCouture": {"u": "19022407815", "p": "Aa147258.."},
    "SableSilks": {"u": "19022407815", "p": "Aa147258.."},
    "NimbusNest": {"u": "19022407757", "p": "Aa159951.."},
    "EtherealEdge": {"u": "19022407757", "p": "Aa159951.."},
    "PolarisApparel": {"u": "19022407757", "p": "Aa159951.."},
    "Jinboxin Electronics": {"u": "19007524937", "p": "hh123456.."},
    "DIVVV Trendy": {"u": "19007524561", "p": "Aa123456"},
    "PURSEEK Trendy": {"u": "19007524561", "p": "Aa123456"},
    "DZiTuuv": {"u": "19007524561", "p": "Aa123456"},
    "VerveVesture": {"u": "19022407379", "p": "Aa159789.."},
    "ChicStitchCo": {"u": "19022407379", "p": "Aa159789.."},
    "Xinghuo Ecommerce": {"u": "19022407379", "p": "Aa159789.."},
    "lixiangjie": {"u": "19007524561", "p": "Aa123456"},
    "HuZhaoYuuuu": {"u": "19007524937", "p": "hh123456.."},
    "Promise dian zi": {"u": "13652778273", "p": "Aa159753"},
    "Xihangcommerce": {"u": "13652778273", "p": "Aa159753"},
    "cheng nuo xi hang local": {"u": "13652778273", "p": "Aa159753"},
    "DENSUN TECHNOLOGY INTERNATIONAL": {"u": "19007524561", "p": "Aa123456"},
    "wxjzhangyi": {"u": "19022502091", "p": "Aa369963.."},
    "Yijie Impression": {"u": "19022502091", "p": "Aa369963.."},
    "EmberEssentials": {"u": "19022502091", "p": "Aa369963.."},
    "wuxiaoyun": {"u": "13725082513", "p": "Aa123456"},
    "Wu Xiaoyun": {"u": "13725082513", "p": "Aa123456"},
    "guanzhijuan": {"u": "15875297933", "p": "Aa123456"},
    "Hdkdda": {"u": "15089231500", "p": "Aa123456"},
    "patch king": {"u": "13725082513", "p": "Aa123456"},
    "Jinboxin Ecommerce": {"u": "19007524937", "p": "hh123456.."},
    "Loushiliang": {"u": "15816312270", "p": "Aa123123"},
    "Shi Luo Xin Huan Yu": {"u": "15816312270", "p": "Aa123123"},
    "liuyuting": {"u": "19879873627", "p": "Aa123123"},
    "Xinuoshang": {"u": "13669591113", "p": "Aa123123"},
    "purseek badges": {"u": "13669591113", "p": "Aa123123"},
    "wuxiaojun": {"u": "13433443738", "p": "Aa123123"},
    "CosmoCloset": {"u": "19022407203", "p": "Aa135531.."},
    "TerraTextiles": {"u": "19022407203", "p": "Aa135531.."},
    "BloomBoutique": {"u": "19022407203", "p": "Aa135531.."},
    "yejinfa": {"u": "13433408444", "p": "Aa123456"},
    "zhangyiiiii": {"u": "13421637662", "p": "Aa123456"},
    "zhangyieeeeee": {"u": "13421637662", "p": "Aa123456"},
    "Tianyao Decoration": {"u": "13421637662", "p": "Aa123456"},
    "Good Nice Hats": {"u": "19022407745", "p": "QWE159jjq."},
    "DENSUN TECHNOLOGY": {"u": "19022407745", "p": "QWE159jjq."},
    "DENSUN BAG": {"u": "17852405897", "p": "Gzz123456"},
    "divi good hat": {"u": "17852405897", "p": "Gzz123456"},
    "shunzhii": {"u": "13798520112", "p": "Aa123456"},
    "meng mo mao yi": {"u": "13798520112", "p": "Aa123456"},
    "sunqiiiii": {"u": "13798520112", "p": "Aa123456"},
    "Fumicang Ecommerce": {"u": "19022407850", "p": "Aa789654.."},
    "GlamThreads": {"u": "19022407850", "p": "Aa789654.."},
    "UrbanVibeWear": {"u": "19022407850", "p": "Aa789654.."},
}


def update_shop_credentials():
    """批量更新店铺账号密码"""
    updated = 0
    not_found = []

    print(f"开始更新，共 {len(SHOP_DATA)} 个店铺...\n")

    for shop_name, creds in SHOP_DATA.items():
        account = creds["u"]
        password = creds["p"]

        # 尝试查找并更新
        shops = TemuShop.objects.filter(shop_name=shop_name)
        count = shops.count()

        if count > 0:
            shops.update(shop_account=account, shop_password=password)
            updated += count
            print(f"✅ [{shop_name}] 更新成功 (账号: {account})")
        else:
            not_found.append(shop_name)
            print(f"❌ [{shop_name}] 店铺不存在")

    print(f"\n{'=' * 50}")
    print(f"更新完成：成功 {updated} 个，未找到 {len(not_found)} 个")

    if not_found:
        print(f"\n以下店铺未找到：")
        for name in not_found:
            print(f"  - {name}")


if __name__ == "__main__":
    update_shop_credentials()