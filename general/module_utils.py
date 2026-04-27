from functools import wraps

from django.db import DatabaseError
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone

from general.models import CompanyModuleGrant


MODULE_USER_PERMISSION_CODES = {
    'logistics': {5, 6, 555, 557},
    'theme': {8, 555},
    'infringement': {556, 555},
}


def get_user_permission_code_set(user):
    if not user or not getattr(user, 'is_authenticated', False):
        return set()

    try:
        return set(user.permission_configs.values_list('code', flat=True))
    except DatabaseError:
        return set()


def user_has_module_permission(user, module_code):
    required_codes = MODULE_USER_PERMISSION_CODES.get(module_code)
    if not required_codes:
        return True

    return bool(get_user_permission_code_set(user) & required_codes)


def company_has_module(company, module_code, at_time=None):
    """判断公司是否已开通且当前有效某个系统模块。"""
    if not company or not module_code:
        return False

    at_time = at_time or timezone.now()
    try:
        return CompanyModuleGrant.objects.filter(
            company=company,
            module__code=module_code,
            module__is_active=True,
            enabled=True,
        ).filter(
            Q(starts_at__isnull=True) | Q(starts_at__lte=at_time),
            Q(expires_at__isnull=True) | Q(expires_at__gte=at_time),
        ).exists()
    except DatabaseError:
        return False


def user_company_has_module(user, module_code, at_time=None):
    """基于用户所属公司判断模块授权。平台总管理员不绕过公司授权。"""
    if not user or not getattr(user, 'is_authenticated', False):
        return False
    return company_has_module(getattr(user, 'company', None), module_code, at_time=at_time)


def user_can_access_module(user, module_code, at_time=None):
    return user_company_has_module(user, module_code, at_time=at_time) and user_has_module_permission(user, module_code)


def get_user_company_module_codes(user, at_time=None):
    """返回当前用户所属公司已开通且当前有效的模块编码集合。"""
    if not user or not getattr(user, 'is_authenticated', False):
        return set()

    company = getattr(user, 'company', None)
    if not company:
        return set()

    at_time = at_time or timezone.now()
    try:
        return set(
            CompanyModuleGrant.objects.filter(
                company=company,
                module__is_active=True,
                enabled=True,
            ).filter(
                Q(starts_at__isnull=True) | Q(starts_at__lte=at_time),
                Q(expires_at__isnull=True) | Q(expires_at__gte=at_time),
            ).values_list('module__code', flat=True)
        )
    except DatabaseError:
        return set()


def get_user_accessible_company_module_codes(user, at_time=None):
    return {
        module_code
        for module_code in get_user_company_module_codes(user, at_time=at_time)
        if user_has_module_permission(user, module_code)
    }


def is_api_request(request):
    """判断请求是否期望 JSON 响应。"""
    return (
        request.path.startswith('/api/')
        or '/api/' in request.path
        or request.headers.get('x-requested-with') == 'XMLHttpRequest'
        or 'application/json' in request.headers.get('accept', '')
    )


def permission_denied_response(request, message='无权访问该模块', status=403):
    """页面与 API 共用的拒绝访问响应。"""
    if is_api_request(request):
        return JsonResponse({
            'success': False,
            'message': message,
        }, status=status)

    return render(request, 'error/403.html', {
        'message': message,
    }, status=status)


def module_access_required(module_code, module_name=None):
    """按公司模块授权保护页面与 API。"""
    display_name = module_name or module_code

    def decorator(view_func):
        @wraps(view_func)
        def wrapped_view(request, *args, **kwargs):
            if not getattr(request.user, 'is_authenticated', False):
                if is_api_request(request):
                    return JsonResponse({
                        'success': False,
                        'message': '未登录或会话已过期',
                    }, status=401)
                return redirect('general:login')

            if user_company_has_module(request.user, module_code):
                if user_has_module_permission(request.user, module_code):
                    return view_func(request, *args, **kwargs)
                return permission_denied_response(
                    request,
                    f'当前用户没有{display_name}权限，请询问公司管理员。',
                    status=403,
                )

            return permission_denied_response(
                request,
                f'当前公司未开通{display_name}，请联系平台管理员授权。',
                status=403,
            )

        return wrapped_view

    return decorator
