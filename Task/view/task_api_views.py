# Task/view/task_api_views.py

import json
import requests
import threading
from datetime import datetime
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from django.utils import timezone
from django.db.models import Q
from django.db import transaction

from general.models import User, AmazonShop, TemuShop
from task.models import Task, SubTask, TaskTemplate
from task.utils import (
    generate_task_no,
    get_visible_shops,
    parse_permissions,
    validate_subtask_params
)


@login_required
@require_http_methods(["GET"])
def get_available_shops_api(request):
    """
    获取可见店铺列表（带权限控制）
    GET /api/tasks/shops/?type=amazon|temu
    """
    try:
        shop_type = request.GET.get('type', 'amazon')
        permissions = parse_permissions(getattr(request.user, 'permission', ''))

        # 基础查询
        if shop_type == 'amazon':
            # Amazon：ops是外键，可以用select_related
            queryset = AmazonShop.objects.filter(ops__isnull=False).select_related('ops')
        elif shop_type == 'temu':
            # Temu：ops_id是IntegerField，不能用select_related！
            queryset = TemuShop.objects.filter(ops_id__isnull=False)
        else:
            return JsonResponse({'success': False, 'message': '无效的店铺类型'}, status=400)

        # 权限过滤（完全复制邮件视图逻辑）
        if 'ops_all' not in permissions:
            if 'ops_group' in permissions and hasattr(request.user, 'operational_account'):
                group_name = request.user.operational_account.ops_group
                if group_name:
                    if shop_type == 'amazon':
                        queryset = queryset.filter(ops__operational_account__ops_group=group_name)
                    else:
                        # Temu：ops_id不是外键，需要用子查询
                        queryset = queryset.filter(
                            ops_id__in=User.objects.filter(
                                operational_account__ops_group=group_name
                            ).values_list('id', flat=True)
                        )
            else:
                if shop_type == 'amazon':
                    queryset = queryset.filter(ops=request.user)
                else:
                    queryset = queryset.filter(ops_id=request.user.id)

        # 组装数据
        shops_data = []
        for shop in queryset:
            if shop_type == 'amazon':
                shops_data.append({
                    'id': shop.id,
                    'name': f"{shop.shop_name} ({shop.ops.first_name if shop.ops else '无运营'})",
                    'raw_name': shop.shop_name
                })
            else:  # temu
                # 手动查询运营姓名
                try:
                    user = User.objects.get(id=shop.ops_id) if shop.ops_id else None
                    ops_name = user.first_name if user else '无运营'
                except User.DoesNotExist:
                    ops_name = '无运营'

                shops_data.append({
                    'id': shop.id,
                    'name': f"{shop.shop_name} ({ops_name})",
                    'raw_name': shop.shop_name
                })

        shops_data.sort(key=lambda x: x['raw_name'])

        return JsonResponse({'success': True, 'data': shops_data})

    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({'success': False, 'message': f'获取店铺列表失败: {str(e)}'}, status=500)
@login_required
@require_http_methods(["GET"])
def get_available_owners_api(request):
    """
    获取可创建任务的所有者列表
    GET /api/tasks/available-owners/
    """
    try:
        permissions = parse_permissions(getattr(request.user, 'permission', ''))
        current_user = request.user

        owners = []

        # 始终包含自己
        owners.append({
            'id': current_user.id,
            'name': f"{current_user.first_name} (自己)"
        })

        # 如果是管理员，可以选所有人
        if 'ops_all' in permissions:
            all_users = User.objects.filter(
                status=1,
                operational_account__isnull=False
            ).select_related('operational_account')

            for user in all_users:
                if user.id != current_user.id:
                    owners.append({
                        'id': user.id,
                        'name': f"{user.first_name} ({user.operational_account.ops_group or '未分组'})"
                    })

        # 如果是组长，可以选组内成员
        elif 'ops_group' in permissions and hasattr(current_user, 'operational_account'):
            group_name = current_user.operational_account.ops_group
            if group_name:
                group_users = User.objects.filter(
                    status=1,
                    operational_account__ops_group=group_name
                ).select_related('operational_account')

                for user in group_users:
                    if user.id != current_user.id:
                        owners.append({
                            'id': user.id,
                            'name': f"{user.first_name} (组内)"
                        })

        return JsonResponse({
            'success': True,
            'data': owners
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'获取所有者列表失败: {str(e)}'
        }, status=500)


@login_required
@require_http_methods(["GET"])
def generate_task_no_api(request):
    """
    生成任务单号
    GET /api/tasks/generate-no/
    """
    try:
        task_no = generate_task_no(request.user)
        return JsonResponse({
            'success': True,
            'data': {'task_no': task_no}
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'生成任务单号失败: {str(e)}'
        }, status=500)


@login_required
@require_http_methods(["GET"])
def suggest_gallery_paths_api(request):
    """
    获取图库路径建议（基于用户历史输入）
    GET /api/tasks/gallery-paths/suggest/
    """
    try:
        # 获取用户自己的历史路径
        user_paths = SubTask.objects.filter(
            task__created_by=request.user,
            subtask_type='custom_upload',
            params__has_key='gallery_path'
        ).values_list('params__gallery_path', flat=True).distinct()

        # 获取可见范围内的路径（如果是组长或管理员）
        permissions = parse_permissions(getattr(request.user, 'permission', ''))
        if 'ops_all' in permissions or 'ops_group' in permissions:
            visible_paths = SubTask.objects.filter(
                subtask_type='custom_upload',
                params__has_key='gallery_path'
            ).values_list('params__gallery_path', flat=True).distinct()
            all_paths = list(user_paths) + list(visible_paths)
        else:
            all_paths = list(user_paths)

        # 去重并排序
        unique_paths = list(dict.fromkeys(all_paths))[:50]  # 限制数量

        return JsonResponse({
            'success': True,
            'data': unique_paths
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'获取图库路径建议失败: {str(e)}'
        }, status=500)


@login_required
@require_http_methods(["POST"])
@transaction.atomic
def create_task_api(request):
    """
    创建任务（提交或草稿）
    POST /api/tasks/create/
    """
    try:
        data = json.loads(request.body)
        current_user = request.user

        # 基础验证
        title = data.get('title', '').strip()
        if not title:
            return JsonResponse({'success': False, 'message': '任务标题不能为空'})

        # 确定所有者（可为他人创建）
        owner_id = data.get('owner_id', current_user.id)
        try:
            owner = User.objects.get(id=owner_id)
        except User.DoesNotExist:
            return JsonResponse({'success': False, 'message': '指定的所有者不存在'})

        # 权限验证：只能为自己或权限范围内的用户创建
        permissions = parse_permissions(getattr(current_user, 'permission', ''))
        if owner_id != current_user.id:
            if 'ops_all' not in permissions:
                if 'ops_group' in permissions:
                    # 检查是否在同一个组
                    if not hasattr(current_user, 'operational_account') or \
                            not hasattr(owner, 'operational_account') or \
                            current_user.operational_account.ops_group != owner.operational_account.ops_group:
                        return JsonResponse({'success': False, 'message': '无权为该用户创建任务'}, status=403)
                else:
                    return JsonResponse({'success': False, 'message': '无权为该用户创建任务'}, status=403)

        # 验证子任务
        subtasks_data = data.get('subtasks', [])
        if not subtasks_data:
            return JsonResponse({'success': False, 'message': '至少需要一个子任务'})

        # 生成任务单号
        task_no = generate_task_no(current_user)

        # 创建主任务
        is_draft = data.get('is_draft', False)
        task = Task.objects.create(
            title=title,
            task_no=task_no,
            status='draft' if is_draft else 'pending',
            created_by=current_user,
            owner=owner,
            submitted_at=None if is_draft else timezone.now()
        )

        # 创建子任务
        for idx, subtask_data in enumerate(subtasks_data):
            try:
                subtask_type = subtask_data['type']
                params = subtask_data.get('params', {})

                # 验证子任务参数
                validation_result = validate_subtask_params(subtask_type, params, current_user)
                if not validation_result['valid']:
                    raise ValueError(validation_result['message'])

                SubTask.objects.create(
                    task=task,
                    subtask_type=subtask_type,
                    order=idx,
                    params=params
                )

            except Exception as e:
                # 回滚事务
                raise ValueError(f"子任务 #{idx + 1} 验证失败: {str(e)}")

        # 发送 Webhook 通知 (仅正式任务)
        if not is_draft:
            try:
                # 构造完整的通知数据
                webhook_data = data.copy()
                webhook_data.update({
                    'task_id': task.id,
                    'task_no': task_no,
                    'created_by_id': current_user.id,
                    'created_by_name': f"{current_user.first_name} {current_user.last_name}".strip() or current_user.username,
                    'owner_name': f"{owner.first_name} {owner.last_name}".strip() or owner.username,
                    'created_at': timezone.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'status': 'pending'
                })

                def send_webhook_task(payload):
                    url = "https://api.yingdao.com/api/tool/ipaas/webhook/callback/873825669915136000"
                    try:
                        requests.post(url, json=payload, timeout=10)
                    except Exception as e:
                        print(f"Webhook send failed: {e}")

                # 事务提交后异步发送，避免阻塞响应且确保数据已持久化
                transaction.on_commit(lambda: threading.Thread(target=send_webhook_task, args=(webhook_data,)).start())
            
            except Exception as e:
                # 仅打印错误，不影响任务创建流程
                print(f"Error preparing webhook: {e}")

        return JsonResponse({
            'success': True,
            'data': {
                'task_id': task.id,
                'task_no': task_no,
                'redirect_url': '/task/list/'
            }
        })

    except ValueError as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=400)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'创建任务失败: {str(e)}'
        }, status=500)


@login_required
@require_http_methods(["POST"])
@transaction.atomic
def save_draft_api(request):
    """
    保存草稿（支持创建和更新）
    POST /api/tasks/save-draft/
    """
    try:
        data = json.loads(request.body)
        current_user = request.user

        # 验证
        subtasks_data = data.get('subtasks', [])
        if not subtasks_data:
            return JsonResponse({'success': False, 'message': '草稿至少需要包含一个子任务'})

        # 确定所有者
        owner_id = data.get('owner_id', current_user.id)
        try:
            owner = User.objects.get(id=owner_id)
        except User.DoesNotExist:
            return JsonResponse({'success': False, 'message': '所有者不存在'})

        # 权限验证
        permissions = parse_permissions(getattr(current_user, 'permission', ''))
        if owner_id != current_user.id and 'ops_all' not in permissions:
            return JsonResponse({'success': False, 'message': '无权为该用户创建草稿'}, status=403)

        # 获取或创建主任务
        task_id = data.get('task_id')
        if task_id:
            # 更新现有草稿
            try:
                task = Task.objects.get(id=task_id, created_by=current_user)
                task.title = data.get('title', task.title)
                task.owner = owner
                task.save()
            except Task.DoesNotExist:
                return JsonResponse({'success': False, 'message': '草稿不存在或无权修改'}, status=404)
        else:
            # 创建新草稿
            title = data.get('title', '未命名任务')
            task_no = generate_task_no(current_user)

            task = Task.objects.create(
                title=title,
                task_no=task_no,
                status='draft',
                created_by=current_user,
                owner=owner
            )

        # 删除旧子任务
        task.subtasks.all().delete()

        # 创建新子任务
        for idx, subtask_data in enumerate(subtasks_data):
            subtask_type = subtask_data['type']
            params = subtask_data.get('params', {})

            # 草稿模式简化验证
            if not isinstance(params, dict):
                raise ValueError('子任务参数格式错误')

            SubTask.objects.create(
                task=task,
                subtask_type=subtask_type,
                order=idx,
                params=params
            )

        return JsonResponse({
            'success': True,
            'data': {'task_id': task.id}
        })

    except ValueError as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=400)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'保存草稿失败: {str(e)}'
        }, status=500)


@login_required
@require_http_methods(["GET"])
def get_drafts_api(request):
    """
    获取用户的草稿列表
    GET /api/tasks/drafts/
    """
    try:
        drafts = Task.objects.filter(
            created_by=request.user,
            status='draft'
        ).order_by('-updated_at')[:10]

        drafts_data = [{
            'id': draft.id,
            'title': draft.title,
            'task_no': draft.task_no,
            'updated_at': draft.updated_at.strftime('%Y-%m-%d %H:%M:%S'),
            'subtask_count': draft.subtasks.count()
        } for draft in drafts]

        return JsonResponse({
            'success': True,
            'data': drafts_data
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'获取草稿列表失败: {str(e)}'
        }, status=500)


@login_required
@require_http_methods(["GET"])
def get_latest_draft_api(request):
    """
    获取最新的草稿（用于自动恢复）
    """
    try:
        draft = Task.objects.filter(
            created_by=request.user,
            status='draft'
        ).order_by('-updated_at').first()

        if not draft:
            return JsonResponse({'success': False, 'message': '没有草稿'}, status=404)

        subtasks = draft.subtasks.order_by('order')

        draft_data = {
            'id': draft.id,
            'title': draft.title,
            'owner_id': draft.owner_id,
            'subtasks': [{
                'id': subtask.id,
                'type': subtask.subtask_type,
                'params': subtask.params
            } for subtask in subtasks]
        }

        return JsonResponse({'success': True, 'data': draft_data})

    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)
@login_required
@require_http_methods(["DELETE"])
def delete_draft_api(request, task_id):
    """
    删除草稿
    DELETE /api/tasks/drafts/<task_id>/
    """
    try:
        task = Task.objects.get(id=task_id, created_by=request.user, status='draft')
        task.delete()

        return JsonResponse({'success': True, 'message': '草稿已删除'})

    except Task.DoesNotExist:
        return JsonResponse({
            'success': False,
            'message': '草稿不存在或无权删除'
        }, status=404)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'删除草稿失败: {str(e)}'
        }, status=500)


@login_required
@require_http_methods(["GET"])
def get_task_templates_api(request):
    """
    获取任务模板列表
    GET /api/tasks/templates/
    """
    try:
        templates = TaskTemplate.objects.filter(
            created_by=request.user
        ).order_by('-created_at')

        templates_data = [{
            'id': template.id,
            'name': template.name,
            'description': template.description,
            'created_at': template.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            'subtask_count': len(template.content) if isinstance(template.content, list) else 0
        } for template in templates]

        return JsonResponse({
            'success': True,
            'data': templates_data
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'获取模板列表失败: {str(e)}'
        }, status=500)


@login_required
@require_http_methods(["POST"])
def save_template_api(request):
    """
    保存任务模板
    POST /api/tasks/templates/save/
    """
    try:
        data = json.loads(request.body)

        # 验证
        name = data.get('name', '').strip()
        if not name:
            return JsonResponse({'success': False, 'message': '模板名称不能为空'})

        content = data.get('content', [])
        if not isinstance(content, list) or not content:
            return JsonResponse({'success': False, 'message': '模板内容不能为空'})

        # 清理内容
        cleaned_content = []
        for item in content:
            if not isinstance(item, dict):
                continue

            cleaned_content.append({
                'type': item.get('type'),
                'params': item.get('params', {})
            })

        # 创建模板
        template = TaskTemplate.objects.create(
            name=name,
            description=data.get('description', ''),
            content=cleaned_content,
            created_by=request.user
        )

        return JsonResponse({
            'success': True,
            'data': {'id': template.id}
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'保存模板失败: {str(e)}'
        }, status=500)


@login_required
@require_http_methods(["GET"])
def load_template_api(request, template_id):
    """
    加载任务模板详情
    GET /api/tasks/templates/<template_id>/load/
    """
    try:
        template = TaskTemplate.objects.get(id=template_id, created_by=request.user)

        return JsonResponse({
            'success': True,
            'data': {
                'id': template.id,
                'name': template.name,
                'description': template.description,
                'content': template.content
            }
        })

    except TaskTemplate.DoesNotExist:
        return JsonResponse({
            'success': False,
            'message': '模板不存在或无权访问'
        }, status=404)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'加载模板失败: {str(e)}'
        }, status=500)


@login_required
@require_http_methods(["DELETE"])
def delete_template_api(request, template_id):
    """
    删除任务模板
    DELETE /api/tasks/templates/<template_id>/
    """
    try:
        template = TaskTemplate.objects.get(id=template_id, created_by=request.user)
        template.delete()

        return JsonResponse({'success': True, 'message': '模板已删除'})

    except TaskTemplate.DoesNotExist:
        return JsonResponse({
            'success': False,
            'message': '模板不存在或无权删除'
        }, status=404)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'删除模板失败: {str(e)}'
        }, status=500)
