from django.http import JsonResponse
from django.views.decorators.http import require_GET
from django.contrib.auth.decorators import login_required
from general.models import User, OperationalAccount


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
      - ops_all: 返回所有运营人员 + "全部人员"
      - ops_group: 返回"全部人员"+自己分组成员（给组长）
      - ops: 只返回自己
      - 其他: 返回空列表
    参数:
      - platform: 平台筛选，可选值: '亚马逊' 或 'Temu'
      - ops_group: 运营分组名称（仅ops_all权限时有效）
    返回: [{id: 1, first_name: '张三', group: 'A组'}, ...]
    """
    try:
        user = request.user
        permissions = parse_permissions(getattr(user, 'permission', []))

        # 获取参数（仅在ops_all时有效）
        platform = request.GET.get('platform', '').strip()
        ops_group_param = request.GET.get('ops_group', '').strip()

        # 基础查询：查询department包含"运营部门"的用户，并关联OperationalAccount
        queryset = User.objects.filter(
            department__icontains='运营部门'
        ).select_related('operational_account')

        # 权限1: ops_all - 返回所有符合条件的运营人员
        if 'ops_all' in permissions:
            # 应用平台筛选
            if platform in ['亚马逊', 'Temu']:
                queryset = queryset.filter(platform=platform)

            # 应用分组筛选（如果提供了ops_group参数）
            if ops_group_param:
                queryset = queryset.filter(
                    operational_account__ops_group=ops_group_param
                )

            # 获取所需字段并按分组和姓名排序
            operators = queryset.values(
                'id', 'first_name', 'operational_account__ops_group'
            ).order_by('operational_account__ops_group', 'first_name')

            # 构建结果列表
            operators_list = []

            # 添加"全部人员"选项（id用all表示）
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

        # 权限2: ops_group - 返回"全部人员"+自己分组的成员
        elif 'ops_group' in permissions:
            try:
                ops_account = user.operational_account
                user_group = ops_account.ops_group if ops_account else None

                if not user_group:
                    return JsonResponse({
                        'success': True,
                        'data': []
                    })

                # 筛选同组成员
                operators = queryset.filter(
                    operational_account__ops_group=user_group
                ).values(
                    'id', 'first_name', 'operational_account__ops_group'
                ).order_by('first_name')

                # 构建结果列表
                operators_list = []

                # 添加"全部人员"选项（代表整个组）
                operators_list.append({
                    'id': 'all',
                    'first_name': '全部人员',
                    'group': user_group
                })

                # 添加具体成员
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
            except:
                return JsonResponse({
                    'success': True,
                    'data': []
                })

        # 权限3: ops - 只返回自己
        elif 'ops' in permissions:
            operators_list = [{
                'id': user.id,
                'first_name': user.first_name or user.username,
                'group': getattr(user.operational_account, 'ops_group', '未分组') if hasattr(user,
                                                                                             'operational_account') else '未分组'
            }]

            return JsonResponse({
                'success': True,
                'data': operators_list
            })

        # 无权限: 返回空列表
        else:
            return JsonResponse({
                'success': True,
                'data': []
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
      - ops_all: 返回所有组 + "全部分组"
      - ops_group: 只返回用户自己的ops_group
      - 其他: 返回空列表
    """
    try:
        user = request.user
        permissions = parse_permissions(getattr(user, 'permission', []))

        # 权限1: ops_all - 返回所有分组
        if 'ops_all' in permissions:
            groups = OperationalAccount.objects.exclude(
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

        # 权限2: ops_group - 只返回自己的分组
        elif 'ops_group' in permissions:
            try:
                ops_account = user.operational_account
                user_group = ops_account.ops_group if ops_account else None

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
            except:
                return JsonResponse({
                    'success': True,
                    'data': []
                })

        # 无权限: 返回空列表
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