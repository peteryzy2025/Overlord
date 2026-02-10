# General/view_operation_log.py
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.core.paginator import Paginator
from django.shortcuts import render
from datetime import datetime, timedelta
import json

from general.models import User, UserOperationLog

SYSTEM_ACCOUNTS = [55, 56]  # 特殊系统账号，所有人可见
def get_operation_log_permissions(user):
    """
    获取用户在操作日志页面的详细权限
    返回: {
        can_see_type_1: bool,  # 1xxx: 用户管理类
        can_see_type_2: bool,  # 2xxx: 店铺管理类
        ops_all: bool,         # 3xxx和4xxx（订单+邮件）全部
        ops_group: bool,       # 3xxx和4xxx本组
        ops: bool,             # 3xxx和4xxx自己
        user_id: int,
        group_name: str
    }
    """
    permissions = {
        'can_see_type_1': False,
        'can_see_type_2': False,
        'ops_all': False,
        'ops_group': False,
        'ops': False,
        'user_id': user.id,
        'group_name': ''
    }

    user_permission = getattr(user, 'permission', '')
    if not user_permission:
        return permissions

    # 统一转为列表
    if isinstance(user_permission, str):
        perm_list = [perm.strip() for perm in user_permission.split(',') if perm.strip()]
    elif isinstance(user_permission, list):
        perm_list = user_permission
    else:
        perm_list = []

    # 判断555权限（1xxx和2xxx类操作）
    if '555' in perm_list:
        permissions['can_see_type_1'] = True
        permissions['can_see_type_2'] = True

    # 判断3xxx和4xxx类操作权限（订单+邮件）
    if 'ops_all' in perm_list:
        permissions['ops_all'] = True
    elif 'ops_group' in perm_list:
        permissions['ops_group'] = True
        # 获取用户所在分组
        if hasattr(user, 'operational_account') and user.operational_account:
            permissions['group_name'] = user.operational_account.ops_group or ''
    elif 'ops' in perm_list:
        permissions['ops'] = True

    return permissions

@login_required(login_url='/login/')
def operation_log_view(request):
    """
    操作日志管理页面渲染
    """
    user = request.user

    # 获取用户权限
    permissions = get_operation_log_permissions(user)

    # 将权限数据传递给前端
    return render(request, 'management/user_operation_management.html', {
        'active_nav': 'operation_log',
        'currentUserPermissionsData': json.dumps(permissions)  # 传递给JS
    })


@login_required
def get_all_users_api(request):
    """
    API接口：获取所有系统用户列表（用于人员筛选下拉框）
    返回: [{id: 1, first_name: '张三', username: 'zhangsan', department: '运营部门'}, ...]
    """
    try:
        # 查询所有用户，关联operational_account获取分组信息
        users = User.objects.all().select_related('operational_account').values(
            'id', 'first_name', 'username', 'department'
        ).order_by('department', 'first_name')

        users_list = []
        for user in users:
            users_list.append({
                'id': user['id'],
                'first_name': user['first_name'] or user['username'],
                'username': user['username'],
                'department': user['department'] or '未知部门'
            })

        return JsonResponse({
            'success': True,
            'data': users_list
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({
            'success': False,
            'message': f'获取用户列表失败: {str(e)}'
        }, status=500)


@login_required
@login_required
def get_operation_types_api(request):
    """
    API接口：根据用户权限获取可见的操作类型列表
    返回: [{id: 1001, name: '新增用户'}, ...]
    """
    try:
        user = request.user
        permissions = get_operation_log_permissions(user)

        # 获取所有操作类型
        all_types = UserOperationLog.OperationType.choices

        visible_types = []

        for type_id, type_name in all_types:
            type_str = str(type_id)
            # 判断用户是否有权限查看此类型
            if type_str.startswith('1') and not permissions['can_see_type_1']:
                continue
            if type_str.startswith('2') and not permissions['can_see_type_2']:
                continue
            # 修改：3xxx和4xxx共享同一套权限
            if (type_str.startswith('3') or type_str.startswith('4')) and not (
                    permissions['ops_all'] or permissions['ops_group'] or permissions['ops']):
                continue

            visible_types.append({
                'id': type_id,
                'name': type_name
            })

        return JsonResponse({
            'success': True,
            'data': visible_types
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({
            'success': False,
            'message': f'获取操作类型失败: {str(e)}'
        }, status=500)

@login_required
def get_operation_logs_api(request):
    """
    API接口：分页查询操作日志列表（带权限控制）
    POST参数:
        - start_date: 开始日期
        - end_date: 结束日期
        - user_ids: 用户ID列表（空数组表示全部）
        - operation_type: 操作类型ID（空字符串表示全部）
        - record_keyword: 操作记录关键词（模糊搜索）
        - sort_field: 排序字段
        - sort_order: 排序顺序
        - page: 页码
        - page_size: 每页条数
        - permissions: 前端传递的用户权限（用于验证）
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': '只支持POST请求'}, status=405)

    try:
        # 解析请求数据
        data = json.loads(request.body)
        user = request.user

        # 获取后端重新计算的权限（防止前端伪造）
        permissions = get_operation_log_permissions(user)

        # 解析前端传递的权限（用于日志记录，但不直接使用）
        frontend_permissions = data.get('permissions', {})

        # 解析分页参数
        page = int(data.get('page', 1))
        page_size = int(data.get('page_size', 20))

        # 解析筛选条件
        start_date_str = data.get('start_date', '')
        end_date_str = data.get('end_date', '')
        user_ids = data.get('user_ids', [])
        operation_type = data.get('operation_type', '')
        record_keyword = data.get('record_keyword', '').strip()
        sort_field = data.get('sort_field', 'created_at')
        sort_order = data.get('sort_order', 'desc')

        # 日期范围验证
        if not start_date_str or not end_date_str:
            return JsonResponse({
                'success': False,
                'message': '请提供开始日期和结束日期'
            }, status=400)

        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            if start_date > end_date:
                return JsonResponse({
                    'success': False,
                    'message': '开始日期不能晚于结束日期'
                }, status=400)
        except ValueError:
            return JsonResponse({
                'success': False,
                'message': '日期格式错误，应为YYYY-MM-DD格式'
            }, status=400)

        # 构建基础查询
        query = Q()

        # 日期范围筛选
        query &= Q(created_at__date__gte=start_date)
        query &= Q(created_at__date__lte=end_date)

        # 操作类型筛选
        if operation_type:
            try:
                op_type_int = int(operation_type)
                query &= Q(operation_type=op_type_int)
            except (ValueError, TypeError):
                pass

        # 操作记录关键词模糊搜索
        if record_keyword:
            query &= Q(operation_record__icontains=record_keyword)

        # ===== 权限核心控制：用户筛选 =====
        # 基础查询：先筛选出当前用户权限范围内能看到的所有日志
        user_query = Q()

        # 1. 如果用户有1xxx权限，可以看到所有用户管理类操作
        if permissions['can_see_type_1']:
            user_query |= Q(operation_type__gte=1000, operation_type__lt=2000)

        # 2. 如果用户有2xxx权限，可以看到所有店铺管理类操作
        if permissions['can_see_type_2']:
            user_query |= Q(operation_type__gte=2000, operation_type__lt=3000)

        # 3. 3xxx和4xxx订单/邮件操作权限（核心修改）
        if permissions['ops_all']:
            # 可以看到所有3xxx和4xxx操作
            user_query |= Q(operation_type__gte=3000, operation_type__lt=5000)
        elif permissions['ops_group']:
            # 只能看到本组成员的3xxx和4xxx操作 + 机器人
            group_members = User.objects.filter(
                operational_account__ops_group=permissions['group_name']
            ).values_list('id', flat=True)
            user_query |= (Q(operation_type__gte=3000, operation_type__lt=5000) &
                           Q(user__in=list(group_members) + SYSTEM_ACCOUNTS))
        elif permissions['ops']:
            # 只能看到自己的3xxx和4xxx操作 + 机器人
            user_query |= (Q(operation_type__gte=3000, operation_type__lt=5000) &
                           Q(user__in=[permissions['user_id']] + SYSTEM_ACCOUNTS))

        # 如果用户没有选择特定人员，应用权限查询
        if not user_ids:
            query &= user_query
        else:
            # 用户选择了特定人员，需要验证这些人员是否在权限范围内
            allowed_user_ids = set()

            # 1xxx和2xxx类型：如果用户有权限，可以看到所有用户
            if permissions['can_see_type_1']:
                allowed_user_ids.update(
                    User.objects.filter(id__in=user_ids).values_list('id', flat=True)
                )
            if permissions['can_see_type_2']:
                allowed_user_ids.update(
                    User.objects.filter(id__in=user_ids).values_list('id', flat=True)
                )

            # 3xxx和4xxx类型：根据权限范围筛选
            if permissions['ops_all']:
                allowed_user_ids.update(
                    User.objects.filter(id__in=user_ids).values_list('id', flat=True)
                )
            elif permissions['ops_group']:
                group_members = User.objects.filter(
                    operational_account__ops_group=permissions['group_name']
                ).values_list('id', flat=True)
                # 本组人员 + 机器人
                allowed_user_ids.update(
                    [uid for uid in user_ids if uid in list(group_members) + SYSTEM_ACCOUNTS]
                )
            elif permissions['ops']:
                # 自己 + 机器人
                allowed_user_ids.update(
                    [uid for uid in user_ids if uid in [permissions['user_id']] + SYSTEM_ACCOUNTS]
                )

            if allowed_user_ids:
                query &= Q(user__in=list(allowed_user_ids))
            else:
                # 没有允许的用户，返回空
                query &= Q(pk__in=[])

        # 执行查询
        logs_query = UserOperationLog.objects.filter(
            query
        ).select_related('user').values(
            'id', 'operation_type', 'operation_record', 'created_at',
            'user__id', 'user__first_name', 'user__username'
        )

        # 排序
        valid_sort_fields = ['operation_type', 'user', 'created_at']
        if sort_field in valid_sort_fields:
            # 转换字段名
            if sort_field == 'user':
                order_by = 'user__first_name' if sort_order == 'asc' else '-user__first_name'
            else:
                order_by = f"{'-' if sort_order == 'desc' else ''}{sort_field}"

            logs_query = logs_query.order_by(order_by)
        else:
            # 默认按时间倒序
            logs_query = logs_query.order_by('-created_at')

        # 分页
        paginator = Paginator(logs_query, page_size)
        try:
            page_obj = paginator.page(page)
        except Exception:
            page_obj = paginator.page(1)

        # 格式化数据
        logs_list = []
        for log in page_obj.object_list:
            # 获取操作类型显示名称
            operation_type_display = dict(UserOperationLog.OperationType.choices).get(
                log['operation_type'], log['operation_type']
            )

            logs_list.append({
                'id': log['id'],
                'operation_type': log['operation_type'],
                'operation_type_display': operation_type_display,
                'operation_record': log['operation_record'] or '-',
                'created_at': log['created_at'].strftime('%Y-%m-%d %H:%M:%S') if log['created_at'] else '-',
                'user_id': log['user__id'],
                'user_name': log['user__first_name'] or log['user__username'] or '系统'
            })

        return JsonResponse({
            'success': True,
            'data': {
                'logs': logs_list,
                'total': paginator.count,
                'total_pages': paginator.num_pages
            }
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({
            'success': False,
            'message': f'查询失败: {str(e)}'
        }, status=500)
