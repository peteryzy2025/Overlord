from django.http import JsonResponse
from django.views.decorators.http import require_GET
from django.contrib.auth.decorators import login_required

from general.models import User, OperationalAccount


@require_GET
@login_required
def get_ops_list(request):
    """
    API接口：获取所有运营人员列表
    参数:
      - platform: 平台筛选，可选值: 'Temu'
    返回: [{id: 1, first_name: '张三', group: 'A组'}, ...]
    """
    try:
        platform = request.GET.get('platform', '').strip()

        queryset = User.objects.filter(
            department__icontains='运营部门'
        ).select_related('operational_account')

        if platform == 'Temu' or platform == 'Amazon':
            queryset = queryset.filter(platform=platform)

        operators = queryset.values(
            'id', 'first_name', 'operational_account__ops_group'
        ).order_by('operational_account__ops_group', 'first_name')

        operators_list = []
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

@require_GET
@login_required
def get_ops_groups_api(request):
    """
    API接口：获取所有运营分组列表（支持按平台筛选）
    参数:
        - platform: 可选，平台名称 ('亚马逊' 或 'Temu')
    返回: ['A组', 'B组', 'C组', ...]
    """
    try:
        platform = request.GET.get('platform', '').strip()

        # 基础查询：排除空值
        queryset = OperationalAccount.objects.exclude(
            ops_group__isnull=True
        ).exclude(
            ops_group=''
        )

        # 如果指定了平台，通过关联User进行筛选
        if platform:
            queryset = queryset.filter(user__platform=platform)

        groups = queryset.values_list('ops_group', flat=True).distinct().order_by('ops_group')

        return JsonResponse({
            'success': True,
            'data': list(groups)
        })

    except Exception as e:
        print(f"❌ 获取分组列表错误: {str(e)}")
        import traceback
        traceback.print_exc()
        return JsonResponse({
            'success': False,
            'error': f'服务器错误: {str(e)}'
        }, status=500)