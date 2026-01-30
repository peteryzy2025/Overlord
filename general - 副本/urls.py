# General/urls.py
from django.urls import path
from general import (
    views,
    views_amazon_management,
    views_temu_management,
    views_performance,
    demo_view,
    views_announcement_management
)
from general.view import view_operation_log, views_general, views_user_management

app_name = 'general'

urlpatterns = [

    # ========== 重构 ==============
    path('api/ops/list', views_general.get_ops_list, name='get_ops_list_api'),
    path('api/ops-groups/list', views_general.get_ops_groups_api, name='get_ops_groups_list_api'),

    # ========== 人员管理（新增/改造） ==========
    # 页面视图
    path('management/users/', views_user_management.user_management_view, name='user_management'),

    # 用户CRUD API
    path('api/users/', views_user_management.get_users_api, name='get_users_api'),
    path('api/users/create/', views_user_management.create_user_api, name='create_user_api'),
    path('api/users/<int:user_id>/update/', views_user_management.update_user_api, name='update_user_api'),
    path('api/users/bulk-permissions/', views_user_management.bulk_update_permissions_api,
         name='bulk_update_permissions_api'),

    # 辅助数据API
    path('api/roles/', views_user_management.get_roles_api, name='get_roles_api'),
    path('api/permissions/', views_user_management.get_permission_configs_api, name='get_permission_configs_api'),
    path('api/users/ops-groups/', views_user_management.get_ops_groups_api, name='get_users_ops_groups_api'),
    path('api/company/projects/', views_user_management.get_company_projects_api, name='get_company_projects_api'),
    # 新增：获取公司项目列表

    # ========== 基础系统 ==========
    path('test-error/', views.test_error, name='test_error'),
    path('', views.main_page),
    path('login/', views.user_login, name='login'),
    path('logout/', views.user_logout, name='logout'),
    path('main/', views.main_page, name='main'),
    path('management/', views.management_page, name='management'),
    path('csrf/', views.csrf_token_view, name='csrf_token'),
    path('api/update-theme/', views.update_theme, name='update_theme'),
    path('demo1/', demo_view.demo_view),
    path('api/announcement/mark-as-read/', views.mark_announcement_as_read, name='mark_announcement_read'),

    # ========== 公告管理 ==========
    path('management/announcements/', views_announcement_management.announcement_management_view,
         name='announcement_management'),
    path('api/announcements/', views_announcement_management.get_announcements_api, name='get_announcements_api'),
    path('api/announcements/create/', views_announcement_management.create_announcement_api,
         name='create_announcement_api'),
    path('api/announcements/<int:announcement_id>/update/', views_announcement_management.update_announcement_api,
         name='update_announcement_api'),
    path('api/announcements/<int:announcement_id>/delete/', views_announcement_management.delete_announcement_api,
         name='delete_announcement_api'),
    path('api/announcements/<int:announcement_id>/read-records/',
         views_announcement_management.get_announcement_read_records_api, name='get_announcement_read_records_api'),

    # ========== Amazon店铺管理 ==========
    path('amazon-management/', views_amazon_management.amazon_management_view, name='amazon_management'),
    path('api/amazon-shops/', views_amazon_management.get_amazon_shops_api, name='get_amazon_shops_api'),
    path('api/amazon-shops/create/', views_amazon_management.create_amazon_shop_api, name='create_amazon_shop_api'),
    path('api/amazon-shops/<int:shop_id>/update/', views_amazon_management.update_amazon_shop_api,
         name='update_amazon_shop_api'),
    path('api/amazon-shops/bulk-update-project/', views_amazon_management.bulk_update_project_api,
         name='bulk_update_project_api'),
    path('api/operators/', views_amazon_management.get_all_operators_api, name='get_operators_api'),
    path('api/ops-groups/', views_amazon_management.get_all_ops_groups_api, name='get_ops_groups_api'),
    path('api/customers/', views_amazon_management.get_customers_api, name='get_customers_api'),

    # ========== Temu管理 ==========
    path('management/temu/', views_user_management.temu_management_view, name='temu_management'),  # 移到人员管理下避免循环导入问题
    # ⚠️ URL冲突注意：下面这行与Amazon的'api/operators/'冲突，建议保留一个或改名
    # path('api/operators/', views_temu_management.get_all_operators_api, name='get_operators'),
    path('api/temu-customers/', views_temu_management.get_customers_api, name='get_temu_customers'),
    path('api/temu-shops/', views_temu_management.get_temu_shops_api, name='get_temu_shops'),
    path('api/temu-shops/create/', views_temu_management.create_temu_shop_api, name='create_temu_shop'),
    path('api/temu-shops/<int:shop_id>/update/', views_temu_management.update_temu_shop_api, name='update_temu_shop'),

    # ========== 绩效管理 ==========
    path('performance/', views_performance.performance_targets_view, name='performance_targets'),
    path('api/performance/group_targets/', views_performance.get_group_targets_api, name='api_group_targets'),
    path('api/performance/group_targets/create/', views_performance.create_group_target_api, name='api_group_create'),
    path('api/performance/group_targets/<int:target_id>/update/', views_performance.update_group_target_api,
         name='api_group_update'),
    path('api/performance/personal_targets/', views_performance.get_personal_targets_api, name='api_personal_targets'),
    path('api/performance/personal_targets/batch/', views_performance.batch_create_personal_targets_api,
         name='api_personal_batch'),
    path('api/performance/ops_groups/', views_performance.get_ops_groups_for_filter_api, name='api_ops_groups_filter'),
    path('api/performance/operators_by_group/', views_performance.get_operators_by_group_api,
         name='api_operators_by_group'),

    # ========== 操作日志管理 ==========
    path('operation-logs/', view_operation_log.operation_log_view, name='operation_log_management'),
    path('api/users/all/', view_operation_log.get_all_users_api, name='get_all_users_api'),
    path('api/operation-log/types/', view_operation_log.get_operation_types_api, name='get_operation_types_api'),
    path('api/operation-logs/', view_operation_log.get_operation_logs_api, name='get_operation_logs_api'),
]