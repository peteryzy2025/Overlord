import os
import sys
import django
import asyncio
from decimal import Decimal, ROUND_HALF_UP
from asgiref.sync import sync_to_async

# ========== Django环境初始化 ==========
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(CURRENT_DIR))
sys.path.append(PROJECT_ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Overlord.settings")
django.setup()

from temu.models import TemuOrder, TemuOrderItem
from general.models import Project
from api.lingxing.Y_OpenApi import get_api_resp

from typing import Optional
from asgiref.sync import async_to_sync


# ==================== 获取领星API凭证 ====================
async def _get_lingxing_credentials(order: TemuOrder) -> tuple[str, str]:
    """
    根据 Temu 订单获取对应项目的领星API凭证
    
    Returns:
        (app_id, app_secret) 元组
    """
    project = None

    # 异步获取 temu_shop 和 project
    get_temu_shop = sync_to_async(lambda: order.temu_shop, thread_sensitive=True)
    temu_shop = await get_temu_shop()

    if temu_shop:
        get_project = sync_to_async(lambda: temu_shop.project, thread_sensitive=True)
        project = await get_project()
    else:
        # 尝试从 lingxing_shop 获取
        get_lingxing_shop = sync_to_async(lambda: order.lingxing_shop, thread_sensitive=True)
        lingxing_shop = await get_lingxing_shop()
        if lingxing_shop:
            get_temu_shop_from_lx = sync_to_async(lambda: lingxing_shop.temu_shop, thread_sensitive=True)
            lx_temu_shop = await get_temu_shop_from_lx()
            if lx_temu_shop:
                get_project = sync_to_async(lambda: lx_temu_shop.project, thread_sensitive=True)
                project = await get_project()

    if project:
        if project.lingxing_app_id and project.lingxing_app_secret:
            return project.lingxing_app_id, project.lingxing_app_secret
        else:
            raise ValueError(
                f"项目 '{project.name}' (ID: {project.id}) 未配置领星API凭证"
            )
    else:
        raise ValueError("订单未关联项目，无法获取领星API凭证")


# ==================== 查询订单 ====================
@sync_to_async
def get_temu_order(global_order_no: str) -> TemuOrder:
    """获取 Temu 订单（包含商品明细）"""
    return TemuOrder.objects.select_related('lingxing_shop', 'temu_shop').prefetch_related('items').get(
        global_order_no=global_order_no
    )


# ==================== Step1: 新建/编辑产品 ====================
async def step1_set_sku(
        sku: str,
        cg_price: str,
        app_id: str = None,
        app_secret: str = None,
        length_cm: float = None,
        width_cm: float = None,
        height_cm: float = None,
        weight_kg: float = None
):
    """
    新建/编辑产品到领星仓库
    尺寸重量传公制，内部自动转英制
    """
    # 公制转英制
    # 1 inch = 2.54 cm
    # 1 lb = 0.453592 kg
    length_inch = round(length_cm / 2.54, 2) if length_cm else ""
    width_inch = round(width_cm / 2.54, 2) if width_cm else ""
    height_inch = round(height_cm / 2.54, 2) if height_cm else ""
    weight_lb = round(weight_kg / 0.453592, 2) if weight_kg else ""

    req_body = {
        "sku": sku,
        "product_name": sku,
        "sku_identifier": sku,
        "cg_price": cg_price,
        'cg_package_length': str(length_inch) if length_inch != "" else "",
        'cg_package_width': str(width_inch) if width_inch != "" else "",
        'cg_package_height': str(height_inch) if height_inch != "" else "",
        'cg_product_gross_weight': str(weight_lb) if weight_lb != "" else "",
        'description': "temu订单同步，自动创建/更新产品",
    }

    print(f"\n【步骤1】set_sku 请求参数：")
    print(f"   → sku        = {sku}")
    print(f"   → cg_price   = {cg_price}")
    if length_cm or width_cm or height_cm:
        print(f"   → 尺寸(公制)  = {length_cm}×{width_cm}×{height_cm} cm")
        print(f"   → 尺寸(英制)  = {length_inch}×{width_inch}×{height_inch} inch")
    if weight_kg:
        print(f"   → 重量(公制)  = {weight_kg} kg")
        print(f"   → 重量(英制)  = {weight_lb} lb")

    resp = await get_api_resp(
        req_body=req_body,
        api_path="/erp/sc/routing/storage/product/set",
        app_id=app_id,
        app_secret=app_secret
    )
    print(f"   → 返回结果   = {resp}")
    return resp


async def step2_update_order_binding(global_order_no: str, list_mskus: list, app_id: str = None, app_secret: str = None):
    print(f"\n【步骤2】批量绑定商品 updateOrder 传参：")
    order_item_list = []
    for msku in list_mskus:
        order_item_list.append({"sku": msku, "msku": msku, "type": 3})
    req_body = {"order_list": [{"global_order_no": global_order_no, "order_item_list": order_item_list}]}
    resp = await get_api_resp(req_body=req_body, api_path="/pb/mp/order/v2/updateOrder", app_id=app_id,
                              app_secret=app_secret)
    print(f"   → 绑定结果 = {resp}")


async def step2_update_order_binding_v2(store_id: str, items: list, app_id: str = None, app_secret: str = None):
    """
    多平台Listing配对（支持Temu半托管）
    API: /pb/mp/listing/v2/pairMultiPlatform
    """
    print(f"\n【步骤2】多平台Listing配对 pairMultiPlatform 传参：")
    print(f"   → store_id = {store_id}")
    print(f"   → pair_multi_platform_list = [")
    print(f"   ]")

    pair_list = []
    for it in items:
        sku_id = await get_msku_id(it['msku'])
        pair_list.append({"msku": sku_id, "store_id": f"{store_id}", "sku": it['sku']})
    req_body = {"pair_multi_platform_list": pair_list}
    print(req_body)
    resp = await get_api_resp(
        req_body=req_body,
        api_path="/pb/mp/listing/v2/pairMultiPlatform",
        app_id=app_id,
        app_secret=app_secret
    )
    print(f"   → 配对结果 = {resp}")
    return resp

async def get_msku_id(msku):
    req_body ={
        "searchField":9,
        "searchValues":[msku]
    }
    resp = await get_api_resp(req_body=req_body, api_path="/basicOpen/multiplatform/temu/list")
    print(resp)
    print(resp.data[0].get("mskuId"))
    return resp.data[0].get("mskuId")

# ==================== 测试入口 ====================
async def test_step1():
    """测试 step1 - 使用真实订单数据"""
    global_order_no = '103679933161035413'  # 替换为你的测试订单号

    print(f"\n{'=' * 60}")
    print(f"测试 Step1: 新建/编辑产品")
    print(f"订单号: {global_order_no}")
    # 获取API凭证

    print(f"{'=' * 60}")
    order = await get_temu_order(global_order_no)
    print(f"订单: {order}")
    app_id, app_secret = await _get_lingxing_credentials(order)
    print(f"\nAPI凭证获取成功: {app_id[:10]}...")

    # 获取商品列表（需要await因为prefetch_related在async中）
    items = await sync_to_async(list)(order.items.all())
    print(f"\n商品数量: {len(items)}")
    list_sku = []
    for idx, item in enumerate(items, 1):
        print(f"\n【商品{idx}】")
        print(f"  msku: {item.msku}")
        list_sku.append(item.msku)
        print(f"  local_sku: {item.local_sku}")
        print(f"  product_no: {item.product_no}")
        print(f"  quantity: {item.quantity}")
        print(f"  title: {item.title[:50]}..." if item.title and len(item.title) > 50 else f"  title: {item.title}")
        print(f"  unit_price: {item.unit_price_amount}")
        await step1_set_sku(
            sku=item.msku,
            cg_price=str(item.unit_price_amount),
            app_id=app_id,
            app_secret=app_secret,
            length_cm=0.13,
            width_cm=11.81,
            height_cm=11.02,
            weight_kg=1.57
        )# 创建产品

    # 获取store_id（从lingxing_shop）
    lingxing_shop = await sync_to_async(lambda: order.lingxing_shop, thread_sensitive=True)()
    store_id = lingxing_shop.store_id if lingxing_shop else None
    if not store_id:
        raise ValueError("订单未关联领星店铺，无法获取store_id")
    resp = await step2_update_order_binding(global_order_no, list_sku)
    print(resp)




    # 构建配对列表：sku和msku都用msku
    # binding_items = [{"sku": item.msku, "msku": item.msku} for item in items]
    # print(f"\n绑定商品列表: {binding_items}")


    # 再调用新接口（v2多平台配对）
    # print("\n>>> 调用新接口...")
    # await step2_update_order_binding_v2(
    #     store_id=store_id,
    #     items=binding_items,
    #     app_id=app_id,
    #     app_secret=app_secret
    # )


async def demo():
    req_body = {
        "platform_code":[10024]
    }
    resp = await get_api_resp(req_body=req_body,api_path="/pb/mp/shop/v2/getSellerList",)
    print(resp)


if __name__ == '__main__':
    asyncio.run(test_step1())
    # asyncio.run(get_msku_id("#XIYHCjbCPALWMXRB-260210"))