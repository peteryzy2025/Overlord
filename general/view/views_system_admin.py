import json
import traceback
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from general.models import Company, CompanyModuleGrant, PermissionConfig, SystemModule, User, UserOperationLog


SYSTEM_SUPER_ADMIN_ID = 555
COMPANY_ADMIN_PERMISSION_CODE = 555
DEFAULT_SYSTEM_MODULES = [
    {
        'code': 'order_fulfillment',
        'name': '导单发货功能',
        'category': '业务流程',
        'description': '订单导入、订单处理、发货与相关业务流程',
        'icon': 'fas fa-file-import',
        'sort_order': 10,
    },
    {
        'code': 'automation',
        'name': '自动化功能',
        'category': '自动化',
        'description': 'RPA、自动同步、自动通知与自动化任务相关功能',
        'icon': 'fas fa-robot',
        'sort_order': 20,
    },
    {
        'code': 'logistics',
        'name': '物流板块',
        'category': '物流',
        'description': '物流追踪、物流异常、面单与外部采购物流相关功能',
        'icon': 'fas fa-truck',
        'sort_order': 30,
    },
    {
        'code': 'theme',
        'name': '主题板块',
        'category': '数据与选品',
        'description': '主题词、趋势、新品、ABA 与选品数据相关功能',
        'icon': 'fas fa-lightbulb',
        'sort_order': 40,
    },
    {
        'code': 'infringement',
        'name': '侵权板块',
        'category': '风控',
        'description': '侵权词库、商标查询、风险关键词与相关风控功能',
        'icon': 'fas fa-shield-alt',
        'sort_order': 50,
    },
]

LEGACY_MODULE_CODE_MAP = {
    'amazon': 'order_fulfillment',
    'temu': 'order_fulfillment',
    'tracking': 'logistics',
    'inventory': 'logistics',
    'aba': 'theme',
    'task': 'automation',
    'approval': 'automation',
    'performance': 'automation',
    'data_req': 'automation',
    'shop_guard': 'infringement',
    'divi': 'automation',
}


def is_system_super_admin(user):
    """平台总后台只认用户主键 555，不认权限码 555。"""
    return bool(user and user.is_authenticated and user.id == SYSTEM_SUPER_ADMIN_ID)


def system_super_admin_required(view_func):
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not is_system_super_admin(request.user):
            if request.path.startswith('/api/'):
                return JsonResponse({
                    'success': False,
                    'error': '无权访问平台总后台'
                }, status=403)
            return render(request, 'error/403.html', status=403)
        return view_func(request, *args, **kwargs)

    return login_required(_wrapped)


def _json_body(request):
    if not request.body:
        return {}
    return json.loads(request.body.decode('utf-8'))


def _normalize_company_code(code):
    code = (code or '').strip()
    return code or None


def _parse_settings(settings_value):
    if settings_value in (None, ''):
        return {}
    if isinstance(settings_value, dict):
        return settings_value
    if isinstance(settings_value, str):
        parsed = json.loads(settings_value)
        if not isinstance(parsed, dict):
            raise ValueError('公司配置必须是 JSON 对象')
        return parsed
    raise ValueError('公司配置格式不正确')


def _company_status(value, default=Company._meta.get_field('status').default):
    if value in (1, '1', 'active', 'normal', True):
        return 1
    if value in (2, '2', 'disabled', 'inactive', False):
        return 2
    return default


def _user_status(value, default=User.Status.NORMAL):
    if value in (1, '1', 'active', 'normal', True):
        return User.Status.NORMAL
    if value in (2, '2', 'disabled', 'inactive', False):
        return User.Status.DISABLED
    return default


def _ensure_company_admin_permission():
    permission, _ = PermissionConfig.objects.get_or_create(
        code=COMPANY_ADMIN_PERMISSION_CODE,
        defaults={
            'name': '公司管理员',
            'description': '公司层面的管理员权限，不代表平台总后台权限',
            'category': '公司管理',
        }
    )
    return permission


def _permission_objects(raw_codes, force_company_admin=True):
    codes = []
    for code in raw_codes or []:
        if code in ('', None):
            continue
        try:
            codes.append(int(code))
        except (TypeError, ValueError):
            raise ValueError(f'权限码无效: {code}')

    if force_company_admin and COMPANY_ADMIN_PERMISSION_CODE not in codes:
        codes.append(COMPANY_ADMIN_PERMISSION_CODE)

    if COMPANY_ADMIN_PERMISSION_CODE in codes:
        _ensure_company_admin_permission()

    permissions = list(PermissionConfig.objects.filter(code__in=codes))
    found_codes = {permission.code for permission in permissions}
    missing_codes = sorted(set(codes) - found_codes)
    if missing_codes:
        raise ValueError(f'权限码不存在: {", ".join(map(str, missing_codes))}')
    return permissions


def _log_system_action(request, company, operation_type, record):
    UserOperationLog.objects.create(
        company=company,
        user=request.user,
        operation_type=operation_type,
        operation_record=record[:255],
    )


def _ensure_default_system_modules():
    module_by_code = {}
    for module_data in DEFAULT_SYSTEM_MODULES:
        module, _ = SystemModule.objects.update_or_create(
            code=module_data['code'],
            defaults={
                'name': module_data['name'],
                'category': module_data['category'],
                'description': module_data['description'],
                'icon': module_data['icon'],
                'sort_order': module_data['sort_order'],
                'is_active': True,
                'is_builtin': True,
            }
        )
        module_by_code[module.code] = module

    for legacy_code, target_code in LEGACY_MODULE_CODE_MAP.items():
        legacy_module = SystemModule.objects.filter(code=legacy_code).first()
        target_module = module_by_code.get(target_code)
        if not legacy_module or not target_module:
            continue

        legacy_grants = CompanyModuleGrant.objects.filter(module=legacy_module, enabled=True)
        for legacy_grant in legacy_grants:
            grant, created = CompanyModuleGrant.objects.get_or_create(
                company=legacy_grant.company,
                module=target_module,
                defaults={
                    'enabled': True,
                    'settings': legacy_grant.settings or {},
                    'remark': legacy_grant.remark or '',
                    'created_by': legacy_grant.created_by,
                    'updated_by': legacy_grant.updated_by,
                }
            )
            if not created and not grant.enabled:
                grant.enabled = True
                grant.updated_by = legacy_grant.updated_by
                grant.save(update_fields=['enabled', 'updated_by', 'updated_at'])

    current_codes = [module['code'] for module in DEFAULT_SYSTEM_MODULES]
    SystemModule.objects.filter(is_builtin=True).exclude(code__in=current_codes).update(is_active=False)


def _system_module_payload(module):
    return {
        'id': module.id,
        'code': module.code,
        'name': module.name,
        'category': module.category or '',
        'description': module.description or '',
        'icon': module.icon or '',
        'sort_order': module.sort_order,
        'is_active': module.is_active,
    }


def _module_grant_payload(grant):
    return {
        'module_code': grant.module.code,
        'module_name': grant.module.name,
        'enabled': grant.enabled,
        'starts_at': grant.starts_at.strftime('%Y-%m-%d %H:%M') if grant.starts_at else '',
        'expires_at': grant.expires_at.strftime('%Y-%m-%d %H:%M') if grant.expires_at else '',
        'settings': grant.settings or {},
        'remark': grant.remark or '',
    }


def _company_payload(company):
    company_admins = list(
        company.users.filter(permission_configs__code=COMPANY_ADMIN_PERMISSION_CODE)
        .distinct()
        .order_by('id')[:5]
    )
    module_grants = list(
        company.module_grants.select_related('module').order_by('module__category', 'module__sort_order', 'module__code')
    )
    enabled_module_codes = [
        grant.module.code
        for grant in module_grants
        if grant.enabled and grant.module.is_active
    ]
    return {
        'id': company.id,
        'name': company.name,
        'code': company.code or '',
        'status': company.status,
        'status_label': '正常' if company.status == 1 else '停用',
        'settings': company.settings or {},
        'user_count': getattr(company, 'user_count', company.users.count()),
        'module_count': len(enabled_module_codes),
        'enabled_module_codes': enabled_module_codes,
        'module_grants': [_module_grant_payload(grant) for grant in module_grants],
        'admin_count': getattr(company, 'admin_count', company.users.filter(
            permission_configs__code=COMPANY_ADMIN_PERMISSION_CODE
        ).distinct().count()),
        'admins': [
            {
                'id': user.id,
                'username': user.username,
                'first_name': user.first_name or '',
            }
            for user in company_admins
        ],
        'created_at': company.created_at.strftime('%Y-%m-%d %H:%M') if company.created_at else '',
        'updated_at': company.updated_at.strftime('%Y-%m-%d %H:%M') if company.updated_at else '',
    }


def _create_company_owner(company, data):
    username = (data.get('owner_username') or data.get('username') or '').strip()
    first_name = (data.get('owner_first_name') or data.get('first_name') or '').strip()
    password = (data.get('owner_password') or data.get('password') or '').strip()
    phone = (data.get('owner_phone') or data.get('phone') or '').strip()
    status = _user_status(data.get('owner_status') or data.get('status'), User.Status.NORMAL)

    if not username:
        raise ValueError('主账号用户名不能为空')
    if not first_name:
        raise ValueError('主账号姓名不能为空')
    if User.objects.filter(username=username).exists():
        raise ValueError('该用户名已存在')

    user = User(
        username=username,
        first_name=first_name,
        phone=phone,
        status=status,
        is_active=status == User.Status.NORMAL,
        company=company,
        company_name=company.name,
        role='公司管理员',
        remark=(data.get('owner_remark') or data.get('remark') or '').strip(),
    )
    user.set_password(password or 'default123')
    user.save()

    permissions = _permission_objects(data.get('permissions', []), force_company_admin=True)
    user.permission_configs.set(permissions)
    return user


def _sync_company_modules(company, module_codes, actor):
    if module_codes is None:
        return
    if not isinstance(module_codes, list):
        raise ValueError('模块授权数据必须是数组')

    selected_codes = {str(code).strip() for code in module_codes if str(code).strip()}
    modules = list(SystemModule.objects.filter(code__in=selected_codes, is_active=True))
    found_codes = {module.code for module in modules}
    missing_codes = sorted(selected_codes - found_codes)
    if missing_codes:
        raise ValueError(f'模块不存在或已停用: {", ".join(missing_codes)}')

    for module in modules:
        grant, created = CompanyModuleGrant.objects.get_or_create(
            company=company,
            module=module,
            defaults={
                'enabled': True,
                'created_by': actor,
                'updated_by': actor,
            }
        )
        if not created and not grant.enabled:
            grant.enabled = True
            grant.updated_by = actor
            grant.save(update_fields=['enabled', 'updated_by', 'updated_at'])
        elif not created:
            grant.updated_by = actor
            grant.save(update_fields=['updated_by', 'updated_at'])

    CompanyModuleGrant.objects.filter(company=company).exclude(
        module__code__in=selected_codes
    ).update(enabled=False, updated_by_id=actor.id, updated_at=timezone.now())


@system_super_admin_required
def system_admin_view(request):
    return render(request, 'management/system_admin.html', {
        'active_nav': 'system_admin',
        'active_page': 'system_admin',
    })


@require_GET
@system_super_admin_required
def system_modules_api(request):
    _ensure_default_system_modules()
    modules = SystemModule.objects.filter(is_active=True).order_by('category', 'sort_order', 'code')
    return JsonResponse({
        'success': True,
        'data': [_system_module_payload(module) for module in modules],
    })


@require_GET
@system_super_admin_required
def system_permissions_api(request):
    _ensure_company_admin_permission()
    permissions = PermissionConfig.objects.all().order_by('code').values(
        'id', 'code', 'name', 'description', 'category'
    )
    return JsonResponse({
        'success': True,
        'data': list(permissions),
        'company_admin_code': COMPANY_ADMIN_PERMISSION_CODE,
    })


@require_GET
@system_super_admin_required
def system_companies_api(request):
    try:
        page = max(int(request.GET.get('page', 1)), 1)
        page_size = int(request.GET.get('page_size', 20))
        if page_size not in [10, 20, 50, 100]:
            page_size = 20

        search = request.GET.get('search', '').strip()
        status = request.GET.get('status', '').strip()

        queryset = Company.objects.annotate(
            user_count=Count('users', distinct=True),
            admin_count=Count(
                'users',
                filter=Q(users__permission_configs__code=COMPANY_ADMIN_PERMISSION_CODE),
                distinct=True,
            ),
        ).prefetch_related('module_grants__module').order_by('-created_at', '-id')

        if search:
            queryset = queryset.filter(Q(name__icontains=search) | Q(code__icontains=search))
        if status in ['1', '2']:
            queryset = queryset.filter(status=int(status))

        total = queryset.count()
        companies = queryset[(page - 1) * page_size: page * page_size]

        stats = {
            'company_count': Company.objects.count(),
            'active_company_count': Company.objects.filter(status=1).count(),
            'disabled_company_count': Company.objects.filter(status=2).count(),
            'user_count': User.objects.count(),
        }

        return JsonResponse({
            'success': True,
            'data': [_company_payload(company) for company in companies],
            'total': total,
            'page': page,
            'page_size': page_size,
            'stats': stats,
        })
    except Exception as exc:
        traceback.print_exc()
        return JsonResponse({'success': False, 'error': f'获取公司列表失败: {exc}'}, status=500)


@require_POST
@system_super_admin_required
def system_company_create_api(request):
    try:
        data = _json_body(request)
        name = (data.get('name') or '').strip()
        code = _normalize_company_code(data.get('code'))

        if not name:
            return JsonResponse({'success': False, 'error': '公司名称不能为空'}, status=400)
        if Company.objects.filter(name=name).exists():
            return JsonResponse({'success': False, 'error': '公司名称已存在'}, status=400)
        if code and Company.objects.filter(code=code).exists():
            return JsonResponse({'success': False, 'error': '公司代码已存在'}, status=400)

        with transaction.atomic():
            company = Company.objects.create(
                name=name,
                code=code,
                status=_company_status(data.get('status'), 1),
                settings=_parse_settings(data.get('settings')),
            )

            owner = None
            if data.get('owner_username') or data.get('username'):
                owner = _create_company_owner(company, data)

            if 'modules' in data:
                _sync_company_modules(company, data.get('modules'), request.user)

            _log_system_action(
                request,
                company,
                UserOperationLog.OperationType.USER_CREATE,
                f'平台总后台创建公司: {company.name}({company.id})'
            )
            if owner:
                _log_system_action(
                    request,
                    company,
                    UserOperationLog.OperationType.USER_CREATE,
                    f'平台总后台创建公司主账号: {owner.username}({owner.id})'
                )

        return JsonResponse({
            'success': True,
            'message': '公司创建成功',
            'company': _company_payload(company),
            'owner_id': owner.id if owner else None,
        })
    except ValueError as exc:
        return JsonResponse({'success': False, 'error': str(exc)}, status=400)
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': '请求数据不是有效 JSON'}, status=400)
    except Exception as exc:
        traceback.print_exc()
        return JsonResponse({'success': False, 'error': f'创建公司失败: {exc}'}, status=500)


@require_POST
@system_super_admin_required
def system_company_update_api(request, company_id):
    try:
        data = _json_body(request)
        try:
            company = Company.objects.get(id=company_id)
        except Company.DoesNotExist:
            return JsonResponse({'success': False, 'error': '公司不存在'}, status=404)

        with transaction.atomic():
            if 'name' in data:
                name = (data.get('name') or '').strip()
                if not name:
                    return JsonResponse({'success': False, 'error': '公司名称不能为空'}, status=400)
                if Company.objects.exclude(id=company.id).filter(name=name).exists():
                    return JsonResponse({'success': False, 'error': '公司名称已存在'}, status=400)
                company.name = name

            if 'code' in data:
                code = _normalize_company_code(data.get('code'))
                if code and Company.objects.exclude(id=company.id).filter(code=code).exists():
                    return JsonResponse({'success': False, 'error': '公司代码已存在'}, status=400)
                company.code = code

            if 'status' in data:
                company.status = _company_status(data.get('status'), company.status)

            if 'settings' in data:
                company.settings = _parse_settings(data.get('settings'))

            company.save()

            if 'modules' in data:
                _sync_company_modules(company, data.get('modules'), request.user)

            _log_system_action(
                request,
                company,
                UserOperationLog.OperationType.USER_UPDATE,
                f'平台总后台更新公司: {company.name}({company.id})'
            )

        return JsonResponse({
            'success': True,
            'message': '公司更新成功',
            'company': _company_payload(company),
        })
    except ValueError as exc:
        return JsonResponse({'success': False, 'error': str(exc)}, status=400)
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': '请求数据不是有效 JSON'}, status=400)
    except Exception as exc:
        traceback.print_exc()
        return JsonResponse({'success': False, 'error': f'更新公司失败: {exc}'}, status=500)


@require_POST
@system_super_admin_required
def system_company_owner_create_api(request, company_id):
    try:
        data = _json_body(request)
        try:
            company = Company.objects.get(id=company_id)
        except Company.DoesNotExist:
            return JsonResponse({'success': False, 'error': '公司不存在'}, status=404)

        with transaction.atomic():
            owner = _create_company_owner(company, data)
            _log_system_action(
                request,
                company,
                UserOperationLog.OperationType.USER_CREATE,
                f'平台总后台创建公司主账号: {owner.username}({owner.id})'
            )

        return JsonResponse({
            'success': True,
            'message': '公司主账号创建成功',
            'owner': {
                'id': owner.id,
                'username': owner.username,
                'first_name': owner.first_name,
            },
        })
    except ValueError as exc:
        return JsonResponse({'success': False, 'error': str(exc)}, status=400)
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': '请求数据不是有效 JSON'}, status=400)
    except Exception as exc:
        traceback.print_exc()
        return JsonResponse({'success': False, 'error': f'创建公司主账号失败: {exc}'}, status=500)
