# Task/view/task_api_views.py

import json
import requests
import threading
import re
from datetime import datetime
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from django.db.models import Q
from django.db import transaction
from universal.permission_utils import get_user_permission_codes

from general.models import User, AmazonShop, TemuShop
from task.models import Task, TaskStatus, TaskType, SubTask, TaskTemplate, ProductRequirement
from task.utils import (
    generate_task_no,
    get_visible_shops,
    parse_permissions,
    validate_subtask_params
)
from api.wc.crawler_wc import get_ykartwood_product
from task.view.task_upload_views import process_amazon_upload_files


@csrf_exempt
@require_http_methods(["POST"])
def external_update_task_status_api(request):
    """
    对外主任务状态更新接口（无需登录）
    POST /api/external/tasks/update-status/

    支持 JSON 或 form-data：
    {
        "id": 1,              # 或 task_no
        "task_no": "TK001",
        "status": "completed"
    }
    """
    try:
        data = {}
        if request.body:
            try:
                data = json.loads(request.body)
            except json.JSONDecodeError:
                data = {}

        if not data:
            data = request.POST.dict()

        task_id = data.get('id')
        task_no = (data.get('task_no') or '').strip()
        status = (data.get('status') or '').strip()

        if not status:
            return JsonResponse({
                'success': False,
                'message': '缺少必要参数: status'
            }, status=400)

        if not task_id and not task_no:
            return JsonResponse({
                'success': False,
                'message': '缺少必要参数: id 或 task_no'
            }, status=400)

        valid_statuses = [choice.value for choice in TaskStatus]
        if status not in valid_statuses:
            return JsonResponse({
                'success': False,
                'message': f'无效的状态值，必须是: {", ".join(valid_statuses)}'
            }, status=400)

        queryset = Task.objects.all()
        if task_id:
            task = queryset.filter(id=task_id).first()
        else:
            task = queryset.filter(task_no=task_no).first()

        if not task:
            return JsonResponse({
                'success': False,
                'message': '任务不存在'
            }, status=404)

        task.status = status
        task.save()

        return JsonResponse({
            'success': True,
            'data': {
                'task_no': task.task_no,
                'task_name': task.title,
                'status': task.status
            }
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'更新任务状态失败: {str(e)}'
        }, status=500)


@csrf_exempt
@require_http_methods(["GET", "POST"])
def external_get_task_detail_api(request):
    """
    对外主任务详情接口（无需登录）
    GET/POST /api/external/tasks/detail/

    支持 query / JSON / form-data：
    {
        "id": 1,              # 或 task_no
        "task_no": "TK001"
    }
    """
    try:
        data = {}

        if request.method == "GET":
            data = request.GET.dict()
        else:
            if request.body:
                try:
                    data = json.loads(request.body)
                except json.JSONDecodeError:
                    data = {}
            if not data:
                data = request.POST.dict()

        task_id = data.get('id')
        task_no = (data.get('task_no') or '').strip()

        if not task_id and not task_no:
            return JsonResponse({
                'success': False,
                'message': '缺少必要参数: id 或 task_no'
            }, status=400)

        queryset = Task.objects.select_related('created_by', 'owner').prefetch_related(
            'subtasks',
            'subtasks__amazon_upload_files',
            'subtasks__amazon_upload_files__amazon_shop'
        )

        if task_id:
            task = queryset.filter(id=task_id).first()
        else:
            task = queryset.filter(task_no=task_no).first()

        if not task:
            return JsonResponse({
                'success': False,
                'message': '任务不存在'
            }, status=404)

        task_data = {
            'id': task.id,
            'task_no': task.task_no,
            'task_name': task.title,
            'title': task.title,
            'status': task.status,
            'status_display': task.get_status_display(),
            'task_type': task.task_type,
            'task_type_display': dict(TaskType.choices).get(task.task_type, task.task_type),
            'created_by_id': task.created_by_id,
            'created_by_name': task.created_by.first_name or task.created_by.username,
            'owner_id': task.owner_id,
            'owner_name': task.owner.first_name or task.owner.username,
            'created_at': task.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            'updated_at': task.updated_at.strftime('%Y-%m-%d %H:%M:%S'),
            'submitted_at': task.submitted_at.strftime('%Y-%m-%d %H:%M:%S') if task.submitted_at else None,
        }

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
                'execution_result': subtask.execution_result,
                'created_at': subtask.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                'updated_at': subtask.updated_at.strftime('%Y-%m-%d %H:%M:%S'),
            }

            if subtask.subtask_type == SubTask.TYPE_AMAZON_UPLOAD:
                files = subtask.amazon_upload_files.all().order_by('created_at')
                subtask_info['files'] = [{
                    'id': upload_file.id,
                    'shop_name': upload_file.amazon_shop.shop_name if upload_file.amazon_shop else upload_file.shop_name_suffix,
                    'shop_name_suffix': upload_file.shop_name_suffix,
                    'filename': upload_file.excel_filename,
                    'target_path': upload_file.target_path,
                    'status': upload_file.status,
                    'status_display': upload_file.get_status_display(),
                    'success_sku': upload_file.success_sku,
                    'total_sku': upload_file.total_sku,
                    'progress': f"{upload_file.success_sku}/{upload_file.total_sku}" if upload_file.success_sku is not None and upload_file.total_sku is not None else "-/-",
                    'created_at': upload_file.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                    'uploaded_at': upload_file.uploaded_at.strftime('%Y-%m-%d %H:%M:%S') if upload_file.uploaded_at else None,
                } for upload_file in files]

            subtasks_data.append(subtask_info)

        return JsonResponse({
            'success': True,
            'data': {
                'task': task_data,
                'subtasks': subtasks_data
            }
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'获取任务详情失败: {str(e)}'
        }, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def external_update_subtask_status_api(request):
    """
    对外子任务状态更新接口（无需登录）
    POST /api/external/tasks/subtasks/update-status/

    支持 JSON 或 form-data：
    {
        "task_id": 1,
        "subtask_id": 2,
        "status": "completed"
    }
    """
    try:
        data = {}
        if request.body:
            try:
                data = json.loads(request.body)
            except json.JSONDecodeError:
                data = {}

        if not data:
            data = request.POST.dict()

        task_id = data.get('task_id')
        subtask_id = data.get('subtask_id')
        status = (data.get('status') or '').strip()

        if not task_id or not subtask_id or not status:
            return JsonResponse({
                'success': False,
                'message': '缺少必要参数: task_id、subtask_id、status'
            }, status=400)

        valid_statuses = [choice[0] for choice in SubTask.STATUS_CHOICES]
        if status not in valid_statuses:
            return JsonResponse({
                'success': False,
                'message': f'无效的状态值，必须是: {", ".join(valid_statuses)}'
            }, status=400)

        subtask = SubTask.objects.filter(id=subtask_id, task_id=task_id).first()
        if not subtask:
            return JsonResponse({
                'success': False,
                'message': '子任务不存在，或不属于该主任务'
            }, status=404)

        subtask.subtask_status = status
        update_fields = ['subtask_status']

        if status in {SubTask.STATUS_COMPLETED, SubTask.STATUS_FAILED}:
            if not subtask.is_executed:
                subtask.is_executed = True
                update_fields.append('is_executed')
            if not subtask.executed_at:
                subtask.executed_at = timezone.now()
                update_fields.append('executed_at')
        elif status in {SubTask.STATUS_DRAFT, SubTask.STATUS_PENDING, SubTask.STATUS_IN_PROGRESS, SubTask.STATUS_CANCELLED}:
            if subtask.is_executed:
                subtask.is_executed = False
                update_fields.append('is_executed')

        subtask.save(update_fields=update_fields)

        return JsonResponse({
            'success': True,
            'data': {
                'subtask_id': subtask.id,
                'status': subtask.subtask_status
            }
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'更新子任务状态失败: {str(e)}'
        }, status=500)


@csrf_exempt
@require_http_methods(["GET", "POST"])
def external_get_subtask_detail_api(request):
    """
    对外获取子任务详情接口（无需登录）
    GET/POST /api/external/tasks/subtasks/detail/

    支持 query / JSON / form-data：
    {
        "subtask_id": 123
    }
    """
    try:
        data = {}

        if request.method == "GET":
            data = request.GET.dict()
        else:
            if request.body:
                try:
                    data = json.loads(request.body)
                except json.JSONDecodeError:
                    data = {}
            if not data:
                data = request.POST.dict()

        subtask_id = data.get('subtask_id')

        if not subtask_id:
            return JsonResponse({
                'success': False,
                'message': '缺少必要参数: subtask_id'
            }, status=400)

        try:
            subtask_id = int(subtask_id)
        except ValueError:
            return JsonResponse({
                'success': False,
                'message': 'subtask_id 必须是数字'
            }, status=400)

        # 查询子任务
        subtask = SubTask.objects.filter(id=subtask_id).first()
        if not subtask:
            return JsonResponse({
                'success': False,
                'message': '子任务不存在'
            }, status=404)

        # 构造响应数据
        subtask_data = {
            'id': subtask.id,
            'task_id': subtask.task_id,
            'type': subtask.subtask_type,
            'type_display': subtask.get_subtask_type_display(),
            'status': subtask.subtask_status,
            'status_display': dict(SubTask.STATUS_CHOICES).get(subtask.subtask_status, subtask.subtask_status),
            'order': subtask.order,
            'params': subtask.params,
            'is_executed': subtask.is_executed,
            'executed_at': subtask.executed_at.strftime('%Y-%m-%d %H:%M:%S') if subtask.executed_at else None,
            'execution_result': subtask.execution_result,
            'created_at': subtask.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            'updated_at': subtask.updated_at.strftime('%Y-%m-%d %H:%M:%S'),
        }

        return JsonResponse({
            'success': True,
            'data': subtask_data
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'获取子任务详情失败: {str(e)}'
        }, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def external_update_subtask_detail_api(request):
    """
    对外更新子任务详情接口（无需登录）
    POST /api/external/tasks/subtasks/update-detail/

    支持 JSON 或 form-data：
    {
        "subtask_id": 123,
        "params": {
            "diwei_account": "测试",
            "local_gallery_path": "\\\path\\\to\\\folder",
            ...
        },
        "status": "completed"  // 可选，不传则不修改状态
    }
    """
    try:
        data = {}
        if request.body:
            try:
                data = json.loads(request.body)
            except json.JSONDecodeError:
                data = {}
        if not data:
            data = request.POST.dict()

        subtask_id = data.get('subtask_id')
        new_params = data.get('params')
        new_status = (data.get('status') or '').strip()

        if not subtask_id:
            return JsonResponse({
                'success': False,
                'message': '缺少必要参数: subtask_id'
            }, status=400)

        try:
            subtask_id = int(subtask_id)
        except ValueError:
            return JsonResponse({
                'success': False,
                'message': 'subtask_id 必须是数字'
            }, status=400)

        # 查询子任务
        subtask = SubTask.objects.filter(id=subtask_id).first()
        if not subtask:
            return JsonResponse({
                'success': False,
                'message': '子任务不存在'
            }, status=404)

        # 验证状态值（如果提供了）
        if new_status:
            valid_statuses = [choice[0] for choice in SubTask.STATUS_CHOICES]
            if new_status not in valid_statuses:
                return JsonResponse({
                    'success': False,
                    'message': f'无效的状态值，必须是: {", ".join(valid_statuses)}'
                }, status=400)

        # 标记是否有修改
        has_changes = False
        
        # 更新 params（如果提供了）
        if new_params is not None:
            if not isinstance(new_params, dict):
                return JsonResponse({
                    'success': False,
                    'message': 'params 必须是对象类型'
                }, status=400)
            # 打印调试信息
            print(f"[DEBUG] 更新子任务 {subtask_id} 的 params:")
            print(f"[DEBUG] 旧值: {subtask.params}")
            print(f"[DEBUG] 新值: {new_params}")
            # 直接替换 params
            subtask.params = new_params
            has_changes = True

        # 更新状态（如果提供了）
        if new_status:
            subtask.subtask_status = new_status
            has_changes = True

            # 如果状态是完成或失败，更新执行标记
            if new_status in {SubTask.STATUS_COMPLETED, SubTask.STATUS_FAILED}:
                if not subtask.is_executed:
                    subtask.is_executed = True
                    has_changes = True
                if not subtask.executed_at:
                    subtask.executed_at = timezone.now()
                    has_changes = True

        # 保存修改
        if has_changes:
            subtask.save()
            subtask.refresh_from_db()
            print(f"[DEBUG] 保存后 params: {subtask.params}")
        else:
            return JsonResponse({
                'success': False,
                'message': '没有提供任何要修改的数据（params 或 status）'
            }, status=400)

        return JsonResponse({
            'success': True,
            'data': {
                'subtask_id': subtask.id,
                'task_id': subtask.task_id,
                'type': subtask.subtask_type,
                'params': subtask.params,
                'status': subtask.subtask_status
            }
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'更新子任务详情失败: {str(e)}'
        }, status=500)


@login_required
@require_http_methods(["GET"])
def get_tasks_list_api(request):
    """
    获取任务列表（支持分页和筛选）
    GET /api/tasks/list/
    """
    try:
        page = int(request.GET.get('page', 1))
        page_size = int(request.GET.get('page_size', 20))
        
        # 筛选参数
        status = request.GET.get('status')
        creator = request.GET.get('creator')
        date_range = request.GET.get('date_range', 'all')
        start_date = request.GET.get('start_date')
        end_date = request.GET.get('end_date')
        search = request.GET.get('search', '').strip()

        # 基础查询：只能看到自己创建的，或自己负责的，或者有权限看到的
        current_user = request.user
        permissions = parse_permissions(getattr(current_user, 'permission', ''))
        
        queryset = Task.objects.exclude(task_type=TaskType.PRODUCT_REQUIREMENT).select_related(
            'created_by', 'owner'
        ).prefetch_related('subtasks', 'subtasks__amazon_upload_files')

        if 'ops_all' not in permissions:
            if 'ops_group' in permissions and hasattr(current_user, 'operational_account'):
                group_name = current_user.operational_account.ops_group
                # 组长可以看到组内成员创建或负责的任务
                if group_name:
                    queryset = queryset.filter(
                        Q(created_by=current_user) | 
                        Q(owner=current_user) |
                        Q(created_by__operational_account__ops_group=group_name) |
                        Q(owner__operational_account__ops_group=group_name)
                    )
                else:
                    queryset = queryset.filter(Q(created_by=current_user) | Q(owner=current_user))
            else:
                # 普通用户只能看到相关任务
                queryset = queryset.filter(Q(created_by=current_user) | Q(owner=current_user))

        # 应用筛选
        if status:
            status_list = status.split(',')
            queryset = queryset.filter(status__in=status_list)

        if creator:
            creator_list = creator.split(',')
            queryset = queryset.filter(created_by_id__in=creator_list)

        if date_range != 'all':
            now = timezone.now()
            if date_range == 'today':
                queryset = queryset.filter(created_at__date=now.date())
            elif date_range == 'week':
                start_week = now - timezone.timedelta(days=now.weekday())
                queryset = queryset.filter(created_at__gte=start_week.date())
            elif date_range == 'month':
                queryset = queryset.filter(created_at__month=now.month, created_at__year=now.year)
            elif date_range == 'custom' and start_date and end_date:
                queryset = queryset.filter(created_at__range=[start_date, end_date + ' 23:59:59'])

        # 搜索过滤（支持任务标题和任务单号）
        if search:
            queryset = queryset.filter(
                Q(title__icontains=search) | Q(task_no__icontains=search)
            )

        # 排序
        queryset = queryset.order_by('-created_at')

        # 分页
        from django.core.paginator import Paginator
        paginator = Paginator(queryset, page_size)
        page_obj = paginator.get_page(page)

        tasks_data = []
        for task in page_obj:
            subtasks_data = []
            for st in task.subtasks.all():
                # 所有子任务类型都直接使用数据库状态
                subtask_status = st.subtask_status
                subtasks_data.append({
                    'id': st.id,
                    'type': st.subtask_type,
                    'type_display': st.get_subtask_type_display(),
                    'status': subtask_status,
                    'status_display': dict(SubTask.STATUS_CHOICES).get(subtask_status, subtask_status)
                })

            tasks_data.append({
                'id': task.id,
                'task_no': task.task_no,
                'title': task.title,
                'status': task.status,
                'created_at': task.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                'created_by_name': task.created_by.first_name or task.created_by.username,
                'owner_name': task.owner.first_name or task.owner.username,
                'creator_name': task.created_by.first_name or task.created_by.username, # Frontend expects creator_name
                'subtasks': subtasks_data
            })

        return JsonResponse({
            'success': True,
            'data': {
                'tasks': tasks_data,
                'pagination': {
                    'page': page,
                    'page_size': page_size,
                    'total': paginator.count,
                    'total_pages': paginator.num_pages
                }
            }
        })
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)


@login_required
@require_http_methods(["DELETE"])
def delete_task_api(request, task_id):
    """
    删除任务
    DELETE /api/tasks/<task_id>/delete/
    """
    try:
        # 只能删除自己创建的，或者管理员可以删除
        permissions = parse_permissions(getattr(request.user, 'permission', ''))
        
        if 'ops_all' in permissions:
            task = Task.objects.get(id=task_id)
        else:
            task = Task.objects.get(id=task_id, created_by=request.user)
            
        task.delete()

        return JsonResponse({'success': True, 'message': '任务已删除'})

    except Task.DoesNotExist:
        return JsonResponse({
            'success': False,
            'message': '任务不存在或无权删除'
        }, status=404)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'删除任务失败: {str(e)}'
        }, status=500)


@login_required
@require_http_methods(["GET"])
def get_task_stats_api(request):
    """
    获取任务统计数据
    GET /api/tasks/stats/
    """
    try:
        current_user = request.user
        permissions = parse_permissions(getattr(current_user, 'permission', ''))
        
        queryset = Task.objects.exclude(task_type=TaskType.PRODUCT_REQUIREMENT)

        # 权限过滤
        if 'ops_all' not in permissions:
            if 'ops_group' in permissions and hasattr(current_user, 'operational_account'):
                group_name = current_user.operational_account.ops_group
                if group_name:
                    queryset = queryset.filter(
                        Q(created_by=current_user) | 
                        Q(owner=current_user) |
                        Q(created_by__operational_account__ops_group=group_name) |
                        Q(owner__operational_account__ops_group=group_name)
                    )
                else:
                    queryset = queryset.filter(Q(created_by=current_user) | Q(owner=current_user))
            else:
                queryset = queryset.filter(Q(created_by=current_user) | Q(owner=current_user))
        
        stats = {
            'total': queryset.count(),
            'draft': queryset.filter(status='draft').count(),
            'pending': queryset.filter(status='pending').count(),
            'in_progress': queryset.filter(status='in_progress').count()
        }
        
        return JsonResponse({'success': True, 'data': stats})
        
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)


@login_required
@require_http_methods(["GET"])
def get_task_creators_api(request):
    """
    获取任务创建人列表（用于筛选）
    GET /api/tasks/creators/
    """
    try:
        # 获取所有创建过任务的用户
        # 简单起见，这里返回所有有权限的用户，或者复用 available-owners 的逻辑
        # 为了更准确，我们可以查询 Task 表中 distinct 的 created_by
        # 但考虑到性能和权限，直接返回所有可能的运营人员可能更好
        
        # 复用 get_available_owners_api 的逻辑，因为通常创建人就是所有者池子里的
        return get_available_owners_api(request)
        
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)


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
                    'raw_name': shop.shop_name,
                    'shop_status': shop.shop_status or '',  # 店铺状态
                    'ops_name': shop.ops.first_name if shop.ops else '无运营'  # 运营人员
                })
            else:  # temu
                shops_data.append({
                    'id': shop.id,
                    'raw_name': shop.shop_name
                })

        # 排序：正常状态的排在前面，然后按店铺名排序
        def sort_key(x):
            status = x.get('shop_status', '')
            is_normal = 0 if status == 'status-active' else 1
            return (is_normal, x['raw_name'])
        
        shops_data.sort(key=sort_key)

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
def generate_copy_task_no_api(request):
    """
    生成复制任务单号（A方案：在被复制单号后直接追加 -N）
    GET /api/tasks/generate-copy-no/?base_no=XXX
    """
    try:
        base_no = request.GET.get('base_no', '').strip()
        if not base_no:
            return JsonResponse({'success': False, 'message': '缺少 base_no 参数'}, status=400)

        prefix = base_no + '-'
        existing_nos = Task.objects.filter(task_no__startswith=prefix).values_list('task_no', flat=True)

        max_suffix = 0
        for no in existing_nos:
            suffix_str = no[len(prefix):]
            if suffix_str.isdigit():
                max_suffix = max(max_suffix, int(suffix_str))

        new_task_no = f"{prefix}{max_suffix + 1}"
        return JsonResponse({'success': True, 'data': {'task_no': new_task_no}})
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'生成复制任务单号失败: {str(e)}'
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
        # if not title:
        #    return JsonResponse({'success': False, 'message': '任务标题不能为空'})

        # 确定所有者（可为他人创建）
        try:
            owner_id = int(data.get('owner_id', current_user.id))
        except (ValueError, TypeError):
            owner_id = current_user.id
        
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

        # 生成任务单号（优先使用前端传入的复制单号，若已存在则重新生成）
        task_no = data.get('task_no', '').strip()
        if task_no and not Task.objects.filter(task_no=task_no).exists():
            pass  # 使用前端传入的单号
        else:
            task_no = generate_task_no(current_user)

        # 获取任务类型
        task_type = data.get('task_type', TaskType.STANDARD)
        is_draft = data.get('is_draft', False)

        # 特殊处理产品需求：每个子任务创建一个独立的 ProductRequirement (不创建 Task)
        if task_type == 'product_requirement' and not is_draft:
            created_ids = []

            # 支持多上架平台：展开子任务
            expanded_subtasks = []
            for st in subtasks_data:
                params = st.get('params', {})
                lps = params.get('listing_platform', 'amazon')
                if isinstance(lps, str):
                    if ',' in lps:
                        lps = [x.strip() for x in lps.split(',')]
                    else:
                        lps = [lps]
                
                # Ensure lps is a list
                if not isinstance(lps, list):
                    lps = [str(lps)]

                for lp in lps:
                    if not lp: continue # Skip empty
                    new_st = st.copy()
                    new_st['params'] = params.copy()
                    new_st['params']['listing_platform'] = lp
                    expanded_subtasks.append(new_st)
            
            skipped_count = 0
            for idx, subtask_data in enumerate(expanded_subtasks):
                # 生成唯一的任务单号 (加后缀以防冲突)
                # 为了确保唯一性，如果循环处理过快，generate_task_no 可能生成相同的时间戳
                import time
                time.sleep(1.1) 
                task_no = generate_task_no(current_user)

                # 构造子任务标题 (产品需求不再使用标题，但为了兼容性可以设为产品名或空)
                sub_title = '' # title
                if len(expanded_subtasks) > 1:
                     pass # sub_title = f"{title} - {idx + 1}"

                params = subtask_data.get('params', {})
                subtask_type = subtask_data.get('type')
                product_url = params.get('url')
                platform = params.get('platform', 'yizhiguan')
                listing_platform = params.get('listing_platform', 'amazon')
                
                # 提取 Product ID
                product_id = None
                if product_url:
                    if 'yizhiguan' in platform or 'ykartwood' in product_url:
                        match = re.search(r'detail/(\d+)', product_url)
                        if match:
                            product_id = match.group(1)
                    elif 's2b' in platform or 's2bdiy' in product_url:
                        match = re.search(r'productDesignDetail/(\d+)', product_url)
                        if match:
                            product_id = match.group(1)
                    elif 'amazon' in platform or 'amazon' in product_url:
                         # Amazon ID通常是ASIN，如 /dp/B08...
                         match = re.search(r'/dp/([A-Z0-9]{10})', product_url)
                         if not match:
                             match = re.search(r'/gp/product/([A-Z0-9]{10})', product_url)
                         if match:
                             product_id = match.group(1)
                    elif 'temu' in platform or 'temu' in product_url:
                        # Temu ID通常在URL末尾或 goods_id 参数
                         match = re.search(r'goods_id=(\d+)', product_url)
                         if not match:
                            # 尝试匹配URL路径中的数字
                            match = re.search(r'-g-(\d+)\.html', product_url)
                         if match:
                             product_id = match.group(1)

                # 查重逻辑
                if product_id and ProductRequirement.objects.filter(
                    product_id=product_id, 
                    platform=platform, 
                    listing_platform=listing_platform
                ).exists():
                     skipped_count += 1
                     continue
                
                # 抓取数据逻辑 (如果是艺之冠且提取到了ID)
                crawler_data = {}
                initial_status = ProductRequirement.STATUS_CREATED
                
                if 'yizhiguan' in platform and product_id:
                    try:
                        ykat_data = get_ykartwood_product(product_id, listing_platform, platform)
                        if ykat_data:
                            crawler_data = ykat_data
                            initial_status = ProductRequirement.STATUS_PENDING_DESIGN # 状态改为待设计
                    except Exception as e:
                        print(f"Crawler failed: {e}")
                
                craft_map = {
                    'print_external': '印花',
                    'embroidery': '刺绣'
                }
                
                req_data = {
                    'created_by': current_user,
                    'owner': owner, # 新增 owner 字段
                    'platform': platform,
                    'listing_platform': listing_platform,
                    'product_url': product_url,
                    'product_id': product_id,
                    'craft': crawler_data.get('craft') or craft_map.get(subtask_type, ''),
                    'status': initial_status,
                    # 'title': sub_title, # Removed field
                    'requirement_no': task_no,
                    
                    # 爬虫抓取的字段
                    'product_name': crawler_data.get('product_name', ''),
                    'product_abbr': crawler_data.get('product_abbr', ''),
                    'english_name': crawler_data.get('english_name', ''),
                    'material': crawler_data.get('material', ''),
                    'unit': crawler_data.get('unit', ''),
                    'customs_cn_name': crawler_data.get('customs_cn_name', ''),
                    'customs_en_name': crawler_data.get('customs_en_name', ''),
                    'declared_weight': crawler_data.get('declared_weight'),
                    'declared_price': crawler_data.get('declared_price'),
                    'material_cn': crawler_data.get('material_cn', ''),
                    'material_desc': crawler_data.get('material_desc', ''),
                    'accessory_struct': crawler_data.get('accessory_struct', ''),
                    'product_performance': crawler_data.get('product_performance', ''),
                    'applicable_scenario': crawler_data.get('applicable_scenario', ''),
                    'washing_instructions': crawler_data.get('washing_instructions', ''),
                    'special_note': crawler_data.get('special_note', ''),
                    'reminder': crawler_data.get('reminder', ''),
                    'design_desc': crawler_data.get('design_desc', ''),
                    'design_area': crawler_data.get('design_area', ''),
                    
                    # 新增字段
                    'color_name': crawler_data.get('color_name', []),
                    'size_list': crawler_data.get('size_list', []),
                    'img_urls_list': crawler_data.get('img_urls_list', []),

                    # 新增报关字段
                    'category': crawler_data.get('category', ''),
                    'special_cargo_type': crawler_data.get('special_cargo_type', ''),
                    'product_label': crawler_data.get('product_label', ''),
                    'packaging_specification': crawler_data.get('packaging_specification', []),
                    'product_size': crawler_data.get('product_size', []),
                }
                
                # 清理 None 值
                req_data = {k: v for k, v in req_data.items() if v is not None}
                
                req = ProductRequirement.objects.create(**req_data)
                
                created_ids.append(req.id)
                
                # 发送 webhook (针对每个任务发送)
                try:
                    webhook_data = {
                        '事件类型': '产品需求创建',
                        '任务ID': req.id,  # 使用 Requirement ID
                        '任务单号': req.requirement_no,
                        '创建人ID': current_user.id,
                        '创建人': f"{current_user.first_name} {current_user.last_name}".strip() or current_user.username,
                        '所有者': f"{owner.first_name} {owner.last_name}".strip() or owner.username,
                        '创建时间': timezone.now().strftime('%Y-%m-%d %H:%M:%S'),
                        '状态': '待处理',
                        '产品链接': params.get('url'),
                        '参数': params
                    }

                    def send_webhook_task(payload):
                        url = "https://api.yingdao.com/api/tool/ipaas/webhook/callback/929623248793497600"
                        try:
                            requests.post(url, json=payload, timeout=10)
                        except Exception as e:
                            print(f"Webhook send failed: {e}")

                    req.webhook_payload = webhook_data
                    req.save(update_fields=['webhook_payload'])
                    transaction.on_commit(lambda data=webhook_data: threading.Thread(target=send_webhook_task, args=(data,)).start())
                except Exception:
                    pass

            return JsonResponse({
                'success': True,
                'message': f'创建成功 {len(created_ids)} 条' + (f'，跳过重复 {skipped_count} 条' if skipped_count > 0 else ''),
                'data': {
                    'task_ids': created_ids,
                    'redirect_url': '/task/product/list/'
                }
            })

        # 创建主任务
        task = Task.objects.create(
            title=title,
            task_no=task_no,
            task_type=task_type,
            status=TaskStatus.DRAFT if is_draft else TaskStatus.PENDING,
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

                subtask = SubTask.objects.create(
                    task=task,
                    subtask_type=subtask_type,
                    subtask_status=SubTask.get_initial_status(is_draft=is_draft),
                    order=idx,
                    params=params
                )
                if subtask_type == 'amazon_upload' and not is_draft:
                    process_amazon_upload_files(subtask_data.get('params', {}), task_no, task_instance=task,
                                                subtask_instance=subtask)

            except Exception as e:
                # 回滚事务
                raise ValueError(f"子任务 #{idx + 1} 验证失败: {str(e)}")

        # 发送 Webhook 通知 (仅正式任务)
        if not is_draft:
            try:
                # 构造完整的子任务数据（全中文格式）
                subtasks_for_webhook = []
                for st in task.subtasks.all().order_by('order'):
                    params = st.params or {}
                    
                    # 根据子任务类型转换参数为中文
                    if st.subtask_type == 'divi_custom':
                        # 迪唯批量定制 - 转换定制行数据
                        custom_rows_cn = []
                        for row in params.get('custom_rows', []):
                            custom_rows_cn.append({
                                '产品ID': row.get('product_id', ''),
                                '模式': '适应' if row.get('mode') == 'adapt' else '填充',
                                '使用背景图': row.get('use_background', False),
                                '背景颜色': row.get('background_color', '')
                            })
                        
                        subtask_params = {
                            '迪唯账号': params.get('diwei_account', ''),
                            '图库路径': params.get('image_classify', []) if isinstance(params.get('image_classify'), list) else [],
                            '本地路径': params.get('nas_path', ''),
                            '定制行列表': custom_rows_cn
                        }
                    elif st.subtask_type == 'divi_export':
                        # 迪唯汇出上架-Amazon切表版 - 转换汇出行数据
                        export_rows_cn = []
                        for row in params.get('export_rows', []):
                            export_rows_cn.append({
                                '产品ID': row.get('product_id', ''),
                                '产品名称': row.get('product_name', ''),
                                '尺码ID列表': row.get('sizes', []),
                                '尺码名称列表': row.get('size_names', []),
                                '颜色ID列表': row.get('colors', []),
                                '颜色中文列表': row.get('color_names', []),
                                '颜色英文列表': row.get('color_en_names', []),
                                '店铺列表': row.get('shops', [])
                            })
                        
                        subtask_params = {
                            '迪唯账号': params.get('diwei_account', ''),
                            '汇出行列表': export_rows_cn
                        }
                    elif st.subtask_type == 'divi_export_pro':
                        # 迪唯汇出上架-Pro - 转换汇出行数据
                        # 获取子任务级别的平台
                        platform_display = 'Amazon' if params.get('platform') == 'amazon' else 'Temu'
                        
                        export_rows_cn = []
                        for row in params.get('export_rows', []):
                            # 获取尺码名称列表（优先使用size_names，如果没有则使用sizes作为后备）
                            size_names = row.get('size_names', [])
                            if not size_names and row.get('sizes'):
                                size_names = row.get('sizes', [])
                            
                            # 获取颜色中文和英文名称列表
                            color_names = row.get('color_names', [])
                            color_en_names = row.get('color_en_names', [])
                            if not color_names and row.get('colors'):
                                color_names = row.get('colors', [])
                            
                            # 处理上架店铺列表 - 确保始终是列表
                            publish_shops = row.get('publish_shops', [])
                            if isinstance(publish_shops, str):
                                publish_shops = [publish_shops] if publish_shops else []
                            
                            # 处理汇出店铺
                            export_shop = row.get('export_shop', '')
                            
                            # 获取汇出模板信息
                            export_template_id = row.get('export_template_id', '')
                            export_template_name = row.get('export_template_name', '')
                            
                            export_rows_cn.append({
                                '产品ID': row.get('product_id', ''),
                                '尺码名称列表': size_names,
                                '颜色中文列表': color_names,
                                '颜色英文列表': color_en_names,
                                '汇出模板ID': export_template_id,
                                '汇出模板名称': export_template_name,
                                '是否已汇出': bool(row.get('is_exported', False)),
                                '最大汇出数量': row.get('max_export_quantity', 100),
                                '汇出店铺': export_shop,
                                '上架店铺列表': publish_shops,
                                '设计时间自定义': bool(row.get('design_date_filter', False)),
                                '设计时间开始日期': row.get('design_start_date', '') if row.get('design_date_filter') else '',
                                '设计时间结束日期': row.get('design_end_date', '') if row.get('design_date_filter') else ''
                            })
                        
                        subtask_params = {
                            '迪唯账号': params.get('diwei_account', ''),
                            '平台': platform_display,
                            '汇出行列表': export_rows_cn
                        }
                    elif st.subtask_type == 'divi_gallery_upload':
                        subtask_params = {
                            '迪唯账号': params.get('diwei_account', ''),
                            '图库命名': params.get('gallery_name', ''),
                            '本地路径': params.get('local_gallery_path', '')
                        }
                    elif st.subtask_type == 'amazon_exempt':
                        # Amazon资格豁免 - 转换豁免产品数据
                        exempt_rows_cn = []
                        for row in params.get('exempt_rows', []):
                            # 根据中文产品名称查找对应的英文名称
                            product_cn = row.get('product_name', '')
                            product_en = ''
                            product_type = row.get('product_type', '')
                            
                            # 产品映射表（与前端一致）
                            product_map = {
                                '旗': 'Flag',
                                '帽子': 'Hat',
                                '杯子': 'Drinking cup',
                                '袜子': 'Socks',
                                '背包': 'Backpack',
                                '毛毯': 'Blanket',
                                '地垫': 'Rug',
                                '挂毯': 'Wallart',
                                '铁皮挂画': 'Decorative signage',
                                '咖啡垫': 'placemat',
                                '热转印白墨画贴纸': 'iron on transfer design',
                                '胸章': 'apparel pin',
                                'T恤': 'shirt',
                                '围裙': 'apron',
                                '桌布': 'tablecloth',
                                '横幅': 'Banner',
                                '化妆包': 'Cosmetic Bag'
                            }
                            
                            if product_cn in product_map:
                                product_en = product_map[product_cn]
                            
                            exempt_rows_cn.append({
                                '产品名称中文': product_cn,
                                '产品名称英文': product_en,
                                '产品类型': product_type
                            })
                        
                        subtask_params = {
                            'Amazon店铺': params.get('amazon_shop', ''),
                            '豁免产品列表': exempt_rows_cn
                        }
                    elif st.subtask_type == 'divi_multi_side_custom':
                        # 定制坐标转列表
                        custom_coords = params.get('custom_coords', '')
                        custom_coords_list = []
                        if custom_coords:
                            try:
                                custom_coords_list = [int(x) for x in str(custom_coords).strip().split() if x.isdigit()]
                            except (ValueError, AttributeError):
                                custom_coords_list = []
                        
                        # 获取NAS路径和图库分类
                        nas_path = params.get('nas_path', '')
                        image_classify = params.get('image_classify', [])
                        
                        subtask_params = {
                            '产品ID列表': params.get('product_ids', []),
                            '模式': '适应' if params.get('mode') == 'adapt' else '填充',
                            '迪唯账号': params.get('diwei_account', ''),
                            '迪唯登录账号': params.get('diwei_login_account', ''),
                            'NAS路径': nas_path,
                            '图库分类': image_classify if isinstance(image_classify, list) else [],
                            '工艺类型': {
                                'print': '印花',
                                'emboss': '刺绣',
                                'laser': '镭射'
                            }.get(params.get('craft_type'), params.get('craft_type', '')),
                            '定制方式': '多面定制' if params.get('custom_method') == 'multi' else 'divi批量定制',
                            '添加黑边': params.get('add_black_border', False),
                            '识别主题': params.get('recognize_theme', False),
                            '添加定制坐标': params.get('add_custom_coords', False),
                            '定制坐标': custom_coords_list,
                            '添加背景色': params.get('add_background_color', False),
                            '背景颜色': params.get('background_color', ''),
                            '是否平铺': params.get('is_tiled', False),
                            '平铺类型': {
                                'basic': '基础平铺',
                                'spacing': '间距平铺',
                                'horizontal_stagger': '横向交错平铺',
                                'vertical_stagger': '纵向交错平铺',
                                'mirror': '镜像平铺',
                                'random': '随机平铺'
                            }.get(params.get('tile_type'), params.get('tile_type', '')),
                            '平铺间距': params.get('tile_spacing', 0)
                        }
                    elif st.subtask_type == 'amazon_upload':
                        # Amazon上传 - 从数据库获取实际目标路径
                        from task.models import AmazonUploadFile
                        
                        upload_files = AmazonUploadFile.objects.filter(subtask=st).order_by('created_at')
                        files_cn = []
                        
                        for uf in upload_files:
                            files_cn.append({
                                '文件名': uf.excel_filename,
                                '店铺名': uf.amazon_shop.shop_name if uf.amazon_shop else uf.shop_name_suffix,
                                '店铺后缀': uf.shop_name_suffix,
                                '目标路径': uf.target_path,  # 实际的目标路径
                                '状态': uf.get_status_display(),
                                '成功SKU数': uf.success_sku or 0,
                                '总SKU数': uf.total_sku or 0
                            })
                        
                        subtask_params = {
                            '文件数量': len(files_cn),
                            '文件列表': files_cn,
                            '成功文件数': sum(1 for f in files_cn if '成功' in f['状态'] or '完成' in f['状态']),
                            '失败文件数': sum(1 for f in files_cn if '失败' in f['状态'])
                        }
                    else:
                        # 其他类型保持原参数
                        subtask_params = params
                    
                    # 类型映射为中文显示名
                    type_display_map = {
                        'divi_custom': '迪唯批量定制',
                        'divi_export': '迪唯汇出上架-Amazon切表版',
                        'divi_export_pro': '迪唯汇出上架-Pro',
                        'amazon_exempt': 'Amazon UPC豁免',
                        'divi_gallery_upload': 'DIVI图库上传',
                        'divi_multi_side_custom': '迪唯多面定制',
                        'custom_upload': 'Temu定制上架',
                        'temu_export': 'Temu导单',
                        'amazon_upload': 'Amazon上传商品',
                        'print_external': '印花外采'
                    }
                    
                    subtasks_for_webhook.append({
                        '子任务ID': st.id,
                        '子任务类型': type_display_map.get(st.subtask_type, st.subtask_type),
                        '子任务参数': subtask_params
                    })

                # 构造统一的通知数据（全中文格式）
                webhook_data = {
                    '事件类型': '任务创建',
                    '任务ID': task.id,
                    '任务单号': task_no,
                    '任务标题': title,
                    '任务状态': '待处理',
                    '创建人ID': current_user.id,
                    '创建人姓名': f"{current_user.first_name} {current_user.last_name}".strip() or current_user.username,
                    '所有者姓名': f"{owner.first_name} {owner.last_name}".strip() or owner.username,
                    '创建时间': timezone.now().strftime('%Y-%m-%d %H:%M:%S'),
                    '企业微信通知url': data.get('wx_url', ''),
                    '子任务列表': subtasks_for_webhook
                }

                def send_webhook_task(payload):
                    url = "https://api.yingdao.com/api/tool/ipaas/webhook/callback/929623248793497600"
                    try:
                        requests.post(url, json=payload, timeout=10)
                    except Exception as e:
                        print(f"Webhook send failed: {e}")

                task.webhook_payload = webhook_data
                task.save(update_fields=['webhook_payload'])
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
        task_type = data.get('task_type', TaskType.STANDARD)

        if task_id:
            # 更新现有草稿
            try:
                task = Task.objects.get(id=task_id, created_by=current_user)
                task.title = data.get('title', task.title)
                task.owner = owner
                task.task_type = task_type
                task.save()
            except Task.DoesNotExist:
                return JsonResponse({'success': False, 'message': '草稿不存在或无权修改'}, status=404)
        else:
            # 创建新草稿
            title = data.get('title', '未命名任务')
            task_no = data.get('task_no', '').strip()
            if task_no and not Task.objects.filter(task_no=task_no).exists():
                pass
            else:
                task_no = generate_task_no(current_user)

            task = Task.objects.create(
                title=title,
                task_no=task_no,
                task_type=task_type,
                status=TaskStatus.DRAFT,
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
                subtask_status=SubTask.get_initial_status(is_draft=True),
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
    GET /api/tasks/drafts/latest/?task_type=standard|product_requirement
    """
    try:
        task_type = request.GET.get('task_type', TaskType.STANDARD)

        draft = Task.objects.filter(
            created_by=request.user,
            status='draft',
            task_type=task_type
        ).order_by('-updated_at').first()

        if not draft:
            return JsonResponse({'success': True, 'data': None})

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
        permissions = parse_permissions(getattr(request.user, 'permission', ''))
        templates = TaskTemplate.objects.select_related('created_by')

        if 'ops_all' not in permissions:
            templates = templates.filter(created_by=request.user)

        templates = templates.order_by('-created_at')

        templates_data = [{
            'id': template.id,
            'name': template.name,
            'description': template.description,
            'creator_name': template.created_by.first_name or template.created_by.username,
            'created_at': template.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            'subtask_count': len(template.content) if isinstance(template.content, list) else 0,
            'can_delete': template.created_by_id == request.user.id
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
        permissions = parse_permissions(getattr(request.user, 'permission', ''))
        queryset = TaskTemplate.objects.all()

        if 'ops_all' not in permissions:
            queryset = queryset.filter(created_by=request.user)

        template = queryset.get(id=template_id)

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



# ========== DIVI 产品相关接口 ==========

@login_required
@require_http_methods(["GET"])
def get_divi_products_api(request):
    """
    获取所有 DIVI 产品列表（用于下拉框）
    GET /api/divi/products/
    """
    try:
        from divi.models import Product
        products = Product.objects.all().order_by('name').values('id', 'name')
        return JsonResponse({
            'success': True,
            'data': list(products)
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'获取产品列表失败: {str(e)}'
        }, status=500)


@login_required
@require_http_methods(["GET"])
def get_divi_product_detail_api(request, product_id):
    """
    获取单个 DIVI 产品的颜色和尺寸详情
    GET /api/divi/products/{product_id}/detail/
    """
    try:
        from divi.models import Product
        product = Product.objects.get(id=product_id)
        
        colors = list(product.colors.values(
            'color_classify_id', 
            'color_name', 
            'en_name'
        ))
        sizes = list(product.sizes.values(
            'product_size_id', 
            'product_size_name'
        ))
        
        return JsonResponse({
            'success': True,
            'data': {
                'product_id': product.id,
                'product_name': product.name,
                'colors': colors,
                'sizes': sizes
            }
        })
    except Product.DoesNotExist:
        return JsonResponse({
            'success': False,
            'message': '产品不存在'
        }, status=404)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'获取产品详情失败: {str(e)}'
        }, status=500)


@login_required
@require_http_methods(["GET"])
def get_diwei_accounts_api(request):
    """
    获取迪唯账号列表（用于下拉框）
    GET /api/tasks/diwei-accounts/
    返回: [{ value: 'divi_username', label: 'divi_username（diwei_account）' }]
    排序: 按 user_id 升序
    筛选: 当前公司 + diwei_account 非空 + 权限控制
    """
    try:
        from general.models import OperationalAccount
        
        # 获取当前用户的公司
        current_company = request.user.company
        if not current_company:
            return JsonResponse({
                'success': False,
                'message': '当前用户未分配公司'
            }, status=403)
        
        # 基础查询：当前公司的用户 + divi_username 非空 + diwei_account 非空
        queryset = OperationalAccount.objects.filter(
            user__company=current_company
        ).exclude(
            divi_username__isnull=True
        ).exclude(
            divi_username=''
        ).exclude(
            diwei_account__isnull=True
        ).exclude(
            diwei_account=''
        )
        
        # 权限过滤
        permissions = parse_permissions(getattr(request.user, 'permission', ''))
        if 'ops_all' not in permissions:
            if 'ops_group' in permissions and hasattr(request.user, 'operational_account'):
                # 组长：可以看到组内成员的（包括自己）
                group_name = request.user.operational_account.ops_group
                if group_name:
                    queryset = queryset.filter(
                        user__operational_account__ops_group=group_name
                    )
                else:
                    # 组长但未分组，只能看到自己的
                    queryset = queryset.filter(user=request.user)
            else:
                # 普通用户：只能看到自己的
                queryset = queryset.filter(user=request.user)
        
        accounts = queryset.order_by('user_id').values('divi_username', 'diwei_account')
        
        data = []
        for account in accounts:
            divi_username = account['divi_username']
            diwei_account = account['diwei_account']
            data.append({
                'value': divi_username,
                'label': f"{divi_username}（{diwei_account}）",
                'diwei_account': diwei_account
            })
        
        return JsonResponse({
            'success': True,
            'data': data
        })
    except Exception as e:
        import traceback
        print(f"获取迪唯账号列表错误: {str(e)}")
        traceback.print_exc()
        return JsonResponse({
            'success': False,
            'message': f'获取迪唯账号列表失败: {str(e)}'
        }, status=500)


@login_required
@require_http_methods(["GET"])
def get_divi_export_templates_api(request):
    """
    获取 DIVI 汇出模板列表（根据产品和店铺筛选）
    GET /api/divi/export-templates/?product_id=123&shop=汇出店铺名&divi_account=YMX-26
    
    参数:
        product_id: 产品ID（必填）
        shop: 汇出店铺名（必填）
        divi_account: 迪唯登录账号（如YMX-26，必填）
    
    返回: [{ template_id, template_name, value, label }]
      - template_name 已包含【系统】或【用户】后缀
    """
    try:
        from divi.models import DiviExportTemplate
        from django.db.models import Q
        
        product_id = request.GET.get('product_id')
        shop_name = request.GET.get('shop', '').strip()
        divi_account = request.GET.get('divi_account', '').strip()
        
        if not product_id:
            return JsonResponse({
                'success': False,
                'message': '缺少必要参数: product_id'
            }, status=400)
        
        # 获取当前用户公司
        company = request.user.company
        if not company:
            return JsonResponse({
                'success': True,
                'data': []
            })
        
        # 基础查询：当前公司的模板，且包含所选产品
        base_query = Q(
            company=company,
            products__id=product_id
        )
        
        # 系统模板：template_type=1，只验证产品ID，不验证店铺
        system_query = base_query & Q(template_type=1)
        
        # 用户模板：template_type=2，验证产品ID + 店铺 + 账号
        user_query = None
        if divi_account:
            user_query = base_query & Q(template_type=2, username=divi_account)
            # 用户模板需要根据店铺筛选
            if shop_name:
                user_query &= Q(shops__shop_name=shop_name)
        
        # 合并查询
        if user_query:
            queryset = DiviExportTemplate.objects.filter(system_query | user_query).distinct()
        else:
            queryset = DiviExportTemplate.objects.filter(system_query).distinct()
        
        # 组装数据
        templates = queryset.order_by('-synced_at').values('template_id', 'template_name', 'template_type')
        
        data = [_format_divi_export_template(tpl) for tpl in templates]
        
        return JsonResponse({
            'success': True,
            'data': data
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({
            'success': False,
            'message': f'获取汇出模板列表失败: {str(e)}'
        }, status=500)


def _format_divi_export_template(tpl):
    """辅助函数：格式化 DIVI 汇出模板数据"""
    original_name = tpl.get('template_name') or tpl.get('template_name__') or f"模板-{tpl.get('template_id')}"
    template_type = tpl.get('template_type')
    suffix = '【系统】' if template_type == 1 else '【用户】'
    display_name = original_name + suffix
    color = 'var(--warning-color)' if template_type == 1 else 'var(--success-color)'
    html_display_name = f"{original_name}<span style=\"color:{color};font-weight:500\">{suffix}</span>"
    return {
        'template_id': tpl.get('template_id'),
        'template_name': original_name,
        'template_name_display': display_name,
        'html_label': html_display_name,
        'value': tpl.get('template_id'),
        'label': display_name
    }


@login_required
@require_http_methods(["GET"])
def get_divi_export_templates_by_shop_api(request):
    """
    获取某店铺+迪唯账号下的所有可用模板（不限制产品）
    GET /api/divi/export-templates/by-shop/?shop=店铺名&divi_account=YMX-26
    """
    try:
        from divi.models import DiviExportTemplate
        from django.db.models import Q
        
        shop_name = request.GET.get('shop', '').strip()
        divi_account = request.GET.get('divi_account', '').strip()
        
        company = request.user.company
        if not company:
            return JsonResponse({'success': True, 'data': []})
        
        # 系统模板：当前公司下所有类型=1的模板
        system_query = Q(company=company, template_type=1)
        
        # 用户模板：当前公司 + 迪唯账号 + 店铺匹配
        user_query = None
        if divi_account:
            user_query = Q(company=company, template_type=2, username=divi_account)
            if shop_name:
                user_query &= Q(shops__shop_name=shop_name)
        
        if user_query:
            queryset = DiviExportTemplate.objects.filter(system_query | user_query).distinct()
        else:
            queryset = DiviExportTemplate.objects.filter(system_query).distinct()
        
        templates = queryset.order_by('-synced_at').values('template_id', 'template_name', 'template_type')
        data = [_format_divi_export_template(tpl) for tpl in templates]
        
        return JsonResponse({'success': True, 'data': data})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({'success': False, 'message': f'获取汇出模板失败: {str(e)}'}, status=500)


@login_required
@require_http_methods(["GET"])
def get_divi_image_classifies_api(request):
    """
    获取 DIVI 图库分类树形数据（根据迪唯账号筛选）
    GET /api/divi/image-classifies/?username=YMX-26
    
    参数:
        username: 迪唯账号用户名（如 YMX-26，必填）
    
    返回: 树形结构数据 [{ id, label, children: [...] }]
    """
    try:
        from divi.models import DiviImageClassify
        
        username = request.GET.get('username', '').strip()
        
        if not username:
            return JsonResponse({
                'success': False,
                'message': '缺少必要参数: username'
            }, status=400)
        
        # 查询该账号下的所有分类
        classifies = DiviImageClassify.objects.filter(
            username=username
        ).order_by('level', 'sort_order', 'id')
        
        # 构建树形结构
        node_map = {}
        root_nodes = []
        
        for cls in classifies:
            node = {
                'id': cls.id,
                'label': cls.label,
                'level': cls.level,
                'path': cls.path or '',
                'children': []
            }
            node_map[cls.id] = node
            
            if cls.parent_id and cls.parent_id in node_map:
                node_map[cls.parent_id]['children'].append(node)
            else:
                root_nodes.append(node)
        
        return JsonResponse({
            'success': True,
            'data': root_nodes
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({
            'success': False,
            'message': f'获取图库分类失败: {str(e)}'
        }, status=500)


def _send_webhook_payload(payload):
    """通用 webhook 发送辅助函数"""
    url = "https://api.yingdao.com/api/tool/ipaas/webhook/callback/929623248793497600"
    try:
        requests.post(url, json=payload, timeout=10)
        return True
    except Exception as e:
        print(f"Webhook send failed: {e}")
        return False


@login_required
@require_http_methods(["POST"])
def resend_task_webhook_api(request, task_id):
    """
    重新发送任务 webhook（仅 code=555 管理员可用）
    POST /api/tasks/<int:task_id>/resend-webhook/
    """
    user_perms = get_user_permission_codes(request.user)
    if 555 not in user_perms:
        return JsonResponse({'success': False, 'message': '无权限执行此操作'}, status=403)

    try:
        task = Task.objects.get(id=task_id)
    except Task.DoesNotExist:
        return JsonResponse({'success': False, 'message': '任务不存在'}, status=404)

    payload = task.webhook_payload
    if not payload:
        return JsonResponse({'success': False, 'message': '该任务没有保存的 webhook 数据，无法重新发送'})

    # 异步发送，避免阻塞
    threading.Thread(target=_send_webhook_payload, args=(payload,)).start()

    return JsonResponse({'success': True, 'message': 'Webhook 正在重新发送'})


@login_required
@require_http_methods(["GET"])
def get_user_export_shop_products_api(request):
    """
    获取当前用户的汇出店铺-产品-模板偏好设置（组合式）
    GET /api/user/export-shop-products/
    返回: [{ shop_id, shop_name, diwei_account, product_id, template_ids: [] }]
    """
    try:
        from collections import defaultdict
        from task.models import UserExportShopProductPreference
        
        prefs = UserExportShopProductPreference.objects.filter(
            user=request.user
        ).select_related('shop', 'product', 'template').order_by('diwei_account', 'shop__shop_name', 'product__name')
        
        # 按 (diwei_account, shop_id, product_id) 聚合 template_ids
        group_map = defaultdict(list)
        shop_meta = {}
        for p in prefs:
            shop_meta[p.shop_id] = {
                'shop_name': p.shop_name or (p.shop.shop_name if p.shop else f"店铺-{p.shop_id}")
            }
            if p.product_id:
                group_map[(p.diwei_account or '', p.shop_id, p.product_id)].append(p.template_id)
        
        data = []
        for (diwei_account, shop_id, product_id) in sorted(group_map.keys()):
            template_ids = [tid for tid in group_map[(diwei_account, shop_id, product_id)] if tid is not None]
            data.append({
                'shop_id': shop_id,
                'shop_name': shop_meta.get(shop_id, {}).get('shop_name', f"店铺-{shop_id}"),
                'diwei_account': diwei_account,
                'product_id': product_id,
                'template_ids': template_ids
            })
        
        return JsonResponse({'success': True, 'data': data})
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'获取偏好设置失败: {str(e)}'}, status=500)


@login_required
@require_http_methods(["POST"])
def save_user_export_shop_products_api(request):
    """
    保存/覆盖当前用户的汇出店铺-产品-模板偏好设置（组合式）
    POST /api/user/export-shop-products/save/
    请求体: { preferences: [{ shop_id, shop_name, diwei_account, product_id, template_ids: [] }] }
    """
    try:
        import json
        from django.db import transaction
        from general.models import AmazonShop
        from task.models import UserExportShopProductPreference
        
        body = json.loads(request.body)
        preferences = body.get('preferences', [])
        
        # 预查店铺名
        shop_ids = [item.get('shop_id') for item in preferences if item.get('shop_id')]
        shop_name_map = {}
        if shop_ids:
            for s in AmazonShop.objects.filter(id__in=shop_ids).values('id', 'shop_name'):
                shop_name_map[s['id']] = s['shop_name'] or f"店铺-{s['id']}"
        
        with transaction.atomic():
            UserExportShopProductPreference.objects.filter(user=request.user).delete()
            
            objs = []
            for item in preferences:
                shop_id = item.get('shop_id')
                product_id = item.get('product_id')
                template_ids = item.get('template_ids', [])
                diwei_account = item.get('diwei_account', '')
                shop_name = item.get('shop_name') or shop_name_map.get(shop_id, f"店铺-{shop_id}")
                if not shop_id or not product_id:
                    continue
                if template_ids and len(template_ids) > 0:
                    for tid in template_ids:
                        objs.append(UserExportShopProductPreference(
                            user=request.user,
                            shop_id=shop_id,
                            shop_name=shop_name,
                            product_id=product_id,
                            template_id=tid,
                            diwei_account=diwei_account
                        ))
                else:
                    # 占位：保存一条 template_id=None 的记录，使产品置顶仍生效
                    objs.append(UserExportShopProductPreference(
                        user=request.user,
                        shop_id=shop_id,
                        shop_name=shop_name,
                        product_id=product_id,
                        template_id=None,
                        diwei_account=diwei_account
                    ))
            
            if objs:
                UserExportShopProductPreference.objects.bulk_create(objs)
        
        return JsonResponse({'success': True, 'message': '保存成功'})
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'保存偏好设置失败: {str(e)}'}, status=500)
