"""
通用 API 路由配置
"""
from django.urls import path
from . import group_and_ops

urlpatterns = [
    # 运营分组和人员查询接口
    path('ops-groups/', group_and_ops.get_ops_groups_api, name='api_ops_groups'),
    path('operators/', group_and_ops.get_operators_api, name='api_operators'),
]
