# Yuser/view_yuser.py
import json
from django.shortcuts import render
from django.http import JsonResponse
from django.db import transaction
from django.db.models import Q, Sum, F, DecimalField
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from decimal import Decimal

from General.models import User, UserOperationLog
from Yuser.models import (
    AssessmentTemplate, AssessmentCategory, AssessmentGroup,
    AssessmentItem, ScoringRule, AssessmentInstance, AssessmentScore
)


def check_permission_555(user):
    """检查用户是否有555权限（考核管理权限）"""
    if not user.permission:
        return False
    return '555' in user.permission.split(',')


@login_required
def assessment_management_view(request):
    """主页面视图"""
    if not check_permission_555(request.user):
        return render(request, '403.html', {'message': '需要权限555才能访问'})

    return render(request, 'assessment_management.html', {
        'username': request.user.first_name or request.user.username,
    })


# ==================== 模板管理API ====================

@login_required
@require_http_methods(["GET"])
def api_template_list(request):
    """获取模板列表"""
    if not check_permission_555(request.user):
        return JsonResponse({'success': False, 'error': '权限不足'}, status=403)

    page = int(request.GET.get('page', 1))
    page_size = int(request.GET.get('page_size', 10))
    search = request.GET.get('search', '')
    status_filter = request.GET.get('status', '')

    # 查询模板
    templates = AssessmentTemplate.objects.all()
    if search:
        templates = templates.filter(name__icontains=search)
    if status_filter:
        templates = templates.filter(is_active=(status_filter == 'active'))

    templates = templates.order_by('-created_at')
    total = templates.count()

    # 分页
    start = (page - 1) * page_size
    end = start + page_size

    data = []
    for template in templates[start:end]:
        # 统计实例数量
        instance_count = AssessmentInstance.objects.filter(template=template).count()
        active_instances = AssessmentInstance.objects.filter(
            template=template,
            status__in=['submitted', 'confirmed']
        ).count()

        data.append({
            'id': template.id,
            'name': template.name,
            'version': template.version,
            'is_active': template.is_active,
            'instance_count': instance_count,
            'active_instances': active_instances,
            'can_delete': instance_count == 0,
            'can_edit_structure': active_instances == 0,
            'created_at': template.created_at.strftime('%Y-%m-%d %H:%M:%S'),
        })

    return JsonResponse({
        'success': True,
        'data': data,
        'total': total,
        'page': page,
        'page_size': page_size
    })


@login_required
@require_http_methods(["POST"])
@transaction.atomic
def api_template_create(request):
    """创建模板（支持嵌套结构）"""
    if not check_permission_555(request.user):
        return JsonResponse({'success': False, 'error': '权限不足'}, status=403)

    try:
        data = json.loads(request.body)

        # 创建模板
        template = AssessmentTemplate.objects.create(
            name=data['name'].strip(),
            description=data.get('description', '').strip(),
            version=data.get('version', '1.0').strip(),
            is_active=data.get('is_active', True)
        )

        # 创建分类结构
        _create_template_structure(template, data.get('categories', []))

        # 记录日志
        UserOperationLog.objects.create(
            user=request.user,
            operation_type=UserOperationLog.USER_CREATE,
            operation_record=f"创建考核模板: {template.name} (ID:{template.id})"
        )

        return JsonResponse({
            'success': True,
            'message': '模板创建成功',
            'template_id': template.id
        })

    except Exception as e:
        return JsonResponse({'success': False, 'error': f'创建失败: {str(e)}'}, status=400)


@login_required
@require_http_methods(["GET"])
def api_template_detail(request, template_id):
    """获取模板详情（含完整嵌套结构）"""
    if not check_permission_555(request.user):
        return JsonResponse({'success': False, 'error': '权限不足'}, status=403)

    try:
        template = AssessmentTemplate.objects.prefetch_related(
            'categories__groups__items__scoring_rules'
        ).get(id=template_id)

        # 检查是否有已提交的实例
        has_active_instances = AssessmentInstance.objects.filter(
            template=template,
            status__in=['submitted', 'confirmed']
        ).exists()

        # 构建嵌套结构
        categories_data = []
        for category in template.categories.all():
            if category.groups.exists():  # 行为考核类型（有分组）
                groups_data = []
                for group in category.groups.all():
                    items_data = []
                    for item in group.items.all():
                        rules = [{
                            'id': rule.id,
                            'condition': rule.condition,
                            'score_rule': rule.score_rule,
                            'order': rule.order
                        } for rule in item.scoring_rules.all()]

                        items_data.append({
                            'id': item.id,
                            'serial_number': item.serial_number or '',
                            'name': item.name,
                            'description': item.description or '',
                            'max_score': float(item.max_score),
                            'scoring_type': item.scoring_type,
                            'is_zero_if_violated': item.is_zero_if_violated,
                            'is_bonus_item': item.is_bonus_item,
                            'order': item.order,
                            'rules': rules
                        })

                    groups_data.append({
                        'id': group.id,
                        'name': group.name,
                        'order': group.order,
                        'items': items_data
                    })

                categories_data.append({
                    'id': category.id,
                    'name': category.name,
                    'weight': float(category.weight),
                    'order': category.order,
                    'has_groups': True,
                    'groups': groups_data
                })
            else:  # 业绩指标类型（无分组）
                items_data = []
                for item in category.items.all():
                    rules = [{
                        'id': rule.id,
                        'condition': rule.condition,
                        'score_rule': rule.score_rule,
                        'order': rule.order
                    } for rule in item.scoring_rules.all()]

                    items_data.append({
                        'id': item.id,
                        'serial_number': item.serial_number or '',
                        'name': item.name,
                        'description': item.description or '',
                        'max_score': float(item.max_score),
                        'scoring_type': item.scoring_type,
                        'is_zero_if_violated': item.is_zero_if_violated,
                        'is_bonus_item': item.is_bonus_item,
                        'order': item.order,
                        'rules': rules
                    })

                categories_data.append({
                    'id': category.id,
                    'name': category.name,
                    'weight': float(category.weight),
                    'order': category.order,
                    'has_groups': False,
                    'items': items_data
                })

        return JsonResponse({
            'success': True,
            'data': {
                'id': template.id,
                'name': template.name,
                'description': template.description,
                'version': template.version,
                'is_active': template.is_active,
                'can_edit_structure': not has_active_instances,
                'categories': categories_data
            }
        })

    except AssessmentTemplate.DoesNotExist:
        return JsonResponse({'success': False, 'error': '模板不存在'}, status=404)


@login_required
@require_http_methods(["POST"])
@transaction.atomic
def api_template_update(request, template_id):
    """更新模板"""
    if not check_permission_555(request.user):
        return JsonResponse({'success': False, 'error': '权限不足'}, status=403)

    try:
        template = AssessmentTemplate.objects.get(id=template_id)
        data = json.loads(request.body)

        # 检查是否有已提交的实例
        has_active_instances = AssessmentInstance.objects.filter(
            template=template,
            status__in=['submitted', 'confirmed']
        ).exists()

        # 更新基本信息
        template.name = data.get('name', template.name).strip()
        template.description = data.get('description', template.description).strip()
        template.version = data.get('version', template.version).strip()
        template.is_active = data.get('is_active', template.is_active)
        template.save()

        # 如果能编辑结构，则重建整个结构
        if not has_active_instances and 'categories' in data:
            # 删除原有结构
            template.categories.all().delete()
            # 重新创建
            _create_template_structure(template, data['categories'])

        # 记录日志
        UserOperationLog.objects.create(
            user=request.user,
            operation_type=UserOperationLog.USER_UPDATE,
            operation_record=f"更新考核模板: {template.name} (ID:{template.id})"
        )

        return JsonResponse({'success': True, 'message': '模板更新成功'})

    except AssessmentTemplate.DoesNotExist:
        return JsonResponse({'success': False, 'error': '模板不存在'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'error': f'更新失败: {str(e)}'}, status=400)


@login_required
@require_http_methods(["POST"])
def api_template_delete(request, template_id):
    """删除模板"""
    if not check_permission_555(request.user):
        return JsonResponse({'success': False, 'error': '权限不足'}, status=403)

    try:
        template = AssessmentTemplate.objects.get(id=template_id)

        # 检查是否有实例
        if AssessmentInstance.objects.filter(template=template).exists():
            return JsonResponse({'success': False, 'error': '该模板已有考核实例，不能删除'}, status=400)

        template.delete()

        UserOperationLog.objects.create(
            user=request.user,
            operation_type=UserOperationLog.USER_DELETE,
            operation_record=f"删除考核模板: {template.name} (ID:{template.id})"
        )

        return JsonResponse({'success': True, 'message': '模板删除成功'})

    except AssessmentTemplate.DoesNotExist:
        return JsonResponse({'success': False, 'error': '模板不存在'}, status=404)


def _create_template_structure(template, categories_data):
    """辅助函数：创建模板的完整结构"""
    for cat_data in categories_data:
        category = AssessmentCategory.objects.create(
            template=template,
            name=cat_data['name'].strip(),
            weight=Decimal(str(cat_data.get('weight', 0))),
            order=cat_data.get('order', 0)
        )

        if cat_data.get('has_groups', False):
            # 行为考核类型：有分组
            for group_data in cat_data.get('groups', []):
                group = AssessmentGroup.objects.create(
                    category=category,
                    name=group_data['name'].strip(),
                    order=group_data.get('order', 0)
                )

                for item_data in group_data.get('items', []):
                    _create_item(group, category, item_data, is_direct=False)
        else:
            # 业绩指标类型：无分组，直接挂分类
            for item_data in cat_data.get('items', []):
                _create_item(None, category, item_data, is_direct=True)


def _create_item(group, category, item_data, is_direct=True):
    """辅助函数：创建项目及评分标准"""
    try:
        # 判断是否为加分项
        is_bonus = '加分项' in item_data.get('name', '') or item_data.get('is_bonus_item', False)
        # 判断是否为"分数全无"项
        is_zero_violated = '分数全无' in item_data.get('name', '') or item_data.get('is_zero_if_violated', False)

        # 准备基础数据
        item = AssessmentItem.objects.create(
            category=category,  # 必须关联一级分类
            group=group if not is_direct else None,  # 业绩指标类型group为None
            serial_number=item_data.get('serial_number', ''),
            name=item_data['name'].strip(),
            description=item_data.get('description', '').strip(),
            max_score=Decimal(str(item_data['max_score'])),
            scoring_type=item_data.get('scoring_type', 'manual'),
            is_zero_if_violated=is_zero_violated,
            is_bonus_item=is_bonus,
            order=item_data.get('order', 0)
        )

        # 创建评分标准
        for rule_data in item_data.get('rules', []):
            ScoringRule.objects.create(
                item=item,
                condition=rule_data.get('condition', '').strip(),
                score_rule=rule_data.get('score_rule', '').strip(),
                order=rule_data.get('order', 0)
            )

        return item

    except Exception as e:
        print(f"创建项目失败: {str(e)}")
        raise e


# ==================== 实例管理API ====================

@login_required
@require_http_methods(["GET"])
def api_instance_list(request):
    """获取考核实例列表"""
    if not check_permission_555(request.user):
        return JsonResponse({'success': False, 'error': '权限不足'}, status=403)

    page = int(request.GET.get('page', 1))
    page_size = int(request.GET.get('page_size', 10))
    search = request.GET.get('search', '')
    status_filter = request.GET.get('status', '')

    instances = AssessmentInstance.objects.select_related(
        'template'
    ).prefetch_related('item_scores__item').order_by('-created_at')

    if search:
        instances = instances.filter(
            Q(employee_name__icontains=search) |
            Q(period__icontains=search) |
            Q(department__icontains=search)
        )

    if status_filter:
        instances = instances.filter(status=status_filter)

    total = instances.count()
    start = (page - 1) * page_size
    end = start + page_size

    data = []
    for instance in instances[start:end]:
        # 计算进度
        total_items = instance.item_scores.count()
        scored_items = instance.item_scores.filter(actual_score__gt=0).count()

        data.append({
            'id': instance.id,
            'template_name': instance.template.name,
            'employee_name': instance.employee_name,
            'department': instance.department,
            'position': instance.position,
            'period': instance.period,
            'total_score': float(instance.total_score) if instance.total_score else None,
            'grade': instance.grade,
            'status': instance.status,
            'status_display': instance.get_status_display(),
            'progress': f"{scored_items}/{total_items}",
            'created_at': instance.created_at.strftime('%Y-%m-%d %H:%M:%S'),
        })

    return JsonResponse({
        'success': True,
        'data': data,
        'total': total,
        'page': page,
        'page_size': page_size
    })


@login_required
@require_http_methods(["POST"])
@transaction.atomic
def api_instance_create(request):
    """创建考核实例"""
    if not check_permission_555(request.user):
        return JsonResponse({'success': False, 'error': '权限不足'}, status=403)

    try:
        data = json.loads(request.body)
        template = AssessmentTemplate.objects.get(id=data['template_id'])

        # 检查是否已存在同周期实例
        if AssessmentInstance.objects.filter(
                template=template,
                employee_name=data['employee_name'],
                period=data['period']
        ).exists():
            return JsonResponse({'success': False, 'error': '该员工已存在相同周期的考核实例'}, status=400)

        # 创建实例
        instance = AssessmentInstance.objects.create(
            template=template,
            employee_name=data['employee_name'].strip(),
            department=data.get('department', '运营部').strip(),
            position=data.get('position', '运营专员').strip(),
            period=data['period'].strip(),
            status='draft'
        )

        # 初始化所有评分项
        items_query = AssessmentItem.objects.filter(
            Q(category__template=template)
        ).select_related('category')

        for item in items_query:
            AssessmentScore.objects.create(
                instance=instance,
                item=item,
                actual_score=Decimal('0'),
                remarks=''
            )

        # 记录日志
        UserOperationLog.objects.create(
            user=request.user,
            operation_type=1004,  # 模板操作
            operation_record=f"创建考核实例: {instance.employee_name} - {instance.period} (ID:{instance.id})"
        )

        return JsonResponse({
            'success': True,
            'message': '考核实例创建成功',
            'instance_id': instance.id
        })

    except Exception as e:
        return JsonResponse({'success': False, 'error': f'创建失败: {str(e)}'}, status=400)


@login_required
@require_http_methods(["GET"])
def api_instance_detail(request, instance_id):
    """获取考核实例详情（用于填写）"""
    if not check_permission_555(request.user):
        return JsonResponse({'success': False, 'error': '权限不足'}, status=403)

    try:
        instance = AssessmentInstance.objects.prefetch_related(
            'item_scores__item__category',
            'template__categories__groups__items'
        ).get(id=instance_id)

        # 构建层级结构
        categories_data = []
        for category in instance.template.categories.all():
            groups_data = []
            if category.groups.exists():  # 有分组（行为考核）
                for group in category.groups.all():
                    items_data = []
                    for item in group.items.all():
                        score_obj = instance.item_scores.get(item=item)
                        items_data.append(_build_item_data(item, score_obj))

                    groups_data.append({
                        'group_id': group.id,
                        'group_name': group.name,
                        'items': items_data
                    })
            else:  # 无分组（业绩指标）
                items_data = []
                for item in category.items.all():
                    score_obj = instance.item_scores.get(item=item)
                    items_data.append(_build_item_data(item, score_obj))

                groups_data.append({
                    'group_id': None,
                    'group_name': None,
                    'items': items_data
                })

            categories_data.append({
                'category_id': category.id,
                'category_name': category.name,
                'weight': float(category.weight),
                'groups': groups_data
            })

        return JsonResponse({
            'success': True,
            'data': {
                'id': instance.id,
                'template_name': instance.template.name,
                'employee_name': instance.employee_name,
                'department': instance.department,
                'position': instance.position,
                'period': instance.period,
                'status': instance.status,
                'status_display': instance.get_status_display(),
                'total_score': float(instance.total_score) if instance.total_score else None,
                'grade': instance.grade,
                'categories': categories_data
            }
        })

    except AssessmentInstance.DoesNotExist:
        return JsonResponse({'success': False, 'error': '考核实例不存在'}, status=404)


def _build_item_data(item, score_obj):
    """辅助函数：构建项目数据"""
    return {
        'score_id': score_obj.id,
        'item_id': item.id,
        'item_name': item.name,
        'serial_number': item.serial_number,
        'description': item.description,
        'max_score': float(item.max_score),
        'scoring_type': item.scoring_type,
        'is_zero_if_violated': item.is_zero_if_violated,
        'is_bonus_item': item.is_bonus_item,
        'rules': [{
            'condition': rule.condition,
            'score_rule': rule.score_rule
        } for rule in item.scoring_rules.all()],
        'actual_score': float(score_obj.actual_score),
        'remarks': score_obj.remarks
    }


@login_required
@require_http_methods(["POST"])
@transaction.atomic
@login_required
@require_http_methods(["POST"])
@transaction.atomic
def api_instance_update(request, instance_id):
    """更新考核实例（填写分数、变更状态）"""
    if not check_permission_555(request.user):
        return JsonResponse({'success': False, 'error': '权限不足'}, status=403)

    try:
        instance = AssessmentInstance.objects.get(id=instance_id)
        data = json.loads(request.body)

        # 更新评分
        if 'scores' in data:
            for score_data in data['scores']:
                AssessmentScore.objects.filter(id=score_data['score_id']).update(
                    actual_score=Decimal(str(score_data['actual_score'])),
                    remarks=score_data.get('remarks', '').strip()
                )

        # 状态变更
        new_status = data.get('status')
        if new_status and new_status != instance.status:
            # 状态流转校验
            valid_transitions = {
                'draft': ['submitted'],
                'submitted': ['draft', 'confirmed'],
                'confirmed': []
            }

            if new_status not in valid_transitions.get(instance.status, []):
                return JsonResponse({
                    'success': False,
                    'error': f'无效的状态流转：{instance.status} -> {new_status}'
                }, status=400)

            instance.status = new_status

            # 如果是确认状态，计算总分
            if 'scores' in data:
                for score_data in data['scores']:
                    AssessmentScore.objects.filter(id=score_data['score_id']).update(...)

                # 新增：无论状态如何，都重新计算总分和评级
                _calculate_instance_score(instance)

            instance.save()

            # 记录状态变更日志
            UserOperationLog.objects.create(
                user=request.user,
                operation_type=1004,
                operation_record=f"更新考核实例状态: {instance.employee_name} - {instance.period} "
                                 f"{instance.get_status_display()} (ID:{instance.id})"
            )

        # 记录编辑日志（只有草稿状态才记录）
        if instance.status == 'draft':
            UserOperationLog.objects.create(
                user=request.user,
                operation_type=1004,
                operation_record=f"编辑考核实例: {instance.employee_name} - {instance.period} (ID:{instance.id})"
            )

        return JsonResponse({
            'success': True,
            'message': '更新成功',  # 修复：加上引号
            'total_score': float(instance.total_score) if instance.total_score else None,
            'grade': instance.grade,
            'status': instance.status,
            'status_display': instance.get_status_display()
        })

    except AssessmentInstance.DoesNotExist:
        return JsonResponse({'success': False, 'error': '考核实例不存在'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'error': f'更新失败: {str(e)}'}, status=400)


def _calculate_instance_score(instance):
    """计算考核实例总分和评级（按权重）"""
    total_score = Decimal('0')
    has_zero_violated = False

    # 遍历所有分类
    for category in instance.template.categories.all():
        category_score = Decimal('0')
        category_max_score = Decimal('0')

        # 获取该分类下的所有项目
        items_query = AssessmentItem.objects.filter(
            Q(category=category) | Q(group__category=category)
        )

        for item in items_query:
            score_obj = instance.item_scores.get(item=item)
            item_score = score_obj.actual_score

            # 检查"分数全无"规则
            if item.is_zero_if_violated and item_score == 0:
                has_zero_violated = True
                break

            # 累加分项得分
            if item.is_bonus_item:
                total_score += item_score
            else:
                category_score += item_score
                category_max_score += item.max_score

        if has_zero_violated:
            break

        # 按权重计算该分类贡献的分数
        if category_max_score > 0:
            category_contribution = (category_score / category_max_score) * category.weight

    # 如果有"分数全无"项被触发，总分直接为0
    if has_zero_violated:
        total_score = Decimal('0')

    instance.total_score = total_score
    instance.grade = _calculate_grade(total_score)
    instance.save()


def _calculate_grade(score):
    """根据分数计算评级"""
    if score >= 150:
        return 'S'
    elif score >= 90:
        return 'A'
    elif score >= 80:
        return 'B'
    elif score >= 70:
        return 'C'
    elif score >= 60:
        return 'D'
    else:
        return 'E'


@login_required
@require_http_methods(["POST"])
def api_instance_delete(request, instance_id):
    """删除考核实例"""
    if not check_permission_555(request.user):
        return JsonResponse({'success': False, 'error': '权限不足'}, status=403)

    try:
        instance = AssessmentInstance.objects.get(id=instance_id)

        if instance.status != 'draft':
            return JsonResponse({'success': False, 'error': '只有草稿状态才能删除'}, status=400)

        instance.delete()

        UserOperationLog.objects.create(
            user=request.user,
            operation_type=UserOperationLog.USER_DELETE,
            operation_record=f"删除考核实例: {instance.employee_name} - {instance.period} (ID:{instance.id})"
        )

        return JsonResponse({'success': True, 'message': '删除成功'})

    except AssessmentInstance.DoesNotExist:
        return JsonResponse({'success': False, 'error': '考核实例不存在'}, status=404)


# ==================== 辅助API ====================

@login_required
def api_get_users_for_instance(request):
    """获取可用于创建实例的员工列表"""
    if not check_permission_555(request.user):
        return JsonResponse({'success': False, 'error': '权限不足'}, status=403)

    users = User.objects.filter(
        status=User.STATUS_NORMAL,
        department__in=['运营部', '运营部门', '运营']  # 根据实际情况调整
    ).values('id', 'first_name', 'department', 'role')

    return JsonResponse({
        'success': True,
        'data': list(users)
    })


@login_required
@require_http_methods(["POST"])
@transaction.atomic
def api_template_copy(request, template_id):
    """复制模板"""
    if not check_permission_555(request.user):
        return JsonResponse({'success': False, 'error': '权限不足'}, status=403)

    try:
        # 获取原模板
        source_template = AssessmentTemplate.objects.prefetch_related(
            'categories__groups__items__scoring_rules'
        ).get(id=template_id)

        # 创建新模板
        new_template = AssessmentTemplate.objects.create(
            name=f"{source_template.name}-复制",
            description=source_template.description,
            version="1.0",  # 复制后版本重置
            is_active=False  # 默认停用，需要用户手动启用
        )

        # 复制完整结构
        for category in source_template.categories.all():
            # 复制分类
            new_category = AssessmentCategory.objects.create(
                template=new_template,
                name=category.name,
                weight=category.weight,
                order=category.order
            )

            if category.groups.exists():  # 有分组（行为考核）
                for group in category.groups.all():
                    # 复制分组
                    new_group = AssessmentGroup.objects.create(
                        category=new_category,
                        name=group.name,
                        order=group.order
                    )

                    # 复制项目
                    for item in group.items.all():
                        new_item = AssessmentItem.objects.create(
                            category=new_category,
                            group=new_group,
                            serial_number=item.serial_number,
                            name=item.name,
                            description=item.description,
                            max_score=item.max_score,
                            scoring_type=item.scoring_type,
                            is_zero_if_violated=item.is_zero_if_violated,
                            is_bonus_item=item.is_bonus_item,
                            order=item.order
                        )

                        # 复制评分标准
                        for rule in item.scoring_rules.all():
                            ScoringRule.objects.create(
                                item=new_item,
                                condition=rule.condition,
                                score_rule=rule.score_rule,
                                order=rule.order
                            )
            else:  # 无分组（业绩指标）
                # 直接复制项目
                for item in category.items.all():
                    new_item = AssessmentItem.objects.create(
                        category=new_category,
                        group=None,
                        serial_number=item.serial_number,
                        name=item.name,
                        description=item.description,
                        max_score=item.max_score,
                        scoring_type=item.scoring_type,
                        is_zero_if_violated=item.is_zero_if_violated,
                        is_bonus_item=item.is_bonus_item,
                        order=item.order
                    )

                    # 复制评分标准
                    for rule in item.scoring_rules.all():
                        ScoringRule.objects.create(
                            item=new_item,
                            condition=rule.condition,
                            score_rule=rule.score_rule,
                            order=rule.order
                        )

        # 记录日志
        UserOperationLog.objects.create(
            user=request.user,
            operation_type=UserOperationLog.USER_CREATE,
            operation_record=f"复制考核模板: {source_template.name} -> {new_template.name} (新ID:{new_template.id})"
        )

        return JsonResponse({
            'success': True,
            'message': '模板复制成功',
            'new_template_id': new_template.id
        })

    except AssessmentTemplate.DoesNotExist:
        return JsonResponse({'success': False, 'error': '模板不存在'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'error': f'复制失败: {str(e)}'}, status=400)
