# Amazon/amazon_divi_views.py

import asyncio
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from Api.lingxing.Y_OpenApi import get_api_resp
from Api.divi.divi_order_service import (
    query_divi_order,
    import_order_from_lingxing_to_divi,
    get_divi_brand_id_from_sid,
)
from Amazon.models import AmazonOrders


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
        brand_id = get_divi_brand_id_from_sid(sid)
        if not brand_id:
            print(f"❌ 错误: sid={sid} 未配置 divi_shop_id")
            return JsonResponse(
                {"status": "error", "message": f"sid={sid} 未配置 divi_shop_id"},
                status=500,
            )
        print(f"✅ 找到 brand_id (divi_shop_id): {brand_id}")

        # ========== 3) 查询 Divi 是否已有订单 ==========
        print(f"🔍 查询DIVI系统中是否已存在订单 {amazon_order_id}...")
        exists, orders, _ = query_divi_order(
            amazon_order_id=amazon_order_id,
            brand_id=brand_id,
            has_logistics=has_logistics,
        )
        print(f"📊 DIVI查询结果: exists={exists}, 返回订单数={len(orders) if orders else 0}")

        if exists:
            print(f"⚠️ 订单已存在于DIVI，准备更新本地状态...")
            # 如果已存在，更新本地状态为已导出
            try:
                updated = AmazonOrders.objects.filter(
                    amazon_order_id=amazon_order_id
                ).update(is_exported_to_divi=True)
                print(f"✅ 本地订单状态更新: {'成功' if updated > 0 else '未找到记录'}")
                print(f"   - 更新记录数: {updated}")
            except Exception as update_error:
                print(f"⚠️ 更新本地状态失败: {update_error}")

            return JsonResponse({
                "status": "exists",
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
            print(f"   📊 查询结果: exists={exists}")
            retry_count += 1

        if exists:
            print(f"✅ 确认订单已在DIVI中存在，准备更新本地数据库...")
            # 更新本地数据库状态
            try:
                updated = AmazonOrders.objects.filter(
                    amazon_order_id=amazon_order_id
                ).update(is_exported_to_divi=True)

                if updated > 0:
                    print(f"✅ 已更新本地订单 {amazon_order_id} 的DIVI状态为已导出")
                else:
                    print(f"⚠️ 未找到本地订单 {amazon_order_id} 进行状态更新")
            except Exception as update_error:
                print(f"⚠️ 更新本地DIVI状态失败: {update_error}")
                # 即使更新本地状态失败，也不影响主流程
        else:
            print(f"⚠️ 警告：导入后仍未在DIVI中查询到订单，状态可能未同步")

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
            "local_updated": exists  # 告知前端本地状态已更新
        })

    except Exception as e:
        print(f"\n{'=' * 60}")
        print(f"❌ 导单流程异常终止: {str(e)}")
        import traceback
        traceback.print_exc()
        print(f"{'=' * 60}\n")
        return JsonResponse({"status": "error", "message": str(e)}, status=500)
