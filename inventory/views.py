from django.shortcuts import render
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.db.models import Q, Subquery, OuterRef
from django.utils import timezone
from datetime import timedelta
import json
import openpyxl
import tempfile
import os
from .models import InventoryMaster, InventoryDaily

@login_required(login_url='/login/')
def inventory_list_page(request):
    """库存清单页面渲染"""
    return render(request, 'inventory_list.html', {
        'active_nav': 'inventory_list',
    })

@csrf_exempt
def upload_inventory_file(request):
    """
    外部API：上传Excel文件并更新库存数据
    表头顺序：工厂名称, 产品名称, MOSKU, 颜色, 尺码, 库位, 库存数量, 可用数量
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': '仅支持POST请求'}, status=405)

    if 'file' not in request.FILES:
        return JsonResponse({'success': False, 'message': '未找到文件'}, status=400)

    excel_file = request.FILES['file']
    if not (excel_file.name.endswith('.xlsx') or excel_file.name.endswith('.xls')):
        return JsonResponse({'success': False, 'message': '不支持的文件格式，请上传 .xlsx 或 .xls'}, status=400)

    try:
        # 保存到临时文件进行处理
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(excel_file.name)[1]) as tmp:
            for chunk in excel_file.chunks():
                tmp.write(chunk)
            tmp_path = tmp.name

        wb = openpyxl.load_workbook(tmp_path, data_only=True)
        ws = wb.active
        
        rows = list(ws.rows)
        if len(rows) < 2:
            return JsonResponse({'success': False, 'message': '文件内容为空'}, status=400)

        # 映射表头列索引 (从0开始)
        # 顺序：工厂名称, 产品名称, MOSKU, 颜色, 尺码, 库位, 库存数量, 可用数量
        header_map = {
            'factory_name': 0,
            'product_name': 1,
            'mosku': 2,
            'color': 3,
            'size': 4,
            'location': 5,
            'stock_qty': 6,
            'available_qty': 7
        }

        success_count = 0
        error_count = 0
        errors = []
        today = timezone.now().date()

        from django.db import transaction
        with transaction.atomic():
            for i, row in enumerate(rows[1:], start=2):
                try:
                    # 获取各列值
                    factory_name = str(row[header_map['factory_name']].value or '').strip()
                    product_name = str(row[header_map['product_name']].value or '').strip()
                    mosku = str(row[header_map['mosku']].value or '').strip()
                    color = str(row[header_map['color']].value or '').strip()
                    size = str(row[header_map['size']].value or '').strip()
                    location = str(row[header_map['location']].value or '').strip()
                    
                    try:
                        stock_qty = int(row[header_map['stock_qty']].value or 0)
                        available_qty = int(row[header_map['available_qty']].value or 0)
                    except (ValueError, TypeError):
                        stock_qty = 0
                        available_qty = 0

                    if not mosku:
                        error_count += 1
                        errors.append(f"第 {i} 行: MOSKU 不能为空")
                        continue

                    # 1. 更新或创建 InventoryMaster (库存主表)
                    master, created = InventoryMaster.objects.update_or_create(
                        mosku=mosku,
                        defaults={
                            'factory_name': factory_name,
                            'product_name': product_name,
                            'color': color,
                            'size': size,
                            'location': location,
                            'stock_qty': stock_qty,
                            'is_active': True
                        }
                    )

                    # 2. 更新或创建 InventoryDaily (每日快照)
                    InventoryDaily.objects.update_or_create(
                        inventory=master,
                        date=today,
                        defaults={
                            'available_qty': available_qty
                        }
                    )
                    
                    success_count += 1
                except Exception as row_err:
                    error_count += 1
                    errors.append(f"第 {i} 行: {str(row_err)}")

        # 删除临时文件
        os.unlink(tmp_path)

        return JsonResponse({
            'success': True,
            'message': f'处理完成。成功: {success_count}, 失败: {error_count}',
            'data': {
                'success_count': success_count,
                'error_count': error_count,
                'errors': errors[:10]  # 只返回前10个错误
            }
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({'success': False, 'message': f'文件处理失败: {str(e)}'}, status=500)

@login_required
def get_inventory_list_api(request):
    """
    获取库存列表（带分页、排序、筛选）
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': '只支持POST请求'}, status=405)

    try:
        data = json.loads(request.body)
        
        # 分页参数
        page = int(data.get('page', 1))
        page_size = int(data.get('page_size', 20))
        page_size = min(page_size, 100)

        # 排序参数
        sort_field = data.get('sort_field', 'mosku')
        sort_order = data.get('sort_order', 'asc')
        valid_sort_fields = ['mosku', 'product_name', 'factory_name', 'supplier_name']
        if sort_field not in valid_sort_fields:
            sort_field = 'mosku'

        # 构建查询条件
        query_filter = Q()

        # MOSKU筛选
        mosku = data.get('mosku', '').strip()
        if mosku:
            query_filter &= Q(mosku__icontains=mosku)

        # 产品名称筛选
        product_name = data.get('product_name', '').strip()
        if product_name:
            query_filter &= Q(product_name__icontains=product_name)

        # 工厂名称筛选
        factory_name = data.get('factory_name', '').strip()
        if factory_name:
            query_filter &= Q(factory_name__icontains=factory_name)

        # 供应商名称筛选
        supplier_name = data.get('supplier_name', '').strip()
        if supplier_name:
            query_filter &= Q(supplier_name__icontains=supplier_name)

        # 构建排序
        order_by_prefix = '-' if sort_order == 'desc' else ''
        ordering = f'{order_by_prefix}{sort_field}'

        # 查询数据
        queryset = InventoryMaster.objects.filter(query_filter)

        # 关联查询最新的InventoryDaily
        newest_daily = InventoryDaily.objects.filter(
            inventory=OuterRef('pk')
        ).order_by('-date')

        queryset = queryset.annotate(
            latest_available_qty=Subquery(newest_daily.values('available_qty')[:1]),
            latest_date=Subquery(newest_daily.values('date')[:1])
        ).order_by(ordering)

        # 分页
        total = queryset.count()
        paginator = Paginator(queryset, page_size)
        try:
            items_page = paginator.page(page)
        except PageNotAnInteger:
            items_page = paginator.page(1)
        except EmptyPage:
            items_page = paginator.page(paginator.num_pages)

        # 获取当前页的MOSKU列表
        page_moskus = [item.mosku for item in items_page]
        
        # 获取最近15天的库存记录 (需要15天来计算14天的变化量)
        today = timezone.now().date()
        date_15_days_ago = today - timedelta(days=15)
        
        daily_records = InventoryDaily.objects.filter(
            inventory_id__in=page_moskus,
            date__gte=date_15_days_ago
        ).values('inventory_id', 'date', 'available_qty')
        
        # 将记录按MOSKU和日期组织
        daily_map = {mosku: {} for mosku in page_moskus}
        for record in daily_records:
            daily_map[record['inventory_id']][record['date']] = record['available_qty']

        # 组装数据
        items_data = []
        for item in items_page:
            # 获取最近15天的库存历史 (0为今天, 1为昨天...)
            qty_history = []
            for i in range(15):
                d = today - timedelta(days=i)
                # 如果没有记录，假设库存为0
                qty_history.append(daily_map[item.mosku].get(d, 0))
            
            # 计算最近14天的每日消耗量 (Prev - Curr)
            # changes[0] 是今天的消耗 (昨天库存 - 今天库存)
            # changes[1] 是昨天的消耗 (前天库存 - 昨天库存)
            daily_changes = []
            for i in range(14):
                # qty_history[i] 是 Day i (较新)
                # qty_history[i+1] 是 Day i+1 (较旧)
                # 消耗量 = 旧 - 新
                change = qty_history[i+1] - qty_history[i]
                daily_changes.append(change)

            # 趋势图数据：最近7天的消耗量 (从旧到新)
            # daily_changes[0] 是今天，daily_changes[6] 是6天前
            trend_data = daily_changes[0:7][::-1]
            
            # 计算3日消耗同比 (近3日总消耗 vs 3-6日总消耗)
            # 近3日: 0, 1, 2
            # 前3日: 3, 4, 5
            sum_3_curr = sum(daily_changes[0:3])
            sum_3_prev = sum(daily_changes[3:6])
            
            diff_3_pct = 0
            if sum_3_prev != 0:
                diff_3_pct = (sum_3_curr - sum_3_prev) / abs(sum_3_prev) * 100
            elif sum_3_curr != 0:
                diff_3_pct = 100
                
            # 计算7日消耗同比 (近7日总消耗 vs 7-14日总消耗)
            # 近7日: 0..6
            # 前7日: 7..13
            sum_7_curr = sum(daily_changes[0:7])
            sum_7_prev = sum(daily_changes[7:14])
            
            diff_7_pct = 0
            if sum_7_prev != 0:
                diff_7_pct = (sum_7_curr - sum_7_prev) / abs(sum_7_prev) * 100
            elif sum_7_curr != 0:
                diff_7_pct = 100

            items_data.append({
                'mosku': item.mosku,
                'product_name': item.product_name,
                'factory_name': item.factory_name,
                'supplier_name': item.supplier_name,
                'color': item.color,
                'size': item.size,
                'location': item.location,
                'is_active': item.is_active,
                'stock_qty': item.stock_qty,  # 备货库存
                'available_qty': item.latest_available_qty if item.latest_available_qty is not None else 0,  # 最新库存
                'latest_date': item.latest_date.strftime('%Y-%m-%d') if item.latest_date else '-',  # 更新日期
                'trend_data': trend_data,
                'diff_3_pct': round(diff_3_pct, 1),
                'diff_7_pct': round(diff_7_pct, 1),
            })

        return JsonResponse({
            'success': True,
            'data': {
                'items': items_data,
                'total': total,
                'page': items_page.number,
                'page_size': page_size,
                'total_pages': paginator.num_pages,
            }
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({
            'success': False,
            'message': f'服务器错误: {str(e)}'
        }, status=500)
