# Amazon/view/views_dashboard.py
# 驾驶舱和排名页面视图

from django.contrib.auth.decorators import login_required
from django.shortcuts import render


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
    return render(request, 'ranking.html', {
        'active_page': 'ranking',
        'active_nav': 'dashboard'
    })
