# # advertisement/view/views_campaign.py
#
# import json
# from datetime import datetime, timedelta
# from calendar import monthrange
# from django.contrib.auth.decorators import login_required
# from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
# from django.db.models import Q, Sum
# from django.http import JsonResponse
# from django.shortcuts import render
#
# from advertisement.models import LingXingCampaign, LingXingAdHourlyData
# from amazon.models import LingXingAmazonShop
#
#
# @login_required
# def campaign_list_page(request):
#     """
#     广告活动列表页面
#     """
#     return render(request, 'advertisement/campaign_list.html', {
#         'active_nav': 'advertisement_campaigns',
#         'active_page': 'campaign_list',
#     })
#
#
# @login_required
# def get_campaign_list_api(request):
#     """
#     获取广告活动列表数据 API
#     支持分页、筛选，包含广告效果数据汇总
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
#         page_size = min(page_size, 100)  # 最多100条
#
#         # 广告日期范围筛选（用于效果数据汇总）
#         ad_start_date_str = data.get('ad_start_date', '')
#         ad_end_date_str = data.get('ad_end_date', '')
#
#         # Campaign 日期筛选（保留原有功能）
#         start_date_str = data.get('start_date', '')
#         end_date_str = data.get('end_date', '')
#
#         # 其他筛选条件
#         campaign_name_filter = data.get('campaign_name', '').strip()
#         shop_name_filter = data.get('shop_name', '').strip()
#
#         # 多选筛选条件
#         campaign_type_filter = data.get('campaign_type', '').strip()
#         campaign_type_list = [s.strip() for s in campaign_type_filter.split(',') if s.strip()] if campaign_type_filter else []
#
#         status_filter = data.get('status', '').strip()
#         status_list = [s.strip() for s in status_filter.split(',') if s.strip()] if status_filter else []
#
#         serving_status_filter = data.get('serving_status', '').strip()
#         serving_status_list = [s.strip() for s in serving_status_filter.split(',') if s.strip()] if serving_status_filter else []
#
#         targeting_type_filter = data.get('targeting_type', '').strip()
#         targeting_type_list = [s.strip() for s in targeting_type_filter.split(',') if s.strip()] if targeting_type_filter else []
#
#         # 解析广告日期范围（效果数据）
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
#         # 解析 Campaign 日期范围（原有功能）
#         campaign_start_date, campaign_end_date = None, None
#         if start_date_str and end_date_str:
#             try:
#                 campaign_start_date = datetime.strptime(start_date_str.split(' ')[0], '%Y-%m-%d').date()
#                 campaign_end_date = datetime.strptime(end_date_str.split(' ')[0], '%Y-%m-%d').date()
#             except:
#                 pass
#
#         # ========== 构建 Campaign 查询条件 ==========
#         campaign_filter = Q()
#
#         # Campaign 日期筛选（根据开始日期）
#         if campaign_start_date and campaign_end_date:
#             campaign_filter &= Q(start_date__gte=campaign_start_date)
#             campaign_filter &= Q(start_date__lte=campaign_end_date)
#
#         # 活动名称模糊查询
#         if campaign_name_filter:
#             campaign_filter &= Q(campaign_name__icontains=campaign_name_filter)
#
#         # 店铺名称模糊查询
#         if shop_name_filter:
#             campaign_filter &= Q(lingxing_shop__name__icontains=shop_name_filter)
#
#         # 活动类型多选
#         if campaign_type_list:
#             if len(campaign_type_list) == 1:
#                 campaign_filter &= Q(campaign_type=campaign_type_list[0])
#             else:
#                 campaign_filter &= Q(campaign_type__in=campaign_type_list)
#
#         # 状态多选
#         if status_list:
#             if len(status_list) == 1:
#                 campaign_filter &= Q(status=status_list[0])
#             else:
#                 campaign_filter &= Q(status__in=status_list)
#
#         # 投放状态多选
#         if serving_status_list:
#             if len(serving_status_list) == 1:
#                 campaign_filter &= Q(serving_status=serving_status_list[0])
#             else:
#                 campaign_filter &= Q(serving_status__in=serving_status_list)
#
#         # 投放方式多选
#         if targeting_type_list:
#             if len(targeting_type_list) == 1:
#                 campaign_filter &= Q(targeting_type=targeting_type_list[0])
#             else:
#                 campaign_filter &= Q(targeting_type__in=targeting_type_list)
#
#         # ========== 构建最终 queryset ==========
#         campaigns_queryset = LingXingCampaign.objects.filter(campaign_filter) \
#             .select_related('lingxing_shop') \
#             .order_by('-last_updated_at')
#
#         # ========== 分页 ==========
#         paginator = Paginator(campaigns_queryset, page_size)
#         total = paginator.count
#
#         try:
#             page_obj = paginator.page(page)
#         except PageNotAnInteger:
#             page_obj = paginator.page(1)
#         except EmptyPage:
#             page_obj = paginator.page(paginator.num_pages)
#
#         # ========== 获取当前页所有 Campaign ID ==========
#         campaign_ids = [c.campaign_id for c in page_obj]
#
#         # ========== 批量查询效果数据 ==========
#         campaign_metrics = {}
#         if campaign_ids and ad_start_date and ad_end_date:
#             # 使用 campaign_id 字段查询（不是 id）
#             hourly_data = LingXingAdHourlyData.objects.filter(
#                 campaign_id__in=campaign_ids,
#                 report_date__gte=ad_start_date,
#                 report_date__lte=ad_end_date
#             ).values('campaign_id').annotate(
#                 total_cost=Sum('cost'),
#                 total_sales=Sum('sales'),
#                 total_clicks=Sum('clicks'),
#                 total_impressions=Sum('impressions'),
#                 total_orders=Sum('orders')
#             )
#
#             for item in hourly_data:
#                 campaign_id = item['campaign_id']
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
#                 campaign_metrics[campaign_id] = {
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
#         # ========== 组装返回数据 ==========
#         campaigns_data = []
#         for campaign in page_obj:
#             shop_name = campaign.lingxing_shop.name if campaign.lingxing_shop else '未知店铺'
#
#             # 获取效果数据（如果没有则显示为 0 或 -）
#             metrics = campaign_metrics.get(campaign.campaign_id, {
#                 'cost': 0,
#                 'sales': 0,
#                 'clicks': 0,
#                 'impressions': 0,
#                 'orders': 0,
#                 'acos': 0,
#                 'roas': 0,
#                 'ctr': 0,
#                 'cvr': 0,
#                 'cpc': 0,
#             })
#
#             campaigns_data.append({
#                 'campaign_id': campaign.campaign_id,
#                 'campaign_name': campaign.campaign_name or '',
#                 'shop_name': shop_name,
#                 'campaign_type': campaign.campaign_type or '',
#                 'campaign_type_display': campaign.get_campaign_type_display() if campaign.campaign_type else '',
#                 'status': campaign.status or '',
#                 'status_display': campaign.get_status_display() if campaign.status else '',
#                 'serving_status': campaign.serving_status or '',
#                 'serving_status_display': campaign.get_serving_status_display() if campaign.serving_status else '',
#                 'targeting_type': campaign.targeting_type or '',
#                 'targeting_type_display': campaign.get_targeting_type_display() if campaign.targeting_type else '',
#                 'daily_budget': str(campaign.daily_budget) if campaign.daily_budget else '0.00',
#                 'start_date': campaign.start_date.strftime('%Y-%m-%d') if campaign.start_date else '',
#                 'end_date': campaign.end_date.strftime('%Y-%m-%d') if campaign.end_date else '',
#                 'last_updated_at': campaign.last_updated_at.strftime('%Y-%m-%d %H:%M:%S') if campaign.last_updated_at else '',
#                 # 效果数据
#                 'cost': metrics['cost'],
#                 'sales': metrics['sales'],
#                 'clicks': metrics['clicks'],
#                 'impressions': metrics['impressions'],
#                 'orders': metrics['orders'],
#                 'acos': metrics['acos'],
#                 'roas': metrics['roas'],
#                 'ctr': metrics['ctr'],
#                 'cvr': metrics['cvr'],
#                 'cpc': metrics['cpc'],
#             })
#
#         return JsonResponse({
#             'success': True,
#             'data': {
#                 'campaigns': campaigns_data,
#                 'total': total,
#                 'page': page,
#                 'page_size': page_size,
#                 'total_pages': paginator.num_pages
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
# def get_campaign_detail_api(request, campaign_id):
#     """
#     获取单个广告活动详情 API
#     """
#     if request.method != 'GET':
#         return JsonResponse({'success': False, 'message': '只支持GET请求'}, status=405)
#
#     try:
#         campaign = LingXingCampaign.objects.select_related('lingxing_shop').get(campaign_id=campaign_id)
#
#         shop_name = campaign.lingxing_shop.name if campaign.lingxing_shop else '未知店铺'
#
#         data = {
#             'campaign_id': campaign.campaign_id,
#             'campaign_name': campaign.campaign_name or '',
#             'shop_name': shop_name,
#             'campaign_type': campaign.campaign_type or '',
#             'campaign_type_display': campaign.get_campaign_type_display() if campaign.campaign_type else '',
#             'status': campaign.status or '',
#             'status_display': campaign.get_status_display() if campaign.status else '',
#             'serving_status': campaign.serving_status or '',
#             'serving_status_display': campaign.get_serving_status_display() if campaign.serving_status else '',
#             'targeting_type': campaign.targeting_type or '',
#             'targeting_type_display': campaign.get_targeting_type_display() if campaign.targeting_type else '',
#             'daily_budget': str(campaign.daily_budget) if campaign.daily_budget else '0.00',
#             'start_date': campaign.start_date.strftime('%Y-%m-%d') if campaign.start_date else '',
#             'end_date': campaign.end_date.strftime('%Y-%m-%d') if campaign.end_date else '',
#             'creation_date': campaign.creation_date.strftime('%Y-%m-%d') if campaign.creation_date else '',
#             'portfolio_id': campaign.portfolio_id,
#             'bidding': campaign.bidding or {},
#             'first_seen_at': campaign.first_seen_at.strftime('%Y-%m-%d %H:%M:%S') if campaign.first_seen_at else '',
#             'last_updated_at': campaign.last_updated_at.strftime('%Y-%m-%d %H:%M:%S') if campaign.last_updated_at else '',
#         }
#
#         return JsonResponse({
#             'success': True,
#             'data': data
#         })
#
#     except LingXingCampaign.DoesNotExist:
#         return JsonResponse({'success': False, 'message': '广告活动不存在'}, status=404)
#     except Exception as e:
#         import traceback
#         traceback.print_exc()
#         return JsonResponse({'success': False, 'message': f'服务器错误: {str(e)}'}, status=500)
#
#
# @login_required
# def batch_update_campaign_status_api(request):
#     """
#     批量更新广告活动状态 API
#     """
#     if request.method != 'POST':
#         return JsonResponse({'success': False, 'message': '只支持POST请求'}, status=405)
#
#     try:
#         data = json.loads(request.body)
#         campaign_ids = data.get('campaign_ids', [])
#         new_status = data.get('status', '')
#
#         if not campaign_ids:
#             return JsonResponse({'success': False, 'message': '请选择要更新的广告活动'}, status=400)
#
#         if not new_status:
#             return JsonResponse({'success': False, 'message': '请指定新的状态'}, status=400)
#
#         # 验证状态值是否有效
#         valid_statuses = [choice[0] for choice in LingXingCampaign.Status.choices]
#         if new_status not in valid_statuses:
#             return JsonResponse({'success': False, 'message': f'无效的状态值: {new_status}'}, status=400)
#
#         # 批量更新
#         updated_count = LingXingCampaign.objects.filter(
#             campaign_id__in=campaign_ids
#         ).update(status=new_status)
#
#         return JsonResponse({
#             'success': True,
#             'message': f'成功更新 {updated_count} 个广告活动',
#             'updated_count': updated_count
#         })
#
#     except Exception as e:
#         import traceback
#         traceback.print_exc()
#         return JsonResponse({'success': False, 'message': f'服务器错误: {str(e)}'}, status=500)
