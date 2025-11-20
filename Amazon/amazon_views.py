# Amazon/amazon_views.py
from django.http import JsonResponse
from django.db.models import Sum, Count, Q
from django.db.models.functions import TruncDate
from datetime import datetime, timedelta
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
import json

from django.shortcuts import render

# 模型导入
from General.models import User, AmazonShop, OperationalAccount
from Amazon.models import LingXingAmazonShop, AmazonOrders, AmazonOrderItem

# DIVI服务导入
from Api.divi.divi_order_service import query_divi_order


@login_required(login_url='/login/')
def amazon_dashboard_page(request):
    """Amazon驾驶舱页面渲染"""
    theme = request.COOKIES.get('theme', 'light')
    return render(request, 'amazon_dashboard.html', {
        'theme': theme,
        'active_nav': 'amazon'
    })


def get_date_range_from_option(date_range_option):
    """
    根据快捷选项获取日期范围
    返回: (start_date, end_date) 日期对象
    """
    today = datetime.now().date()

    if date_range_option == 'today':
        return today, today
    elif date_range_option == 'yesterday':
        yesterday = today - timedelta(days=1)
        return yesterday, yesterday
    elif date_range_option == 'last7days':
        # 包含今天，共7天
        start = today - timedelta(days=6)
        return start, today
    elif date_range_option == 'last30days':
        # 包含今天，共30天
        start = today - timedelta(days=29)
        return start, today
    else:
        return None, None


def get_previous_period(start_date, end_date):
    """
    计算同期日期范围（往前推相同天数）
    """
    days = (end_date - start_date).days + 1
    previous_start = start_date - timedelta(days=days)
    previous_end = end_date - timedelta(days=days)
    return previous_start, previous_end


def get_order_statistics(lingxing_shop_ids, start_date, end_date):
    """
    核心函数：计算指定店铺和日期范围的统计数据
    返回包含所有6个指标的字典
    """
    # 日期筛选
    order_filter = Q(lingxing_shop_id__in=lingxing_shop_ids)
    order_filter &= Q(purchase_date_local__date__gte=start_date)
    order_filter &= Q(purchase_date_local__date__lte=end_date)

    # 性能优化：只查询需要的字段
    orders = AmazonOrders.objects.filter(order_filter).only(
        'amazon_order_id', 'order_total_amount', 'fulfillment_channel'
    )

    order_count = orders.count()

    if order_count == 0:
        return {
            'order_count': 0,
            'total_sales_quantity': 0,
            'total_revenue': 0.0,
            'avg_order_value': 0.0,
            'fba_count': 0,
            'fbm_count': 0,
            'fba_percentage': '0.0%',
            'fbm_percentage': '0.0%',
        }

    # 修复1：使用订单自增ID（不是amazon_order_id）关联查询，解决模型结构变更问题
    order_ids = list(orders.values_list('id', flat=True))

    # 修复2：使用正确的关联字段查询订单明细，大幅提升性能
    quantity_agg = AmazonOrderItem.objects.filter(
        order_id__in=order_ids  # 关联的是AmazonOrders.id（自增主键）
    ).aggregate(total_quantity=Sum('quantity_ordered'))
    total_sales_quantity = quantity_agg['total_quantity'] or 0

    # 计算营业额
    revenue_agg = orders.aggregate(total_revenue=Sum('order_total_amount'))
    total_revenue = float(revenue_agg['total_revenue'] or 0)

    # 计算客单价（营业额/订单量）
    avg_order_value = total_revenue / order_count if order_count > 0 else 0

    # 计算FBA和FBM（保持逻辑不变）
    fulfillment_stats = orders.values('fulfillment_channel').annotate(
        count=Count('fulfillment_channel')
    )

    fba_count = 0
    fbm_count = 0
    for stat in fulfillment_stats:
        channel = stat['fulfillment_channel']
        count = stat['count']
        if channel == 'AFN':
            fba_count = count
        elif channel == 'MFN':
            fbm_count = count

    # 计算占比
    fba_percentage = (fba_count / order_count * 100) if order_count > 0 else 0
    fbm_percentage = (fbm_count / order_count * 100) if order_count > 0 else 0

    return {
        'order_count': order_count,
        'total_sales_quantity': total_sales_quantity,
        'total_revenue': round(total_revenue, 2),
        'avg_order_value': round(avg_order_value, 2),
        'fba_count': fba_count,
        'fbm_count': fbm_count,
        'fba_percentage': f"{fba_percentage:.1f}%",
        'fbm_percentage': f"{fbm_percentage:.1f}%",
    }


def calculate_change_rate(current, previous):
    """
    计算环比变化率
    返回: "+12.3%" 或 "-8.5%" 或 "0.0%"
    """
    if previous == 0:
        return "+100.0%" if current > 0 else "0.0%"

    change = ((current - previous) / previous) * 100
    sign = "+" if change >= 0 else ""
    return f"{sign}{change:.1f}%"


def calculate_all_change_rates(current_stats, previous_stats):
    """计算所有指标的环比变化率"""
    comparison = {}

    # 数值型指标
    numeric_keys = ['order_count', 'total_sales_quantity', 'total_revenue', 'avg_order_value']
    for key in numeric_keys:
        comparison[f'{key}_change'] = calculate_change_rate(
            current_stats[key], previous_stats[key]
        )

    # 百分比指标（去掉%号）
    pct_keys = ['fba_percentage', 'fbm_percentage']
    for key in pct_keys:
        current_val = float(current_stats[key].rstrip('%'))
        previous_val = float(previous_stats[key].rstrip('%'))
        comparison[f'{key}_change'] = calculate_change_rate(current_val, previous_val)

    print("\n环比变化率:")
    for key, value in comparison.items():
        print(f"  {key}: {value}")

    return comparison


def get_shop_ids_by_filter(filter_type, filter_value):
    """
    根据筛选类型获取AmazonShop的ID列表（支持权限控制）
    Args:
        filter_type: 'ops_id', 'ops_group', 'all', 'none'
        filter_value: 对应的值
    Returns:
        QuerySet: AmazonShop的ID列表
    """
    if filter_type == 'ops_id':
        print(f"按运营ID筛选: ops_id={filter_value}")
        return AmazonShop.objects.filter(ops_id=filter_value).values_list('id', flat=True)

    elif filter_type == 'ops_group':
        print(f"查询分组 '{filter_value}' 的成员...")
        user_ids = OperationalAccount.objects.filter(
            ops_group=filter_value
        ).values_list('user_id', flat=True)

        user_ids_list = list(user_ids)
        print(f"✅ 找到用户ID: {user_ids_list}")

        if user_ids_list:
            shop_ids = AmazonShop.objects.filter(
                ops_id__in=user_ids_list
            ).values_list('id', flat=True)
            print(f"✅ 找到店铺ID: {list(shop_ids)}")
            return shop_ids
        else:
            print(f"⚠️ 分组 '{filter_value}' 没有成员")
            return AmazonShop.objects.none().values_list('id', flat=True)

    elif filter_type == 'all':
        print("查询所有AmazonShop")
        return AmazonShop.objects.all().values_list('id', flat=True)

    elif filter_type == 'none':
        print("⚠️ 权限不足，返回空QuerySet")
        return AmazonShop.objects.none().values_list('id', flat=True)

    else:
        print(f"⚠️ 未知的筛选类型: {filter_type}")
        return AmazonShop.objects.none().values_list('id', flat=True)


def get_sales_trend_data(lingxing_shop_ids):
    """
    获取最近14天每日销量数据
    返回: [{date: '2025-11-18', sales: 156}, ...] 格式
    """
    # 计算14天日期范围
    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=13)

    print(f"\n{'=' * 60}")
    print("📈 计算销量趋势数据...")
    print(f"统计日期范围: {start_date} 至 {end_date}")

    if not lingxing_shop_ids:
        print("⚠️ 没有店铺数据，返回空趋势数据")
        return []

    # 性能优化：使用更高效的查询，避免N+1问题
    daily_sales_raw = AmazonOrderItem.objects.filter(
        order__lingxing_shop_id__in=lingxing_shop_ids,
        order__purchase_date_local__date__gte=start_date,
        order__purchase_date_local__date__lte=end_date
    ).values(
        date=TruncDate('order__purchase_date_local')
    ).annotate(
        sales=Sum('quantity_ordered')
    ).order_by('date')

    # 将查询结果转换为字典 {date: sales}
    sales_dict = {}
    for item in daily_sales_raw:
        date_obj = item['date']
        sales_dict[date_obj] = item['sales'] or 0

    print(f"查询到 {len(sales_dict)} 天的销量数据")

    # 组装14天完整数据（补全缺失日期）
    result = []
    for i in range(14):
        date = start_date + timedelta(days=i)
        sales = sales_dict.get(date, 0)
        result.append({
            'date': date.strftime('%Y-%m-%d'),
            'sales': sales
        })

    print(f"✅ 返回 {len(result)} 天的完整销量数据")
    print(f"{'=' * 60}\n")

    return result


@login_required
def filter_amazon_data_api(request):
    """
    筛选亚马逊订单数据（带严格权限控制）
    权限:
      - ops_all: 可使用前端传递的任意筛选条件
      - ops_group: 只能查询自己分组的数据（忽略前端传递的无效参数）
      - ops: 只能查询自己的数据
      - 无权限: 直接返回空数据

    优先级：先判断分组，再判断人员
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': '只支持POST请求'}, status=405)

    try:
        # 解析请求数据
        data = json.loads(request.body)
        user = request.user
        permissions = getattr(user, 'permission', []) or []
        if isinstance(permissions, str):
            permissions = [permissions]

        print(f"\n{'=' * 60}")
        print(f"用户 {user.username} 的权限: {permissions}")
        print(f"接收到的原始参数: {json.dumps(data, ensure_ascii=False, indent=2)}")

        # ============= 权限控制核心逻辑 =============
        filter_type = None
        filter_value = None

        # 权限1: ops_all - 信任并使用前端传递的筛选参数
        if 'ops_all' in permissions:
            print("✅ 权限校验通过: ops_all，使用前端传递的筛选参数")

            # 解析前端传递的筛选参数
            ops_id_raw = data.get('operator_id') or data.get('ops_id')
            ops_group_raw = data.get('group') or data.get('ops_group')

            # 优先级：先判断分组，再判断人员
            # 关键修复：同时检查 'all' 和 '全部分组' 这两个特殊值
            if ops_group_raw and ops_group_raw not in ['all', '全部分组']:
                # 优先使用分组筛选（优先级更高）
                filter_type = 'ops_group'
                filter_value = ops_group_raw.strip()
            elif ops_id_raw and ops_id_raw not in ['all', '全部人员']:
                # 其次使用人员筛选
                filter_type = 'ops_id'
                filter_value = int(ops_id_raw)
            else:
                # 前端选择了"全部"选项
                filter_type = 'all'
                filter_value = None

        # 权限2: ops_group - 强制查询自己分组，忽略前端无效参数
        elif 'ops_group' in permissions:
            print("✅ 权限校验通过: ops_group，强制查询自己分组")

            # 获取当前用户的分组
            try:
                ops_account = user.operational_account
                user_group = ops_account.ops_group if ops_account else None

                if user_group:
                    filter_type = 'ops_group'
                    filter_value = user_group
                else:
                    print("⚠️ 用户未配置运营分组，返回空数据")
                    filter_type = 'none'
            except:
                print("⚠️ 用户未配置运营分组，返回空数据")
                filter_type = 'none'

        # 权限3: ops - 强制查询自己，忽略前端任何参数
        elif 'ops' in permissions:
            print("✅ 权限校验通过: ops，强制查询自己")
            filter_type = 'ops_id'
            filter_value = user.id

        # 无权限: 直接返回空数据
        else:
            print("❌ 权限校验失败: 用户无任何运营权限，返回空数据")
            filter_type = 'none'

        print(f"最终确定的筛选条件: filter_type={filter_type}, filter_value={filter_value}")
        print(f"{'=' * 60}\n")
        # ============= 权限控制结束 =============

        # 处理日期参数（保持不变）
        date_range_option = data.get('date_range', '')
        start_date_str = data.get('start_date', '')
        end_date_str = data.get('end_date', '')

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
                'message': '请提供有效的日期范围或选择日期快捷选项'
            }, status=400)

        previous_start, previous_end = get_previous_period(current_start, current_end)

        # 筛选店铺（保持不变）
        if filter_type == 'none':
            return assemble_response_data(
                filter_type='none',
                filter_value=None,
                current_start=current_start,
                current_end=current_end,
                previous_start=previous_start,
                previous_end=previous_end,
                shop_count=0,
                lingxing_shop_count=0,
                trend_data=[]
            )

        shop_ids = get_shop_ids_by_filter(filter_type, filter_value)
        shop_ids_list = list(shop_ids)
        shop_count = len(shop_ids_list)

        if shop_count == 0:
            return assemble_response_data(
                filter_type=filter_type,
                filter_value=filter_value,
                current_start=current_start,
                current_end=current_end,
                previous_start=previous_start,
                previous_end=previous_end,
                shop_count=0,
                lingxing_shop_count=0,
                trend_data=[]
            )

        # 获取LingXing店铺ID
        lingxing_shops = LingXingAmazonShop.objects.filter(amazon_shop_id__in=shop_ids_list)
        lingxing_shop_ids = list(lingxing_shops.values_list('sid', flat=True))
        lingxing_shop_count = len(lingxing_shop_ids)

        # 计算统计数据
        current_stats = get_order_statistics(lingxing_shop_ids, current_start, current_end)
        previous_stats = get_order_statistics(lingxing_shop_ids, previous_start, previous_end)
        comparison = calculate_all_change_rates(current_stats, previous_stats)
        trend_data = get_sales_trend_data(lingxing_shop_ids)

        return assemble_and_print_response(
            current_stats, previous_stats, comparison, trend_data,
            filter_type, filter_value, current_start, current_end,
            previous_start, previous_end, shop_count, lingxing_shop_count
        )

    except Exception as e:
        print(f"\n{'=' * 60}")
        print(f"❌ 错误发生: {str(e)}")
        import traceback
        traceback.print_exc()
        print(f"{'=' * 60}\n")

        return JsonResponse({
            'success': False,
            'message': f'服务器错误: {str(e)}',
            'debug_info': {
                'error_type': type(e).__name__,
                'error_detail': str(e)
            }
        }, status=500)


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
        permissions = getattr(user, 'permission', []) or []
        if isinstance(permissions, str):
            permissions = [permissions]

        print(f"\n{'=' * 60}")
        print(f"📋 订单列表API - 用户 {user.username} 的权限: {permissions}")
        print(f"接收到的参数: {json.dumps(data, ensure_ascii=False, indent=2)}")

        # ============= 权限控制核心逻辑（复用） =============
        filter_type = None
        filter_value = None

        if 'ops_all' in permissions:
            print("✅ 权限校验通过: ops_all")
            ops_id_raw = data.get('operator_id') or data.get('ops_id')
            ops_group_raw = data.get('group') or data.get('ops_group')

            if ops_group_raw and ops_group_raw not in ['all', '全部分组']:
                filter_type = 'ops_group'
                filter_value = ops_group_raw.strip()
            elif ops_id_raw and ops_id_raw not in ['all', '全部人员']:
                filter_type = 'ops_id'
                filter_value = int(ops_id_raw)
            else:
                filter_type = 'all'
        elif 'ops_group' in permissions:
            print("✅ 权限校验通过: ops_group")
            try:
                ops_account = user.operational_account
                user_group = ops_account.ops_group if ops_account else None
                if user_group:
                    filter_type = 'ops_group'
                    filter_value = user_group
                else:
                    filter_type = 'none'
            except:
                filter_type = 'none'
        elif 'ops' in permissions:
            print("✅ 权限校验通过: ops")
            filter_type = 'ops_id'
            filter_value = user.id
        else:
            print("❌ 权限校验失败: 无权限")
            filter_type = 'none'

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

        # 获取店铺
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

        # 优化：只查询需要的字段，并使用select_related减少查询次数
        orders_queryset = AmazonOrders.objects.filter(order_filter).select_related(
            'lingxing_shop', 'amazon_shop'
        ).only(
            'id', 'amazon_order_id', 'lingxing_shop', 'amazon_shop',
            'order_status', 'order_total_amount', 'purchase_date_local', 'is_exported_to_divi'
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
                'quantity': 0,  # 暂时为0，后续可以优化
                'order_total_amount': str(order.order_total_amount or '0.00'),
                'purchase_date_local': order.purchase_date_local.strftime(
                    '%Y-%m-%d %H:%M:%S') if order.purchase_date_local else '',
                'is_exported_to_divi': order.is_exported_to_divi,
                'fulfillment_channel': order.fulfillment_channel or ''  # 添加这行
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
            # 找到对应的order对象获取id
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


@login_required
@login_required
def update_divi_export_status_api(request):
    """
    批量更新订单的DIVI导出状态
    根据当前筛选条件查询订单，检查每个订单在DIVI中的存在性
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': '只支持POST请求'}, status=405)

    try:
        data = json.loads(request.body)
        user = request.user
        permissions = getattr(user, 'permission', []) or []
        if isinstance(permissions, str):
            permissions = [permissions]

        print(f"\n{'=' * 60}")
        print(f"🔄 更新DIVI状态API - 用户 {user.username} 的权限: {permissions}")
        print(f"接收到的参数: {json.dumps(data, ensure_ascii=False, indent=2)}")

        # ============= 权限控制核心逻辑（复用） =============
        filter_type = None
        filter_value = None

        if 'ops_all' in permissions:
            ops_id_raw = data.get('operator_id')
            ops_group_raw = data.get('group')

            if ops_group_raw and ops_group_raw not in ['all', '全部分组']:
                filter_type = 'ops_group'
                filter_value = ops_group_raw.strip()
            elif ops_id_raw and ops_id_raw not in ['all', '全部人员']:
                filter_type = 'ops_id'
                filter_value = int(ops_id_raw)
            else:
                filter_type = 'all'
        elif 'ops_group' in permissions:
            try:
                ops_account = user.operational_account
                user_group = ops_account.ops_group if ops_account else None
                if user_group:
                    filter_type = 'ops_group'
                    filter_value = user_group
                else:
                    filter_type = 'none'
            except:
                filter_type = 'none'
        elif 'ops' in permissions:
            filter_type = 'ops_id'
            filter_value = user.id
        else:
            filter_type = 'none'

        print(f"最终筛选条件: filter_type={filter_type}, filter_value={filter_value}")
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
            except:
                pass

        if not current_start or not current_end:
            current_start, current_end = get_date_range_from_option(date_range_option)

        if not current_start or not current_end:
            return JsonResponse({
                'success': False,
                'message': '请提供有效的日期范围'
            }, status=400)

        # 分页参数
        page = int(data.get('page', 1))
        page_size = int(data.get('page_size', 20))
        page_size = min(page_size, 100)

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

        # 获取店铺
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

        # 查询需要更新的订单
        order_filter = Q(lingxing_shop_id__in=lingxing_shop_ids)
        order_filter &= Q(purchase_date_local__date__gte=current_start)
        order_filter &= Q(purchase_date_local__date__lte=current_end)

        orders_queryset = AmazonOrders.objects.filter(order_filter)

        # 统计总数量
        total = orders_queryset.count()

        # 分页处理
        paginator = Paginator(orders_queryset, page_size)
        try:
            orders_page = paginator.page(page)
        except PageNotAnInteger:
            orders_page = paginator.page(1)
        except EmptyPage:
            orders_page = paginator.page(paginator.num_pages)

        # 批量更新DIVI导出状态
        updated_count = 0
        skipped_orders = []  # 记录未更新的订单及原因

        for order in orders_page:
            order_id = order.amazon_order_id
            try:
                # 检查关联关系链
                if not order.lingxing_shop:
                    skipped_orders.append({
                        'order_id': order_id,
                        'reason': '未关联领星店铺'
                    })
                    continue

                if not order.lingxing_shop.amazon_shop:
                    skipped_orders.append({
                        'order_id': order_id,
                        'reason': '领星店铺未绑定本地AmazonShop'
                    })
                    continue

                divi_shop_id = order.lingxing_shop.amazon_shop.divi_shop_id

                if not divi_shop_id:
                    skipped_orders.append({
                        'order_id': order_id,
                        'reason': '本地店铺未配置divi_shop_id'
                    })
                    continue

                # 查询DIVI订单是否存在
                exists, _, _ = query_divi_order(
                    amazon_order_id=order_id,
                    brand_id=divi_shop_id,
                    has_logistics=False
                )

                # 更新状态
                order.is_exported_to_divi = exists
                order.save(update_fields=['is_exported_to_divi'])
                updated_count += 1

            except Exception as e:
                skipped_orders.append({
                    'order_id': order_id,
                    'reason': f'查询异常: {str(e)}'
                })
                print(f"更新订单 {order_id} 失败: {e}")
                continue

        print(f"✅ 更新了 {updated_count} 条订单的DIVI导出状态")
        if skipped_orders:
            print(f"⚠️ 跳过了 {len(skipped_orders)} 条订单:")
            for skipped in skipped_orders:
                print(f"   - 订单 {skipped['order_id']}: {skipped['reason']}")

        # 重新查询更新后的数据并组装返回
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
                'is_exported_to_divi': order.is_exported_to_divi
            })

        # 批量获取商品数量
        order_ids = [order.id for order in orders_page]
        quantity_map = dict(
            AmazonOrderItem.objects.filter(
                order_id__in=order_ids
            ).values('order_id').annotate(
                total_quantity=Sum('quantity_ordered')
            ).values_list('order_id', 'total_quantity')
        )

        for order_data in orders_data:
            corresponding_order = next((o for o in orders_page if o.amazon_order_id == order_data['amazon_order_id']),
                                       None)
            if corresponding_order:
                order_data['quantity'] = quantity_map.get(corresponding_order.id, 0)

        print(f"✅ 返回 {len(orders_data)} 条订单，总计 {total} 条")
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
        print(f"❌ 更新DIVI状态API错误: {str(e)}")
        import traceback
        traceback.print_exc()
        print(f"{'=' * 60}\n")

        return JsonResponse({
            'success': False,
            'message': f'服务器错误: {str(e)}'
        }, status=500)

def assemble_and_print_response(current_stats, previous_stats, comparison, trend_data,
                                filter_type, filter_value, current_start, current_end,
                                previous_start, previous_end, shop_count, lingxing_shop_count):
    """组装响应数据并打印完整日志"""

    # 组装完整响应
    response_data = {
        'success': True,
        'data': {
            'current': {
                'order_count': current_stats['order_count'],
                'total_sales_quantity': current_stats['total_sales_quantity'],
                'total_revenue': current_stats['total_revenue'],
                'avg_order_value': current_stats['avg_order_value'],
                'fba_percentage': current_stats['fba_percentage'],
                'fbm_percentage': current_stats['fbm_percentage'],
            },
            'previous': {
                'order_count': previous_stats['order_count'],
                'total_sales_quantity': previous_stats['total_sales_quantity'],
                'total_revenue': previous_stats['total_revenue'],
                'avg_order_value': previous_stats['avg_order_value'],
                'fba_percentage': previous_stats['fba_percentage'],
                'fbm_percentage': previous_stats['fbm_percentage'],
            },
            'comparison': comparison,
            'trend_data': trend_data,
            'filter_info': {
                'filter_type': filter_type,
                'filter_value': filter_value,
                'current_date_range': f"{current_start} to {current_end}",
                'previous_date_range': f"{previous_start} to {previous_end}",
                'days': (current_end - current_start).days + 1,
                'shop_count': shop_count,
                'lingxing_shop_count': lingxing_shop_count
            }
        }
    }

    # 打印完整响应（包含filter_info）
    print(f"\n{'=' * 60}")
    print("🎯 最终返回数据（完整版）:")
    print(json.dumps(response_data, indent=2, ensure_ascii=False))
    print(f"{'=' * 60}\n")

    return JsonResponse(response_data)


def assemble_response_data(filter_type, filter_value, current_start, current_end,
                           previous_start, previous_end, shop_count=0,
                           lingxing_shop_count=0, trend_data=None):
    """快速组装空数据响应"""
    if trend_data is None:
        trend_data = []

    response_data = {
        'success': True,
        'data': {
            'current': {
                'order_count': 0, 'total_sales_quantity': 0, 'total_revenue': 0.0,
                'avg_order_value': 0.0, 'fba_percentage': '0.0%', 'fbm_percentage': '0.0%'
            },
            'previous': {
                'order_count': 0, 'total_sales_quantity': 0, 'total_revenue': 0.0,
                'avg_order_value': 0.0, 'fba_percentage': '0.0%', 'fbm_percentage': '0.0%'
            },
            'comparison': {
                'order_count_change': '0.0%', 'total_sales_quantity_change': '0.0%',
                'total_revenue_change': '0.0%', 'avg_order_value_change': '0.0%',
                'fba_percentage_change': '0.0%', 'fbm_percentage_change': '0.0%'
            },
            'trend_data': trend_data,
            'filter_info': {
                'filter_type': filter_type,
                'filter_value': filter_value,
                'current_date_range': f"{current_start} to {current_end}",
                'previous_date_range': f"{previous_start} to {previous_end}",
                'days': (current_end - current_start).days + 1 if current_start and current_end else 0,
                'shop_count': shop_count,
                'lingxing_shop_count': lingxing_shop_count
            }
        }
    }

    print(f"\n{'=' * 60}")
    print("⚠️ 返回空数据（未找到符合条件的记录）:")
    print(json.dumps(response_data, indent=2, ensure_ascii=False))
    print(f"{'=' * 60}\n")

    return JsonResponse(response_data)


