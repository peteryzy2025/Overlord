# advertisement/view/views_campaign.py

import json
from datetime import datetime
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import render

from advertisement.models import LingXingCampaign
from amazon.models import LingXingAmazonShop


@login_required
def campaign_list_page(request):
    """
    广告活动列表页面
    """
    return render(request, 'advertisement/campaign_list.html', {
        'active_nav': 'advertisement_campaigns',
        'active_page': 'campaign_list',
    })


@login_required
def get_campaign_list_api(request):
    """
    获取广告活动列表数据 API
    支持分页、筛选
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': '只支持POST请求'}, status=405)

    try:
        data = json.loads(request.body)
        user = request.user

        # 分页参数
        page = int(data.get('page', 1))
        page_size = int(data.get('page_size', 20))
        page_size = min(page_size, 100)  # 最多100条

        # 日期筛选
        date_range_option = data.get('date_range', 'all')
        start_date_str = data.get('start_date', '')
        end_date_str = data.get('end_date', '')

        # 其他筛选条件
        campaign_name_filter = data.get('campaign_name', '').strip()
        shop_name_filter = data.get('shop_name', '').strip()

        # 多选筛选条件
        campaign_type_filter = data.get('campaign_type', '').strip()
        campaign_type_list = [s.strip() for s in campaign_type_filter.split(',') if s.strip()] if campaign_type_filter else []

        status_filter = data.get('status', '').strip()
        status_list = [s.strip() for s in status_filter.split(',') if s.strip()] if status_filter else []

        serving_status_filter = data.get('serving_status', '').strip()
        serving_status_list = [s.strip() for s in serving_status_filter.split(',') if s.strip()] if serving_status_filter else []

        targeting_type_filter = data.get('targeting_type', '').strip()
        targeting_type_list = [s.strip() for s in targeting_type_filter.split(',') if s.strip()] if targeting_type_filter else []

        # 解析日期范围
        current_start, current_end = None, None
        if start_date_str and end_date_str:
            try:
                current_start = datetime.strptime(start_date_str.split(' ')[0], '%Y-%m-%d').date()
                current_end = datetime.strptime(end_date_str.split(' ')[0], '%Y-%m-%d').date()
            except:
                pass

        # ========== 构建查询条件 ==========
        campaign_filter = Q()

        # 日期筛选（根据开始日期）
        if current_start and current_end:
            campaign_filter &= Q(start_date__gte=current_start)
            campaign_filter &= Q(start_date__lte=current_end)

        # 活动名称模糊查询
        if campaign_name_filter:
            campaign_filter &= Q(campaign_name__icontains=campaign_name_filter)

        # 店铺名称模糊查询
        if shop_name_filter:
            campaign_filter &= Q(lingxing_shop__name__icontains=shop_name_filter)

        # 活动类型多选
        if campaign_type_list:
            if len(campaign_type_list) == 1:
                campaign_filter &= Q(campaign_type=campaign_type_list[0])
            else:
                campaign_filter &= Q(campaign_type__in=campaign_type_list)

        # 状态多选
        if status_list:
            if len(status_list) == 1:
                campaign_filter &= Q(status=status_list[0])
            else:
                campaign_filter &= Q(status__in=status_list)

        # 投放状态多选
        if serving_status_list:
            if len(serving_status_list) == 1:
                campaign_filter &= Q(serving_status=serving_status_list[0])
            else:
                campaign_filter &= Q(serving_status__in=serving_status_list)

        # 投放方式多选
        if targeting_type_list:
            if len(targeting_type_list) == 1:
                campaign_filter &= Q(targeting_type=targeting_type_list[0])
            else:
                campaign_filter &= Q(targeting_type__in=targeting_type_list)

        # ========== 构建最终 queryset ==========
        campaigns_queryset = LingXingCampaign.objects.filter(campaign_filter) \
            .select_related('lingxing_shop') \
            .order_by('-last_updated_at')

        # ========== 分页 ==========
        paginator = Paginator(campaigns_queryset, page_size)
        total = paginator.count

        try:
            page_obj = paginator.page(page)
        except PageNotAnInteger:
            page_obj = paginator.page(1)
        except EmptyPage:
            page_obj = paginator.page(paginator.num_pages)

        # ========== 组装返回数据 ==========
        campaigns_data = []
        for campaign in page_obj:
            shop_name = campaign.lingxing_shop.name if campaign.lingxing_shop else '未知店铺'
            
            campaigns_data.append({
                'campaign_id': campaign.campaign_id,
                'campaign_name': campaign.campaign_name or '',
                'shop_name': shop_name,
                'campaign_type': campaign.campaign_type or '',
                'campaign_type_display': campaign.get_campaign_type_display() if campaign.campaign_type else '',
                'status': campaign.status or '',
                'status_display': campaign.get_status_display() if campaign.status else '',
                'serving_status': campaign.serving_status or '',
                'serving_status_display': campaign.get_serving_status_display() if campaign.serving_status else '',
                'targeting_type': campaign.targeting_type or '',
                'targeting_type_display': campaign.get_targeting_type_display() if campaign.targeting_type else '',
                'daily_budget': str(campaign.daily_budget) if campaign.daily_budget else '0.00',
                'start_date': campaign.start_date.strftime('%Y-%m-%d') if campaign.start_date else '',
                'end_date': campaign.end_date.strftime('%Y-%m-%d') if campaign.end_date else '',
                'last_updated_at': campaign.last_updated_at.strftime('%Y-%m-%d %H:%M:%S') if campaign.last_updated_at else '',
            })

        return JsonResponse({
            'success': True,
            'data': {
                'campaigns': campaigns_data,
                'total': total,
                'page': page,
                'page_size': page_size,
                'total_pages': paginator.num_pages
            }
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({'success': False, 'message': f'服务器错误: {str(e)}'}, status=500)


@login_required
def get_campaign_detail_api(request, campaign_id):
    """
    获取单个广告活动详情 API
    """
    if request.method != 'GET':
        return JsonResponse({'success': False, 'message': '只支持GET请求'}, status=405)

    try:
        campaign = LingXingCampaign.objects.select_related('lingxing_shop').get(campaign_id=campaign_id)
        
        shop_name = campaign.lingxing_shop.name if campaign.lingxing_shop else '未知店铺'
        
        data = {
            'campaign_id': campaign.campaign_id,
            'campaign_name': campaign.campaign_name or '',
            'shop_name': shop_name,
            'campaign_type': campaign.campaign_type or '',
            'campaign_type_display': campaign.get_campaign_type_display() if campaign.campaign_type else '',
            'status': campaign.status or '',
            'status_display': campaign.get_status_display() if campaign.status else '',
            'serving_status': campaign.serving_status or '',
            'serving_status_display': campaign.get_serving_status_display() if campaign.serving_status else '',
            'targeting_type': campaign.targeting_type or '',
            'targeting_type_display': campaign.get_targeting_type_display() if campaign.targeting_type else '',
            'daily_budget': str(campaign.daily_budget) if campaign.daily_budget else '0.00',
            'start_date': campaign.start_date.strftime('%Y-%m-%d') if campaign.start_date else '',
            'end_date': campaign.end_date.strftime('%Y-%m-%d') if campaign.end_date else '',
            'creation_date': campaign.creation_date.strftime('%Y-%m-%d') if campaign.creation_date else '',
            'portfolio_id': campaign.portfolio_id,
            'bidding': campaign.bidding or {},
            'first_seen_at': campaign.first_seen_at.strftime('%Y-%m-%d %H:%M:%S') if campaign.first_seen_at else '',
            'last_updated_at': campaign.last_updated_at.strftime('%Y-%m-%d %H:%M:%S') if campaign.last_updated_at else '',
        }

        return JsonResponse({
            'success': True,
            'data': data
        })

    except LingXingCampaign.DoesNotExist:
        return JsonResponse({'success': False, 'message': '广告活动不存在'}, status=404)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({'success': False, 'message': f'服务器错误: {str(e)}'}, status=500)


@login_required
def batch_update_campaign_status_api(request):
    """
    批量更新广告活动状态 API
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': '只支持POST请求'}, status=405)

    try:
        data = json.loads(request.body)
        campaign_ids = data.get('campaign_ids', [])
        new_status = data.get('status', '')

        if not campaign_ids:
            return JsonResponse({'success': False, 'message': '请选择要更新的广告活动'}, status=400)

        if not new_status:
            return JsonResponse({'success': False, 'message': '请指定新的状态'}, status=400)

        # 验证状态值是否有效
        valid_statuses = [choice[0] for choice in LingXingCampaign.Status.choices]
        if new_status not in valid_statuses:
            return JsonResponse({'success': False, 'message': f'无效的状态值: {new_status}'}, status=400)

        # 批量更新
        updated_count = LingXingCampaign.objects.filter(
            campaign_id__in=campaign_ids
        ).update(status=new_status)

        return JsonResponse({
            'success': True,
            'message': f'成功更新 {updated_count} 个广告活动',
            'updated_count': updated_count
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({'success': False, 'message': f'服务器错误: {str(e)}'}, status=500)
