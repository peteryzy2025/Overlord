# Amazon/amazon_jx_views.py

from django.http import JsonResponse
from django.db.models import Q, Count
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.shortcuts import render
from django.utils import timezone
from datetime import datetime, timedelta
import json

from Amazon.models import AmazonPerformanceNotification
from General.models import AmazonShop, User, OperationalAccount
from Amazon.amazon_views import parse_permissions, determine_filter_type_and_value
from Amazon.amazon_order_views import get_date_range_from_option as base_get_date_range
from Amazon.amazon_order_views import get_shop_ids_by_filter


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
def amazon_performance_notifications_page(request):
    """亚马逊绩效通知管理页面渲染"""
    theme = request.COOKIES.get('theme', 'light')
    return render(request, 'amazon_performance_notifications.html', {
        'theme': theme,
        'active_nav': 'amazon_performance',
    })


@login_required
def get_amazon_performance_notifications_api(request):
    """
    获取绩效通知列表（带分页、排序、筛选）
    权限控制：组长看全组+自己，运营看个人，管理员看全部
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': '只支持POST请求'}, status=405)

    try:
        data = json.loads(request.body)
        user = request.user
        permissions = parse_permissions(getattr(user, 'permission', []))

        # 权限控制核心逻辑
        filter_type, filter_value = determine_filter_type_and_value(request, data, permissions)

        # 分页参数
        page = int(data.get('page', 1))
        page_size = int(data.get('page_size', 20))
        page_size = min(page_size, 100)

        # 排序参数
        sort_field = data.get('sort_field', 'date')
        sort_order = data.get('sort_order', 'desc')
        valid_sort_fields = ['date', 'shop_name', 'operator_name', 'ops_group', 'role']
        if sort_field not in valid_sort_fields:
            sort_field = 'date'

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
                    'notifications': [],
                    'total': 0,
                    'page': page,
                    'page_size': page_size,
                    'total_pages': 0,
                    'stats': {'pending_count': 0}
                }
            })

        # 获取权限范围内的店铺
        shop_ids = get_shop_ids_by_filter(filter_type, filter_value)

        # 构建查询条件
        notification_filter = Q(shop_id__in=list(shop_ids))

        # 日期筛选（如果不限则不添加条件）
        if current_start and current_end:
            notification_filter &= Q(date__gte=current_start)
            notification_filter &= Q(date__lte=current_end)

        # 运营人员多选筛选
        operator_ids = data.get('operator_ids', [])
        if operator_ids and 'ops_all' not in permissions:
            # 验证这些运营是否在当前用户权限范围内
            valid_shop_ids = set(shop_ids)
            operator_shops = AmazonShop.objects.filter(
                ops_id__in=operator_ids
            ).values_list('id', flat=True)
            valid_operator_ids = AmazonShop.objects.filter(
                id__in=valid_shop_ids.intersection(operator_shops)
            ).values_list('ops_id', flat=True)
            notification_filter &= Q(shop__ops_id__in=valid_operator_ids)

        # 店铺名称模糊搜索
        shop_name = data.get('shop_name', '').strip()
        if shop_name:
            notification_filter &= Q(shop__shop_name__icontains=shop_name)

        # 主题关键词搜索
        subject_keyword = data.get('subject_keyword', '').strip()
        if subject_keyword:
            notification_filter &= Q(subject__icontains=subject_keyword)

        # 状态筛选
        status_filter = data.get('status_filter', '')
        if status_filter:
            if status_filter == 'needs_attention':
                notification_filter &= Q(needs_attention=1)
            elif status_filter == 'needs_attention_pending':
                notification_filter &= Q(needs_attention=1, is_processed=0)
            elif status_filter == 'processed':
                notification_filter &= Q(is_processed=1)

        # 构建排序
        order_by_prefix = '-' if sort_order == 'desc' else ''
        if sort_field == 'date':
            ordering = f'{order_by_prefix}date'
        elif sort_field == 'shop_name':
            ordering = f'{order_by_prefix}shop__shop_name'
        elif sort_field == 'operator_name':
            ordering = f'{order_by_prefix}shop__ops__first_name'
        elif sort_field == 'ops_group':
            ordering = f'{order_by_prefix}shop__ops__operational_account__ops_group'
        elif sort_field == 'role':
            ordering = f'{order_by_prefix}shop__ops__role'

        # 查询数据（优化：只查询需要的字段并select_related减少查询）
        notifications_queryset = AmazonPerformanceNotification.objects.filter(
            notification_filter
        ).select_related(
            'shop', 'shop__ops', 'shop__ops__operational_account'
        ).only(
            'id', 'shop_id', 'subject', 'date', 'needs_attention', 'is_processed',
            'shop__shop_name', 'shop__ops__first_name', 'shop__ops__role',
            'shop__ops__operational_account__ops_group',
        ).order_by(ordering)

        # 统计未处理数量（关键：基于当前查询集和权限）
        # 如果筛选条件中包含具体运营，则统计该运营的数量
        # 否则统计当前权限范围内的全部
        stats_base_queryset = notifications_queryset
        if operator_ids and len(operator_ids) == 1:
            # 如果只选了一个运营，则统计该运营的未处理数量
            stats_base_queryset = stats_base_queryset.filter(shop__ops_id=operator_ids[0])

        pending_count = stats_base_queryset.filter(
            needs_attention=1, is_processed=0
        ).count() if stats_base_queryset.exists() else 0

        # 分页
        total = notifications_queryset.count()
        paginator = Paginator(notifications_queryset, page_size)
        try:
            notifications_page = paginator.page(page)
        except PageNotAnInteger:
            notifications_page = paginator.page(1)
        except EmptyPage:
            notifications_page = paginator.page(paginator.num_pages)

        # 组装数据
        notifications_data = []
        for notification in notifications_page:
            # 获取运营信息
            operator_name = ''
            role = ''
            ops_group = ''

            if notification.shop and notification.shop.ops:
                operator_name = notification.shop.ops.first_name
                role = notification.shop.ops.role or ''
                try:
                    ops_group = notification.shop.ops.operational_account.ops_group or ''
                except:
                    ops_group = ''

            notifications_data.append({
                'id': notification.id,
                'shop_name': notification.shop.shop_name if notification.shop else '未知店铺',
                'operator_name': operator_name,
                'role': role,
                'ops_group': ops_group,
                'subject': notification.subject,
                'date': notification.date.strftime('%Y-%m-%d') if notification.date else '',
                'needs_attention': notification.needs_attention,
                'is_processed': notification.is_processed,
            })

        return JsonResponse({
            'success': True,
            'data': {
                'notifications': notifications_data,
                'total': total,
                'page': notifications_page.number,
                'page_size': page_size,
                'total_pages': paginator.num_pages,
                'stats': {'pending_count': pending_count}
            }
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({
            'success': False,
            'message': f'服务器错误: {str(e)}'
        }, status=500)


@login_required
def mark_notification_processed_api(request, notification_id):
    """
    标记绩效通知为已处理
    PUT /api/amazon-performance-notifications/<id>/mark-processed/
    """
    if request.method != 'PUT':
        return JsonResponse({'success': False, 'message': '只支持PUT请求'}, status=405)

    try:
        user = request.user
        permissions = parse_permissions(getattr(user, 'permission', []))

        # 获取通知并验证权限
        try:
            notification = AmazonPerformanceNotification.objects.select_related(
                'shop', 'shop__ops'
            ).get(id=notification_id)
        except AmazonPerformanceNotification.DoesNotExist:
            return JsonResponse({
                'success': False,
                'message': '通知不存在'
            }, status=404)

        # 权限验证：确保用户有权限操作此通知
        if 'ops_all' not in permissions:
            # 获取用户有权限的店铺ID列表
            user_shop_ids = get_shop_ids_by_filter('ops', user.id)
            user_shop_ids_list = list(user_shop_ids)
            if notification.shop_id not in user_shop_ids_list:
                # 备选方案：检查店铺是否直接关联当前用户
                if hasattr(notification.shop, 'ops') and notification.shop.ops_id == user.id:
                    pass
                else:
                    return JsonResponse({
                        'success': False,
                        'message': '无权操作此通知'
                    }, status=403)

        # 更新状态
        notification.is_processed = 1
        notification.save(update_fields=['is_processed', 'updated_at'])

        # 返回更新后的数据
        operator_name = notification.shop.ops.first_name if notification.shop and notification.shop.ops else ''
        role = notification.shop.ops.role if notification.shop and notification.shop.ops else ''
        ops_group = ''
        if notification.shop and notification.shop.ops:
            try:
                ops_group = notification.shop.ops.operational_account.ops_group or ''
            except:
                pass

        return JsonResponse({
            'success': True,
            'data': {
                'id': notification.id,
                'shop_name': notification.shop.shop_name if notification.shop else '未知店铺',
                'operator_name': operator_name,
                'role': role,
                'ops_group': ops_group,
                'subject': notification.subject,
                'date': notification.date.strftime('%Y-%m-%d') if notification.date else '',
                'needs_attention': notification.needs_attention,
                'is_processed': notification.is_processed,
            }
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'服务器错误: {str(e)}'
        }, status=500)


@login_required
def get_performance_operators_api(request):
    """
    获取绩效模块可用的运营人员列表（带权限控制）
    组长只能看自己组（包含自己），管理员看全部
    """
    if request.method != 'GET':
        return JsonResponse({'success': False, 'message': '只支持GET请求'}, status=405)

    try:
        user = request.user
        permissions = parse_permissions(getattr(user, 'permission', []))

        # 判断权限范围
        if 'ops_all' in permissions:
            # 管理员：返回所有运营人员
            shops = AmazonShop.objects.filter(ops__isnull=False).select_related('ops')
        elif 'ops_group' in permissions and hasattr(user, 'operational_account') and user.operational_account.ops_group:
            # 组长：返回自己组的运营人员（包含自己）
            group_name = user.operational_account.ops_group
            shops = AmazonShop.objects.filter(
                ops__operational_account__ops_group=group_name
            ).select_related('ops')
        else:
            # 普通运营：只能看到自己
            shops = AmazonShop.objects.filter(ops=user).select_related('ops')

        # 去重并组装数据
        operators_dict = {}
        for shop in shops:
            if shop.ops:
                operators_dict[shop.ops.id] = {
                    'id': shop.ops.id,
                    'first_name': shop.ops.first_name,
                    'group': shop.ops.operational_account.ops_group if hasattr(shop.ops, 'operational_account') else '',
                }

        operators_list = list(operators_dict.values())
        operators_list.sort(key=lambda x: x['first_name'])

        # 添加"全部"选项
        if len(operators_list) > 1:
            operators_list.insert(0, {
                'id': 'all',
                'first_name': '全部人员',
                'group': ''
            })

        return JsonResponse({
            'success': True,
            'data': operators_list
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'获取运营人员失败: {str(e)}'
        }, status=500)