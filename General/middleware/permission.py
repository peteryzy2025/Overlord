# General/middleware.py

from django.shortcuts import HttpResponseRedirect
from django.http import JsonResponse


class PermissionMiddleware:
    """
    权限控制中间件：只有拥有code=555的PermissionConfig的用户才能访问管理功能
    只拦截明确需要管控的路径，其他路径完全不受影响
    """

    # 需要权限管控的URL路径列表
    PROTECTED_PATHS = [
        '/management/',  # 管理中心页面及子页面
        '/api/users/',  # 用户管理API
        '/api/roles/',  # 角色管理API
        #'/api/amazon-shops/',  # Amazon店铺管理API
        #'/amazon-management/',  # Amazon店铺管理页面
    ]

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # 检查当前路径是否需要权限验证
        if self._is_protected_path(request.path):
            # 未登录或无555权限，拒绝访问
            if not request.user.is_authenticated or not self._has_permission_555(request.user):
                return self._redirect_or_forbid(request)

        # 通过检查，继续处理请求（不影响任何其他路径）
        return self.get_response(request)

    def _is_protected_path(self, path):
        """检查URL是否在需要管控的路径列表中"""
        for protected_path in self.PROTECTED_PATHS:
            if path.startswith(protected_path):
                return True
        return False

    def _has_permission_555(self, user):
        """检查用户是否拥有code=555的业务权限"""
        if not hasattr(user, 'permission_configs'):
            return False
        try:
            return user.permission_configs.filter(code=555).exists()
        except Exception:
            return False

    def _redirect_or_forbid(self, request):
        """
        智能响应：
        - API请求返回JSON格式的403错误
        - 页面请求重定向到/main/
        """
        is_api_request = (
                request.path.startswith('/api/') or
                request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        )

        if is_api_request:
            return JsonResponse({
                'success': False,
                'error': '权限不足，无法访问管理功能'
            }, status=403)
        else:
            return HttpResponseRedirect('/main/')