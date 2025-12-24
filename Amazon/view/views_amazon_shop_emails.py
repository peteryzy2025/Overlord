# Amazon/view/views_amazon_shop_emails.py

from django.http import JsonResponse
from django.db.models import Q, Count
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.shortcuts import render
from django.utils import timezone
from datetime import datetime, timedelta
import json
import requests

from Amazon.models import AmazonShopEmail
from General.models import AmazonShop, User, OperationalAccount, UserOperationLog
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
def amazon_shop_emails_page(request):
    """店铺邮件管理页面渲染"""
    return render(request, 'amazon_shop_emails.html', {
        'active_nav': 'amazon_shop_emails',
    })


@login_required
def get_amazon_shop_emails_api(request):
    """
    获取店铺邮件列表（带分页、排序、筛选）
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
        shop_ids = get_shop_ids_by_filter(filter_type, filter_value)

        # 构建查询条件
        email_filter = Q(shop_id__in=list(shop_ids))

        # 日期筛选（如果不限则不添加条件）
        if current_start and current_end:
            # 因为receive_time是DateTimeField，需要转换为日期范围查询
            email_filter &= Q(receive_time__date__gte=current_start)
            email_filter &= Q(receive_time__date__lte=current_end)

        # 运营人员多选筛选
        operator_ids = data.get('operator_ids', [])
        if operator_ids:
            if 'ops_all' in permissions:
                email_filter &= Q(shop__ops_id__in=operator_ids)
            elif 'ops_group' in permissions:
                valid_shop_ids = set(shop_ids)
                operator_shops = AmazonShop.objects.filter(ops_id__in=operator_ids).values_list('id', flat=True)
                valid_operator_ids = AmazonShop.objects.filter(
                    id__in=valid_shop_ids.intersection(operator_shops)
                ).values_list('ops_id', flat=True)
                email_filter &= Q(shop__ops_id__in=valid_operator_ids)
            else:
                email_filter &= Q(shop__ops_id=user.id)

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
        stats_base_queryset = emails_queryset
        if operator_ids and len(operator_ids) == 1:
            stats_base_queryset = stats_base_queryset.filter(shop__ops_id=operator_ids[0])

        pending_count = stats_base_queryset.filter(
            is_attention_needed=True, is_processed=False
        ).count() if stats_base_queryset.exists() else 0

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
                    ops_group = ''

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
    POST /api/amazon-shop-emails/notify/preview/
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': '只支持POST请求'}, status=405)

    try:
        data = json.loads(request.body)
        user = request.user
        permissions = parse_permissions(getattr(user, 'permission', []))

        filter_type, filter_value = determine_filter_type_and_value(request, data, permissions)

        if filter_type == 'none':
            return JsonResponse({
                'success': True,
                'data': {
                    'operators': [],
                    'total_pending': 0
                }
            })

        shop_ids = get_shop_ids_by_filter(filter_type, filter_value)

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

        # 店铺名称和关键词筛选
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
        if 'ops_all' in permissions:
            pass
        elif 'ops_group' in permissions and hasattr(user, 'operational_account') and user.operational_account.ops_group:
            group_name = user.operational_account.ops_group
            operators_query &= Q(shop__ops__operational_account__ops_group=group_name)
        else:
            return JsonResponse({
                'success': True,
                'data': {
                    'operators': [],
                    'total_pending': 0
                }
            })

        # 聚合统计每个运营的待处理数量
        pending_stats = AmazonShopEmail.objects.filter(
            email_filter & operators_query
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
    POST /api/amazon-shop-emails/notify/
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': '只支持POST请求'}, status=405)

    try:
        data = json.loads(request.body)
        user = request.user
        permissions = parse_permissions(getattr(user, 'permission', []))

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

        shop_ids = get_shop_ids_by_filter(filter_type, filter_value)

        email_filter = Q(
            shop_id__in=list(shop_ids),
            is_attention_needed=True,
            is_processed=False
        )

        # 应用筛选条件
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
        if 'ops_all' in permissions:
            pass
        elif 'ops_group' in permissions and hasattr(user, 'operational_account') and user.operational_account.ops_group:
            group_name = user.operational_account.ops_group
            operators_query &= Q(shop__ops__operational_account__ops_group=group_name)
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
        pending_stats = AmazonShopEmail.objects.filter(
            email_filter & operators_query
        ).values(
            'shop__ops_id',
            'shop__ops__first_name',
            'shop__ops__wx_url'
        ).annotate(
            pending_count=Count('id')
        ).order_by('-pending_count')

        # 发送通知
        success_count = 0
        fail_count = 0
        fail_details = []

        for item in pending_stats:
            operator_id = item['shop__ops_id']
            operator_name = item['shop__ops__first_name'] or '未知姓名'
            wx_url = item['shop__ops__wx_url']
            pending_count = item['pending_count']

            if not wx_url:
                fail_count += 1
                fail_details.append(f'{operator_name}: 未配置企业微信通知地址')
                continue

            # 获取该运营的店铺明细
            shop_details = AmazonShopEmail.objects.filter(
                email_filter,
                shop__ops_id=operator_id
            ).values(
                'shop__shop_name'
            ).annotate(
                shop_pending=Count('id')
            ).order_by('-shop_pending')

            # 构建Markdown消息
            shop_list = '\n'.join([
                f"- {shop['shop__shop_name'] or '未知店铺'}（{shop['shop_pending']}封）"
                for shop in shop_details
            ])

            markdown_message = (
                f"**【店铺邮件提醒】**\n\n"
                f"**运营人员**：{operator_name}\n"
                f"**待处理店铺数**：{len(shop_details)}个\n"
                f"**待处理邮件总数**：{pending_count}封\n\n"
                f"**店铺明细**：\n{shop_list}\n\n"
                f"**操作**：请及时登录系统查看并处理"
            )

            # 发送企业微信消息（重试3次）
            retry_count = 0
            send_success = False
            last_error = None

            while retry_count < 3 and not send_success:
                try:
                    response = requests.post(
                        wx_url,
                        json={
                            "msgtype": "markdown",
                            "markdown": {
                                "content": markdown_message
                            }
                        },
                        timeout=5
                    )

                    if response.status_code == 200:
                        result = response.json()
                        if result.get('errcode') == 0:
                            success_count += 1
                            send_success = True
                        else:
                            retry_count += 1
                            last_error = result.get('errmsg', '未知错误')
                    else:
                        retry_count += 1
                        last_error = f'HTTP {response.status_code}'
                except Exception as e:
                    retry_count += 1
                    last_error = str(e)

            if not send_success:
                fail_count += 1
                fail_details.append(f'{operator_name}: {last_error}')
        details = f"通知{success_count}人成功，{fail_count}人失败"
        if fail_details:
            details += f" | 失败详情: {', '.join(fail_details[:3])}"  # 只记录前3条失败详情

        UserOperationLog.objects.create(
            user=user,
            operation_type=UserOperationLog.EMAIL_NOTIFY_OPERATORS,
            operation_record=f"批量通知运营处理邮件: {details}"
        )
        return JsonResponse({
            'success': True,
            'data': {
                'success_count': success_count,
                'fail_count': fail_count,
                'fail_details': fail_details
            }
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'服务器错误: {str(e)}'
        }, status=500)


@login_required
def get_shop_emails_operators_api(request):
    """
    获取邮件模块可用的运营人员列表（带权限控制）
    组长只能看自己组（包含自己），管理员看全部
    返回用户通知权限标识
    """
    if request.method != 'GET':
        return JsonResponse({'success': False, 'message': '只支持GET请求'}, status=405)

    try:
        user = request.user
        permissions = parse_permissions(getattr(user, 'permission', []))

        # 判断权限范围
        if 'ops_all' in permissions:
            shops = AmazonShop.objects.filter(ops__isnull=False).select_related('ops')
        elif 'ops_group' in permissions and hasattr(user, 'operational_account') and user.operational_account.ops_group:
            group_name = user.operational_account.ops_group
            shops = AmazonShop.objects.filter(
                ops__operational_account__ops_group=group_name
            ).select_related('ops')
        else:
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

        # 返回权限标识
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
def mark_email_processed_api(request, email_id):
    """
    标记邮件为已处理
    PUT /api/amazon-shop-emails/<id>/mark-processed/
    """
    if request.method != 'PUT':
        return JsonResponse({'success': False, 'message': '只支持PUT请求'}, status=405)

    try:
        user = request.user
        permissions = parse_permissions(getattr(user, 'permission', []))

        try:
            email = AmazonShopEmail.objects.select_related(
                'shop', 'shop__ops'
            ).get(id=email_id)
        except AmazonShopEmail.DoesNotExist:
            return JsonResponse({
                'success': False,
                'message': '邮件不存在'
            }, status=404)

        # 权限验证：确保用户有权限操作此邮件
        if 'ops_all' not in permissions:
            user_shop_ids = get_shop_ids_by_filter('ops', user.id)
            user_shop_ids_list = list(user_shop_ids)
            if email.shop_id not in user_shop_ids_list:
                if hasattr(email.shop, 'ops') and email.shop.ops_id == user.id:
                    pass
                else:
                    return JsonResponse({
                        'success': False,
                        'message': '无权操作此邮件'
                    }, status=403)

        # 更新状态
        email.is_processed = True
        email.save(update_fields=['is_processed', 'updated_at'])
        print(f"用户 {user.username} 标记邮件 {email.id} 为已处理")
        try:
            # 先打印准备信息
            print(
                f"【准备创建日志】用户={user.username}, 类型={UserOperationLog.EMAIL_MARK_PROCESSED}, 记录={email.subject[:50]}")

            # 执行创建并捕获返回值
            log = UserOperationLog.objects.create(
                user=user,
                operation_type=UserOperationLog.EMAIL_MARK_PROCESSED,
                operation_record=f"标记邮件已处理: {email.subject[:50]}"
            )

            # 打印成功信息（如果执行到这里，说明一定成功了）
            print(f"✅ 日志创建成功！ID={log.id}, 时间={log.created_at}")

        except Exception as e:
            # 如果失败，会跳到这里
            print(f"❌ 日志创建失败: {e}")
            # 如果你想继续执行，可以 pass
            # 如果你想中断，可以 raise e
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
# 在文件末尾添加以下代码

@login_required
@login_required
def get_email_detail_api(request, email_id):
    """
    获取邮件详情
    GET /api/amazon-shop-emails/<id>/
    """
    if request.method != 'GET':
        return JsonResponse({'success': False, 'message': '只支持GET请求'}, status=405)

    try:
        user = request.user
        permissions = parse_permissions(getattr(user, 'permission', []))

        try:
            email = AmazonShopEmail.objects.select_related(
                'shop', 'shop__ops'
            ).get(id=email_id)
        except AmazonShopEmail.DoesNotExist:
            return JsonResponse({
                'success': False,
                'message': '邮件不存在'
            }, status=404)

        # 权限验证：确保用户有权限查看此邮件
        if 'ops_all' not in permissions:
            user_shop_ids = get_shop_ids_by_filter('ops', user.id)
            user_shop_ids_list = list(user_shop_ids)
            if email.shop_id not in user_shop_ids_list:
                if hasattr(email.shop, 'ops') and email.shop.ops_id == user.id:
                    pass
                else:
                    return JsonResponse({
                        'success': False,
                        'message': '无权查看此邮件'
                    }, status=403)

        # 组装返回数据
        operator_name = email.shop.ops.first_name if email.shop and email.shop.ops else ''
        role = email.shop.ops.role if email.shop and email.shop.ops else ''
        ops_group = ''
        if email.shop and email.shop.ops:
            try:
                ops_group = email.shop.ops.operational_account.ops_group or ''
            except:
                ops_group = ''

        shop_email = email.shop.email_account if email.shop else ''

        return JsonResponse({
            'success': True,
            'data': {
                'id': email.id,
                'shop_name': email.shop.shop_name if email.shop else '未知店铺',
                'shop_email': shop_email,  # 新增：收件邮箱
                'operator_name': operator_name,
                'role': role,
                'ops_group': ops_group,
                'sender': email.sender,
                'subject': email.subject,
                'receive_time': email.receive_time.strftime('%Y-%m-%d %H:%M:%S') if email.receive_time else '',
                'email_body': email.email_body or '暂无邮件内容',
                'is_attention_needed': email.is_attention_needed,
                'is_processed': email.is_processed,
            }
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'服务器错误: {str(e)}'
        }, status=500)