from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST
from general.models import User, OperationalAccount, PermissionConfig, Project
import traceback
from django.views.decorators.csrf import csrf_exempt
from django.db import transaction
import json
from django.db.models import Q
from django.shortcuts import redirect


# ============ 权限辅助函数 ============
def has_perm_code(user, code):
    """检查用户是否有特定权限码（支持 555/551 等）"""
    if not user or not user.is_authenticated:
        return False
    # 兼容旧逻辑：如果用户 ID 是 555 且 code=555，也视为有权限（迁移期兼容）
    if str(user.id) == '555' and str(code) == '555':
        return True
    return user.permission_configs.filter(code=str(code)).exists()


def can_access_user_management(user):
    """人员管理页面权限：555(超管) 或 551(人事管理员)"""
    return has_perm_code(user, '555') or has_perm_code(user, '551')


def get_user_company(user):
    """安全获取用户公司"""
    if not user or not hasattr(user, 'company'):
        return None
    return user.company


# ============ 页面视图 ============
@login_required
def user_management_view(request):
    """渲染人员管理页面（555或551权限可访问）"""
    if not can_access_user_management(request.user):
        return redirect('general:main')

    context = {
        'active_page': 'user_management',
        'active_nav': 'management',
        'current_company': request.user.company.name if request.user.company else '未分配公司'
    }
    return render(request, 'management/user_management.html', context)


# ============ API 视图 ============
@require_GET
@login_required
def get_users_api(request):
    """
    API接口：获取用户列表（已改造：公司隔离）
    """
    try:
        # 公司隔离检查
        current_company = get_user_company(request.user)
        if not current_company:
            return JsonResponse({
                'success': False,
                'error': '当前用户未归属任何公司，无法查看人员'
            }, status=403)

        page = int(request.GET.get('page', 1))
        page_size = int(request.GET.get('page_size', 10))
        if page < 1:
            page = 1
        if page_size not in [10, 20, 50, 100, 200]:
            page_size = 10

        # 筛选参数
        role_filter = request.GET.get('role', '').strip()
        status_filter = request.GET.get('status', '').strip()
        department_filter = request.GET.get('department', '').strip()
        search_filter = request.GET.get('search', '').strip()
        ops_group_filter = request.GET.get('ops_group', '').strip()

        # ===== 公司隔离：只查本公司人员 =====
        queryset = User.objects.filter(
            company=current_company
        ).select_related('operational_account', 'company')

        # 应用筛选
        if role_filter:
            queryset = queryset.filter(role=role_filter)

        if status_filter:
            status_map = {
                'active': User.Status.NORMAL,
                'inactive': User.Status.DISABLED,
            }
            db_status = status_map.get(status_filter)
            if db_status is not None:
                queryset = queryset.filter(status=db_status)

        if department_filter:
            queryset = queryset.filter(department__icontains=department_filter)

        if search_filter:
            queryset = queryset.filter(
                Q(username__icontains=search_filter) |
                Q(first_name__icontains=search_filter)
            )

        if ops_group_filter:
            queryset = queryset.filter(operational_account__ops_group=ops_group_filter)

        total_count = queryset.count()
        offset = (page - 1) * page_size
        users = queryset.order_by('id')[offset:offset + page_size]

        users_data = []
        for user in users:
            status_display_map = {
                User.Status.NORMAL: 'active',
                User.Status.DISABLED: 'inactive'
            }

            account = getattr(user, 'operational_account', None)

            # 权限列表
            permissions = list(user.permission_configs.values_list('code', flat=True))

            user_dict = {
                'id': user.id,
                'username': user.username,
                'first_name': user.first_name or '-',
                'phone': user.phone or '-',
                'department': user.department or '-',
                'status': status_display_map.get(user.status, 'inactive'),
                'company_name': user.company.name if user.company else '-',
                'wx_url': user.wx_url or '',
                'ops_group': account.ops_group or '-' if account else '-',
                'createdAt': user.date_joined.strftime('%Y-%m-%d') if user.date_joined else '-',
                'permissions': permissions,
                'role': user.role or '',
                'platform': user.platform or '',
                'remark': user.remark or '',
            }

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
                    'role': account.role or 'staff',
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
            'company_id': current_company.id,
            'company_name': current_company.name,
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
    API接口：创建新用户（强制选择项目）
    """
    try:
        current_company = get_user_company(request.user)
        if not current_company:
            return JsonResponse({
                'success': False,
                'error': '当前用户无公司归属，无法创建用户'
            }, status=403)

        # 权限检查：只有555或551可以创建用户
        if not can_access_user_management(request.user):
            return JsonResponse({
                'success': False,
                'error': '无权创建用户，需要管理员或人事管理员权限'
            }, status=403)

        data = json.loads(request.body)
        username = data.get('username', '').strip()

        # 验证必填项
        if not username:
            return JsonResponse({'success': False, 'error': '用户名不能为空'}, status=400)

        # 本公司内用户名唯一检查
        if User.objects.filter(company=current_company, username=username).exists():
            return JsonResponse({
                'success': False,
                'error': f'本公司内该用户名已存在'
            }, status=400)

        with transaction.atomic():
            # 创建用户
            user = User.objects.create(
                username=username,
                first_name=data.get('first_name', ''),
                phone=data.get('phone', ''),
                department=data.get('department', ''),
                role=data.get('role', ''),
                status={
                    'active': User.Status.NORMAL,
                    'inactive': User.Status.DISABLED,
                }.get(data.get('status'), User.Status.NORMAL),
                company=current_company,
                platform=data.get('platform', ''),
                remark=data.get('remark', ''),
                wx_url=data.get('wx_url', ''),
            )

            # 设置密码
            password = data.get('password', '').strip()
            user.set_password(password if password else 'default123')
            user.save()

            # 设置权限
            permissions = data.get('permissions', [])
            if permissions:
                # 敏感权限检查（555/5555只能由555设置）
                sensitive_codes = ['555', '5555']
                has_sensitive = any(str(p) in sensitive_codes for p in permissions)

                if has_sensitive and not has_perm_code(request.user, '555'):
                    raise Exception("只有超级管理员可以设置管理员权限")

                permission_objs = PermissionConfig.objects.filter(code__in=permissions)
                user.permission_configs.set(permission_objs)

            # 创建运营账号
            account_data = data.get('operational_account', {})
            if any(account_data.values()):
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
                    role=account_data.get('role', 'staff'),
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


@require_POST
@csrf_exempt
@login_required
def update_user_api(request, user_id):
    """
    API接口：更新用户（强制项目选择）
    """
    try:
        current_company = get_user_company(request.user)
        if not current_company:
            return JsonResponse({
                'success': False,
                'error': '当前用户无公司归属'
            }, status=403)

        # 权限检查
        if not can_access_user_management(request.user):
            return JsonResponse({
                'success': False,
                'error': '无权编辑用户'
            }, status=403)

        data = json.loads(request.body)

        # 仅允许修改本公司成员
        try:
            user = User.objects.get(id=user_id, company=current_company)
        except User.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': '用户不存在或不属于您的公司'
            }, status=404)

        with transaction.atomic():
            user.first_name = data.get('first_name', user.first_name)
            user.phone = data.get('phone', user.phone)
            user.department = data.get('department', user.department)
            user.role = data.get('role', user.role)
            user.platform = data.get('platform', user.platform)
            user.remark = data.get('remark', user.remark)
            user.wx_url = data.get('wx_url', user.wx_url)

            # 状态映射
            status_reverse_map = {
                'active': User.Status.NORMAL,
                'inactive': User.Status.DISABLED,
            }
            if data.get('status'):
                user.status = status_reverse_map.get(data.get('status'), user.status)

            # 密码更新
            password = data.get('password', '').strip()
            if password:
                user.set_password(password)
            user.save()

            # 权限更新
            if 'permissions' in data:
                new_permissions = set(data.get('permissions', []))
                current_permissions = set(
                    user.permission_configs.values_list('code', flat=True)
                )

                sensitive_codes = ['555', '5555']
                is_sensitive_change = any(
                    str(p) in sensitive_codes
                    for p in (new_permissions | current_permissions)
                )

                if is_sensitive_change and not has_perm_code(request.user, '555'):
                    return JsonResponse({
                        'success': False,
                        'error': '只有超级管理员可以修改管理员权限'
                    }, status=403)

                permission_objs = PermissionConfig.objects.filter(code__in=new_permissions)
                user.permission_configs.set(permission_objs)

            # 更新运营账号
            account_data = data.get('operational_account', {})
            if account_data:
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
                        'role': account_data.get('role', 'staff'),
                    }
                )
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
                    account.role = account_data.get('role', account.role)
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


# ============ 辅助API ============
@require_GET
@login_required
def get_company_projects_api(request):
    """
    获取当前公司的所有项目列表（用于新建/编辑用户时的项目选择）
    """
    try:
        current_company = get_user_company(request.user)
        if not current_company:
            return JsonResponse({'success': False, 'error': '无公司归属'}, status=403)

        projects = Project.objects.filter(
            company=current_company,
            is_active=True
        ).order_by('sort_order', '-created_at').values('id', 'name', 'code')

        return JsonResponse({
            'success': True,
            'data': list(projects)
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f'获取项目列表失败: {str(e)}'
        }, status=500)


@require_GET
@login_required
def get_roles_api(request):
    """获取本公司内已存在的角色列表"""
    try:
        current_company = get_user_company(request.user)
        if not current_company:
            return JsonResponse({'success': False, 'error': '无公司归属'}, status=403)

        existing_roles = User.objects.filter(
            company=current_company
        ).exclude(role__isnull=True).exclude(role='').values_list('role', flat=True).distinct()

        roles_data = [{'key': role, 'name': role} for role in sorted(existing_roles)]

        return JsonResponse({'success': True, 'data': roles_data})
    except Exception as e:
        print(f"获取角色列表错误: {str(e)}")
        traceback.print_exc()
        return JsonResponse({
            'success': False,
            'error': f'服务器错误: {str(e)}'
        }, status=500)


@require_GET
@login_required
def get_permission_configs_api(request):
    """获取所有权限配置列表（全局）"""
    try:
        permissions = PermissionConfig.objects.all().values('id', 'code', 'name', 'description').order_by('code')
        return JsonResponse({
            'success': True,
            'data': list(permissions)
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f'获取权限列表失败: {str(e)}'
        }, status=500)


@require_POST
@csrf_exempt
@login_required
def bulk_update_permissions_api(request):
    """
    批量添加/移除用户权限（已改造：仅操作本公司用户）
    """
    try:
        current_company = get_user_company(request.user)
        if not current_company:
            return JsonResponse({
                'success': False,
                'error': '无公司归属'
            }, status=403)

        # 权限检查
        if not can_access_user_management(request.user):
            return JsonResponse({
                'success': False,
                'error': '无权操作'
            }, status=403)

        data = json.loads(request.body)
        user_ids = data.get('user_ids', [])
        action = data.get('action')
        permissions = data.get('permissions', [])

        if not user_ids or not isinstance(user_ids, list):
            return JsonResponse({'success': False, 'error': '未选择任何用户'}, status=400)

        if not permissions or not isinstance(permissions, list):
            return JsonResponse({'success': False, 'error': '未选择任何权限'}, status=400)

        if action not in ['add', 'remove']:
            return JsonResponse({'success': False, 'error': '操作类型无效'}, status=400)

        # 敏感权限检查
        sensitive_codes = ['555', '5555']
        has_sensitive = any(str(p) in sensitive_codes for p in permissions)
        if has_sensitive and not has_perm_code(request.user, '555'):
            return JsonResponse({
                'success': False,
                'error': '只有超级管理员可以操作管理员权限'
            }, status=403)

        permission_objs = PermissionConfig.objects.filter(code__in=permissions)

        with transaction.atomic():
            # 仅操作本公司用户
            users = User.objects.filter(id__in=user_ids, company=current_company)
            actual_count = users.count()

            if action == 'add':
                for user in users:
                    user.permission_configs.add(*permission_objs)
            elif action == 'remove':
                for user in users:
                    user.permission_configs.remove(*permission_objs)

        return JsonResponse({
            'success': True,
            'message': f'已成功更新 {actual_count} 位用户的权限'
        })

    except Exception as e:
        print(f"批量权限操作错误: {str(e)}")
        traceback.print_exc()
        return JsonResponse({
            'success': False,
            'error': f'服务器错误: {str(e)}'
        }, status=500)


@require_GET
@login_required
def get_ops_groups_api(request):
    """
    获取本公司内所有运营小组列表
    """
    try:
        current_company = get_user_company(request.user)
        if not current_company:
            return JsonResponse({'success': False, 'error': '无公司归属'}, status=403)

        ops_groups = OperationalAccount.objects.filter(
            user__company=current_company
        ).exclude(
            ops_group__isnull=True
        ).exclude(
            ops_group=''
        ).values_list(
            'ops_group', flat=True
        ).distinct().order_by('ops_group')

        groups_data = [{'key': group, 'name': group} for group in ops_groups]

        return JsonResponse({
            'success': True,
            'data': groups_data
        })

    except Exception as e:
        print(f"获取运营小组列表错误: {str(e)}")
        traceback.print_exc()
        return JsonResponse({
            'success': False,
            'error': f'服务器错误: {str(e)}'
        }, status=500)


@require_GET
@login_required
def get_departments_api(request):
    """
    获取本公司内所有部门列表
    """
    try:
        current_company = get_user_company(request.user)
        if not current_company:
            return JsonResponse({'success': False, 'error': '无公司归属'}, status=403)

        departments = User.objects.filter(
            company=current_company
        ).exclude(
            department__isnull=True
        ).exclude(
            department=''
        ).values_list(
            'department', flat=True
        ).distinct().order_by('department')

        depts_data = [{'key': dept, 'name': dept} for dept in departments]

        return JsonResponse({
            'success': True,
            'data': depts_data
        })

    except Exception as e:
        print(f"获取部门列表错误: {str(e)}")
        traceback.print_exc()
        return JsonResponse({
            'success': False,
            'error': f'服务器错误: {str(e)}'
        }, status=500)


# ============ 占位视图（防止urls.py引用报错） ============
@login_required
def temu_management_view(request):
    """Temu店铺管理页面 - 占位"""
    context = {'active_page': 'temu_management'}
    return render(request, 'management/temu_shop_management.html', context)