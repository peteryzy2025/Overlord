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
            reverse('general:login'),
            reverse('general:csrf_token'),
            '/admin/',  # 保留 admin 的独立认证
            '/inventory/api/import/',  # 库存上传接口白名单
            '/api/trend/search/', # 查侵权
            '/dw-data/',  # 迪唯产业大数据模型页面
            '/api/market-categories/',  # 迪唯分类API
            '/api/niche-markets/',  # 迪唯市场数据API
        ]

    def __call__(self, request):
        # 检查是否在白名单中
        if request.path_info in self.white_list:
            return self.get_response(request)

        # 对外开放接口：允许匿名访问
        if request.path_info.startswith('/api/external/tasks/'):
            return self.get_response(request)
        if request.path_info.startswith('/api/external/amazon-shops/'):
            return self.get_response(request)

        # 检查静态文件和 media 文件
        if request.path_info.startswith(('/static/', '/media/')):
            return self.get_response(request)
        # ===== 新增：影刀请求特殊放行 =====
        if request.path_info.startswith('/api/rpa/'):
            # 如果是影刀接口，检查 X-RPA-Secret header，有就放行
            if request.headers.get('X-RPA-Secret'):
                return self.get_response(request)
            # 如果没有 secret，还是返回 401（防止外部直接访问）
            return JsonResponse({
                'success': False,
                'error': 'RPA接口需要 X-RPA-Secret 认证'
            }, status=401)
        # 检查用户是否已认证
        if not request.user.is_authenticated:
            # AJAX 请求返回 JSON
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': False,
                    'error': '未登录或会话已过期',
                    'redirect_url': reverse('general:login')
                }, status=401)

            # 普通请求重定向到登录页
            return redirect(f"{reverse('general:login')}?next={request.path_info}")

        return self.get_response(request)
