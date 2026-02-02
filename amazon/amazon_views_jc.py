from django.http import JsonResponse
from django.views.decorators.http import require_GET
from django.contrib.auth.decorators import login_required
from general.models import User, OperationalAccount


def has_perm_code(user, code):
    """检查用户是否有特定权限码（使用 permission_configs）"""
    if not user or not user.is_authenticated:
        return False
    try:
        code_int = int(code)
        return user.permission_configs.filter(code=code_int).exists()
    except (ValueError, TypeError):
        return False


def can_access_operation_management(user):
    """运营管理权限：555(超管) 或 553(运营管理员)"""
    return has_perm_code(user, '555') or has_perm_code(user, '553')


def is_ops_leader(user):
    """检查用户是否是运营组长"""
    if not user or user.department != 'operation':
        return False
    account = getattr(user, 'operational_account', None)
    if not account:
        return False
    return account.role == 'leader'


def get_visible_operator_ids(user):
    """
    获取用户可以看到的运营人员ID列表
    - 555/553：返回 None（不限制）
    - 运营组长：返回自己和组员ID
    - 普通运营：返回自己ID
    - 非运营：返回空列表
    """
    # 管理员可以看到所有人
    if can_access_operation_management(user):
        return None
    
    # 非运营部人员看不到任何运营
    if user.department != 'operation':
        return []
    
    account = getattr(user, 'operational_account', None)
    if not account:
        return [user.id]
    
    # 运营组长可以看自己和组员
    if account.role == 'leader' and account.ops_group:
        members = User.objects.filter(
            company=user.company,
            department='operation',
            operational_account__ops_group=account.ops_group
        ).values_list('id', flat=True)
        return list(members)
    
    # 普通运营只能看自己
    return [user.id]


def parse_permissions(user_permission):
    """
    统一权限解析函数
    处理多种格式的权限数据：
    - 字符串："ops,555,k1,k2" → ["ops", "555", "k1", "k2"]
    - 列表：["ops", "k1"] → 保持不变
    - 其他：返回空列表
    """
    if not user_permission:
        return []

    # 如果是字符串，按逗号分割并去除空白
    if isinstance(user_permission, str):
        return [perm.strip() for perm in user_permission.split(',') if perm.strip()]

    # 如果是列表，直接返回
    if isinstance(user_permission, list):
        return user_permission

    # 其他情况返回空列表
    return []


@require_GET
@login_required
def get_operators_api(request):
    """
    API接口：获取运营人员列表（根据权限）
    权限:
      - 555/553(运营管理员): 返回本公司所有运营人员 + "全部人员"
      - 运营组长: 返回本组组员 + 自己（含"全部人员"选项）
      - 普通运营: 只返回自己
      - 其他: 返回空列表
    参数:
      - platform: 平台筛选，可选值: 'amazon' 或 'temu'
      - ops_group: 运营分组名称（仅管理员权限时有效）
    返回: [{id: 1, first_name: '张三', group: 'A组'}, ...]
    """
    try:
        user = request.user
        
        # 获取可见的运营人员ID列表
        visible_ids = get_visible_operator_ids(user)
        
        # 获取参数
        platform = request.GET.get('platform', '').strip()
        ops_group_param = request.GET.get('ops_group', '').strip()
        
        # 基础查询：本公司运营部门人员
        queryset = User.objects.filter(
            company=user.company,
            department='operation'
        ).select_related('operational_account')
        
        # 应用权限过滤
        if visible_ids is not None:
            queryset = queryset.filter(id__in=visible_ids)
        
        # 应用平台筛选
        if platform in ['amazon', 'temu']:
            queryset = queryset.filter(operational_account__platform=platform)
        
        # 应用分组筛选（仅管理员或组长可以筛选分组）
        if ops_group_param and (can_access_operation_management(user) or is_ops_leader(user)):
            queryset = queryset.filter(operational_account__ops_group=ops_group_param)
        
        # 获取所需字段并按分组和姓名排序
        operators = queryset.values(
            'id', 'first_name', 'operational_account__ops_group'
        ).order_by('operational_account__ops_group', 'first_name')
        
        # 构建结果列表
        operators_list = []
        
        # 管理员或组长添加"全部人员"选项
        if can_access_operation_management(user) or is_ops_leader(user):
            operators_list.append({
                'id': 'all',
                'first_name': '全部人员',
                'group': '全部'
            })
        
        # 添加具体人员
        for op in operators:
            operators_list.append({
                'id': op['id'],
                'first_name': op['first_name'] or '-',
                'group': op['operational_account__ops_group'] or '未分组'
            })
        
        return JsonResponse({
            'success': True,
            'data': operators_list
        })
        
    except Exception as e:
            print(f"❌ 获取运营人员列表错误: {str(e)}")
            import traceback
            traceback.print_exc()
            return JsonResponse({
                'success': False,
                'error': f'服务器错误: {str(e)}'
            }, status=500)


# 获取分组列表API（从OperationalAccount）
@require_GET
@login_required
def get_ops_groups_api(request):
    """
    API接口：获取运营分组列表（根据权限）
    权限:
      - 555/553(运营管理员): 返回本公司所有组 + "全部分组"
      - 运营组长: 只返回用户自己的ops_group
      - 其他: 返回空列表
    """
    try:
        user = request.user
        
        # 管理员可以看到本公司所有分组
        if can_access_operation_management(user):
            groups = OperationalAccount.objects.filter(
                user__company=user.company
            ).exclude(
                ops_group__isnull=True
            ).exclude(
                ops_group=''
            ).values_list('ops_group', flat=True).distinct().order_by('ops_group')

            groups_list = list(groups)
            # 在列表开头插入"全部分组"
            groups_list.insert(0, '全部分组')

            return JsonResponse({
                'success': True,
                'data': groups_list
            })

        # 运营组长只返回自己的分组
        elif is_ops_leader(user):
            account = getattr(user, 'operational_account', None)
            user_group = account.ops_group if account else None

            if user_group:
                return JsonResponse({
                    'success': True,
                    'data': [user_group]
                })
            else:
                return JsonResponse({
                    'success': True,
                    'data': []
                })

        # 其他: 返回空列表
        else:
            return JsonResponse({
                'success': True,
                'data': []
            })

    except Exception as e:
        print(f"获取分组列表错误: {str(e)}")
        import traceback
        traceback.print_exc()
        return JsonResponse({
            'success': False,
            'error': f'服务器错误: {str(e)}'
        }, status=500)