import os
import sys
import django

# ===== Django环境设置 =====
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
sys.path.append(PROJECT_ROOT)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Overlord.settings")
django.setup()

# ===== 查询代码 =====
from amazon.models import AmazonListing

print("=" * 60)
print("Listing 详情查询（含侵权词）")
print("=" * 60)

try:
    # 预加载领星店铺->本地店铺，同时预加载多对多的侵权词
    listing = AmazonListing.objects.select_related(
        'lingxing_shop__amazon_shop'
    ).prefetch_related(
        'tro_words',  # 预加载侵权词
        'tro_words__creator'  # 预加载侵权词的创建人（可选）
    ).get(id=1)

    print(f"📦 Listing 基础信息:")
    print(f"   ID: {listing.id}")
    print(f"   ASIN: {listing.asin}")
    print(f"   标题: {listing.title[:50]}..." if listing.title and len(
        listing.title) > 50 else f"   标题: {listing.title}")
    print(f"   在售状态: {'✅ 在售' if listing.is_active else '❌ 停售'}")

    # 店铺信息链
    if listing.lingxing_shop:
        lx_shop = listing.lingxing_shop
        print(f"\n🏪 领星店铺信息:")
        print(f"   sid: {lx_shop.sid}")
        print(f"   店铺名: {lx_shop.name}")
        print(f"   账号: {lx_shop.account_name}")

        if lx_shop.amazon_shop:
            amazon_shop = lx_shop.amazon_shop
            print(f"\n🎯 本地 AmazonShop:")
            print(f"   店铺ID: {amazon_shop.id}")
            print(f"   ⭐ 店铺名称: {amazon_shop.shop_name}")
            print(f"   卖家记号: {amazon_shop.seller_mark or '无'}")
        else:
            print("\n⚠️  该领星店铺未绑定本地 AmazonShop")
    else:
        print("\n⚠️  该 Listing 未关联领星店铺")

    # 侵权词信息（多对多）
    print(f"\n🚨 侵权词检查 ({listing.tro_words.count()}个):")
    print("-" * 60)

    if listing.tro_words.exists():
        for idx, tro in enumerate(listing.tro_words.all(), 1):
            # 获取分类显示名称
            category_display = tro.get_category_display() if tro.category else "未分类"

            print(f"   {idx}. 侵权词: {tro.theme_name}")
            print(f"      类型码: {tro.name_type or '无'}")
            print(f"      分类: {category_display}")
            if tro.replacement_word:
                print(f"      建议替换为: {tro.replacement_word}")
            if tro.shop:
                print(f"      所属店铺: {tro.shop.shop_name}")
            print(f"      创建时间: {tro.create_time.strftime('%Y-%m-%d %H:%M') if tro.create_time else '未知'}")
            print()
    else:
        print("   ✅ 未命中任何侵权词")

except AmazonListing.DoesNotExist:
    print("❌ ID=1 的 Listing 不存在")
except Exception as e:
    print(f"❌ 查询出错: {str(e)}")
    import traceback

    traceback.print_exc()