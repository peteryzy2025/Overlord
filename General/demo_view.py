# General/views_performance.py

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.csrf import csrf_exempt
from django.db import transaction
from django.db.models import Q, Sum
from general.models import User, OperationalAccount, GroupPerformanceTarget, PersonalPerformanceTarget
import json
import traceback
from datetime import datetime


# ==========================================
# 页面渲染
# ==========================================

@login_required
def demo_view(request):
    """渲染绩效管理页面"""
    # 判断当前用户权限
    context = {
        'can_manage_group': request.user.can_manage_group_targets(),
        'is_group_leader': request.user.is_group_leader(),
        'user_ops_group': request.user.get_ops_group(),
    }
    return render(request, 'demo1.html', context)