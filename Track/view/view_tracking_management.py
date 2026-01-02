# Track/view/view_tracking_management.py
import threading
import time
import os
import tempfile
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.core.paginator import Paginator
from django.db.models import Q, Count, Avg
from django.utils import timezone
from datetime import datetime, timedelta
import openpyxl
from openpyxl.utils.exceptions import InvalidFileException
import json
from Track.models import Tracking, Courier, TrackingDetail, Factory
from Api.track.track_api import register_tracking, get_tracking_updates


# 主页视图
@login_required
def tracking_management(request):
    """物流追踪管理主页"""
    # 权限检查：只有permission包含555或gyl的用户可以访问
    user_permission = request.user.permission or ''
    permission_list = [p.strip() for p in user_permission.split(',') if p.strip()]

    if not any(p in permission_list for p in ['555', 'gyl']):
        from django.shortcuts import redirect
        return redirect('general:main')

    return render(request, 'tracking_management.html', {})


def get_date_range_from_option(option):
    """
    获取日期范围，支持'unlimited'选项
    返回 (start_date, end_date) 或 (None, None) 当选择不限时
    """
    if option == 'unlimited':
        return None, None

    # 标准日期范围映射
    days_map = {
        'today': 0,
        'yesterday': 1,
        'last7days': 7,
        'last30days': 30
    }

    days = days_map.get(option, 30)
    end_date = timezone.now().date()
    start_date = end_date - timedelta(days=days)

    return start_date, end_date


@login_required
def get_factories(request):
    """获取工厂列表"""
    try:
        factories = Factory.objects.all().values('id', 'name').order_by('id')
        return JsonResponse({
            'success': True,
            'data': list(factories)
        })
    except Exception as e:
        print(f"获取工厂列表失败: {str(e)}")
        return JsonResponse({
            'success': False,
            'message': f'获取失败: {str(e)}'
        }, status=500)


# 获取物流商列表
@login_required
def get_couriers(request):
    """获取物流商列表（用于筛选）"""
    try:
        couriers = Courier.objects.all().values('code', 'name_cn', 'name_en')
        return JsonResponse({'success': True, 'data': list(couriers)})
    except Exception as e:
        print(f"获取物流商列表失败: {str(e)}")
        return JsonResponse({
            'success': False,
            'message': f'获取失败: {str(e)}'
        }, status=500)


@login_required
@require_http_methods(["POST"])
@login_required
@require_http_methods(["POST"])
def tracking_list(request):
    """
    运单列表（筛选 + 分页）
    新增：未揽收天数筛选和排除未揽收天数筛选（互斥）
    """
    try:
        data = json.loads(request.body) if request.body else {}

        # 优化的查询
        queryset = Tracking.objects.select_related('courier', 'factory').only(
            'track_no', 'courier__code', 'courier__name_cn',
            'transit_status', 'last_update_time', 'stay_days',
            'order_time', 'platform', 'order_id', 'ops_group', 'ops_name',
            'ship_to', 'factory_id', 'factory__name'
        )

        # 构建查询条件
        filters = Q()

        # 1. 日期范围筛选
        date_range = data.get('date_range', 'last30days')
        if date_range == 'custom':
            start_date = data.get('start_date')
            end_date = data.get('end_date')
            if start_date:
                filters &= Q(order_time__gte=start_date)
            if end_date:
                filters &= Q(order_time__lte=end_date)
        else:
            days = {
                'today': 0,
                'yesterday': 1,
                'last7days': 7,
                'last30days': 30
            }.get(date_range, 30)
            start_date = timezone.now() - timedelta(days=days)
            filters &= Q(order_time__gte=start_date)

        # 2. 多值模糊查询筛选（支持空格/逗号分隔）
        tracking_numbers = data.get('tracking_number', [])
        order_ids = data.get('order_id', [])

        # 处理运单号（数组形式）
        if tracking_numbers and isinstance(tracking_numbers, list) and len(tracking_numbers) > 0:
            if len(tracking_numbers) == 1:
                filters &= Q(track_no__icontains=tracking_numbers[0])
            else:
                tracking_q = Q()
                for tn in tracking_numbers:
                    if tn:  # 确保不为空
                        tracking_q |= Q(track_no__icontains=tn)
                filters &= tracking_q
        elif isinstance(tracking_numbers, str) and tracking_numbers:
            # 兼容旧的字符串格式（如果前端没传数组）
            filters &= Q(track_no__icontains=tracking_numbers)

        # 处理订单号（数组形式）
        if order_ids and isinstance(order_ids, list) and len(order_ids) > 0:
            if len(order_ids) == 1:
                filters &= Q(order_id__icontains=order_ids[0])
            else:
                order_q = Q()
                for oid in order_ids:
                    if oid:  # 确保不为空
                        order_q |= Q(order_id__icontains=oid)
                filters &= order_q
        elif isinstance(order_ids, str) and order_ids:
            # 兼容旧的字符串格式
            filters &= Q(order_id__icontains=order_ids)

        # 3. 下拉框筛选
        if data.get('logistics_method'):
            filters &= Q(courier__code=data['logistics_method'])
        if data.get('factory'):
            filters &= Q(factory_id=data['factory'])
        if data.get('status'):
            filters &= Q(transit_status=data['status'])

        # 4. 运营分组/人员筛选（冲突处理：分组优先）
        ops_group = data.get('ops_group', '').strip()
        ops_name = data.get('ops_name', '').strip()
        if ops_group:
            filters &= Q(ops_group=ops_group)
        elif ops_name:
            filters &= Q(ops_name=ops_name)

        # === 5. 新增：未揽收天数筛选（互斥）===
        uncollected_statuses = ['INIT', 'NO_RECORD', 'INFO_RECEIVED']

        # 参数A：只显示未揽收超过X天的
        uncollected_days = data.get('uncollected_days')
        if uncollected_days:
            hours = int(uncollected_days) * 24
            filters &= Q(transit_status__in=uncollected_statuses)
            filters &= Q(last_update_time__lte=timezone.now() - timedelta(hours=hours))
            # 排除已签收和已过期
            filters &= ~Q(transit_status__in=['DELIVERED', 'EXPIRED'])

        # 参数B：排除未揽收，显示其他状态超过X天的
        exclude_uncollected_days = data.get('exclude_uncollected_days')
        if exclude_uncollected_days:
            hours = int(exclude_uncollected_days) * 24
            filters &= ~Q(transit_status__in=uncollected_statuses)
            filters &= Q(last_update_time__lte=timezone.now() - timedelta(hours=hours))
            # 排除已签收和已过期
            filters &= ~Q(transit_status__in=['DELIVERED', 'EXPIRED'])

        # 6. 轨迹更新情况筛选（原有的）
        tracking_update = data.get('tracking_update')
        if tracking_update:
            if tracking_update == 'today':
                filters &= Q(last_update_time__date=timezone.now().date())
            elif tracking_update == 'stale_3d':
                filters &= Q(last_update_time__lte=timezone.now() - timedelta(hours=72))
                filters &= ~Q(transit_status='DELIVERED')
            elif tracking_update == 'stale_5d':
                filters &= Q(last_update_time__lte=timezone.now() - timedelta(hours=120))
                filters &= ~Q(transit_status='DELIVERED')

        # 应用筛选条件
        queryset = queryset.filter(filters)

        # 分页
        page = int(data.get('page', 1))
        page_size = int(data.get('page_size', 20))
        paginator = Paginator(queryset, page_size)

        try:
            page_obj = paginator.page(page)
        except:
            page_obj = paginator.page(1)

        # 序列化数据（包含 stale_hours 字段）
        orders = []
        now = datetime.now()

        for tracking in page_obj.object_list:
            # 计算停滞小时数（排除已签收和已过期的订单）
            stale_hours = 0
            if tracking.last_update_time and tracking.transit_status not in ['DELIVERED', 'EXPIRED']:
                try:
                    last_time = tracking.last_update_time.replace(tzinfo=None)
                    hours_diff = (now - last_time).total_seconds() / 3600
                    stale_hours = int(hours_diff)
                except Exception as e:
                    stale_hours = 0

            orders.append({
                'track_no': tracking.track_no,
                'courier': tracking.courier.name_cn if tracking.courier else '-',
                'transit_status': tracking.transit_status or 'UNKNOWN',
                'order_time': tracking.order_time.isoformat() if tracking.order_time else None,
                'last_event_time': tracking.last_update_time.isoformat() if tracking.last_update_time else None,
                'stale_hours': stale_hours,
                'ship_to': tracking.ship_to or '-',
                'platform': tracking.platform or 'other',
                'order_id': tracking.order_id or '-',
                'ops_group': tracking.ops_group or '-',
                'ops_name': tracking.ops_name or '-',
                'factory_id': tracking.factory_id,
                'factory_name': tracking.factory.name if tracking.factory else '',
            })

        return JsonResponse({
            'success': True,
            'data': {
                'orders': orders,
                'total': paginator.count,
                'total_pages': paginator.num_pages
            }
        })

    except Exception as e:
        print(f"获取运单列表失败: {str(e)}")
        import traceback
        traceback.print_exc()
        return JsonResponse({
            'success': False,
            'message': f'获取失败: {str(e)}'
        }, status=500)


# 轨迹详情API（保持不变）
@login_required
@require_http_methods(["GET"])
def tracking_details(request):
    """获取单票轨迹详情"""
    try:
        track_no = request.GET.get('track_no')
        if not track_no:
            return JsonResponse({
                'success': False,
                'message': '缺少运单号参数'
            }, status=400)

        tracking = Tracking.objects.filter(track_no=track_no).first()
        if not tracking:
            return JsonResponse({
                'success': False,
                'message': '运单不存在'
            }, status=404)

        # 获取轨迹详情（按时间倒序）
        details = TrackingDetail.objects.filter(
            tracking=tracking
        ).order_by('-event_time')

        data = []
        for detail in details:
            data.append({
                'event_time': detail.event_time.isoformat() if detail.event_time else None,
                'address': detail.address or '',
                'event_detail': detail.event_detail or '',
                'transit_sub_status': detail.transit_sub_status or ''
            })

        return JsonResponse({
            'success': True,
            'data': data
        })

    except Exception as e:
        print(f"获取轨迹详情失败: {str(e)}")
        return JsonResponse({
            'success': False,
            'message': f'获取失败: {str(e)}'
        }, status=500)


# 统计看板API（保持不变）
@login_required
def tracking_stats(request):
    """获取统计看板数据"""
    try:
        today = timezone.now().date()
        now = timezone.now()  # 用于计算小时差

        # 今日签收
        delivered_today = Tracking.objects.filter(
            delivered_time__date=today
        ).count()

        # 在途中
        in_transit = Tracking.objects.filter(
            transit_status__in=['IN_TRANSIT', 'WAITING_DELIVERY']
        ).count()

        # 🔴 修改：超过3天无更新（72小时），只排除已签收
        stale_3_days = Tracking.objects.filter(
            last_update_time__lte=now - timedelta(hours=72)  # 3天 = 72小时
        ).exclude(
            transit_status='DELIVERED'  # 只排除已签收
        ).count()

        # 平均运输时效（仅计算已签收的）
        avg_transit = Tracking.objects.filter(
            delivered_time__isnull=False
        ).aggregate(
            avg_days=Avg('transit_days')
        )['avg_days'] or 0

        return JsonResponse({
            'success': True,
            'data': {
                'delivered_today': delivered_today,
                'in_transit': in_transit,
                'stale_3_days': stale_3_days,
                'avg_transit_days': round(avg_transit, 1)
            }
        })

    except Exception as e:
        print(f"获取统计数据失败: {str(e)}")
        return JsonResponse({
            'success': False,
            'message': f'获取失败: {str(e)}'
        }, status=500)


# 在 view_tracking_management.py 文件中，找到 export_tracking_excel 函数

@login_required
@require_http_methods(["POST"])
def export_tracking_excel(request):
    """导出运单数据到Excel（修复筛选逻辑不一致问题）"""
    try:
        from openpyxl.styles import Font, PatternFill, Alignment
        from openpyxl.utils import get_column_letter

        data = json.loads(request.body) if request.body else {}

        # 状态码翻译映射
        STATUS_TRANSLATION = {
            'INIT': '待追踪',
            'NO_RECORD': '无信息',
            'INFO_RECEIVED': '等待揽收',
            'IN_TRANSIT': '在途中',
            'WAITING_DELIVERY': '派送中',
            'DELIVERY_FAILED': '派送失败',
            'ABNORMAL': '异常',
            'DELIVERED': '已签收',
            'EXPIRED': '已过期',
            'PRE_TRANSIT': '待追踪',
            'UNKNOWN': '未知'
        }

        # 使用与 tracking_list API 完全相同的筛选逻辑
        filters = Q()

        # 1. 日期范围筛选
        date_range = data.get('date_range', 'last30days')
        if date_range == 'custom':
            start_date = data.get('start_date')
            end_date = data.get('end_date')
            if start_date:
                filters &= Q(order_time__gte=start_date)
            if end_date:
                filters &= Q(order_time__lte=end_date)
        else:
            days = {
                'today': 0,
                'yesterday': 1,
                'last7days': 7,
                'last30days': 30
            }.get(date_range, 30)
            start_date = timezone.now() - timedelta(days=days)
            filters &= Q(order_time__gte=start_date)

        # 2. 多值模糊查询筛选（支持空格/逗号分隔）
        tracking_numbers = data.get('tracking_number', [])
        order_ids = data.get('order_id', [])

        # 处理运单号（数组形式）
        if tracking_numbers and isinstance(tracking_numbers, list) and len(tracking_numbers) > 0:
            if len(tracking_numbers) == 1:
                filters &= Q(track_no__icontains=tracking_numbers[0])
            else:
                tracking_q = Q()
                for tn in tracking_numbers:
                    if tn:  # 确保不为空
                        tracking_q |= Q(track_no__icontains=tn)
                filters &= tracking_q
        elif isinstance(tracking_numbers, str) and tracking_numbers:
            # 兼容旧的字符串格式（如果前端没传数组）
            filters &= Q(track_no__icontains=tracking_numbers)

        # 处理订单号（数组形式）
        if order_ids and isinstance(order_ids, list) and len(order_ids) > 0:
            if len(order_ids) == 1:
                filters &= Q(order_id__icontains=order_ids[0])
            else:
                order_q = Q()
                for oid in order_ids:
                    if oid:  # 确保不为空
                        order_q |= Q(order_id__icontains=oid)
                filters &= order_q
        elif isinstance(order_ids, str) and order_ids:
            # 兼容旧的字符串格式
            filters &= Q(order_id__icontains=order_ids)

        # 3. 下拉框筛选
        if data.get('logistics_method'):
            filters &= Q(courier__code=data['logistics_method'])
        if data.get('factory'):
            filters &= Q(factory_id=data['factory'])
        if data.get('status'):
            filters &= Q(transit_status=data['status'])

        # 4. 运营分组/人员筛选（冲突处理：分组优先）
        ops_group = data.get('ops_group', '').strip()
        ops_name = data.get('ops_name', '').strip()
        if ops_group:
            filters &= Q(ops_group=ops_group)
        elif ops_name:
            filters &= Q(ops_name=ops_name)

        # 5. 轨迹更新筛选（使用 last_update_time 而非 stay_days）
        tracking_update = data.get('tracking_update')
        if tracking_update:
            if tracking_update == 'today':
                # 今日有更新
                filters &= Q(last_update_time__date=timezone.now().date())
            elif tracking_update == 'stale_3d':
                # 超过3天无更新 = 72小时
                filters &= Q(last_update_time__lte=timezone.now() - timedelta(hours=72))
                filters &= ~Q(transit_status='DELIVERED')  # 排除已签收
            elif tracking_update == 'stale_5d':
                # 超过5天无更新 = 120小时
                filters &= Q(last_update_time__lte=timezone.now() - timedelta(hours=120))
                filters &= ~Q(transit_status='DELIVERED')  # 排除已签收

        # 查询所有字段（添加 factory__name）
        queryset = Tracking.objects.filter(filters).select_related('courier', 'factory')

        # 创建Excel
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "物流追踪"

        # 表头：工厂列放在第二列
        headers = [
            '运单号', '工厂', '物流商', '当前状态', '目的地', '最新轨迹时间', '停滞天数',
            '下单时间', '平台', '订单号', '运营分组', '运营姓名'
        ]

        for col, header in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col)
            cell.value = header
            cell.font = Font(bold=True)
            cell.fill = PatternFill(start_color="366092", end_color="366092", fill_type="solid")
            cell.alignment = Alignment(horizontal="center")

        # 数据行：工厂列在第二列，状态翻译为中文
        for row, tracking in enumerate(queryset, 2):
            # 翻译状态码为中文
            status_display = STATUS_TRANSLATION.get(tracking.transit_status, tracking.transit_status or '未知')

            ws.cell(row=row, column=1, value=tracking.track_no)
            ws.cell(row=row, column=2, value=tracking.factory.name if tracking.factory else '-')
            ws.cell(row=row, column=3, value=tracking.courier.name_cn if tracking.courier else '-')
            ws.cell(row=row, column=4, value=status_display)  # 使用翻译后的中文状态
            ws.cell(row=row, column=5, value=tracking.ship_to or '-')
            ws.cell(row=row, column=6,
                    value=tracking.last_update_time.strftime('%Y-%m-%d %H:%M') if tracking.last_update_time else '-')
            ws.cell(row=row, column=7, value=tracking.stay_days or 0)
            ws.cell(row=row, column=8, value=tracking.order_time.strftime('%Y-%m-%d') if tracking.order_time else '-')
            ws.cell(row=row, column=9, value=tracking.platform or 'other')
            ws.cell(row=row, column=10, value=tracking.order_id or '-')
            ws.cell(row=row, column=11, value=tracking.ops_group or '-')
            ws.cell(row=row, column=12, value=tracking.ops_name or '-')

        # 列宽调整
        column_widths = [20, 15, 15, 12, 12, 18, 12, 12, 10, 20, 12, 12]
        for col, width in enumerate(column_widths, 1):
            ws.column_dimensions[get_column_letter(col)].width = width

        # 生成响应
        response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        response['Content-Disposition'] = 'attachment; filename="物流追踪_{}.xlsx"'.format(
            timezone.now().strftime('%Y%m%d_%H%M%S')
        )
        wb.save(response)
        return response

    except Exception as e:
        print(f"导出Excel失败: {str(e)}")
        import traceback
        traceback.print_exc()
        return JsonResponse({
            'success': False,
            'message': f'导出失败: {str(e)}'
        }, status=500)


@login_required
@require_http_methods(["POST"])
def import_tracking_excel(request):
    """从Excel导入物流单号（支持工厂关联 + 后台异步更新轨迹）"""

    # ==================== 🔴 新增：权限检查开始 ====================
    user_permission = request.user.permission or ''
    print(user_permission)
    permission_list = [p.strip() for p in user_permission.split(',') if p.strip()]

    if 'gyl_admin' not in permission_list:
        return JsonResponse({
            'success': False,
            'message': '权限不足：需要 供应链管理员 权限才能导入物流单号'
        }, status=403)
    # ==================== 权限检查结束 ====================

    if 'file' not in request.FILES:
        return JsonResponse({'success': False, 'message': '未上传文件'}, status=400)

    factory_id = request.POST.get('factory_id')
    if not factory_id:
        return JsonResponse({'success': False, 'message': '未选择工厂'}, status=400)

    try:
        factory = Factory.objects.get(id=factory_id)
    except Factory.DoesNotExist:
        return JsonResponse({'success': False, 'message': '工厂不存在'}, status=400)

    file = request.FILES['file']

    # 验证文件扩展名
    allowed_extensions = ['.xlsx', '.xls']
    file_ext = os.path.splitext(file.name)[1].lower()
    if file_ext not in allowed_extensions:
        return JsonResponse({
            'success': False,
            'message': '不支持的文件格式，请上传.xlsx或.xls文件'
        }, status=400)

    # 临时保存文件
    with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as tmp_file:
        for chunk in file.chunks():
            tmp_file.write(chunk)
        tmp_file_path = tmp_file.name

    try:
        # ==================== 🔴 修改：自动识别物流单号列开始 ====================
        workbook = openpyxl.load_workbook(tmp_file_path, data_only=True)
        worksheet = workbook.active

        print(f"正在解析Excel文件: {file.name}")
        print(f"工作表名称: {worksheet.title}")
        print(f"最大行数: {worksheet.max_row}, 最大列数: {worksheet.max_column}")

        # 自动查找"物流单号"列
        target_col = None
        header_row = list(worksheet[1])

        print(f"表头行内容: {[cell.value for cell in header_row]}")

        # 方法1：精确匹配"物流单号"
        for idx, cell in enumerate(worksheet[1], 1):
            cell_value = str(cell.value).strip() if cell.value else ''
            if cell_value == '物流单号':
                target_col = idx
                print(f"✅ 精确匹配成功：找到'物流单号'在第 {target_col} 列")
                break

        # 方法2：模糊匹配（如果没找到精确匹配）
        if not target_col:
            print("未找到精确匹配，尝试模糊匹配...")
            for idx, cell in enumerate(worksheet[1], 1):
                cell_value = str(cell.value).lower().strip() if cell.value else ''
                if '单号' in cell_value or 'tracking' in cell_value:
                    target_col = idx
                    actual_value = str(cell.value).strip()
                    print(f"✅ 模糊匹配成功：找到'{actual_value}'在第 {target_col} 列")
                    break

        if not target_col:
            workbook.close()
            print("❌ 未找到物流单号列！")
            return JsonResponse({
                'success': False,
                'message': 'Excel格式错误：未找到"物流单号"列，请确保表头包含这四个字'
            }, status=400)
        # ==================== 自动识别列结束 ====================

        # 读取该列所有有效单号
        trackings = []
        seen = set()

        for row_idx in range(2, worksheet.max_row + 1):
            cell_value = worksheet.cell(row=row_idx, column=target_col).value
            if cell_value:
                track_no = str(cell_value).strip()
                if len(track_no) > 5 and track_no not in seen:
                    trackings.append({'track_no': track_no})
                    seen.add(track_no)
                elif len(track_no) > 0 and len(track_no) <= 5:
                    print(f"⚠️ 跳过第 {row_idx} 行：单号'{track_no}'长度不足6位")

        workbook.close()

        if not trackings:
            return JsonResponse({
                'success': False,
                'message': '未找到有效的物流单号（要求长度大于5）'
            }, status=400)

        # 批量处理结果初始化
        results = {
            'total_to_process': len(trackings),
            'imported': 0,
            'duplicates_local': 0,
            'duplicates_api': 0,
            'errors': 0,
            'details': []
        }

        # 记录需要后续更新的新单号
        track_nos_to_update = []

        # 区分本地重复和需要调用API的单号
        track_no_list = [item['track_no'] for item in trackings]
        existing_trackings_set = set(
            Tracking.objects.filter(
                track_no__in=track_no_list
            ).values_list('track_no', flat=True)
        )

        track_no_for_api = []
        for item in trackings:
            track_no = item['track_no']
            if track_no in existing_trackings_set:
                # ✅ 立即更新（性能影响很小，因为只有重复时才执行）
                Tracking.objects.filter(track_no=track_no).update(factory=factory)
                results['duplicates_local'] += 1
                results['details'].append({
                    'track_no': track_no,
                    'status': 'duplicate_local',
                    'message': f'运单号已存在，工厂已更新为: {factory.name}'
                })
            else:
                track_no_for_api.append(track_no)

        # 分批处理Track123 API调用
        new_tracking_objects = []
        courier_cache = {}

        if track_no_for_api:
            batch_size = 100
            total_batches = (len(track_no_for_api) + batch_size - 1) // batch_size

            for batch_idx in range(total_batches):
                start_idx = batch_idx * batch_size
                end_idx = min(start_idx + batch_size, len(track_no_for_api))
                current_batch = track_no_for_api[start_idx:end_idx]

                print(f"处理批次 {batch_idx + 1}/{total_batches}，单号数量: {len(current_batch)}")

                api_response = register_tracking(current_batch)
                time.sleep(1)

                if api_response.get('code') == '00000':
                    data = api_response.get('data', {})
                    accepted = data.get('accepted', [])
                    rejected = data.get('rejected', [])

                    # 预处理当前批次的物流商
                    courier_codes_to_check = set()
                    for item in accepted + rejected:
                        if item.get('courierCode'):
                            courier_codes_to_check.add(item['courierCode'])

                    # 批量获取/创建物流商
                    for code in courier_codes_to_check:
                        if code not in courier_cache:
                            courier, _ = Courier.objects.get_or_create(
                                code=code,
                                defaults={'name_cn': code.upper(), 'name_en': code.upper()}
                            )
                            courier_cache[code] = courier

                    # 处理 Accepted
                    for accepted_item in accepted:
                        track_no = accepted_item['trackNo']
                        courier_code = accepted_item.get('courierCode')
                        courier = courier_cache.get(courier_code)

                        new_tracking_objects.append(
                            Tracking(
                                track_no=track_no,
                                courier=courier,
                                factory=factory,
                                transit_status='INIT',
                                order_time=timezone.now(),
                            )
                        )
                        track_nos_to_update.append(track_no)

                        results['imported'] += 1
                        results['details'].append({
                            'track_no': track_no,
                            'status': 'success',
                            'message': f'导入成功，物流商: {courier_code}'
                        })

                    # 处理 Rejected
                    for rejected_item in rejected:
                        track_no = rejected_item['trackNo']
                        error_code = rejected_item.get('error', {}).get('code')
                        error_msg = rejected_item.get('error', {}).get('msg', '未知API错误')

                        if error_code == 'A0400':
                            courier_code = rejected_item.get('courierCode')
                            courier = courier_cache.get(courier_code)

                            new_tracking_objects.append(
                                Tracking(
                                    track_no=track_no,
                                    courier=courier,
                                    factory=factory,
                                    transit_status='PRE_TRANSIT',
                                    order_time=timezone.now(),
                                )
                            )
                            track_nos_to_update.append(track_no)

                            results['imported'] += 1
                            results['duplicates_api'] += 1
                            results['details'].append({
                                'track_no': track_no,
                                'status': 'duplicate_api',
                                'message': f'运单号已存在于Track123，已创建本地记录，物流商: {courier_code}'
                            })
                        else:
                            results['errors'] += 1
                            results['details'].append({
                                'track_no': track_no,
                                'status': 'error',
                                'message': f'注册失败: {error_msg}'
                            })
                else:
                    # API调用失败
                    error_msg = api_response.get('msg', 'Track123 API系统错误')
                    results['errors'] += len(current_batch)
                    for track_no in current_batch:
                        results['details'].append({
                            'track_no': track_no,
                            'status': 'error',
                            'message': f'批量注册失败: {error_msg}'
                        })

                # 批次间延迟
                if batch_idx < total_batches - 1:
                    time.sleep(0.5)

            # 所有批次完成后，批量创建记录
            if new_tracking_objects:
                # 使用 ignore_conflicts 静默跳过已存在记录，避免 IntegrityError
                Tracking.objects.bulk_create(new_tracking_objects, ignore_conflicts=True)

                # 批量更新所有相关记录的工厂字段（覆盖新建和已存在的记录）
                track_nos_in_batch = [obj.track_no for obj in new_tracking_objects]
                Tracking.objects.filter(track_no__in=track_nos_in_batch).update(factory=factory)

                print(f"批量创建了 {len(new_tracking_objects)} 条Tracking记录")

        # 启动后台线程更新轨迹
        if track_nos_to_update:
            print(f"启动后台任务更新 {len(track_nos_to_update)} 个新单号的轨迹")
            thread = threading.Thread(
                target=async_update_tracking_batch,
                args=(track_nos_to_update,),
                daemon=True
            )
            thread.start()

        return JsonResponse({
            'success': True,
            'data': results,
            'async_update': {
                'enabled': True,
                'total_to_update': len(track_nos_to_update),
                'message': f'后台正在更新轨迹，预计5-10分钟后查看结果'
            }
        })

    except Exception as e:
        print(f"导入物流单号时发生错误: {str(e)}")
        import traceback
        traceback.print_exc()
        return JsonResponse({
            'success': False,
            'message': f'服务器错误: {str(e)}'
        }, status=500)
    finally:
        # 删除临时文件
        try:
            os.unlink(tmp_file_path)
        except:
            pass


def async_update_tracking_batch(track_nos):
    """后台批量更新轨迹（与 sync_tracking_update_v2.py 类似）"""
    print(f"[后台任务] 开始更新 {len(track_nos)} 个新单号的轨迹...")

    batch_size = 100
    total_batches = (len(track_nos) + batch_size - 1) // batch_size

    for batch_idx in range(total_batches):
        start_idx = batch_idx * batch_size
        end_idx = min(start_idx + batch_size, len(track_nos))
        current_batch = track_nos[start_idx:end_idx]

        try:
            print(f"[后台任务] 处理批次 {batch_idx + 1}/{total_batches}，单号数量: {len(current_batch)}")

            # 调用API批量更新
            result = get_tracking_updates(current_batch)

            if result.get('success'):
                success_count = result['data']['success_count']
                fail_count = result['data']['fail_count']
                print(f"[后台任务] 批次 {batch_idx + 1} 完成：成功 {success_count}，失败 {fail_count}")
            else:
                print(f"[后台任务] 批次 {batch_idx + 1} 失败: {result.get('message', '未知错误')}")

            # 批次间延迟，避免API限制
            if batch_idx < total_batches - 1:
                time.sleep(1)

        except Exception as e:
            print(f"[后台任务] 批次 {batch_idx + 1} 异常: {str(e)}")
            import traceback
            traceback.print_exc()

    print(f"[后台任务] 所有批次处理完成！")


@login_required
@require_http_methods(["POST"])
def refresh_tracking(request):
    """批量刷新运单轨迹（真实API调用）"""
    try:
        data = json.loads(request.body) if request.body else {}
        track_nos = data.get('track_nos', [])

        if not track_nos:
            return JsonResponse({
                'success': False,
                'message': '未选择运单号'
            }, status=400)

        # 调用完整的更新函数
        from Api.track.track_api import get_tracking_updates
        result = get_tracking_updates(track_nos)

        if result['success']:
            return JsonResponse({
                'success': True,
                'message': f"成功刷新 {result['data']['success_count']} 条轨迹",
                'data': result['data']
            })
        else:
            return JsonResponse({
                'success': False,
                'message': result.get('message', '刷新失败')
            }, status=500)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({
            'success': False,
            'message': f'服务器错误: {str(e)}'
        }, status=500)
