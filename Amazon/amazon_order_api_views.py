# amazon_order_view.py
import json
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from asgiref.sync import async_to_sync

from Amazon.models import AmazonOrders
from Api.lingxing_p.lingxing_fh import lingxing_ship_order  # 你已经改好的发货程序入口


@csrf_exempt
def api_ship_order(request):
    """
    一键发货 API
    前端会传 sid + order_id
    """
    if request.method != "POST":
        return JsonResponse({"success": False, "message": "只支持 POST 请求"})

    try:
        data = json.loads(request.body)
    except Exception:
        return JsonResponse({"success": False, "message": "请求体必须为 JSON"})

    sid = data.get("sid")
    amazon_order_id = data.get("order_id")

    if not sid or not amazon_order_id:
        return JsonResponse({"success": False, "message": "缺少 sid 或 order_id"})

    try:
        # 找对应订单
        try:
            order = AmazonOrders.objects.select_related("lingxing_shop").get(
                amazon_order_id=amazon_order_id,
                lingxing_shop__sid=sid
            )
        except AmazonOrders.DoesNotExist:
            return JsonResponse({
                "success": False,
                "message": "未找到对应订单（请检查 sid 与 order_id）"
            })


        # ⭐ 执行 Divi 完整发货流程
        lingxing_ship_order(sid, amazon_order_id, mode="full_shipment")

        # ⭐ 发货后重新拿一下订单最新数据（含 divi_logistics_method / divi_tracking_number）
        order.refresh_from_db()

        # ⭐ 新：根据物流方式 + 跟踪号 判断是否为“假面单发货”
        # 定义：divi_logistics_method == "F-USPS" 且 跟踪号包含 "LS"
        logistics_method = (order.divi_logistics_method or "").strip()
        tracking_number = (order.divi_tracking_number or "").strip()

        # 只在「满足条件且当前还不是假面单」时，自动标记为假面单
        if (
            logistics_method == "F-USPS" and
            tracking_number and "LS" in tracking_number and
            not order.masked_single
        ):
            order.masked_single = True
            order.save(update_fields=["masked_single"])

        return JsonResponse({
            "success": True,
            "message": f"订单 {amazon_order_id} 发货流程已执行"
        })

    except Exception as e:
        return JsonResponse({
            "success": False,
            "message": f"发货异常：{str(e)}"
        })

@csrf_exempt
def api_mark_real_shipment(request):
    """
    将假面单发货的订单标注为“真发”
    条件：masked_single == True
    动作：masked_single 置为 False
    前端传参：
        - sid
        - order_id (amazon_order_id)
    """
    if request.method != "POST":
        return JsonResponse({"success": False, "message": "只支持 POST 请求"})

    try:
        data = json.loads(request.body.decode())
    except Exception:
        return JsonResponse({"success": False, "message": "请求体必须为 JSON"})

    sid = data.get("sid")
    amazon_order_id = data.get("order_id")

    if not sid or not amazon_order_id:
        return JsonResponse({"success": False, "message": "缺少 sid 或 order_id"})

    try:
        order = AmazonOrders.objects.select_related("lingxing_shop").get(
            amazon_order_id=amazon_order_id,
            lingxing_shop__sid=sid,
        )
    except AmazonOrders.DoesNotExist:
        return JsonResponse({
            "success": False,
            "message": "未找到对应订单（请检查 sid 和 order_id）"
        })

    # 只有假面单订单才允许标注真发
    if not order.masked_single:
        return JsonResponse({
            "success": False,
            "message": "该订单当前不是假面单发货，无需标注真发"
        })

    # 标注为真发：把假面单标记取消
    order.masked_single = False
    order.save(update_fields=["masked_single"])

    return JsonResponse({
        "success": True,
        "message": f"订单 {amazon_order_id} 已标注为真发"
    })
