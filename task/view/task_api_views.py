# Task/view/task_api_views.py

import json
import requests
import threading
import re
from datetime import datetime
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from django.utils import timezone
from django.db.models import Q
from django.db import transaction

from general.models import User, AmazonShop, TemuShop
from task.models import Task, SubTask, TaskTemplate, ProductRequirement
from task.utils import (
    generate_task_no,
    get_visible_shops,
    parse_permissions,
    validate_subtask_params
)
from api.wc.crawler_wc import get_ykartwood_product
from task.view.task_upload_views import process_amazon_upload_files


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

        # 基础查询：只能看到自己创建的，或自己负责的，或者有权限看到的
        current_user = request.user
        permissions = parse_permissions(getattr(current_user, 'permission', ''))
        
        queryset = Task.objects.exclude(task_type=Task.TYPE_PRODUCT).select_related('created_by', 'owner').prefetch_related('subtasks')

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

        # 排序
        queryset = queryset.order_by('-created_at')

        # 分页
        from django.core.paginator import Paginator
        paginator = Paginator(queryset, page_size)
        page_obj = paginator.get_page(page)

        tasks_data = []
        for task in page_obj:
            tasks_data.append({
                'id': task.id,
                'task_no': task.task_no,
                'title': task.title,
                'status': task.status,
                'created_at': task.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                'created_by_name': task.created_by.first_name or task.created_by.username,
                'owner_name': task.owner.first_name or task.owner.username,
                'creator_name': task.created_by.first_name or task.created_by.username, # Frontend expects creator_name
                'subtasks': [{
                    'id': st.id,
                    'type': st.subtask_type
                } for st in task.subtasks.all()]
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
        
        queryset = Task.objects.exclude(task_type=Task.TYPE_PRODUCT)

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
        # if not title:
        #    return JsonResponse({'success': False, 'message': '任务标题不能为空'})

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

        # 获取任务类型
        task_type = data.get('task_type', Task.TYPE_STANDARD)
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
                    webhook_data = data.copy()
                    webhook_data.update({
                        'task_id': req.id, # 使用 Requirement ID
                        'task_no': req.requirement_no,
                        # 'title': sub_title,
                        'created_by_id': current_user.id,
                        'created_by_name': f"{current_user.first_name} {current_user.last_name}".strip() or current_user.username,
                        'owner_name': f"{owner.first_name} {owner.last_name}".strip() or owner.username,
                        'created_at': timezone.now().strftime('%Y-%m-%d %H:%M:%S'),
                        'status': 'pending',
                        'product_url': params.get('url')
                    })

                    def send_webhook_task(payload):
                        url = "https://api.yingdao.com/api/tool/ipaas/webhook/callback/873825669915136000"
                        try:
                            requests.post(url, json=payload, timeout=10)
                        except Exception as e:
                            print(f"Webhook send failed: {e}")

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
                if subtask_type == 'amazon_upload' and not is_draft:
                    process_amazon_upload_files(subtask_data.get('params', {}), task_no)

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
        task_type = data.get('task_type', Task.TYPE_STANDARD)

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
            task_no = generate_task_no(current_user)

            task = Task.objects.create(
                title=title,
                task_no=task_no,
                task_type=task_type,
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
    GET /api/tasks/drafts/latest/?task_type=standard|product_requirement
    """
    try:
        task_type = request.GET.get('task_type', Task.TYPE_STANDARD)

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
