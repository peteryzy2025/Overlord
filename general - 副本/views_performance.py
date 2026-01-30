# General/views_performance.py

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.csrf import csrf_exempt
from django.db import transaction
from django.db.models import Q, Sum
from general.models import User, OperationalAccount, GroupPerformanceTarget, PersonalPerformanceTarget
import json
import traceback
from datetime import datetime
from api.WX.wx import send_wechat_work_message


# ==========================================
# 页面渲染
# ==========================================

@login_required
def performance_targets_view(request):
    """渲染绩效管理页面"""
    # 判断当前用户权限
    context = {
        'can_manage_group': request.user.can_manage_group_targets(),
        'is_group_leader': request.user.is_group_leader(),
        'user_ops_group': request.user.get_ops_group(),
        'active_page': 'performance_targets',
    }
    return render(request, 'performance_targets.html', context)


# ==========================================
# 组目标管理API
# ==========================================

@require_GET
@login_required
def get_group_targets_api(request):
    """
    获取组绩效目标列表（支持分页和筛选）
    支持参数: page, page_size, month, ops_group, search
    """
    try:
        page = int(request.GET.get('page', 1))
        page_size = int(request.GET.get('page_size', 10))

        if page < 1: page = 1
        if page_size not in [10, 20, 50, 100]: page_size = 10

        query = GroupPerformanceTarget.objects.select_related('created_by').all()

        # 筛选条件
        month_filter = request.GET.get('month', '').strip()
        if month_filter:
            # 补全日期为1号
            try:
                if len(month_filter) == 7:  # YYYY-MM
                    month_filter = f"{month_filter}-01"
                query = query.filter(month=month_filter)
            except Exception:
                pass  # 格式不对就不筛选日期

        ops_group_filter = request.GET.get('ops_group', '').strip()
        if ops_group_filter:
            query = query.filter(ops_group=ops_group_filter)

        search = request.GET.get('search', '').strip()
        if search:
            query = query.filter(
                Q(ops_group__icontains=search) |
                Q(note__icontains=search)
            )

        total_count = query.count()
        offset = (page - 1) * page_size
        targets = query.order_by('-month', 'ops_group')[offset:offset + page_size]

        data = []
        for target in targets:
            # 计算当前成员目标总和
            member_totals = target.get_current_member_total()

            data.append({
                'id': target.id,
                'month': target.month,
                'ops_group': target.ops_group,
                'target_performance': target.target_performance,
                'member_target_total': member_totals['target_total'],
                'is_balanced': member_totals['matches_group_target'],
                'note': target.note or '-',
                'creator_name': target.created_by.first_name if target.created_by else '系统',
                'created_at': target.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                'updated_at': target.updated_at.strftime('%Y-%m-%d %H:%M:%S'),
            })

        return JsonResponse({
            'success': True,
            'data': data,
            'total': total_count,
            'page': page,
            'page_size': page_size
        })

    except Exception as e:
        print(f"❌ 获取组目标列表错误: {str(e)}")
        traceback.print_exc()
        return JsonResponse({'success': False, 'error': f'服务器错误: {str(e)}'}, status=500)


@require_POST
@csrf_exempt
@login_required
def create_group_target_api(request):
    """创建组绩效目标（需permission包含555）"""
    try:
        # 权限检查
        if not request.user.can_manage_group_targets():
            return JsonResponse({'success': False, 'error': '无权限创建组目标'}, status=403)

        data = json.loads(request.body)

        month = data.get('month', '').strip()
        ops_group = data.get('ops_group', '').strip()
        target_performance = int(data.get('target_performance', 0))
        note = data.get('note', '')

        # 验证
        if not month or not ops_group:
            return JsonResponse({'success': False, 'error': '月份和运营分组是必填项'}, status=400)

        try:
            # 格式校验并转换为 YYYY-MM-01
            date_obj = datetime.strptime(month, '%Y-%m')
            month = date_obj.strftime('%Y-%m-01')
        except ValueError:
            return JsonResponse({'success': False, 'error': '月份格式错误，应为YYYY-MM'}, status=400)

        # 检查重复
        if GroupPerformanceTarget.objects.filter(month=month, ops_group=ops_group).exists():
            return JsonResponse({'success': False, 'error': '该组该月份已存在目标'}, status=400)

        with transaction.atomic():
            target = GroupPerformanceTarget.objects.create(
                month=month,
                ops_group=ops_group,
                target_performance=target_performance,
                note=note,
                created_by=request.user
            )

        try:
            recipients = User.objects.filter(
                operational_account__ops_group=ops_group,
                status=User.STATUS_NORMAL
            ).exclude(wx_url__isnull=True).exclude(wx_url='')
            month_display = month[:7] if len(month) >= 7 else month
            content = "\n".join([
                "**绩效目标通知**",
                "",
                f"组：{ops_group}",
                f"月份：{month_display}",
                f"组目标：{target_performance}",
                "",
                "请前往系统页面查看：/performance/"
            ])
            sent_count = 0
            for u in recipients:
                result = send_wechat_work_message(u.wx_url, content)
                if result.get('success'):
                    sent_count += 1
        except Exception:
            pass

        return JsonResponse({
            'success': True,
            'message': '组目标创建成功',
            'target_id': target.id,
            'notify_sent': sent_count if 'sent_count' in locals() else 0
        })

    except Exception as e:
        print(f"❌ 创建组目标错误: {str(e)}")
        traceback.print_exc()
        return JsonResponse({'success': False, 'error': f'服务器错误: {str(e)}'}, status=500)


@require_POST
@csrf_exempt
@login_required
def update_group_target_api(request, target_id):
    """更新组绩效目标"""
    try:
        if not request.user.can_manage_group_targets():
            return JsonResponse({'success': False, 'error': '无权限修改组目标'}, status=403)

        try:
            target = GroupPerformanceTarget.objects.get(id=target_id)
        except GroupPerformanceTarget.DoesNotExist:
            return JsonResponse({'success': False, 'error': '组目标不存在'}, status=404)

        data = json.loads(request.body or '{}')

        target_performance = int(data.get('target_performance', target.target_performance))
        note = data.get('note', target.note or '')

        # 检查成员目标总和是否匹配
        member_totals = target.get_current_member_total()
        if member_totals['target_total'] != target_performance:
            return JsonResponse({
                'success': False,
                'error': f'成员目标总和({member_totals["target_total"]})与组目标不符，请先调整成员目标'
            }, status=400)

        with transaction.atomic():
            target.target_performance = target_performance
            target.note = note
            target.save()

        return JsonResponse({'success': True, 'message': '组目标更新成功'})

    except Exception as e:
        print(f"❌ 更新组目标错误: {str(e)}")
        traceback.print_exc()
        return JsonResponse({'success': False, 'error': f'服务器错误: {str(e)}'}, status=500)


# ==========================================
# 个人目标管理API
# ==========================================

@require_GET
@login_required
def get_personal_targets_api(request):
    """
    获取个人绩效目标列表（运营组长只能看自己组，其他人看所有）
    支持参数: page, page_size, month, user, ops_group, search
    """
    try:
        page = int(request.GET.get('page', 1))
        page_size = int(request.GET.get('page_size', 10))

        if page < 1: page = 1
        if page_size not in [10, 20, 50, 100]: page_size = 10

        query = PersonalPerformanceTarget.objects.select_related('user', 'created_by').all()

        # 如果是运营组长，只能看自己组的目标
        if request.user.is_group_leader():
            ops_group = request.user.get_ops_group()
            if ops_group:
                query = query.filter(ops_group=ops_group)
            else:
                query = query.none()  # 没有分组则看不到任何数据

        # 筛选条件
        month_filter = request.GET.get('month', '').strip()
        if month_filter:
            # 补全日期为1号
            try:
                if len(month_filter) == 7:  # YYYY-MM
                    month_filter = f"{month_filter}-01"
                query = query.filter(month=month_filter)
            except Exception:
                pass

        user_filter = request.GET.get('user', '').strip()
        if user_filter:
            query = query.filter(user_id=int(user_filter))

        ops_group_filter = request.GET.get('ops_group', '').strip()
        if ops_group_filter and request.user.can_manage_group_targets():
            query = query.filter(ops_group=ops_group_filter)

        search = request.GET.get('search', '').strip()
        if search:
            query = query.filter(
                Q(user__first_name__icontains=search) |
                Q(user__username__icontains=search) |
                Q(month__icontains=search)
            )

        total_count = query.count()
        offset = (page - 1) * page_size
        targets = query.order_by('-month', 'user__first_name')[offset:offset + page_size]

        data = []
        for target in targets:
            data.append({
                'id': target.id,
                'user_id': target.user_id,
                'user_name': target.user.first_name or target.user.username,
                'ops_group': target.ops_group or '-',
                'month': target.month,
                'target_performance': target.target_performance,
                'note': target.note or '-',
                'creator_name': target.created_by.first_name if target.created_by else '系统',
                'created_at': target.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                'updated_at': target.updated_at.strftime('%Y-%m-%d %H:%M:%S'),
            })

        return JsonResponse({
            'success': True,
            'data': data,
            'total': total_count,
            'page': page,
            'page_size': page_size
        })

    except Exception as e:
        print(f"❌ 获取个人目标列表错误: {str(e)}")
        traceback.print_exc()
        return JsonResponse({'success': False, 'error': f'服务器错误: {str(e)}'}, status=500)


@require_POST
@csrf_exempt
@login_required
def batch_create_personal_targets_api(request):
    """
    批量创建/更新个人绩效目标（运营组长专用）
    请求体: {
        month: '2025-01',
        ops_group: '李湘杰组',
        targets: [
            {user_id: 1, target_performance: 100, stretch_target: 120, note: ''},
            {user_id: 2, target_performance: 150, stretch_target: 180, note: ''}
        ]
    }
    """
    try:
        # 权限检查：必须是运营组长
        if not request.user.is_group_leader():
            return JsonResponse({'success': False, 'error': '只有运营组长可以批量设置组员目标'}, status=403)

        data = json.loads(request.body)

        month = data.get('month', '').strip()
        ops_group = data.get('ops_group', '').strip()
        targets_data = data.get('targets', [])

        # 格式化日期
        try:
            if len(month) == 7:
                month = f"{month}-01"
            datetime.strptime(month, '%Y-%m-%d')
        except ValueError:
             return JsonResponse({'success': False, 'error': '月份格式错误'}, status=400)

        # 验证组长只能设置自己组的目标
        user_ops_group = request.user.get_ops_group()
        if not user_ops_group or user_ops_group != ops_group:
            return JsonResponse({'success': False, 'error': f'您只能管理自己所在组({user_ops_group})的目标'},
                                status=403)

        # 验证组目标是否存在
        group_target = GroupPerformanceTarget.objects.filter(
            month=month, ops_group=ops_group
        ).first()

        if not group_target:
            return JsonResponse({'success': False, 'error': '请先创建该月份的组目标'}, status=400)

        # 验证成员目标总和等于组目标
        total_target = sum([t.get('target_performance', 0) for t in targets_data])

        if total_target != group_target.target_performance:
            return JsonResponse({
                'success': False,
                'error': f'组员目标总和({total_target})必须等于组目标({group_target.target_performance})'
            }, status=400)

        # 验证所有成员都属于该组
        user_ids = [t['user_id'] for t in targets_data]
        group_members = User.objects.filter(
            id__in=user_ids,
            operational_account__ops_group=ops_group
        )

        if group_members.count() != len(user_ids):
            return JsonResponse({'success': False, 'error': '只能为本组成员设置目标'}, status=400)

        # 批量创建或更新
        created_count = 0
        updated_count = 0
        notify_list = []

        with transaction.atomic():
            for target_info in targets_data:
                user_id = target_info['user_id']
                target_performance = target_info.get('target_performance', 0)
                note = target_info.get('note', '')

                # 检查是否已存在
                existing = PersonalPerformanceTarget.objects.filter(
                    user_id=user_id, month=month
                ).first()

                if existing:
                    existing.target_performance = target_performance
                    existing.note = note
                    existing.created_by = request.user
                    existing.save()
                    updated_count += 1
                    notify_list.append({'user_id': user_id, 'target_performance': target_performance, 'status': 'updated'})
                else:
                    PersonalPerformanceTarget.objects.create(
                        user_id=user_id,
                        month=month,
                        target_performance=target_performance,
                        note=note,
                        ops_group=ops_group,
                        created_by=request.user
                    )
                    created_count += 1
                    notify_list.append({'user_id': user_id, 'target_performance': target_performance, 'status': 'created'})

        try:
            month_display = month[:7] if len(month) >= 7 else month
            for item in notify_list:
                u = User.objects.filter(id=item['user_id'], status=User.STATUS_NORMAL).exclude(wx_url__isnull=True).exclude(wx_url='').first()
                if not u:
                    continue
                action = "已设置" if item['status'] == 'created' else "已更新"
                content = "\n".join([
                    "**个人绩效目标通知**",
                    "",
                    f"组：{ops_group}",
                    f"月份：{month_display}",
                    f"目标：{item['target_performance']}",
                    f"状态：{action}",
                    "",
                    f"分配人：{request.user.first_name or request.user.username}",
                    "",
                    "请前往系统页面查看：/performance/"
                ])
                send_wechat_work_message(u.wx_url, content)
        except Exception:
            pass

        return JsonResponse({
            'success': True,
            'message': f'批量设置成功！新建{created_count}个，更新{updated_count}个',
            'created': created_count,
            'updated': updated_count
        })

    except Exception as e:
        print(f"❌ 批量设置个人目标错误: {str(e)}")
        traceback.print_exc()
        return JsonResponse({'success': False, 'error': f'服务器错误: {str(e)}'}, status=500)


# ==========================================
# 筛选选项API
# ==========================================

@require_GET
@login_required
def get_ops_groups_for_filter_api(request):
    """
    获取所有运营分组列表（用于筛选器，去重去空）
    返回: ['李湘杰组', '王五组', ...]
    """
    try:
        groups = OperationalAccount.objects.exclude(
            ops_group__isnull=True
        ).exclude(
            ops_group=''
        ).values_list('ops_group', flat=True).distinct().order_by('ops_group')

        return JsonResponse({
            'success': True,
            'data': list(groups)
        })

    except Exception as e:
        print(f"❌ 获取运营分组列表错误: {str(e)}")
        traceback.print_exc()
        return JsonResponse({'success': False, 'error': f'服务器错误: {str(e)}'}, status=500)


@require_GET
@login_required
def get_operators_by_group_api(request):
    """
    根据分组获取运营人员列表
    参数: ops_group
    返回: [{id, first_name, username}, ...]
    """
    try:
        ops_group = request.GET.get('ops_group', '').strip()
        if not ops_group:
            return JsonResponse({'success': False, 'error': '需要提供ops_group参数'}, status=400)

        users = User.objects.filter(
            department='运营部门',
            operational_account__ops_group=ops_group
        ).order_by('first_name')

        data = []
        for user in users:
            data.append({
                'id': user.id,
                'first_name': user.first_name or user.username,
                'username': user.username,
            })

        return JsonResponse({
            'success': True,
            'data': data
        })

    except Exception as e:
        print(f"❌ 获取分组运营人员错误: {str(e)}")
        traceback.print_exc()
        return JsonResponse({'success': False, 'error': f'服务器错误: {str(e)}'}, status=500)
