# General/views_user_management.py

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.http import require_GET
from General.models import User, OperationalAccount
import traceback
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from django.db import transaction
import json
from django.db.models import Q
# 人员管理页面视图
@login_required
def user_management_view(request):
    """渲染人员管理页面"""
    return render(request, 'user_management.html')


# Amazon店铺管理页面视图
@login_required
def amazon_management_view(request):
    """渲染Amazon店铺管理页面"""
    return render(request, 'amazon_shop_management.html')


# Temu店铺管理页面视图
@login_required
def temu_management_view(request):
    """渲染Temu店铺管理页面"""
    return render(request, 'temu_shop_management.html')


# 修改 get_users_api 函数，支持分页参数
def get_users_api(request):
    """
    API接口：获取用户列表及关联的运营账号信息（支持分页和筛选）
    参数:
        - page=1, page_size=10
        - role=角色值
        - status=状态值(active/inactive/cancelled)
        - department=部门搜索词
        - search=通用搜索词（搜索用户名/名字）
    返回: {success: true, data: [用户数据], total: 总条数, page: 当前页, page_size: 每页条数}
    """
    try:
        # 获取分页参数
        page = int(request.GET.get('page', 1))
        page_size = int(request.GET.get('page_size', 10))

        # 参数校验
        if page < 1: page = 1
        if page_size not in [10, 20, 50, 100]: page_size = 10

        # 获取筛选参数
        role_filter = request.GET.get('role', '').strip()
        status_filter = request.GET.get('status', '').strip()
        department_filter = request.GET.get('department', '').strip()
        search_filter = request.GET.get('search', '').strip()

        # 构建基础查询集（使用 select_related 预加载关联数据）
        queryset = User.objects.select_related('operational_account').all()

        # 应用筛选条件
        if role_filter:
            queryset = queryset.filter(role=role_filter)

        if status_filter:
            # 将前端的status值转换为数据库值
            status_map = {
                'active': User.STATUS_NORMAL,
                'inactive': User.STATUS_DISABLED,
                'cancelled': User.STATUS_CANCELLED
            }
            db_status = status_map.get(status_filter)
            if db_status is not None:
                queryset = queryset.filter(status=db_status)

        if department_filter:
            queryset = queryset.filter(department__icontains=department_filter)

        if search_filter:
            # 搜索用户名或名字
            queryset = queryset.filter(
                Q(username__icontains=search_filter) |
                Q(first_name__icontains=search_filter)
            )

        # 查询总条数（应用筛选后）
        total_count = queryset.count()

        # 计算偏移量并应用分页
        offset = (page - 1) * page_size
        users = queryset.order_by('id')[offset:offset + page_size]

        users_data = []
        for user in users:
            # 状态映射
            status_map = {
                User.STATUS_NORMAL: 'active',
                User.STATUS_DISABLED: 'inactive',
                User.STATUS_CANCELLED: 'cancelled'
            }

            # ✅ 关键修改：安全获取关联的运营账号对象
            account = getattr(user, 'operational_account', None)

            user_dict = {
                'id': user.id,
                'username': user.username,
                'first_name': user.first_name or '-',
                'phone': user.phone or '-',
                'department': user.department or '-',
                'role': user.role or '',
                'status': status_map.get(user.status, 'inactive'),
                'company_name': user.company_name or '-',
                'platform': user.platform or '-',
                'remark': user.remark or '',
                'ops_group': account.ops_group or '-' if account else '-',
                'createdAt': user.date_joined.strftime('%Y-%m-%d') if user.date_joined else '-',
            }

            # ✅ 优化：复用 account 变量，避免重复查询
            if account:
                user_dict['operational_account'] = {
                    'shandianyun_account': account.shandianyun_account or '-',
                    'shandianyun_username': account.shandianyun_username or '-',
                    'shandianyun_password': account.shandianyun_password or '-',
                    'lingxing_username': account.lingxing_username or '-',
                    'lingxing_password': account.lingxing_password or '-',
                    'ziniao_company': account.ziniao_company or '-',
                    'ziniao_username': account.ziniao_username or '-',
                    'ziniao_password': account.ziniao_password or '-',
                    'diwei_account': account.diwei_account or '-',
                    'diwei_password': account.diwei_password or '-',
                }
            else:
                user_dict['operational_account'] = {}

            users_data.append(user_dict)

        return JsonResponse({
            'success': True,
            'data': users_data,
            'total': total_count,
            'page': page,
            'page_size': page_size,
            'filters_applied': bool(role_filter or status_filter or department_filter or search_filter)
        })

    except Exception as e:
        print(f"获取用户数据错误: {str(e)}")
        traceback.print_exc()
        return JsonResponse({
            'success': False,
            'error': f'服务器错误: {str(e)}'
        }, status=500)

@require_POST
@csrf_exempt
@login_required
def create_user_api(request):
    """
    API接口：创建新用户及其关联的运营账号信息
    """
    try:
        # 解析请求数据
        data = json.loads(request.body)

        # 验证必填项
        username = data.get('username', '').strip()
        if not username:
            return JsonResponse({
                'success': False,
                'error': '用户名不能为空'
            }, status=400)

        # 检查用户名是否已存在
        if User.objects.filter(username=username).exists():
            return JsonResponse({
                'success': False,
                'error': '用户名已存在'
            }, status=400)

        # 使用事务确保数据一致性
        with transaction.atomic():
            # 创建用户
            user = User.objects.create(
                username=username,
                first_name=data.get('first_name', ''),
                phone=data.get('phone', ''),
                department=data.get('department', ''),
                role=data.get('role', ''),
                status={
                    'active': User.STATUS_NORMAL,
                    'inactive': User.STATUS_DISABLED,
                    'cancelled': User.STATUS_CANCELLED
                }.get(data.get('status'), User.STATUS_NORMAL),
                company_name=data.get('company_name', ''),
                platform=data.get('platform', ''),
                remark=data.get('remark', ''),
            )

            # 设置默认密码（可以根据需要修改）
            user.set_password('default123')  # 默认密码
            user.save()

            # 创建运营账号信息
            account_data = data.get('operational_account', {})
            if any(account_data.values()):  # 只有当至少有一个字段有值时才创建
                OperationalAccount.objects.create(
                    user=user,
                    ops_group=account_data.get('ops_group', ''),
                    shandianyun_account=account_data.get('shandianyun_account', ''),
                    shandianyun_username=account_data.get('shandianyun_username', ''),
                    shandianyun_password=account_data.get('shandianyun_password', ''),
                    lingxing_username=account_data.get('lingxing_username', ''),
                    lingxing_password=account_data.get('lingxing_password', ''),
                    ziniao_company=account_data.get('ziniao_company', ''),
                    ziniao_username=account_data.get('ziniao_username', ''),
                    ziniao_password=account_data.get('ziniao_password', ''),
                    diwei_account=account_data.get('diwei_account', ''),
                    diwei_password=account_data.get('diwei_password', ''),
                )

        return JsonResponse({
            'success': True,
            'message': '用户创建成功',
            'user_id': user.id
        })

    except Exception as e:
        print(f"创建用户错误: {str(e)}")
        traceback.print_exc()

        return JsonResponse({
            'success': False,
            'error': f'服务器错误: {str(e)}'
        }, status=500)


# 修改原有的update_user_api函数，确保它能正确处理更新
@require_POST
@csrf_exempt
@login_required
def update_user_api(request, user_id):
    """
    API接口：更新用户及其关联的运营账号信息
    """
    try:
        # 解析请求数据
        data = json.loads(request.body)

        # 获取用户对象
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': '用户不存在'
            }, status=404)

        # 使用事务确保数据一致性
        with transaction.atomic():
            # 更新用户基本信息（排除id和username）
            user.first_name = data.get('first_name', user.first_name)
            user.phone = data.get('phone', user.phone)
            user.department = data.get('department', user.department)
            user.role = data.get('role', user.role)

            # 状态映射转换
            status_reverse_map = {
                'active': User.STATUS_NORMAL,
                'inactive': User.STATUS_DISABLED,
                'cancelled': User.STATUS_CANCELLED
            }
            user.status = status_reverse_map.get(data.get('status'), user.status)

            user.company_name = data.get('company_name', user.company_name)
            user.platform = data.get('platform', user.platform)
            user.remark = data.get('remark', user.remark)
            user.save()

            # 更新运营账号信息
            account_data = data.get('operational_account', {})
            if account_data:
                # 获取或创建运营账号
                account, created = OperationalAccount.objects.get_or_create(
                    user=user,
                    defaults={
                        'ops_group': account_data.get('ops_group', ''),
                        'shandianyun_account': account_data.get('shandianyun_account', ''),
                        'shandianyun_username': account_data.get('shandianyun_username', ''),
                        'shandianyun_password': account_data.get('shandianyun_password', ''),
                        'lingxing_username': account_data.get('lingxing_username', ''),
                        'lingxing_password': account_data.get('lingxing_password', ''),
                        'ziniao_company': account_data.get('ziniao_company', ''),
                        'ziniao_username': account_data.get('ziniao_username', ''),
                        'ziniao_password': account_data.get('ziniao_password', ''),
                        'diwei_account': account_data.get('diwei_account', ''),
                        'diwei_password': account_data.get('diwei_password', ''),
                    }
                )

                # 如果账号已存在，更新所有字段
                if not created:
                    account.ops_group = account_data.get('ops_group', account.ops_group)
                    account.shandianyun_account = account_data.get('shandianyun_account', account.shandianyun_account)
                    account.shandianyun_username = account_data.get('shandianyun_username',
                                                                    account.shandianyun_username)
                    account.shandianyun_password = account_data.get('shandianyun_password',
                                                                    account.shandianyun_password)
                    account.lingxing_username = account_data.get('lingxing_username', account.lingxing_username)
                    account.lingxing_password = account_data.get('lingxing_password', account.lingxing_password)
                    account.ziniao_company = account_data.get('ziniao_company', account.ziniao_company)
                    account.ziniao_username = account_data.get('ziniao_username', account.ziniao_username)
                    account.ziniao_password = account_data.get('ziniao_password', account.ziniao_password)
                    account.diwei_account = account_data.get('diwei_account', account.diwei_account)
                    account.diwei_password = account_data.get('diwei_password', account.diwei_password)
                    account.save()

        return JsonResponse({
            'success': True,
            'message': '用户信息更新成功'
        })

    except Exception as e:
        print(f"更新用户数据错误: {str(e)}")
        traceback.print_exc()

        return JsonResponse({
            'success': False,
            'error': f'服务器错误: {str(e)}'
        }, status=500)


@require_GET
@login_required
def get_roles_api(request):
    """
    API接口：从数据库中获取所有已存在的角色列表
    返回格式: [{'key': 'role_value', 'name': 'role_value'}, ...]
    """
    try:
        # 查询数据库中所有用户，提取唯一的、非空的role值
        existing_roles = User.objects.exclude(role__isnull=True).exclude(role='').values_list('role',
                                                                                              flat=True).distinct()

        # 转换为前端需要的格式，按字母顺序排序
        roles_data = [
            {'key': role, 'name': role}  # 直接使用数据库中的值作为显示名称
            for role in sorted(existing_roles)
        ]

        return JsonResponse({
            'success': True,
            'data': roles_data
        })

    except Exception as e:
        print(f"获取角色列表错误: {str(e)}")
        traceback.print_exc()

        return JsonResponse({
            'success': False,
            'error': f'服务器错误: {str(e)}'
        }, status=500)