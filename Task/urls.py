# Task/urls.py

from django.urls import path
from task.view import task_api_views, task_page_views, product_views

app_name = 'task'  # 命名空间
urlpatterns = [
    # 页面路由
    path('task/create/', task_page_views.task_create_page, name='task_create_page'),
    path('task/product/create/', product_views.product_create_page, name='product_create_page'),
    path('task/product/list/', product_views.product_list_page, name='product_list_page'),
    path('task/list/', task_page_views.task_list_page, name='task_list_page'),

    # API路由
    # 产品需求相关
    path('api/products/create/', product_views.create_product_requirement_api, name='create_product_requirement'),
    path('api/products/list/', product_views.get_product_requirements_api, name='get_product_requirements'),
    path('api/products/<int:pk>/', product_views.get_product_requirement_detail_api, name='get_product_requirement_detail'),
    path('api/products/<int:pk>/update/', product_views.update_product_requirement_api, name='update_product_requirement'),

    # 店铺相关
    path('api/tasks/shops/', task_api_views.get_available_shops_api, name='get_available_shops'),

    # 所有者相关
    path('api/tasks/available-owners/', task_api_views.get_available_owners_api, name='get_available_owners'),

    # 任务单号
    path('api/tasks/generate-no/', task_api_views.generate_task_no_api, name='generate_task_no'),

    # 图库路径建议
    path('api/tasks/gallery-paths/suggest/', task_api_views.suggest_gallery_paths_api, name='suggest_gallery_paths'),

    # 任务管理
    path('api/tasks/create/', task_api_views.create_task_api, name='create_task'),
    path('api/tasks/save-draft/', task_api_views.save_draft_api, name='save_draft'),
    path('api/tasks/drafts/', task_api_views.get_drafts_api, name='get_drafts'),
    path('api/tasks/drafts/latest/', task_api_views.get_latest_draft_api, name='get_latest_draft'),
    path('api/tasks/drafts/<int:task_id>/delete/', task_api_views.delete_draft_api, name='delete_draft'),

    # 模板管理
    path('api/tasks/templates/', task_api_views.get_task_templates_api, name='get_task_templates'),
    path('api/tasks/templates/save/', task_api_views.save_template_api, name='save_template'),
    path('api/tasks/templates/<int:template_id>/load/', task_api_views.load_template_api, name='load_template'),
    path('api/tasks/templates/<int:template_id>/delete/', task_api_views.delete_template_api, name='delete_template'),
]