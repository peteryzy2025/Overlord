# Amazon/amazon_divi_views.py

import asyncio
from django.http import JsonResponse
from django.views.decorators.http import require_GET
from datetime import datetime
from django.utils import timezone

from Api.lingxing.Y_OpenApi import get_api_resp
from Api.divi.divi_order_service import (
    query_divi_order,
    import_order_from_lingxing_to_divi,
    get_divi_brand_id_from_sid,
)
from Amazon.models import AmazonOrders, AmazonOrderItem


def parse_divi_time(time_str):
    """解析DIVI时间字符串为Django DateTimeField"""
    if not time_str:
        return None
    try:
        dt = datetime.strptime(time_str, '%Y-%m-%d %H:%M:%S')
        return timezone.make_aware(dt)
    except:
        return None


def update_divi_order_fields(order, divi_order_data):
    """
    更新订单的DIVI字段（包括商品明细）
    """
    # 更新主订单字段
    update_data = {
        'is_exported_to_divi': True,
        'divi_import_time': parse_divi_time(divi_order_data.get('createTime')),
        'divi_payment_time': parse_divi_time(divi_order_data.get('paymentTime')),
        'divi_dispatch_time': parse_divi_time(divi_order_data.get('sendOrderTime')),
        'divi_shipment_time': parse_divi_time(divi_order_data.get('sendGoodsTime')),
        'divi_logistics_method': divi_order_data.get('logisticsMethodName'),
        'divi_tracking_number': divi_order_data.get('trackingNumber'),
        'divi_order_status': divi_order_data.get('status'),
    }

    # 审核时间特殊处理（JSON中没有，可能需要从其他来源获取）
    # 如果状态>=3且审核时间为空，可设置当前时间为审核时间
    if divi_order_data.get('status') >= 3 and not order.divi_audit_time:
        update_data['divi_audit_time'] = timezone.now()

    # 使用update批量更新字段
    AmazonOrders.objects.filter(id=order.id).update(**update_data)

    # 更新商品明细
    order_goods_list = divi_order_data.get('orderGoodsList', [])
    for goods in order_goods_list:
        # 根据seller_sku查找或创建商品明细
        item_defaults = {
            'divi_product_name': goods.get('productName'),
            'quantity_ordered': goods.get('quantityOrdered', 1),
        }

        AmazonOrderItem.objects.update_or_create(
            order=order,
            seller_sku=goods.get('sellerSku'),
            defaults=item_defaults
        )

    return True


@require_GET
def add_divi_amazon_order(request):
    """
    测试流程：
    1. 通过领星接口获取 sid（如果你没传 sid）
    2. 通过 sid 在本地数据库找到 brand_id(divi_shop_id)
    3. 查询 Divi 订单是否存在
    4. 不存在就在 Divi 创建订单
    5. 导单成功后查询确认并更新本地状态
    """

    amazon_order_id = request.GET.get("order_id")
    print(f"\n{'=' * 60}")
    print(f"🚀 开始导单流程 - 订单号: {amazon_order_id}")
    print(f"{'=' * 60}")

    if not amazon_order_id:
        print("❌ 错误: 缺少参数 order_id")
        return JsonResponse({"status": "error", "message": "缺少参数 order_id"}, status=400)

    # 可选：用户也能传 sid
    sid_param = request.GET.get("sid")
    has_logistics = request.GET.get("has_logistics") == "1"
    print(f"📋 接收参数 - sid: {sid_param}, has_logistics: {has_logistics}")

    try:
        # ========== 1) 获取 sid（同步视图内，用 asyncio.run 调用 async API）==========
        if sid_param:
            sid = int(sid_param)
            print(f"✅ 使用传入的sid: {sid}")
        else:
            print(f"🔍 未传入sid，准备调用领星API查询...")
            lx_resp = asyncio.run(
                get_api_resp(
                    req_body={"order_id": amazon_order_id},
                    api_path="/erp/sc/data/mws/orderDetail",
                )
            )
            print(f"📡 领星API响应状态: {'成功' if lx_resp.data else '失败'}")
            if not lx_resp.data:
                print(f"❌ 领星未找到订单 {amazon_order_id}")
                return JsonResponse(
                    {"status": "error", "message": f"领星未找到订单 {amazon_order_id}"}
                )
            sid = lx_resp.data[0]["sid"]
            print(f"✅ 从领星获取到sid: {sid}")

        # ========== 2) sid → brandId（同步 ORM）==========
        print(f"🔍 正在查询 sid {sid} 对应的 divi_shop_id...")

        # 新增：优先使用前端直接传的 brand_id
        brand_id = request.GET.get("brand_id") or request.GET.get("divi_shop_id")
        if brand_id:
            try:
                brand_id = int(brand_id)
                print(f"✅ 前端直接传入 brand_id={brand_id}，优先使用")
            except:
                brand_id = None

        # 如果前端没传，才走老逻辑：通过 sid 查配置
        if not brand_id:
            brand_id = get_divi_brand_id_from_sid(sid)

        if not brand_id:
            print(f"❌ 错误: sid={sid} 未配置 divi_shop_id 且前端未传入")
            return JsonResponse({"status": "error", "message": "未找到有效的 divi_shop_id"}, status=500)

        print(f"✅ 最终使用的 brand_id: {brand_id}")

        # ========== 3) 查询 Divi 是否已有订单 ==========
        print(f"🔍 查询DIVI系统中是否已存在订单 {amazon_order_id}...")
        exists, orders, _ = query_divi_order(
            amazon_order_id=amazon_order_id,
            brand_id=brand_id,
            has_logistics=has_logistics,
        )
        print(f"📊 DIVI查询结果: exists={exists}, 返回订单数={len(orders) if orders else 0}")

        # 找到本地订单对象（用于后续更新）
        local_order = None
        try:
            local_order = AmazonOrders.objects.get(
                amazon_order_id=amazon_order_id,
                lingxing_shop__sid=sid
            )
        except AmazonOrders.DoesNotExist:
            print(f"⚠️ 未找到本地订单记录 {amazon_order_id}")

        if exists:
            print(f"⚠️ 订单已存在于DIVI，准备更新本地状态...")

            if local_order and orders:
                # 使用第一个订单数据更新所有字段
                divi_order_data = orders[0]
                update_divi_order_fields(local_order, divi_order_data)
                print(f"✅ 已更新本地订单 {amazon_order_id} 的所有DIVI字段")

            return JsonResponse({
                "status": "exists_updated",
                "brand_id": brand_id,
                "orders": orders,
            })

        # ========== 4) 不存在 -> 从领星导入到 Divi ==========
        print(f"🎯 订单不存在于DIVI，准备执行导入...")
        divi_result = import_order_from_lingxing_to_divi(
            order_id=amazon_order_id,
            print_if=False,
        )
        print(f"📦 DIVI导入完成，结果: {divi_result}")

        # ========== 5) 导单成功后查询确认并更新本地状态 ==========
        print(f"🔍 导入后重新查询DIVI确认...")
        max_retries = 3
        retry_count = 0
        exists = False
        divi_order_data = None

        while retry_count < max_retries and not exists:
            if retry_count > 0:
                print(f"   ⏳ 第{retry_count}次查询未找到，等待1秒后重试...")
                import time
                time.sleep(1)  # 等待1秒

            print(f"   🔍 第{retry_count + 1}次查询DIVI系统...")
            exists, orders, _ = query_divi_order(
                amazon_order_id=amazon_order_id,
                brand_id=brand_id,
                has_logistics=has_logistics,
            )
            if exists and orders:
                divi_order_data = orders[0]
            print(f"   📊 查询结果: exists={exists}")
            retry_count += 1

        if exists and local_order and divi_order_data:
            print(f"✅ 确认订单已在DIVI中存在，准备更新本地数据库...")
            update_divi_order_fields(local_order, divi_order_data)
            print(f"✅ 已更新本地订单 {amazon_order_id} 的所有DIVI字段")

            # 转成可序列化格式
            if hasattr(divi_result, "dict"):
                divi_response = divi_result.dict()
            else:
                divi_response = str(divi_result)

            print(f"🎉 导单流程完成，返回成功响应")
            print(f"{'=' * 60}\n")

            return JsonResponse({
                "status": "imported_updated",
                "brand_id": brand_id,
                "divi_response": divi_response,
                "local_updated": True
            })
        else:
            print(f"⚠️ 导入后未查询到订单或本地订单不存在")

        # 转成可序列化格式
        if hasattr(divi_result, "dict"):
            divi_response = divi_result.dict()
        else:
            divi_response = str(divi_result)

        print(f"🎉 导单流程完成，返回成功响应")
        print(f"{'=' * 60}\n")

        return JsonResponse({
            "status": "imported",
            "brand_id": brand_id,
            "divi_response": divi_response,
            "local_updated": exists and local_order is not None
        })

    except Exception as e:
        print(f"\n{'=' * 60}")
        print(f"❌ 导单流程异常终止: {str(e)}")
        import traceback
        traceback.print_exc()
        print(f"{'=' * 60}\n")
        return JsonResponse({"status": "error", "message": str(e)}, status=500)