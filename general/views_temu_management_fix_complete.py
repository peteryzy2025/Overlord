"""
Temu后端视图完整修复
将以下内容添加到 general/views_temu_management.py 文件中
"""

# ==================== 第一部分：修改 get_temu_shops_api 函数 ====================
# 替换第 213-233 行的筛选逻辑：

"""
        # 处理店铺状态多选（逗号分隔）
        status_filter = request.GET.get('status', '').strip()
        if status_filter:
            try:
                # 支持 "1,2,3" 格式
                status_list = [int(s) for s in status_filter.split(',') if s]
                if status_list:
                    query = query.filter(shop_status__in=status_list)
            except ValueError:
                pass  # 如果转换失败，忽略该筛选

        # 处理运营人员多选（逗号分隔的ID列表）
        operator_filter = request.GET.get('operator', '').strip()
        if operator_filter:
            try:
                # 支持 "30,28" 格式
                operator_list = [int(o) for o in operator_filter.split(',') if o]
                if operator_list:
                    query = query.filter(ops_id__in=operator_list)
            except ValueError:
                pass

        # 处理运营分组多选
        ops_group_filter = request.GET.get('ops_group', '').strip()
        if ops_group_filter:
            # 支持多个分组，逗号分隔
            group_list = [g for g in ops_group_filter.split(',') if g]
            if group_list:
                # 获取该分组的所有运营人员ID
                user_ids = OperationalAccount.objects.filter(
                    ops_group__in=group_list
                ).values_list('user_id', flat=True)
                query = query.filter(ops_id__in=list(user_ids))

        # 处理客户多选（逗号分隔）
        customer_filter = request.GET.get('customer', '').strip()
        if customer_filter:
            # 支按 "客户A,客户B" 格式
            customer_list = [c for c in customer_filter.split(',') if c]
            if customer_list:
                query = query.filter(customer__in=customer_list)

        # 搜索词
        search_term = request.GET.get('search', '').strip()
        if search_term:
            query = query.filter(
                Q(shop_name__icontains=search_term) |
                Q(shop_account__icontains=search_term) |
                Q(shop_temu_id__icontains=search_term)
            )
"""


# ==================== 第二部分：添加项目字段到返回数据 ====================
# 在单店铺查询部分（第 172-196 行）添加 project_name 字段：
"""
                shop_dict = {
                    'id': shop.id,
                    'shop_name': shop.shop_name or '-',
                    'project_id': shop.project_id if shop.project_id else '',
                    'project_name': shop.project.name if shop.project else '-',
                    # ... 其他字段不变 ...
                }
"""

# 在列表查询部分（第 261-285 行）添加 project_name 字段：
"""
            shops_data.append({
                'id': shop.id,
                'shop_name': shop.shop_name or '-',
                'project_id': shop.project_id if shop.project_id else '',
                'project_name': shop.project.name if shop.project else '-',
                # ... 其他字段不变 ...
            })
"""


# ==================== 第三部分：修改创建店铺API支持project_id ====================
# 在 create_temu_shop_api 函数中（第 307-368 行），在创建 shop 时添加 project 字段：

"""
        # 获取项目ID
        project_id = data.get('project_id')
        project = None
        if project_id:
            from general.models import Project
            try:
                project = Project.objects.get(id=int(project_id))
            except (Project.DoesNotExist, ValueError):
                pass

        # 使用事务确保数据一致性
        with transaction.atomic():
            shop = TemuShop.objects.create(
                # 基本信息
                project=project,  # 添加项目关联
                shop_name=shop_name,
                # ... 其他字段不变 ...
            )
"""


# ==================== 第四部分：修改更新店铺API支持project_id ====================
# 在 update_temu_shop_api 函数中（第 374-420 行），在更新 shop 时添加 project 字段：

"""
        with transaction.atomic():
            # 更新项目关联
            project_id = data.get('project_id')
            if project_id is not None:  # 允许空值表示移除项目
                if project_id == '' or project_id == '':
                    shop.project = None
                else:
                    try:
                        from general.models import Project
                        project = Project.objects.get(id=int(project_id))
                        shop.project = project
                    except (Project.DoesNotExist, ValueError):
                        pass  # 如果项目不存在，保持原来的
            
            # 基本信息
            shop.shop_name = shop_name
            # ... 其他字段不变 ...
"""


# ==================== 第五部分：添加批量更新项目API ====================
# 在文件末尾添加以下函数：

"""
from django.utils import timezone

@require_POST
@csrf_exempt
@login_required
def bulk_update_project_api(request):
    """批量设置或移除Temu店铺的项目归属"""
    try:
        data = json.loads(request.body)
        shop_ids = data.get('shop_ids', [])
        project_id = data.get('project_id')  # 为 None 或 '' 表示移除项目

        if not shop_ids:
            return JsonResponse({'success': False, 'error': '未选择店铺'}, status=400)

        with transaction.atomic():
            if project_id:
                # 设置项目
                from general.models import Project
                try:
                    project = Project.objects.get(id=int(project_id))
                    TemuShop.objects.filter(id__in=shop_ids).update(project=project)
                except Project.DoesNotExist:
                    return JsonResponse({'success': False, 'error': '项目不存在'}, status=404)
                except ValueError:
                    return JsonResponse({'success': False, 'error': '项目ID格式错误'}, status=400)
            else:
                # 移除项目
                TemuShop.objects.filter(id__in=shop_ids).update(project=None)

        return JsonResponse({
            'success': True, 
            'message': '批量操作成功',
            'updated_count': len(shop_ids)
        })

    except Exception as e:
        print(f"批量更新项目错误: {str(e)}")
        import traceback
        traceback.print_exc()
        return JsonResponse({
            'success': False, 
            'error': f'服务器错误: {str(e)}'
        }, status=500)
"""
