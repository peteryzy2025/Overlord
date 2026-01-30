# General/views_temu_management.py

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST
from general.models import User, OperationalAccount, TemuShop
from django.views.decorators.csrf import csrf_exempt
from django.db import transaction
from django.db.models import Q
import json
import traceback


# Temu店铺管理页面视图
@login_required
def temu_management_view(request):
    """渲染Temu店铺管理页面"""
    return render(request, 'management/temu_shop_management.html')


# 获取运营人员列表API（复用Amazon的，支持platform参数）
@require_GET
@login_required
def get_all_operators_api(request):
    """
    API接口：获取所有运营人员列表
    参数:
      - platform: 平台筛选，可选值: 'Temu'
    返回: [{id: 1, first_name: '张三', group: 'A组'}, ...]
    """
    try:
        platform = request.GET.get('platform', '').strip()

        queryset = User.objects.filter(
            department__icontains='运营部门'
        ).select_related('operational_account')

        if platform == 'Temu':
            queryset = queryset.filter(platform=platform)

        operators = queryset.values(
            'id', 'first_name', 'operational_account__ops_group'
        ).order_by('operational_account__ops_group', 'first_name')

        operators_list = []
        for op in operators:
            operators_list.append({
                'id': op['id'],
                'first_name': op['first_name'] or '-',
                'group': op['operational_account__ops_group'] or '未分组'
            })

        return JsonResponse({
            'success': True,
            'data': operators_list
        })

    except Exception as e:
        print(f"❌ 获取运营人员列表错误: {str(e)}")
        import traceback
        traceback.print_exc()
        return JsonResponse({
            'success': False,
            'error': f'服务器错误: {str(e)}'
        }, status=500)


# 获取运营分组列表API（复用Amazon的）
@require_GET
@login_required
def get_all_ops_groups_api(request):
    """
    API接口：获取所有运营分组列表（支持按平台筛选）
    参数:
        - platform: 可选，平台名称 ('亚马逊' 或 'Temu')
    返回: ['A组', 'B组', 'C组', ...]
    """
    try:
        platform = request.GET.get('platform', '').strip()

        # 基础查询：排除空值
        queryset = OperationalAccount.objects.exclude(
            ops_group__isnull=True
        ).exclude(
            ops_group=''
        )

        # 如果指定了平台，通过关联User进行筛选
        if platform:
            queryset = queryset.filter(user__platform=platform)

        groups = queryset.values_list('ops_group', flat=True).distinct().order_by('ops_group')

        return JsonResponse({
            'success': True,
            'data': list(groups)
        })

    except Exception as e:
        print(f"❌ 获取分组列表错误: {str(e)}")
        import traceback
        traceback.print_exc()
        return JsonResponse({
            'success': False,
            'error': f'服务器错误: {str(e)}'
        }, status=500)


# 获取客户列表API（从TemuShop获取）
@require_GET
@login_required
def get_customers_api(request):
    """
    API接口：获取所有客户列表（从TemuShop.customer去重）
    返回: ['客户A', '客户B', ...]
    """
    try:
        customers = TemuShop.objects.exclude(
            customer__isnull=True
        ).exclude(
            customer=''
        ).values_list('customer', flat=True).distinct().order_by('customer')

        customers_list = list(customers)

        return JsonResponse({
            'success': True,
            'data': customers_list
        })

    except Exception as e:
        print(f"获取客户列表错误: {str(e)}")
        traceback.print_exc()
        return JsonResponse({
            'success': False,
            'error': f'服务器错误: {str(e)}'
        }, status=500)


# 获取Temu店铺列表API（支持分页和筛选）
@require_GET
@login_required
def get_temu_shops_api(request):
    """
    API接口：获取Temu店铺列表（支持分页、多重筛选）
    支持参数:
        - id=xxx（单店铺查询）
        - page, page_size
        - status, operator, ops_group, customer, search
    """
    try:
        # 优先处理指定 ID 查询
        shop_id = request.GET.get('id')
        if shop_id:
            try:
                shop = TemuShop.objects.get(id=int(shop_id))

                # 获取关联的运营信息
                ops_first_name = '-'
                ops_group = '-'
                if shop.ops_id:
                    try:
                        user = User.objects.select_related('operational_account').get(id=shop.ops_id)
                        ops_first_name = user.first_name or '-'
                        if hasattr(user, 'operational_account'):
                            ops_group = user.operational_account.ops_group or '-'
                        ops_role = user.role or '-'
                    except User.DoesNotExist:
                        pass

                shop_dict = {
                    'id': shop.id,
                    'shop_name': shop.shop_name or '-',
                    'shop_account': shop.shop_account or '-',
                    'shop_password': shop.shop_password or '-',
                    'invitation_code': shop.invitation_code or '-',
                    'verification_email': shop.verification_email or '-',
                    'email_password': shop.email_password or '-',
                    'shop_temu_id': shop.shop_temu_id or '-',
                    'compliance_center': shop.compliance_center or '-',
                    'new_principal_info': shop.new_principal_info or '-',
                    'new_manufacturer_info': shop.new_manufacturer_info or '-',
                    'phone_account_holder': shop.phone_account_holder or '-',
                    'phone_current_location': shop.phone_current_location or '-',
                    'shop_nature': shop.shop_nature or '-',
                    'place_of_origin': shop.place_of_origin or '-',
                    'legal_person': shop.legal_person or '-',
                    'customer': shop.customer or '-',
                    'shop_status': shop.shop_status or 1,
                    'ops_id': shop.ops_id,
                    'ops_first_name': ops_first_name,
                    'ops_role': ops_role,
                    'ops_group': ops_group,
                    'divi_shop_id': shop.divi_shop_id or '',
                }

                return JsonResponse({
                    'success': True,
                    'data': [shop_dict],
                    'total': 1,
                    'page': 1,
                    'page_size': 1
                })

            except TemuShop.DoesNotExist:
                return JsonResponse({'success': False, 'error': '店铺不存在'}, status=404)

        # ====== 正常分页 / 筛选逻辑 ======
        page = int(request.GET.get('page', 1))
        page_size = int(request.GET.get('page_size', 10))

        status_filter = request.GET.get('status', '').strip()
        operator_filter = request.GET.get('operator', '').strip()
        ops_group_filter = request.GET.get('ops_group', '').strip()
        customer_filter = request.GET.get('customer', '').strip()
        search_term = request.GET.get('search', '').strip()

        if page < 1: page = 1
        if page_size not in [10, 20, 50, 100, 5000]: page_size = 10

        query = TemuShop.objects.all()

        if status_filter:
            query = query.filter(shop_status=status_filter)
        if operator_filter:
            query = query.filter(ops_id=int(operator_filter))
        if ops_group_filter:
            # 先找到该分组的用户ID列表
            user_ids = OperationalAccount.objects.filter(ops_group=ops_group_filter).values_list('user_id', flat=True)
            query = query.filter(ops_id__in=user_ids)
        if customer_filter:
            query = query.filter(customer=customer_filter)
        if search_term:
            query = query.filter(
                Q(shop_name__icontains=search_term) |
                Q(shop_account__icontains=search_term) |
                Q(shop_temu_id__icontains=search_term)
            )

        total_count = query.count()
        offset = (page - 1) * page_size
        shops = query.order_by('id')[offset:offset + page_size]

        # 批量获取运营信息
        ops_ids = [shop.ops_id for shop in shops if shop.ops_id]
        users_info = {}
        if ops_ids:
            users = User.objects.select_related('operational_account').filter(id__in=ops_ids)
            for user in users:
                group = user.operational_account.ops_group if hasattr(user, 'operational_account') else '-'
                users_info[user.id] = {
                    'first_name': user.first_name or '-',
                    'group': group or '-',
                    'role': user.role or '-'
                }

        shops_data = []
        for shop in shops:
            ops_info = users_info.get(shop.ops_id, {'first_name': '-', 'group': '-'})
            shops_data.append({
                'id': shop.id,
                'shop_name': shop.shop_name or '-',
                'shop_account': shop.shop_account or '-',
                'shop_password': shop.shop_password or '-',
                'invitation_code': shop.invitation_code or '-',
                'verification_email': shop.verification_email or '-',
                'email_password': shop.email_password or '-',
                'shop_temu_id': shop.shop_temu_id or '-',
                'compliance_center': shop.compliance_center or '-',
                'new_principal_info': shop.new_principal_info or '-',
                'new_manufacturer_info': shop.new_manufacturer_info or '-',
                'phone_account_holder': shop.phone_account_holder or '-',
                'phone_current_location': shop.phone_current_location or '-',
                'shop_nature': shop.shop_nature or '-',
                'place_of_origin': shop.place_of_origin or '-',
                'legal_person': shop.legal_person or '-',
                'customer': shop.customer or '-',
                'shop_status': shop.shop_status or 1,
                'ops_id': shop.ops_id,
                'ops_first_name': ops_info['first_name'],
                'ops_role': ops_info['role'],
                'ops_group': ops_info['group'],
                'divi_shop_id': shop.divi_shop_id or '',
            })

        return JsonResponse({
            'success': True,
            'data': shops_data,
            'total': total_count,
            'page': page,
            'page_size': page_size
        })

    except Exception as e:
        print(f"获取Temu店铺数据错误: {str(e)}")
        traceback.print_exc()
        return JsonResponse({
            'success': False,
            'error': f'服务器错误: {str(e)}'
        }, status=500)


@require_POST
@csrf_exempt
@login_required
def create_temu_shop_api(request):
    """
    API接口：创建新Temu店铺
    """
    try:
        data = json.loads(request.body)

        # 验证必填项
        shop_name = data.get('shop_name', '').strip()
        if not shop_name:
            return JsonResponse({
                'success': False,
                'error': '店铺名称不能为空'
            }, status=400)

        # 检查店铺名称是否已存在
        if TemuShop.objects.filter(shop_name=shop_name).exists():
            return JsonResponse({
                'success': False,
                'error': '店铺名称已存在'
            }, status=400)

        # 使用事务确保数据一致性
        with transaction.atomic():
            shop = TemuShop.objects.create(
                # 基本信息
                shop_name=shop_name,
                shop_entity=data.get('shop_entity', ''),
                shop_account=data.get('shop_account', ''),
                shop_password=data.get('shop_password', ''),
                invitation_code=data.get('invitation_code', ''),
                verification_email=data.get('verification_email', ''),
                email_password=data.get('email_password', ''),
                shop_temu_id=data.get('shop_temu_id', ''),
                compliance_center=data.get('compliance_center', ''),
                new_principal_info=data.get('new_principal_info', ''),
                new_manufacturer_info=data.get('new_manufacturer_info', ''),
                phone_account_holder=data.get('phone_account_holder', ''),
                phone_current_location=data.get('phone_current_location', ''),
                shop_nature=data.get('shop_nature', ''),
                place_of_origin=data.get('place_of_origin', ''),
                legal_person=data.get('legal_person', ''),
                customer=data.get('customer', ''),
                shop_status=data.get('shop_status', 1),
                ops_id=data.get('ops') if data.get('ops') else None,
                divi_shop_id=data.get('divi_shop_id') or None,
            )

        return JsonResponse({
            'success': True,
            'message': '店铺创建成功',
            'shop_id': shop.id
        })

    except Exception as e:
        print(f"创建Temu店铺错误: {str(e)}")
        traceback.print_exc()

        return JsonResponse({
            'success': False,
            'error': f'服务器错误: {str(e)}'
        }, status=500)


@require_POST
@csrf_exempt
@login_required
def update_temu_shop_api(request, shop_id):
    """
    通过店铺ID更新Temu店铺信息
    """
    try:
        shop = TemuShop.objects.get(id=shop_id)
    except TemuShop.DoesNotExist:
        return JsonResponse({'success': False, 'error': '店铺不存在'}, status=404)

    try:
        data = json.loads(request.body or '{}')

        # 简单校验
        shop_name = (data.get('shop_name') or '').strip()
        if not shop_name:
            return JsonResponse({'success': False, 'error': '店铺名称不能为空'}, status=400)

        # 可选：检查重名（排除自己）
        if TemuShop.objects.filter(shop_name=shop_name).exclude(id=shop_id).exists():
            return JsonResponse({'success': False, 'error': '店铺名称已存在'}, status=400)

        with transaction.atomic():
            # 基本信息
            shop.shop_name = shop_name
            shop.shop_entity = data.get('shop_entity', '') or ''
            shop.shop_account = data.get('shop_account', '') or ''
            shop.shop_password = data.get('shop_password', '') or ''
            shop.invitation_code = data.get('invitation_code', '') or ''
            shop.verification_email = data.get('verification_email', '') or ''
            shop.email_password = data.get('email_password', '') or ''
            shop.shop_temu_id = data.get('shop_temu_id', '') or ''
            shop.compliance_center = data.get('compliance_center', '') or ''
            shop.new_principal_info = data.get('new_principal_info', '') or ''
            shop.new_manufacturer_info = data.get('new_manufacturer_info', '') or ''
            shop.phone_account_holder = data.get('phone_account_holder', '') or ''
            shop.phone_current_location = data.get('phone_current_location', '') or ''
            shop.shop_nature = data.get('shop_nature', '') or ''
            shop.place_of_origin = data.get('place_of_origin', '') or ''
            shop.legal_person = data.get('legal_person', '') or ''
            shop.customer = data.get('customer', '') or ''
            shop.shop_status = data.get('shop_status', 1) or 1
            shop.ops_id = data.get('ops') or None
            shop.divi_shop_id = data.get('divi_shop_id') or None

            shop.save()

        return JsonResponse({'success': True, 'message': '店铺信息更新成功'})

    except Exception as e:
        print(f"更新Temu店铺错误: {str(e)}")
        traceback.print_exc()
        return JsonResponse({'success': False, 'error': f'服务器错误: {str(e)}'}, status=500)