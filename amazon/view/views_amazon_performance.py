# Amazon/view/views_amazon_performance.py

from django.http import JsonResponse
from django.db.models import Q, Count
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.shortcuts import render
from datetime import datetime, timedelta
import json
from amazon.models import AmazonPerformanceNotification
from general.models import AmazonShop, User, OperationalAccount
from amazon.amazon_views import get_user_operation_permissions, determine_filter_type_and_value
from amazon.amazon_order_views import get_date_range_from_option as base_get_date_range
from amazon.amazon_order_views import get_shop_ids_by_filter
from api.WX.wx import send_wechat_work_message
from amazon.services.amazon_performance_service import (
    send_performance_notifications,
    get_pending_performance_stats
)


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
    return render(request, 'amazon_performance_notifications.html', {
        'active_nav': 'amazon_performance_notifications',
        'active_page': 'amazon_performance_notifications',
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
        permissions = get_user_operation_permissions(user)

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

        # 获取权限范围内的店铺（传入user进行公司限定）
        shop_ids = get_shop_ids_by_filter(filter_type, filter_value, user=user)

        # 构建查询条件
        notification_filter = Q(shop_id__in=list(shop_ids))

        # 日期筛选（如果不限则不添加条件）
        if current_start and current_end:
            notification_filter &= Q(date__gte=current_start)
            notification_filter &= Q(date__lte=current_end)

        # 运营分组多选筛选
        ops_groups = data.get('ops_groups', [])
        if ops_groups:
            notification_filter &= Q(shop__ops__operational_account__ops_group__in=ops_groups)

        # 运营人员多选筛选
        operator_ids = data.get('operator_ids', [])
        if operator_ids:  # 只要有选择运营人员，就应用筛选（无论权限）
            if 'ops_all' in permissions:
                # 管理员：直接应用筛选，无需额外权限验证
                notification_filter &= Q(shop__ops_id__in=operator_ids)
            elif 'ops_group' in permissions:
                # 组长：需要验证运营是否在本组权限范围内
                valid_shop_ids = set(shop_ids)
                # 获取用户公司的店铺（公司限定）
                base_shop_qs = AmazonShop.objects.all()
                if hasattr(user, 'company') and user.company:
                    base_shop_qs = base_shop_qs.filter(company=user.company)
                operator_shops = base_shop_qs.filter(ops_id__in=operator_ids).values_list('id', flat=True)
                valid_operator_ids = base_shop_qs.filter(
                    id__in=valid_shop_ids.intersection(operator_shops)
                ).values_list('ops_id', flat=True)
                notification_filter &= Q(shop__ops_id__in=valid_operator_ids)
            else:
                # 普通运营：理论上不应该传operator_ids，但如果传了，只显示自己的数据
                notification_filter &= Q(shop__ops_id=user.id)

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
        stats_base_queryset = notifications_queryset
        if operator_ids and len(operator_ids) == 1:
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
def notify_operators_preview_api(request):
    """
    预览待通知的运营人员列表
    POST /api/amazon-performance-notifications/notify-operators/preview/
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': '只支持POST请求'}, status=405)

    try:
        data = json.loads(request.body)
        user = request.user
        permissions = get_user_operation_permissions(user)

        # 使用与列表查询相同的权限和筛选逻辑
        filter_type, filter_value = determine_filter_type_and_value(request, data, permissions)

        if filter_type == 'none':
            return JsonResponse({
                'success': True,
                'data': {
                    'operators': [],
                    'total_pending': 0
                }
            })

        # 获取可见店铺范围（传入user进行公司限定）
        shop_ids = get_shop_ids_by_filter(filter_type, filter_value, user=user)

        # 构建基础查询（仅待处理）
        notification_filter = Q(
            shop_id__in=list(shop_ids),
            needs_attention=1,
            is_processed=0
        )

        # 日期筛选
        date_range_option = data.get('date_range', 'unlimited')
        start_date_str = data.get('start_date', '')
        end_date_str = data.get('end_date', '')

        current_start, current_end = None, None
        if date_range_option == 'custom' and start_date_str and end_date_str:
            try:
                current_start = datetime.strptime(start_date_str.split(' ')[0], '%Y-%m-%d').date()
                current_end = datetime.strptime(end_date_str.split(' ')[0], '%Y-%m-%d').date()
            except:
                pass

        if not current_start or not current_end:
            current_start, current_end = get_date_range_from_option(date_range_option)

        if current_start and current_end:
            notification_filter &= Q(date__gte=current_start)
            notification_filter &= Q(date__lte=current_end)

        # 店铺名称和关键词筛选
        shop_name = data.get('shop_name', '').strip()
        if shop_name:
            notification_filter &= Q(shop__shop_name__icontains=shop_name)

        subject_keyword = data.get('subject_keyword', '').strip()
        if subject_keyword:
            notification_filter &= Q(subject__icontains=subject_keyword)

        # 根据权限过滤通知对象
        operators_query = Q()
        if 'ops_all' in permissions:
            # 管理员：可以通知所有筛选结果中的运营
            pass
        elif 'ops_group' in permissions and hasattr(user, 'operational_account') and user.operational_account.ops_group:
            # 组长：只能通知本组成员
            group_name = user.operational_account.ops_group
            operators_query &= Q(shop__ops__operational_account__ops_group=group_name)
        else:
            # 普通运营：无通知权限
            return JsonResponse({
                'success': True,
                'data': {
                    'operators': [],
                    'total_pending': 0
                }
            })

        # 聚合统计每个运营的待处理数量
        pending_stats = AmazonPerformanceNotification.objects.filter(
            notification_filter & operators_query
        ).values(
            'shop__ops_id',
            'shop__ops__first_name'
        ).annotate(
            pending_count=Count('id')
        ).order_by('-pending_count')

        operators_list = [
            {
                'operator_id': item['shop__ops_id'],
                'operator_name': item['shop__ops__first_name'] or '未知姓名',
                'pending_count': item['pending_count']
            }
            for item in pending_stats if item['shop__ops_id']
        ]

        total_pending = sum(item['pending_count'] for item in operators_list)

        return JsonResponse({
            'success': True,
            'data': {
                'operators': operators_list,
                'total_pending': total_pending
            }
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'服务器错误: {str(e)}'
        }, status=500)


@login_required
def notify_operators_api(request):
    """
    执行通知运营人员
    POST /api/amazon-performance-notifications/notify-operators/
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': '只支持POST请求'}, status=405)

    try:
        data = json.loads(request.body)
        user = request.user
        permissions = get_user_operation_permissions(user)

        if 'ops_all' not in permissions and 'ops_group' not in permissions:
            return JsonResponse({
                'success': False,
                'message': '无权操作：需要 ops_all 或 ops_group 权限'
            }, status=403)

        filter_type, filter_value = determine_filter_type_and_value(request, data, permissions)

        if filter_type == 'none':
            return JsonResponse({
                'success': True,
                'data': {
                    'success_count': 0,
                    'fail_count': 0,
                    'fail_details': []
                }
            })

        shop_ids = get_shop_ids_by_filter(filter_type, filter_value, user=user)

        # 使用Q对象构建基础筛选条件
        base_filter = Q(
            needs_attention=1,
            is_processed=0,
            shop_id__in=list(shop_ids)
        )

        # 日期筛选
        date_range_option = data.get('date_range', 'unlimited')
        start_date_str = data.get('start_date', '')
        end_date_str = data.get('end_date', '')

        current_start, current_end = None, None
        if date_range_option == 'custom' and start_date_str and end_date_str:
            try:
                current_start = datetime.strptime(start_date_str.split(' ')[0], '%Y-%m-%d').date()
                current_end = datetime.strptime(end_date_str.split(' ')[0], '%Y-%m-%d').date()
            except:
                pass

        if not current_start or not current_end:
            current_start, current_end = get_date_range_from_option(date_range_option)

        if current_start and current_end:
            base_filter &= Q(date__gte=current_start, date__lte=current_end)

        # 店铺名称搜索
        shop_name = data.get('shop_name', '').strip()
        if shop_name:
            base_filter &= Q(shop__shop_name__icontains=shop_name)

        # 主题关键词搜索
        subject_keyword = data.get('subject_keyword', '').strip()
        if subject_keyword:
            base_filter &= Q(subject__icontains=subject_keyword)

        # 权限范围控制
        if 'ops_all' in permissions:
            operators_query = Q()  # 管理员：无额外限制
        elif 'ops_group' in permissions and hasattr(user, 'operational_account') and user.operational_account.ops_group:
            group_name = user.operational_account.ops_group
            operators_query = Q(shop__ops__operational_account__ops_group=group_name)
        else:
            return JsonResponse({
                'success': True,
                'data': {
                    'success_count': 0,
                    'fail_count': 0,
                    'fail_details': []
                }
            })

        # 获取每个运营的待处理统计
        pending_stats = AmazonPerformanceNotification.objects.filter(
            base_filter & operators_query
        ).values(
            'shop__ops_id',
            'shop__ops__first_name',
            'shop__ops__wx_url'
        ).annotate(
            pending_count=Count('id')
        ).order_by('-pending_count')

        # 构建 operator_stats 格式
        operator_stats = {}
        for item in pending_stats:
            ops_name = item['shop__ops__first_name']
            if not ops_name:
                continue

            if ops_name not in operator_stats:
                operator_stats[ops_name] = {
                    'wx_url': item['shop__ops__wx_url'],
                    'shops': [],
                    'total_count': item['pending_count']
                }

            # 获取该运营的店铺明细及所有通知主题
            shop_details_query = AmazonPerformanceNotification.objects.filter(
                base_filter & operators_query,
                shop__ops_id=item['shop__ops_id']
            ).values(
                'shop__shop_name'
            ).annotate(
                shop_pending=Count('id')
            ).order_by('-shop_pending')

            for shop in shop_details_query:
                # 获取该店铺的所有通知主题
                subjects = AmazonPerformanceNotification.objects.filter(
                    base_filter & operators_query,
                    shop__ops_id=item['shop__ops_id'],
                    shop__shop_name=shop['shop__shop_name']
                ).values_list('subject', flat=True)

                operator_stats[ops_name]['shops'].append({
                    'shop_name': shop['shop__shop_name'] or '未知店铺',
                    'count': shop['shop_pending'],
                    'subjects': list(subjects)
                })

        # 调用服务层发送
        result = send_performance_notifications(operator_stats)

        # 记录操作日志
        details = f"通知{result['success_count']}人成功，{result['fail_count']}人失败"
        if result['fail_details']:
            details += f" | 失败详情: {', '.join(result['fail_details'][:3])}"

        UserOperationLog.objects.create(
            user=user,
            operation_type=UserOperationLog.PERFORMANCE_NOTIFY_OPERATORS,
            operation_record=f"批量通知运营处理绩效: {details}"
        )

        return JsonResponse({
            'success': True,
            'data': result
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
    新增：返回用户通知权限标识
    """
    if request.method != 'GET':
        return JsonResponse({'success': False, 'message': '只支持GET请求'}, status=405)

    try:
        user = request.user
        permissions = get_user_operation_permissions(user)

        # 判断权限范围（带公司限定）
        base_shop_qs = AmazonShop.objects.all()
        if hasattr(user, 'company') and user.company:
            base_shop_qs = base_shop_qs.filter(company=user.company)
        
        if 'ops_all' in permissions:
            shops = base_shop_qs.filter(ops__isnull=False).select_related('ops')
        elif 'ops_group' in permissions and hasattr(user, 'operational_account') and user.operational_account.ops_group:
            group_name = user.operational_account.ops_group
            shops = base_shop_qs.filter(
                ops__operational_account__ops_group=group_name
            ).select_related('ops')
        else:
            shops = base_shop_qs.filter(ops=user).select_related('ops')

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

        # 新增：返回权限标识
        can_notify_all = 'ops_all' in permissions
        can_notify_group = 'ops_group' in permissions
        group_name = user.operational_account.ops_group if hasattr(user,
                                                                   'operational_account') and user.operational_account.ops_group else ''

        return JsonResponse({
            'success': True,
            'data': operators_list,
            'can_notify_all': can_notify_all,
            'can_notify_group': can_notify_group,
            'group_name': group_name
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'获取运营人员失败: {str(e)}'
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
        permissions = get_user_operation_permissions(user)

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
            user_shop_ids = get_shop_ids_by_filter('ops', user.id, user=user)
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
