"""
Temu后端视图修复代码
将以下代码添加到 general/views_temu_management.py 文件中
"""

# 1. 修改 get_temu_shops_api 函数支持多选筛选
# 在处理筛选参数的地方替换为：

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

        # 处理客户多选
        customer_filter = request.GET.get('customer', '').strip()
        if customer_filter:
            # 支持 "客户A,客户B" 格式
            customer_list = [c for c in customer_filter.split(',') if c]
            if customer_list:
                query = query.filter(customer__in=customer_list)

        # 处理运营人员多选
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
            # 通过 ops_id 反查分组
            group_list = [g for g in ops_group_filter.split(',') if g]
            if group_list:
                # 获取该分组的所有运营人员ID
                from general.models import OperationalAccount
                ops_in_groups = OperationalAccount.objects.filter(
                    ops_group__in=group_list
                ).values_list('user_id', flat=True)
                query = query.filter(ops_id__in=list(ops_in_groups))
"""


# 2. 添加批量更新项目API
# 在文件末尾添加：

"""
from django.utils import timezone
from django.db import transaction

@require_POST
@csrf_exempt
@login_required
def bulk_update_project_api(request):
    """批量设置或移除Temu店铺的项目归属"""
    try:
        data = json.loads(request.body)
        shop_ids = data.get('shop_ids', [])
        project_id = data.get('project_id')  # 为 None 表示移除项目

        if not shop_ids:
            return JsonResponse({'success': False, 'error': '未选择店铺'}, status=400)

        with transaction.atomic():
            if project_id:
                # 设置项目
                from general.models import Project
                try:
                    project = Project.objects.get(id=project_id)
                    TemuShop.objects.filter(id__in=shop_ids).update(
                        project=project
                    )
                except Project.DoesNotExist:
                    return JsonResponse({'success': False, 'error': '项目不存在'}, status=404)
            else:
                # 移除项目 - 需要设置为默认项目或空
                # 如果模型允许null，则设置为None
                TemuShop.objects.filter(id__in=shop_ids).update(project=None)

        return JsonResponse({'success': True, 'message': '批量操作成功'})

    except Exception as e:
        print(f"批量更新项目错误: {str(e)}")
        return JsonResponse({'success': False, 'error': f'服务器错误: {str(e)}'}, status=500)
"""


# 3. 修改创建/更新店铺API支持project_id
# 在创建和更新视图中添加对project_id的处理：

"""
# 在创建店铺时：
project_id = data.get('project_id')
if project_id:
    try:
        from general.models import Project
        project = Project.objects.get(id=project_id)
        shop.project = project
    except Project.DoesNotExist:
        pass  # 如果项目不存在，忽略

# 在更新店铺时同样处理...
"""


# 4. 修改模型（如果需要）
# 如果 TemuShop 的 project 字段不允许 null，需要修改：
"""
# 在 general/models.py 中修改 TemuShop 模型：
class TemuShop(models.Model):
    # ... 其他字段 ...
    
    project = models.ForeignKey(
        'general.Project',
        on_delete=models.PROTECT,
        related_name='temu_shops',
        verbose_name='所属项目',
        null=True,  # 允许为空
        blank=True,  # 表单中允许为空
        db_comment='业务分组标签，可自由迁移'
    )
    # ... 其他字段 ...
"""
