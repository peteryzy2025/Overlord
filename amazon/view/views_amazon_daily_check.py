# Amazon/view/views_amazon_daily_check.py

from django.http import JsonResponse
from django.db.models import Q, Count, Max, Min
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.shortcuts import render
from django.utils import timezone
from datetime import datetime, timedelta
import json

from general.models import AmazonShop, User, OperationalAccount
from amazon.models import AmazonShopDailyCheck
from amazon.view.views_amazon_performance import parse_permissions, determine_filter_type_and_value, \
    get_shop_ids_by_filter
# 修正导入路径：从Amazon模块下的amazon_order_views导入
from amazon.amazon_order_views import get_date_range_from_option as base_get_date_range
from general.models import UserOperationLog

# ============= 操作类型常量 =============
DAILY_CHECK_RESET = 4011


# ============= 本地扩展函数 =============
def get_date_range_from_option(option):
    """
    获取日期范围，支持'unlimited'选项
    返回 (start_date, end_date) 或 (None, None) 当选择不限时
    """
    if option == 'unlimited':
        return None, None
    return base_get_date_range(option)


@login_required(login_url='/login/')
def amazon_daily_check_report_page(request):
    """巡店报告管理页面渲染"""
    return render(request, 'amazon_daily_check_report.html', {
        'active_nav': 'amazon_daily_check',
    })


@login_required
def get_amazon_daily_check_list_api(request):
    """
    获取巡店报告列表（带分页、排序、筛选）
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
        sort_field = data.get('sort_field', 'check_date')
        sort_order = data.get('sort_order', 'desc')
        valid_sort_fields = ['check_date', 'shop_name', 'operator_name', 'ops_group', 'role', 'last_restock_date', 'withdrawal_amount', 'shop_status']
        if sort_field not in valid_sort_fields:
            sort_field = 'check_date'

        # 日期参数
        date_range_option = data.get('date_range', 'unlimited')
        start_date_str = data.get('start_date', '')
        end_date_str = data.get('end_date', '')

        # 解析日期范围 - 使用本地定义的扩展函数
        current_start, current_end = None, None
        if date_range_option == 'custom' and start_date_str and end_date_str:
            try:
                current_start = datetime.strptime(start_date_str.split(' ')[0], '%Y-%m-%d').date()
                current_end = datetime.strptime(end_date_str.split(' ')[0], '%Y-%m-%d').date()
            except:
                pass

        # 如果自定义日期解析失败，或不是自定义模式，则使用标准日期范围函数
        if not current_start or not current_end:
            current_start, current_end = get_date_range_from_option(date_range_option)

        # 无权限直接返回空
        if filter_type == 'none':
            return JsonResponse({
                'success': True,
                'data': {
                    'daily_checks': [],
                    'total': 0,
                    'page': page,
                    'page_size': page_size,
                    'total_pages': 0,
                    'stats': {
                        'total_shops': 0,
                        'completed_checks': 0,
                        'pending_today': 0
                    }
                }
            })

        # 获取权限范围内的店铺
        shop_ids = get_shop_ids_by_filter(filter_type, filter_value)

        # 构建查询条件
        daily_check_filter = Q(shop_id__in=list(shop_ids))

        # 日期筛选（如果不限则不添加条件）
        if current_start and current_end:
            daily_check_filter &= Q(check_date__gte=current_start)
            daily_check_filter &= Q(check_date__lte=current_end)

        # 运营人员多选筛选
        operator_ids = data.get('operator_ids', [])
        if operator_ids:
            if 'ops_all' in permissions:
                daily_check_filter &= Q(shop__ops_id__in=operator_ids)
            elif 'ops_group' in permissions:
                valid_shop_ids = set(shop_ids)
                operator_shops = AmazonShop.objects.filter(ops_id__in=operator_ids).values_list('id', flat=True)
                valid_operator_ids = AmazonShop.objects.filter(
                    id__in=valid_shop_ids.intersection(operator_shops)
                ).values_list('ops_id', flat=True)
                daily_check_filter &= Q(shop__ops_id__in=valid_operator_ids)
            else:
                daily_check_filter &= Q(shop__ops_id=user.id)

        # 运营分组筛选（兼容多选）
        ops_group_raw = data.get('ops_group', [])
        if isinstance(ops_group_raw, list):
            ops_groups = [
                str(g or '').strip()
                for g in ops_group_raw
                if str(g or '').strip() and str(g or '').strip().lower() not in ['all', '*', '__all__', '不限', '全部']
            ]
        else:
            ops_group_text = str(ops_group_raw or '').strip()
            if ops_group_text and ',' in ops_group_text:
                ops_groups = [
                    g.strip() for g in ops_group_text.split(',')
                    if g.strip() and g.strip().lower() not in ['all', '*', '__all__', '不限', '全部']
                ]
            elif ops_group_text and ops_group_text.lower() not in ['all', '*', '__all__', '不限', '全部']:
                ops_groups = [ops_group_text]
            else:
                ops_groups = []

        if ops_groups:
            daily_check_filter &= Q(shop__ops__operational_account__ops_group__in=ops_groups)

        # 店铺名称模糊搜索
        shop_name = data.get('shop_name', '').strip()
        if shop_name:
            daily_check_filter &= Q(shop__shop_name__icontains=shop_name)

        # 状态筛选（BooleanField在数据库中表现为0/1）
        visited = data.get('visited', '')
        if visited in ['0', '1']:
            daily_check_filter &= Q(visited=(visited == '1'))

        performance_checked = data.get('performance_checked', '')
        if performance_checked in ['0', '1']:
            daily_check_filter &= Q(performance_checked=(performance_checked == '1'))

        withdrawal_processed = data.get('withdrawal_processed', '')
        if withdrawal_processed in ['0', '1']:
            daily_check_filter &= Q(withdrawal_processed=(withdrawal_processed == '1'))

        # 店铺状况模糊搜索
        shop_status = data.get('shop_status', '').strip()
        if shop_status:
            daily_check_filter &= Q(shop_status__icontains=shop_status)

        # 最后上货日期筛选（支持范围）
        restock_start_str = data.get('restock_start_date', '')
        restock_end_str = data.get('restock_end_date', '')
        if restock_start_str:
            try:
                restock_start = datetime.strptime(restock_start_str, '%Y-%m-%d').date()
                daily_check_filter &= Q(last_restock_date__gte=restock_start)
            except:
                pass
        if restock_end_str:
            try:
                restock_end = datetime.strptime(restock_end_str, '%Y-%m-%d').date()
                daily_check_filter &= Q(last_restock_date__lte=restock_end)
            except:
                pass

        # 构建排序
        order_by_prefix = '-' if sort_order == 'desc' else ''
        if sort_field == 'check_date':
            ordering = f'{order_by_prefix}check_date'
        elif sort_field == 'shop_name':
            ordering = f'{order_by_prefix}shop__shop_name'
        elif sort_field == 'operator_name':
            ordering = f'{order_by_prefix}shop__ops__first_name'
        elif sort_field == 'ops_group':
            ordering = f'{order_by_prefix}shop__ops__operational_account__ops_group'
        elif sort_field == 'role':
            ordering = f'{order_by_prefix}shop__ops__role'
        elif sort_field == 'last_restock_date':
            ordering = f'{order_by_prefix}last_restock_date'
        elif sort_field == 'withdrawal_amount':
            ordering = f'{order_by_prefix}withdrawal_amount'
        elif sort_field == 'shop_status':
            ordering = f'{order_by_prefix}shop_status'

        # 查询数据
        daily_checks_queryset = AmazonShopDailyCheck.objects.filter(
            daily_check_filter
        ).select_related(
            'shop', 'shop__ops', 'shop__ops__operational_account'
        ).only(
            'id', 'shop_id', 'check_date', 'visited', 'performance_checked',
            'withdrawal_processed', 'withdrawal_amount', 'last_restock_date', 'shop_status',
            'shop__shop_name', 'shop__ops__first_name', 'shop__ops__role',
            'shop__ops__operational_account__ops_group',
        ).order_by(ordering)

        # 统计信息（基于当前筛选条件）
        stats_base_queryset = daily_checks_queryset
        total_shops = stats_base_queryset.count()
        completed_checks = stats_base_queryset.filter(
            visited=1, performance_checked=1, withdrawal_processed=1
        ).count()

        # 今日待巡检店铺数（仅在无日期筛选或包含今日时显示）
        pending_today = 0
        today = timezone.now().date()
        if (not current_start or not current_end) or (current_start <= today <= current_end):
            # 获取所有可见店铺
            all_shops = AmazonShop.objects.filter(id__in=list(shop_ids))
            # 统计已巡检的店铺
            checked_today = AmazonShopDailyCheck.objects.filter(
                shop_id__in=list(shop_ids),
                check_date=today
            ).values_list('shop_id', flat=True)
            # 待巡检 = 可见店铺 - 已巡检
            pending_today = all_shops.exclude(id__in=checked_today).count()

        # 分页
        total = daily_checks_queryset.count()
        paginator = Paginator(daily_checks_queryset, page_size)
        try:
            daily_checks_page = paginator.page(page)
        except PageNotAnInteger:
            daily_checks_page = paginator.page(1)
        except EmptyPage:
            daily_checks_page = paginator.page(paginator.num_pages)

        # 组装数据
        daily_checks_data = []
        for daily_check in daily_checks_page:
            operator_name = ''
            role = ''
            ops_group = ''

            if daily_check.shop and daily_check.shop.ops:
                operator_name = daily_check.shop.ops.first_name
                role = daily_check.shop.ops.role or ''
                try:
                    ops_group = daily_check.shop.ops.operational_account.ops_group or ''
                except:
                    ops_group = ''

            daily_checks_data.append({
                'id': daily_check.id,
                'shop_name': daily_check.shop.shop_name if daily_check.shop else '未知店铺',
                'operator_name': operator_name,
                'role': role,
                'ops_group': ops_group,
                'check_date': daily_check.check_date.strftime('%Y-%m-%d') if daily_check.check_date else '',
                'visited': daily_check.visited,
                'performance_checked': daily_check.performance_checked,
                'withdrawal_processed': daily_check.withdrawal_processed,
                'withdrawal_amount': daily_check.withdrawal_amount,
                'last_restock_date': daily_check.last_restock_date.strftime(
                    '%Y-%m-%d') if daily_check.last_restock_date else '',
                'shop_status': daily_check.shop_status or '',
            })

        return JsonResponse({
            'success': True,
            'data': {
                'daily_checks': daily_checks_data,
                'total': total,
                'page': daily_checks_page.number,
                'page_size': page_size,
                'total_pages': paginator.num_pages,
                'stats': {
                    'total_shops': total_shops,
                    'completed_checks': completed_checks,
                    'pending_today': pending_today
                }
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
def get_daily_check_operators_api(request):
    """
    获取巡店报告模块可用的运营人员列表（带权限控制）
    组长只能看自己组（包含自己），管理员看全部
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

        # 权限标识
        can_reset_daily_check = 'ops_all' in permissions

        return JsonResponse({
            'success': True,
            'data': operators_list,
            'can_reset_daily_check': can_reset_daily_check
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'获取运营人员失败: {str(e)}'
        }, status=500)


@login_required
def reset_today_daily_check_api(request):
    """
    重置今日所有巡店记录（将visited设为false）
    仅限管理员操作，并记录操作日志
    POST /api/amazon-daily-check/reset-today/
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': '只支持POST请求'}, status=405)

    try:
        user = request.user
        permissions = parse_permissions(getattr(user, 'permission', []))

        # 权限验证：仅限管理员
        if 'ops_all' not in permissions:
            return JsonResponse({
                'success': False,
                'message': '无权操作：需要管理员权限'
            }, status=403)

        # 获取今日日期
        today = timezone.now().date()

        # 获取筛选条件（用于日志记录和范围限制）
        data = json.loads(request.body) if request.body else {}

        # 构建查询条件：获取今日有巡检记录的店铺
        reset_filter = Q(check_date=today)

        # 根据筛选条件中的运营人员范围进行限制（如果提供了）
        operator_ids = data.get('operator_ids', [])
        if operator_ids:
            reset_filter &= Q(shop__ops_id__in=operator_ids)

        # 店铺名称筛选
        shop_name = data.get('shop_name', '').strip()
        if shop_name:
            reset_filter &= Q(shop__shop_name__icontains=shop_name)

        # 执行重置操作
        updated_count = AmazonShopDailyCheck.objects.filter(reset_filter).update(
            visited=False,
            performance_checked=False,
            withdrawal_processed=False,
            updated_at=timezone.now()
        )

        # 记录操作日志
        operation_detail = f"重置今日巡店: {updated_count}条记录"
        if shop_name:
            operation_detail += f", 店铺筛选: {shop_name}"
        if operator_ids:
            operation_detail += f", 运营筛选: {len(operator_ids)}人"

        UserOperationLog.objects.create(
            user=user,
            operation_type=DAILY_CHECK_RESET,
            operation_record=operation_detail
        )

        return JsonResponse({
            'success': True,
            'data': {
                'reset_count': updated_count,
                'message': f'成功重置{updated_count}条今日巡店记录'
            }
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({
            'success': False,
            'message': f'服务器错误: {str(e)}'
        }, status=500)
