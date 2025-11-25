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
    一键发货 API（增强版）
    前端会传 sid + order_id
    后端必须完整验证所有业务条件，防止绕过前端
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
        # 找对应订单（带关联查询，减少数据库访问）
        try:
            order = AmazonOrders.objects.select_related(
                "lingxing_shop",
                "amazon_shop"
            ).get(
                amazon_order_id=amazon_order_id,
                lingxing_shop__sid=sid
            )
        except AmazonOrders.DoesNotExist:
            return JsonResponse({
                "success": False,
                "message": "未找到对应订单（请检查 sid 与 order_id）"
            })

        # ========== ⭐ 核心业务验证（防止绕过前端）⭐ ==========

        # 验证1：订单状态必须是 Unshipped
        if order.order_status != 'Unshipped':
            return JsonResponse({
                "success": False,
                "message": f"订单状态为 '{order.order_status}'，不是待发货状态，无法发货"
            })

        # 验证2：必须是FBM订单
        if order.fulfillment_channel != 'MFN':
            return JsonResponse({
                "success": False,
                "message": f"订单类型为 '{order.fulfillment_channel}'，不是FBM订单，无法发货"
            })

        # 验证3：DIVI状态必须在允许范围内 [3,4,5]
        if order.divi_order_status not in [3, 4, 5]:
            return JsonResponse({
                "success": False,
                "message": f"DIVI订单状态为 '{order.divi_order_status}'，未达到可发货状态（需为排单中、生产中或已发货）"
            })

        # 验证4：物流方式不能为空
        logistics_method = (order.divi_logistics_method or "").strip()
        if not logistics_method:
            return JsonResponse({
                "success": False,
                "message": "DIVI物流方式为空，无法发货"
            })

        # 验证5：跟踪号不能为空
        tracking_number = (order.divi_tracking_number or "").strip()
        if not tracking_number:
            return JsonResponse({
                "success": False,
                "message": "DIVI跟踪号为空，无法发货"
            })
        # ========== 业务验证通过，执行发货 ==========

        # 执行 Divi 完整发货流程
        lingxing_ship_order(sid, amazon_order_id, mode="full_shipment")

        # 发货后重新获取订单最新数据
        order.refresh_from_db()

        # 自动标记假面单（保持原有逻辑）
        logistics_method = (order.divi_logistics_method or "").strip()
        tracking_number = (order.divi_tracking_number or "").strip()

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
