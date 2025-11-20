from django.http import JsonResponse
from django.db.models import Sum, Q
from datetime import datetime
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
import json

from django.shortcuts import render
from Amazon.models import LingXingAmazonShop, AmazonOrders, AmazonOrderItem
from Amazon.amazon_views import parse_permissions, determine_filter_type_and_value, get_shop_ids_by_filter, \
    get_date_range_from_option


@login_required(login_url='/login/')
def amazon_order_management_page(request):
    """亚马逊订单管理页面渲染"""
    theme = request.COOKIES.get('theme', 'light')
    return render(request, 'amazon_order_management.html', {
        'theme': theme,
        'active_nav': 'amazon_orders'
    })


@login_required
def get_amazon_orders_list_api(request):
    """
    获取订单列表（带分页和排序）
    支持相同的权限控制逻辑
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': '只支持POST请求'}, status=405)

    try:
        # 解析请求数据
        data = json.loads(request.body)
        user = request.user
        permissions = parse_permissions(getattr(user, 'permission', []))

        print(f"\n{'=' * 60}")
        print(f"📋 订单列表API - 用户 {user.username} 的权限: {permissions}")
        print(f"接收到的参数: {json.dumps(data, ensure_ascii=False, indent=2)}")

        # ============= 权限控制核心逻辑（使用统一函数） =============
        filter_type, filter_value = determine_filter_type_and_value(request, data, permissions)
        print(f"最终筛选条件: filter_type={filter_type}, filter_value={filter_value}")
        # ============= 权限控制结束 =============

        # 分页参数
        page = int(data.get('page', 1))
        page_size = int(data.get('page_size', 20))
        page_size = min(page_size, 100)  # 最大100条

        # 日期参数
        date_range_option = data.get('date_range', 'yesterday')
        start_date_str = data.get('start_date', '')
        end_date_str = data.get('end_date', '')

        # 订单号筛选
        order_id_filter = data.get('order_id', '').strip()

        # 店铺名称筛选（新增）
        shop_name_filter = data.get('shop_name', '').strip()

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
                    'page': page,
                    'page_size': page_size,
                    'total_pages': 0
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
                    'page': page,
                    'page_size': page_size,
                    'total_pages': 0
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
                    'page': page,
                    'page_size': page_size,
                    'total_pages': 0
                }
            })

        # 查询订单（按下单时间倒序）
        order_filter = Q(lingxing_shop_id__in=lingxing_shop_ids)
        order_filter &= Q(purchase_date_local__date__gte=current_start)
        order_filter &= Q(purchase_date_local__date__lte=current_end)

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

        # 优化：只查询需要的字段，并使用select_related减少查询次数
        orders_queryset = AmazonOrders.objects.filter(order_filter).select_related(
            'lingxing_shop', 'amazon_shop'
        ).only(
            'id', 'amazon_order_id', 'lingxing_shop', 'amazon_shop',
            'order_status', 'order_total_amount', 'purchase_date_local', 'is_exported_to_divi',
            'fulfillment_channel'
        ).order_by('-purchase_date_local')  # 倒序排列

        # 统计总数量
        total = orders_queryset.count()

        # 分页
        paginator = Paginator(orders_queryset, page_size)
        try:
            orders_page = paginator.page(page)
        except PageNotAnInteger:
            orders_page = paginator.page(1)
        except EmptyPage:
            orders_page = paginator.page(paginator.num_pages)

        # 组装订单数据
        orders_data = []
        for order in orders_page:
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

        # 批量获取商品数量（性能优化）
        order_ids = [order.id for order in orders_page]
        quantity_map = dict(
            AmazonOrderItem.objects.filter(
                order_id__in=order_ids
            ).values('order_id').annotate(
                total_quantity=Sum('quantity_ordered')
            ).values_list('order_id', 'total_quantity')
        )

        # 填充商品数量
        for order_data in orders_data:
            corresponding_order = next((o for o in orders_page if o.amazon_order_id == order_data['amazon_order_id']),
                                       None)
            if corresponding_order:
                order_data['quantity'] = quantity_map.get(corresponding_order.id, 0)

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

        print(f"✅ 返回 {len(orders_data)} 条订单，总计 {total} 条，当前页 {orders_page.number}/{paginator.num_pages}")
        print(f"{'=' * 60}\n")

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