# Amazon/views_ranking.py
from django.http import JsonResponse
from django.db.models import Sum, Count, Q
from django.db.models.functions import TruncDate
from django.shortcuts import render
from datetime import datetime, timedelta
from django.contrib.auth.decorators import login_required
from decimal import Decimal

# 模型导入
from General.models import User, AmazonShop, TemuShop, OperationalAccount
from Amazon.models import LingXingAmazonShop, AmazonOrders, AmazonOrderItem
from Temu.models import LingXingTemuShop, TemuOrder, TemuOrderItem


@login_required
def ranking_page(request):
    """运营排名页面渲染"""
    return render(request, 'ranking.html', {
        'active_nav': 'ranking'
    })


@login_required
def get_ranking_data_api(request):
    """
    获取运营排名数据 API
    GET参数:
      - start_date: 开始日期
      - end_date: 结束日期
    返回: 按订单量排序的运营排名数据（包含销售量）
    """
    if request.method != 'GET':
        return JsonResponse({'success': False, 'message': '只支持GET请求'}, status=405)

    try:
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

        print(f"\n{'=' * 60}")
        print(f"📊 计算运营排名: {start_date} 至 {end_date}")
        print(f"{'=' * 60}\n")

        # ========== 查询所有运营人员 ==========
        # 获取所有有店铺的 ops_id
        amazon_ops = set(AmazonShop.objects.filter(
            ops_id__isnull=False
        ).values_list('ops_id', flat=True))

        temu_ops = set(TemuShop.objects.filter(
            ops_id__isnull=False
        ).values_list('ops_id', flat=True))

        all_ops_ids = amazon_ops.union(temu_ops)

        if not all_ops_ids:
            return JsonResponse({
                'success': True,
                'data': [],
                'message': '暂无运营数据'
            })

        # 查询运营人员信息
        users = User.objects.filter(
            id__in=all_ops_ids,
            status=1  # 只查正常状态用户
        ).select_related('operational_account')

        user_dict = {u.id: u for u in users}

        # ========== 统计每个运营的业绩 ==========
        ranking_data = []

        for ops_id in all_ops_ids:
            user = user_dict.get(ops_id)
            if not user:
                continue

            # ===== Amazon 统计 =====
            amazon_shops = AmazonShop.objects.filter(ops_id=ops_id)
            amazon_shop_ids = list(amazon_shops.values_list('id', flat=True))

            amazon_order_count = 0
            amazon_sales_quantity = 0

            if amazon_shop_ids:
                lingxing_shops = LingXingAmazonShop.objects.filter(
                    amazon_shop_id__in=amazon_shop_ids
                )
                lingxing_shop_ids = list(lingxing_shops.values_list('sid', flat=True))

                if lingxing_shop_ids:
                    # 订单量（排除退货）
                    amazon_order_count = AmazonOrders.objects.filter(
                        lingxing_shop_id__in=lingxing_shop_ids,
                        purchase_date_local__date__gte=start_date,
                        purchase_date_local__date__lte=end_date
                    ).exclude(
                        order_status='Canceled'
                    ).count()

                    # 销售量（件数，排除退货）- 修复：使用 exclude 而不是 __ne
                    quantity_agg = AmazonOrderItem.objects.filter(
                        order__lingxing_shop_id__in=lingxing_shop_ids,
                        order__purchase_date_local__date__gte=start_date,
                        order__purchase_date_local__date__lte=end_date,
                    ).exclude(
                        order__order_status='Canceled'  # 修复：使用 exclude 排除退货
                    ).aggregate(
                        total_quantity=Sum('quantity_ordered')
                    )
                    amazon_sales_quantity = quantity_agg['total_quantity'] or 0

            # ===== Temu 统计 =====
            temu_shops = TemuShop.objects.filter(ops_id=ops_id)
            temu_shop_ids = list(temu_shops.values_list('id', flat=True))

            temu_order_count = 0
            temu_sales_quantity = 0

            if temu_shop_ids:
                # 获取日期范围内的所有订单
                all_orders = TemuOrder.objects.filter(
                    lingxing_shop__temu_shop_id__in=temu_shop_ids,
                    global_purchase_time__date__gte=start_date,
                    global_purchase_time__date__lte=end_date
                ).values('global_order_no', 'platform_info')

                # 找出退货订单号
                cancelled_order_nos = [
                    o['global_order_no'] for o in all_orders
                    if o.get('platform_info') and len(o.get('platform_info', [])) > 0
                       and o['platform_info'][0].get('status') == 'CANCELED'
                ]

                # 订单量（排除退货）
                temu_order_count = TemuOrder.objects.filter(
                    lingxing_shop__temu_shop_id__in=temu_shop_ids,
                    global_purchase_time__date__gte=start_date,
                    global_purchase_time__date__lte=end_date
                ).exclude(
                    global_order_no__in=cancelled_order_nos
                ).count()

                # 销售量（件数，排除退货）
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

            # ===== 合并数据 =====
            total_order_count = amazon_order_count + temu_order_count
            total_sales_quantity = amazon_sales_quantity + temu_sales_quantity

            if total_order_count > 0:  # 只显示有订单的运营
                ranking_data.append({
                    'operator_id': ops_id,
                    'operator_name': user.first_name or user.username,
                    'group': user.operational_account.ops_group if hasattr(user,
                                                                           'operational_account') and user.operational_account else '未分组',
                    'amazon_orders': amazon_order_count,
                    'temu_orders': temu_order_count,
                    'total_orders': total_order_count,
                    'amazon_sales_quantity': amazon_sales_quantity,
                    'temu_sales_quantity': temu_sales_quantity,
                    'total_sales_quantity': total_sales_quantity,
                })

        # 按订单量降序排序
        ranking_data.sort(key=lambda x: x['total_orders'], reverse=True)

        # 添加排名序号
        for idx, item in enumerate(ranking_data, 1):
            item['rank'] = idx

        print(f"✅ 返回 {len(ranking_data)} 条排名数据")
        print(f"{'=' * 60}\n")

        return JsonResponse({
            'success': True,
            'data': ranking_data,
            'date_range': {
                'start': start_date.strftime('%Y-%m-%d'),
                'end': end_date.strftime('%Y-%m-%d')
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