# Amazon/view/views_amazon_shop_emails.py

from django.http import JsonResponse
from django.db.models import Q, Count
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.shortcuts import render
from django.utils import timezone
from datetime import datetime, timedelta
import json

from amazon.models import AmazonShopEmail
from general.models import AmazonShop, User, OperationalAccount, UserOperationLog
from api.WX.wx import send_wechat_work_message
from amazon.services.amazon_shop_email_service import send_email_notifications
from universal.permission_utils import get_user_permission_codes

def get_user_ops_group(user):
    """获取用户的运营分组（安全获取）"""
    try:
        return user.operational_account.ops_group
    except AttributeError:
        return None
def get_date_range_from_option(option):
    """
    获取日期范围，支持'unlimited'选项
    返回 (start_date, end_date) 或 (None, None) 当选择不限时
    """
    if option == 'unlimited':
        return None, None

    today = datetime.now().date()
    if option == 'today':
        return today, today
    elif option == 'last7days':
        return today - timedelta(days=6), today
    elif option == 'last30days':
        return today - timedelta(days=29), today
    else:
        return None, None


def get_user_permission_codes(user):
    """
    获取用户的所有权限code列表
    返回: list[int] - 如 [1, 2, 555] 或 []
    """
    if not user or not user.is_authenticated:
        return []
    return list(user.permission_configs.values_list('code', flat=True))


def is_user_in_same_group(user, target_user_id):
    """
    判断目标用户是否和当前用户在同一个运营组
    用于组长权限验证
    """
    try:
        user_group = user.operational_account.ops_group
        if not user_group:
            return False
        return OperationalAccount.objects.filter(
            user_id=target_user_id,
            ops_group=user_group
        ).exists()
    except AttributeError:
        return False


@login_required(login_url='/login/')
def amazon_shop_emails_page(request):
    """店铺邮件管理页面渲染"""
    return render(request, 'amazon_shop_emails.html', {
        'active_nav': 'amazon_shop_emails',
    })


@login_required
def get_amazon_shop_emails_api(request):
    """
    获取店铺邮件列表（带分页、排序、筛选）
    权限控制：基于permission_configs的code判断
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': '只支持POST请求'}, status=405)

    try:
        data = json.loads(request.body)
        user = request.user

        # 新权限判断
        permission_codes = get_user_permission_codes(user)

        # 解析前端参数
        ops_id_raw = data.get('operator_id')
        ops_group_raw = data.get('group') or data.get('ops_group')

        # 默认无权限
        filter_type, filter_value = 'none', None

        # code=3或555：运营全部权限（可查看所有）
        if 3 in permission_codes or 555 in permission_codes:
            if ops_group_raw and ops_group_raw not in ['all', '全部分组']:
                filter_type, filter_value = 'ops_group', ops_group_raw.strip()
            elif ops_id_raw and ops_id_raw not in ['all', '全部人员']:
                try:
                    filter_type, filter_value = 'ops_id', int(ops_id_raw)
                except:
                    pass
            else:
                filter_type, filter_value = 'all', None

        # code=2：组长权限（只能看本组）
        elif 2 in permission_codes:
            try:
                user_group = user.operational_account.ops_group
                if not user_group:
                    filter_type, filter_value = 'none', None
                else:
                    # 组内筛选具体人员（需验证是否属于本组）
                    if ops_id_raw and ops_id_raw not in ['all', '全部人员']:
                        try:
                            target_id = int(ops_id_raw)
                            if OperationalAccount.objects.filter(
                                    user_id=target_id, ops_group=user_group
                            ).exists():
                                filter_type, filter_value = 'ops_id', target_id
                            else:
                                filter_type, filter_value = 'none', None  # 越权
                        except:
                            filter_type, filter_value = 'none', None
                    # 筛选其他组（拒绝）
                    elif ops_group_raw and ops_group_raw != user_group:
                        filter_type, filter_value = 'none', None
                    # 默认查本组
                    else:
                        filter_type, filter_value = 'ops_group', user_group
            except AttributeError:
                filter_type, filter_value = 'none', None

        # code=1：普通运营（只能看自己）
        elif 1 in permission_codes:
            filter_type, filter_value = 'ops_id', user.id

        # 无任何权限
        else:
            filter_type, filter_value = 'none', None

        # 分页参数
        page = int(data.get('page', 1))
        page_size = int(data.get('page_size', 20))
        page_size = min(page_size, 100)

        # 排序参数
        sort_field = data.get('sort_field', 'receive_time')
        sort_order = data.get('sort_order', 'desc')
        valid_sort_fields = ['receive_time', 'shop_name', 'operator_name', 'ops_group', 'role']
        if sort_field not in valid_sort_fields:
            sort_field = 'receive_time'

        # 日期参数
        date_range_option = data.get('date_range', 'unlimited')
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
                    'emails': [],
                    'total': 0,
                    'page': page,
                    'page_size': page_size,
                    'total_pages': 0,
                    'stats': {'pending_count': 0}
                }
            })

        # 获取权限范围内的店铺
        if filter_type == 'ops_id':
            shop_ids = AmazonShop.objects.filter(ops_id=filter_value).values_list('id', flat=True)
        elif filter_type == 'ops_group':
            user_ids = OperationalAccount.objects.filter(ops_group=filter_value).values_list('user_id', flat=True)
            shop_ids = AmazonShop.objects.filter(ops_id__in=list(user_ids)).values_list('id', flat=True)
        elif filter_type == 'all':
            shop_ids = AmazonShop.objects.all().values_list('id', flat=True)
        else:
            shop_ids = AmazonShop.objects.none().values_list('id', flat=True)

        # 构建查询条件
        email_filter = Q(shop_id__in=list(shop_ids))

        # 日期筛选
        if current_start and current_end:
            email_filter &= Q(receive_time__date__gte=current_start)
            email_filter &= Q(receive_time__date__lte=current_end)

        # 运营人员多选筛选
        operator_ids = data.get('operator_ids', [])
        if operator_ids:
            if 3 in permission_codes or 555 in permission_codes:
                email_filter &= Q(shop__ops_id__in=operator_ids)
            elif 2 in permission_codes:
                user_group = get_user_ops_group(user)
                valid_ids = list(OperationalAccount.objects.filter(
                    ops_group=user_group, user_id__in=operator_ids
                ).values_list('user_id', flat=True))
                if set(operator_ids).issubset(set(valid_ids)):
                    email_filter &= Q(shop__ops_id__in=operator_ids)
                else:
                    return JsonResponse({'success': False, 'message': '无权筛选指定运营人员'}, status=403)
            else:
                return JsonResponse({'success': False, 'message': '无权筛选运营人员'}, status=403)

        # 店铺名称模糊搜索
        shop_name = data.get('shop_name', '').strip()
        if shop_name:
            email_filter &= Q(shop__shop_name__icontains=shop_name)

        # 发件人搜索
        sender_keyword = data.get('sender_keyword', '').strip()
        if sender_keyword:
            email_filter &= Q(sender__icontains=sender_keyword)

        # 邮件标题搜索
        subject_keyword = data.get('subject_keyword', '').strip()
        if subject_keyword:
            email_filter &= Q(subject__icontains=subject_keyword)

        # 状态筛选
        status_filter = data.get('status_filter', '')
        if status_filter:
            if status_filter == 'needs_attention':
                email_filter &= Q(is_attention_needed=True)
            elif status_filter == 'needs_attention_pending':
                email_filter &= Q(is_attention_needed=True, is_processed=False)
            elif status_filter == 'processed':
                email_filter &= Q(is_processed=True)

        # 构建排序
        order_by_prefix = '-' if sort_order == 'desc' else ''
        if sort_field == 'receive_time':
            ordering = f'{order_by_prefix}receive_time'
        elif sort_field == 'shop_name':
            ordering = f'{order_by_prefix}shop__shop_name'
        elif sort_field == 'operator_name':
            ordering = f'{order_by_prefix}shop__ops__first_name'
        elif sort_field == 'ops_group':
            ordering = f'{order_by_prefix}shop__ops__operational_account__ops_group'
        elif sort_field == 'role':
            ordering = f'{order_by_prefix}shop__ops__role'

        # 查询数据
        emails_queryset = AmazonShopEmail.objects.filter(
            email_filter
        ).select_related(
            'shop', 'shop__ops', 'shop__ops__operational_account'
        ).only(
            'id', 'shop_id', 'subject', 'sender', 'receive_time',
            'is_attention_needed', 'is_processed',
            'shop__shop_name', 'shop__ops__first_name', 'shop__ops__role',
            'shop__ops__operational_account__ops_group',
        ).order_by(ordering)

        # 统计未处理数量
        pending_count = emails_queryset.filter(
            is_attention_needed=True, is_processed=False
        ).count() if emails_queryset.exists() else 0

        # 分页
        total = emails_queryset.count()
        paginator = Paginator(emails_queryset, page_size)
        try:
            emails_page = paginator.page(page)
        except PageNotAnInteger:
            emails_page = paginator.page(1)
        except EmptyPage:
            emails_page = paginator.page(paginator.num_pages)

        # 组装数据
        emails_data = []
        for email in emails_page:
            operator_name = ''
            role = ''
            ops_group = ''

            if email.shop and email.shop.ops:
                operator_name = email.shop.ops.first_name
                role = email.shop.ops.role or ''
                try:
                    ops_group = email.shop.ops.operational_account.ops_group or ''
                except:
                    pass

            emails_data.append({
                'id': email.id,
                'shop_name': email.shop.shop_name if email.shop else '未知店铺',
                'operator_name': operator_name,
                'role': role,
                'ops_group': ops_group,
                'sender': email.sender,
                'subject': email.subject,
                'receive_time': email.receive_time.strftime('%Y-%m-%d %H:%M:%S') if email.receive_time else '',
                'is_attention_needed': email.is_attention_needed,
                'is_processed': email.is_processed,
            })

        return JsonResponse({
            'success': True,
            'data': {
                'emails': emails_data,
                'total': total,
                'page': emails_page.number,
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
    权限判断：code=555/3/2 可通知
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': '只支持POST请求'}, status=405)

    try:
        data = json.loads(request.body)
        user = request.user

        # 新权限判断
        permission_codes = get_user_permission_codes(user)

        # 只有code=2/3/555可以通知
        if not any(code in permission_codes for code in [2, 3, 555]):
            return JsonResponse({
                'success': True,
                'data': {
                    'operators': [],
                    'total_pending': 0
                }
            })

        # 解析前端参数
        ops_id_raw = data.get('operator_id')
        ops_group_raw = data.get('group') or data.get('ops_group')

        # 默认无权限
        filter_type, filter_value = 'none', None

        # code=3或555：可查看所有
        if 3 in permission_codes or 555 in permission_codes:
            if ops_group_raw and ops_group_raw not in ['all', '全部分组']:
                filter_type, filter_value = 'ops_group', ops_group_raw.strip()
            elif ops_id_raw and ops_id_raw not in ['all', '全部人员']:
                try:
                    filter_type, filter_value = 'ops_id', int(ops_id_raw)
                except:
                    pass
            else:
                filter_type, filter_value = 'all', None

        # code=2：组长权限（只能看本组）
        elif 2 in permission_codes:
            try:
                user_group = user.operational_account.ops_group
                if not user_group:
                    filter_type, filter_value = 'none', None
                else:
                    # 组内筛选具体人员（需验证是否属于本组）
                    if ops_id_raw and ops_id_raw not in ['all', '全部人员']:
                        try:
                            target_id = int(ops_id_raw)
                            if OperationalAccount.objects.filter(
                                    user_id=target_id, ops_group=user_group
                            ).exists():
                                filter_type, filter_value = 'ops_id', target_id
                            else:
                                filter_type, filter_value = 'none', None
                        except:
                            filter_type, filter_value = 'none', None
                    # 筛选其他组（拒绝）
                    elif ops_group_raw and ops_group_raw != user_group:
                        filter_type, filter_value = 'none', None
                    # 默认查本组
                    else:
                        filter_type, filter_value = 'ops_group', user_group
            except AttributeError:
                filter_type, filter_value = 'none', None
        else:
            filter_type, filter_value = 'none', None

        if filter_type == 'none':
            return JsonResponse({
                'success': True,
                'data': {
                    'operators': [],
                    'total_pending': 0
                }
            })

        # 获取店铺ID
        if filter_type == 'ops_id':
            shop_ids = AmazonShop.objects.filter(ops_id=filter_value).values_list('id', flat=True)
        elif filter_type == 'ops_group':
            user_ids = OperationalAccount.objects.filter(ops_group=filter_value).values_list('user_id', flat=True)
            shop_ids = AmazonShop.objects.filter(ops_id__in=list(user_ids)).values_list('id', flat=True)
        elif filter_type == 'all':
            shop_ids = AmazonShop.objects.all().values_list('id', flat=True)
        else:
            shop_ids = AmazonShop.objects.none().values_list('id', flat=True)

        # 构建基础筛选条件
        email_filter = Q(
            shop_id__in=list(shop_ids),
            is_attention_needed=True,
            is_processed=False
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
            email_filter &= Q(receive_time__date__gte=current_start)
            email_filter &= Q(receive_time__date__lte=current_end)

        # 其他筛选条件
        shop_name = data.get('shop_name', '').strip()
        if shop_name:
            email_filter &= Q(shop__shop_name__icontains=shop_name)

        sender_keyword = data.get('sender_keyword', '').strip()
        if sender_keyword:
            email_filter &= Q(sender__icontains=sender_keyword)

        subject_keyword = data.get('subject_keyword', '').strip()
        if subject_keyword:
            email_filter &= Q(subject__icontains=subject_keyword)

        # 权限范围控制
        operators_query = Q()
        if 3 in permission_codes or 555 in permission_codes:
            # 全部权限，不限制
            pass
        elif 2 in permission_codes:
            # 组长，限制到本组
            user_group = get_user_ops_group(user)
            if user_group:
                operators_query &= Q(shop__ops__operational_account__ops_group=user_group)

        # 聚合统计每个运营的待处理数量
        pending_stats = AmazonShopEmail.objects.filter(
            email_filter & operators_query
        ).values(
            'shop__ops_id', 'shop__ops__first_name'
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
    权限判断：code=2/3/555可执行
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': '只支持POST请求'}, status=405)

    try:
        data = json.loads(request.body)
        user = request.user

        # 新权限判断
        permission_codes = get_user_permission_codes(user)

        # 只有code=2/3/555可以通知
        if not any(code in permission_codes for code in [2, 3, 555]):
            return JsonResponse({
                'success': False,
                'message': '无权操作：需要组长或更高权限'
            }, status=403)

        # 解析前端参数
        ops_id_raw = data.get('operator_id')
        ops_group_raw = data.get('group') or data.get('ops_group')

        # 默认无权限
        filter_type, filter_value = 'none', None

        # code=3或555：可查看所有
        if 3 in permission_codes or 555 in permission_codes:
            if ops_group_raw and ops_group_raw not in ['all', '全部分组']:
                filter_type, filter_value = 'ops_group', ops_group_raw.strip()
            elif ops_id_raw and ops_id_raw not in ['all', '全部人员']:
                try:
                    filter_type, filter_value = 'ops_id', int(ops_id_raw)
                except:
                    pass
            else:
                filter_type, filter_value = 'all', None

        # code=2：组长权限（只能看本组）
        elif 2 in permission_codes:
            try:
                user_group = user.operational_account.ops_group
                if not user_group:
                    filter_type, filter_value = 'none', None
                else:
                    # 组内筛选具体人员（需验证是否属于本组）
                    if ops_id_raw and ops_id_raw not in ['all', '全部人员']:
                        try:
                            target_id = int(ops_id_raw)
                            if OperationalAccount.objects.filter(
                                    user_id=target_id, ops_group=user_group
                            ).exists():
                                filter_type, filter_value = 'ops_id', target_id
                            else:
                                filter_type, filter_value = 'none', None
                        except:
                            filter_type, filter_value = 'none', None
                    # 筛选其他组（拒绝）
                    elif ops_group_raw and ops_group_raw != user_group:
                        filter_type, filter_value = 'none', None
                    # 默认查本组
                    else:
                        filter_type, filter_value = 'ops_group', user_group
            except AttributeError:
                filter_type, filter_value = 'none', None
        else:
            filter_type, filter_value = 'none', None

        if filter_type == 'none':
            return JsonResponse({
                'success': True,
                'data': {
                    'success_count': 0,
                    'fail_count': 0,
                    'fail_details': []
                }
            })

        # 获取店铺ID
        if filter_type == 'ops_id':
            shop_ids = AmazonShop.objects.filter(ops_id=filter_value).values_list('id', flat=True)
        elif filter_type == 'ops_group':
            user_ids = OperationalAccount.objects.filter(ops_group=filter_value).values_list('user_id', flat=True)
            shop_ids = AmazonShop.objects.filter(ops_id__in=list(user_ids)).values_list('id', flat=True)
        elif filter_type == 'all':
            shop_ids = AmazonShop.objects.all().values_list('id', flat=True)
        else:
            shop_ids = AmazonShop.objects.none().values_list('id', flat=True)

        # 使用Q对象构建基础筛选条件
        base_filter = Q(
            shop_id__in=list(shop_ids),
            is_attention_needed=True,
            is_processed=False
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
            base_filter &= Q(receive_time__date__gte=current_start)
            base_filter &= Q(receive_time__date__lte=current_end)

        # 其他筛选条件
        shop_name = data.get('shop_name', '').strip()
        if shop_name:
            base_filter &= Q(shop__shop_name__icontains=shop_name)

        sender_keyword = data.get('sender_keyword', '').strip()
        if sender_keyword:
            base_filter &= Q(sender__icontains=sender_keyword)

        subject_keyword = data.get('subject_keyword', '').strip()
        if subject_keyword:
            base_filter &= Q(subject__icontains=subject_keyword)

        # 权限范围控制
        operators_query = Q()
        if 3 in permission_codes or 555 in permission_codes:
            pass  # 全部权限
        elif 2 in permission_codes:
            user_group = get_user_ops_group(user)
            if user_group:
                operators_query &= Q(shop__ops__operational_account__ops_group=user_group)

        # 获取每个运营的待处理统计
        pending_stats = AmazonShopEmail.objects.filter(
            base_filter & operators_query
        ).values(
            'shop__ops_id', 'shop__ops__first_name', 'shop__ops__wx_url'
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
                    'total_count': item['pending_count'],
                    'backlog_stats': {3: 0, 7: 0, 15: 0}
                }

            # 获取店铺明细及所有邮件标题
            shop_details_query = AmazonShopEmail.objects.filter(
                base_filter & operators_query,
                shop__ops_id=item['shop__ops_id']
            ).values(
                'shop__shop_name'
            ).annotate(
                shop_pending=Count('id')
            ).order_by('-shop_pending')

            for shop in shop_details_query:
                # 获取该店铺的所有邮件标题
                subjects = AmazonShopEmail.objects.filter(
                    base_filter & operators_query,
                    shop__ops_id=item['shop__ops_id'],
                    shop__shop_name=shop['shop__shop_name']
                ).values_list('subject', flat=True)

                operator_stats[ops_name]['shops'].append({
                    'shop_name': shop['shop__shop_name'] or '未知店铺',
                    'count': shop['shop_pending'],
                    'subjects': list(subjects)
                })

            # 计算积压统计
            now = timezone.now()
            for days in [3, 7, 15]:
                backlog_count = AmazonShopEmail.objects.filter(
                    base_filter & operators_query,
                    shop__ops_id=item['shop__ops_id'],
                    receive_time__lte=now - timedelta(days=days)
                ).count()
                operator_stats[ops_name]['backlog_stats'][days] = backlog_count

        # 调用服务层发送
        result = send_email_notifications(operator_stats)

        # 记录操作日志
        details = f"通知{result['success_count']}人成功，{result['fail_count']}人失败"
        if result['fail_details']:
            details += f" | 失败详情: {', '.join(result['fail_details'][:3])}"

        UserOperationLog.objects.create(
            user=user,
            operation_type=UserOperationLog.EMAIL_NOTIFY_OPERATORS,
            operation_record=f"批量通知运营处理邮件: {details}"
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
def get_shop_emails_operators_api(request):
    """
    获取邮件模块可用的运营人员列表
    权限判断：code=3/555看全部，code=2看本组，code=1看自己
    """
    if request.method != 'GET':
        return JsonResponse({'success': False, 'message': '只支持GET请求'}, status=405)

    try:
        user = request.user
        permission_codes = get_user_permission_codes(user)

        # 判断权限范围
        if 3 in permission_codes or 555 in permission_codes:
            shops = AmazonShop.objects.filter(ops__isnull=False).select_related('ops')
        elif 2 in permission_codes:
            try:
                user_group = user.operational_account.ops_group
                shops = AmazonShop.objects.filter(
                    ops__operational_account__ops_group=user_group
                ).select_related('ops')
            except AttributeError:
                shops = AmazonShop.objects.none()
        elif 1 in permission_codes:
            shops = AmazonShop.objects.filter(ops=user).select_related('ops')
        else:
            shops = AmazonShop.objects.none()

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

        # 返回权限标识
        can_notify_all = 3 in permission_codes or 555 in permission_codes
        can_notify_group = 2 in permission_codes
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
def mark_email_processed_api(request, email_id):
    """
    标记邮件为已处理
    权限判断：code=555/3可操作所有，code=2可操作本组(含组员)，code=1只能操作自己的
    """
    if request.method != 'PUT':
        return JsonResponse({'success': False, 'message': '只支持PUT请求'}, status=405)

    try:
        user = request.user
        permission_codes = get_user_permission_codes(user)

        try:
            email = AmazonShopEmail.objects.select_related('shop', 'shop__ops').get(id=email_id)
        except AmazonShopEmail.DoesNotExist:
            return JsonResponse({'success': False, 'message': '邮件不存在'}, status=404)

        # 权限判断：code=3或555可操作任何邮件
        if 3 not in permission_codes and 555 not in permission_codes:
            # code=2：组长可操作本组人员（包括自己）的邮件
            if 2 in permission_codes:
                if email.shop and email.shop.ops_id:
                    # 检查是否是组员或自己
                    if not (email.shop.ops_id == user.id or is_user_in_same_group(user, email.shop.ops_id)):
                        return JsonResponse({
                            'success': False,
                            'message': '无权操作此邮件（非本组成员）'
                        }, status=403)
                else:
                    return JsonResponse({
                        'success': False,
                        'message': '邮件无关联运营人员'
                    }, status=403)
            # code=1：普通运营只能操作自己的
            elif 1 in permission_codes:
                if email.shop and email.shop.ops_id != user.id:
                    return JsonResponse({
                        'success': False,
                        'message': '无权操作此邮件'
                    }, status=403)
            # 无任何权限
            else:
                return JsonResponse({
                    'success': False,
                    'message': '无权操作此邮件'
                }, status=403)

        # 更新状态（后续代码保持不变）
        email.is_processed = True
        email.save(update_fields=['is_processed', 'updated_at'])

        # 记录操作日志
        UserOperationLog.objects.create(
            user=user,
            operation_type=UserOperationLog.EMAIL_MARK_PROCESSED,
            operation_record=f"标记邮件已处理: {email.subject[:50]}"
        )

        # 返回更新后的数据
        operator_name = email.shop.ops.first_name if email.shop and email.shop.ops else ''
        role = email.shop.ops.role if email.shop and email.shop.ops else ''
        ops_group = ''
        if email.shop and email.shop.ops:
            try:
                ops_group = email.shop.ops.operational_account.ops_group or ''
            except:
                pass

        return JsonResponse({
            'success': True,
            'data': {
                'id': email.id,
                'shop_name': email.shop.shop_name if email.shop else '未知店铺',
                'operator_name': operator_name,
                'role': role,
                'ops_group': ops_group,
                'sender': email.sender,
                'subject': email.subject,
                'receive_time': email.receive_time.strftime('%Y-%m-%d %H:%M:%S') if email.receive_time else '',
                'is_attention_needed': email.is_attention_needed,
                'is_processed': email.is_processed,
            }
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'服务器错误: {str(e)}'
        }, status=500)


@login_required
def get_email_detail_api(request, email_id):
    """
    获取邮件详情
    权限判断：code=555/3可查看所有，code=2可查看本组(含组员)，code=1只能看自己的
    """
    if request.method != 'GET':
        return JsonResponse({'success': False, 'message': '只支持GET请求'}, status=405)

    try:
        user = request.user
        permission_codes = get_user_permission_codes(user)

        try:
            email = AmazonShopEmail.objects.select_related('shop', 'shop__ops').get(id=email_id)
        except AmazonShopEmail.DoesNotExist:
            return JsonResponse({'success': False, 'message': '邮件不存在'}, status=404)

        # 权限判断：code=3或555可查看任何邮件
        if 3 not in permission_codes and 555 not in permission_codes:
            # code=2：组长可查看本组人员（包括自己）的邮件
            if 2 in permission_codes:
                if email.shop and email.shop.ops_id:
                    # 检查是否是组员或自己
                    if not (email.shop.ops_id == user.id or is_user_in_same_group(user, email.shop.ops_id)):
                        return JsonResponse({
                            'success': False,
                            'message': '无权查看此邮件（非本组成员）'
                        }, status=403)
                else:
                    return JsonResponse({
                        'success': False,
                        'message': '邮件无关联运营人员'
                    }, status=403)
            # code=1：普通运营只能查看自己的
            elif 1 in permission_codes:
                if email.shop and email.shop.ops_id != user.id:
                    return JsonResponse({
                        'success': False,
                        'message': '无权查看此邮件'
                    }, status=403)
            # 无任何权限
            else:
                return JsonResponse({
                    'success': False,
                    'message': '无权查看此邮件'
                }, status=403)

        # 组装返回数据（后续代码保持不变）
        operator_name = email.shop.ops.first_name if email.shop and email.shop.ops else ''
        role = email.shop.ops.role if email.shop and email.shop.ops else ''
        ops_group = ''
        if email.shop and email.shop.ops:
            try:
                ops_group = email.shop.ops.operational_account.ops_group or ''
            except:
                pass
        shop_email = email.shop.email_account if email.shop else ''

        return JsonResponse({
            'success': True,
            'data': {
                'id': email.id,
                'shop_name': email.shop.shop_name if email.shop else '未知店铺',
                'shop_email': shop_email,
                'operator_name': operator_name,
                'role': role,
                'ops_group': ops_group,
                'sender': email.sender,
                'subject': email.subject,
                'receive_time': email.receive_time.strftime('%Y-%m-%d %H:%M:%S') if email.receive_time else '',
                'email_body': email.email_body or '',
                'html_body': email.html_body or '',
                'is_attention_needed': email.is_attention_needed,
                'is_processed': email.is_processed,
            }
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'服务器错误: {str(e)}'
        }, status=500)
