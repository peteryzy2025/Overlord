# # advertisement/view/views_asin_detail.py
#
# import json
# from datetime import datetime, timedelta
# from calendar import monthrange
# from django.contrib.auth.decorators import login_required
# from django.db.models import Q, Sum
# from django.http import JsonResponse
# from django.shortcuts import render
#
# from advertisement.models import LingXingAdHourlyData, LingXingCampaign
# from amazon.models import LingXingAmazonShop
#
#
# @login_required
# def asin_detail_page(request, asin):
#     """
#     ASIN 详细数据页面
#     """
#     return render(request, 'advertisement/asin_detail.html', {
#         'active_nav': 'advertisement_campaigns',
#         'active_page': 'asin_detail',
#         'asin': asin,
#     })
#
#
# @login_required
# def get_asin_daily_data_api(request, asin):
#     """
#     获取 ASIN 每日数据 API（用于趋势图和明细表）
#     """
#     if request.method != 'GET':
#         return JsonResponse({'success': False, 'message': '只支持GET请求'}, status=405)
#
#     try:
#         asin = asin.strip().upper()
#         compare_asin = request.GET.get('compare_asin', '').strip().upper()
#         days = int(request.GET.get('days', 30))
#
#         if not asin:
#             return JsonResponse({'success': False, 'message': 'ASIN不能为空'}, status=400)
#
#         # 限制天数范围
#         days = max(7, min(days, 90))
#
#         # 计算日期范围
#         end_date = datetime.now().date()
#         start_date = end_date - timedelta(days=days-1)
#
#         # 获取主 ASIN 每日数据
#         daily_data = get_asin_daily_summary(asin, start_date, end_date)
#
#         # 如果有对比 ASIN，获取对比数据
#         compare_data = None
#         if compare_asin and compare_asin != asin:
#             compare_data = get_asin_daily_summary(compare_asin, start_date, end_date)
#
#         return JsonResponse({
#             'success': True,
#             'data': {
#                 'asin': asin,
#                 'compare_asin': compare_asin if compare_asin != asin else None,
#                 'date_range': {
#                     'start': start_date.strftime('%Y-%m-%d'),
#                     'end': end_date.strftime('%Y-%m-%d'),
#                     'days': days
#                 },
#                 'daily_data': daily_data,
#                 'compare_daily_data': compare_data
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
# def get_asin_hourly_data_api(request, asin):
#     """
#     获取 ASIN 某天的小时数据 API
#     """
#     if request.method != 'GET':
#         return JsonResponse({'success': False, 'message': '只支持GET请求'}, status=405)
#
#     try:
#         asin = asin.strip().upper()
#         date_str = request.GET.get('date', '')
#
#         if not asin or not date_str:
#             return JsonResponse({'success': False, 'message': 'ASIN和日期不能为空'}, status=400)
#
#         try:
#             query_date = datetime.strptime(date_str, '%Y-%m-%d').date()
#         except:
#             return JsonResponse({'success': False, 'message': '日期格式错误'}, status=400)
#
#         # 获取该日小时数据
#         hourly_data = LingXingAdHourlyData.objects.filter(
#             asin=asin,
#             report_date=query_date
#         ).values('hour').annotate(
#             cost=Sum('cost'),
#             sales=Sum('sales'),
#             clicks=Sum('clicks'),
#             impressions=Sum('impressions'),
#             orders=Sum('orders')
#         ).order_by('hour')
#
#         # 组装24小时数据（缺失小时补0）
#         hourly_map = {h['hour']: h for h in hourly_data}
#         result = []
#         for hour in range(24):
#             data = hourly_map.get(hour, {
#                 'hour': hour,
#                 'cost': 0,
#                 'sales': 0,
#                 'clicks': 0,
#                 'impressions': 0,
#                 'orders': 0
#             })
#
#             # 计算比率
#             ctr = (data['clicks'] / data['impressions'] * 100) if data['impressions'] > 0 else 0
#             cvr = (data['orders'] / data['clicks'] * 100) if data['clicks'] > 0 else 0
#
#             result.append({
#                 'hour': hour,
#                 'hour_display': f'{hour:02d}:00',
#                 'impressions': int(data['impressions'] or 0),
#                 'clicks': int(data['clicks'] or 0),
#                 'orders': int(data['orders'] or 0),
#                 'cost': round(float(data['cost'] or 0), 2),
#                 'sales': round(float(data['sales'] or 0), 2),
#                 'ctr': round(ctr, 2),
#                 'cvr': round(cvr, 2),
#             })
#
#         return JsonResponse({
#             'success': True,
#             'data': {
#                 'asin': asin,
#                 'date': date_str,
#                 'hourly_data': result
#             }
#         })
#
#     except Exception as e:
#         import traceback
#         traceback.print_exc()
#         return JsonResponse({'success': False, 'message': f'服务器错误: {str(e)}'}, status=500)
#
#
# def get_hourly_data_for_asin(asin, query_date):
#     """获取指定 ASIN 和日期的小时数据（辅助函数）"""
#     hourly_data = LingXingAdHourlyData.objects.filter(
#         asin=asin,
#         report_date=query_date
#     ).values('hour').annotate(
#         cost=Sum('cost'),
#         sales=Sum('sales'),
#         clicks=Sum('clicks'),
#         impressions=Sum('impressions'),
#         orders=Sum('orders')
#     ).order_by('hour')
#
#     # 组装24小时数据（缺失小时补0）
#     hourly_map = {h['hour']: h for h in hourly_data}
#     result = []
#     for hour in range(24):
#         data = hourly_map.get(hour, {
#             'hour': hour,
#             'cost': 0,
#             'sales': 0,
#             'clicks': 0,
#             'impressions': 0,
#             'orders': 0
#         })
#
#         # 计算比率
#         ctr = (data['clicks'] / data['impressions'] * 100) if data['impressions'] > 0 else 0
#         cvr = (data['orders'] / data['clicks'] * 100) if data['clicks'] > 0 else 0
#         acos = (data['cost'] / data['sales'] * 100) if data['sales'] > 0 else 0
#         roas = (data['sales'] / data['cost']) if data['cost'] > 0 else 0
#         cpc = (data['cost'] / data['clicks']) if data['clicks'] > 0 else 0
#
#         result.append({
#             'hour': hour,
#             'hour_display': f'{hour:02d}:00',
#             'impressions': int(data['impressions'] or 0),
#             'clicks': int(data['clicks'] or 0),
#             'orders': int(data['orders'] or 0),
#             'cost': round(float(data['cost'] or 0), 2),
#             'sales': round(float(data['sales'] or 0), 2),
#             'ctr': round(ctr, 2),
#             'cvr': round(cvr, 2),
#             'acos': round(acos, 2),
#             'roas': round(roas, 2),
#             'cpc': round(cpc, 2),
#         })
#
#     return result
#
#
# @login_required
# def get_asin_hourly_distribution_api(request, asin):
#     """
#     获取 ASIN 24小时数据（最近24小时或指定日期），支持对比
#     """
#     if request.method != 'GET':
#         return JsonResponse({'success': False, 'message': '只支持GET请求'}, status=405)
#
#     try:
#         asin = asin.strip().upper()
#         compare_asin = request.GET.get('compare_asin', '').strip().upper()
#         date_str = request.GET.get('date', '')
#
#         if not asin:
#             return JsonResponse({'success': False, 'message': 'ASIN不能为空'}, status=400)
#
#         # 如果指定了日期，使用该日期；否则使用最近有数据的日期
#         if date_str:
#             try:
#                 query_date = datetime.strptime(date_str, '%Y-%m-%d').date()
#             except:
#                 return JsonResponse({'success': False, 'message': '日期格式错误'}, status=400)
#         else:
#             # 获取最近有数据的日期
#             latest = LingXingAdHourlyData.objects.filter(asin=asin).order_by('-report_date').first()
#             if not latest:
#                 return JsonResponse({
#                     'success': True,
#                     'data': {
#                         'asin': asin,
#                         'date': '-',
#                         'hourly_distribution': []
#                     }
#                 })
#             query_date = latest.report_date
#
#         # 获取主 ASIN 小时数据
#         result = get_hourly_data_for_asin(asin, query_date)
#
#         # 获取对比 ASIN 小时数据（如果指定了）
#         compare_result = None
#         if compare_asin and compare_asin != asin:
#             compare_result = get_hourly_data_for_asin(compare_asin, query_date)
#
#         return JsonResponse({
#             'success': True,
#             'data': {
#                 'asin': asin,
#                 'compare_asin': compare_asin if compare_asin != asin else None,
#                 'date': query_date.strftime('%Y-%m-%d'),
#                 'hourly_distribution': result,
#                 'compare_hourly_distribution': compare_result
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
# def get_asin_campaigns_api(request, asin):
#     """
#     获取 ASIN 关联的广告活动列表
#     """
#     if request.method != 'GET':
#         return JsonResponse({'success': False, 'message': '只支持GET请求'}, status=405)
#
#     try:
#         asin = asin.strip().upper()
#
#         if not asin:
#             return JsonResponse({'success': False, 'message': 'ASIN不能为空'}, status=400)
#
#         # 获取投放该 ASIN 的活动ID列表（去重）
#         campaign_ids = LingXingAdHourlyData.objects.filter(
#             asin=asin
#         ).values_list('campaign_id', flat=True).distinct()
#
#         # 获取活动详情
#         campaigns = LingXingCampaign.objects.filter(
#             campaign_id__in=campaign_ids
#         ).select_related('lingxing_shop')
#
#         # 获取最近30天的汇总数据
#         end_date = datetime.now().date()
#         start_date = end_date - timedelta(days=29)
#
#         campaign_data = []
#         for campaign in campaigns:
#             # 获取该活动该 ASIN 的最近30天数据
#             summary = LingXingAdHourlyData.objects.filter(
#                 campaign_id=campaign.campaign_id,
#                 asin=asin,
#                 report_date__gte=start_date,
#                 report_date__lte=end_date
#             ).aggregate(
#                 cost=Sum('cost'),
#                 sales=Sum('sales'),
#                 clicks=Sum('clicks'),
#                 impressions=Sum('impressions'),
#                 orders=Sum('orders')
#             )
#
#             cost = summary['cost'] or 0
#             sales = summary['sales'] or 0
#             clicks = summary['clicks'] or 0
#             impressions = summary['impressions'] or 0
#             orders = summary['orders'] or 0
#
#             acos = (cost / sales * 100) if sales > 0 else 0
#
#             campaign_data.append({
#                 'campaign_id': campaign.campaign_id,
#                 'campaign_name': campaign.campaign_name or '未命名',
#                 'shop_name': campaign.lingxing_shop.name if campaign.lingxing_shop else '未知店铺',
#                 'status': campaign.status or '-',
#                 'daily_budget': str(campaign.daily_budget) if campaign.daily_budget else '0.00',
#                 'cost': round(cost, 2),
#                 'sales': round(sales, 2),
#                 'acos': round(acos, 2),
#                 'orders': int(orders),
#             })
#
#         return JsonResponse({
#             'success': True,
#             'data': {
#                 'asin': asin,
#                 'campaigns': campaign_data
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
# def get_asin_summary_api(request, asin):
#     """
#     获取 ASIN 汇总数据（用于顶部信息栏和核心指标卡片）
#     """
#     if request.method != 'GET':
#         return JsonResponse({'success': False, 'message': '只支持GET请求'}, status=405)
#
#     try:
#         asin = asin.strip().upper()
#         compare_asin = request.GET.get('compare_asin', '').strip().upper()
#
#         if not asin:
#             return JsonResponse({'success': False, 'message': 'ASIN不能为空'}, status=400)
#
#         # 最近30天汇总
#         end_date = datetime.now().date()
#         start_date = end_date - timedelta(days=29)
#
#         # 主 ASIN 数据
#         main_summary = get_asin_summary_data(asin, start_date, end_date)
#
#         # 对比 ASIN 数据
#         compare_summary = None
#         if compare_asin and compare_asin != asin:
#             compare_summary = get_asin_summary_data(compare_asin, start_date, end_date)
#
#         # 获取基本信息
#         latest_data = LingXingAdHourlyData.objects.filter(
#             asin=asin
#         ).select_related('lingxing_shop').order_by('-report_date', '-hour').first()
#
#         return JsonResponse({
#             'success': True,
#             'data': {
#                 'asin': asin,
#                 'compare_asin': compare_asin if compare_asin != asin else None,
#                 'basic_info': {
#                     'asin': asin,
#                     'msku': latest_data.msku if latest_data else '-',
#                     'shop_name': latest_data.lingxing_shop.name if latest_data and latest_data.lingxing_shop else '未知店铺',
#                     'latest_date': latest_data.report_date.strftime('%Y-%m-%d') if latest_data else '-',
#                 },
#                 'summary': main_summary,
#                 'compare_summary': compare_summary
#             }
#         })
#
#     except Exception as e:
#         import traceback
#         traceback.print_exc()
#         return JsonResponse({'success': False, 'message': f'服务器错误: {str(e)}'}, status=500)
#
#
# # ========== 辅助函数 ==========
#
# def get_asin_daily_summary(asin, start_date, end_date):
#     """
#     获取 ASIN 每日汇总数据（只返回有数据的日期）
#     """
#     daily_data = LingXingAdHourlyData.objects.filter(
#         asin=asin,
#         report_date__gte=start_date,
#         report_date__lte=end_date
#     ).values('report_date').annotate(
#         cost=Sum('cost'),
#         sales=Sum('sales'),
#         clicks=Sum('clicks'),
#         impressions=Sum('impressions'),
#         orders=Sum('orders')
#     ).order_by('report_date')
#
#     result = []
#     for data in daily_data:
#         cost = data['cost'] or 0
#         sales = data['sales'] or 0
#         clicks = data['clicks'] or 0
#         impressions = data['impressions'] or 0
#         orders = data['orders'] or 0
#
#         # 计算比率
#         ctr = (clicks / impressions * 100) if impressions > 0 else 0
#         cvr = (orders / clicks * 100) if clicks > 0 else 0
#         acos = (cost / sales * 100) if sales > 0 else 0
#         roas = (sales / cost) if cost > 0 else 0
#         cpc = (cost / clicks) if clicks > 0 else 0
#
#         result.append({
#             'date': data['report_date'].strftime('%Y-%m-%d'),
#             'impressions': int(impressions),
#             'clicks': int(clicks),
#             'orders': int(orders),
#             'cost': round(cost, 2),
#             'sales': round(sales, 2),
#             'ctr': round(ctr, 2),
#             'cvr': round(cvr, 2),
#             'acos': round(acos, 2),
#             'roas': round(roas, 2),
#             'cpc': round(cpc, 2),
#         })
#
#     return result
#
#
# def get_asin_summary_data(asin, start_date, end_date):
#     """
#     获取 ASIN 汇总统计数据
#     """
#     summary = LingXingAdHourlyData.objects.filter(
#         asin=asin,
#         report_date__gte=start_date,
#         report_date__lte=end_date
#     ).aggregate(
#         cost=Sum('cost'),
#         sales=Sum('sales'),
#         clicks=Sum('clicks'),
#         impressions=Sum('impressions'),
#         orders=Sum('orders')
#     )
#
#     cost = summary['cost'] or 0
#     sales = summary['sales'] or 0
#     clicks = summary['clicks'] or 0
#     impressions = summary['impressions'] or 0
#     orders = summary['orders'] or 0
#
#     # 计算比率
#     ctr = (clicks / impressions * 100) if impressions > 0 else 0
#     cvr = (orders / clicks * 100) if clicks > 0 else 0
#     acos = (cost / sales * 100) if sales > 0 else 0
#     roas = (sales / cost) if cost > 0 else 0
#     cpc = (cost / clicks) if clicks > 0 else 0
#
#     return {
#         'impressions': int(impressions),
#         'clicks': int(clicks),
#         'orders': int(orders),
#         'cost': round(cost, 2),
#         'sales': round(sales, 2),
#         'ctr': round(ctr, 2),
#         'cvr': round(cvr, 2),
#         'acos': round(acos, 2),
#         'roas': round(roas, 2),
#         'cpc': round(cpc, 2),
#     }
