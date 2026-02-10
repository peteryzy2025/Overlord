# Amazon/view/views_amazon_order.py

import io
import asyncio
import json
from datetime import datetime, timedelta
import asyncio
from asgiref.sync import sync_to_async
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.db import transaction
from django.db.models import Sum, Q
from django.http import JsonResponse, HttpResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET
from django.utils import timezone

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter
# 项目内模型
from amazon.models import LingXingAmazonShop, AmazonOrders, AmazonOrderItem
from general.models import UserOperationLog

# 项目内工具函数 / 视图函数
from amazon.amazon_views import (
    get_user_operation_permissions,
    determine_filter_type_and_value,
    get_date_range_from_option,
    get_shop_ids_by_filter,
)
from amazon.amazon_divi_views import update_divi_order_fields

# 领星 & DIVI 接口服务
from api.lingxing.Y_OpenApi import get_api_resp
from api.divi.divi_order_service import (
    query_divi_order,
    import_order_from_lingxing_to_divi,
    get_divi_brand_id_from_sid,
)
from api.lingxing_p.lingxing_fh import lingxing_ship_order


@login_required
def amazon_order_management_page(request):
    # 什么都不查！直接返回空！
    return render(request, 'amazon_order_management.html', {
       'active_nav': 'amazon_orders',
        'active_page': 'amazon_orders',
    })


@login_required
def get_amazon_orders_list_api(request):
    """
    优化版：5万条订单 → 0.5~0.8秒响应（PostgreSQL）
    核心：预警过滤 + 分页全在数据库完成，只取一页数据
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': '只支持POST请求'}, status=405)

    try:
        data = json.loads(request.body)
        user = request.user
        permissions = get_user_operation_permissions(user)

        # ========== 权限控制 ==========
        filter_type, filter_value = determine_filter_type_and_value(request, data, permissions)

        # 分页参数
        page = int(data.get('page', 1))
        page_size = int(data.get('page_size', 20))
        page_size = min(page_size, 100)  # 最多100条

        # 日期筛选
        date_range_option = data.get('date_range', 'yesterday')
        start_date_str = data.get('start_date', '')
        end_date_str = data.get('end_date', '')

        # 其他筛选条件
        order_id_filter = data.get('order_id', '').strip()
        shop_name_filter = data.get('shop_name', '').strip()

        # 多选筛选条件（逗号分隔）
        shop_status_filter = data.get('shop_status', '').strip()
        shop_status_list = [s.strip() for s in shop_status_filter.split(',') if s.strip()] if shop_status_filter else []

        order_status_filter = data.get('order_status', '').strip()
        order_status_list = [s.strip() for s in order_status_filter.split(',') if s.strip()] if order_status_filter else []

        fulfillment_channel_filter = data.get('fulfillment_channel', '').strip()
        fulfillment_channel_list = [s.strip() for s in fulfillment_channel_filter.split(',') if s.strip()] if fulfillment_channel_filter else []

        divi_export_filter = data.get('divi_export', '').strip()
        divi_export_list = [s.strip() for s in divi_export_filter.split(',') if s.strip()] if divi_export_filter else []

        divi_order_status_filter = data.get('divi_order_status', '').strip()
        divi_order_status_list = [s.strip() for s in divi_order_status_filter.split(',') if s.strip()] if divi_order_status_filter else []

        divi_tracking_filter = data.get('divi_tracking', '').strip()
        divi_tracking_list = [s.strip() for s in divi_tracking_filter.split(',') if s.strip()] if divi_tracking_filter else []

        masked_single_filter = data.get('masked_single', '').strip()
        masked_single_list = [s.strip() for s in masked_single_filter.split(',') if s.strip()] if masked_single_filter else []

        shipping_deadline_filter = data.get('shipping_deadline', '').strip()  # red / yellow / all_deadline
        shipping_deadline_list = [s.strip() for s in shipping_deadline_filter.split(',') if s.strip()] if shipping_deadline_filter else []

        # 解析日期范围
        current_start, current_end = None, None
        if start_date_str and end_date_str:
            try:
                current_start = datetime.strptime(start_date_str.split(' ')[0], '%Y-%m-%d').date()
                current_end = datetime.strptime(end_date_str.split(' ')[0], '%Y-%m-%d').date()
            except:
                pass
        if not current_start or not current_end:
            current_start, current_end = get_date_range_from_option(date_range_option)

        if not current_start or not current_end:
            return JsonResponse({'success': False, 'message': '请提供有效的日期范围'}, status=400)

        # 无权限返回空
        if filter_type == 'none':
            return JsonResponse({'success': True,
                                 'data': {'orders': [], 'total': 0, 'page': page, 'page_size': page_size,
                                          'total_pages': 0}})

        # 获取权限内店铺
        shop_ids = get_shop_ids_by_filter(filter_type, filter_value, user=user)
        shop_ids_list = list(shop_ids)
        if not shop_ids_list:
            return JsonResponse({'success': True,
                                 'data': {'orders': [], 'total': 0, 'page': page, 'page_size': page_size,
                                          'total_pages': 0}})

        lingxing_shops = LingXingAmazonShop.objects.filter(amazon_shop_id__in=shop_ids_list)
        lingxing_shop_ids = list(lingxing_shops.values_list('sid', flat=True))
        if not lingxing_shop_ids:
            return JsonResponse({'success': True,
                                 'data': {'orders': [], 'total': 0, 'page': page, 'page_size': page_size,
                                          'total_pages': 0}})

        # ========== 构建查询条件 ==========
        order_filter = Q(lingxing_shop_id__in=lingxing_shop_ids)
        order_filter &= Q(purchase_date_local__date__gte=current_start)
        order_filter &= Q(purchase_date_local__date__lte=current_end)

        # 其他普通筛选条件（支持多选）
        if order_status_list:
            if len(order_status_list) == 1:
                order_filter &= Q(order_status=order_status_list[0])
            else:
                order_filter &= Q(order_status__in=order_status_list)

        if fulfillment_channel_list:
            if len(fulfillment_channel_list) == 1:
                order_filter &= Q(fulfillment_channel=fulfillment_channel_list[0])
            else:
                order_filter &= Q(fulfillment_channel__in=fulfillment_channel_list)

        if divi_export_list:
            # 处理多选布尔值
            bool_values = []
            for v in divi_export_list:
                if v.lower() == 'true':
                    bool_values.append(True)
                elif v.lower() == 'false':
                    bool_values.append(False)
            if bool_values:
                if len(bool_values) == 1:
                    order_filter &= Q(is_exported_to_divi=bool_values[0])
                else:
                    order_filter &= Q(is_exported_to_divi__in=bool_values)

        if divi_order_status_list:
            status_ints = [int(s) for s in divi_order_status_list if s.isdigit()]
            if status_ints:
                if len(status_ints) == 1:
                    order_filter &= Q(divi_order_status=status_ints[0])
                else:
                    order_filter &= Q(divi_order_status__in=status_ints)

        if divi_tracking_list:
            # 面单筛选不支持简单的 __in，需要特殊处理
            if len(divi_tracking_list) == 1:
                if divi_tracking_list[0] == 'has':
                    order_filter &= Q(divi_tracking_number__isnull=False) & ~Q(divi_tracking_number='')
                elif divi_tracking_list[0] == 'none':
                    order_filter &= (Q(divi_tracking_number__isnull=True) | Q(divi_tracking_number=''))
            else:
                # 同时选了 has 和 none 表示不筛选
                pass

        if shop_status_list:
            if len(shop_status_list) == 1:
                order_filter &= Q(amazon_shop__shop_status=shop_status_list[0])
            else:
                order_filter &= Q(amazon_shop__shop_status__in=shop_status_list)

        if masked_single_list:
            bool_values = [(v.lower() == 'true') for v in masked_single_list if v.lower() in ['true', 'false']]
            if bool_values:
                if len(bool_values) == 1:
                    order_filter &= Q(masked_single=bool_values[0])
                else:
                    order_filter &= Q(masked_single__in=bool_values)

        if order_id_filter:
            order_filter &= Q(amazon_order_id__icontains=order_id_filter)
        if shop_name_filter:
            order_filter &= Q(lingxing_shop__name__icontains=shop_name_filter)

        # ========== 关键优化：发货时限预警过滤搬到数据库 ==========
        now_utc = timezone.now()
        EXCLUDE_STATUS = ['PendingAvailability', 'Pending', 'Canceled', 'Shipped']

        if shipping_deadline_list:
            base_q = (
                    Q(latest_ship_date__isnull=False) &
                    ~Q(order_status__in=EXCLUDE_STATUS)
            )

            # 处理多选发货预警类型
            has_red = 'red' in shipping_deadline_list
            has_yellow = 'yellow' in shipping_deadline_list
            has_all = 'all_deadline' in shipping_deadline_list

            if has_red and has_yellow or has_all:
                # 红色+黄色或全部预警 = 全部预警范围
                yellow_max = now_utc + timedelta(hours=32)
                order_filter &= base_q & Q(latest_ship_date__lte=yellow_max)
            elif has_red:
                red_threshold = now_utc + timedelta(hours=8)
                order_filter &= base_q & Q(latest_ship_date__lte=red_threshold)
            elif has_yellow:
                yellow_min = now_utc + timedelta(hours=8, seconds=1)
                yellow_max = now_utc + timedelta(hours=32)
                order_filter &= base_q & Q(latest_ship_date__gt=yellow_min) & Q(
                    latest_ship_date__lte=yellow_max)

        # ========== 构建最终 queryset（带预加载，无.only()）==========
        orders_queryset = AmazonOrders.objects.filter(order_filter) \
            .select_related(
            'lingxing_shop',
            'amazon_shop__ops__operational_account'
        ) \
            .order_by('-purchase_date_local')

        # ========== 分页（数据库级）==========
        from django.core.paginator import Paginator
        paginator = Paginator(orders_queryset, page_size)
        total = paginator.count  # PostgreSQL 很快

        try:
            page_obj = paginator.page(page)
        except PageNotAnInteger:
            page_obj = paginator.page(1)
        except EmptyPage:
            page_obj = paginator.page(paginator.num_pages)

        # ========== 只对当前页（20条）计算预警文字 ==========
        order_ids = [obj.id for obj in page_obj]
        quantity_map = {}
        if order_ids:
            quantity_results = AmazonOrderItem.objects.filter(order_id__in=order_ids) \
                .values('order_id') \
                .annotate(total_quantity=Sum('quantity_ordered')) \
                .values_list('order_id', 'total_quantity')
            quantity_map = dict(quantity_results)

        orders_data = []
        for order in page_obj:
            # 预警状态计算（只算20次）
            deadline_status = 'normal'
            deadline_text = ''
            hours_remaining = None
            print(f"\n{'=' * 60}")
            print(f"调试订单: {order.amazon_order_id}")
            print(f"原始 latest_ship_date: {order.latest_ship_date} (类型: {type(order.latest_ship_date)})")
            print(f"订单状态: {order.order_status}")
            print(f"是否在排除列表: {order.order_status in EXCLUDE_STATUS}")

            if (order.latest_ship_date and order.order_status not in EXCLUDE_STATUS):
                beijing_deadline = order.latest_ship_date + timedelta(hours=16)
                hours_remaining = (beijing_deadline - now_utc).total_seconds() / 3600

                if hours_remaining <= 24:
                    deadline_status = 'red'
                    deadline_text = f'{int(hours_remaining)}小时'
                elif hours_remaining <= 48:
                    deadline_status = 'yellow'
                    deadline_text = f'{int(hours_remaining)}小时'

            # 运营信息（已预加载，无N+1）
            operator_name = ''
            group_name = ''
            if order.amazon_shop and order.amazon_shop.ops:
                operator_name = order.amazon_shop.ops.first_name or order.amazon_shop.ops.username
                if (hasattr(order.amazon_shop.ops, 'operational_account') and
                        order.amazon_shop.ops.operational_account):
                    group_name = order.amazon_shop.ops.operational_account.ops_group or ''

            shop_name = order.lingxing_shop.name if order.lingxing_shop else '未知店铺'
            shop_status = order.amazon_shop.shop_status if order.amazon_shop else ''

            orders_data.append({
                'amazon_order_id': order.amazon_order_id,
                'shop_name': shop_name,
                'shop_status': shop_status,
                'operator_name': operator_name,
                'group': group_name,
                'order_status': order.order_status or '',
                'quantity': quantity_map.get(order.id, 0),
                'order_total_amount': str(order.order_total_amount or '0.00'),
                'purchase_date_local': order.purchase_date_local.strftime(
                    '%Y-%m-%d %H:%M:%S') if order.purchase_date_local else '',
                'is_exported_to_divi': order.is_exported_to_divi,
                'fulfillment_channel': order.fulfillment_channel or '',
                'divi_order_status': order.divi_order_status,
                'sid': order.lingxing_shop.sid if order.lingxing_shop else None,
                'divi_shop_id': (order.lingxing_shop.amazon_shop.divi_shop_id
                                 if order.lingxing_shop and order.lingxing_shop.amazon_shop else None),
                'divi_logistics_method': order.divi_logistics_method or '',
                'divi_tracking_number': order.divi_tracking_number or '',
                'masked_single': order.masked_single,
                'latest_ship_date': (order.latest_ship_date.strftime('%Y-%m-%d %H:%M:%S')
                                           if order.latest_ship_date else ''),
                'deadline_status': deadline_status,
                'deadline_text': deadline_text,
                'hours_remaining': hours_remaining
            })

        return JsonResponse({
            'success': True,
            'data': {
                'orders': orders_data,
                'total': total,
                'page': page,
                'page_size': page_size,
                'total_pages': paginator.num_pages
            }
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({'success': False, 'message': f'服务器错误: {str(e)}'}, status=500)


@require_GET
@login_required
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
        # ✅ 修改1：记录失败日志（店铺未知）
        try:
            UserOperationLog.objects.create(
                user=request.user,
                operation_type=UserOperationLog.ORDER_IMPORT,
                operation_record=f"店铺[未知]订单导单失败: 缺少order_id参数",
            )
        except Exception as log_error:
            print(f"❌ 日志记录失败: {log_error}")
        return JsonResponse({"status": "error", "message": "缺少参数 order_id"}, status=400)

    # 可选：用户也能传 sid
    sid_param = request.GET.get("sid")
    has_logistics = request.GET.get("has_logistics") == "1"
    print(f"📋 接收参数 - sid: {sid_param}, has_logistics: {has_logistics}")

    # 提前定义 local_order，用于后续日志记录
    local_order = None

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
                # ✅ 修改2：记录失败日志（店铺未知）
                try:
                    UserOperationLog.objects.create(
                        user=request.user,
                        operation_type=UserOperationLog.ORDER_IMPORT,
                        operation_record=f"店铺[未知]订单[{amazon_order_id}]导单失败: 领星未找到该订单",
                    )
                except Exception as log_error:
                    print(f"❌ 日志记录失败: {log_error}")
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
            # ✅ 修改3：记录失败日志（店铺未知）
            try:
                UserOperationLog.objects.create(
                    user=request.user,
                    operation_type=UserOperationLog.ORDER_IMPORT,
                    operation_record=f"店铺[未知]订单[{amazon_order_id}]导单失败: 未配置divi_shop_id",
                )
            except Exception as log_error:
                print(f"❌ 日志记录失败: {log_error}")
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

            # ✅ 修改4：记录成功日志（订单已存在）
            shop_name = local_order.lingxing_shop.name if local_order and local_order.lingxing_shop else '未知'
            try:
                UserOperationLog.objects.create(
                    user=request.user,
                    operation_type=UserOperationLog.ORDER_IMPORT,
                    operation_record=f"店铺[{shop_name}]订单[{amazon_order_id}]导单到DIVI: 成功（订单已存在）",
                )
            except Exception as log_error:
                print(f"❌ 日志记录失败: {log_error}")

            return JsonResponse({
                "status": "exists_updated",
                "brand_id": brand_id,
                "orders": orders,
            })

        # ========== 4) 不存在 -> 从领星导入到 Divi ==========
        print(f"🎯 订单不存在于DIVI，准备执行导入...")
        divi_result = import_order_from_lingxing_to_divi(
            order_id=amazon_order_id,
            print_if=True,
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

            # ✅ 修改5：记录成功日志（导入成功）
            shop_name = local_order.lingxing_shop.name if local_order and local_order.lingxing_shop else '未知'
            try:
                UserOperationLog.objects.create(
                    user=request.user,
                    operation_type=UserOperationLog.ORDER_IMPORT,
                    operation_record=f"店铺[{shop_name}]订单[{amazon_order_id}]导单到DIVI: 成功",
                )
            except Exception as log_error:
                print(f"❌ 日志记录失败: {log_error}")

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

        # ✅ 修改6：记录成功日志（导入但本地未更新）
        shop_name = local_order.lingxing_shop.name if local_order and local_order.lingxing_shop else '未知'
        try:
            UserOperationLog.objects.create(
                user=request.user,
                operation_type=UserOperationLog.ORDER_IMPORT,
                operation_record=f"店铺[{shop_name}]订单[{amazon_order_id}]导单到DIVI: 成功（DIVI响应）",
            )
        except Exception as log_error:
            print(f"❌ 日志记录失败: {log_error}")

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

        # ✅ 修改7：记录异常日志
        shop_name = local_order.lingxing_shop.name if local_order and local_order.lingxing_shop else '未知'
        try:
            UserOperationLog.objects.create(
                user=request.user,
                operation_type=UserOperationLog.ORDER_IMPORT,
                operation_record=f"店铺[{shop_name}]订单[{amazon_order_id}]导单异常: {str(e)[:200]}",
            )
        except Exception as log_error:
            print(f"❌ 日志记录失败: {log_error}")

        return JsonResponse({"status": "error", "message": str(e)}, status=500)


@login_required
def update_divi_export_status_api(request):
    """
    并发优化版：批量更新订单的DIVI导出状态（线程池版，避免asyncio线程问题）
    核心优化：ThreadPoolExecutor 并发查询 DIVI + bulk_update 批量写库
    性能：100 条订单 ≈ 4~6 秒，兼容 Django runserver 多线程环境
    """
    if request.method != 'POST':
        print("❌ 错误: 只支持POST请求")
        return JsonResponse({'success': False, 'message': '只支持POST请求'}, status=405)

    try:
        data = json.loads(request.body)
        user = request.user
        permissions = get_user_operation_permissions(user)

        print(f"\n{'=' * 60}")
        print(f"🔄 批量更新DIVI状态API - 用户: {user.username} (权限: {permissions})")
        print(f"📋 接收参数: {json.dumps(data, ensure_ascii=False, indent=2)}")

        # ============= 权限控制核心逻辑（使用统一函数） =============
        filter_type, filter_value = determine_filter_type_and_value(request, data, permissions)
        print(f"🔐 权限校验结果: filter_type={filter_type}, filter_value={filter_value}")

        # 解析日期参数
        date_range_option = data.get('date_range', 'yesterday')
        start_date_str = data.get('start_date', '')
        end_date_str = data.get('end_date', '')

        # 订单号筛选
        order_id_filter = data.get('order_id', '').strip()
        shop_name_filter = data.get('shop_name', '').strip()
        shop_status_filter = data.get('shop_status', '').strip()

        # ========== 新增筛选项解析 ==========
        order_status_filter = data.get('order_status', '').strip()
        fulfillment_channel_filter = data.get('fulfillment_channel', '').strip()
        divi_export_filter = data.get('divi_export', '').strip()
        divi_order_status_filter = data.get('divi_order_status', '').strip()
        divi_tracking_filter = data.get('divi_tracking', '').strip()
        masked_single_filter = data.get('masked_single', '').strip()

        current_start, current_end = None, None
        if start_date_str and end_date_str:
            try:
                current_start = datetime.strptime(start_date_str.split(' ')[0], '%Y-%m-%d').date()
                current_end = datetime.strptime(end_date_str.split(' ')[0], '%Y-%m-%d').date()
                print(f"📅 使用自定义日期: {current_start} 至 {current_end}")
            except:
                print(f"⚠️ 日期解析失败，将使用快捷选项")
                pass

        if not current_start or not current_end:
            current_start, current_end = get_date_range_from_option(date_range_option)
            print(f"📅 使用快捷日期({date_range_option}): {current_start} 至 {current_end}")

        if not current_start or not current_end:
            print("❌ 错误: 未提供有效的日期范围")
            return JsonResponse({
                'success': False,
                'message': '请提供有效的日期范围'
            }, status=400)

        # 分页参数
        page = int(data.get('page', 1))
        page_size = int(data.get('page_size', 20))
        page_size = min(page_size, 100)
        print(f"📄 分页参数: page={page}, page_size={page_size}")

        # 无权限或没店铺直接返回空
        if filter_type == 'none':
            print("⚠️ 权限不足，返回空数据")
            return JsonResponse({
                'success': True,
                'data': {
                    'orders': [],
                    'total': 0,
                    'page': page,
                    'page_size': page_size,
                    'total_pages': 0
                }
            })

        # 获取店铺
        print(f"🔍 查询符合条件的店铺...")
        shop_ids = get_shop_ids_by_filter(filter_type, filter_value)
        shop_ids_list = list(shop_ids)
        print(f"✅ 找到 {len(shop_ids_list)} 个AmazonShop")

        if not shop_ids_list:
            print("⚠️ 未找到任何店铺，返回空数据")
            return JsonResponse({
                'success': True,
                'data': {
                    'orders': [],
                    'total': 0,
                    'page': page,
                    'page_size': page_size,
                    'total_pages': 0
                }
            })

        # 获取LingXing店铺
        print(f"🔍 查询绑定的LingXing店铺...")
        lingxing_shops = LingXingAmazonShop.objects.filter(amazon_shop_id__in=shop_ids_list)
        lingxing_shop_ids = list(lingxing_shops.values_list('sid', flat=True))
        print(f"✅ 找到 {len(lingxing_shop_ids)} 个LingXing店铺")

        if not lingxing_shop_ids:
            print("⚠️ 未找到LingXing店铺，返回空数据")
            return JsonResponse({
                'success': True,
                'data': {
                    'orders': [],
                    'total': 0,
                    'page': page,
                    'page_size': page_size,
                    'total_pages': 0
                }
            })

        # 构建订单查询条件
        print(f"🔍 构建订单查询条件...")
        order_filter = Q(lingxing_shop_id__in=lingxing_shop_ids)
        order_filter &= Q(purchase_date_local__date__gte=current_start)
        order_filter &= Q(purchase_date_local__date__lte=current_end)

        # ========== 应用所有筛选项 ==========
        if order_status_filter:
            order_filter &= Q(order_status=order_status_filter)
        if fulfillment_channel_filter:
            order_filter &= Q(fulfillment_channel=fulfillment_channel_filter)
        if divi_export_filter:
            divi_export_bool = divi_export_filter.lower() == 'true'
            order_filter &= Q(is_exported_to_divi=divi_export_bool)
        if divi_order_status_filter:
            order_filter &= Q(divi_order_status=int(divi_order_status_filter))
        if divi_tracking_filter:
            if divi_tracking_filter == 'has':
                order_filter &= Q(divi_tracking_number__isnull=False) & ~Q(divi_tracking_number='')
            elif divi_tracking_filter == 'none':
                order_filter &= (Q(divi_tracking_number__isnull=True) | Q(divi_tracking_number=''))
        if shop_status_filter:
            order_filter &= Q(amazon_shop__shop_status=shop_status_filter)
        if masked_single_filter:
            if masked_single_filter == 'true':
                order_filter &= Q(masked_single=True)
            elif masked_single_filter == 'false':
                order_filter &= Q(masked_single=False)
        if order_id_filter:
            order_filter &= Q(amazon_order_id__icontains=order_id_filter)
        if shop_name_filter:
            order_filter &= Q(lingxing_shop__name__icontains=shop_name_filter)

        orders_queryset = AmazonOrders.objects.filter(order_filter) \
            .select_related('lingxing_shop__amazon_shop', 'amazon_shop__ops__operational_account') \
            .order_by('-purchase_date_local', 'id')

        total = orders_queryset.count()
        print(f"📊 符合筛选条件的订单总数: {total}")

        # 分页处理
        paginator = Paginator(orders_queryset, page_size)
        try:
            orders_page = paginator.page(page)
        except PageNotAnInteger:
            orders_page = paginator.page(1)
        except EmptyPage:
            orders_page = paginator.page(paginator.num_pages)

        print(f"📄 当前页: {orders_page.number}/{paginator.num_pages}, 本页订单数: {len(orders_page)}")

        # ========== 线程池并发更新核心开始 ==========
        print(f"\n{'=' * 40}")
        print(f"🚀 开始线程池并发更新 DIVI 状态（本页 {len(orders_page)} 条）")
        print(f"{'=' * 40}")

        # 准备有效订单列表
        valid_orders = []
        for order in orders_page:
            if not order.lingxing_shop or not order.lingxing_shop.amazon_shop:
                continue
            divi_shop_id = order.lingxing_shop.amazon_shop.divi_shop_id
            if not divi_shop_id:
                continue
            valid_orders.append({
                'order': order,
                'amazon_order_id': order.amazon_order_id,
                'divi_shop_id': divi_shop_id
            })

        updated_count = 0
        if valid_orders:
            from concurrent.futures import ThreadPoolExecutor, as_completed

            def query_divi_single(item):
                try:
                    amazon_order_id = item['amazon_order_id']
                    divi_shop_id = item['divi_shop_id']
                    exists, divi_orders, _ = query_divi_order(
                        amazon_order_id=amazon_order_id,
                        brand_id=divi_shop_id,
                        has_logistics=False
                    )
                    divi_data = divi_orders[0] if exists and divi_orders else None
                    return item['order'], amazon_order_id, exists, divi_data
                except Exception as e:
                    print(f"   ❌ 查询异常 {item['amazon_order_id']}: {str(e)}")
                    return item['order'], item['amazon_order_id'], False, None

            # 使用线程池并发查询（最大并发50，防止打爆DIVI接口）
            objects_to_update = []
            with ThreadPoolExecutor(max_workers=30) as executor:
                future_to_order = {executor.submit(query_divi_single, item): item for item in valid_orders}
                for future in as_completed(future_to_order):
                    order, amazon_order_id, exists, divi_data = future.result()
                    old_status = order.is_exported_to_divi

                    if exists and divi_data:
                        update_divi_order_fields(order, divi_data)
                        print(f"   ✅ 更新字段 {amazon_order_id}")
                    else:
                        print(f"   ⏭️ 不存在于DIVI {amazon_order_id}")

                    order.is_exported_to_divi = exists
                    if old_status != exists:
                        updated_count += 1

                    objects_to_update.append(order)

            # 批量写入数据库
            if objects_to_update:
                with transaction.atomic():
                    AmazonOrders.objects.bulk_update(
                        objects_to_update,
                        fields=[
                            'is_exported_to_divi', 'divi_order_status', 'divi_tracking_number',
                            'divi_logistics_method', 'divi_import_time', 'divi_payment_time',
                            'divi_audit_time', 'divi_dispatch_time', 'divi_shipment_time',
                            'divi_shipping_amount', 'divi_goods_payment_total'
                        ],
                        batch_size=100
                    )
                print(f"✅ 批量写入数据库完成，共更新 {updated_count} 条状态")
        else:
            print("⚠️ 本页无有效订单可更新")

        print(f"{'=' * 40}")
        print(f"线程池并发更新完成！本页更新 {updated_count} 条")
        print(f"{'=' * 40}\n")

        # ========== 返回更新后的当前页数据 ==========
        print(f"🔍 重新组装返回数据...")
        orders_data = []
        for order in orders_page:
            operator_name = ''
            group_name = ''
            if order.amazon_shop and order.amazon_shop.ops:
                operator_name = order.amazon_shop.ops.first_name or order.amazon_shop.ops.username
                if hasattr(order.amazon_shop.ops, 'operational_account') and order.amazon_shop.ops.operational_account:
                    group_name = order.amazon_shop.ops.operational_account.ops_group or ''

            shop_name = order.lingxing_shop.name if order.lingxing_shop else '未知店铺'

            orders_data.append({
                'amazon_order_id': order.amazon_order_id,
                'shop_name': shop_name,
                'operator_name': operator_name,
                'group': group_name,
                'order_status': order.order_status or '',
                'quantity': 0,  # 临时占位
                'order_total_amount': str(order.order_total_amount or '0.00'),
                'purchase_date_local': order.purchase_date_local.strftime(
                    '%Y-%m-%d %H:%M:%S') if order.purchase_date_local else '',
                'is_exported_to_divi': order.is_exported_to_divi,
                'fulfillment_channel': order.fulfillment_channel or ''
            })

        # 批量获取商品数量
        order_ids = [order.id for order in orders_page]
        if order_ids:
            quantity_map = dict(
                AmazonOrderItem.objects.filter(order_id__in=order_ids)
                .values('order_id')
                .annotate(total_quantity=Sum('quantity_ordered'))
                .values_list('order_id', 'total_quantity')
            )
        else:
            quantity_map = {}

        for order_data in orders_data:
            corresponding_order = next((o for o in orders_page if o.amazon_order_id == order_data['amazon_order_id']),
                                       None)
            if corresponding_order:
                order_data['quantity'] = quantity_map.get(corresponding_order.id, 0)

        print(f"✅ 返回数据准备完成，共 {len(orders_data)} 条")
        print(f"{'=' * 60}\n")

        return JsonResponse({
            'success': True,
            'message': f'批量更新完成，共更新 {updated_count} 条订单状态',
            'updated_count': updated_count,
            'data': {
                'orders': orders_data,
                'total': total,
                'page': orders_page.number,
                'page_size': page_size,
                'total_pages': paginator.num_pages
            }
        })

    except Exception as e:
        print(f"\n{'=' * 60}")
        print(f"❌ 批量更新DIVI状态API异常: {str(e)}")
        import traceback
        traceback.print_exc()
        print(f"{'=' * 60}\n")
        return JsonResponse({
            'success': False,
            'message': f'服务器错误: {str(e)}'
        }, status=500)


@csrf_exempt
@login_required
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

    # ✅ 修改1：优化日志辅助函数（自动获取店铺名称）
    def log_shipment(success, message, logistics=None, tracking=None):
        """记录发货日志的辅助函数"""
        try:
            # 从order对象获取店铺名称
            shop_name = order.lingxing_shop.name if order and order.lingxing_shop else '未知'
            record = f"店铺[{shop_name}]订单[{amazon_order_id}]发货: "
            if success:
                record += f"成功 - 物流[{logistics}], 跟踪号[{tracking}]"
            else:
                record += f"失败 - {message}"
            # 截断到250字符，预留5字符给"..."（因为CharField最大255）
            if len(record) > 250:
                record = record[:247] + "..."

            UserOperationLog.objects.create(
                user=request.user,
                operation_type=UserOperationLog.ORDER_SHIP,
                operation_record=record,
            )
        except Exception as log_error:
            print(f"❌ 日志记录失败: {log_error}")

    if not sid or not amazon_order_id:
        # ✅ 修改2：记录失败日志
        log_shipment(False, "缺少sid或order_id")
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
            # ✅ 修改3：记录失败日志
            log_shipment(False, "未找到对应订单")
            return JsonResponse({
                "success": False,
                "message": "未找到对应订单（请检查 sid 与 order_id）"
            })

        # ========== ⭐ 核心业务验证（防止绕过前端）⭐ ==========

        # 验证1：订单状态必须是 Unshipped
        if order.order_status != 'Unshipped':
            # ✅ 修改4：记录失败日志
            log_shipment(False, f"订单状态为'{order.order_status}'，不是待发货状态")
            return JsonResponse({
                "success": False,
                "message": f"订单状态为 '{order.order_status}'，不是待发货状态，无法发货"
            })

        # 验证2：必须是FBM订单
        if order.fulfillment_channel != 'MFN':
            # ✅ 修改5：记录失败日志
            log_shipment(False, f"订单类型为'{order.fulfillment_channel}'，不是FBM订单")
            return JsonResponse({
                "success": False,
                "message": f"订单类型为 '{order.fulfillment_channel}'，不是FBM订单，无法发货"
            })

        # 验证3：DIVI状态必须在允许范围内 [3,4,5]
        if order.divi_order_status not in [3, 4, 5]:
            # ✅ 修改6：记录失败日志
            log_shipment(False, f"DIVI状态未达标（当前{order.divi_order_status}）")
            return JsonResponse({
                "success": False,
                "message": f"DIVI订单状态为 '{order.divi_order_status}'，未达到可发货状态（需为排单中、生产中或已发货）"
            })

        # 验证4：物流方式不能为空
        logistics_method = (order.divi_logistics_method or "").strip()
        if not logistics_method:
            # ✅ 修改7：记录失败日志
            log_shipment(False, "DIVI物流方式为空")
            return JsonResponse({
                "success": False,
                "message": "DIVI物流方式为空，无法发货"
            })

        # 验证5：跟踪号不能为空
        tracking_number = (order.divi_tracking_number or "").strip()
        if not tracking_number:
            # ✅ 修改8：记录失败日志
            log_shipment(False, "DIVI跟踪号为空")
            return JsonResponse({
                "success": False,
                "message": "DIVI跟踪号为空，无法发货"
            })

        # 验证6：店铺状态检查
        if not order.amazon_shop or order.amazon_shop.shop_status != '正常':
            current_status = order.amazon_shop.shop_status if order.amazon_shop else '未知'
            # ✅ 修改9：记录失败日志
            log_shipment(False, f"店铺状态为'{current_status}'")
            return JsonResponse({
                "success": False,
                "message": f"店铺状态为 '{current_status}'，无法执行发货操作"
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

        # ✅ 修改10：记录成功日志
        log_shipment(True, "成功", logistics_method, tracking_number)

        return JsonResponse({
            "success": True,
            "message": f"订单 {amazon_order_id} 发货流程已执行"
        })

    except Exception as e:
        error_msg = f"发货异常：{str(e)}"
        # ✅ 修改11：记录异常日志
        log_shipment(False, f"异常：{str(e)[:100]}")
        return JsonResponse({
            "success": False,
            "message": error_msg
        })


@csrf_exempt
@login_required
def api_mark_real_shipment(request):
    """
    将假面单发货的订单标注为"真发"
    条件：masked_single == True
    动作：masked_single 置为 False
    前端传参：sid, order_id (amazon_order_id)
    """
    if request.method != "POST":
        return JsonResponse({"success": False, "message": "只支持 POST 请求"})

    try:
        data = json.loads(request.body.decode())
    except Exception:
        return JsonResponse({"success": False, "message": "请求体必须为 JSON"})

    sid = data.get("sid")
    amazon_order_id = data.get("order_id")

    # ✅ 修改1：优化日志辅助函数（自动获取店铺名称）
    def log_mark_real(success, message):
        """记录标注真发日志的辅助函数"""
        try:
            # 从order对象获取店铺名称
            shop_name = order.lingxing_shop.name if order and order.lingxing_shop else '未知'
            record = f"店铺[{shop_name}]订单[{amazon_order_id}]标注真发: "
            record += "成功 - 取消假面单标记" if success else f"失败 - {message}"
            # 截断处理
            if len(record) > 250:
                record = record[:247] + "..."

            UserOperationLog.objects.create(
                user=request.user,
                operation_type=UserOperationLog.ORDER_MARK_REAL,
                operation_record=record,
            )
        except Exception as log_error:
            print(f"❌ 日志记录失败: {log_error}")

    if not sid or not amazon_order_id:
        # ✅ 修改2：记录失败日志
        log_mark_real(False, "缺少sid或order_id")
        return JsonResponse({"success": False, "message": "缺少 sid 或 order_id"})

    try:
        order = AmazonOrders.objects.select_related("lingxing_shop").get(
            amazon_order_id=amazon_order_id,
            lingxing_shop__sid=sid,
        )
    except AmazonOrders.DoesNotExist:
        # ✅ 修改3：记录失败日志
        log_mark_real(False, "未找到对应订单")
        return JsonResponse({
            "success": False,
            "message": "未找到对应订单（请检查 sid 和 order_id）"
        })

    # 只有假面单订单才允许标注真发
    if not order.masked_single:
        # ✅ 修改4：记录失败日志
        log_mark_real(False, "该订单当前不是假面单发货")
        return JsonResponse({
            "success": False,
            "message": "该订单当前不是假面单发货，无需标注真发"
        })

    # 标注为真发：把假面单标记取消
    order.masked_single = False
    order.save(update_fields=["masked_single"])

    # ✅ 修改5：记录成功日志
    log_mark_real(True, "")

    return JsonResponse({
        "success": True,
        "message": f"订单 {amazon_order_id} 已标注为真发"
    })


@login_required
def export_amazon_orders_excel(request):
    """
    导出当前筛选条件的所有订单数据到Excel
    前端传值：所有筛选条件（不需要page和page_size）
    导出所有页数据
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': '只支持POST请求'}, status=405)

    try:
        # 解析请求数据
        data = json.loads(request.body)
        user = request.user
        permissions = get_user_operation_permissions(user)

        # ========== 权限控制核心逻辑 ==========
        filter_type, filter_value = determine_filter_type_and_value(request, data, permissions)
        # ========== 权限控制结束 ==========

        # 日期参数
        date_range_option = data.get('date_range', 'yesterday')
        start_date_str = data.get('start_date', '')
        end_date_str = data.get('end_date', '')

        # 筛选项
        order_id_filter = data.get('order_id', '').strip()
        shop_name_filter = data.get('shop_name', '').strip()

        # 多选筛选条件（逗号分隔）
        shop_status_filter = data.get('shop_status', '').strip()
        shop_status_list = [s.strip() for s in shop_status_filter.split(',') if s.strip()] if shop_status_filter else []

        order_status_filter = data.get('order_status', '').strip()
        order_status_list = [s.strip() for s in order_status_filter.split(',') if s.strip()] if order_status_filter else []

        fulfillment_channel_filter = data.get('fulfillment_channel', '').strip()
        fulfillment_channel_list = [s.strip() for s in fulfillment_channel_filter.split(',') if s.strip()] if fulfillment_channel_filter else []

        divi_export_filter = data.get('divi_export', '').strip()
        divi_export_list = [s.strip() for s in divi_export_filter.split(',') if s.strip()] if divi_export_filter else []

        divi_order_status_filter = data.get('divi_order_status', '').strip()
        divi_order_status_list = [s.strip() for s in divi_order_status_filter.split(',') if s.strip()] if divi_order_status_filter else []

        divi_tracking_filter = data.get('divi_tracking', '').strip()
        divi_tracking_list = [s.strip() for s in divi_tracking_filter.split(',') if s.strip()] if divi_tracking_filter else []

        masked_single_filter = data.get('masked_single', '').strip()
        masked_single_list = [s.strip() for s in masked_single_filter.split(',') if s.strip()] if masked_single_filter else []

        shipping_deadline_filter = data.get('shipping_deadline', '').strip()
        shipping_deadline_list = [s.strip() for s in shipping_deadline_filter.split(',') if s.strip()] if shipping_deadline_filter else []

        # 解析日期范围
        current_start, current_end = None, None
        if start_date_str and end_date_str:
            try:
                current_start = datetime.strptime(start_date_str.split(' ')[0], '%Y-%m-%d').date()
                current_end = datetime.strptime(end_date_str.split(' ')[0], '%Y-%m-%d').date()
            except:
                pass

        if not current_start or not current_end:
            current_start, current_end = get_date_range_from_option(date_range_option)

        if not current_start or not current_end:
            return JsonResponse({
                'success': False,
                'message': '请提供有效的日期范围'
            }, status=400)

        # 无权限或没店铺直接返回空
        if filter_type == 'none':
            return JsonResponse({
                'success': True,
                'data': {
                    'orders': [],
                    'total': 0,
                }
            })

        # 获取店铺（权限范围内的店铺）
        shop_ids = get_shop_ids_by_filter(filter_type, filter_value)
        shop_ids_list = list(shop_ids)

        if not shop_ids_list:
            return JsonResponse({
                'success': True,
                'data': {
                    'orders': [],
                    'total': 0,
                }
            })

        # 获取LingXing店铺
        lingxing_shops = LingXingAmazonShop.objects.filter(amazon_shop_id__in=shop_ids_list)
        lingxing_shop_ids = list(lingxing_shops.values_list('sid', flat=True))

        if not lingxing_shop_ids:
            return JsonResponse({
                'success': True,
                'data': {
                    'orders': [],
                    'total': 0,
                }
            })

        # 构建订单查询条件（不分页，查询所有数据）
        order_filter = Q(lingxing_shop_id__in=lingxing_shop_ids)
        order_filter &= Q(purchase_date_local__date__gte=current_start)
        order_filter &= Q(purchase_date_local__date__lte=current_end)

        # 应用筛选项（支持多选）
        if order_status_list:
            if len(order_status_list) == 1:
                order_filter &= Q(order_status=order_status_list[0])
            else:
                order_filter &= Q(order_status__in=order_status_list)

        if fulfillment_channel_list:
            if len(fulfillment_channel_list) == 1:
                order_filter &= Q(fulfillment_channel=fulfillment_channel_list[0])
            else:
                order_filter &= Q(fulfillment_channel__in=fulfillment_channel_list)

        if divi_export_list:
            bool_values = []
            for v in divi_export_list:
                if v.lower() == 'true':
                    bool_values.append(True)
                elif v.lower() == 'false':
                    bool_values.append(False)
            if bool_values:
                if len(bool_values) == 1:
                    order_filter &= Q(is_exported_to_divi=bool_values[0])
                else:
                    order_filter &= Q(is_exported_to_divi__in=bool_values)

        if divi_order_status_list:
            status_ints = [int(s) for s in divi_order_status_list if s.isdigit()]
            if status_ints:
                if len(status_ints) == 1:
                    order_filter &= Q(divi_order_status=status_ints[0])
                else:
                    order_filter &= Q(divi_order_status__in=status_ints)

        if divi_tracking_list:
            if len(divi_tracking_list) == 1:
                if divi_tracking_list[0] == 'has':
                    order_filter &= Q(divi_tracking_number__isnull=False) & ~Q(divi_tracking_number='')
                elif divi_tracking_list[0] == 'none':
                    order_filter &= (Q(divi_tracking_number__isnull=True) | Q(divi_tracking_number=''))

        if shop_status_list:
            if len(shop_status_list) == 1:
                order_filter &= Q(amazon_shop__shop_status=shop_status_list[0])
            else:
                order_filter &= Q(amazon_shop__shop_status__in=shop_status_list)

        if masked_single_list:
            bool_values = [(v.lower() == 'true') for v in masked_single_list if v.lower() in ['true', 'false']]
            if bool_values:
                if len(bool_values) == 1:
                    order_filter &= Q(masked_single=bool_values[0])
                else:
                    order_filter &= Q(masked_single__in=bool_values)

        if order_id_filter:
            order_filter &= Q(amazon_order_id__icontains=order_id_filter)
        if shop_name_filter:
            order_filter &= Q(lingxing_shop__name__icontains=shop_name_filter)

        # 查询所有订单（不分页）
        orders_queryset = AmazonOrders.objects.filter(order_filter).select_related(
            'lingxing_shop', 'amazon_shop'
        ).only(
            'id', 'amazon_order_id', 'order_no', 'lingxing_shop', 'amazon_shop',
            'order_status', 'order_total_amount', 'purchase_date_local',
            'is_exported_to_divi', 'fulfillment_channel', 'divi_order_status',
            'divi_logistics_method', 'divi_tracking_number', 'masked_single',
            'latest_ship_date', 'divi_import_time', 'divi_payment_time',
            'divi_audit_time', 'divi_dispatch_time', 'divi_shipment_time',
            'divi_shipping_amount', 'divi_goods_payment_total'
        ).order_by('-purchase_date_local')

        # 获取所有订单（不分页）
        all_orders = list(orders_queryset)

        # 计算发货时限预警
        from django.utils import timezone
        from datetime import timedelta
        now = timezone.now()
        NON_DEADLINE_STATUSES = ['PendingAvailability', 'Pending', 'Canceled', 'Shipped']

        orders_with_deadline = []
        for order in all_orders:
            deadline_status = 'normal'
            deadline_text = ''
            hours_remaining = None

            if (order.latest_ship_date and
                    order.order_status not in NON_DEADLINE_STATUSES):
                beijing_deadline = order.latest_ship_date + timedelta(hours=16)
                time_diff = beijing_deadline - now
                hours_remaining = time_diff.total_seconds() / 3600

                if hours_remaining <= 24:
                    deadline_status = 'red'
                    deadline_text = f'[红色预警：剩余{int(hours_remaining)}小时]'
                elif hours_remaining <= 48:
                    deadline_status = 'yellow'
                    deadline_text = f'[黄色预警：剩余{int(hours_remaining)}小时]'

            # 应用发货时限筛选（支持多选）
            if shipping_deadline_list:
                has_red = 'red' in shipping_deadline_list
                has_yellow = 'yellow' in shipping_deadline_list
                has_all = 'all_deadline' in shipping_deadline_list

                if has_red and has_yellow or has_all:
                    if deadline_status not in ['red', 'yellow']:
                        continue
                elif has_red:
                    if deadline_status != 'red':
                        continue
                elif has_yellow:
                    if deadline_status != 'yellow':
                        continue

            orders_with_deadline.append({
                'order': order,
                'deadline_status': deadline_status,
                'deadline_text': deadline_text,
                'hours_remaining': hours_remaining
            })

        # 构建完整数据
        order_ids = [item['order'].id for item in orders_with_deadline]

        # 批量获取商品数量
        if order_ids:
            quantity_map = dict(
                AmazonOrderItem.objects.filter(
                    order_id__in=order_ids
                ).values('order_id').annotate(
                    total_quantity=Sum('quantity_ordered')
                ).values_list('order_id', 'total_quantity')
            )
        else:
            quantity_map = {}

        # 准备Excel数据
        wb = Workbook()
        ws = wb.active
        ws.title = "亚马逊订单数据"

        # 定义表头
        headers = [
            '订单ID', '领星订单号', '店铺名称', '店铺状态',
            '运营分组', '运营人员', '订单状态', '订单类型',
            '商品数量', '订单金额', '下单时间',
            '发货时限', 'DIVI导单状态', 'DIVI订单状态',
            'DIVI物流方式', 'DIVI跟踪号', '假面单发货',
            'DIVI导入时间', 'DIVI付款时间', 'DIVI审核时间',
            'DIVI派单时间', 'DIVI发货时间', 'DIVI运费',
            'DIVI货款总计'
        ]

        # 设置表头样式
        header_fill = PatternFill(start_color="366092", end_color="366092", fill_type="solid")
        header_font = Font(color="FFFFFF", bold=True)
        for col_idx, header in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col_idx, value=header)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center", vertical="center")

        # 填充数据
        for row_idx, item in enumerate(orders_with_deadline, 2):
            order = item['order']

            # 获取运营信息
            operator_name = ''
            group_name = ''
            if order.amazon_shop and order.amazon_shop.ops:
                operator_name = order.amazon_shop.ops.first_name or order.amazon_shop.ops.username
                try:
                    op_account = order.amazon_shop.ops.operational_account
                    group_name = op_account.ops_group if op_account else ''
                except:
                    group_name = ''

            # 获取店铺名称和状态
            shop_name = order.lingxing_shop.name if order.lingxing_shop else '未知店铺'
            shop_status = order.amazon_shop.shop_status if order.amazon_shop else ''

            # 构建发货时限显示
            deadline_display = ''
            if order.latest_ship_date:
                deadline_display = order.latest_ship_date.strftime('%Y-%m-%d %H:%M:%S')
                if item['deadline_text']:
                    deadline_display += f" {item['deadline_text']}"

            # DIVI状态文字
            divi_status_map = {
                0: '取消订单', 1: '未付货款', 2: '未审核',
                3: '排单中', 4: '生产中', 5: '已发货'
            }
            divi_status_text = divi_status_map.get(order.divi_order_status,
                                                   '-') if order.divi_order_status is not None else '-'

            # 假面单标记
            masked_single_text = '是' if order.masked_single else '否'

            # DIVI导单状态
            divi_export_text = '已导单' if order.is_exported_to_divi else '未导单'

            # 获取商品数量
            quantity = quantity_map.get(order.id, 0)

            # 填充行数据
            row_data = [
                order.amazon_order_id or '-',
                order.order_no or '-',
                shop_name,
                shop_status or '-',
                group_name or '-',
                operator_name or '-',
                order.order_status or '-',
                order.fulfillment_channel or '-',
                quantity,
                float(order.order_total_amount or 0),
                order.purchase_date_local.strftime('%Y-%m-%d %H:%M:%S') if order.purchase_date_local else '-',
                deadline_display or '-',
                divi_export_text,
                divi_status_text,
                order.divi_logistics_method or '-',
                order.divi_tracking_number or '-',
                masked_single_text,
                order.divi_import_time.strftime('%Y-%m-%d %H:%M:%S') if order.divi_import_time else '-',
                order.divi_payment_time.strftime('%Y-%m-%d %H:%M:%S') if order.divi_payment_time else '-',
                order.divi_audit_time.strftime('%Y-%m-%d %H:%M:%S') if order.divi_audit_time else '-',
                order.divi_dispatch_time.strftime('%Y-%m-%d %H:%M:%S') if order.divi_dispatch_time else '-',
                order.divi_shipment_time.strftime('%Y-%m-%d %H:%M:%S') if order.divi_shipment_time else '-',
                float(order.divi_shipping_amount or 0),
                float(order.divi_goods_payment_total or 0)
            ]

            for col_idx, cell_value in enumerate(row_data, 1):
                ws.cell(row=row_idx, column=col_idx, value=cell_value)

        # 调整列宽
        column_widths = [20, 20, 25, 15, 15, 15, 15, 12, 10, 12, 20, 35, 12, 12, 20, 25, 12, 20, 20, 20, 20, 20, 12, 15]
        for i, width in enumerate(column_widths, 1):
            ws.column_dimensions[get_column_letter(i)].width = width

        # 生成文件名
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'亚马逊订单_{timestamp}.xlsx'

        # 将Excel写入内存
        buffer = io.BytesIO()
        wb.save(buffer)
        buffer.seek(0)

        # 创建响应
        response = HttpResponse(
            buffer.getvalue(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response['Content-Disposition'] = f'attachment; filename="{filename}"'

        return response

    except Exception as e:
        print(f"\n{'=' * 60}")
        print(f"❌ 导出Excel错误: {str(e)}")
        import traceback
        traceback.print_exc()
        print(f"{'=' * 60}\n")

        return JsonResponse({
            'success': False,
            'message': f'导出失败: {str(e)}'
        }, status=500)
