# Amazon/view/views_dashboard.py
# 驾驶舱和排名页面视图

from django.contrib.auth.decorators import login_required
from django.shortcuts import render


def has_perm_code(user, code):
    """检查用户是否有特定权限码（使用 permission_configs）"""
    if not user or not user.is_authenticated:
        return False
    try:
        code_int = int(code)
        return user.permission_configs.filter(code=code_int).exists()
    except (ValueError, TypeError):
        return False


@login_required(login_url='/login/')
def dashboard_page(request):
    """
    Amazon驾驶舱页面
    路径: /dashboard/
    """
    return render(request, 'dashboard.html', {
        'active_page': 'dashboard',
        'active_nav': 'dashboard'
    })


@login_required(login_url='/login/')
def ranking_page(request):
    """
    登神长阶 - 运营排名页面
    路径: /ranking/
    """
    user = request.user
    # 判断是否为管理员（555超管或 553 运营管理员）
    is_admin = has_perm_code(user, '555') or has_perm_code(user, '553')

    return render(request, 'ranking.html', {
        'active_page': 'ranking',
        'active_nav': 'dashboard',
        'is_admin': is_admin,
        'current_user_id': user.id
    })
