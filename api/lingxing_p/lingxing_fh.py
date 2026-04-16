import os
import sys
import django
import asyncio
from decimal import Decimal, ROUND_HALF_UP
from asgiref.sync import sync_to_async
from datetime import datetime, timedelta  # 新增导入

# ========== Django环境初始化 ==========
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
sys.path.append(PROJECT_ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Overlord.settings")
django.setup()

from amazon.models import AmazonOrders
from general.models import Project
from api.lingxing.Y_OpenApi import get_api_resp
from api.lingxing_p.lingxing_jc1 import get_lingxing_zifa_order  # 新增导入

# ==================== 物流匹配 ====================
from typing import Optional
from asgiref.sync import async_to_sync

# ==================== 异常定义 ====================
class LingxingAPIException(Exception):
    """领星API调用异常"""
    pass


async def _get_lingxing_credentials(order) -> tuple[str, str]:
    """
    根据订单获取对应项目的领星API凭证
    
    Args:
        order: AmazonOrders 订单对象
        
    Returns:
        (app_id, app_secret) 元组
        
    Raises:
        ValueError: 如果项目未配置领星凭证
    """
    # 获取订单对应的项目（使用 sync_to_async 包装同步数据库操作）
    project = None
    
    # 异步获取 amazon_shop 和 project
    get_amazon_shop = sync_to_async(lambda: order.amazon_shop, thread_sensitive=True)
    amazon_shop = await get_amazon_shop()
    
    if amazon_shop:
        get_project = sync_to_async(lambda: amazon_shop.project, thread_sensitive=True)
        project = await get_project()
    
    # 检查项目是否配置了领星凭证
    if project:
        if project.lingxing_app_id and project.lingxing_app_secret:
            return project.lingxing_app_id, project.lingxing_app_secret
        else:
            raise ValueError(
                f"项目 '{project.name}' (ID: {project.id}) 未配置领星API凭证，"
                f"请先填写 lingxing_app_id 和 lingxing_app_secret"
            )
    else:
        raise ValueError("订单未关联项目，无法获取领星API凭证")


def get_divi_logistics_code(divi_logistics_method: str,
                            tracking_no: Optional[str] = None) -> str:
    """
    根据物流方式 + （可选）单号，返回对应的分销物流编码。
    """
    if not divi_logistics_method:
        return ""

    method = divi_logistics_method.strip().upper()
    tracking = (tracking_no or "").strip().upper()

    # 1. F-USPS 特殊处理（放在最前面）
    if method == "F-USPS":
        if not tracking:
            print("F-USPS 未提供单号，无法识别承运商")
            return ""
        if tracking.startswith("SF"):
            # UniUni
            return "500518-21734"
        # 单号前缀判断：UniUni
        if tracking.startswith("UU"):
            # UniUni
            return "500518-21736"

        # 单号前缀判断：GOFO
        if tracking.startswith("YT") :
            # GOFO
            return "500518-21672"
        if tracking.startswith("GFU"):
            return "500518-22837"

        # 按长度区分不同承运商（根据你举的几个例子来写）：
        length = len(tracking)
        if length == 22:
            # 例：9214490374017154170799
            # USPS
            return "500518-21735"

        if length == 12:
            # 例：395511858923
            # FEDEX
            return "500518-22808"

        if length == 30:
            # 例：420383059261290304442265416750
            # DHL
            return "500518-22809"
        if "LS" in tracking:
            return "500518-21735"

        print(f"F-USPS 单号未能识别承运商: {tracking_no}")
        return ""

    # 2. 完全匹配的渠道名 新增记得改大写！！！
    exact_map = {
        "威速易美国小货专线": "500518-22812",
        "云途全球专线挂号（标快普货）": "500518-22810",
        "京东普货标准专线-IE-01": "500518-22811",
        "GOFO PARCEL PICKUP": "500518-21672",
        "美西GOFO EXPRESS SERVICE": "500518-22837",
        "ES-FEDEX GROUND（美西）": "500518-23409",
        "ES-FEDEX HD（美西）": "500518-23410",
        "ES-USPS GA（美西）": "500518-23411",
        "ES-USPS PM（美西）": "500518-23412",
        "SWIFTX EXPRESS(美西)": "500518-23413",
        "顺丰国际电商专递-CD": "500518-21734",
        "顺丰国际电商专递-标准": "500518-30771",
        #新增记得改大写！！！
    }
    if method in exact_map:
        return exact_map[method]

    contain_map = {
        "USPS": "500518-21735",
        "FEDEX": "500518-22808",
        # "GOFO": "500518-21672",
        "DHL": "500518-22809",
        "UNIUNI": "500518-21736",
    }
    for key, code in contain_map.items():
        if key in method:
            return code

    print(f"未匹配到物流方式: 【{divi_logistics_method}】")
    return ""

# ==================== 新增：订单号同步函数 ====================
async def sync_order_no_if_empty(order, sid: int, amazon_order_id: str, app_id: str = None, app_secret: str = None) -> tuple[bool, str]:
    """
    如果订单 order_no 为空，则从领星API同步并更新数据库
    返回: (是否成功, 订单号或错误信息)
    """
    if order.order_no:
        return True, order.order_no

    print(f"⚠️  【警告】订单 {amazon_order_id} 的 order_no 为空，尝试从领星API同步...")

    try:
        # 调用API获取最近10天的自发货订单
        zifa_data = await get_lingxing_zifa_order(sid=str(sid), days=10, app_id=app_id, app_secret=app_secret)

        if not zifa_data:
            return False, "领星API返回空数据"

        # 建立 platform_order_id -> order_number 映射
        order_map = {}
        for item in zifa_data:
            order_number = item.get('order_number')
            platform_list = item.get('platform_list', [])

            if not order_number or not platform_list:
                continue

            for platform_id in platform_list:
                order_map[platform_id] = order_number

        # 查找当前订单
        if amazon_order_id in order_map:
            order_number = order_map[amazon_order_id]

            # 更新数据库和对象
            @sync_to_async
            def update_order():
                order.order_no = order_number
                order.save(update_fields=['order_no'])
                return order_number

            await update_order()
            print(f"✅  【成功】已同步订单号: {order_number}")
            return True, order_number
        else:
            return False, f"在领星API中未找到订单 {amazon_order_id}"

    except Exception as e:
        return False, f"同步失败: {type(e).__name__}: {e}"


# ==================== 核心函数（仅打印传参 + 可选执行）===================
async def step1_set_sku(sku: str, cg_price: str, execute: bool = True, app_id: str = None, app_secret: str = None):
    print(f"\n【步骤1】set_sku 传参：")
    print(f"   → sku        = {sku}")
    print(f"   → cg_price   = {cg_price}")
    if not execute:
        print("   → [预览模式] 不执行")
        return
    req_body = {"sku": sku, "product_name": sku, "sku_identifier":sku,"cg_price": cg_price}
    resp = await get_api_resp(req_body=req_body, api_path="/erp/sc/routing/storage/product/set", app_id=app_id, app_secret=app_secret)
    print(f"   → 新建产品结果 = {resp}")
    # print(f"   → 返回结果   = {resp.dict().get('msg', 'OK')}")


async def step2_update_order_binding(global_order_no: str, items: list, execute: bool = True, app_id: str = None, app_secret: str = None):
    print(f"\n【步骤2】批量绑定商品 updateOrder 传参：")
    print(f"   → global_order_no = {global_order_no}")
    print(f"   → order_item_list = [")
    for it in items:
        print(f"       {{ sku: {it['sku']}, msku: {it['sku']}, type: 3 }}")
    print(f"   ]")
    if not execute:
        print("   → [预览模式] 不执行")
        return
    order_item_list = [{"sku": it['sku'], "msku": it['sku'], "type": 3} for it in items]
    req_body = {"order_list": [{"global_order_no": global_order_no, "order_item_list": order_item_list}]}
    resp = await get_api_resp(req_body=req_body, api_path="/pb/mp/order/v2/updateOrder", app_id=app_id, app_secret=app_secret)
    # print(f"   → 返回结果 = {resp.dict().get('msg', 'OK')}")
    print(f"   → 绑定结果 = {resp}")


async def step3_add_warehousing(items_with_qty_price: list, execute: bool = True, app_id: str = None, app_secret: str = None):
    print(f"\n【步骤3】批量入库 add_warehousing 传参：")
    print(f"   → sys_wid = 509522, type = 1")
    print(f"   → product_list = [")
    for it in items_with_qty_price:
        print(f"       {{ sku: {it['sku']}, good_num: {it['quantity']}, price: {it['price_per_unit']} }}")
    print(f"   ]")
    if not execute:
        print("   → [预览模式] 不执行")
        return
    product_list = [
        {"sku": it['sku'], "good_num": it['quantity'], "bad_num": 0, "price": it['price_per_unit'], "fnsku": ""}
        for it in items_with_qty_price
    ]
    req_body = {"sys_wid": 509522, "type": 1, "product_list": product_list}
    resp = await get_api_resp(req_body=req_body, api_path="/erp/sc/routing/storage/storage/orderAdd", app_id=app_id, app_secret=app_secret)
    # print(f"   → 返回结果 = {resp.dict().get('msg', 'OK')}")
    print(f"   → 入库结果 = {resp}")



async def step4_fast_outbound(global_order_no: str, logistics_type_id: str, waybill_no: str, freight: str,
                              execute: bool = True, app_id: str = None, app_secret: str = None):
    print(f"\n【步骤4】快速出库 fastOutbound 传参：")
    print(f"   → global_order_no    = {global_order_no}")
    print(f"   → wid                = 509522")
    print(f"   → logistics_type_id  = {logistics_type_id}")
    print(f"   → waybill_no         = {waybill_no}")
    print(f"   → logistics_freight  = {freight}")
    if not execute:
        print("   → [预览模式] 不执行")
        return
    req_body = {
        "package": [{
            "global_order_no": global_order_no,
            "wid": 509522,
            "logistics_type_id": logistics_type_id,
            "waybill_no": waybill_no,
            "logistics_freight": freight,
        }]
    }
    resp = await get_api_resp(req_body=req_body, api_path="/pb/mp/order/v2/fastOutbound", app_id=app_id, app_secret=app_secret)
    # print(f"   → 出库结果 = {resp.dict().get('msg', 'OK')}")
    print(f"   → 出库结果 = {resp}")
    if resp.code != 0:
        raise LingxingAPIException(
            f"快速出库失败: code={resp.code}, message='{resp.message}'"
        )
    print("   → 快速出库成功 ✓")


async def step5_delivery_goods(order_no: str, execute: bool = True, app_id: str = None, app_secret: str = None):
    print(f"\n【步骤5】标发确认 deliveryGoods 传参：")
    print(f"   → order_number_list = {order_no}")
    if not execute:
        print("   → [预览模式] 不执行（会发两次）")
        return
    req_body = {"order_number_list": order_no}
    resp1 = await get_api_resp(req_body=req_body, api_path="/basicOpen/selfShipmentOrder/deliveryGoods", app_id=app_id, app_secret=app_secret)
    print(f"   → 第一次标发 = {resp1}")
    await asyncio.sleep(2.5)
    resp2 = await get_api_resp(req_body=req_body, api_path="/basicOpen/selfShipmentOrder/deliveryGoods", app_id=app_id, app_secret=app_secret)
    print(f"   → 第二次标发 = {resp2}")


# ==================== 查询订单 ====================
@sync_to_async
def get_full_order(sid: int, amazon_order_id: str):
    return AmazonOrders.objects.select_related('lingxing_shop').prefetch_related('items').get(
        lingxing_shop__sid=sid,
        amazon_order_id=amazon_order_id
    )


# ==================== 主流程 ====================
async def process_order(sid: int, amazon_order_id: str, mode: str = "preview"):
    print(f"\n{'=' * 100}")
    print(f"开始处理订单 | MODE = {mode.upper()}")
    print(f"SID = {sid} | 亚马逊订单号 = {amazon_order_id}")
    print(f"{'=' * 100}")
    try:
        order = await get_full_order(sid, amazon_order_id)

        # 获取项目的领星API凭证（尽早获取，用于后续所有API调用）
        try:
            app_id, app_secret = await _get_lingxing_credentials(order)
            print(f"\n【项目配置】使用项目领星API凭证")
        except ValueError as e:
            print(f"\n【致命错误】{str(e)}，终止处理")
            raise

        # ==================== 关键修复：自动同步订单号 ====================
        success, result = await sync_order_no_if_empty(order, sid, amazon_order_id, app_id=app_id, app_secret=app_secret)
        if not success:
            print(f"\n【致命错误】{result}，终止处理")
            return

        # 重新获取order_no（可能已被更新）
        order_no = result
        # ==================== 原有逻辑继续 ====================

        total_payment = Decimal(str(order.divi_goods_payment_total or 0))
        total_quantity = sum(item.quantity_ordered for item in order.items.all())
        price_per_unit = (total_payment / Decimal(total_quantity)).quantize(Decimal('0.00'),
                                                                            rounding=ROUND_HALF_UP) if total_quantity > 0 else Decimal(
            '0.00')

        waybill_no = order.divi_tracking_number or ""
        if waybill_no == "" or waybill_no is None:
            raise Exception("没有跟踪号，请手动处理")
        logistics_type_id = get_divi_logistics_code(order.divi_logistics_method or "", waybill_no)
        if logistics_type_id is None or logistics_type_id == "":
            raise Exception(f"物流方式 {order.divi_logistics_method} 不支持，请手动处理")
        freight = str(order.divi_shipping_amount or "0")

        print(f"领星订单号: {order_no}")
        print(f"总货款: {total_payment} | 总件数: {total_quantity} → 每件成本价: {price_per_unit}")
        print(f"物流方式: {order.divi_logistics_method} → 物流ID: {logistics_type_id}")
        print(f"跟踪号: {waybill_no} | 运费: {freight}")

        items = []
        for item in order.items.all():
            sku = item.seller_sku or item.local_sku or item.asin
            items.append({
                "sku": sku,
                "quantity": item.quantity_ordered,
                "price_per_unit": str(price_per_unit)
            })
            print(f"  商品: {sku} × {item.quantity_ordered} | ASIN: {item.asin}")

        # ==================== 关键：preview 模式也打印全部传参！====================
        execute_step1 = execute_step2 = execute_step3 = execute_step4 = execute_step5 = (mode != "preview")

        if mode == "preview":
            print(f"\n{'*' * 40} PREVIEW 模式：展示所有真实传参 {'*' * 40}")
        elif mode == "up_to_outbound":
            execute_step5 = False
            print(f"\n{'*' * 40} 执行到第4步出库（不标发） {'*' * 40}")
        elif mode == "full_shipment":
            print(f"\n{'*' * 40} 完整发货模式（5步全执行） {'*' * 40}")

        await step1_set_sku(items[0]['sku'], items[0]['price_per_unit'], execute=execute_step1, app_id=app_id, app_secret=app_secret)
        if len(items) > 1:
            for it in items[1:]:
                await step1_set_sku(it['sku'], it['price_per_unit'], execute=execute_step1, app_id=app_id, app_secret=app_secret)

        await step2_update_order_binding(order_no, items, execute=execute_step2, app_id=app_id, app_secret=app_secret)
        await step3_add_warehousing(items, execute=execute_step3, app_id=app_id, app_secret=app_secret)
        await step4_fast_outbound(order_no, logistics_type_id, waybill_no, freight, execute=execute_step4, app_id=app_id, app_secret=app_secret)
        await step5_delivery_goods(order_no, execute=execute_step5, app_id=app_id, app_secret=app_secret)

        print(f"\n{'=' * 100}")
        print(f"订单 {order_no} 处理完成！模式: {mode}")
        print(f"{'=' * 100}\n")
    except LingxingAPIException as e:
        # 捕获出库失败，打印并重新抛出
        print(f"\n❌ 订单处理失败: {str(e)}")
        print(f"{'=' * 100}\n")
        raise  # 重新抛出给上层调用

    except Exception as e:
        # 其他异常也打印并抛出
        print(f"\n❌ 订单处理异常: {type(e).__name__}: {e}")
        print(f"{'=' * 100}\n")
        raise


def lingxing_ship_order(sid: int, amazon_order_id: str, mode: str = "full_shipment"):
    """
    对外调用入口：
    - sid: 店铺 SID
    - amazon_order_id: 亚马逊订单号
    - mode: 默认为 "full_shipment"（完整一键发货）
            你也可以传入 "preview" / "up_to_outbound" 做测试
    """
    if not mode:
        mode = "preview"
        # mode = "up_to_outbound"
        # mode = "full_shipment"
    # mode = "preview"
    # 同步环境中跑异步的 process_order
    async_to_sync(process_order)(sid, amazon_order_id, mode=mode)


# ==================== 主函数-对内 ====================
async def main():
    sid = 521925
    amazon_order_id = "113-6214019-0037034"
    # 改这里就行！
    # MODE = "preview"  # 现在会打印全部5步传参！
    # MODE = "up_to_outbound"  # 执行到出库为止
    MODE = "full_shipment"  # 完整一键发货

    await process_order(sid, amazon_order_id, mode=MODE)


if __name__ == '__main__':
    asyncio.run(main())
