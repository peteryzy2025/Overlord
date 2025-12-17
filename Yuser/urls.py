# Yuser/urls.py
from django.urls import path
from Yuser.view_yuser import (
    assessment_management_view,
    # 模板管理
    api_template_list,
    api_template_create,
    api_template_detail,
    api_template_update,
    api_template_delete,
    # 实例管理
    api_instance_list,
    api_instance_create,
    api_instance_detail,
    api_instance_update,
    api_instance_delete,
    # 辅助
    api_get_users_for_instance,
    api_template_copy
)

urlpatterns = [
    # 主页面
    path('assessment/', assessment_management_view, name='assessment_management'),

    # 模板管理API
    path('api/templates/', api_template_list, name='api_template_list'),
    path('api/templates/create/', api_template_create, name='api_template_create'),
    path('api/templates/<int:template_id>/', api_template_detail, name='api_template_detail'),
    path('api/templates/<int:template_id>/update/', api_template_update, name='api_template_update'),
    path('api/templates/<int:template_id>/delete/', api_template_delete, name='api_template_delete'),

    # 实例管理API
    path('api/instances/', api_instance_list, name='api_instance_list'),
    path('api/instances/create/', api_instance_create, name='api_instance_create'),
    path('api/instances/<int:instance_id>/', api_instance_detail, name='api_instance_detail'),
    path('api/instances/<int:instance_id>/update/', api_instance_update, name='api_instance_update'),
    path('api/instances/<int:instance_id>/delete/', api_instance_delete, name='api_instance_delete'),

    # 辅助API
    path('api/users/for_instance/', api_get_users_for_instance, name='api_users_for_instance'),
    path('api/templates/<int:template_id>/copy/', api_template_copy, name='api_template_copy'),
]
