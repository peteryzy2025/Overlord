"""
主题切换中间件
自动为每个请求加载用户的主题偏好，实现全站主题持久化
"""


class ThemeMiddleware:
    """
    从数据库加载已登录用户的主题设置，并添加到request.theme
    未登录用户默认使用'light'主题
    """

    def __init__(self, get_response):
        """
        中间件初始化，Django启动时执行一次
        :param get_response: 下一个中间件或视图的回调函数
        """
        self.get_response = get_response

    def __call__(self, request):
        """
        每个请求都会调用此方法
        :param request: HTTP请求对象
        :return: HTTP响应对象
        """
        # ===== 核心逻辑：加载主题 =====
        if request.user.is_authenticated:
            # 已登录用户：从数据库的theme字段读取
            # 使用getattr防止theme字段不存在时出现AttributeError
            request.theme = getattr(request.user, 'theme', 'light')
        else:
            # 未登录用户：默认浅色主题
            request.theme = 'light'

        # 继续处理请求链（调用下一个中间件或视图）
        response = self.get_response(request)

        return response


