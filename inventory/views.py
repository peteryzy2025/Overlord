import json
import os
import tempfile
import openpyxl
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from django.db.models import Q
from django.core.paginator import Paginator
from django.utils import timezone
from .models import InventoryMaster, Factory

@login_required
def inventory_list_page(request):
    """库存清单页面"""
    return render(request, 'inventory_list.html')

@login_required
@require_http_methods(["GET"])
def get_factories_api(request):
    """获取工厂列表API"""
    try:
        factories = Factory.objects.values('id', 'name').order_by('name')
        return JsonResponse({
            'success': True,
            'data': list(factories)
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'获取工厂列表失败: {str(e)}'
        }, status=500)

@login_required
@require_http_methods(["POST"])
def get_inventory_list_api(request):
    """获取库存列表API"""
    try:
        data = json.loads(request.body) if request.body else {}
        
        # 基础查询
        queryset = InventoryMaster.objects.select_related('factory').all()
        
        # 筛选条件
        filters = Q()
        
        mosku = data.get('mosku')
        if mosku:
            filters &= Q(mosku__icontains=mosku)
            
        product_name = data.get('product_name')
        if product_name:
            filters &= Q(product_name__icontains=product_name)
            
        factory_name = data.get('factory_name')
        if factory_name:
            filters &= Q(factory__name__icontains=factory_name)
            
        supplier_name = data.get('supplier_name')
        if supplier_name:
            filters &= Q(supplier_name__icontains=supplier_name)
            
        queryset = queryset.filter(filters)
        
        # 排序
        sort_field = data.get('sort_field', 'mosku')
        sort_order = data.get('sort_order', 'asc')
        
        if sort_field:
            if sort_field == 'factory_name':
                order_by = 'factory__name'
            else:
                order_by = sort_field
                
            if sort_order == 'desc':
                order_by = f'-{order_by}'
            
            queryset = queryset.order_by(order_by)
            
        # 分页
        page = int(data.get('page', 1))
        page_size = int(data.get('page_size', 20))
        paginator = Paginator(queryset, page_size)
        
        try:
            page_obj = paginator.page(page)
        except:
            page_obj = paginator.page(1)
            
        # 序列化数据
        items = []
        for item in page_obj.object_list:
            items.append({
                'mosku': item.mosku,
                'product_name': item.product_name,
                'factory_name': item.factory.name if item.factory else '-',
                'supplier_name': item.supplier_name,
                'stock_qty': item.stock_qty,
                'available_qty': item.stock_qty, # 暂时使用总库存代替可用库存，后续可对接InventoryDaily
                'color': item.color,
                'size': item.size,
                'location': item.location,
                'is_active': True, # 暂时默认为True
                'latest_date': timezone.now().date().isoformat(), # 示例日期
                'trend_data': [], # 趋势图占位
                'diff_3_pct': 0,
                'diff_7_pct': 0,
            })
            
        return JsonResponse({
            'success': True,
            'data': {
                'items': items,
                'total': paginator.count,
                'total_pages': paginator.num_pages
            }
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({
            'success': False,
            'message': f'获取数据失败: {str(e)}'
        }, status=500)

@csrf_exempt
@require_http_methods(["POST"])
def import_inventory_excel(request):
    """导入库存Excel"""
    # 1. 权限检查 (根据实际需求调整，这里暂时只检查登录)
    # if not request.user.has_perm('inventory.add_inventorymaster'):
    #     return JsonResponse({'success': False, 'message': '权限不足'}, status=403)
        
    if 'file' not in request.FILES:
        return JsonResponse({'success': False, 'message': '未上传文件'}, status=400)
        
    factory_id = request.POST.get('factory_id')
    # 注意：如果Excel中包含工厂信息，factory_id可以不是必须的，
    # 但由于mosku+factory唯一，通常建议指定工厂导入，或者Excel里明确指定工厂。
    # 这里我们采用策略：优先使用UI选择的工厂，如果未选择，则尝试从Excel读取（暂未实现Excel读取工厂列，简单起见要求UI选择）
    
    target_factory = None
    if factory_id:
        try:
            target_factory = Factory.objects.get(id=factory_id)
        except Factory.DoesNotExist:
            return JsonResponse({'success': False, 'message': '选择的工厂不存在'}, status=400)
    
    file = request.FILES['file']
    allowed_extensions = ['.xlsx', '.xls']
    file_ext = os.path.splitext(file.name)[1].lower()
    
    if file_ext not in allowed_extensions:
        return JsonResponse({'success': False, 'message': '不支持的文件格式'}, status=400)
        
    # 保存临时文件
    with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as tmp_file:
        for chunk in file.chunks():
            tmp_file.write(chunk)
        tmp_file_path = tmp_file.name
        
    try:
        wb = openpyxl.load_workbook(tmp_file_path, data_only=True)
        ws = wb.active
        
        # 识别表头
        header_map = {}
        # 期望的列名 -> 模型字段名
        expected_columns = {
            'MOSKU': 'mosku',
            '产品名称': 'product_name',
            '颜色': 'color',
            '尺码': 'size',
            '库位': 'location',
            '库存数量': 'stock_qty',
            '供应商': 'supplier_name',
            '供应商名称': 'supplier_name',
            '工厂': 'factory_name_in_excel',
            '工厂名称': 'factory_name_in_excel',
        }
        
        headers = [cell.value for cell in ws[1]]
        for idx, header in enumerate(headers):
            if not header: continue
            header_str = str(header).strip().upper() # 统一转大写比较
            
            # 尝试匹配
            for col_name, field_name in expected_columns.items():
                if col_name in header_str or header_str in col_name:
                    header_map[field_name] = idx
                    break
        
        if 'mosku' not in header_map:
             return JsonResponse({'success': False, 'message': '未找到MOSKU列'}, status=400)
             
        stats = {
            'total': 0,
            'updated': 0,
            'created': 0,
            'errors': 0,
            'details': []
        }
        
        # 缓存工厂对象，避免每行都查询数据库
        factory_cache = {}
        if target_factory:
            factory_cache[target_factory.name] = target_factory
        
        # 开始导入
        for row_idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
            try:
                mosku = row[header_map['mosku']]
                if not mosku: continue
                
                mosku = str(mosku).strip()
                stats['total'] += 1
                
                # 准备数据
                data = {'mosku': mosku}
                
                # 确定工厂
                current_factory = target_factory
                
                # 如果没有全局指定工厂，尝试从Excel行读取
                if not current_factory and 'factory_name_in_excel' in header_map:
                    raw_factory_name = row[header_map['factory_name_in_excel']]
                    if raw_factory_name:
                        factory_name = str(raw_factory_name).strip()
                        if factory_name:
                            # 尝试从缓存获取
                            if factory_name in factory_cache:
                                current_factory = factory_cache[factory_name]
                            else:
                                # 数据库查询或创建
                                current_factory, _ = Factory.objects.get_or_create(name=factory_name)
                                factory_cache[factory_name] = current_factory
                
                # 如果最终没有确定工厂，则报错
                if not current_factory:
                     stats['errors'] += 1
                     stats['details'].append(f"第{row_idx}行: 未指定工厂且Excel中未找到有效工厂名称")
                     continue
                
                data['factory'] = current_factory
                
                # 读取其他字段
                defaults = {}
                if 'product_name' in header_map:
                    defaults['product_name'] = str(row[header_map['product_name']] or '')
                else:
                    defaults['product_name'] = mosku # 默认产品名为mosku
                    
                if 'color' in header_map:
                    defaults['color'] = str(row[header_map['color']] or '')
                    
                if 'size' in header_map:
                    defaults['size'] = str(row[header_map['size']] or '')
                    
                if 'location' in header_map:
                    defaults['location'] = str(row[header_map['location']] or '')
                    
                if 'supplier_name' in header_map:
                    defaults['supplier_name'] = str(row[header_map['supplier_name']] or '')
                    
                if 'stock_qty' in header_map:
                    try:
                        defaults['stock_qty'] = int(row[header_map['stock_qty']] or 0)
                    except:
                        defaults['stock_qty'] = 0
                
                # 更新或创建
                # 核心逻辑：使用 (mosku, factory) 作为唯一标识
                obj, created = InventoryMaster.objects.update_or_create(
                    mosku=mosku,
                    factory=current_factory,
                    defaults=defaults
                )
                
                if created:
                    stats['created'] += 1
                else:
                    stats['updated'] += 1
                    
            except Exception as row_e:
                stats['errors'] += 1
                stats['details'].append(f"第{row_idx}行错误: {str(row_e)}")
                
        return JsonResponse({
            'success': True,
            'data': stats,
            'message': f"导入完成: 新增{stats['created']}, 更新{stats['updated']}, 失败{stats['errors']}"
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({'success': False, 'message': f'文件解析失败: {str(e)}'}, status=500)
    finally:
        try:
            os.unlink(tmp_file_path)
        except:
            pass
