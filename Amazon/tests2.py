# verify_fix.py
"""
验证修改后的视图逻辑是否与排名脚本一致
"""

import os
import sys
import django
from datetime import date

# Django环境设置
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
sys.path.append(PROJECT_ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Overlord.settings")
django.setup()

from django.db.models import Sum, Q
from general.models import User, AmazonShop
from amazon.models import AmazonOrders, AmazonOrderItem

TEST_USER_ID = 23
TARGET_DATE = date(2025, 12, 31)
MONTH_START = date(2025, 12, 1)


def calculate_with_old_logic(user_id, start_date, end_date):
    """旧逻辑：通过LingXing映射查询"""
    from amazon.models import LingXingAmazonShop

    # 获取映射
    amazon_shops = AmazonShop.objects.filter(ops_id=user_id)
    amazon_shop_ids = list(amazon_shops.values_list('id', flat=True))

    lingxing_shops = LingXingAmazonShop.objects.filter(
        amazon_shop_id__in=amazon_shop_ids,
        sid__isnull=False
    ).exclude(sid=0)
    lingxing_shop_ids = list(lingxing_shops.values_list('sid', flat=True))

    # 统计
    items = AmazonOrderItem.objects.filter(
        order__lingxing_shop_id__in=lingxing_shop_ids,
        order__purchase_date_local__date__gte=start_date,
        order__purchase_date_local__date__lte=end_date
    ).exclude(order__order_status='Canceled')

    return items.aggregate(total=Sum('quantity_ordered'))['total'] or 0


def calculate_with_new_logic(user_id, start_date, end_date):
    """新逻辑：通过反向关联查询"""
    # 获取所有店铺ID（包括停用）
    amazon_shop_ids = list(AmazonShop.objects.filter(
        ops_id=user_id
    ).values_list('id', flat=True))

    # 统计
    items = AmazonOrderItem.objects.filter(
        order__lingxing_shop__amazon_shop_id__in=amazon_shop_ids,
        order__purchase_date_local__date__gte=start_date,
        order__purchase_date_local__date__lte=end_date
    ).exclude(order__order_status='Canceled')

    return items.aggregate(total=Sum('quantity_ordered'))['total'] or 0


def main():
    print("\n" + "🔍" * 30)
    print("验证修复效果")
    print("🔍" * 30)

    old_result = calculate_with_old_logic(TEST_USER_ID, MONTH_START, TARGET_DATE)
    new_result = calculate_with_new_logic(TEST_USER_ID, MONTH_START, TARGET_DATE)

    print(f"\n旧逻辑结果（通过LingXing映射）: {old_result}")
    print(f"新逻辑结果（通过反向关联）: {new_result}")

    if old_result == new_result:
        print("\n✅ 结果一致！修复成功")
    else:
        print(f"\n❌ 差异: {abs(new_result - old_result)}")
        print("需要进一步检查映射表是否还有未发现问题")

    # 显示缺失映射的店铺
    from amazon.models import LingXingAmazonShop
    all_shops = AmazonShop.objects.filter(ops_id=TEST_USER_ID)
    missing = []
    for shop in all_shops:
        exists = LingXingAmazonShop.objects.filter(
            amazon_shop_id=shop.id,
            sid__isnull=False
        ).exclude(sid=0).exists()
        if not exists:
            missing.append(f"{shop.shop_name} (ID: {shop.id}, 状态: {shop.shop_status})")

    if missing:
        print(f"\n⚠️ 仍有 {len(missing)} 个店铺缺失LingXing映射:")
        for m in missing:
            print(f"  - {m}")
    else:
        print("\n✅ 所有店铺都有LingXing映射")


if __name__ == "__main__":
    main()