from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required(login_url='/login/')
def amazon_order_management_page(request):
    """亚马逊订单管理页面渲染"""
    theme = request.COOKIES.get('theme', 'light')
    return render(request, 'amazon_order_management.html', {
        'theme': theme,
        'active_nav': 'amazon_orders'
    })