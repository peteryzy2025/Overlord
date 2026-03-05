# -*- coding: utf-8 -*-
"""
Temu 订单管理视图
"""
import json
from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from django.db.models import Q, Sum, F
from django.core.paginator import Paginator

from temu.models import TemuOrder, TemuOrderItem, LingXingTemuShop


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
        order_id = data.get('order_id', '')
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
        
        # 订单号筛选
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
            
            # DIVI 相关信息（占位，后续接入实际数据）
            is_exported_to_divi = False  # 后续从关联表获取
            divi_order_status = None
            divi_logistics_method = ''
            divi_tracking_number = ''
            
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
