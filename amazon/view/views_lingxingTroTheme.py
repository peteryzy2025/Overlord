import os
import sys
import django

# 1. 将项目根目录添加到系统路径（防止导入 App 时报错）
# 假设脚本在 theme/view/ 目录下，我们需要定位到 Overlord 根目录
project_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(project_path)

# 2. 设置环境变量，指向你的 settings.py 文件
# 这里的 'Overlord.settings' 需要根据你项目实际的 settings 路径修改
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Overlord.settings')

# 3. 启动 Django
django.setup()


from amazon.models import LingXingAmazonShop
from theme.view.views_trend import analyze_theme_trend
from api.lingxing.Y_OpenApi import get_api_resp
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.http import JsonResponse
import json
import asyncio

#======调用LingXing API===========================
async def lingxing_api_info_getter(sid):
    """
    获取领星店铺列表
    """
    resp = await get_api_resp(
        req_body={
            "sid": sid
        },
        api_path="/erp/sc/data/mws/listing",
        method="POST"
    )
    # print(resp.data)
    return resp.data



#======================构造表格所需数据======================
def get_lingxing_api_info(sid):
    """
    获取领星API数据，返回JSON字符串
    如果API返回空或出错，返回None
    """
    try:
        info = asyncio.run(lingxing_api_info_getter(sid))
        if not info:
            print(f"sid={sid}, API返回为空")
            return None
        json_data = json.dumps(info, ensure_ascii=False, indent=2)
        return json_data
    except Exception as e:
        print(f"sid={sid}, API调用异常: {e}")
        return None

def process_lingxing_api_info(json_data, shop_name, amazon_shop_name, shop_owner, limit=None):
    """
    处理领星店铺列表数据，返回listing列表

    Args:
        json_data: API 返回的 JSON 数据
        shop_name: 领星店铺名称
        amazon_shop_name: Amazon 店铺名称
        shop_owner: 店铺负责人
        limit: 最多返回的数据条数，None 表示不限制
    """
    # 1. 检查空值
    if not json_data:
        return []

    # 2. 解析 JSON 数据
    try:
        data = json.loads(json_data)
    except json.JSONDecodeError as e:
        print(f"JSON解析失败: {e}")
        return []

    # 3. 检查数据是否为列表
    if not isinstance(data, list):
        print(f"API返回数据格式错误，期望list，实际: {type(data)}")
        return []

    result = []
    # 4. 提取需要的字段
    for item in data:
        # 如果已达到限制条数，停止处理
        if limit is not None and len(result) >= limit:
            break

        item_name = item.get("item_name", "")

        # 过滤掉 title 为空的数据项
        if not item_name or not item_name.strip():
            continue

        tro_words_analyze = analyze_theme_trend(item_name)
        title_risk_level = tro_words_analyze.get("theme_risk_text", "")

        if title_risk_level == "low":
            continue

        tro_words_origin = []
        if len(tro_words_analyze.get('uspto_keywords')) != 0:
            tro_words_origin.append("美标网")
        if len(tro_words_analyze.get('tro_keywords')) != 0:
            tro_words_origin.append("数据库")

        asin = item.get("asin", "")
        high_risk_list = tro_words_analyze.get("high_risk_words", [])
        medium_risk_list = tro_words_analyze.get("medium_risk_words", [])

        item_result = {
            "amazon_shop_name": amazon_shop_name,
            "shop_name": shop_name,
            "shop_owner": shop_owner,
            "asin": asin,
            "title": item_name,
            "title_risk_level": title_risk_level,
            "high_risk_list": high_risk_list,
            "medium_risk_list": medium_risk_list,
            "tro_words_origin": tro_words_origin,
        }
        result.append(item_result)

    return result


def apply_filters(listings, shop_name_filter, shop_owner_filter, asin_filter, infringement_filter):
    """
    应用筛选条件到数据列表
    """
    filtered = listings

    if shop_name_filter:
        filtered = [item for item in filtered if shop_name_filter.lower() in item.get('shop_name', '').lower()]

    if shop_owner_filter:
        filtered = [item for item in filtered if shop_owner_filter.lower() in item.get('shop_owner', '').lower()]

    if asin_filter:
        filtered = [item for item in filtered if asin_filter.upper() in item.get('asin', '').upper()]

    if infringement_filter:
        filtered = [item for item in filtered if item.get('title_risk_level', '') == infringement_filter]

    return filtered


# 测试代码（手动运行时取消注释）
# if __name__ == "__main__":
#     json_data = get_lingxing_api_info("522144")
#     result = process_lingxing_api_info(json_data, "领星店铺", "美国店铺", "领星")
#     print(f"共获取 {len(result)} 条数据")




#筛选出所有美国店铺，拼装基本信息，获取Json数据


# process_lingxing_api_info(get_lingxing_api_info("522144"))

@csrf_exempt
@require_http_methods(["POST"])
def get_lingxing_tro_listing_api(request):
    """
    获取 TRO Listing 数据 API
    优化：限制获取的数据总量，避免加载过多数据
    """
    try:
        data = json.loads(request.body)

        # 获取筛选条件
        shop_name_filter = data.get('shop_name', '').strip()
        shop_owner_filter = data.get('shop_owner', '').strip()
        asin_filter = data.get('asin', '').strip()
        infringement_filter = data.get('infringement', '').strip()

        # 分页参数
        page = int(data.get('page', 1))
        page_size = int(data.get('page_size', 20))

        # 计算需要获取的数据量（当前页 + 缓冲）
        # 获取当前页的数据量，加一些缓冲用于筛选后仍有足够数据
        NEEDED_DATA_SIZE = page_size * 2  # 获取2倍页面的数据量

        # 查询 US 店铺
        all_shops = LingXingAmazonShop.objects.select_related('amazon_shop__ops').filter(
            name__contains='US'
        )

        all_listing = []
        for shop in all_shops:
            # 如果已获取足够数据，停止继续获取
            if len(all_listing) >= NEEDED_DATA_SIZE:
                break

            sid = shop.sid
            store_name = shop.name
            related_amazon_shop = shop.amazon_shop.shop_name if shop.amazon_shop else ''
            owner_name = (shop.amazon_shop.ops.first_name if shop.amazon_shop and shop.amazon_shop.ops else '')

            # 计算当前店铺还需要获取的数据量
            remaining_needed = NEEDED_DATA_SIZE - len(all_listing)

            # 获取 API 数据，限制每个店铺的返回条数
            json_data = get_lingxing_api_info(sid)
            item_result = process_lingxing_api_info(
                json_data,
                store_name,
                related_amazon_shop,
                owner_name,
                limit=remaining_needed  # 只获取需要的数据量
            )
            all_listing.extend(item_result)

        # 应用筛选条件
        filtered_listing = apply_filters(all_listing, shop_name_filter, shop_owner_filter, asin_filter, infringement_filter)

        # 分页
        paginator = Paginator(filtered_listing, page_size)

        try:
            page_obj = paginator.page(page)
        except EmptyPage:
            page_obj = paginator.page(paginator.num_pages)
        except PageNotAnInteger:
            page_obj = paginator.page(1)

        # 返回数据
        return JsonResponse({
            'success': True,
            'data': {
                'listings': list(page_obj),
                'total': paginator.count,
                'page': page,
                'page_size': page_size,
                'total_pages': paginator.num_pages,
            }
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({
            'success': False,
            'message': str(e)
        }, status=500)




#======================Amazon Listing 管理页面======================
def amazon_listing_management_page(request):
    """
    Amazon Listing 管理页面
    """
    return render(request, 'amazon_listing_management.html')




