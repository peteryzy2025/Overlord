# Amazon/views_ranking.py
from django.http import JsonResponse
from django.db.models import Sum
from django.shortcuts import render
from datetime import datetime, timedelta
from django.contrib.auth.decorators import login_required
from collections import defaultdict

# 模型导入
from general.models import User, AmazonShop, TemuShop, OperationalAccount
from amazon.models import LingXingAmazonShop, AmazonOrders, AmazonOrderItem
from temu.models import TemuOrder, TemuOrderItem

# 登神长阶：不需要权限限制，所有运营人员均可查看全公司排名


def get_operator_stats(company, ops_id, start_date, end_date):
    """
    获取单个运营人员在指定日期范围内的统计数据
    返回: {'total_orders': int, 'total_sales_quantity': int, ...}
    """
    # ===== Amazon 统计 =====
    amazon_shops = AmazonShop.objects.filter(
        company=company,
        ops_id=ops_id
    )
    amazon_shop_ids = list(amazon_shops.values_list('id', flat=True))

    amazon_order_count = 0
    amazon_sales_quantity = 0

    if amazon_shop_ids:
        lingxing_shops = LingXingAmazonShop.objects.filter(
            amazon_shop_id__in=amazon_shop_ids
        )
        lingxing_shop_ids = list(lingxing_shops.values_list('sid', flat=True))

        if lingxing_shop_ids:
            amazon_order_count = AmazonOrders.objects.filter(
                lingxing_shop_id__in=lingxing_shop_ids,
                purchase_date_local__date__gte=start_date,
                purchase_date_local__date__lte=end_date
            ).exclude(
                order_status='Canceled'
            ).count()

            quantity_agg = AmazonOrderItem.objects.filter(
                order__lingxing_shop_id__in=lingxing_shop_ids,
                order__purchase_date_local__date__gte=start_date,
                order__purchase_date_local__date__lte=end_date,
            ).exclude(
                order__order_status='Canceled'
            ).aggregate(
                total_quantity=Sum('quantity_ordered')
            )
            amazon_sales_quantity = quantity_agg['total_quantity'] or 0

    # ===== Temu 统计 =====
    temu_shops = TemuShop.objects.filter(
        company=company,
        ops_id=ops_id
    )
    temu_shop_ids = list(temu_shops.values_list('id', flat=True))

    temu_order_count = 0
    temu_sales_quantity = 0

    if temu_shop_ids:
        all_orders = TemuOrder.objects.filter(
            lingxing_shop__temu_shop_id__in=temu_shop_ids,
            global_purchase_time__date__gte=start_date,
            global_purchase_time__date__lte=end_date
        ).values('global_order_no', 'platform_info')

        cancelled_order_nos = [
            o['global_order_no'] for o in all_orders
            if o.get('platform_info') and len(o.get('platform_info', [])) > 0
               and o['platform_info'][0].get('status') == 'CANCELED'
        ]

        temu_order_count = TemuOrder.objects.filter(
            lingxing_shop__temu_shop_id__in=temu_shop_ids,
            global_purchase_time__date__gte=start_date,
            global_purchase_time__date__lte=end_date
        ).exclude(
            global_order_no__in=cancelled_order_nos
        ).count()

        temu_quantity_agg = TemuOrderItem.objects.filter(
            order__lingxing_shop__temu_shop_id__in=temu_shop_ids,
            order__global_purchase_time__date__gte=start_date,
            order__global_purchase_time__date__lte=end_date
        ).exclude(
            order__global_order_no__in=cancelled_order_nos
        ).aggregate(
            total_quantity=Sum('quantity')
        )
        temu_sales_quantity = temu_quantity_agg['total_quantity'] or 0

    total_order_count = amazon_order_count + temu_order_count
    total_sales_quantity = amazon_sales_quantity + temu_sales_quantity

    return {
        'amazon_orders': amazon_order_count,
        'temu_orders': temu_order_count,
        'total_orders': total_order_count,
        'amazon_sales_quantity': amazon_sales_quantity,
        'temu_sales_quantity': temu_sales_quantity,
        'total_sales_quantity': total_sales_quantity,
    }


@login_required
def get_ranking_data_api(request):
    """
    获取运营排名数据 API（带公司隔离）
    登神长阶 - 所有运营人员均可查看全公司排名
    GET参数:
      - start_date: 开始日期
      - end_date: 结束日期
    返回: 
      - personal_ranking: 个人排名数据
      - group_ranking: 小组排名数据（含组员列表）
      - 环比数据
    """
    if request.method != 'GET':
        return JsonResponse({'success': False, 'message': '只支持GET请求'}, status=405)

    try:
        user = request.user

        # 解析日期参数
        start_date_str = request.GET.get('start_date', '')
        end_date_str = request.GET.get('end_date', '')

        # 默认最近7天
        if not start_date_str or not end_date_str:
            end_date = datetime.now().date()
            start_date = end_date - timedelta(days=6)
        else:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()

        # 计算对比期（上一期，同样长度）
        date_range_days = (end_date - start_date).days + 1
        prev_end_date = start_date - timedelta(days=1)
        prev_start_date = prev_end_date - timedelta(days=date_range_days - 1)

        print(f"\n{'=' * 60}")
        print(f"📊 登神长阶 - 当期: {start_date} 至 {end_date}")
        print(f"📊 登神长阶 - 对比期: {prev_start_date} 至 {prev_end_date}")
        print(f"{'=' * 60}\n")

        # ========== 查询本公司有店铺的运营人员 ==========
        amazon_ops = set(AmazonShop.objects.filter(
            company=user.company,
            ops_id__isnull=False
        ).values_list('ops_id', flat=True))

        temu_ops = set(TemuShop.objects.filter(
            company=user.company,
            ops_id__isnull=False
        ).values_list('ops_id', flat=True))

        all_ops_ids = amazon_ops.union(temu_ops)

        if not all_ops_ids:
            return JsonResponse({
                'success': True,
                'data': {'personal_ranking': [], 'group_ranking': []},
                'message': '暂无运营数据'
            })

        # 查询运营人员信息
        users = User.objects.filter(
            id__in=all_ops_ids,
            status=1
        ).select_related('operational_account')

        user_dict = {u.id: u for u in users}

        # ========== 统计当期数据 ==========
        current_data = []
        prev_data = []

        for ops_id in all_ops_ids:
            user_obj = user_dict.get(ops_id)
            if not user_obj:
                continue

            # 当期数据
            current_stats = get_operator_stats(user_obj.company, ops_id, start_date, end_date)
            if current_stats['total_orders'] > 0:
                current_data.append({
                    'operator_id': ops_id,
                    'operator_name': user_obj.first_name or user_obj.username,
                    'group': user_obj.operational_account.ops_group if hasattr(user_obj, 'operational_account') and user_obj.operational_account else '未分组',
                    **current_stats
                })

            # 对比期数据
            prev_stats = get_operator_stats(user_obj.company, ops_id, prev_start_date, prev_end_date)
            if prev_stats['total_orders'] > 0:
                prev_data.append({
                    'operator_id': ops_id,
                    'group': user_obj.operational_account.ops_group if hasattr(user_obj, 'operational_account') and user_obj.operational_account else '未分组',
                    **prev_stats
                })

        # ========== 构建个人排名（当期） ==========
        current_data.sort(key=lambda x: x['total_orders'], reverse=True)
        for idx, item in enumerate(current_data, 1):
            item['rank'] = idx

        # ========== 构建小组排名 ==========
        # 按小组聚合
        group_stats = defaultdict(lambda: {
            'total_orders': 0,
            'total_sales_quantity': 0,
            'members': []
        })

        for item in current_data:
            group_name = item['group']
            group_stats[group_name]['total_orders'] += item['total_orders']
            group_stats[group_name]['total_sales_quantity'] += item['total_sales_quantity']
            group_stats[group_name]['members'].append({
                'operator_id': item['operator_id'],
                'operator_name': item['operator_name'],
                'total_orders': item['total_orders'],
                'total_sales_quantity': item['total_sales_quantity'],
                'rank': item['rank']
            })

        # 对比期小组数据（用于环比）
        prev_group_stats = defaultdict(lambda: {'total_orders': 0})
        for item in prev_data:
            group_name = item['group']
            prev_group_stats[group_name]['total_orders'] += item['total_orders']

        # 构建小组排名列表
        group_ranking = []
        for group_name, stats in group_stats.items():
            # 组员按订单量降序排序
            members = sorted(stats['members'], key=lambda x: x['total_orders'], reverse=True)
            # 添加组内排名
            for idx, member in enumerate(members, 1):
                member['group_rank'] = idx

            # 计算环比
            prev_orders = prev_group_stats[group_name]['total_orders']
            current_orders = stats['total_orders']
            change_percent = 0
            if prev_orders > 0:
                change_percent = round((current_orders - prev_orders) / prev_orders * 100, 1)

            group_ranking.append({
                'group_name': group_name,
                'total_orders': current_orders,
                'total_sales_quantity': stats['total_sales_quantity'],
                'member_count': len(members),
                'members': members,
                'prev_orders': prev_orders,
                'change_percent': change_percent
            })

        # 小组按订单量降序排序
        group_ranking.sort(key=lambda x: x['total_orders'], reverse=True)
        # 添加小组排名
        for idx, item in enumerate(group_ranking, 1):
            item['group_rank'] = idx

        print(f"✅ 个人排名: {len(current_data)} 人")
        print(f"✅ 小组排名: {len(group_ranking)} 组")
        print(f"{'=' * 60}\n")

        return JsonResponse({
            'success': True,
            'data': {
                'personal_ranking': current_data,
                'group_ranking': group_ranking
            },
            'date_range': {
                'current': {
                    'start': start_date.strftime('%Y-%m-%d'),
                    'end': end_date.strftime('%Y-%m-%d')
                },
                'previous': {
                    'start': prev_start_date.strftime('%Y-%m-%d'),
                    'end': prev_end_date.strftime('%Y-%m-%d')
                }
            }
        })

    except Exception as e:
        print(f"\n{'=' * 60}")
        print(f"❌ 排名API错误: {str(e)}")
        import traceback
        traceback.print_exc()
        print(f"{'=' * 60}\n")

        return JsonResponse({
            'success': False,
            'message': f'服务器错误: {str(e)}'
        }, status=500)
