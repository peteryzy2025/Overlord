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
    if not amazon_order_id:
        return JsonResponse({"status": "error", "message": "缺少参数 order_id"}, status=400)

    # 可选：用户也能传 sid
    sid_param = request.GET.get("sid")
    has_logistics = request.GET.get("has_logistics") == "1"

    try:
        # ========== 1) 获取 sid（同步视图内，用 asyncio.run 调用 async API）==========
        if sid_param:
            sid = int(sid_param)
        else:
            lx_resp = asyncio.run(
                get_api_resp(
                    req_body={"order_id": amazon_order_id},
                    api_path="/erp/sc/data/mws/orderDetail",
                )
            )
            if not lx_resp.data:
                return JsonResponse(
                    {"status": "error", "message": f"领星未找到订单 {amazon_order_id}"}
                )
            sid = lx_resp.data[0]["sid"]

        # ========== 2) sid → brandId（同步 ORM）==========
        brand_id = get_divi_brand_id_from_sid(sid)
        if not brand_id:
            return JsonResponse(
                {"status": "error", "message": f"sid={sid} 未配置 divi_shop_id"},
                status=500,
            )

        # ========== 3) 查询 Divi 是否已有订单 ==========
        exists, orders, _ = query_divi_order(
            amazon_order_id=amazon_order_id,
            brand_id=brand_id,
            has_logistics=has_logistics,
        )

        if exists:
            # 如果已存在，更新本地状态为已导出
            try:
                AmazonOrders.objects.filter(
                    amazon_order_id=amazon_order_id
                ).update(is_exported_to_divi=True)
                print(f"✅ 订单 {amazon_order_id} 已存在DIVI，更新本地状态为已导出")
            except Exception as update_error:
                print(f"⚠️ 更新本地状态失败: {update_error}")

            return JsonResponse({
                "status": "exists",
                "brand_id": brand_id,
                "orders": orders,
            })

        # ========== 4) 不存在 -> 从领星导入到 Divi ==========
        divi_result = import_order_from_lingxing_to_divi(
            order_id=amazon_order_id,
            print_if=False,
        )

        # ========== 5) 导单成功后查询确认并更新本地状态 ==========
        try:
            # 重新查询DIVI确认订单是否存在
            exists, orders, _ = query_divi_order(
                amazon_order_id=amazon_order_id,
                brand_id=brand_id,
                has_logistics=has_logistics,
            )

            if exists:
                # 更新本地数据库状态
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

        # 转成可序列化格式
        if hasattr(divi_result, "dict"):
            divi_response = divi_result.dict()
        else:
            divi_response = str(divi_result)

        return JsonResponse({
            "status": "imported",
            "brand_id": brand_id,
            "divi_response": divi_response,
            "local_updated": exists  # 告知前端本地状态已更新
        })

    except Exception as e:
        print(f'导单出错：{e}')
        import traceback
        traceback.print_exc()
        return JsonResponse({"status": "error", "message": str(e)}, status=500)