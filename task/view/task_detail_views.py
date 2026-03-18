# Task/view/task_detail_views.py

import json
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from django.db.models import Q
from django.utils import timezone

from task.models import Task, SubTask, AmazonUploadFile
from general.models import User
from task.utils import parse_permissions


@login_required
def task_detail_page(request, task_id):
    """
    任务详情页面
    GET /task/detail/<task_id>/
    """
    # 权限检查
    task = get_object_or_404(Task, id=task_id)
    current_user = request.user
    permissions = parse_permissions(getattr(current_user, 'permission', ''))

    # 检查是否有权限查看此任务
    has_permission = False
    if 'ops_all' in permissions:
        has_permission = True
    elif task.created_by == current_user or task.owner == current_user:
        has_permission = True
    elif 'ops_group' in permissions and hasattr(current_user, 'operational_account'):
        group_name = current_user.operational_account.ops_group
        if group_name:
            if hasattr(task.created_by, 'operational_account') and \
                    task.created_by.operational_account.ops_group == group_name:
                has_permission = True
            elif hasattr(task.owner, 'operational_account') and \
                    task.owner.operational_account.ops_group == group_name:
                has_permission = True

    if not has_permission:
        return render(request, 'error.html', {'message': '无权查看此任务'}, status=403)

    return render(request, 'task_detail.html', {
        'task_id': task_id,
        'task': task,
        'active_nav': 'task_manage'
    })


@login_required
@require_http_methods(["GET"])
def get_task_detail_api(request, task_id):
    """
    获取任务详情API
    GET /api/tasks/<task_id>/detail/
    """
    try:
        task = get_object_or_404(
            Task.objects.select_related('created_by', 'owner').prefetch_related(
                'subtasks',
                'subtasks__amazon_upload_files',
                'subtasks__amazon_upload_files__amazon_shop'
            ),
            id=task_id
        )
        current_user = request.user
        permissions = parse_permissions(getattr(current_user, 'permission', ''))

        # 权限检查（同上）
        has_permission = False
        if 'ops_all' in permissions:
            has_permission = True
        elif task.created_by == current_user or task.owner == current_user:
            has_permission = True
        elif 'ops_group' in permissions and hasattr(current_user, 'operational_account'):
            group_name = current_user.operational_account.ops_group
            if group_name:
                if hasattr(task.created_by, 'operational_account') and \
                        task.created_by.operational_account.ops_group == group_name:
                    has_permission = True
                elif hasattr(task.owner, 'operational_account') and \
                        task.owner.operational_account.ops_group == group_name:
                    has_permission = True

        if not has_permission:
            return JsonResponse({'success': False, 'message': '无权查看'}, status=403)

        # 组装任务基本信息
        task_data = {
            'id': task.id,
            'task_no': task.task_no,
            'title': task.title,
            'status': task.status,
            'status_display': task.get_status_display(),
            'task_type': task.task_type,
            'created_by_name': task.created_by.first_name or task.created_by.username,
            'owner_name': task.owner.first_name or task.owner.username,
            'created_at': task.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            'submitted_at': task.submitted_at.strftime('%Y-%m-%d %H:%M:%S') if task.submitted_at else None,
        }

        # 获取子任务列表
        subtasks_data = []
        subtasks = task.subtasks.all().order_by('order')

        for subtask in subtasks:
            # 所有子任务类型都直接使用数据库状态
            subtask_status = subtask.subtask_status
            subtask_info = {
                'id': subtask.id,
                'type': subtask.subtask_type,
                'type_display': subtask.get_subtask_type_display(),
                'status': subtask_status,
                'status_display': dict(SubTask.STATUS_CHOICES).get(subtask_status, subtask_status),
                'order': subtask.order,
                'params': subtask.params,
                'is_executed': subtask.is_executed,
                'executed_at': subtask.executed_at.strftime('%Y-%m-%d %H:%M:%S') if subtask.executed_at else None,
            }

            # 如果是amazon_upload类型，附加文件列表
            if subtask.subtask_type == 'amazon_upload':
                files = subtask.amazon_upload_files.all().order_by('created_at')
                files_data = []
                for f in files:
                    files_data.append({
                        'id': f.id,
                        'shop_name': f.amazon_shop.shop_name if f.amazon_shop else f.shop_name_suffix,
                        'shop_name_suffix': f.shop_name_suffix,
                        'filename': f.excel_filename,
                        'status': f.status,
                        'status_display': f.get_status_display(),
                        'success_sku': f.success_sku,
                        'total_sku': f.total_sku,
                        'progress': f"{f.success_sku}/{f.total_sku}" if f.success_sku is not None and f.total_sku is not None else "-/-",
                        'created_at': f.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                        'uploaded_at': f.uploaded_at.strftime('%Y-%m-%d %H:%M:%S') if f.uploaded_at else None,
                    })
                subtask_info['files'] = files_data

            subtasks_data.append(subtask_info)

        return JsonResponse({
            'success': True,
            'data': {
                'task': task_data,
                'subtasks': subtasks_data
            }
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({
            'success': False,
            'message': f'获取详情失败: {str(e)}'
        }, status=500)


@login_required
@require_http_methods(["GET"])
def get_pending_files_api(request):
    """
    获取待上传的文件列表（供影刀调用）
    GET /api/tasks/amazon-upload/pending-files/
    """
    try:
        # 获取所有pending状态的文件
        pending_files = AmazonUploadFile.objects.filter(
            status=AmazonUploadFile.STATUS_PENDING
        ).select_related('task', 'amazon_shop')

        data = []
        for f in pending_files:
            data.append({
                'file_id': f.id,
                'task_no': f.task.task_no,
                'shop_name': f.amazon_shop.shop_name if f.amazon_shop else f.shop_name_suffix,
                'shop_name_suffix': f.shop_name_suffix,
                'filename': f.excel_filename,
                'target_path': f.target_path,
                'created_at': f.created_at.strftime('%Y-%m-%d %H:%M:%S')
            })

        return JsonResponse({
            'success': True,
            'data': data
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'获取失败: {str(e)}'
        }, status=500)


@login_required
@require_http_methods(["POST"])
def update_upload_status_api(request):
    """
    更新文件上传状态（供影刀调用）
    POST /api/tasks/amazon-upload/update-status/

    Request Body:
    {
        "file_id": 1,
        "status": "completed",  // completed/failed/uploading
        "success_sku": 150,
        "total_sku": 165
    }
    """
    try:
        data = json.loads(request.body)
        file_id = data.get('file_id')
        status = data.get('status')
        success_sku = data.get('success_sku')
        total_sku = data.get('total_sku')

        if not file_id or not status:
            return JsonResponse({
                'success': False,
                'message': '缺少必要参数: file_id 和 status'
            }, status=400)

        # 验证状态值
        valid_statuses = [AmazonUploadFile.STATUS_PENDING,
                          AmazonUploadFile.STATUS_UPLOADING,
                          AmazonUploadFile.STATUS_COMPLETED,
                          AmazonUploadFile.STATUS_FAILED]
        if status not in valid_statuses:
            return JsonResponse({
                'success': False,
                'message': f'无效的状态值，必须是: {", ".join(valid_statuses)}'
            }, status=400)

        try:
            upload_file = AmazonUploadFile.objects.get(id=file_id)
        except AmazonUploadFile.DoesNotExist:
            return JsonResponse({
                'success': False,
                'message': '文件记录不存在'
            }, status=404)

        # 更新状态
        upload_file.status = status
        if success_sku is not None:
            upload_file.success_sku = success_sku
        if total_sku is not None:
            upload_file.total_sku = total_sku

        if status == AmazonUploadFile.STATUS_COMPLETED:
            upload_file.uploaded_at = timezone.now()

        upload_file.save()
        subtask_status = upload_file.subtask.sync_amazon_upload_status()

        return JsonResponse({
            'success': True,
            'message': '状态更新成功',
            'data': {
                'file_id': upload_file.id,
                'status': upload_file.status,
                'progress': f"{upload_file.success_sku}/{upload_file.total_sku}" if upload_file.success_sku is not None else "-/-",
                'subtask_status': subtask_status,
                'subtask_status_display': dict(SubTask.STATUS_CHOICES).get(subtask_status, subtask_status)
            }
        })

    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'message': 'JSON格式错误'
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'更新失败: {str(e)}'
        }, status=500)
