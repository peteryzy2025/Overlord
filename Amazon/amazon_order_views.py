# Amazon/amazon_order_views.py

from django.http import JsonResponse
from django.db.models import Sum, Q
from datetime import datetime
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
import json
import time
from django.utils import timezone

from django.shortcuts import render
from Amazon.models import LingXingAmazonShop, AmazonOrders, AmazonOrderItem
from Amazon.amazon_views import parse_permissions, determine_filter_type_and_value, get_date_range_from_option,get_shop_ids_by_filter
# DIVI服务导入
from Api.divi.divi_order_service import query_divi_order
from Amazon.amazon_divi_views import update_divi_order_fields


@login_required(login_url='/login/')
def amazon_order_management_page(request):
    """亚马逊订单管理页面渲染（终极增强版）"""
    theme = request.COOKIES.get('theme', 'light')

    # 关键：加上这几行，提前加载所有订单 + 商品明细 + 店铺信息
    orders = AmazonOrders.objects.filter(
        fulfillment_channel='MFN'  # 如果你还想看AFN可以去掉这行
    ).select_related(
        'lingxing_shop',
        'amazon_shop'
    ).prefetch_related(
        'amazonorderitem_set'  # 核心：预加载所有商品明细，避免N+1
    ).order_by('-purchase_date_local')

    return render(request, 'amazon_order_management.html', {
        'theme': theme,
        'active_nav': 'amazon_orders',
        'orders': orders,  # 关键：把订单数据传给模板！
    })


@login_required
def get_amazon_orders_list_api(request):
    """
    获取订单列表（带分页和排序）
    支持相同的权限控制逻辑
    """
    if request.method != 'POST':
        print("❌ 错误: 只支持POST请求")
        return JsonResponse({'success': False, 'message': '只支持POST请求'}, status=405)

    try:
        # 解析请求数据
        data = json.loads(request.body)
        user = request.user
        permissions = parse_permissions(getattr(user, 'permission', []))

        # print(f"\n{'=' * 60}")
        # print(f"📋 订单列表API - 用户 {user.username} 的权限: {permissions}")
        # print(f"接收到的参数: {json.dumps(data, ensure_ascii=False, indent=2)}")

        # ============= 权限控制核心逻辑（使用统一函数） =============
        filter_type, filter_value = determine_filter_type_and_value(request, data, permissions)
        # print(f"🔐 权限校验结果: filter_type={filter_type}, filter_value={filter_value}")
        # ============= 权限控制结束 =============

        # 分页参数
        page = int(data.get('page', 1))
        page_size = int(data.get('page_size', 20))
        page_size = min(page_size, 100)  # 最大100条
        # print(f"📄 分页参数: page={page}, page_size={page_size}")

        # 日期参数
        date_range_option = data.get('date_range', 'yesterday')
        start_date_str = data.get('start_date', '')
        end_date_str = data.get('end_date', '')
        # print(f"📅 日期参数: date_range={date_range_option}, start={start_date_str}, end={end_date_str}")

        # 订单号筛选
        order_id_filter = data.get('order_id', '').strip()
        if order_id_filter:
            print(f"🔍 订单号筛选: {order_id_filter}")

        # 店铺名称筛选（新增）
        shop_name_filter = data.get('shop_name', '').strip()
        if shop_name_filter:
            print(f"🔍 店铺名称筛选: {shop_name_filter}")

        # ========== 新增筛选项处理 ==========
        # 1. 订单状态筛选
        order_status_filter = data.get('order_status', '').strip()
        if order_status_filter:
            print(f"🔍 订单状态筛选: {order_status_filter}")

        # 2. 订单类型筛选
        fulfillment_channel_filter = data.get('fulfillment_channel', '').strip()
        if fulfillment_channel_filter:
            print(f"🔍 订单类型筛选: {fulfillment_channel_filter}")

        # 3. DIVI导单情况筛选
        divi_export_filter = data.get('divi_export', '').strip()
        if divi_export_filter:
            print(f"🔍 DIVI导单情况筛选: {divi_export_filter}")

        # 4. DIVI订单状态筛选
        divi_order_status_filter = data.get('divi_order_status', '').strip()
        if divi_order_status_filter:
            print(f"🔍 DIVI订单状态筛选: {divi_order_status_filter}")

        # 5. DIVI是否有面单筛选
        divi_tracking_filter = data.get('divi_tracking', '').strip()
        if divi_tracking_filter:
            print(f"🔍 DIVI是否有面单筛选: {divi_tracking_filter}")
        masked_single_filter = data.get('masked_single', '').strip()
        if masked_single_filter:
            print(f"🔍 是否假面单发货筛选: {masked_single_filter}")

        current_start, current_end = None, None
        if start_date_str and end_date_str:
            try:
                current_start = datetime.strptime(start_date_str.split(' ')[0], '%Y-%m-%d').date()
                current_end = datetime.strptime(end_date_str.split(' ')[0], '%Y-%m-%d').date()
                # print(f"✅ 使用自定义日期范围: {current_start} 至 {current_end}")
            except:
                print(f"⚠️ 日期解析失败，将使用快捷选项")
                pass

        if not current_start or not current_end:
            current_start, current_end = get_date_range_from_option(date_range_option)
            # print(f"✅ 使用快捷日期范围({date_range_option}): {current_start} 至 {current_end}")

        if not current_start or not current_end:
            print("❌ 错误: 未提供有效的日期范围")
            return JsonResponse({
                'success': False,
                'message': '请提供有效的日期范围'
            }, status=400)

        # 无权限或没店铺直接返回空
        if filter_type == 'none':
            print("⚠️ 权限不足(filter_type=none)，返回空数据")
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

        # 获取店铺（权限范围内的店铺）
        # print(f"🔍 查询权限范围内的店铺...")
        shop_ids = get_shop_ids_by_filter(filter_type, filter_value)
        shop_ids_list = list(shop_ids)
        # print(f"✅ 找到 {len(shop_ids_list)} 个店铺: {shop_ids_list}")

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
        # print(f"🔍 查询LingXing店铺...")
        lingxing_shops = LingXingAmazonShop.objects.filter(amazon_shop_id__in=shop_ids_list)
        lingxing_shop_ids = list(lingxing_shops.values_list('sid', flat=True))
        # print(f"✅ 找到 {len(lingxing_shop_ids)} 个LingXing店铺: {lingxing_shop_ids}")

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

        # 查询订单（按下单时间倒序）
        # print(f"🔍 构建订单查询条件...")
        order_filter = Q(lingxing_shop_id__in=lingxing_shop_ids)
        order_filter &= Q(purchase_date_local__date__gte=current_start)
        order_filter &= Q(purchase_date_local__date__lte=current_end)
        # print(f"📋 基础查询条件: lingxing_shop_id__in={lingxing_shop_ids}, 日期={current_start}至{current_end}")

        # ========== 应用新增筛选项 ==========
        # 1. 订单状态筛选
        if order_status_filter:
            order_filter &= Q(order_status=order_status_filter)
            # print(f"📋 添加订单状态筛选: {order_status_filter}")

        # 2. 订单类型筛选
        if fulfillment_channel_filter:
            order_filter &= Q(fulfillment_channel=fulfillment_channel_filter)
            # print(f"📋 添加订单类型筛选: {fulfillment_channel_filter}")

        # 3. DIVI导单情况筛选
        if divi_export_filter:
            divi_export_bool = divi_export_filter.lower() == 'true'
            order_filter &= Q(is_exported_to_divi=divi_export_bool)
            # print(f"📋 添加DIVI导单筛选: {divi_export_bool}")

        # 4. DIVI订单状态筛选
        if divi_order_status_filter:
            order_filter &= Q(divi_order_status=int(divi_order_status_filter))
            # print(f"📋 添加DIVI订单状态筛选: {divi_order_status_filter}")

        # 5. DIVI是否有面单筛选
        if divi_tracking_filter:
            if divi_tracking_filter == 'has':
                order_filter &= Q(divi_tracking_number__isnull=False) & ~Q(divi_tracking_number='')
                # print(f"📋 添加DIVI有面单筛选")
            elif divi_tracking_filter == 'none':
                order_filter &= Q(divi_tracking_number__isnull=True) | Q(divi_tracking_number='')
                # print(f"📋 添加DIVI无面单筛选")
        # 是否假面单发货 masked_single
        if masked_single_filter:
            if masked_single_filter == 'true':
                order_filter &= Q(masked_single=True)
                # print("📋 添加筛选：仅假面单发货订单 (masked_single=True)")
            elif masked_single_filter == 'false':
                order_filter &= Q(masked_single=False)
                # print("📋 添加筛选：排除假面单，仅正常面单订单 (masked_single=False)")

        # 订单号筛选（模糊查询）
        if order_id_filter:
            # 对于非ops_all权限，需要验证订单号是否在权限范围内
            if 'ops_all' not in permissions:
                test_exists = AmazonOrders.objects.filter(
                    order_filter,
                    amazon_order_id__icontains=order_id_filter
                ).exists()

                if not test_exists:
                    print(f"⚠️ 订单号 '{order_id_filter}' 不在权限范围内或不存在")
                    return JsonResponse({
                        'success': True,
                        'data': {
                            'orders': [],
                            'total': 0,
                            'page': page,
                            'page_size': page_size,
                            'total_pages': 0,
                            'warning': '未找到符合条件的订单或权限不足'
                        }
                    })

            order_filter &= Q(amazon_order_id__icontains=order_id_filter)
            # print(f"🔍 添加订单号模糊筛选: {order_id_filter}")

        # 店铺名称筛选（模糊查询，新增）
        if shop_name_filter:
            # 对于非ops_all权限，需要验证店铺是否在权限范围内
            if 'ops_all' not in permissions:
                test_exists = AmazonOrders.objects.filter(
                    order_filter,
                    lingxing_shop__name__icontains=shop_name_filter
                ).exists()

                if not test_exists:
                    print(f"⚠️ 店铺名称 '{shop_name_filter}' 不在权限范围内或不存在")
                    return JsonResponse({
                        'success': True,
                        'data': {
                            'orders': [],
                            'total': 0,
                            'page': page,
                            'page_size': page_size,
                            'total_pages': 0,
                            'warning': '未找到符合条件的店铺或权限不足'
                        }
                    })

            order_filter &= Q(lingxing_shop__name__icontains=shop_name_filter)
            print(f"🔍 添加店铺名称模糊筛选: {shop_name_filter}")

        # 优化：只查询需要的字段，并使用select_related减少查询次数
        orders_queryset = AmazonOrders.objects.filter(order_filter).select_related(
            'lingxing_shop', 'amazon_shop'
        ).only(
            'id', 'amazon_order_id', 'lingxing_shop', 'amazon_shop',
            'order_status', 'order_total_amount', 'purchase_date_local', 'is_exported_to_divi',
            'fulfillment_channel', 'divi_order_status', 'divi_tracking_number',
            'divi_logistics_method',  # 新增
            'masked_single',  # 新增
        ).order_by('-purchase_date_local')

        # 统计总数量
        total = orders_queryset.count()
        # print(f"📊 符合筛选条件的订单总数: {total}")

        # 分页
        paginator = Paginator(orders_queryset, page_size)
        try:
            orders_page = paginator.page(page)
            # print(f"📄 分页成功: 当前页 {orders_page.number}/{paginator.num_pages}, 本页记录数: {len(orders_page)}")
        except PageNotAnInteger:
            print(f"⚠️ 页码不是整数，使用第1页")
            orders_page = paginator.page(1)
        except EmptyPage:
            print(f"⚠️ 页码超出范围，使用最后一页")
            orders_page = paginator.page(paginator.num_pages)

        # 组装订单数据
        orders_data = []
        # print(f"\n{'=' * 40}")
        # print(f"开始组装订单数据...")
        # print(f"{'=' * 40}\n")

        for idx, order in enumerate(orders_page, 1):
            # 获取运营人员信息
            operator_name = ''
            group_name = ''

            if order.amazon_shop and order.amazon_shop.ops:
                operator_name = order.amazon_shop.ops.first_name or order.amazon_shop.ops.username
                # 获取分组
                try:
                    op_account = order.amazon_shop.ops.operational_account
                    group_name = op_account.ops_group if op_account else ''
                except:
                    group_name = ''

            # 获取领星店铺名称
            shop_name = order.lingxing_shop.name if order.lingxing_shop else '未知店铺'

            order_data = {
                'amazon_order_id': order.amazon_order_id,
                'shop_name': shop_name,
                'operator_name': operator_name,
                'group': group_name,
                'order_status': order.order_status or '',
                'quantity': 0,
                'order_total_amount': str(order.order_total_amount or '0.00'),
                'purchase_date_local': order.purchase_date_local.strftime(
                    '%Y-%m-%d %H:%M:%S') if order.purchase_date_local else '',
                'is_exported_to_divi': order.is_exported_to_divi,
                'fulfillment_channel': order.fulfillment_channel or '',
                'divi_order_status': order.divi_order_status,  # 返回DIVI订单状态给前端
                'sid': order.lingxing_shop.sid if order.lingxing_shop else None,
                'divi_shop_id': order.lingxing_shop.amazon_shop.divi_shop_id if order.lingxing_shop and order.lingxing_shop.amazon_shop else None,
                'divi_logistics_method': order.divi_logistics_method or '',
                'divi_tracking_number': order.divi_tracking_number or '',
                'masked_single': order.masked_single,

            }

            orders_data.append(order_data)
            # print(f"【{idx}/{len(orders_page)}】订单: {order.amazon_order_id}")
            # print(f"   - 店铺: {shop_name}, 运营: {operator_name} ({group_name})")
            # print(f"   - 状态: {order.order_status}, 金额: {order.order_total_amount}")
            # print(
            #     f"   - DIVI状态: {'已导出' if order.is_exported_to_divi else '未导出'}, 渠道: {order.fulfillment_channel}")

        # 批量获取商品数量（性能优化）
        order_ids = [order.id for order in orders_page]
        # print(f"\n🔍 批量查询商品数量，订单ID: {order_ids}")

        if order_ids:
            quantity_map = dict(
                AmazonOrderItem.objects.filter(
                    order_id__in=order_ids
                ).values('order_id').annotate(
                    total_quantity=Sum('quantity_ordered')
                ).values_list('order_id', 'total_quantity')
            )
            # print(f"✅ 商品数量查询完成: {quantity_map}")
        else:
            quantity_map = {}
            print("⚠️ 订单ID列表为空")

        # 填充商品数量
        for order_data in orders_data:
            corresponding_order = next((o for o in orders_page if o.amazon_order_id == order_data['amazon_order_id']),
                                       None)
            if corresponding_order:
                qty = quantity_map.get(corresponding_order.id, 0)
                order_data['quantity'] = qty
                # print(f"   - 订单 {order_data['amazon_order_id']}: 商品数量={qty}")

        # print(f"\n✅ 订单数据组装完成，共 {len(orders_data)} 条")
        # print(f"{'=' * 60}\n")

        response_data = {
            'success': True,
            'data': {
                'orders': orders_data,
                'total': total,
                'page': orders_page.number,
                'page_size': page_size,
                'total_pages': paginator.num_pages
            }
        }

        return JsonResponse(response_data)

    except Exception as e:
        print(f"\n{'=' * 60}")
        print(f"❌ 订单列表API错误: {str(e)}")
        import traceback
        traceback.print_exc()
        print(f"{'=' * 60}\n")

        return JsonResponse({
            'success': False,
            'message': f'服务器错误: {str(e)}'
        }, status=500)


# ========== 新增辅助函数 ==========

def parse_divi_time(time_str):
    """解析DIVI时间字符串为Django DateTimeField"""
    if not time_str:
        return None
    try:
        dt = datetime.strptime(time_str, '%Y-%m-%d %H:%M:%S')
        return timezone.make_aware(dt)
    except:
        return None


@login_required
def update_divi_export_status_api(request):
    """
    批量更新订单的DIVI导出状态
    根据当前筛选条件查询订单，检查每个订单在DIVI中的存在性
    如果存在，更新所有DIVI字段和商品明细
    """
    if request.method != 'POST':
        print("❌ 错误: 只支持POST请求")
        return JsonResponse({'success': False, 'message': '只支持POST请求'}, status=405)

    try:
        data = json.loads(request.body)
        user = request.user
        permissions = parse_permissions(getattr(user, 'permission', []))

        print(f"\n{'=' * 60}")
        print(f"🔄 批量更新DIVI状态API - 用户: {user.username} (权限: {permissions})")
        print(f"📋 接收参数: {json.dumps(data, ensure_ascii=False, indent=2)}")

        # ============= 权限控制核心逻辑（使用统一函数） =============
        filter_type, filter_value = determine_filter_type_and_value(request, data, permissions)
        print(f"🔐 权限校验结果: filter_type={filter_type}, filter_value={filter_value}")
        # ============= 权限控制结束 =============

        # 解析日期参数
        date_range_option = data.get('date_range', 'yesterday')
        start_date_str = data.get('start_date', '')
        end_date_str = data.get('end_date', '')

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
        print(f"✅ 找到 {len(shop_ids_list)} 个AmazonShop: {shop_ids_list}")

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

        # 查询需要更新的订单
        print(f"🔍 构建订单查询条件...")
        order_filter = Q(lingxing_shop_id__in=lingxing_shop_ids)
        order_filter &= Q(purchase_date_local__date__gte=current_start)
        order_filter &= Q(purchase_date_local__date__lte=current_end)
        print(f"📋 查询条件: lingxing_shop_id__in={lingxing_shop_ids}, 日期={current_start}至{current_end}")

        orders_queryset = AmazonOrders.objects.filter(order_filter).order_by(
            '-purchase_date_local',
            'id'
        )
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

        # 批量更新DIVI导出状态
        updated_count = 0
        skipped_orders = []  # 记录未更新的订单及原因
        processed_orders = []  # 记录处理过的订单

        print(f"\n{'=' * 40}")
        print(f"开始逐笔更新订单DIVI状态...")
        print(f"{'=' * 40}")

        for idx, order in enumerate(orders_page, 1):
            order_id = order.amazon_order_id
            print(f"\n【{idx}/{len(orders_page)}】处理订单: {order_id}")

            try:
                # 检查关联关系链
                if not order.lingxing_shop:
                    reason = '未关联领星店铺'
                    print(f"   ⚠️ 跳过: {reason}")
                    skipped_orders.append({
                        'order_id': order_id,
                        'reason': reason
                    })
                    continue

                if not order.lingxing_shop.amazon_shop:
                    reason = '领星店铺未绑定本地AmazonShop'
                    print(f"   ⚠️ 跳过: {reason}")
                    skipped_orders.append({
                        'order_id': order_id,
                        'reason': reason
                    })
                    continue

                divi_shop_id = order.lingxing_shop.amazon_shop.divi_shop_id
                print(f"   🔍 店铺配置: divi_shop_id={divi_shop_id}")

                if not divi_shop_id:
                    reason = '本地店铺未配置divi_shop_id'
                    print(f"   ⚠️ 跳过: {reason}")
                    skipped_orders.append({
                        'order_id': order_id,
                        'reason': reason
                    })
                    continue

                # ✅ 查询DIVI订单是否存在（包含完整数据）
                print(f"   🔍 查询DIVI系统...")
                exists, divi_orders, _ = query_divi_order(
                    amazon_order_id=order_id,
                    brand_id=divi_shop_id,
                    has_logistics=False
                )
                print(f"   📊 DIVI查询结果: exists={exists}")

                # ✅ 关键修改：如果存在，更新所有DIVI字段和商品明细
                if exists and divi_orders:
                    print(f"   📦 订单存在于DIVI，准备更新所有字段...")
                    update_divi_order_fields(order, divi_orders[0])
                    print(f"   ✅ 已更新订单 {order_id} 的所有DIVI字段和商品明细")
                    status_changed = not order.is_exported_to_divi
                else:
                    status_changed = False
                    print(f"   ⏭️ 订单不存在于DIVI，仅更新状态为False")

                # 更新主状态字段
                old_status = order.is_exported_to_divi
                order.is_exported_to_divi = exists
                order.save(update_fields=['is_exported_to_divi'])

                updated_count += 1
                processed_orders.append({
                    'order_id': order_id,
                    'old_status': old_status,
                    'new_status': exists,
                    'changed': status_changed or (old_status != exists)
                })

            except Exception as e:
                reason = f'查询异常: {str(e)}'
                print(f"   ❌ 异常: {reason}")
                skipped_orders.append({
                    'order_id': order_id,
                    'reason': reason
                })
                continue

        print(f"\n{'=' * 40}")
        print(f"批量更新完成总结:")
        print(f"   - 成功处理: {updated_count} 条")
        print(f"   - 跳过处理: {len(skipped_orders)} 条")
        print(f"   - 状态变化: {sum(1 for p in processed_orders if p['changed'])} 条")
        print(f"{'=' * 40}\n")

        if skipped_orders:
            print(f"⚠️ 跳过的订单详情:")
            for skip in skipped_orders:
                print(f"   - {skip['order_id']}: {skip['reason']}")

        # 重新查询更新后的数据并组装返回
        print(f"🔍 重新查询更新后的订单数据...")
        orders_data = []
        for order in orders_page:
            operator_name = ''
            group_name = ''

            if order.amazon_shop and order.amazon_shop.ops:
                operator_name = order.amazon_shop.ops.first_name or order.amazon_shop.ops.username
                try:
                    op_account = order.amazon_shop.ops.operational_account
                    group_name = op_account.ops_group if op_account else ''
                except:
                    group_name = ''

            shop_name = order.lingxing_shop.name if order.lingxing_shop else '未知店铺'

            orders_data.append({
                'amazon_order_id': order.amazon_order_id,
                'shop_name': shop_name,
                'operator_name': operator_name,
                'group': group_name,
                'order_status': order.order_status or '',
                'quantity': 0,
                'order_total_amount': str(order.order_total_amount or '0.00'),
                'purchase_date_local': order.purchase_date_local.strftime(
                    '%Y-%m-%d %H:%M:%S') if order.purchase_date_local else '',
                'is_exported_to_divi': order.is_exported_to_divi,
                'fulfillment_channel': order.fulfillment_channel or ''
            })

        # 批量获取商品数量
        order_ids = [order.id for order in orders_page]
        print(f"🔍 批量查询商品数量，订单ID列表: {order_ids}")

        if order_ids:
            quantity_map = dict(
                AmazonOrderItem.objects.filter(
                    order_id__in=order_ids
                ).values('order_id').annotate(
                    total_quantity=Sum('quantity_ordered')
                ).values_list('order_id', 'total_quantity')
            )
            print(f"✅ 商品数量查询完成，结果: {quantity_map}")
        else:
            quantity_map = {}
            print("⚠️ 订单ID列表为空，跳过商品数量查询")

        # 填充商品数量
        for order_data in orders_data:
            corresponding_order = next((o for o in orders_page if o.amazon_order_id == order_data['amazon_order_id']),
                                       None)
            if corresponding_order:
                qty = quantity_map.get(corresponding_order.id, 0)
                order_data['quantity'] = qty
                print(f"   - 订单 {order_data['amazon_order_id']}: 商品数量={qty}")

        print(f"\n✅ 准备返回数据: 共 {len(orders_data)} 条订单")
        print(f"{'=' * 60}\n")

        return JsonResponse({
            'success': True,
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
