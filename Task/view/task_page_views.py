# Task/views/task_page_views.py

from django.shortcuts import render
from django.contrib.auth.decorators import login_required

@login_required(login_url='/login/')
def task_create_page(request):
    """创建任务页面"""
    return render(request, 'task_create.html', {
        'active_nav': 'task_manage'  # 根据您的侧边栏配置调整
    })

@login_required(login_url='/login/')
def task_list_page(request):
    """任务列表页面"""
    return render(request, 'task_list.html', {
        'active_nav': 'task_manage'
    })