# Track/view/view_external_procurement.py
import json
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.core.paginator import Paginator
from django.db.models import Q
from track.models import ExternalProcurementProduct


@login_required
def external_procurement_management(request):
    """外采产品管理主页"""
    # 权限检查：只有permission包含555或557的用户可以访问
    user_permission = request.user.permission or ''
    permission_list = [p.strip() for p in user_permission.split(',') if p.strip()]

    if not any(p in permission_list for p in ['555', '557']):
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
            page_size = int(request.GET.get('page_size', 100))

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
