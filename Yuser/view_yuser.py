# Yuser/view_yuser.py
import json
from django.shortcuts import render
from django.http import JsonResponse
from django.db import transaction
from django.db.models import Q, Sum, F, DecimalField
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from decimal import Decimal

from General.models import User, UserOperationLog
from Yuser.models import (
    AssessmentTemplate, AssessmentCategory, AssessmentGroup,
    AssessmentItem, ScoringRule, AssessmentInstance, AssessmentScore
)


def check_permission_555(user):
    """检查用户是否有555权限（考核管理权限）"""
    if not user.permission:
        return False
    return '555' in user.permission.split(',')


def assessment_management_view(request):
    # 考核数据
    target_orders = 1900  # 目标订单量
    actual_orders = 2042  # 实际订单量
    achievement_rate = (actual_orders / target_orders) * 100

    # 计算业绩目标达成得分（满分90）
    if achievement_rate >= 100:
        performance_score = 90
    elif achievement_rate >= 80:
        performance_score = 90 - ((100 - achievement_rate) * 2)
    else:
        performance_score = 0

    # 店铺激活情况（可以从数据库获取）
    shop_activation_count = 2  # 示例：激活了2个店铺

    context = {
        'target_orders': target_orders,
        'actual_orders': actual_orders,
        'achievement_rate': round(achievement_rate, 2),
        'performance_score': round(performance_score, 2),
        'current_period': '2025-12',
        'shop_activation_count': shop_activation_count,  # 传入店铺激活数
    }
    return render(request, 'assessment_management2.html', context)

# 在文件末尾添加以下两个视图函数

def amazon_operation_assessment_view(request):
    """
    亚马逊运营绩效考核视图
    业绩指标60% + 行为考核40%
    """
    # 测试数据 - 可从数据库获取
    target_orders = 1040  # 目标订单量
    actual_orders = 980   # 实际订单量（示例：未达标）
    achievement_rate = (actual_orders / target_orders) * 100

    # 计算业绩目标达成得分（满分90）
    if achievement_rate >= 100:
        performance_score = 90
    elif achievement_rate >= 80:
        performance_score = 90 - ((100 - achievement_rate) * 2)
    else:
        performance_score = 0

    context = {
        'employee_name': '蒋欣叶',
        'target_orders': target_orders,
        'actual_orders': actual_orders,
        'achievement_rate': round(achievement_rate, 2),
        'performance_score': round(performance_score, 2),
        'current_period': '2025-12',
    }
    return render(request, 'amazon_operation_assessment.html', context)


def amazon_assistant_assessment_view(request):
    """
    亚马逊运营助理绩效考核视图
    业绩指标30% + 行为考核70%
    """
    # 测试数据
    target_orders = 300   # 目标订单量
    actual_orders = 320   # 实际订单量（示例：超额完成）
    achievement_rate = (actual_orders / target_orders) * 100

    # 计算业绩目标达成得分（满分80）
    if achievement_rate >= 100:
        performance_score = 80
    elif achievement_rate >= 80:
        performance_score = 80 - ((100 - achievement_rate) * 2)
    else:
        performance_score = 0

    context = {
        'employee_name': '刘悦',
        'target_orders': target_orders,
        'actual_orders': actual_orders,
        'achievement_rate': round(achievement_rate, 2),
        'performance_score': round(performance_score, 2),
        'current_period': '2025-12',
    }
    return render(request, 'amazon_assistant_assessment.html', context)

