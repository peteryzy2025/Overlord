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

from Amazon.models import AmazonOrders
from Api.lingxing.Y_OpenApi import get_api_resp
from Api.lingxing_p.lingxing_jc1 import get_lingxing_zifa_order  # 新增导入

# ==================== 物流匹配 ====================
from typing import Optional


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

        # 单号前缀判断：UniUni
        if tracking.startswith("UU"):
            # UniUni
            return "500518-21736"

        # 单号前缀判断：GOFO
        if tracking.startswith("YT") or tracking.startswith("GFU"):
            # GOFO
            return "500518-21672"

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

    # 2. 完全匹配的渠道名
    exact_map = {
        "威速易美国小货专线": "500518-22812",
        "云途全球专线挂号（标快普货）": "500518-22810",
        "京东普货标准专线-IE-01": "500518-22811",
    }
    if method in exact_map:
        return exact_map[method]

    contain_map = {
        "USPS": "500518-21735",
        "FEDEX": "500518-22808",
        "GOFO": "500518-21672",
        "DHL": "500518-22809",
        "顺丰": "500518-21734",
        "UNIUNI": "500518-21736",
    }
    for key, code in contain_map.items():
        if key in method:
            return code

    print(f"未匹配到物流方式: {divi_logistics_method}")
    return ""

# ==================== 新增：订单号同步函数 ====================
async def sync_order_no_if_empty(order, sid: int, amazon_order_id: str) -> tuple[bool, str]:
    """
    如果订单 order_no 为空，则从领星API同步并更新数据库
    返回: (是否成功, 订单号或错误信息)
    """
    if order.order_no:
        return True, order.order_no

    print(f"\n⚠️  【警告】订单 {amazon_order_id} 的 order_no 为空，尝试从领星API同步...")

    try:
        # 调用API获取最近10天的自发货订单
        zifa_data = await get_lingxing_zifa_order(sid=str(sid), days=10)

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
async def step1_set_sku(sku: str, cg_price: str, execute: bool = True):
    print(f"\n【步骤1】set_sku 传参：")
    print(f"   → sku        = {sku}")
    print(f"   → cg_price   = {cg_price}")
    if not execute:
        print("   → [预览模式] 不执行")
        return
    req_body = {"sku": sku, "product_name": sku, "cg_price": cg_price}
    resp = await get_api_resp(req_body=req_body, api_path="/erp/sc/routing/storage/product/set")
    print(f"   → 返回结果   = {resp.dict().get('msg', 'OK')}")


async def step2_update_order_binding(global_order_no: str, items: list, execute: bool = True):
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
    resp = await get_api_resp(req_body=req_body, api_path="/pb/mp/order/v2/updateOrder")
    print(f"   → 返回结果 = {resp.dict().get('msg', 'OK')}")


async def step3_add_warehousing(items_with_qty_price: list, execute: bool = True):
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
    resp = await get_api_resp(req_body=req_body, api_path="/erp/sc/routing/storage/storage/orderAdd")
    print(f"   → 返回结果 = {resp.dict().get('msg', 'OK')}")


async def step4_fast_outbound(global_order_no: str, logistics_type_id: str, waybill_no: str, freight: str,
                              execute: bool = True):
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
    resp = await get_api_resp(req_body=req_body, api_path="/pb/mp/order/v2/fastOutbound")
    # print(f"   → 出库结果 = {resp.dict().get('msg', 'OK')}")


async def step5_delivery_goods(order_no: str, execute: bool = True):
    print(f"\n【步骤5】标发确认 deliveryGoods 传参：")
    print(f"   → order_number_list = {order_no}")
    if not execute:
        print("   → [预览模式] 不执行（会发两次）")
        return
    req_body = {"order_number_list": order_no}
    resp1 = await get_api_resp(req_body=req_body, api_path="/basicOpen/selfShipmentOrder/deliveryGoods")
    print(f"   → 第一次标发 = {resp1.dict().get('msg', 'OK')}")
    await asyncio.sleep(2.5)
    resp2 = await get_api_resp(req_body=req_body, api_path="/basicOpen/selfShipmentOrder/deliveryGoods")
    print(f"   → 第二次标发 = {resp2.dict().get('msg', 'OK')}")


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

    order = await get_full_order(sid, amazon_order_id)

    # ==================== 关键修复：自动同步订单号 ====================
    success, result = await sync_order_no_if_empty(order, sid, amazon_order_id)
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
    logistics_type_id = get_divi_logistics_code(order.divi_logistics_method or "", waybill_no)
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

    await step1_set_sku(items[0]['sku'], items[0]['price_per_unit'], execute=execute_step1)
    if len(items) > 1:
        for it in items[1:]:
            await step1_set_sku(it['sku'], it['price_per_unit'], execute=execute_step1)

    await step2_update_order_binding(order_no, items, execute=execute_step2)
    await step3_add_warehousing(items, execute=execute_step3)
    await step4_fast_outbound(order_no, logistics_type_id, waybill_no, freight, execute=execute_step4)
    await step5_delivery_goods(order_no, execute=execute_step5)

    print(f"\n{'=' * 100}")
    print(f"订单 {order_no} 处理完成！模式: {mode}")
    print(f"{'=' * 100}\n")


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
    asyncio.run(process_order(sid, amazon_order_id, mode=mode))


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
