# Amazon/view/views_amazon_upload_records.py

from django.http import JsonResponse
from django.db.models import Q
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.shortcuts import render
from datetime import datetime, timedelta
import json
from amazon.models import AmazonShopUploadRecord
from general.models import AmazonShop, User, OperationalAccount
from amazon.amazon_views import get_user_operation_permissions, determine_filter_type_and_value
from amazon.amazon_order_views import get_date_range_from_option as base_get_date_range
from amazon.amazon_order_views import get_shop_ids_by_filter


# 扩展日期范围函数，支持'unlimited'
def get_date_range_from_option(option):
    """
    获取日期范围，支持'unlimited'选项
    返回 (start_date, end_date) 或 (None, None) 当选择不限时
    """
    if option == 'unlimited':
        return None, None
    return base_get_date_range(option)


@login_required(login_url='/login/')
def amazon_upload_records_page(request):
    """亚马逊店铺上货情况页面渲染"""
    return render(request, 'amazon_upload_records.html', {
        'active_nav': 'amazon_upload_records',
        'active_page': 'amazon_upload_records',
    })


@login_required
def get_amazon_upload_records_api(request):
    """
    获取店铺上货记录列表（带分页、排序、筛选）
    权限控制：组长看全组+自己，运营看个人，管理员看全部
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': '只支持POST请求'}, status=405)

    try:
        data = json.loads(request.body)
        user = request.user
        permissions = get_user_operation_permissions(user)

        # 权限控制核心逻辑
        filter_type, filter_value = determine_filter_type_and_value(request, data, permissions)

        # 分页参数
        page = int(data.get('page', 1))
        page_size = int(data.get('page_size', 20))
        page_size = min(page_size, 100)

        # 排序参数
        sort_field = data.get('sort_field', 'upload_time')
        sort_order = data.get('sort_order', 'desc')
        valid_sort_fields = ['upload_time', 'file_name', 'batch_id', 'shop_name', 'operator_name', 'ops_group']
        if sort_field not in valid_sort_fields:
            sort_field = 'upload_time'

        # 日期参数
        date_range_option = data.get('date_range', 'unlimited')  # 默认不限
        start_date_str = data.get('start_date', '')
        end_date_str = data.get('end_date', '')

        # 解析日期
        current_start, current_end = None, None
        if date_range_option == 'custom' and start_date_str and end_date_str:
            try:
                current_start = datetime.strptime(start_date_str.split(' ')[0], '%Y-%m-%d').date()
                current_end = datetime.strptime(end_date_str.split(' ')[0], '%Y-%m-%d').date()
            except:
                pass

        if not current_start or not current_end:
            current_start, current_end = get_date_range_from_option(date_range_option)

        # 无权限直接返回空
        if filter_type == 'none':
            return JsonResponse({
                'success': True,
                'data': {
                    'records': [],
                    'total': 0,
                    'page': page,
                    'page_size': page_size,
                    'total_pages': 0
                }
            })

        # 获取权限范围内的店铺（传入user进行公司限定）
        shop_ids = get_shop_ids_by_filter(filter_type, filter_value, user=user)

        # 构建查询条件
        record_filter = Q(shop_id__in=list(shop_ids))

        # 日期筛选（如果不限则不添加条件）
        if current_start and current_end:
            # upload_time 是 DateTimeField，需要处理时间部分
            start_datetime = datetime.combine(current_start, datetime.min.time())
            end_datetime = datetime.combine(current_end, datetime.max.time())
            record_filter &= Q(upload_time__gte=start_datetime)
            record_filter &= Q(upload_time__lte=end_datetime)

        # 运营人员多选筛选
        operator_ids = data.get('operator_ids', [])
        if operator_ids:
            if 'ops_all' in permissions:
                record_filter &= Q(shop__ops_id__in=operator_ids)
            elif 'ops_group' in permissions:
                valid_shop_ids = set(shop_ids)
                base_shop_qs = AmazonShop.objects.all()
                if hasattr(user, 'company') and user.company:
                    base_shop_qs = base_shop_qs.filter(company=user.company)
                operator_shops = base_shop_qs.filter(ops_id__in=operator_ids).values_list('id', flat=True)
                valid_operator_ids = base_shop_qs.filter(
                    id__in=valid_shop_ids.intersection(operator_shops)
                ).values_list('ops_id', flat=True)
                record_filter &= Q(shop__ops_id__in=valid_operator_ids)
            else:
                record_filter &= Q(shop__ops_id=user.id)

        # 店铺名称模糊搜索
        shop_name = data.get('shop_name', '').strip()
        if shop_name:
            record_filter &= Q(shop__shop_name__icontains=shop_name)

        # 文件名称模糊搜索
        file_name_keyword = data.get('file_name_keyword', '').strip()
        if file_name_keyword:
            record_filter &= Q(file_name__icontains=file_name_keyword)

        # 状态筛选
        status_filter = data.get('status_filter', '')
        if status_filter:
            record_filter &= Q(status=status_filter)

        # 构建排序
        order_by_prefix = '-' if sort_order == 'desc' else ''
        if sort_field == 'upload_time':
            ordering = f'{order_by_prefix}upload_time'
        elif sort_field == 'file_name':
            ordering = f'{order_by_prefix}file_name'
        elif sort_field == 'batch_id':
            ordering = f'{order_by_prefix}batch_id'
        elif sort_field == 'shop_name':
            ordering = f'{order_by_prefix}shop__shop_name'
        elif sort_field == 'operator_name':
            ordering = f'{order_by_prefix}shop__ops__first_name'
        elif sort_field == 'ops_group':
            ordering = f'{order_by_prefix}shop__ops__operational_account__ops_group'

        # 查询数据（优化：只查询需要的字段并select_related减少查询）
        records_queryset = AmazonShopUploadRecord.objects.filter(
            record_filter
        ).select_related(
            'shop', 'shop__ops', 'shop__ops__operational_account'
        ).only(
            'batch_id', 'file_name', 'status', 'upload_time', 'sku_success', 'submitted',
            'shop__shop_name', 'shop__ops__first_name',
            'shop__ops__operational_account__ops_group',
        ).order_by(ordering)

        # 分页
        total = records_queryset.count()
        paginator = Paginator(records_queryset, page_size)
        try:
            records_page = paginator.page(page)
        except PageNotAnInteger:
            records_page = paginator.page(1)
        except EmptyPage:
            records_page = paginator.page(paginator.num_pages)

        # 组装数据
        records_data = []
        for record in records_page:
            operator_name = ''
            ops_group = ''

            if record.shop and record.shop.ops:
                operator_name = record.shop.ops.first_name
                try:
                    ops_group = record.shop.ops.operational_account.ops_group or ''
                except:
                    ops_group = ''

            records_data.append({
                'batch_id': record.batch_id,
                'file_name': record.file_name,
                'status': record.status,
                'status_display': record.get_status_display(),
                'upload_time': record.upload_time.strftime('%Y-%m-%d %H:%M') if record.upload_time else '',
                'sku_success': record.sku_success or 0,
                'submitted': record.submitted or 0,
                'sku_progress': f"{record.sku_success or 0}/{record.submitted or 0}",
                'shop_name': record.shop.shop_name if record.shop else '未知店铺',
                'operator_name': operator_name,
                'ops_group': ops_group,
            })

        return JsonResponse({
            'success': True,
            'data': {
                'records': records_data,
                'total': total,
                'page': records_page.number,
                'page_size': page_size,
                'total_pages': paginator.num_pages
            }
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({
            'success': False,
            'message': f'服务器错误: {str(e)}'
        }, status=500)
