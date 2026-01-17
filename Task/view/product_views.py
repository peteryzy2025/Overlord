from django.shortcuts import render
from django.contrib.auth.decorators import login_required

@login_required
def product_create_page(request):
    """
    产品需求创建页面
    """
    return render(request, 'product_create.html')
