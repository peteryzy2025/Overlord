from django.db import models  # 添加这一行
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods
from django.db import transaction
from django.core.exceptions import ValidationError
from .models import User, PerformanceTarget, OperationalAccount
import json
from datetime import datetime


def performance_targets(request):
    """
    绩效目标管理页面视图
    """
    if not request.user.is_authenticated:
        return redirect('login')

    return render(request, 'performance_targets.html', {
        'active_nav': 'management',
        'theme': request.COOKIES.get('theme', 'light')
    })


def get_group_targets(request):
    """
    获取所有小组的绩效目标汇总
    """
    if not request.user.is_authenticated:
        return JsonResponse({'success': False, 'error': '未登录'}, status=401)

    month = request.GET.get('month', datetime.now().strftime('%Y-%m'))

    # FIX: 使用 user__operational_account__ops_group
    groups = PerformanceTarget.objects.filter(
        month=month,
        user__operational_account__ops_group__isnull=False
    ).values(
        'user__operational_account__ops_group'
    ).annotate(
        total_target=models.Sum('target_performance'),
        total_stretch=models.Sum('stretch_target'),
        member_count=models.Count('user')
    ).order_by('user__operational_account__ops_group')

    return JsonResponse({
        'success': True,
        'data': list(groups),
        'month': month
    })


@require_http_methods(["GET"])
def get_performance_targets(request):
    """
    获取绩效目标列表
    """
    if not request.user.is_authenticated:
        return JsonResponse({'success': False, 'error': '未登录'}, status=401)

    month = request.GET.get('month', datetime.now().strftime('%Y-%m'))
    ops_group = request.GET.get('ops_group', '')

    targets = PerformanceTarget.objects.filter(month=month)

    if ops_group:
        # FIX: 使用 user__operational_account__ops_group
        targets = targets.filter(user__operational_account__ops_group=ops_group)

    # 如果不是permission=555的用户，只能查看自己小组的目标
    if request.user.permission != '555':
        # FIX: 使用 user__operational_account__ops_group
        targets = targets.filter(
            user__operational_account__ops_group=request.user.operational_account.ops_group
        )

    data = []
    for target in targets:
        # FIX: 通过 operational_account 获取 ops_group
        ops_group = target.user.operational_account.ops_group if hasattr(target.user, 'operational_account') else '-'

        data.append({
            'id': target.id,
            'user_id': target.user.id,
            'user_name': target.user.first_name or target.user.username,
            'username': target.user.username,
            'ops_group': ops_group,
            'role': target.user.role or '-',
            'month': target.month,
            'target_performance': target.target_performance,
            'stretch_target': target.stretch_target,
            'note': target.note or '',
            'created_by': target.created_by.first_name if target.created_by else '-'
        })

    return JsonResponse({
        'success': True,
        'data': data,
        'total': len(data)
    })


@require_http_methods(["POST"])
@transaction.atomic
def create_group_target(request):
    """
    创建小组绩效目标（仅permission=555可用）
    """
    if not request.user.is_authenticated:
        return JsonResponse({'success': False, 'error': '未登录'}, status=401)

    if request.user.permission != '555':
        return JsonResponse({'success': False, 'error': '无权限操作'}, status=403)

    try:
        data = json.loads(request.body)
        month = data.get('month')
        ops_group = data.get('ops_group')
        target_performance = int(data.get('target_performance', 0))
        stretch_target = int(data.get('stretch_target', 0))
        note = data.get('note', '')

        # FIX: 使用 operational_account__ops_group 查询
        group_members = User.objects.filter(
            operational_account__ops_group=ops_group,
            status=User.STATUS_NORMAL
        )

        if not group_members.exists():
            return JsonResponse({'success': False, 'error': '该小组没有成员'}, status=400)

        created_targets = []
        for member in group_members:
            target, created = PerformanceTarget.objects.update_or_create(
                user=member,
                month=month,
                defaults={
                    'target_performance': 0,
                    'stretch_target': 0,
                    'note': note,
                    'created_by': request.user
                }
            )
            created_targets.append(target.id)

        return JsonResponse({
            'success': True,
            'message': f'已为小组 {ops_group} 创建 {len(created_targets)} 条绩效目标',
            'targets': created_targets
        })

    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@require_http_methods(["POST"])
@transaction.atomic
def update_performance_target(request, target_id):
    """
    更新个人绩效目标
    """
    if not request.user.is_authenticated:
        return JsonResponse({'success': False, 'error': '未登录'}, status=401)

    try:
        target = PerformanceTarget.objects.get(id=target_id)
    except PerformanceTarget.DoesNotExist:
        return JsonResponse({'success': False, 'error': '目标不存在'}, status=404)

    # FIX: 获取正确的 ops_group
    target_ops_group = target.user.operational_account.ops_group if hasattr(target.user,
                                                                            'operational_account') else None
    request_ops_group = request.user.operational_account.ops_group if hasattr(request.user,
                                                                              'operational_account') else None

    # 权限检查：只能修改自己小组的成员目标
    if request.user.permission != '555' and target_ops_group != request_ops_group:
        return JsonResponse({'success': False, 'error': '只能修改本组成员目标'}, status=403)

    # 如果是组长，不能修改自己的
    if request.user.role == 'leader' and target.user.id == request.user.id:
        return JsonResponse({'success': False, 'error': '组长不能修改自己的目标'}, status=403)

    try:
        data = json.loads(request.body)
        new_target = int(data.get('target_performance', target.target_performance))
        new_stretch = int(data.get('stretch_target', target.stretch_target))
        note = data.get('note', target.note)

        if new_stretch <= new_target:
            return JsonResponse({'success': False, 'error': '冲单目标必须大于基础目标'}, status=400)

        # 检查总额是否匹配（仅组长修改时检查）
        if request.user.role == 'leader':
            month = target.month
            # FIX: 使用 operational_account__ops_group
            ops_group = target_ops_group

            # 获取小组总目标
            try:
                # FIX: 查询逻辑需要根据实际数据模型调整
                # 这里假设555用户也在小组中且有目标记录
                group_target_obj = PerformanceTarget.objects.filter(
                    month=month,
                    user__operational_account__ops_group=ops_group,
                    user__permission='555'
                ).first()

                if not group_target_obj:
                    return JsonResponse({'success': False, 'error': '未找到小组总目标'}, status=400)

                group_target = group_target_obj.target_performance

                # 计算其他成员的目标总和
                # FIX: 使用 operational_account__ops_group
                other_targets_sum = PerformanceTarget.objects.filter(
                    month=month,
                    user__operational_account__ops_group=ops_group
                ).exclude(id=target_id).aggregate(
                    total=models.Sum('target_performance')
                )['total'] or 0

                if other_targets_sum + new_target != group_target:
                    return JsonResponse({
                        'success': False,
                        'error': f'单量总和必须等于小组目标 {group_target} 单，当前其他成员总和 {other_targets_sum} 单，您可分配 {group_target - other_targets_sum} 单'
                    }, status=400)

            except Exception as e:
                return JsonResponse({'success': False, 'error': f'校验失败: {str(e)}'}, status=500)

        target.target_performance = new_target
        target.stretch_target = new_stretch
        target.note = note
        target.save()

        return JsonResponse({
            'success': True,
            'message': '目标更新成功'
        })

    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@require_http_methods(["GET"])
def get_groups(request):
    """
    获取所有小组列表
    """
    if not request.user.is_authenticated:
        return JsonResponse({'success': False, 'error': '未登录'}, status=401)

    # FIX: 使用 operational_account__ops_group
    groups = User.objects.filter(
        operational_account__ops_group__isnull=False
    ).values_list('operational_account__ops_group', flat=True).distinct().order_by('operational_account__ops_group')

    return JsonResponse({
        'success': True,
        'data': [{'id': g, 'name': g} for g in groups if g]
    })
