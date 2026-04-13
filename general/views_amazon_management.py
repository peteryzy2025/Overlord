# General/views_amazon_management.py

from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST
from general.models import User, AmazonShop, OperationalAccount
from django.views.decorators.csrf import csrf_exempt
from django.db import transaction
from django.db.models import Q
import json
import traceback
from amazon.amazon_views import parse_permissions


# ============ 权限辅助函数 ============
def has_perm_code(user, code):
    """检查用户是否有特定权限码"""
    if not user or not user.is_authenticated:
        return False
    # code字段是IntegerField，尝试转为整数比较
    try:
        code_int = int(code)
        return user.permission_configs.filter(code=code_int).exists()
    except (ValueError, TypeError):
        return False


def can_access_shop_management(user):
    """店铺管理页面权限：555(超管) 或 552(店铺管理)"""
    return has_perm_code(user, '555') or has_perm_code(user, '552')


def is_ops_leader(user):
    """检查用户是否是运营组长"""
    if not user or user.department != 'operation':
        return False
    account = getattr(user, 'operational_account', None)
    if not account:
        return False
    return account.role == 'leader'


def get_visible_ops_ids(user):
    """获取用户可以看到的运营人员ID列表"""
    # 管理员可以看到所有人
    if can_access_shop_management(user):
        return None  # None表示不限制
    
    # 非运营部人员看不到任何店铺
    if user.department != 'operation':
        return []
    
    account = getattr(user, 'operational_account', None)
    if not account:
        return [user.id]
    
    # 运营组长可以看自己和组员
    if account.role == 'leader' and account.ops_group:
        members = User.objects.filter(
            company=user.company,
            department='operation',
            operational_account__ops_group=account.ops_group
        ).values_list('id', flat=True)
        return list(members)
    
    # 普通运营只能看自己
    return [user.id]


# Amazon店铺管理页面视图
@login_required
def amazon_management_view(request):
    """渲染Amazon店铺管理页面（仅运营部或管理员可访问）"""
    user = request.user
    
    # 检查权限：管理员或运营部人员可以访问
    if not can_access_shop_management(user) and user.department != 'operation':
        return redirect('general:main')
    
    import json
    user_perms = list(user.permission_configs.values_list('code', flat=True))
    user_perms_str = [str(p) for p in user_perms]
    context = {
        'active_page': 'amazon_management',
        'active_nav': 'management',
        'user_ops_group': getattr(request.user, 'get_ops_group', lambda: None)(),
        'user_permissions': user_perms_str,  # 用于Django模板条件判断
        'user_permissions_json': json.dumps(user_perms),  # 用于JS
        'is_admin': can_access_shop_management(user),
        'is_ops_leader': is_ops_leader(user),
    }
    return render(request, 'management/amazon_shop_management.html', context)


# 获取运营人员列表API（含OperationalAccount分组信息，按分组排序）
@require_GET
@login_required
def get_all_operators_api(request):
    """
    API接口：获取所有运营人员列表（本公司内）
    参数:
      - platform: 平台筛选，可选值: '亚马逊' 或 'Temu'
      - ops_group: 运营分组名称，可选筛选
    返回: [{id: 1, first_name: '张三', group: 'A组'}, ...]
    """
    try:
        # 获取参数
        platform = request.GET.get('platform', '').strip()
        ops_group_param = request.GET.get('ops_group', '').strip()

        # 基础查询：查询本公司运营部(operation)的用户
        queryset = User.objects.filter(
            company=request.user.company,
            department='operation'
        ).select_related('operational_account')

        # 应用平台筛选（兼容旧数据的中文平台字段）
        if platform in ['亚马逊', 'Temu']:
            queryset = queryset.filter(platform=platform)
        elif platform == 'amazon':
            queryset = queryset.filter(Q(platform='amazon') | Q(platform='亚马逊'))
        elif platform == 'temu':
            queryset = queryset.filter(Q(platform='temu') | Q(platform='Temu'))

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
    API接口：获取所有运营分组列表（支持按平台筛选，本公司内）
    参数:
        - platform: 可选，平台名称 ('亚马逊' 或 'Temu')
    返回: ['A组', 'B组', 'C组', ...]
    """
    try:
        platform = request.GET.get('platform', '').strip()

        # 基础查询：本公司内排除空值
        queryset = OperationalAccount.objects.filter(
            user__company=request.user.company
        ).exclude(
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
    API接口：获取所有客户列表（从AmazonShop.customer去重，本公司内）
    返回: ['客户A', '客户B', ...]
    """
    try:
        # 从AmazonShop查询customer，本公司内去重并排除空值
        customers = AmazonShop.objects.filter(
            company=request.user.company
        ).exclude(
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


@csrf_exempt
def external_amazon_shops_api(request):
    """
    对外免登录的 Amazon 店铺查询接口

    可选参数:
        - customer: 客户名称，支持模糊匹配

    返回:
        [
            {
                "店铺名称": "...",
                "状态": "...",
                "客户": "...",
                "亚马逊名称": "..."
                "浏览器":"..."
            }
        ]
    """
    if request.method != 'GET':
        return JsonResponse(
            {'error': '只支持GET请求'},
            status=405,
            json_dumps_params={'ensure_ascii': False}
        )

    try:
        customer = (request.GET.get('customer') or '').strip()

        query = AmazonShop.objects.all().order_by('id')
        if customer:
            query = query.filter(customer__icontains=customer)

        shops = query.values('shop_name', 'shop_status', 'customer', 'amazon_shop_name','browser')
        data = [
            {
                '店铺名称': shop.get('shop_name') or '',
                '状态': shop.get('shop_status') or '',
                '客户': shop.get('customer') or '',
                '亚马逊名称': shop.get('amazon_shop_name') or '',
                '浏览器': shop.get('browser') or '',
            }
            for shop in shops
        ]

        return JsonResponse(data, safe=False, json_dumps_params={'ensure_ascii': False})

    except Exception as e:
        print(f"对外Amazon店铺查询错误: {str(e)}")
        traceback.print_exc()
        return JsonResponse(
            {'error': f'服务器错误: {str(e)}'},
            status=500,
            json_dumps_params={'ensure_ascii': False}
        )


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
        permissions = parse_permissions(getattr(request.user, 'permission', ''))
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
                    'project_id': shop.project_id,
                    'project_name': shop.project.name if shop.project else '-',
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
                    'id_card_address': shop.id_card_address or '-',
                    'company_address': shop.company_address or '-',
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
        page_size = int(request.GET.get('page_size', 20))

        # 支持多选参数处理，统一将“全部”类值视为不筛选
        def get_list_param(name):
            val = request.GET.get(name, '').strip()
            if not val:
                return []

            def is_all_token(raw):
                token = str(raw or '').strip().lower()
                return token in {'', 'all', '*', 'any', '__all__', '全部', '不限'}

            values = [v.strip() for v in val.split(',') if v.strip()]
            if not values:
                return []
            if any(is_all_token(v) for v in values):
                return []
            return [v for v in values if not is_all_token(v)]

        status_filters = get_list_param('status')
        operator_filters = get_list_param('operator')
        ops_group_filters = get_list_param('ops_group')
        customer_filters = get_list_param('customer')
        project_filters = get_list_param('project')
        search_term = request.GET.get('search', '').strip()

        # 其他单选筛选
        shop_date_start = request.GET.get('shop_date_start', '').strip()
        shop_date_end = request.GET.get('shop_date_end', '').strip()
        qu_dao = request.GET.get('qu_dao', '').strip()
        backup_email_or_phone = request.GET.get('backup_email_or_phone', '').strip()
        additional_remark = request.GET.get('additional_remark', '').strip()
        company_name = request.GET.get('company_name', '').strip()
        ling_xing_if = request.GET.get('ling_xing_if', '').strip()
        browser = request.GET.get('browser', '').strip()
        xunhui_login_account = request.GET.get('xunhui_login_account', '').strip()
        email_account = request.GET.get('email_account', '').strip()

        if page < 1: page = 1
        if page_size not in [10, 20, 50, 100, 200, 5000]: page_size = 20

        # 公司隔离：只查本公司店铺
        query = AmazonShop.objects.filter(
            company=request.user.company
        ).select_related('ops', 'project').prefetch_related('ops__operational_account')

        # 权限范围过滤：555/552查看全部；运营组长查看本组；普通运营查看本人
        visible_ops_ids = get_visible_ops_ids(request.user)
        if visible_ops_ids is not None:  # None表示管理员，不限制
            query = query.filter(ops_id__in=visible_ops_ids)

        # 应用筛选逻辑
        if status_filters:
            query = query.filter(shop_status__in=status_filters)
        if operator_filters:
            query = query.filter(ops_id__in=[int(o) for o in operator_filters if o.isdigit()])
        if ops_group_filters:
            user_ids = OperationalAccount.objects.filter(ops_group__in=ops_group_filters).values_list('user_id', flat=True)
            query = query.filter(ops_id__in=user_ids)
        if customer_filters:
            query = query.filter(customer__in=customer_filters)
        if project_filters:
            query = query.filter(project_id__in=[int(p) for p in project_filters if p.isdigit()])
        
        if search_term:
            query = query.filter(
                Q(shop_name__icontains=search_term) |
                Q(amazon_shop_name__icontains=search_term)
            )

        # 其他新增筛选逻辑
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
        if email_account:
            query = query.filter(email_account__icontains=email_account)

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
                    pass

            shops_data.append({
                'id': shop.id,
                'shop_name': shop.shop_name or '-',
                'amazon_shop_name': shop.amazon_shop_name or '-',
                'customer': shop.customer or '-',
                'project_id': shop.project_id,
                'project_name': shop.project.name if shop.project else '-',
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
                'id_card_address': shop.id_card_address or '-',
                'company_address': shop.company_address or '-',
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


from django.utils import timezone


@require_POST
@csrf_exempt
@login_required
def bulk_update_project_api(request):
    """批量设置或移除店铺的项目归属（仅管理员）"""
    try:
        data = json.loads(request.body)
        shop_ids = data.get('shop_ids', [])
        project_id = data.get('project_id')  # 为 None 表示移除项目

        if not shop_ids:
            return JsonResponse({'success': False, 'error': '未选择店铺'}, status=400)

        # 权限校验：仅管理员（555/552）
        if not can_access_shop_management(request.user):
            return JsonResponse({'success': False, 'error': '无权限进行批量操作，仅管理员可用'}, status=403)

        with transaction.atomic():
            if project_id:
                # 检查项目是否存在且属于本公司
                from general.models import Project
                try:
                    project = Project.objects.get(id=project_id, company=request.user.company)
                    # 只更新本公司店铺
                    AmazonShop.objects.filter(id__in=shop_ids, company=request.user.company).update(project=project, updated_at=timezone.now())
                except Project.DoesNotExist:
                    return JsonResponse({'success': False, 'error': '项目不存在或不属于本公司'}, status=404)
            else:
                # 移除项目（只更新本公司店铺）
                AmazonShop.objects.filter(id__in=shop_ids, company=request.user.company).update(project=None, updated_at=timezone.now())

        return JsonResponse({'success': True, 'message': '批量操作成功'})

    except Exception as e:
        print(f"批量更新项目错误: {str(e)}")
        return JsonResponse({'success': False, 'error': f'服务器错误: {str(e)}'}, status=500)


@require_POST
@csrf_exempt
@login_required
def bulk_update_operator_api(request):
    """批量设置店铺的运营人员"""
    try:
        # 权限检查：仅管理员（555/552）
        if not can_access_shop_management(request.user):
            return JsonResponse({'success': False, 'error': '无权限进行批量操作，仅管理员可用'}, status=403)

        data = json.loads(request.body)
        shop_ids = data.get('shop_ids', [])
        operator_id = data.get('operator_id')

        if not shop_ids:
            return JsonResponse({'success': False, 'error': '未选择店铺'}, status=400)

        if not operator_id:
            return JsonResponse({'success': False, 'error': '未选择运营人员'}, status=400)

        # 检查运营人员是否存在且属于本公司
        try:
            operator = User.objects.get(id=operator_id, company=request.user.company)
        except User.DoesNotExist:
            return JsonResponse({'success': False, 'error': '运营人员不存在或不属于本公司'}, status=404)

        with transaction.atomic():
            # 只更新本公司店铺
            AmazonShop.objects.filter(id__in=shop_ids, company=request.user.company).update(
                ops_id=operator_id,
                updated_at=timezone.now()
            )

        return JsonResponse({
            'success': True,
            'message': f'已成功将 {len(shop_ids)} 个店铺分配给 {operator.first_name}'
        })

    except Exception as e:
        print(f"批量设置运营人员错误: {str(e)}")
        return JsonResponse({'success': False, 'error': f'服务器错误: {str(e)}'}, status=500)


@require_POST
@csrf_exempt
@login_required
def create_amazon_shop_api(request):
    """
    API接口：创建新Amazon店铺
    权限要求：用户必须拥有 permission_configs 中的 555（超管）或 551（店铺管理员）
    """
    try:
        data = json.loads(request.body)

        # 检查权限：必须有 555 或 552
        if not can_access_shop_management(request.user):
            return JsonResponse({
                'success': False,
                'error': '无创建权限，需要店铺管理员权限（552）或超管权限（555）'
            }, status=403)

        # 验证必填项
        shop_name = data.get('shop_name', '').strip()
        if not shop_name:
            return JsonResponse({
                'success': False,
                'error': '店铺名称不能为空'
            }, status=400)

        # 检查店铺名是否已存在
        if AmazonShop.objects.filter(shop_name=shop_name).exists():
            return JsonResponse({
                'success': False,
                'error': '店铺名称已存在'
            }, status=400)

        # 处理数字字段：空字符串转为 None
        shop_number = data.get('shop_number')
        if shop_number and str(shop_number).strip() not in ['', 'null', 'undefined']:
            try:
                shop_number = int(shop_number)
            except ValueError:
                return JsonResponse({'success': False, 'error': '店铺序号必须是数字'}, status=400)
        else:
            shop_number = None

        divi_shop_id = data.get('divi_shop_id')
        if divi_shop_id and str(divi_shop_id).strip() not in ['', 'null', 'undefined']:
            try:
                divi_shop_id = int(divi_shop_id)
            except ValueError:
                return JsonResponse({'success': False, 'error': '迪唯店铺ID必须是数字'}, status=400)
        else:
            divi_shop_id = None

        # 处理 ling_xing_if（领星绑定）
        ling_xing_if = data.get('ling_xing_if', 0)
        if ling_xing_if and str(ling_xing_if).strip() not in ['', 'null', 'undefined']:
            ling_xing_if = 1 if ling_xing_if in [1, '1', True, 'true'] else 0
        else:
            ling_xing_if = 0

        now = timezone.now()  # 获取当前时间

        with transaction.atomic():
            shop = AmazonShop.objects.create(
                # 基本信息
                company_id=request.user.company_id,
                project_id=data.get('project') if data.get('project') else None,
                shop_name=shop_name,
                shop_number=shop_number,
                amazon_shop_name=data.get('amazon_shop_name', '') or '',
                customer=data.get('customer', '') or '',
                ops_id=data.get('ops') if data.get('ops') else None,
                shop_status=data.get('shop_status', 'status-active') or 'status-active',
                shop_date=data.get('shop_date') or None,
                qu_dao=data.get('qu_dao', '') or '',
                seller_mark=data.get('seller_mark', '') or '',
                whitelist=data.get('whitelist', '') or '',
                ip_address=data.get('ip_address', '') or '',
                remark=data.get('remark', '') or '',

                # 时间字段（关键修复）
                created_at=now,
                updated_at=now,

                # 账号信息
                email_account=data.get('email_account', '') or '',
                email_password=data.get('email_password', '') or '',
                shop_password=data.get('shop_password', '') or '',
                registered_phone=data.get('registered_phone', '') or '',
                backup_email_or_phone=data.get('backup_email_or_phone', '') or '',
                voucher_163=data.get('voucher_163', '') or '',
                email_163_account=data.get('email_163_account', '') or '',
                browser=data.get('browser', '') or '',
                ling_xing_if=ling_xing_if,
                divi_shop_id=divi_shop_id,

                # 收款信息
                credit_card_channel=data.get('credit_card_channel', '') or '',
                credit_card_number=data.get('credit_card_number', '') or '',
                credit_card_expiry=data.get('credit_card_expiry', '') or '',
                credit_card_cvv=data.get('credit_card_cvv', '') or '',
                is_consolidated=data.get('is_consolidated', '') or '',
                bind_collection=data.get('bind_collection', '') or '',
                collection_channel=data.get('collection_channel', '') or '',
                xunhui_login_account=data.get('xunhui_login_account', '') or '',
                login_password=data.get('login_password', '') or '',
                bind_phone=data.get('bind_phone', '') or '',
                collection_card_number=data.get('collection_card_number', '') or '',
                payment_password=data.get('payment_password', '') or '',

                # 法人信息
                id_number=data.get('id_number', '') or '',
                legal_person_phone=data.get('legal_person_phone', '') or '',
                company_name=data.get('company_name', '') or '',
                license_number=data.get('license_number', '') or '',
                business_license_date=data.get('business_license_date') or None,
                birth_date=data.get('birth_date') or None,
                id_expiry_date=data.get('id_expiry_date', '') or '',
                id_card_address=data.get('id_card_address', '') or '',
                company_address=data.get('company_address', '') or '',
                additional_remark=data.get('additional_remark', '') or '',
                img1=data.get('img1', '') or '',
            )

        return JsonResponse({
            'success': True,
            'message': '店铺创建成功',
            'shop_id': shop.id
        })

    except Exception as e:
        print(f"❌ 创建Amazon店铺错误: {str(e)}")
        import traceback
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

        # 权限校验：管理员可更新任何；运营组长仅能更新本组；普通运营仅能更新本人店铺
        if can_access_shop_management(request.user):
            pass  # 管理员有全部权限
        elif is_ops_leader(request.user):
            # 运营组长只能更新本组店铺
            leader_account = getattr(request.user, 'operational_account', None)
            if leader_account and leader_account.ops_group:
                if not OperationalAccount.objects.filter(user_id=shop.ops_id, ops_group=leader_account.ops_group).exists():
                    return JsonResponse({'success': False, 'error': '无权限更新该店铺'}, status=403)
                new_ops_id = data.get('ops')
                if new_ops_id and not OperationalAccount.objects.filter(user_id=new_ops_id, ops_group=leader_account.ops_group).exists():
                    return JsonResponse({'success': False, 'error': '不可将店铺分配到其他分组'}, status=403)
            else:
                return JsonResponse({'success': False, 'error': '无权限更新该店铺'}, status=403)
        else:
            # 普通运营只能更新自己的店铺
            if shop.ops_id != request.user.id:
                return JsonResponse({'success': False, 'error': '仅允许更新本人店铺'}, status=403)
            new_ops_id = data.get('ops')
            if new_ops_id and int(new_ops_id) != request.user.id:
                return JsonResponse({'success': False, 'error': '不可将店铺分配给其他人'}, status=403)

        with transaction.atomic():
            # 基本信息
            shop.project_id = data.get('project') or None
            shop.shop_name = shop_name
            shop.shop_number = data.get('shop_number') or None
            shop.amazon_shop_name = data.get('amazon_shop_name', '') or ''
            shop.customer = data.get('customer', '') or ''
            shop.ops_id = data.get('ops') or None
            shop.shop_status = data.get('shop_status', 'status-active') or 'status-active'
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
            shop.id_card_address = data.get('id_card_address', '') or ''
            shop.company_address = data.get('company_address', '') or ''
            shop.additional_remark = data.get('additional_remark', '') or ''

            # 其他
            shop.img1 = data.get('img1', '') or ''

            shop.save()

        return JsonResponse({'success': True, 'message': '店铺信息更新成功'})

    except Exception as e:
        print(f"更新Amazon店铺错误: {str(e)}")
        traceback.print_exc()
        return JsonResponse({'success': False, 'error': f'服务器错误: {str(e)}'}, status=500)
