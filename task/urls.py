# Task/urls.py

from django.urls import path
from task.view import approval_views, task_api_views, task_page_views, product_views, task_upload_views,task_detail_views
app_name = 'task'  # 命名空间
urlpatterns = [
    # 页面路由
    path('task/create/', task_page_views.task_create_page, name='task_create_page'),
    path('task/approval/create/', approval_views.approval_create_page, name='approval_create_page'),
    path('task/approval/drafts/', approval_views.approval_draft_page, name='approval_draft_page'),
    path('task/approval/leader/', approval_views.approval_leader_page, name='approval_leader_page'),
    path('task/product/create/', product_views.product_create_page, name='product_create_page'),
    path('task/product/list/', product_views.product_list_page, name='product_list_page'),
    path('task/list/', task_page_views.task_list_page, name='task_list_page'),

    # API路由
    # 产品需求相关
    path('api/products/create/', product_views.create_product_requirement_api, name='create_product_requirement'),
    path('api/products/list/', product_views.get_product_requirements_api, name='get_product_requirements'),
    path('api/products/recrawl/', product_views.recrawl_product_requirement_api, name='recrawl_product_requirement'),
    path('api/products/reject/', product_views.reject_product_requirements_api, name='reject_product_requirements'),
    path('api/products/<int:pk>/', product_views.get_product_requirement_detail_api, name='get_product_requirement_detail'),
    path('api/products/<int:pk>/update/', product_views.update_product_requirement_api, name='update_product_requirement'),
    path('api/products/<int:pk>/claim/', product_views.claim_product_requirement_api, name='claim_product_requirement'),
    path('api/products/<int:pk>/complete/', product_views.complete_product_design_api, name='complete_product_design'),
    path('api/products/<int:pk>/export/', product_views.export_product_requirement_excel_api, name='export_product_requirement'),
# 🔥 新增：状态选项API
    path('api/products/status-choices/', product_views.get_status_choices_api, name='get_status_choices'),
    # 店铺相关
    path('api/tasks/shops/', task_api_views.get_available_shops_api, name='get_available_shops'),
    path('api/task/approvals/ad/meta/', approval_views.approval_meta_api, name='approval_meta_api'),
    path('api/task/approvals/ad/stores/', approval_views.approval_stores_api, name='approval_stores_api'),
    path('api/task/approvals/ad/drafts/', approval_views.approval_draft_list_api, name='approval_draft_list_api'),
    path('api/task/approvals/ad/drafts/<int:approval_id>/', approval_views.approval_draft_detail_api, name='approval_draft_detail_api'),
    path('api/task/approvals/ad/asins/', approval_views.approval_asins_api, name='approval_asins_api'),
    path('api/task/approvals/ad/create/', approval_views.create_ad_approval_api, name='create_ad_approval_api'),
    path('api/task/approvals/leader/list/', approval_views.approval_leader_list_api, name='approval_leader_list_api'),
    path('api/task/approvals/leader/action/', approval_views.approval_leader_action_api, name='approval_leader_action_api'),

    # 所有者相关
    path('api/tasks/available-owners/', task_api_views.get_available_owners_api, name='get_available_owners'),

    # 迪唯账号列表
    path('api/tasks/diwei-accounts/', task_api_views.get_diwei_accounts_api, name='get_diwei_accounts'),

    # 任务单号
    path('api/tasks/generate-no/', task_api_views.generate_task_no_api, name='generate_task_no'),

    # 图库路径建议
    path('api/tasks/gallery-paths/suggest/', task_api_views.suggest_gallery_paths_api, name='suggest_gallery_paths'),

    # 任务管理
    path('api/external/tasks/update-status/', task_api_views.external_update_task_status_api,
         name='external_update_task_status'),
    path('api/external/tasks/detail/', task_api_views.external_get_task_detail_api,
         name='external_get_task_detail'),
    path('api/external/tasks/subtasks/update-status/', task_api_views.external_update_subtask_status_api,
         name='external_update_subtask_status'),
    path('api/external/tasks/subtasks/detail/', task_api_views.external_get_subtask_detail_api,
         name='external_get_subtask_detail'),
    path('api/external/tasks/subtasks/update-detail/', task_api_views.external_update_subtask_detail_api,
         name='external_update_subtask_detail'),
    path('api/tasks/list/', task_api_views.get_tasks_list_api, name='get_tasks_list'),
    path('api/tasks/stats/', task_api_views.get_task_stats_api, name='get_task_stats'),
    path('api/tasks/creators/', task_api_views.get_task_creators_api, name='get_task_creators'),
    path('api/tasks/create/', task_api_views.create_task_api, name='create_task'),
    path('api/tasks/<int:task_id>/delete/', task_api_views.delete_task_api, name='delete_task'),
    path('api/tasks/save-draft/', task_api_views.save_draft_api, name='save_draft'),
    path('api/tasks/drafts/', task_api_views.get_drafts_api, name='get_drafts'),
    path('api/tasks/drafts/latest/', task_api_views.get_latest_draft_api, name='get_latest_draft'),
    path('api/tasks/drafts/<int:task_id>/delete/', task_api_views.delete_draft_api, name='delete_draft'),

    # 模板管理
    path('api/tasks/templates/', task_api_views.get_task_templates_api, name='get_task_templates'),
    path('api/tasks/templates/save/', task_api_views.save_template_api, name='save_template'),
    path('api/tasks/templates/<int:template_id>/load/', task_api_views.load_template_api, name='load_template'),
    path('api/tasks/templates/<int:template_id>/delete/', task_api_views.delete_template_api, name='delete_template'),

    # ===== 文件上传相关（新增）=====
    # Amazon店铺列表（用于文件名校验）
    path('api/tasks/amazon-shops/', task_upload_views.get_amazon_shops_api, name='get_amazon_shops'),

    # 临时文件上传（预校验店名）
    path('api/tasks/upload-temp/', task_upload_views.upload_temp_file_api, name='upload_temp_file'),

    # ===== 任务详情页（新增）=====
    # 页面路由
    path('task/detail/<int:task_id>/', task_detail_views.task_detail_page, name='task_detail'),

    # API路由
    path('api/tasks/<int:task_id>/detail/', task_detail_views.get_task_detail_api, name='get_task_detail'),

    # 影刀接口
    path('api/tasks/amazon-upload/pending-files/', task_detail_views.get_pending_files_api, name='get_pending_files'),
    path('api/tasks/amazon-upload/update-status/', task_detail_views.update_upload_status_api,
         name='update_upload_status'),
    
    # ===== DIVI 产品相关接口 =====
    path('api/divi/products/', task_api_views.get_divi_products_api, name='get_divi_products'),
    path('api/divi/products/<int:product_id>/detail/', task_api_views.get_divi_product_detail_api, name='get_divi_product_detail'),
]
