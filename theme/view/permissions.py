from functools import wraps

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect

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
    @login_required
    @wraps(view_func)
    def wrapped_view(request, *args, **kwargs):
        if can_access_theme_admin_pages(request.user):
            return view_func(request, *args, **kwargs)

        if request.path.startswith('/api/') or request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({
                'success': False,
                'message': '无权访问该 Theme 页面',
            }, status=403)

        return redirect('general:main')

    return wrapped_view
