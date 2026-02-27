# # advertisement/view/views_asin.py
#
# import json
# from datetime import datetime
# from calendar import monthrange
# from django.contrib.auth.decorators import login_required
# from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
# from django.db.models import Q, Sum
# from django.http import JsonResponse
# from django.shortcuts import render
#
# from advertisement.models import LingXingAdHourlyData
# from amazon.models import LingXingAmazonShop
#
#
# @login_required
# def asin_list_page(request):
#     """
#     ASIN 广告数据列表页面
#     """
#     return render(request, 'advertisement/asin_list.html', {
#         'active_nav': 'advertisement_campaigns',
#         'active_page': 'asin_list',
#     })
#
#
# @login_required
# def get_asin_list_api(request):
#     """
#     获取 ASIN 广告数据列表 API
#     支持分页、筛选，按 ASIN 汇总广告效果数据
#     """
#     if request.method != 'POST':
#         return JsonResponse({'success': False, 'message': '只支持POST请求'}, status=405)
#
#     try:
#         data = json.loads(request.body)
#         user = request.user
#
#         # 分页参数
#         page = int(data.get('page', 1))
#         page_size = int(data.get('page_size', 20))
#         page_size = min(page_size, 100)
#
#         # 广告日期范围筛选
#         ad_start_date_str = data.get('ad_start_date', '')
#         ad_end_date_str = data.get('ad_end_date', '')
#
#         # 其他筛选条件
#         asin_filter = data.get('asin', '').strip().upper()
#         shop_name_filter = data.get('shop_name', '').strip()
#
#         # 解析广告日期范围
#         ad_start_date, ad_end_date = None, None
#         if ad_start_date_str and ad_end_date_str:
#             try:
#                 ad_start_date = datetime.strptime(ad_start_date_str.split(' ')[0], '%Y-%m-%d').date()
#                 ad_end_date = datetime.strptime(ad_end_date_str.split(' ')[0], '%Y-%m-%d').date()
#             except:
#                 pass
#
#         # 默认当月（如果没有传）
#         if not ad_start_date or not ad_end_date:
#             today = datetime.now().date()
#             ad_start_date = today.replace(day=1)
#             _, last_day = monthrange(today.year, today.month)
#             ad_end_date = today.replace(day=last_day)
#
#         # ========== 构建 ASIN 数据查询条件 ==========
#         data_filter = Q()
#
#         # 广告日期范围筛选
#         if ad_start_date and ad_end_date:
#             data_filter &= Q(report_date__gte=ad_start_date)
#             data_filter &= Q(report_date__lte=ad_end_date)
#
#         # ASIN 模糊查询
#         if asin_filter:
#             data_filter &= Q(asin__icontains=asin_filter)
#
#         # 店铺名称模糊查询（通过关联表）
#         if shop_name_filter:
#             data_filter &= Q(lingxing_shop__name__icontains=shop_name_filter)
#
#         # ========== 获取所有 ASIN 列表（去重）==========
#         asin_queryset = LingXingAdHourlyData.objects.filter(data_filter)
#
#         # 获取唯一 ASIN 列表（带店铺信息）
#         unique_asins = asin_queryset.values('asin', 'lingxing_shop__name').distinct()
#
#         # 构建 ASIN 列表
#         asin_list = []
#         for item in unique_asins:
#             if item['asin']:  # 排除空 ASIN
#                 asin_list.append({
#                     'asin': item['asin'],
#                     'shop_name': item['lingxing_shop__name'] or '未知店铺'
#                 })
#
#         # 去重（同一 ASIN 可能在多个店铺出现，这里简单处理）
#         seen_asins = set()
#         unique_asin_list = []
#         for item in asin_list:
#             if item['asin'] not in seen_asins:
#                 seen_asins.add(item['asin'])
#                 unique_asin_list.append(item)
#
#         total = len(unique_asin_list)
#
#         # ========== 分页 ==========
#         start_idx = (page - 1) * page_size
#         end_idx = start_idx + page_size
#         page_asins = unique_asin_list[start_idx:end_idx]
#
#         # ========== 获取当前页 ASIN 的效果数据 ==========
#         asin_data = []
#         if page_asins:
#             asin_codes = [item['asin'] for item in page_asins]
#
#             # 查询这些 ASIN 的汇总数据
#             hourly_data = LingXingAdHourlyData.objects.filter(
#                 data_filter,
#                 asin__in=asin_codes
#             ).values('asin').annotate(
#                 total_cost=Sum('cost'),
#                 total_sales=Sum('sales'),
#                 total_clicks=Sum('clicks'),
#                 total_impressions=Sum('impressions'),
#                 total_orders=Sum('orders')
#             )
#
#             # 构建数据映射
#             metrics_map = {}
#             for item in hourly_data:
#                 asin = item['asin']
#                 total_cost = item['total_cost'] or 0
#                 total_sales = item['total_sales'] or 0
#                 total_clicks = item['total_clicks'] or 0
#                 total_impressions = item['total_impressions'] or 0
#                 total_orders = item['total_orders'] or 0
#
#                 # 计算指标
#                 acos = (total_cost / total_sales * 100) if total_sales > 0 else 0
#                 roas = (total_sales / total_cost) if total_cost > 0 else 0
#                 ctr = (total_clicks / total_impressions * 100) if total_impressions > 0 else 0
#                 cvr = (total_orders / total_clicks * 100) if total_clicks > 0 else 0
#                 cpc = (total_cost / total_clicks) if total_clicks > 0 else 0
#
#                 metrics_map[asin] = {
#                     'cost': round(total_cost, 2),
#                     'sales': round(total_sales, 2),
#                     'clicks': int(total_clicks),
#                     'impressions': int(total_impressions),
#                     'orders': int(total_orders),
#                     'acos': round(acos, 2),
#                     'roas': round(roas, 2),
#                     'ctr': round(ctr, 2),
#                     'cvr': round(cvr, 2),
#                     'cpc': round(cpc, 2),
#                 }
#
#             # 组装返回数据
#             for item in page_asins:
#                 asin = item['asin']
#                 shop_name = item['shop_name']
#                 metrics = metrics_map.get(asin, {
#                     'cost': 0,
#                     'sales': 0,
#                     'clicks': 0,
#                     'impressions': 0,
#                     'orders': 0,
#                     'acos': 0,
#                     'roas': 0,
#                     'ctr': 0,
#                     'cvr': 0,
#                     'cpc': 0,
#                 })
#
#                 asin_data.append({
#                     'asin': asin,
#                     'shop_name': shop_name,
#                     **metrics
#                 })
#
#         # 计算总页数
#         total_pages = (total + page_size - 1) // page_size
#
#         return JsonResponse({
#             'success': True,
#             'data': {
#                 'asins': asin_data,
#                 'total': total,
#                 'page': page,
#                 'page_size': page_size,
#                 'total_pages': total_pages
#             }
#         })
#
#     except Exception as e:
#         import traceback
#         traceback.print_exc()
#         return JsonResponse({'success': False, 'message': f'服务器错误: {str(e)}'}, status=500)
#
#
# @login_required
# def get_asin_detail_api(request, asin):
#     """
#     获取单个 ASIN 广告详情 API
#     """
#     if request.method != 'GET':
#         return JsonResponse({'success': False, 'message': '只支持GET请求'}, status=405)
#
#     try:
#         # 获取 ASIN 的最新数据
#         latest_data = LingXingAdHourlyData.objects.filter(
#             asin=asin
#         ).select_related('lingxing_shop').order_by('-report_date', '-hour').first()
#
#         if not latest_data:
#             return JsonResponse({'success': False, 'message': 'ASIN 不存在'}, status=404)
#
#         # 汇总数据
#         summary = LingXingAdHourlyData.objects.filter(
#             asin=asin
#         ).aggregate(
#             total_cost=Sum('cost'),
#             total_sales=Sum('sales'),
#             total_clicks=Sum('clicks'),
#             total_impressions=Sum('impressions'),
#             total_orders=Sum('orders')
#         )
#
#         total_cost = summary['total_cost'] or 0
#         total_sales = summary['total_sales'] or 0
#         total_clicks = summary['total_clicks'] or 0
#         total_impressions = summary['total_impressions'] or 0
#         total_orders = summary['total_orders'] or 0
#
#         acos = (total_cost / total_sales * 100) if total_sales > 0 else 0
#         roas = (total_sales / total_cost) if total_cost > 0 else 0
#         ctr = (total_clicks / total_impressions * 100) if total_impressions > 0 else 0
#         cvr = (total_orders / total_clicks * 100) if total_clicks > 0 else 0
#         cpc = (total_cost / total_clicks) if total_clicks > 0 else 0
#
#         data = {
#             'asin': asin,
#             'shop_name': latest_data.lingxing_shop.name if latest_data.lingxing_shop else '未知店铺',
#             'msku': latest_data.msku or '-',
#             'total_cost': round(total_cost, 2),
#             'total_sales': round(total_sales, 2),
#             'total_clicks': int(total_clicks),
#             'total_impressions': int(total_impressions),
#             'total_orders': int(total_orders),
#             'acos': round(acos, 2),
#             'roas': round(roas, 2),
#             'ctr': round(ctr, 2),
#             'cvr': round(cvr, 2),
#             'cpc': round(cpc, 2),
#             'latest_report_date': latest_data.report_date.strftime('%Y-%m-%d') if latest_data.report_date else '-',
#         }
#
#         return JsonResponse({
#             'success': True,
#             'data': data
#         })
#
#     except Exception as e:
#         import traceback
#         traceback.print_exc()
#         return JsonResponse({'success': False, 'message': f'服务器错误: {str(e)}'}, status=500)
