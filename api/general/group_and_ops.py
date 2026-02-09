"""
通用运营分组和运营人员查询 API
用于驾驶舱、订单管理等页面获取可筛选的运营分组和人员列表
根据当前用户权限返回对应的数据范围
"""

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


def get_user_ops_permission(user):
    """
    获取用户在运营数据中的权限级别
    
    返回:
        - 'admin': 超管/运营管理员，看全公司数据
        - ('leader', ops_group): 运营组长，看同组数据
        - 'self': 普通运营，只看自己
        - 'none': 无权限，看不到任何运营数据
    """
    if not user or not user.is_authenticated:
        return 'none'
    
    # 1. 超管(555) / 运营管理员(553) → 看全部
    if has_perm_code(user, '555') or has_perm_code(user, '553'):
        return 'admin'
    
    # 2. 非运营部人员 → 看不到任何运营数据
    if user.department != 'operation':
        return 'none'
    
    # 3. 获取运营账号信息
    account = getattr(user, 'operational_account', None)
    if not account:
        # 没有运营账号信息，只能看自己
        return 'self'
    
    # 4. 运营组长 → 看同组
    if account.role == OperationalAccount.Role.LEADER:
        return ('leader', account.ops_group)
    
    # 5. 普通运营/助理 → 只看自己
    return 'self'


@require_GET
@login_required
def get_ops_groups_api(request):
    """
    API接口：获取运营分组列表（根据用户权限）
    
    权限:
      - 555/553(管理员): 返回本公司所有分组 + "全部分组"
      - 运营组长: 只返回自己的 ops_group
      - 普通运营: 返回自己的 ops_group（如果有）
      - 其他: 返回空列表
    
    参数:
      - platform: 平台筛选，可选值 'amazon' | 'temu'，不传则返回所有平台的分组
    
    返回: [{value: '', label: '全部分组'}, {value: 'A组', label: 'A组'}, ...]
    """
    try:
        user = request.user
        platform = request.GET.get('platform', '').strip()
        
        # 获取用户权限级别
        perm_level = get_user_ops_permission(user)
        
        # 无权限
        if perm_level == 'none':
            return JsonResponse({
                'success': True,
                'data': []
            })
        
        # 基础查询：本公司的运营账号
        queryset = OperationalAccount.objects.filter(
            user__company=user.company
        ).select_related('user')
        
        # 根据权限过滤
        if perm_level == 'admin':
            # 管理员：看全公司，不过滤
            pass
        elif isinstance(perm_level, tuple) and perm_level[0] == 'leader':
            # 组长：只看自己组
            queryset = queryset.filter(ops_group=perm_level[1])
        elif perm_level == 'self':
            # 普通运营：看自己的组（如果有）
            account = getattr(user, 'operational_account', None)
            if account and account.ops_group:
                queryset = queryset.filter(ops_group=account.ops_group)
            else:
                queryset = queryset.none()
        
        # 平台筛选
        if platform:
            queryset = queryset.filter(platform=platform)
        
        # 去重获取分组名（排除空值）
        groups = queryset.exclude(
            ops_group__isnull=True
        ).exclude(
            ops_group=''
        ).values_list('ops_group', flat=True).distinct().order_by('ops_group')
        
        # 构建返回数据
        result = [{'value': '', 'label': '全部分组'}]
        result.extend([{'value': g, 'label': g} for g in groups])
        
        return JsonResponse({
            'success': True,
            'data': result
        })
        
    except Exception as e:
        print(f"获取运营分组列表错误: {str(e)}")
        import traceback
        traceback.print_exc()
        return JsonResponse({
            'success': False,
            'error': f'服务器错误: {str(e)}'
        }, status=500)


@require_GET
@login_required
def get_operators_api(request):
    """
    API接口：获取运营人员列表（根据用户权限）
    
    权限:
      - 555/553(管理员): 返回本公司所有运营人员 + "全部人员"
      - 运营组长: 返回同组人员 + "全部人员"
      - 普通运营: 只返回自己
      - 其他: 返回空列表
    
    参数:
      - platform: 平台筛选，可选值 'amazon' | 'temu'，不传则返回所有平台人员
      - ops_group: 分组筛选，不传则不按分组筛选
    
    返回: [{value: 'all', label: '全部人员', group: '全部'},
           {value: 1, label: '张三 (A组)', group: 'A组'}, ...]
    """
    try:
        user = request.user
        platform = request.GET.get('platform', '').strip()
        ops_group_raw = request.GET.get('ops_group', '').strip()
        
        # 获取用户权限级别
        perm_level = get_user_ops_permission(user)
        
        # 无权限
        if perm_level == 'none':
            return JsonResponse({
                'success': True,
                'data': []
            })
        
        # 基础查询：本公司运营部人员
        queryset = User.objects.filter(
            company=user.company,
            department='operation'
        ).select_related('operational_account')
        
        # 权限过滤
        if perm_level == 'admin':
            # 管理员：看全公司，不过滤
            pass
        elif isinstance(perm_level, tuple) and perm_level[0] == 'leader':
            # 组长：只看同组
            queryset = queryset.filter(
                operational_account__ops_group=perm_level[1]
            )
        elif perm_level == 'self':
            # 普通运营：只看自己
            queryset = queryset.filter(id=user.id)
        
        # 平台筛选
        if platform:
            queryset = queryset.filter(operational_account__platform=platform)
        
        # 分组筛选（支持逗号分隔多选）
        if ops_group_raw:
            ops_groups = [g.strip() for g in ops_group_raw.split(',') if g.strip()]
            if ops_groups:
                queryset = queryset.filter(operational_account__ops_group__in=ops_groups)
        
        # 构建返回数据
        result = []
        
        # 管理员和组长添加"全部人员"选项
        is_admin = perm_level == 'admin'
        is_leader = isinstance(perm_level, tuple) and perm_level[0] == 'leader'
        
        if is_admin or is_leader:
            result.append({
                'value': 'all',
                'label': '全部人员',
                'group': '全部'
            })
        
        # 添加人员列表
        for op in queryset.order_by('operational_account__ops_group', 'first_name'):
            account = getattr(op, 'operational_account', None)
            group_name = account.ops_group if account and account.ops_group else '未分组'
            result.append({
                'value': op.id,
                'label': f"{op.first_name or '-'} ({group_name})",
                'group': group_name
            })
        
        return JsonResponse({
            'success': True,
            'data': result
        })
        
    except Exception as e:
        print(f"获取运营人员列表错误: {str(e)}")
        import traceback
        traceback.print_exc()
        return JsonResponse({
            'success': False,
            'error': f'服务器错误: {str(e)}'
        }, status=500)
