# amazon/view/views_amazon_profit.py
"""
Amazon MSKU 利润明细页面
"""

import json
from datetime import datetime, timedelta
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt

from amazon.amazon_views import (
    get_user_operation_permissions,
    determine_filter_type_and_value,
    get_shop_ids_by_filter,
    parse_multi_select,
    has_perm_code,
)
from amazon.models import (
    LingXingAmazonShop,
    AmazonMSKUDailyProfit,
)
from general.models import AmazonShop


@login_required
def amazon_profit_detail_page(request):
    """利润明细页面"""
    from amazon.amazon_views import has_perm_code
    user = request.user
    is_admin = has_perm_code(user, '555')
    return render(request, 'amazon_profit_detail.html', {
        'active_nav': 'amazon_profit',
        'active_page': 'amazon_profit',
        'is_admin': is_admin,
    })


@login_required
@csrf_exempt
def get_amazon_profit_detail_api(request):
    """
    获取 MSKU 利润明细数据 API
    POST 请求
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
        page_size = min(page_size, 100)

        # 日期筛选
        start_date_str = data.get('start_date', '')
        end_date_str = data.get('end_date', '')

        # 如果没有传日期，默认昨天
        if not start_date_str or not end_date_str:
            yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
            start_date_str = yesterday
            end_date_str = yesterday

        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        except ValueError:
            return JsonResponse({'success': False, 'message': '日期格式错误'}, status=400)

        # ========== 获取店铺ID列表（含公司隔离） ==========
        shop_ids = get_shop_ids_by_filter(filter_type, filter_value, user=user)
        shop_ids_list = list(shop_ids)

        # 如果没有权限或没有店铺，返回空数据（不报错）
        if not shop_ids_list:
            return JsonResponse({
                'success': True,
                'data': {
                    'profits': [],
                    'total': 0,
                    'page': page,
                    'page_size': page_size,
                    'total_pages': 0,
                    'summary': {
                        'total_sales': '0.00',
                        'total_ad_cost': '0.00',
                        'total_cost': '0.00',
                        'total_net_profit': '0.00',
                    }
                }
            })

        # 通过 AmazonShop ID 找到对应的 LingXingAmazonShop sid
        lingxing_shops = LingXingAmazonShop.objects.filter(
            amazon_shop_id__in=shop_ids_list
        ).select_related('amazon_shop')

        # 构建 sid -> shop_name 映射
        sid_to_shop = {}
        for lx in lingxing_shops:
            if lx.amazon_shop:
                sid_to_shop[lx.sid] = {
                    'shop_name': lx.amazon_shop.shop_name or lx.amazon_shop.amazon_shop_name or f'店铺{lx.sid}',
                    'ops_id': lx.amazon_shop.ops_id,
                }

        sid_list = list(sid_to_shop.keys())

        # ========== 构建查询条件 ==========
        q_filter = Q(sid__in=sid_list, sync_date__gte=start_date, sync_date__lte=end_date)

        # 店铺筛选（前端传的 shop_id 是 AmazonShop 的 ID）
        shop_id_raw = data.get('shop_id', '')
        shop_id_list = parse_multi_select(shop_id_raw)
        if shop_id_list:
            try:
                shop_id_ints = [int(v) for v in shop_id_list]
                # 找到这些 AmazonShop 对应的 sid
                target_sids = LingXingAmazonShop.objects.filter(
                    amazon_shop_id__in=shop_id_ints
                ).values_list('sid', flat=True)
                q_filter &= Q(sid__in=list(target_sids))
            except (ValueError, TypeError):
                pass

        # 关键词搜索（MSKU / ASIN / 品名）
        keyword = data.get('keyword', '').strip()
        if keyword:
            q_filter &= (
                Q(seller_sku__icontains=keyword) |
                Q(item_name__icontains=keyword) |
                Q(price_list__asin__icontains=keyword)
            )

        # ========== 查询数据 ==========
        profits_qs = AmazonMSKUDailyProfit.objects.filter(q_filter).order_by('-sync_date', 'sid', 'seller_sku')

        # 分页
        paginator = Paginator(profits_qs, page_size)
        total = paginator.count

        try:
            page_obj = paginator.page(page)
        except (EmptyPage, PageNotAnInteger):
            page_obj = paginator.page(1)
            page = 1

        total_pages = paginator.num_pages

        # ========== 汇总统计（全部数据，不只是当前页） ==========
        all_profits = profits_qs.values_list('amount', 'spend', 'total_costs')
        total_sales = Decimal('0')
        total_ad_cost = Decimal('0')
        total_cost = Decimal('0')
        total_net_profit = Decimal('0')

        for amount, spend, costs in all_profits:
            amt = amount or Decimal('0')
            spd = spend or Decimal('0')
            cst = costs or Decimal('0')
            total_sales += amt
            total_ad_cost += spd
            total_cost += cst
            total_net_profit += (amt - spd - cst)

        # ========== 序列化当前页数据 ==========
        profit_list = []
        for profit in page_obj:
            shop_info = sid_to_shop.get(profit.sid, {})

            # 获取 ASIN（从 price_list 子表取第一个）
            asin = ''
            price_list = profit.price_list.first()
            if price_list:
                asin = price_list.asin or ''

            # 计算净利润
            amount = profit.amount or Decimal('0')
            spend = profit.spend or Decimal('0')
            total_costs = profit.total_costs or Decimal('0')
            net_profit = amount - spend - total_costs

            profit_list.append({
                'id': profit.id,
                'sync_date': profit.sync_date.strftime('%Y-%m-%d'),
                'shop_name': shop_info.get('shop_name', f'店铺{profit.sid}'),
                'sid': profit.sid,
                'seller_sku': profit.seller_sku,
                'asin': asin,
                'item_name': profit.item_name or '',
                'volume': profit.volume or 0,
                'afn_volume': profit.afn_volume or 0,
                'mfn_volume': profit.mfn_volume or 0,
                'ad_volume': profit.ad_volume or 0,
                'amount': str(amount) if amount else '0.00',
                'afn_amount': str(profit.afn_amount) if profit.afn_amount else '0.00',
                'mfn_amount': str(profit.mfn_amount) if profit.mfn_amount else '0.00',
                'ad_sales_amount': str(profit.ad_sales_amount) if profit.ad_sales_amount else '0.00',
                'spend': str(spend) if spend else '0.00',
                'ads_sp_cost': str(profit.ads_sp_cost) if profit.ads_sp_cost else '0.00',
                'ads_sb_cost': str(profit.ads_sb_cost) if profit.ads_sb_cost else '0.00',
                'ads_sbv_cost': str(profit.ads_sbv_cost) if profit.ads_sbv_cost else '0.00',
                'ads_sd_cost': str(profit.ads_sd_cost) if profit.ads_sd_cost else '0.00',
                'purchase_costs': str(profit.purchase_costs) if profit.purchase_costs else '0.00',
                'logistics_costs': str(profit.logistics_costs) if profit.logistics_costs else '0.00',
                'other_costs': str(profit.other_costs) if profit.other_costs else '0.00',
                'total_costs': str(total_costs) if total_costs else '0.00',
                'net_profit': str(net_profit),
            })

        return JsonResponse({
            'success': True,
            'data': {
                'profits': profit_list,
                'total': total,
                'page': page,
                'page_size': page_size,
                'total_pages': total_pages,
                'summary': {
                    'total_sales': str(total_sales.quantize(Decimal('0.00'))),
                    'total_ad_cost': str(total_ad_cost.quantize(Decimal('0.00'))),
                    'total_cost': str(total_cost.quantize(Decimal('0.00'))),
                    'total_net_profit': str(total_net_profit.quantize(Decimal('0.00'))),
                }
            }
        })

    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'message': 'JSON解析错误'}, status=400)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({'success': False, 'message': f'服务器错误: {str(e)}'}, status=500)


@login_required
def get_amazon_profit_filter_options_api(request):
    """
    获取利润明细页面的筛选选项（店铺列表、人员列表）
    GET 请求
    """
    user = request.user
    permissions = get_user_operation_permissions(user)
    filter_type, filter_value = determine_filter_type_and_value(request, {}, permissions)

    # 获取店铺列表
    shop_ids = get_shop_ids_by_filter(filter_type, filter_value, user=user)
    shops = AmazonShop.objects.filter(id__in=list(shop_ids)).select_related('ops')

    shop_options = []
    for shop in shops:
        shop_options.append({
            'id': shop.id,
            'name': shop.shop_name or shop.amazon_shop_name or f'店铺{shop.id}',
        })

    # 获取人员列表（只有555管理员才返回全部人员）
    operator_options = []
    if has_perm_code(user, '555'):
        from general.models import OperationalAccount
        operators = OperationalAccount.objects.select_related('user').all()
        for op in operators:
            if op.user:
                operator_options.append({
                    'id': op.user.id,
                    'name': op.user.first_name or op.user.username,
                    'group': op.ops_group or '',
                })

    return JsonResponse({
        'success': True,
        'data': {
            'shops': shop_options,
            'operators': operator_options,
            'permissions': permissions,
        }
    })
