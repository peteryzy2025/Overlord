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
from track.models import Tracking, Courier, TrackingDetail, Factory
from api.track.track_api import register_tracking, get_tracking_updates, parse_datetime


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

    return render(request, 'tracking_management.html', {
        'active_page': 'tracking-management',
        'active_nav': 'tracking-management'
    })


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


def is_all_filter_token(value):
    token = str(value or '').strip().lower()
    return token in {'', 'all', '*', 'any', '__all__', '全部', '不限'}


def parse_multi_filter_values(raw):
    """
    将筛选参数统一转换为字符串列表，兼容:
    - 单值字符串
    - 逗号分隔字符串
    - 数组
    并过滤"全部/不限"类占位值。
    """
    if raw is None:
        return []

    source = raw if isinstance(raw, list) else [raw]
    values = []
    for item in source:
        if item is None:
            continue
        if isinstance(item, list):
            for sub in item:
                text = str(sub or '').strip()
                if text:
                    values.append(text)
            continue
        text = str(item).strip()
        if not text:
            continue
        if ',' in text:
            values.extend([part.strip() for part in text.split(',') if part.strip()])
        else:
            values.append(text)

    if any(is_all_filter_token(v) for v in values):
        return []

    result = []
    seen = set()
    for val in values:
        if is_all_filter_token(val):
            continue
        if val not in seen:
            seen.add(val)
            result.append(val)
    return result


@login_required
@require_http_methods(["POST"])
def tracking_list(request):
    """获取运单列表（支持分页、筛选）"""
    try:
        data = json.loads(request.body)

        # 基础筛选参数
        date_range = data.get('date_range', 'last30days')
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        tracking_numbers = data.get('tracking_number', [])
        order_ids = data.get('order_id', [])
        logistics_methods = parse_multi_filter_values(data.get('logistics_method'))
        factories = parse_multi_filter_values(data.get('factory'))
        status = data.get('status')
        ops_groups = parse_multi_filter_values(data.get('ops_group'))
        ops_names = parse_multi_filter_values(data.get('ops_name'))
        tracking_update = data.get('tracking_update')
        uncollected_days = data.get('uncollected_days')
        exclude_uncollected_days = data.get('exclude_uncollected_days')
        cancel_status = data.get('cancel_status', 'all')

        # 分页参数
        page = int(data.get('page', 1))
        page_size = int(data.get('page_size', 20))

        # 构建查询
        queryset = Tracking.objects.all()

        # 取消状态筛选
        if cancel_status == 'cancelled':
            queryset = queryset.filter(cancel_bool=True)
        elif cancel_status == 'active':
            queryset = queryset.filter(cancel_bool=False)
        # else: 'all' - 不做筛选

        # 日期范围筛选
        if date_range != 'custom':
            start_date, end_date = get_date_range_from_option(date_range)

        if start_date and end_date:
            queryset = queryset.filter(create_time__date__gte=start_date, create_time__date__lte=end_date)

        # 运单号筛选
        if tracking_numbers:
            q_objects = Q()
            for tn in tracking_numbers:
                q_objects |= Q(track_no__icontains=tn)
            queryset = queryset.filter(q_objects)

        # 订单号筛选
        if order_ids:
            q_objects = Q()
            for oid in order_ids:
                q_objects |= Q(order_id__icontains=oid)
            queryset = queryset.filter(q_objects)

        # 物流商筛选
        if logistics_methods:
            queryset = queryset.filter(courier__code__in=logistics_methods)

        # 工厂筛选
        if factories:
            queryset = queryset.filter(factory_id__in=factories)

        # 状态筛选
        if status:
            queryset = queryset.filter(transit_status=status)

        # 运营分组筛选（精确匹配）
        if ops_groups:
            queryset = queryset.filter(ops_group__in=ops_groups)

        # 运营姓名筛选（精确匹配）
        if ops_names:
            queryset = queryset.filter(ops_name__in=ops_names)

        # 轨迹更新情况筛选
        if tracking_update:
            now = timezone.now()
            if tracking_update == 'today':
                today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
                queryset = queryset.filter(last_update_time__gte=today_start)
            elif tracking_update == 'stale_3d':
                stale_date = now - timedelta(days=3)
                queryset = queryset.filter(last_update_time__lt=stale_date)
            elif tracking_update == 'stale_5d':
                stale_date = now - timedelta(days=5)
                queryset = queryset.filter(last_update_time__lt=stale_date)

        # 未揽收天数筛选（新增）
        if uncollected_days:
            try:
                days = int(uncollected_days)
                cutoff = timezone.now() - timedelta(days=days)
                queryset = queryset.filter(
                    Q(transit_status='INFO_RECEIVED') | Q(transit_status='INIT') | Q(transit_status='NO_RECORD'),
                    order_time__lt=cutoff
                )
            except ValueError:
                pass

        # 排除未揽收后超过X天（新增）
        if exclude_uncollected_days:
            try:
                days = int(exclude_uncollected_days)
                cutoff = timezone.now() - timedelta(days=days)
                queryset = queryset.filter(
                    ~Q(transit_status__in=['INFO_RECEIVED', 'INIT', 'NO_RECORD']),
                    last_update_time__lt=cutoff
                )
            except ValueError:
                pass

        # 计算总数
        total = queryset.count()

        # 分页
        paginator = Paginator(queryset.order_by('-create_time'), page_size)
        page_obj = paginator.get_page(page)

        # 序列化数据
        orders = []
        for tracking in page_obj:
            order = {
                'track_no': tracking.track_no,
                'courier': tracking.courier.name_cn if tracking.courier else None,
                'transit_status': tracking.transit_status,
                'order_time': tracking.order_time.isoformat() if tracking.order_time else None,
                'delivered_time': tracking.delivered_time.isoformat() if tracking.delivered_time else None,
                'last_event_time': tracking.last_update_time.isoformat() if tracking.last_update_time else None,
                'stale_hours': tracking.stay_days * 24 if tracking.stay_days else 0,
                'order_id': tracking.order_id,
                'ops_group': tracking.ops_group,
                'ops_name': tracking.ops_name,
                'cancel_bool': tracking.cancel_bool,
                'factory_id': tracking.factory_id,
                'factory_name': tracking.factory.name if tracking.factory else None,
                'remark': tracking.remark
            }
            orders.append(order)

        return JsonResponse({
            'success': True,
            'data': {
                'orders': orders,
                'total': total,
                'page': page,
                'page_size': page_size,
                'total_pages': paginator.num_pages
            }
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'服务器错误: {str(e)}'
        }, status=500)


@login_required
def tracking_details(request):
    """获取运单轨迹详情"""
    try:
        track_no = request.GET.get('track_no')
        if not track_no:
            return JsonResponse({
                'success': False,
                'message': '缺少运单号参数'
            })

        tracking = Tracking.objects.filter(track_no=track_no).first()
        if not tracking:
            return JsonResponse({
                'success': False,
                'message': '运单不存在'
            })

        details = TrackingDetail.objects.filter(tracking=tracking).order_by('-event_time')

        data = []
        for detail in details:
            data.append({
                'event_time': detail.event_time.isoformat() if detail.event_time else None,
                'address': detail.address,
                'event_detail': detail.event_detail
            })

        return JsonResponse({
            'success': True,
            'data': data
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'服务器错误: {str(e)}'
        }, status=500)


@login_required
@require_http_methods(["POST"])
def tracking_stats(request):
    """获取运单统计信息"""
    try:
        data = json.loads(request.body)

        # 获取筛选条件（与列表接口一致）
        date_range = data.get('date_range', 'last30days')
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        status = data.get('status')
        tracking_numbers = data.get('tracking_number', [])
        logistics_methods = parse_multi_filter_values(data.get('logistics_method'))
        ops_groups = parse_multi_filter_values(data.get('ops_group'))
        ops_names = parse_multi_filter_values(data.get('ops_name'))
        tracking_update = data.get('tracking_update')
        uncollected_days = data.get('uncollected_days')
        exclude_uncollected_days = data.get('exclude_uncollected_days')

        # 构建基础查询（只筛选时间范围，不筛选状态）
        queryset = Tracking.objects.all()

        # 日期范围筛选
        if date_range != 'custom':
            start_date, end_date = get_date_range_from_option(date_range)

        if start_date and end_date:
            queryset = queryset.filter(create_time__date__gte=start_date, create_time__date__lte=end_date)

        # 运单号筛选
        if tracking_numbers:
            q_objects = Q()
            for tn in tracking_numbers:
                q_objects |= Q(track_no__icontains=tn)
            queryset = queryset.filter(q_objects)

        # 物流商筛选
        if logistics_methods:
            queryset = queryset.filter(courier__code__in=logistics_methods)

        # 运营分组筛选
        if ops_groups:
            queryset = queryset.filter(ops_group__in=ops_groups)

        # 运营姓名筛选
        if ops_names:
            queryset = queryset.filter(ops_name__in=ops_names)

        # 状态筛选
        if status:
            queryset = queryset.filter(transit_status=status)

        # 轨迹更新筛选
        if tracking_update:
            now = timezone.now()
            if tracking_update == 'today':
                today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
                queryset = queryset.filter(last_update_time__gte=today_start)
            elif tracking_update == 'stale_3d':
                stale_date = now - timedelta(days=3)
                queryset = queryset.filter(last_update_time__lt=stale_date)
            elif tracking_update == 'stale_5d':
                stale_date = now - timedelta(days=5)
                queryset = queryset.filter(last_update_time__lt=stale_date)

        # 未揽收天数筛选
        if uncollected_days:
            try:
                days = int(uncollected_days)
                cutoff = timezone.now() - timedelta(days=days)
                queryset = queryset.filter(
                    Q(transit_status__in=['INFO_RECEIVED', 'INIT', 'NO_RECORD']),
                    order_time__lt=cutoff
                )
            except ValueError:
                pass

        # 排除未揽收后超过X天
        if exclude_uncollected_days:
            try:
                days = int(exclude_uncollected_days)
                cutoff = timezone.now() - timedelta(days=days)
                queryset = queryset.filter(
                    ~Q(transit_status__in=['INFO_RECEIVED', 'INIT', 'NO_RECORD']),
                    last_update_time__lt=cutoff
                )
            except ValueError:
                pass

        # 统计计算（基于筛选后的结果）
        now = timezone.now()

        # 在途中（不包含取消的）
        in_transit_count = queryset.filter(
            transit_status='IN_TRANSIT',
            cancel_bool=False
        ).count()

        # 超过3天无更新（包含取消和未取消的）
        stale_3d_date = now - timedelta(days=3)
        stale_3d_total = queryset.filter(
            last_update_time__lt=stale_3d_date
        ).count()
        stale_3d_cancelled = queryset.filter(
            last_update_time__lt=stale_3d_date,
            cancel_bool=True
        ).count()
        stale_3d_normal = stale_3d_total - stale_3d_cancelled
        stale_3d_display = f"{stale_3d_normal} / {stale_3d_total}" if stale_3d_cancelled > 0 else str(stale_3d_total)

        # 超过5天无更新（包含取消和未取消的）
        stale_5d_date = now - timedelta(days=5)
        stale_5d_total = queryset.filter(
            last_update_time__lt=stale_5d_date
        ).count()
        stale_5d_cancelled = queryset.filter(
            last_update_time__lt=stale_5d_date,
            cancel_bool=True
        ).count()
        stale_5d_normal = stale_5d_total - stale_5d_cancelled
        stale_5d_display = f"{stale_5d_normal} / {stale_5d_total}" if stale_5d_cancelled > 0 else str(stale_5d_total)

        # 平均运输时效（已签收且非取消的）
        delivered_queryset = queryset.filter(
            transit_status='DELIVERED',
            delivered_days__isnull=False,
            cancel_bool=False
        )
        avg_days = delivered_queryset.aggregate(avg_days=Avg('delivered_days'))['avg_days']
        avg_transit_days = round(avg_days, 1) if avg_days else 0

        return JsonResponse({
            'success': True,
            'data': {
                'in_transit': in_transit_count,
                'stale_3_days': stale_3d_display,
                'stale_5_days': stale_5d_display,
                'avg_transit_days': avg_transit_days
            }
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'服务器错误: {str(e)}'
        }, status=500)


@login_required
def import_tracking_excel(request):
    """导入物流单号Excel"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': '仅支持POST请求'})

    try:
        if 'file' not in request.FILES:
            return JsonResponse({'success': False, 'message': '未找到上传的文件'})

        excel_file = request.FILES['file']
        factory_id = request.POST.get('factory_id')

        if not factory_id:
            return JsonResponse({'success': False, 'message': '请选择工厂'})

        # 验证文件类型
        if not excel_file.name.endswith(('.xlsx', '.xls')):
            return JsonResponse({'success': False, 'message': '请上传Excel文件(.xlsx或.xls)'})

        # 读取Excel文件
        wb = openpyxl.load_workbook(excel_file, data_only=True)
        ws = wb.active

        # 查找"物流单号"列
        header_row = list(ws.iter_rows(min_row=1, max_row=1, values_only=True))[0]
        tracking_col = None

        for idx, cell in enumerate(header_row):
            if cell and ('物流单号' in str(cell) or '运单号' in str(cell) or 'Tracking' in str(cell)):
                tracking_col = idx
                break

        # 如果没找到标题，默认使用第3列(C列)
        if tracking_col is None:
            tracking_col = 2  # 0-based index

        # 提取运单号
        tracking_numbers = []
        for row in ws.iter_rows(min_row=2, values_only=True):
            if len(row) > tracking_col and row[tracking_col]:
                track_no = str(row[tracking_col]).strip()
                if track_no and track_no.lower() not in ['nan', 'none', '']:
                    tracking_numbers.append(track_no)

        if not tracking_numbers:
            return JsonResponse({'success': False, 'message': '未找到有效的运单号'})

        # 去重
        tracking_numbers = list(set(tracking_numbers))

        # 批量注册到Track123
        results = {
            'success_count': 0,
            'fail_count': 0,
            'failed_numbers': []
        }

        for track_no in tracking_numbers:
            try:
                success, message = register_tracking(track_no, factory_id=factory_id)
                if success:
                    results['success_count'] += 1
                else:
                    results['fail_count'] += 1
                    results['failed_numbers'].append({'track_no': track_no, 'reason': message})
            except Exception as e:
                results['fail_count'] += 1
                results['failed_numbers'].append({'track_no': track_no, 'reason': str(e)})

        return JsonResponse({
            'success': True,
            'message': f'导入完成: 成功{results["success_count"]}条, 失败{results["fail_count"]}条',
            'data': results
        })

    except InvalidFileException:
        return JsonResponse({'success': False, 'message': '无效的Excel文件格式'})
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'导入失败: {str(e)}'})


@login_required
def refresh_tracking(request):
    """刷新运单轨迹"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': '仅支持POST请求'})

    try:
        data = json.loads(request.body)
        track_nos = data.get('track_nos', [])

        if not track_nos:
            return JsonResponse({'success': False, 'message': '未提供运单号'})

        # 限制批量刷新数量
        if len(track_nos) > 100:
            return JsonResponse({'success': False, 'message': '单次最多刷新100个运单'})

        # 获取轨迹更新
        success_count = 0
        failed_count = 0

        for track_no in track_nos:
            try:
                success, message = get_tracking_updates(track_no)
                if success:
                    success_count += 1
                else:
                    failed_count += 1
            except Exception as e:
                failed_count += 1

        return JsonResponse({
            'success': True,
            'message': f'刷新完成: 成功{success_count}条, 失败{failed_count}条'
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'刷新失败: {str(e)}'
        })


@login_required
def export_tracking_excel(request):
    """导出运单数据到Excel"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': '仅支持POST请求'})

    try:
        # 使用 tracking_list 相同的逻辑获取数据
        data = json.loads(request.body)

        # 获取筛选条件（与列表接口一致）
        date_range = data.get('date_range', 'last30days')
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        tracking_numbers = data.get('tracking_number', [])
        logistics_methods = parse_multi_filter_values(data.get('logistics_method'))
        factories = parse_multi_filter_values(data.get('factory'))
        status = data.get('status')
        ops_groups = parse_multi_filter_values(data.get('ops_group'))
        ops_names = parse_multi_filter_values(data.get('ops_name'))
        tracking_update = data.get('tracking_update')
        uncollected_days = data.get('uncollected_days')
        exclude_uncollected_days = data.get('exclude_uncollected_days')
        cancel_status = data.get('cancel_status', 'all')

        # 构建查询
        queryset = Tracking.objects.all()

        # 取消状态筛选
        if cancel_status == 'cancelled':
            queryset = queryset.filter(cancel_bool=True)
        elif cancel_status == 'active':
            queryset = queryset.filter(cancel_bool=False)

        # 日期范围筛选
        if date_range != 'custom':
            start_date, end_date = get_date_range_from_option(date_range)

        if start_date and end_date:
            queryset = queryset.filter(create_time__date__gte=start_date, create_time__date__lte=end_date)

        # 运单号筛选
        if tracking_numbers:
            q_objects = Q()
            for tn in tracking_numbers:
                q_objects |= Q(track_no__icontains=tn)
            queryset = queryset.filter(q_objects)

        # 物流商筛选
        if logistics_methods:
            queryset = queryset.filter(courier__code__in=logistics_methods)

        # 工厂筛选
        if factories:
            queryset = queryset.filter(factory_id__in=factories)

        # 状态筛选
        if status:
            queryset = queryset.filter(transit_status=status)

        # 运营分组筛选
        if ops_groups:
            queryset = queryset.filter(ops_group__in=ops_groups)

        # 运营姓名筛选
        if ops_names:
            queryset = queryset.filter(ops_name__in=ops_names)

        # 轨迹更新筛选
        if tracking_update:
            now = timezone.now()
            if tracking_update == 'today':
                today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
                queryset = queryset.filter(last_update_time__gte=today_start)
            elif tracking_update == 'stale_3d':
                stale_date = now - timedelta(days=3)
                queryset = queryset.filter(last_update_time__lt=stale_date)
            elif tracking_update == 'stale_5d':
                stale_date = now - timedelta(days=5)
                queryset = queryset.filter(last_update_time__lt=stale_date)

        # 未揽收天数筛选
        if uncollected_days:
            try:
                days = int(uncollected_days)
                cutoff = timezone.now() - timedelta(days=days)
                queryset = queryset.filter(
                    Q(transit_status__in=['INFO_RECEIVED', 'INIT', 'NO_RECORD']),
                    order_time__lt=cutoff
                )
            except ValueError:
                pass

        # 排除未揽收后超过X天
        if exclude_uncollected_days:
            try:
                days = int(exclude_uncollected_days)
                cutoff = timezone.now() - timedelta(days=days)
                queryset = queryset.filter(
                    ~Q(transit_status__in=['INFO_RECEIVED', 'INIT', 'NO_RECORD']),
                    last_update_time__lt=cutoff
                )
            except ValueError:
                pass

        # 限制导出数量
        MAX_EXPORT = 10000
        total_count = queryset.count()
        if total_count > MAX_EXPORT:
            return JsonResponse({
                'success': False,
                'message': f'导出数据过多(>{MAX_EXPORT}条)，请缩小筛选范围'
            })

        # 创建Excel
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "物流追踪"

        # 设置表头
        headers = [
            '运单号', '物流商', '当前状态', '订单号', '平台',
            '运营分组', '运营姓名', '工厂', '下单时间', '签收时间',
            '最新轨迹时间', '停滞天数', '运输天数', '总签收天数', '发货地', '收货地', '备注'
        ]
        ws.append(headers)

        # 状态映射
        status_map = {
            'INIT': '待追踪',
            'NO_RECORD': '无信息',
            'INFO_RECEIVED': '等待揽收',
            'IN_TRANSIT': '在途中',
            'WAITING_DELIVERY': '派送中',
            'DELIVERY_FAILED': '派送失败',
            'ABNORMAL': '异常',
            'DELIVERED': '已签收',
            'EXPIRED': '已过期'
        }

        # 写入数据
        for tracking in queryset.order_by('-create_time')[:MAX_EXPORT]:
            row = [
                tracking.track_no,
                tracking.courier.name_cn if tracking.courier else '',
                status_map.get(tracking.transit_status, tracking.transit_status),
                tracking.order_id or '',
                tracking.platform or '',
                tracking.ops_group or '',
                tracking.ops_name or '',
                tracking.factory.name if tracking.factory else '',
                tracking.order_time.strftime('%Y-%m-%d %H:%M') if tracking.order_time else '',
                tracking.delivered_time.strftime('%Y-%m-%d %H:%M') if tracking.delivered_time else '',
                tracking.last_update_time.strftime('%Y-%m-%d %H:%M') if tracking.last_update_time else '',
                tracking.stay_days or 0,
                tracking.transit_days or 0,
                tracking.delivered_days or 0,
                tracking.ship_from or '',
                tracking.ship_to or '',
                tracking.remark or ''
            ]
            ws.append(row)

        # 调整列宽
        column_widths = [20, 15, 12, 20, 10, 12, 10, 15, 16, 16, 16, 10, 10, 10, 10, 10, 30]
        for i, width in enumerate(column_widths, 1):
            ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = width

        # 保存到内存
        from io import BytesIO
        output = BytesIO()
        wb.save(output)
        output.seek(0)

        # 设置响应头
        filename = f'物流追踪_{timezone.now().strftime("%Y%m%d_%H%M%S")}.xlsx'
        response = HttpResponse(
            output.getvalue(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response['Content-Disposition'] = f'attachment; filename={filename}'

        return response

    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'导出失败: {str(e)}'
        })


@login_required
def get_couriers(request):
    """获取物流商列表"""
    try:
        couriers = Courier.objects.all().values('code', 'name_cn', 'name_en')
        return JsonResponse({
            'success': True,
            'data': list(couriers)
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': str(e)
        })


@login_required
def get_factories(request):
    """获取工厂列表"""
    try:
        factories = Factory.objects.all().values('id', 'name').order_by('name')
        return JsonResponse({
            'success': True,
            'data': list(factories)
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': str(e)
        })


@login_required
@require_http_methods(["POST"])
def toggle_cancel_status(request):
    """切换运单的取消/恢复状态"""
    try:
        data = json.loads(request.body)
        track_no = data.get('track_no')
        action = data.get('action')  # 'cancel' 或 'undo'

        if not track_no:
            return JsonResponse({
                'success': False,
                'message': '缺少运单号'
            })

        tracking = Tracking.objects.filter(track_no=track_no).first()
        if not tracking:
            return JsonResponse({
                'success': False,
                'message': '运单不存在'
            })

        if action == 'cancel':
            tracking.cancel_bool = True
            tracking.save()
            return JsonResponse({
                'success': True,
                'message': '运单已标记为取消'
            })
        elif action == 'undo':
            tracking.cancel_bool = False
            tracking.save()
            return JsonResponse({
                'success': True,
                'message': '运单已恢复'
            })
        else:
            return JsonResponse({
                'success': False,
                'message': '无效的操作类型'
            })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'操作失败: {str(e)}'
        })


@login_required
@require_http_methods(["POST"])
def update_tracking_remark(request):
    """更新运单备注"""
    try:
        data = json.loads(request.body)
        track_no = data.get('track_no')
        remark = data.get('remark', '')

        if not track_no:
            return JsonResponse({
                'success': False,
                'message': '缺少运单号'
            })

        tracking = Tracking.objects.filter(track_no=track_no).first()
        if not tracking:
            return JsonResponse({
                'success': False,
                'message': '运单不存在'
            })

        # 限制备注长度
        if len(remark) > 200:
            return JsonResponse({
                'success': False,
                'message': '备注长度不能超过200字符'
            })

        tracking.remark = remark
        tracking.save()

        return JsonResponse({
            'success': True,
            'message': '备注更新成功'
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'更新失败: {str(e)}'
        })


# 外采产品管理视图
@login_required
def external_procurement_management(request):
    """外采产品管理主页"""
    # 权限检查：只有permission包含555或556的用户可以访问
    user_permission = request.user.permission or ''
    permission_list = [p.strip() for p in user_permission.split(',') if p.strip()]

    if not any(p in permission_list for p in ['555', '556']):
        from django.shortcuts import redirect
        return redirect('general:main')

    # 准备权限信息给前端
    user_permissions_json = json.dumps(permission_list)

    return render(request, 'external_procurement_product_management.html', {
        'user_permissions_json': user_permissions_json,
        'is_admin': True,
        'active_page': 'external-procurement-management',
        'active_nav': 'external-procurement-management'
    })


# ==================== 外采产品管理 API ====================

from track.models import ExternalProcurementProduct


@login_required
def external_procurement_products_api(request):
    """外采产品列表 API（支持分页、筛选）"""
    if request.method == 'GET':
        try:
            # 获取筛选参数
            platform = request.GET.get('platform', '')
            process_type = request.GET.get('process_type', '')
            is_listed = request.GET.get('is_listed', '')
            search = request.GET.get('search', '')
            page = int(request.GET.get('page', 1))
            page_size = int(request.GET.get('page_size', 20))

            # 构建查询
            queryset = ExternalProcurementProduct.objects.all()

            if platform:
                queryset = queryset.filter(platform=platform)
            if process_type:
                queryset = queryset.filter(process_type=process_type)
            if is_listed:
                queryset = queryset.filter(is_listed=(is_listed == 'true'))
            if search:
                queryset = queryset.filter(
                    Q(product_id__icontains=search) |
                    Q(product_name__icontains=search) |
                    Q(color__icontains=search) |
                    Q(size__icontains=search)
                )

            # 分页
            total = queryset.count()
            paginator = Paginator(queryset.order_by('-id'), page_size)
            page_obj = paginator.get_page(page)

            # 序列化数据
            data = []
            for product in page_obj:
                data.append({
                    'id': product.id,
                    'product_id': product.product_id,
                    'product_name': product.product_name,
                    'platform': product.platform,
                    'process_type': product.process_type,
                    'is_listed': product.is_listed,
                    'color': product.color,
                    'size': product.size,
                    'divi_color': product.divi_color,
                    'divi_size': product.divi_size,
                    'min_order_qty': product.min_order_qty,
                    'purchase_unit_origin_price': str(product.purchase_unit_origin_price) if product.purchase_unit_origin_price else None,
                    'purchase_unit_now_price': str(product.purchase_unit_now_price) if product.purchase_unit_now_price else None,
                })

            return JsonResponse({
                'success': True,
                'data': data,
                'total': total,
                'page': page,
                'page_size': page_size,
                'total_pages': paginator.num_pages
            })

        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': f'服务器错误: {str(e)}'
            }, status=500)

    elif request.method == 'POST':
        # 创建新产品
        try:
            data = json.loads(request.body)

            product = ExternalProcurementProduct.objects.create(
                product_id=data.get('product_id'),
                product_name=data.get('product_name'),
                platform=data.get('platform', 'yzg'),
                process_type=data.get('process_type', 'printing'),
                is_listed=data.get('is_listed', False),
                color=data.get('color', ''),
                size=data.get('size', ''),
                divi_color=data.get('divi_color', ''),
                divi_size=data.get('divi_size', ''),
                min_order_qty=data.get('min_order_qty', ''),
                purchase_unit_origin_price=data.get('purchase_unit_origin_price', 0),
                purchase_unit_now_price=data.get('purchase_unit_now_price'),
            )

            return JsonResponse({
                'success': True,
                'message': '产品创建成功',
                'data': {'id': product.id}
            })

        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': f'创建失败: {str(e)}'
            }, status=500)

    return JsonResponse({'success': False, 'message': '不支持的请求方法'}, status=405)


@login_required
def external_procurement_product_detail_api(request, product_id):
    """外采产品详情 API（获取、更新）"""
    try:
        product = ExternalProcurementProduct.objects.filter(id=product_id).first()
        if not product:
            return JsonResponse({
                'success': False,
                'message': '产品不存在'
            }, status=404)

        if request.method == 'GET':
            # 获取详情
            return JsonResponse({
                'success': True,
                'data': {
                    'id': product.id,
                    'product_id': product.product_id,
                    'product_name': product.product_name,
                    'platform': product.platform,
                    'process_type': product.process_type,
                    'is_listed': product.is_listed,
                    'color': product.color,
                    'size': product.size,
                    'divi_color': product.divi_color,
                    'divi_size': product.divi_size,
                    'min_order_qty': product.min_order_qty,
                    'purchase_unit_origin_price': str(product.purchase_unit_origin_price) if product.purchase_unit_origin_price else None,
                    'purchase_unit_now_price': str(product.purchase_unit_now_price) if product.purchase_unit_now_price else None,
                }
            })

        elif request.method == 'PUT':
            # 更新产品
            data = json.loads(request.body)

            product.product_id = data.get('product_id', product.product_id)
            product.product_name = data.get('product_name', product.product_name)
            product.platform = data.get('platform', product.platform)
            product.process_type = data.get('process_type', product.process_type)
            product.is_listed = data.get('is_listed', product.is_listed)
            product.color = data.get('color', product.color)
            product.size = data.get('size', product.size)
            product.divi_color = data.get('divi_color', product.divi_color)
            product.divi_size = data.get('divi_size', product.divi_size)
            product.min_order_qty = data.get('min_order_qty', product.min_order_qty)
            product.purchase_unit_origin_price = data.get('purchase_unit_origin_price', product.purchase_unit_origin_price)
            product.purchase_unit_now_price = data.get('purchase_unit_now_price', product.purchase_unit_now_price)
            product.save()

            return JsonResponse({
                'success': True,
                'message': '产品更新成功'
            })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'操作失败: {str(e)}'
        }, status=500)

    return JsonResponse({'success': False, 'message': '不支持的请求方法'}, status=405)


@login_required
@require_http_methods(["POST"])
def batch_update_products(request):
    """批量更新产品（上架/下架）"""
    try:
        data = json.loads(request.body)
        ids = data.get('ids', [])
        is_listed = data.get('is_listed')

        if not ids:
            return JsonResponse({
                'success': False,
                'message': '未选择产品'
            })

        count = ExternalProcurementProduct.objects.filter(id__in=ids).update(is_listed=is_listed)

        return JsonResponse({
            'success': True,
            'message': f'成功更新 {count} 个产品'
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'批量更新失败: {str(e)}'
        }, status=500)


@login_required
@require_http_methods(["POST"])
def batch_delete_products(request):
    """批量删除产品"""
    try:
        data = json.loads(request.body)
        ids = data.get('ids', [])

        if not ids:
            return JsonResponse({
                'success': False,
                'message': '未选择产品'
            })

        count = ExternalProcurementProduct.objects.filter(id__in=ids).delete()[0]

        return JsonResponse({
            'success': True,
            'message': f'成功删除 {count} 个产品'
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'批量删除失败: {str(e)}'
        }, status=500)
