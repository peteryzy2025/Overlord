# -*- coding: utf-8 -*-
"""
Temu 订单管理视图
"""
import json
from django.shortcuts import render
from django.http import JsonResponse, FileResponse, HttpResponse
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from django.db.models import Q, Sum, F
from django.core.paginator import Paginator

from temu.models import TemuOrder, TemuOrderItem, LingXingTemuShop
import asyncio
from asgiref.sync import async_to_sync
import os
from api.lingxing_p.lingxing_temu import check_temu_order_to_divi, temu_order_to_divi_and_lingxing, refresh_temu_order_by_sn, shipment_order, get_wms_orders_by_order_numbers, refresh_temu_order_by_sn


@login_required
def temu_order_management_page(request):
    """
    Temu 订单管理页面
    """
    context = {
        'active_page': 'temu_orders',
        'active_nav': 'temu_orders',
    }
    return render(request, 'temu_order_management.html', context)


@require_http_methods(["POST"])
def get_temu_orders_list_api(request):
    """
    获取 Temu 订单列表 API
    """
    try:
        data = json.loads(request.body)
        
        # 分页参数
        page = int(data.get('page', 1))
        page_size = int(data.get('page_size', 20))
        
        # 筛选参数
        date_range = data.get('date_range', 'last30days')
        start_date = data.get('start_date', '')
        end_date = data.get('end_date', '')
        operator_id = data.get('operator_id', '')
        group = data.get('group', '')
        platform_order_no = data.get('platform_order_no', '')  # 平台单号
        order_id = data.get('order_id', '')  # 系统单号
        shop_name = data.get('shop_name', '')
        shop_status = data.get('shop_status', '')
        order_status = data.get('order_status', '')
        divi_export = data.get('divi_export', '')
        divi_order_status = data.get('divi_order_status', '')
        
        # 基础查询
        queryset = TemuOrder.objects.select_related('lingxing_shop', 'temu_shop').all()
        
        # 日期筛选
        if date_range == 'custom' and start_date and end_date:
            queryset = queryset.filter(global_purchase_time__date__gte=start_date,
                                       global_purchase_time__date__lte=end_date)
        elif date_range == 'today':
            from datetime import datetime, timedelta
            today = datetime.now().date()
            queryset = queryset.filter(global_purchase_time__date=today)
        elif date_range == 'yesterday':
            from datetime import datetime, timedelta
            yesterday = datetime.now().date() - timedelta(days=1)
            queryset = queryset.filter(global_purchase_time__date=yesterday)
        elif date_range == 'last7days':
            from datetime import datetime, timedelta
            end = datetime.now().date()
            start = end - timedelta(days=6)
            queryset = queryset.filter(global_purchase_time__date__gte=start,
                                       global_purchase_time__date__lte=end)
        elif date_range == 'last30days':
            from datetime import datetime, timedelta
            end = datetime.now().date()
            start = end - timedelta(days=29)
            queryset = queryset.filter(global_purchase_time__date__gte=start,
                                       global_purchase_time__date__lte=end)
        
        # 平台单号筛选（模糊查询）
        if platform_order_no:
            queryset = queryset.filter(reference_no__icontains=platform_order_no)
        
        # 系统单号筛选
        if order_id:
            queryset = queryset.filter(global_order_no__icontains=order_id)
        
        # 店铺名称筛选
        if shop_name:
            queryset = queryset.filter(lingxing_shop__store_name__icontains=shop_name)
        
        # 店铺状态筛选（TemuShop没有status字段，暂时注释掉）
        # if shop_status:
        #     status_list = shop_status.split(',')
        #     queryset = queryset.filter(temu_shop__status__in=status_list)
        
        # 订单状态筛选
        if order_status:
            status_list = [int(s) for s in order_status.split(',') if s.isdigit()]
            if status_list:
                queryset = queryset.filter(status__in=status_list)
        
        # DIVI导单情况筛选
        if divi_export:
            export_list = divi_export.split(',')
            if 'true' in export_list and 'false' not in export_list:
                queryset = queryset.filter(divi_if_order=True)
            elif 'false' in export_list and 'true' not in export_list:
                queryset = queryset.filter(divi_if_order=False)
        
        # DIVI订单状态筛选
        if divi_order_status:
            divi_status_list = [int(s) for s in divi_order_status.split(',') if s.isdigit()]
            if divi_status_list:
                queryset = queryset.filter(divi_order_status__in=divi_status_list)
        
        # 运营人员筛选（TemuShop的ops_id是IntegerField，不是ForeignKey）
        # 同时考虑 order.temu_shop 和 order.lingxing_shop.temu_shop 两种关联方式
        if operator_id:
            operator_list = [int(s) for s in operator_id.split(',') if s.isdigit()]
            if operator_list:
                queryset = queryset.filter(
                    Q(temu_shop__ops_id__in=operator_list) | 
                    Q(lingxing_shop__temu_shop__ops_id__in=operator_list)
                )
        
        # 运营分组筛选（通过User的get_ops_group获取，需要子查询）
        if group:
            from general.models import User
            group_list = group.split(',')
            # 获取该分组下的所有用户ID
            user_ids = []
            for user in User.objects.all():
                user_group = user.get_ops_group()
                if user_group in group_list:
                    user_ids.append(user.id)
            if user_ids:
                queryset = queryset.filter(
                    Q(temu_shop__ops_id__in=user_ids) | 
                    Q(lingxing_shop__temu_shop__ops_id__in=user_ids)
                )
        
        # 排序
        queryset = queryset.order_by('-global_purchase_time')
        
        # 分页
        paginator = Paginator(queryset, page_size)
        total_pages = paginator.num_pages
        total = paginator.count
        
        try:
            page_obj = paginator.page(page)
        except:
            page_obj = paginator.page(1)
        
        # 序列化数据
        orders = []
        for order in page_obj:
            # 获取商品数量
            quantity = TemuOrderItem.objects.filter(order=order).aggregate(
                total=Sum('quantity')
            )['total'] or 0
            
            # 获取店铺信息
            shop_name = order.lingxing_shop.store_name if order.lingxing_shop else '-'
            shop_status = '正常'  # TemuShop没有status字段，默认显示正常
            
            # 获取运营信息（TemuShop的ops_id是IntegerField）
            group_name = ''
            operator_name = ''
            
            # 尝试从 order.temu_shop 获取，如果没有则尝试从 lingxing_shop.temu_shop 获取
            temu_shop = None
            if order.temu_shop:
                temu_shop = order.temu_shop
            elif order.lingxing_shop and order.lingxing_shop.temu_shop:
                temu_shop = order.lingxing_shop.temu_shop
            
            if temu_shop and temu_shop.ops_id:
                from general.models import User
                try:
                    ops_user = User.objects.get(id=temu_shop.ops_id)
                    operator_name = ops_user.first_name or ops_user.username
                    # 获取分组信息
                    group_name = ops_user.get_ops_group() or ''
                except User.DoesNotExist:
                    pass
            
            # DIVI 相关信息
            is_exported_to_divi = order.divi_if_order if order.divi_if_order is not None else False
            divi_order_status = order.divi_order_status
            divi_logistics_method = order.divi_logistics_method or ''
            divi_tracking_number = order.divi_tracking_number or ''
            
            orders.append({
                'global_order_no': order.global_order_no,
                'reference_no': order.reference_no or '-',
                'status': order.status,
                'shop_name': shop_name,
                'shop_status': shop_status,
                'group': group_name,
                'operator_name': operator_name,
                'is_exported_to_divi': is_exported_to_divi,
                'divi_order_status': divi_order_status,
                'divi_logistics_method': divi_logistics_method,
                'divi_tracking_number': divi_tracking_number,
                'tracking_number': order.tracking_number or '',
                'order_tag': order.order_tag or [],
                'quantity': quantity,
                'order_total_amount': str(order.order_total_amount) if order.order_total_amount else '0.00',
                'purchase_time': order.global_purchase_time.strftime('%Y-%m-%d %H:%M') if order.global_purchase_time else '-',
                'delivery_type': order.delivery_type,
                'sid': order.lingxing_shop.sid if order.lingxing_shop else '',
                'divi_shop_id': temu_shop.divi_shop_id if temu_shop else '',
            })
        
        return JsonResponse({
            'success': True,
            'data': {
                'orders': orders,
                'total': total,
                'total_pages': total_pages,
                'page': page,
                'page_size': page_size
            }
        })
        
    except Exception as e:
        import traceback
        return JsonResponse({
            'success': False,
            'message': str(e),
            'detail': traceback.format_exc()
        }, status=500)


@require_http_methods(["POST"])
def update_temu_divi_export_status_api(request):
    """
    更新 DIVI 导单状态 API（占位）
    """
    # 后续实现与 DIVI 系统的状态同步
    return JsonResponse({
        'success': True,
        'message': '状态更新功能开发中'
    })


@require_http_methods(["POST"])
def export_temu_orders_excel(request):
    """
    导出 Temu 订单到 Excel（占位）
    """
    # 后续实现导出功能
    return JsonResponse({
        'success': False,
        'message': '导出功能开发中'
    }, status=501)


@require_http_methods(["POST"])
def download_temu_label_api(request):
    """
    下载Temu面单PDF
    从共享路径读取文件并返回下载
    """
    try:
        data = json.loads(request.body)
        platform_order_no = data.get('platform_order_no', '')
        tracking_number = data.get('tracking_number', '')
        
        if not platform_order_no or not tracking_number:
            return JsonResponse({
                'success': False,
                'message': '缺少平台单号或物流单号'
            }, status=400)
        
        # 构建文件路径（使用双反斜杠）
        base_path = r'\\192.168.110.54\overlord_555\自动化\Temu面单'
        filename = f'{platform_order_no}#{tracking_number}.pdf'
        file_path = os.path.join(base_path, filename)
        
        # 检查文件是否存在
        if not os.path.exists(file_path):
            return JsonResponse({
                'success': False,
                'message': '无面单文件！'
            }, status=404)
        
        # 返回文件下载
        response = FileResponse(
            open(file_path, 'rb'),
            content_type='application/pdf',
            as_attachment=True,
            filename=filename
        )
        return response
        
    except Exception as e:
        import traceback
        return JsonResponse({
            'success': False,
            'message': str(e),
            'detail': traceback.format_exc()
        }, status=500)


@require_http_methods(["POST"])
def refresh_temu_divi_status_api(request):
    """
    批量刷新订单的DIVI状态
    调用 check_temu_order_to_divi 函数查询并更新
    """
    try:
        data = json.loads(request.body)
        order_ids = data.get('order_ids', [])
        
        if not order_ids:
            return JsonResponse({
                'success': False,
                'message': '未提供订单ID列表'
            }, status=400)
        
        results = []
        for sn_no in order_ids:
            try:
                # 先刷新订单数据
                refresh_success = async_to_sync(refresh_temu_order_by_sn)(sn_no)
                if not refresh_success:
                    results.append({
                        'order_id': sn_no,
                        'found_in_divi': False,
                        'status': 'error',
                        'error': '订单数据刷新失败'
                    })
                    continue
                
                # 再调用异步函数查询DIVI状态
                result = async_to_sync(check_temu_order_to_divi)(sn_no)
                
                # 查询订单最新状态
                try:
                    order = TemuOrder.objects.get(global_order_no=sn_no)
                    # 如果状态为5（待发货），执行发货和下载面单
                    if order.status == 5:
                        try:
                            async_to_sync(shipment_order)(sn_no)
                        except Exception as ship_err:
                            print(f"订单 {sn_no} 发货失败: {ship_err}")
                        
                        try:
                            async_to_sync(get_wms_orders_by_order_numbers)(sn_no)
                        except Exception as pdf_err:
                            print(f"订单 {sn_no} 下载面单失败: {pdf_err}")
                except TemuOrder.DoesNotExist:
                    pass
                
                results.append({
                    'order_id': sn_no,
                    'found_in_divi': result,
                    'status': 'success'
                })
            except Exception as e:
                results.append({
                    'order_id': sn_no,
                    'found_in_divi': False,
                    'status': 'error',
                    'error': str(e)
                })
        
        return JsonResponse({
            'success': True,
            'message': f'已处理 {len(results)} 个订单',
            'data': results
        })
        
    except Exception as e:
        import traceback
        return JsonResponse({
            'success': False,
            'message': str(e),
            'detail': traceback.format_exc()
        }, status=500)


@require_http_methods(["POST"])
def temu_order_to_divi_and_lingxing_api(request):
    """
    将Temu订单导单到DIVI并执行领星发货流程
    调用 temu_order_to_divi_and_lingxing 函数
    """
    try:
        data = json.loads(request.body)
        sn_no = data.get('order_id', '')
        
        if not sn_no:
            return JsonResponse({
                'success': False,
                'message': '未提供订单ID'
            }, status=400)
        
        # 调用异步函数执行导单和发货
        async_to_sync(temu_order_to_divi_and_lingxing)(sn_no)
        
        return JsonResponse({
            'success': True,
            'message': f'订单 {sn_no} 导单并发货流程已启动'
        })
        
    except Exception as e:
        import traceback
        return JsonResponse({
            'success': False,
            'message': str(e),
            'detail': traceback.format_exc()
        }, status=500)
