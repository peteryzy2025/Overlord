# debug_shop_coverage.py
"""
快速验证脚本：检查LingXing映射表是否完整
"""

import os
import sys
import django
from datetime import date

# ===== Django环境设置 =====
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
sys.path.append(PROJECT_ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Overlord.settings")
django.setup()

from django.db.models import Sum
from general.models import User, AmazonShop
from amazon.models import LingXingAmazonShop, AmazonOrders, AmazonOrderItem

# ===== 配置 =====
TEST_USER_ID = 23
TARGET_DATE_STR = "2025-12-31"

target_date = date.fromisoformat(TARGET_DATE_STR)
month_start = target_date.replace(day=1)


def main():
    print(f"\n{'=' * 80}")
    print(f"检查用户 {TEST_USER_ID} 的店铺覆盖完整性")
    print(f"统计月份: {month_start.year}-{month_start.month:02d}")
    print(f"{'=' * 80}\n")

    # ========== 1. 获取所有AmazonShop（包括停用）==========
    all_shops = AmazonShop.objects.filter(ops=TEST_USER_ID)
    all_shop_ids = list(all_shops.values_list('id', flat=True))

    print(f"AmazonShop总数: {len(all_shop_ids)}")
    print("\n所有店铺详情:")
    for shop in all_shops.order_by('id'):
        print(f"  - ID: {shop.id:>3} | 状态: {shop.shop_status:<4} | 名称: {shop.shop_name}")

    # ========== 2. 检查LingXing映射==========
    print(f"\n{'=' * 80}")
    print("LingXingAmazonShop映射情况:")
    print(f"{'=' * 80}")

    missing_shops = []  # 缺失映射的店铺
    multi_mapped_shops = []  # 重复映射的店铺

    for shop in all_shops:
        mappings = LingXingAmazonShop.objects.filter(
            amazon_shop_id=shop.id,
            sid__isnull=False
        ).exclude(sid=0)

        count = mappings.count()

        if count == 0:
            missing_shops.append(shop)
            print(f"❌ 缺失: ID {shop.id} '{shop.shop_name}' (状态: {shop.shop_status})")
        elif count > 1:
            multi_mapped_shops.append((shop, count))
            sids = list(mappings.values_list('sid', flat=True))
            print(f"⚠️ 重复: ID {shop.id} '{shop.shop_name}' (状态: {shop.shop_status}) 有 {count} 个SID: {sids}")
        else:
            sid = mappings.first().sid
            print(f"✅ 正常: ID {shop.id} '{shop.shop_name}' → SID: {sid}")

    # ========== 3. 统计缺失店铺的订单量==========
    print(f"\n{'=' * 80}")
    print("缺失映射店铺的订单统计:")
    print(f"{'=' * 80}")

    if missing_shops:
        missing_shop_ids = [s.id for s in missing_shops]

        # 这些店铺的总订单数
        missing_orders = AmazonOrders.objects.filter(
            lingxing_shop__amazon_shop_id__in=missing_shop_ids,
            purchase_date_local__date__gte=month_start,
            purchase_date_local__date__lte=target_date
        )

        missing_order_count = missing_orders.count()

        # 这些店铺的退货订单数
        missing_cancelled_orders = missing_orders.filter(order_status='Canceled')
        missing_cancelled_count = missing_cancelled_orders.count()

        # 这些店铺的商品件数
        missing_items = AmazonOrderItem.objects.filter(
            order__lingxing_shop__amazon_shop_id__in=missing_shop_ids,
            order__purchase_date_local__date__gte=month_start,
            order__purchase_date_local__date__lte=target_date
        )
        missing_item_total = missing_items.aggregate(
            total=Sum('quantity_ordered')
        )['total'] or 0

        # 这些店铺的退货件数
        missing_return_items = missing_items.filter(order__order_status='Canceled')
        missing_return_total = missing_return_items.aggregate(
            total=Sum('quantity_ordered')
        )['total'] or 0

        print(f"缺失映射的店铺数: {len(missing_shops)}")
        print(f"这些店铺的总订单数: {missing_order_count}")
        print(f"这些店铺的退货订单数: {missing_cancelled_count}")
        print(f"这些店铺的有效订单数: {missing_order_count - missing_cancelled_count}")
        print(f"这些店铺的总商品件数: {missing_item_total}")
        print(f"这些店铺的退货件数: {missing_return_total}")
        print(f"这些店铺的有效商品件数: {missing_item_total - missing_return_total}")

        print("\n缺失映射店铺列表:")
        for shop in missing_shops:
            print(f"  - {shop.shop_name} (ID: {shop.id}, 状态: {shop.shop_status})")
    else:
        print("✅ 所有店铺都有LingXing映射")

    # ========== 4. 对比两个逻辑的统计结果==========
    print(f"\n{'=' * 80}")
    print("统计结果对比:")
    print(f"{'=' * 80}")

    # 视图逻辑的店铺范围（有映射的）
    valid_lingxing_ids = list(LingXingAmazonShop.objects.filter(
        amazon_shop_id__in=all_shop_ids,
        sid__isnull=False
    ).exclude(sid=0).values_list('sid', flat=True))

    views_orders = AmazonOrders.objects.filter(
        lingxing_shop_id__in=valid_lingxing_ids,
        purchase_date_local__date__gte=month_start,
        purchase_date_local__date__lte=target_date
    )
    views_order_count = views_orders.count()

    views_items = AmazonOrderItem.objects.filter(
        order__lingxing_shop_id__in=valid_lingxing_ids,
        order__purchase_date_local__date__gte=month_start,
        order__purchase_date_local__date__lte=target_date
    ).exclude(order__order_status='Canceled')
    views_item_count = views_items.aggregate(
        total=Sum('quantity_ordered')
    )['total'] or 0

    # 排名脚本的店铺范围（所有店铺）
    ranking_orders = AmazonOrders.objects.filter(
        lingxing_shop__amazon_shop_id__in=all_shop_ids,
        purchase_date_local__date__gte=month_start,
        purchase_date_local__date__lte=target_date
    )
    ranking_order_count = ranking_orders.count()

    ranking_items = AmazonOrderItem.objects.filter(
        order__lingxing_shop__amazon_shop_id__in=all_shop_ids,
        order__purchase_date_local__date__gte=month_start,
        order__purchase_date_local__date__lte=target_date
    ).exclude(order__order_status='Canceled')
    ranking_item_count = ranking_items.aggregate(
        total=Sum('quantity_ordered')
    )['total'] or 0

    print(f"视图逻辑统计:")
    print(f"  有效店铺数: {len(valid_lingxing_ids)}")
    print(f"  总订单数: {views_order_count}")
    print(f"  有效商品件数: {views_item_count}")

    print(f"\n排名脚本统计:")
    print(f"  总店铺数: {len(all_shop_ids)}")
    print(f"  总订单数: {ranking_order_count}")
    print(f"  有效商品件数: {ranking_item_count}")

    print(f"\n差异:")
    print(f"  店铺数差异: {len(all_shop_ids) - len(valid_lingxing_ids)}")
    print(f"  订单数差异: {ranking_order_count - views_order_count}")
    print(f"  商品件数差异: {ranking_item_count - views_item_count}")

    # ========== 5. 建议 ==========
    print(f"\n{'=' * 80}")
    print("🎯 结论与建议")
    print(f"{'=' * 80}")

    if missing_shops:
        print("问题根源: LingXingAmazonShop映射表不完整")
        print("解决方案:")
        print("  1. 执行SQL补全缺失的LingXing映射:")
        print("     INSERT INTO amazon_lingxingamazonshop (amazon_shop_id, sid, name)")
        print("     VALUES (...), (...), ...")
        print("\n  2. 或者修改视图逻辑，使用反向关联查询（不依赖LingXing表）:")
        print("     # 改为使用 amazon_shop_id 反向关联")
        print("     AmazonOrderItem.objects.filter(")
        print("         order__lingxing_shop__amazon_shop_id__in=amazon_shop_ids,")
        print("         ...")
        print("     )")
    else:
        print("✅ 映射表完整，无需处理")

    print("\n业务确认:")
    print("  - 停用店铺当月订单应计入统计 ✅")
    print("  - 注销店铺当月订单应计入统计 ✅")
    print("  - 视图逻辑因映射缺失导致漏统计 ❌")
    print(f"{'=' * 80}")


if __name__ == "__main__":
    main()