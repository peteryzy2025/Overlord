from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from django.http import JsonResponse
from django.db import transaction
from django.core.paginator import Paginator
import json

from task.models import ProductRequirement
from task.utils import parse_permissions

@login_required
def product_create_page(request):
    """
    产品需求创建页面
    """
    return render(request, 'product/product_create.html')

@login_required
def product_list_page(request):
    """
    产品需求列表页面
    """
    return render(request, 'product/product_list.html')

@login_required
@require_http_methods(["POST"])
@transaction.atomic
def create_product_requirement_api(request):
    """
    创建产品需求 (简化版)
    """
    try:
        data = json.loads(request.body)
        
        # 必填字段验证
        required_fields = ['platform', 'product_url']
        
        for field in required_fields:
            if not data.get(field):
                return JsonResponse({'success': False, 'message': f'字段 {field} 不能为空'}, status=400)
                
        # 创建对象
        requirement = ProductRequirement.objects.create(
            created_by=request.user,
            platform=data.get('platform'),
            product_url=data.get('product_url'),
            status=ProductRequirement.STATUS_SUBMITTED
        )
        
        return JsonResponse({
            'success': True,
            'data': {'id': requirement.id, 'redirect_url': '/task/product/list/'}
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)

@login_required
@require_http_methods(["GET"])
def get_product_requirements_api(request):
    """
    获取产品需求列表
    """
    try:
        page = int(request.GET.get('page', 1))
        page_size = int(request.GET.get('page_size', 20))
        status = request.GET.get('status')
        search = request.GET.get('search')
        
        queryset = ProductRequirement.objects.all().order_by('-created_at')
        
        # 筛选
        if status:
            queryset = queryset.filter(status=status)
            
        if search:
            queryset = queryset.filter(product_name__icontains=search)
            
        paginator = Paginator(queryset, page_size)
        page_obj = paginator.get_page(page)
        
        data = []
        for item in page_obj:
            data.append({
                'id': item.id,
                'product_name': item.product_name,
                'product_abbr': item.product_abbr,
                'english_name': item.english_name,
                'status': item.status,
                'status_display': item.get_status_display(),
                'created_by': item.created_by.first_name or item.created_by.username,
                'created_at': item.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                # 可以根据需要添加更多字段
            })
            
        return JsonResponse({
            'success': True,
            'data': {
                'items': data,
                'total': paginator.count,
                'page': page,
                'total_pages': paginator.num_pages
            }
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)

@login_required
@require_http_methods(["GET"])
def get_product_requirement_detail_api(request, pk):
    """
    获取单个产品需求详情
    """
    try:
        item = ProductRequirement.objects.get(pk=pk)
        
        data = {
            'id': item.id,
            'platform': item.platform,
            'product_url': item.product_url,
            'product_name': item.product_name,
            'product_abbr': item.product_abbr,
            'english_name': item.english_name,
            'material': item.material,
            'craft': item.craft,
            'unit': item.unit,
            
            'customs_cn_name': item.customs_cn_name,
            'customs_en_name': item.customs_en_name,
            'declared_weight': item.declared_weight,
            'declared_price': str(item.declared_price) if item.declared_price else None,
            'customs_code': item.customs_code,
            'material_cn': item.material_cn,
            'material_en': item.material_en,
            
            'material_desc': item.material_desc,
            'accessory_struct': item.accessory_struct,
            'product_performance': item.product_performance,
            'applicable_scenario': item.applicable_scenario,
            'washing_instructions': item.washing_instructions,
            'special_note': item.special_note,
            'reminder': item.reminder,
            
            'design_desc': item.design_desc,
            'design_area': item.design_area,
            'image_requirement': item.image_requirement,
            
            'status': item.status,
            'status_display': item.get_status_display(),
            'created_by': item.created_by.first_name or item.created_by.username,
            'created_at': item.created_at.strftime('%Y-%m-%d %H:%M:%S'),
        }
        
        # 检查当前用户是否有编辑权限 (PermissionConfig id=555)
        # 假设 parse_permissions 可以解析用户权限字符串
        permissions = parse_permissions(getattr(request.user, 'permission', ''))
        can_edit = '555' in permissions
        
        return JsonResponse({
            'success': True,
            'data': data,
            'meta': {
                'can_edit': can_edit
            }
        })
        
    except ProductRequirement.DoesNotExist:
        return JsonResponse({'success': False, 'message': '未找到该记录'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)

@login_required
@require_http_methods(["POST"])
def update_product_requirement_api(request, pk):
    """
    更新产品需求 (仅限拥有 555 权限的用户)
    """
    try:
        # 权限检查
        permissions = parse_permissions(getattr(request.user, 'permission', ''))
        if '555' not in permissions:
            return JsonResponse({'success': False, 'message': '无权限修改'}, status=403)
            
        item = ProductRequirement.objects.get(pk=pk)
        data = json.loads(request.body)
        
        # 更新字段
        fields = [
            'platform', 'product_url',
            'product_name', 'product_abbr', 'english_name', 'material',  
            'craft', 'unit', 'customs_cn_name', 'customs_en_name',
            'declared_weight', 'declared_price', 'customs_code',
            'material_cn', 'material_en', 'material_desc', 
            'accessory_struct', 'product_performance', 'applicable_scenario',
            'washing_instructions', 'special_note', 'reminder',
            'design_desc', 'design_area', 'image_requirement', 'status'
        ]
        
        for field in fields:
            if field in data:
                setattr(item, field, data[field])
                
        item.save()
        
        return JsonResponse({'success': True, 'message': '更新成功'})
        
    except ProductRequirement.DoesNotExist:
        return JsonResponse({'success': False, 'message': '未找到该记录'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)
