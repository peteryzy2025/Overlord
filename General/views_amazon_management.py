# General/views_amazon_management.py

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST
from General.models import User, AmazonShop, OperationalAccount
from django.views.decorators.csrf import csrf_exempt
from django.db import transaction
from django.db.models import Q
import json
import traceback


# Amazon店铺管理页面视图
@login_required
def amazon_management_view(request):
    """渲染Amazon店铺管理页面"""
    context = {
        'active_page': 'amazon_management'
    }
    return render(request, 'amazon_shop_management.html', context)


# 获取运营人员列表API（含OperationalAccount分组信息，按分组排序）
@require_GET
@login_required
def get_all_operators_api(request):
    """
    API接口：获取所有运营人员列表（无权限限制）
    参数:
      - platform: 平台筛选，可选值: '亚马逊' 或 'Temu'
      - ops_group: 运营分组名称，可选筛选
    返回: [{id: 1, first_name: '张三', group: 'A组'}, ...]
    """
    try:
        # 获取参数
        platform = request.GET.get('platform', '').strip()
        ops_group_param = request.GET.get('ops_group', '').strip()

        # 基础查询：查询department包含"运营部门"的用户，并关联OperationalAccount
        queryset = User.objects.filter(
            department__icontains='运营部门'
        ).select_related('operational_account')

        # 应用平台筛选
        if platform in ['亚马逊', 'Temu']:
            queryset = queryset.filter(platform=platform)

        # 应用分组筛选（如果提供了ops_group参数）
        if ops_group_param:
            queryset = queryset.filter(
                operational_account__ops_group=ops_group_param
            )

        # 获取所需字段并按分组和姓名排序
        operators = queryset.values(
            'id', 'first_name', 'operational_account__ops_group'
        ).order_by('operational_account__ops_group', 'first_name')

        # 构建结果列表
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
# 获取客户列表API
@require_GET
@login_required
def get_customers_api(request):
    """
    API接口：获取所有客户列表（从AmazonShop.customer去重）
    返回: ['客户A', '客户B', ...]
    """
    try:
        # 从AmazonShop查询customer，去重并排除空值
        customers = AmazonShop.objects.exclude(
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


# 获取Amazon店铺列表API（支持分页和筛选，含 id 精准查询）
@require_GET
@login_required
def get_amazon_shops_api(request):
    """
    API接口：获取Amazon店铺列表（支持分页、多重筛选，或通过 id 精准查询）
    支持参数:
        - id=xxx（优先，单店铺查询）
        - page, page_size
        - status, operator, ops_group, customer, search
        - shop_date_start, shop_date_end（新增：下店日期范围）
        - qu_dao（新增：店铺渠道）
        - backup_email_or_phone（新增：备用联系方式）
        - additional_remark（新增：附加备注）
        - company_name（新增：公司名称）
        - ling_xing_if（新增：领星授权 0/1）
        - browser（新增：浏览器）
        - xunhui_login_account（新增：收款账号）
    """
    try:
        # 优先处理指定 ID 查询
        shop_id = request.GET.get('id')
        if shop_id:
            try:
                shop = AmazonShop.objects.select_related('ops__operational_account').get(id=int(shop_id))

                ops_group = '-'
                ops_role = '-'
                if shop.ops and hasattr(shop.ops, 'operational_account'):
                    ops_group = shop.ops.operational_account.ops_group or '-'
                    ops_role = shop.ops.role or '-'

                shop_dict = {
                    'id': shop.id,
                    'shop_name': shop.shop_name or '-',
                    'amazon_shop_name': shop.amazon_shop_name or '-',
                    'customer': shop.customer or '-',
                    'ops_id': shop.ops.id if shop.ops else None,
                    'ops_first_name': shop.ops.first_name if shop.ops else '-',
                    'ops_role': ops_role,
                    'ops_group': ops_group,
                    'shop_status': shop.shop_status or '-',
                    'shop_date': shop.shop_date.strftime('%Y-%m-%d') if shop.shop_date else '-',
                    'shop_number': shop.shop_number or '',
                    'seller_mark': shop.seller_mark or '-',
                    'qu_dao': shop.qu_dao or '-',
                    'ip_address': shop.ip_address or '-',
                    'browser': shop.browser or '-',
                    'whitelist': shop.whitelist or '-',
                    'email_account': shop.email_account or '-',
                    'email_password': shop.email_password or '-',
                    'shop_password': shop.shop_password or '-',
                    'registered_phone': shop.registered_phone or '-',
                    'backup_email_or_phone': shop.backup_email_or_phone or '-',
                    'voucher_163': shop.voucher_163 or '-',
                    'email_163_account': shop.email_163_account or '-',
                    'ling_xing_if': shop.ling_xing_if or 0,
                    'divi_shop_id': shop.divi_shop_id or '',
                    'credit_card_channel': shop.credit_card_channel or '-',
                    'credit_card_number': shop.credit_card_number or '-',
                    'credit_card_expiry': shop.credit_card_expiry or '-',
                    'credit_card_cvv': shop.credit_card_cvv or '-',
                    'is_consolidated': shop.is_consolidated or '-',
                    'bind_collection': shop.bind_collection or '-',
                    'collection_channel': shop.collection_channel or '-',
                    'xunhui_login_account': shop.xunhui_login_account or '-',
                    'login_password': shop.login_password or '-',
                    'bind_phone': shop.bind_phone or '-',
                    'collection_card_number': shop.collection_card_number or '-',
                    'payment_password': shop.payment_password or '-',
                    'id_number': shop.id_number or '-',
                    'legal_person_phone': shop.legal_person_phone or '-',
                    'company_name': shop.company_name or '-',
                    'license_number': shop.license_number or '-',
                    'business_license_date': shop.business_license_date.strftime(
                        '%Y-%m-%d') if shop.business_license_date else '-',
                    'birth_date': shop.birth_date.strftime('%Y-%m-%d') if shop.birth_date else '-',
                    'id_expiry_date': shop.id_expiry_date or '-',
                    'remark': shop.remark or '-',
                    'additional_remark': shop.additional_remark or '-',
                    'img1': shop.img1 or '',
                }

                return JsonResponse({
                    'success': True,
                    'data': [shop_dict],
                    'total': 1,
                    'page': 1,
                    'page_size': 1
                })

            except AmazonShop.DoesNotExist:
                return JsonResponse({'success': False, 'error': '店铺不存在'}, status=404)

        # ====== 正常分页 / 筛选逻辑 ======
        page = int(request.GET.get('page', 1))
        page_size = int(request.GET.get('page_size', 10))

        status_filter = request.GET.get('status', '').strip()
        operator_filter = request.GET.get('operator', '').strip()
        ops_group_filter = request.GET.get('ops_group', '').strip()
        customer_filter = request.GET.get('customer', '').strip()
        search_term = request.GET.get('search', '').strip()

        # 新增筛选参数
        shop_date_start = request.GET.get('shop_date_start', '').strip()
        shop_date_end = request.GET.get('shop_date_end', '').strip()
        qu_dao = request.GET.get('qu_dao', '').strip()
        backup_email_or_phone = request.GET.get('backup_email_or_phone', '').strip()
        additional_remark = request.GET.get('additional_remark', '').strip()
        company_name = request.GET.get('company_name', '').strip()
        ling_xing_if = request.GET.get('ling_xing_if', '').strip()
        browser = request.GET.get('browser', '').strip()
        xunhui_login_account = request.GET.get('xunhui_login_account', '').strip()

        if page < 1: page = 1
        if page_size not in [10, 20, 50, 100, 5000]: page_size = 10

        query = AmazonShop.objects.select_related('ops').prefetch_related('ops__operational_account')

        # 原有筛选逻辑
        if status_filter:
            query = query.filter(shop_status=status_filter)
        if operator_filter:
            query = query.filter(ops_id=int(operator_filter))
        if ops_group_filter:
            user_ids = OperationalAccount.objects.filter(ops_group=ops_group_filter).values_list('user_id', flat=True)
            query = query.filter(ops_id__in=user_ids)
        if customer_filter:
            query = query.filter(customer=customer_filter)
        if search_term:
            query = query.filter(
                Q(shop_name__icontains=search_term) |
                Q(amazon_shop_name__icontains=search_term)
            )

        # 新增筛选逻辑
        if shop_date_start:
            query = query.filter(shop_date__gte=shop_date_start)
        if shop_date_end:
            query = query.filter(shop_date__lte=shop_date_end)
        if qu_dao:
            query = query.filter(qu_dao__icontains=qu_dao)
        if backup_email_or_phone:
            query = query.filter(backup_email_or_phone__icontains=backup_email_or_phone)
        if additional_remark:
            query = query.filter(additional_remark__icontains=additional_remark)
        if company_name:
            query = query.filter(company_name__icontains=company_name)
        if ling_xing_if in ['0', '1']:
            query = query.filter(ling_xing_if=int(ling_xing_if))
        if browser:
            query = query.filter(browser=browser)
        if xunhui_login_account:
            query = query.filter(
                Q(xunhui_login_account__icontains=xunhui_login_account) |
                Q(collection_card_number__icontains=xunhui_login_account)
            )

        total_count = query.count()
        offset = (page - 1) * page_size
        shops = query.order_by('id')[offset:offset + page_size]

        shops_data = []
        for shop in shops:
            ops_group = '-'
            ops_role = '-'
            if shop.ops:
                try:
                    ops_group = shop.ops.operational_account.ops_group or '-'
                    ops_role = shop.ops.role or '-'
                except OperationalAccount.DoesNotExist:
                    ops_group = '-'
                    ops_role = '-'

            shops_data.append({
                'id': shop.id,
                'shop_name': shop.shop_name or '-',
                'amazon_shop_name': shop.amazon_shop_name or '-',
                'customer': shop.customer or '-',
                'ops_id': shop.ops.id if shop.ops else None,
                'ops_first_name': shop.ops.first_name if shop.ops else '-',
                'ops_role': ops_role,
                'ops_group': ops_group,
                'shop_status': shop.shop_status or '-',
                'shop_date': shop.shop_date.strftime('%Y-%m-%d') if shop.shop_date else '-',
                'shop_number': shop.shop_number or '',
                'seller_mark': shop.seller_mark or '-',
                'qu_dao': shop.qu_dao or '-',
                'ip_address': shop.ip_address or '-',
                'browser': shop.browser or '-',
                'whitelist': shop.whitelist or '-',
                'email_account': shop.email_account or '-',
                'email_password': shop.email_password or '-',
                'shop_password': shop.shop_password or '-',
                'registered_phone': shop.registered_phone or '-',
                'backup_email_or_phone': shop.backup_email_or_phone or '-',
                'voucher_163': shop.voucher_163 or '-',
                'email_163_account': shop.email_163_account or '-',
                'ling_xing_if': shop.ling_xing_if or 0,
                'divi_shop_id': shop.divi_shop_id or '',
                'credit_card_channel': shop.credit_card_channel or '-',
                'credit_card_number': shop.credit_card_number or '-',
                'credit_card_expiry': shop.credit_card_expiry or '-',
                'credit_card_cvv': shop.credit_card_cvv or '-',
                'is_consolidated': shop.is_consolidated or '-',
                'bind_collection': shop.bind_collection or '-',
                'collection_channel': shop.collection_channel or '-',
                'xunhui_login_account': shop.xunhui_login_account or '-',
                'login_password': shop.login_password or '-',
                'bind_phone': shop.bind_phone or '-',
                'collection_card_number': shop.collection_card_number or '-',
                'payment_password': shop.payment_password or '-',
                'id_number': shop.id_number or '-',
                'legal_person_phone': shop.legal_person_phone or '-',
                'company_name': shop.company_name or '-',
                'license_number': shop.license_number or '-',
                'business_license_date': shop.business_license_date.strftime(
                    '%Y-%m-%d') if shop.business_license_date else '-',
                'birth_date': shop.birth_date.strftime('%Y-%m-%d') if shop.birth_date else '-',
                'id_expiry_date': shop.id_expiry_date or '-',
                'remark': shop.remark or '-',
                'additional_remark': shop.additional_remark or '-',
                'img1': shop.img1 or '',
            })

        return JsonResponse({
            'success': True,
            'data': shops_data,
            'total': total_count,
            'page': page,
            'page_size': page_size
        })

    except Exception as e:
        print(f"获取Amazon店铺数据错误: {str(e)}")
        traceback.print_exc()
        return JsonResponse({
            'success': False,
            'error': f'服务器错误: {str(e)}'
        }, status=500)


@require_POST
@csrf_exempt
@login_required
def create_amazon_shop_api(request):
    """
    API接口：创建新Amazon店铺（支持所有字段）
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
        if AmazonShop.objects.filter(shop_name=shop_name).exists():
            return JsonResponse({
                'success': False,
                'error': '店铺名称已存在'
            }, status=400)

        # 使用事务确保数据一致性
        with transaction.atomic():
            shop = AmazonShop.objects.create(
                # 基本信息
                shop_name=shop_name,
                shop_number=data.get('shop_number'),
                amazon_shop_name=data.get('amazon_shop_name', ''),
                customer=data.get('customer', ''),
                ops_id=data.get('ops') if data.get('ops') else None,
                shop_status=data.get('shop_status', '正常'),
                shop_date=data.get('shop_date'),
                qu_dao=data.get('qu_dao', ''),
                seller_mark=data.get('seller_mark', ''),
                whitelist=data.get('whitelist', ''),
                ip_address=data.get('ip_address', ''),
                remark=data.get('remark', ''),
                # 账号信息
                email_account=data.get('email_account', ''),
                email_password=data.get('email_password', ''),
                shop_password=data.get('shop_password', ''),
                backup_email_or_phone=data.get('backup_email_or_phone', ''),
                voucher_163=data.get('voucher_163', ''),
                email_163_account=data.get('email_163_account', ''),
                browser=data.get('browser', ''),
                ling_xing_if=data.get('ling_xing_if', 0),
                divi_shop_id=data.get('divi_shop_id'),
                # 收款信息
                credit_card_channel=data.get('credit_card_channel', ''),
                credit_card_number=data.get('credit_card_number', ''),
                credit_card_expiry=data.get('credit_card_expiry', ''),
                credit_card_cvv=data.get('credit_card_cvv', ''),
                is_consolidated=data.get('is_consolidated', ''),
                bind_collection=data.get('bind_collection', ''),
                collection_channel=data.get('collection_channel', ''),
                xunhui_login_account=data.get('xunhui_login_account', ''),
                login_password=data.get('login_password', ''),
                bind_phone=data.get('bind_phone', ''),
                collection_card_number=data.get('collection_card_number', ''),
                payment_password=data.get('payment_password', ''),
                # 法人信息
                id_number=data.get('id_number', ''),
                legal_person_phone=data.get('legal_person_phone', ''),
                company_name=data.get('company_name', ''),
                license_number=data.get('license_number', ''),
                business_license_date=data.get('business_license_date'),
                birth_date=data.get('birth_date'),
                id_expiry_date=data.get('id_expiry_date', ''),
                additional_remark=data.get('additional_remark', ''),
                # 其他
                img1=data.get('img1', ''),
            )

        return JsonResponse({
            'success': True,
            'message': '店铺创建成功',
            'shop_id': shop.id
        })

    except Exception as e:
        print(f"创建Amazon店铺错误: {str(e)}")
        traceback.print_exc()

        return JsonResponse({
            'success': False,
            'error': f'服务器错误: {str(e)}'
        }, status=500)


@require_POST
@csrf_exempt
@login_required
def update_amazon_shop_api(request, shop_id):
    """
    通过店铺ID更新亚马逊店铺信息
    请求体：与 create 接口相同字段
    """
    try:
        shop = AmazonShop.objects.get(id=shop_id)
    except AmazonShop.DoesNotExist:
        return JsonResponse({'success': False, 'error': '店铺不存在'}, status=404)

    try:
        data = json.loads(request.body or '{}')

        # 简单校验
        shop_name = (data.get('shop_name') or '').strip()
        if not shop_name:
            return JsonResponse({'success': False, 'error': '店铺名称不能为空'}, status=400)

        # 可选：检查重名（排除自己）
        if AmazonShop.objects.filter(shop_name=shop_name).exclude(id=shop_id).exists():
            return JsonResponse({'success': False, 'error': '店铺名称已存在'}, status=400)

        with transaction.atomic():
            # 基本信息
            shop.shop_name = shop_name
            shop.shop_number = data.get('shop_number') or None
            shop.amazon_shop_name = data.get('amazon_shop_name', '') or ''
            shop.customer = data.get('customer', '') or ''
            shop.ops_id = data.get('ops') or None
            shop.shop_status = data.get('shop_status', '正常') or '正常'
            shop.shop_date = data.get('shop_date') or None
            shop.qu_dao = data.get('qu_dao', '') or ''
            shop.seller_mark = data.get('seller_mark', '') or ''
            shop.whitelist = data.get('whitelist', '') or ''
            shop.ip_address = data.get('ip_address', '') or ''
            shop.remark = data.get('remark', '') or ''

            # 账号信息
            shop.email_account = data.get('email_account', '') or ''
            shop.email_password = data.get('email_password', '') or ''
            shop.shop_password = data.get('shop_password', '') or ''
            shop.backup_email_or_phone = data.get('backup_email_or_phone', '') or ''
            shop.voucher_163 = data.get('voucher_163', '') or ''
            shop.email_163_account = data.get('email_163_account', '') or ''
            shop.browser = data.get('browser', '') or ''
            shop.ling_xing_if = data.get('ling_xing_if', 0) or 0
            shop.divi_shop_id = data.get('divi_shop_id') or None

            # 收款信息
            shop.credit_card_channel = data.get('credit_card_channel', '') or ''
            shop.credit_card_number = data.get('credit_card_number', '') or ''
            shop.credit_card_expiry = data.get('credit_card_expiry', '') or ''
            shop.credit_card_cvv = data.get('credit_card_cvv', '') or ''
            shop.is_consolidated = data.get('is_consolidated', '') or ''
            shop.bind_collection = data.get('bind_collection', '') or ''
            shop.collection_channel = data.get('collection_channel', '') or ''
            shop.xunhui_login_account = data.get('xunhui_login_account', '') or ''
            shop.login_password = data.get('login_password', '') or ''
            shop.bind_phone = data.get('bind_phone', '') or ''
            shop.collection_card_number = data.get('collection_card_number', '') or ''
            shop.payment_password = data.get('payment_password', '') or ''

            # 法人信息
            shop.id_number = data.get('id_number', '') or ''
            shop.legal_person_phone = data.get('legal_person_phone', '') or ''
            shop.company_name = data.get('company_name', '') or ''
            shop.license_number = data.get('license_number', '') or ''
            shop.business_license_date = data.get('business_license_date') or None
            shop.birth_date = data.get('birth_date') or None
            shop.id_expiry_date = data.get('id_expiry_date', '') or ''
            shop.additional_remark = data.get('additional_remark', '') or ''

            # 其他
            shop.img1 = data.get('img1', '') or ''

            shop.save()

        return JsonResponse({'success': True, 'message': '店铺信息更新成功'})

    except Exception as e:
        print(f"更新Amazon店铺错误: {str(e)}")
        traceback.print_exc()
        return JsonResponse({'success': False, 'error': f'服务器错误: {str(e)}'}, status=500)
