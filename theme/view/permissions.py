from functools import wraps

from general.module_utils import permission_denied_response, user_company_has_module
from universal.permission_utils import get_user_permission_codes


THEME_ACCESS_CODES = {555, 8}


def can_access_theme_admin_pages(user):
    """仅允许 555、8 访问指定 Theme 页面。"""
    if not user or not user.is_authenticated:
        return False

    user_codes = set(get_user_permission_codes(user))
    return bool(user_codes & THEME_ACCESS_CODES)


def theme_access_required(view_func):
    """保护 Theme 管理页面及其内部 API。"""
    @wraps(view_func)
    def wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return permission_denied_response(request, '未登录或会话已过期', status=401)

        if not user_company_has_module(request.user, 'theme'):
            return permission_denied_response(
                request,
                '当前公司未开通主题板块，请联系平台管理员授权。',
                status=403,
            )

        if can_access_theme_admin_pages(request.user):
            return view_func(request, *args, **kwargs)

        return permission_denied_response(request, '当前用户没有主题板块权限，请询问公司管理员。', status=403)

    return wrapped_view
