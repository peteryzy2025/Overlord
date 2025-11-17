import json
from django.shortcuts import redirect
from django.urls import reverse
from django.http import JsonResponse


class LoginRequiredMiddleware:
    """
    登录验证中间件
    - 未登录用户访问非白名单页面时自动跳转登录页
    - 支持 AJAX 请求返回 JSON 格式错误
    """

    def __init__(self, get_response):
        self.get_response = get_response
        # 白名单：不需要登录即可访问的 URL
        self.white_list = [
            reverse('login'),
            reverse('csrf_token'),
            '/admin/',  # 保留 admin 的独立认证
        ]

    def __call__(self, request):
        # 检查是否在白名单中
        if request.path_info in self.white_list:
            return self.get_response(request)

        # 检查静态文件和 media 文件
        if request.path_info.startswith(('/static/', '/media/')):
            return self.get_response(request)

        # 检查用户是否已认证
        if not request.user.is_authenticated:
            # AJAX 请求返回 JSON
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': False,
                    'error': '未登录或会话已过期',
                    'redirect_url': reverse('login')
                }, status=401)

            # 普通请求重定向到登录页
            return redirect(f"{reverse('login')}?next={request.path_info}")

        return self.get_response(request)