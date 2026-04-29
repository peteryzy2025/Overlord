# amazon/view/views_amazon_profit.py
"""
Amazon MSKU 利润明细页面
支持单天显示和多天聚合（按 MSKU+店铺维度）
"""

import json
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.db.models import Q, Sum
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


NUMERIC_FIELD_TYPES = {
    'DecimalField',
    'IntegerField',
    'BigIntegerField',
    'SmallIntegerField',
    'PositiveIntegerField',
    'PositiveSmallIntegerField',
    'FloatField',
}

COMPUTED_FIELDS = {'ad_cost_ratio', 'cost_ratio', 'platform_fee_ratio', 'logistics_ratio', 'profit_ratio', 'net_profit', 'gross_profit'}
PYTHON_SORT_FIELDS = COMPUTED_FIELDS | {'asin', 'shop_name'}
PERCENT_COMPUTED_FIELDS = {'ad_cost_ratio', 'cost_ratio', 'platform_fee_ratio', 'logistics_ratio', 'profit_ratio'}
NON_SUM_NUMERIC_NAMES = {
    'id',
    'sid',
    'avg_volume',
    'return_rate',
    'refund_amount_rate',
    'avg_net_amount',
    'avg_purchase_costs',
    'avg_logistics_costs',
    'avg_other_costs',
    'gross_margin',
    'avg_gross_profit',
    'net_gross_margin',
    'selling_fee_rate',
    'fulfillment_fee_rate',
    'spend_rate',
    'total_stock_fee_rate',
}
EXCLUDED_PROFIT_COLUMN_KEYS = {
    'id',
    'lxshop_id',
    'sid',
    'currency_code',
    'currency_icon',
    'small_image_url',
    'principal_names',
    'is_parent',
    'categories',
    'brands',
    'gross_profit',
    'created_at',
    'updated_at',
}
PINNED_AFTER_DATE_COLUMNS = [
    {'key': 'spend', 'label': '广告总花费', 'sortable': True, 'value_type': 'amount_percent', 'ratio_key': 'ad_cost_ratio'},
    {'key': 'total_costs', 'label': '合计成本', 'sortable': True, 'value_type': 'amount_percent', 'ratio_key': 'cost_ratio'},
    {'key': 'selling_fee', 'label': '平台费', 'sortable': True, 'value_type': 'amount_percent', 'ratio_key': 'platform_fee_ratio'},
    {'key': 'gross_profit', 'label': '利润', 'sortable': True, 'value_type': 'amount_percent', 'ratio_key': 'profit_ratio'},
]
PINNED_AFTER_DATE_KEYS = {column['key'] for column in PINNED_AFTER_DATE_COLUMNS}


def get_profit_field_key(field):
    return field.attname if getattr(field, 'many_to_one', False) else field.name


def infer_profit_column_type(key, field_type=None):
    if key in PERCENT_COMPUTED_FIELDS:
        return 'percent'
    if field_type == 'BooleanField':
        return 'boolean'
    if field_type == 'JSONField':
        return 'json'
    if field_type in {'DateField', 'DateTimeField'}:
        return 'datetime'
    if field_type in NUMERIC_FIELD_TYPES:
        return 'number'
    return 'text'


def get_profit_table_columns():
    columns = []
    inserted_after_sku = False

    for field in AmazonMSKUDailyProfit._meta.fields:
        key = get_profit_field_key(field)
        field_type = field.get_internal_type()
        if key in EXCLUDED_PROFIT_COLUMN_KEYS or key in PINNED_AFTER_DATE_KEYS:
            continue

        columns.append({
            'key': key,
            'label': '数据日期' if key == 'sync_date' else field.db_comment or field.verbose_name or key,
            'sortable': True,
            'value_type': infer_profit_column_type(key, field_type),
        })

        if key == 'sync_date':
            columns.extend(PINNED_AFTER_DATE_COLUMNS)

        if field.name == 'seller_sku' and not inserted_after_sku:
            columns.extend([
                {'key': 'small_image_url', 'label': '图片', 'sortable': False, 'value_type': 'image'},
                {'key': 'shop_name', 'label': '店铺', 'sortable': True, 'value_type': 'text'},
                {'key': 'asin', 'label': 'ASIN', 'sortable': True, 'value_type': 'text'},
            ])
            inserted_after_sku = True

    columns.extend([
        {'key': 'logistics_ratio', 'label': '运费占比', 'sortable': True, 'value_type': 'percent'},
        {'key': 'gross_profit', 'label': '利润', 'sortable': True, 'value_type': 'amount_percent', 'ratio_key': 'profit_ratio'},
    ])

    return columns


PROFIT_TABLE_COLUMNS = get_profit_table_columns()
DB_SORT_FIELD_MAP = {
    get_profit_field_key(field): get_profit_field_key(field)
    for field in AmazonMSKUDailyProfit._meta.fields
}
AGGREGATE_SUM_FIELDS = [
    field.name
    for field in AmazonMSKUDailyProfit._meta.fields
    if field.get_internal_type() in NUMERIC_FIELD_TYPES
    and field.name not in NON_SUM_NUMERIC_NAMES
]


def serialize_profit_value(value):
    if value is None:
        return ''
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def decimal_or_zero(value):
    if value in (None, ''):
        return Decimal('0')
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal('0')


def calculate_profit_metrics(amount, spend, total_costs, logistics_costs, selling_fee=None):
    amount = decimal_or_zero(amount)
    spend = decimal_or_zero(spend)
    total_costs = decimal_or_zero(total_costs)
    logistics_costs = decimal_or_zero(logistics_costs)
    selling_fee = decimal_or_zero(selling_fee)

    net_profit = amount + spend + total_costs + selling_fee

    amount_abs = abs(amount) if amount else Decimal('0')
    ad_cost_ratio = (abs(spend) / amount_abs * 100) if amount_abs else Decimal('0')
    cost_ratio = (abs(total_costs) / amount_abs * 100) if amount_abs else Decimal('0')
    platform_fee_ratio = (abs(selling_fee) / amount_abs * 100) if amount_abs else Decimal('0')
    logistics_ratio = (abs(logistics_costs) / amount_abs * 100) if amount_abs else Decimal('0')
    profit_ratio = (net_profit / amount_abs * 100) if amount_abs else Decimal('0')
    return net_profit, ad_cost_ratio, cost_ratio, platform_fee_ratio, logistics_ratio, profit_ratio


def apply_profit_metrics(
    row,
    amount=None,
    spend=None,
    total_costs=None,
    logistics_costs=None,
    selling_fee=None,
    formatted=True,
):
    net_profit, ad_cost_ratio, cost_ratio, platform_fee_ratio, logistics_ratio, profit_ratio = calculate_profit_metrics(
        amount=amount if amount is not None else row.get('amount'),
        spend=spend if spend is not None else row.get('spend'),
        total_costs=total_costs if total_costs is not None else row.get('total_costs'),
        logistics_costs=logistics_costs if logistics_costs is not None else row.get('logistics_costs'),
        selling_fee=selling_fee if selling_fee is not None else row.get('selling_fee'),
    )

    if formatted:
        row['net_profit'] = str(net_profit)
        row['gross_profit'] = str(net_profit)
        row['ad_cost_ratio'] = f"{ad_cost_ratio:.1f}"
        row['cost_ratio'] = f"{cost_ratio:.1f}"
        row['platform_fee_ratio'] = f"{platform_fee_ratio:.1f}"
        row['logistics_ratio'] = f"{logistics_ratio:.1f}"
        row['profit_ratio'] = f"{profit_ratio:.1f}"
    else:
        row['net_profit'] = net_profit
        row['gross_profit'] = net_profit
        row['ad_cost_ratio'] = ad_cost_ratio
        row['cost_ratio'] = cost_ratio
        row['platform_fee_ratio'] = platform_fee_ratio
        row['logistics_ratio'] = logistics_ratio
        row['profit_ratio'] = profit_ratio
    return row


def get_profit_asin(profit):
    price = profit.price_list.first()
    return price.asin if price else ''


def build_profit_row(profit, shop_info=None, asin=None, formatted=True):
    row = {}
    for field in AmazonMSKUDailyProfit._meta.fields:
        key = get_profit_field_key(field)
        row[key] = serialize_profit_value(getattr(profit, key))

    row['shop_name'] = (shop_info or {}).get('shop_name', f'店铺{profit.sid}')
    row['asin'] = asin if asin is not None else get_profit_asin(profit)
    apply_profit_metrics(row, formatted=formatted)
    return row


def sort_profit_rows(rows, sort_field, sort_order):
    reverse = sort_order == 'desc'

    def sort_value(row):
        value = row.get(sort_field)
        if value in (None, ''):
            return (2, '')
        try:
            return (0, Decimal(str(value)))
        except Exception:
            return (1, str(value).lower())

    rows.sort(key=sort_value, reverse=reverse)


@login_required
def amazon_profit_detail_page(request):
    """利润明细页面"""
    user = request.user
    is_admin = has_perm_code(user, '555')
    user_permissions = list(user.permission_configs.values_list('code', flat=True))
    return render(request, 'amazon_profit_detail.html', {
        'active_nav': 'amazon_profit',
        'active_page': 'amazon_profit',
        'is_admin': is_admin,
        'user_permissions': user_permissions,
        'profit_columns': PROFIT_TABLE_COLUMNS,
    })


@login_required
@csrf_exempt
def get_amazon_profit_detail_api(request):
    """
    获取 MSKU 利润明细数据 API
    POST 请求
    支持单天显示和多天聚合（按 MSKU+店铺维度）
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
        page_size = int(data.get('page_size', 100))
        page_size = min(page_size, 500)

        # 排序参数
        sort_field = data.get('sort_field', 'amount')  # 默认按销售额
        sort_order = data.get('sort_order', 'desc')    # 默认降序
        if sort_field not in DB_SORT_FIELD_MAP and sort_field not in PYTHON_SORT_FIELDS:
            sort_field = 'amount'

        # 日期筛选
        start_date_str = data.get('start_date', '')
        end_date_str = data.get('end_date', '')
        date_range = str(data.get('date_range', '') or '').strip()

        if not start_date_str or not end_date_str:
            today = datetime.now().date()
            if date_range == 'today':
                start_date_str = today.strftime('%Y-%m-%d')
                end_date_str = today.strftime('%Y-%m-%d')
            elif date_range == 'last7days':
                start_date_str = (today - timedelta(days=6)).strftime('%Y-%m-%d')
                end_date_str = today.strftime('%Y-%m-%d')
            elif date_range == 'last30days':
                start_date_str = (today - timedelta(days=29)).strftime('%Y-%m-%d')
                end_date_str = today.strftime('%Y-%m-%d')

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

        # 判断是否多天聚合
        is_multi_day = (end_date - start_date).days > 0

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
                        'total_platform_fee': '0.00',
                        'total_cost': '0.00',
                        'total_net_profit': '0.00',
                        'ad_cost_ratio': '0.0',
                        'platform_fee_ratio': '0.0',
                        'cost_ratio': '0.0',
                        'profit_ratio': '0.0',
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

        # 履约方式筛选：MSKU 包含 -FBA 视为 FBA，否则视为 FBM
        fulfillment_type = str(data.get('fulfillment_type', 'all') or 'all').strip().lower()
        if fulfillment_type == 'fba':
            q_filter &= Q(seller_sku__icontains='-fba')
        elif fulfillment_type == 'fbm':
            q_filter &= ~Q(seller_sku__icontains='-fba')

        # ========== 查询数据 ==========
        # 过滤掉空/无效 MSKU 的记录
        profits_qs = AmazonMSKUDailyProfit.objects.filter(q_filter).exclude(
            seller_sku__isnull=True
        ).exclude(seller_sku='').exclude(seller_sku='-')

        # ========== 汇总统计（全部数据） ==========
        all_profits = profits_qs.values_list(
            'amount',
            'spend',
            'selling_fee',
            'total_costs',
        )
        total_sales = Decimal('0')
        total_ad_cost = Decimal('0')
        total_platform_fee = Decimal('0')
        total_cost = Decimal('0')
        total_net_profit = Decimal('0')

        for amount, spend, selling_fee, costs in all_profits:
            amt = amount or Decimal('0')
            spd = spend or Decimal('0')
            fee = selling_fee or Decimal('0')
            cst = costs or Decimal('0')
            prf = amt + spd + cst + fee
            total_sales += amt
            total_ad_cost += spd
            total_platform_fee += fee
            total_cost += cst
            total_net_profit += prf

        total_sales_abs = abs(total_sales) if total_sales else Decimal('0')
        summary_ad_cost_ratio = (abs(total_ad_cost) / total_sales_abs * 100) if total_sales_abs else Decimal('0')
        summary_platform_fee_ratio = (abs(total_platform_fee) / total_sales_abs * 100) if total_sales_abs else Decimal('0')
        summary_cost_ratio = (abs(total_cost) / total_sales_abs * 100) if total_sales_abs else Decimal('0')
        summary_profit_ratio = (total_net_profit / total_sales_abs * 100) if total_sales_abs else Decimal('0')

        # ========== 单天 or 多天聚合 ==========
        if is_multi_day:
            aggregations = {f'{field_name}_sum': Sum(field_name) for field_name in AGGREGATE_SUM_FIELDS}
            aggregated = profits_qs.values('sid', 'seller_sku').annotate(**aggregations).order_by('seller_sku', 'sid')

            latest_rows = {}
            for profit in profits_qs.order_by('sid', 'seller_sku', '-sync_date', '-id'):
                key = (profit.sid, profit.seller_sku)
                if key not in latest_rows:
                    latest_rows[key] = build_profit_row(
                        profit,
                        sid_to_shop.get(profit.sid, {}),
                        asin='',
                        formatted=True,
                    )

            # 获取 ASIN
            from amazon.models import AmazonMSKUDailyProfitPriceList
            asin_map = {}
            for pl in AmazonMSKUDailyProfitPriceList.objects.filter(
                profit__sid__in=sid_list,
                profit__sync_date__gte=start_date,
                profit__sync_date__lte=end_date
            ).values('profit__sid', 'profit__seller_sku', 'asin').distinct():
                key = (pl['profit__sid'], pl['profit__seller_sku'])
                if key not in asin_map:
                    asin_map[key] = pl['asin'] or ''

            # 构建聚合后的列表
            profit_list = []
            for item in aggregated:
                sid = item['sid']
                seller_sku = item['seller_sku']
                key = (sid, seller_sku)
                shop_info = sid_to_shop.get(sid, {})

                row = dict(latest_rows.get(key, {}))
                row.update({
                    'id': f"{sid}_{seller_sku}",
                    'sync_date': f"{start_date_str} ~ {end_date_str}",
                    'shop_name': shop_info.get('shop_name', f'店铺{sid}'),
                    'sid': sid,
                    'seller_sku': seller_sku,
                    'asin': asin_map.get(key, ''),
                })
                for field_name in AGGREGATE_SUM_FIELDS:
                    row[field_name] = serialize_profit_value(item.get(f'{field_name}_sum') or Decimal('0'))

                apply_profit_metrics(row, formatted=True)
                profit_list.append(row)

            sort_profit_rows(profit_list, sort_field, sort_order)

            total = len(profit_list)
            total_pages = (total + page_size - 1) // page_size
            start_idx = (page - 1) * page_size
            end_idx = start_idx + page_size
            profit_list = profit_list[start_idx:end_idx]

        else:
            is_python_sort = sort_field in PYTHON_SORT_FIELDS

            if is_python_sort:
                profits_qs = profits_qs.order_by('seller_sku', 'sid')
                all_profits = list(profits_qs)

                profit_list_all = []
                for profit in all_profits:
                    shop_info = sid_to_shop.get(profit.sid, {})
                    profit_list_all.append(build_profit_row(profit, shop_info, formatted=True))

                sort_profit_rows(profit_list_all, sort_field, sort_order)

                total = len(profit_list_all)
                total_pages = (total + page_size - 1) // page_size
                start_idx = (page - 1) * page_size
                end_idx = start_idx + page_size
                profit_list = profit_list_all[start_idx:end_idx]

            else:
                db_sort_field = DB_SORT_FIELD_MAP.get(sort_field, 'amount')
                order_prefix = '-' if sort_order == 'desc' else ''
                order_fields = [f"{order_prefix}{db_sort_field}"]
                if db_sort_field != 'seller_sku':
                    order_fields.append('seller_sku')
                profits_qs = profits_qs.order_by(*order_fields)
                paginator = Paginator(profits_qs, page_size)
                total = paginator.count

                try:
                    page_obj = paginator.page(page)
                except (EmptyPage, PageNotAnInteger):
                    page_obj = paginator.page(1)
                    page = 1

                total_pages = paginator.num_pages

                profit_list = []
                for profit in page_obj:
                    shop_info = sid_to_shop.get(profit.sid, {})
                    profit_list.append(build_profit_row(profit, shop_info, formatted=True))

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
                    'total_platform_fee': str(total_platform_fee.quantize(Decimal('0.00'))),
                    'total_cost': str(total_cost.quantize(Decimal('0.00'))),
                    'total_net_profit': str(total_net_profit.quantize(Decimal('0.00'))),
                    'ad_cost_ratio': str(summary_ad_cost_ratio.quantize(Decimal('0.1'))),
                    'platform_fee_ratio': str(summary_platform_fee_ratio.quantize(Decimal('0.1'))),
                    'cost_ratio': str(summary_cost_ratio.quantize(Decimal('0.1'))),
                    'profit_ratio': str(summary_profit_ratio.quantize(Decimal('0.1'))),
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
