# General/urls.py
from django.urls import path
from general import (
    views,
    views_amazon_management,
    views_temu_management,
    views_project_management,
    views_performance,
    views_announcement_management,
    views_profile
)
from general.view import view_operation_log, views_general, views_user_management, views_system_admin
from api.general import group_and_ops
from general.api import divi_account_api

app_name = 'general'

urlpatterns = [

    # ========== 重构 ==============
    path('api/ops/list', views_general.get_ops_list, name='get_ops_list_api'),
    path('api/ops-groups/list', views_general.get_ops_groups_api, name='get_ops_groups_list_api'),

    # ========== 平台总后台（仅 user.id == 555） ==========
    path('system-admin/', views_system_admin.system_admin_view, name='system_admin'),
    path('api/system-admin/modules/', views_system_admin.system_modules_api,
         name='system_modules_api'),
    path('api/system-admin/permissions/', views_system_admin.system_permissions_api,
         name='system_permissions_api'),
    path('api/system-admin/companies/', views_system_admin.system_companies_api,
         name='system_companies_api'),
    path('api/system-admin/companies/create/', views_system_admin.system_company_create_api,
         name='system_company_create_api'),
    path('api/system-admin/companies/<int:company_id>/update/',
         views_system_admin.system_company_update_api, name='system_company_update_api'),
    path('api/system-admin/companies/<int:company_id>/owners/create/',
         views_system_admin.system_company_owner_create_api, name='system_company_owner_create_api'),

    # ========== 通用运营分组和人员查询接口（新） ==========
    path('api/general/ops-groups/', group_and_ops.get_ops_groups_api, name='api_general_ops_groups'),
    path('api/general/operators/', group_and_ops.get_operators_api, name='api_general_operators'),

    # ========== 人员管理（新增/改造） ==========
    # 页面视图
    path('management/users/', views_user_management.user_management_view, name='user_management'),

    # 用户CRUD API
    path('api/users/', views_user_management.get_users_api, name='get_users_api'),
    path('api/users/create/', views_user_management.create_user_api, name='create_user_api'),
    path('api/users/<int:user_id>/update/', views_user_management.update_user_api, name='update_user_api'),
    path('api/users/bulk-permissions/', views_user_management.bulk_update_permissions_api,
         name='bulk_update_permissions_api'),
    path('api/users/bulk-department/', views_user_management.bulk_update_department_api,
         name='bulk_update_department_api'),

    # 辅助数据API
    path('api/roles/', views_user_management.get_roles_api, name='get_roles_api'),
    path('api/permissions/', views_user_management.get_permission_configs_api, name='get_permission_configs_api'),
    path('api/users/ops-groups/', views_user_management.get_ops_groups_api, name='get_users_ops_groups_api'),
    path('api/users/departments/', views_user_management.get_departments_api, name='get_users_departments_api'),
    path('api/company/projects/', views_user_management.get_company_projects_api, name='get_company_projects_api'),
    path('api/company/users/', views_user_management.get_company_users_api, name='get_company_users_api'),
    # 新增：获取公司项目列表

    # ========== 基础系统 ==========
    path('test-error/', views.test_error, name='test_error'),
    path('', views.main_page),
    path('login-v2/', views.user_login_v2, name='login_v2'),
    path('login/', views.user_login, name='login'),
    path('logout/', views.user_logout, name='logout'),
    path('main/', views.main_page, name='main'),
    path('management/', views.management_page, name='management'),
    path('csrf/', views.csrf_token_view, name='csrf_token'),
    path('api/update-theme/', views.update_theme, name='update_theme'),
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
    path('api/external/amazon-shops/', views_amazon_management.external_amazon_shops_api,
         name='external_amazon_shops_api'),
    path('api/external/divi-account/', divi_account_api.divi_account_query_api,
         name='external_divi_account_api'),
    path('api/amazon-shops/', views_amazon_management.get_amazon_shops_api, name='get_amazon_shops_api'),
    path('api/amazon-shops/create/', views_amazon_management.create_amazon_shop_api, name='create_amazon_shop_api'),
    path('api/amazon-shops/bulk-update-project/', views_amazon_management.bulk_update_project_api, name='bulk_update_project_api'),
    path('api/amazon-shops/bulk-update-operator/', views_amazon_management.bulk_update_operator_api, name='bulk_update_operator_api'),
    path('api/amazon-shops/bulk-update-authorized-users/', views_amazon_management.bulk_update_authorized_users_api, name='bulk_update_authorized_users_api'),
    path('api/amazon-shops/<int:shop_id>/authorized-users/', views_amazon_management.update_authorized_users_api, name='update_authorized_users_api'),
    path('api/amazon-shops/<int:shop_id>/update/', views_amazon_management.update_amazon_shop_api,
         name='update_amazon_shop_api'),
    path('api/operators/', views_amazon_management.get_all_operators_api, name='get_operators_api'),
    path('api/ops-groups/', views_amazon_management.get_all_ops_groups_api, name='get_ops_groups_api'),
    path('api/customers/', views_amazon_management.get_customers_api, name='get_customers_api'),

    # ========== 项目管理 ==========
    path('management/projects/', views_project_management.project_management_view, name='project_management'),
    path('api/projects/', views_project_management.get_projects_api, name='get_projects_api'),
    path('api/projects/logistics-choices/', views_project_management.get_logistics_choices_api,
         name='get_project_logistics_choices_api'),
    path('api/projects/create/', views_project_management.create_project_api, name='create_project_api'),
    path('api/projects/<int:project_id>/update/', views_project_management.update_project_api,
         name='update_project_api'),
    path('api/projects/<int:project_id>/logistics-codes/', views_project_management.save_project_logistics_codes_api,
         name='save_project_logistics_codes_api'),
    path('api/projects/<int:project_id>/logistics-codes/copy/',
         views_project_management.copy_project_logistics_codes_api,
         name='copy_project_logistics_codes_api'),

    # ========== Temu管理 ==========
    path('management/temu/', views_temu_management.temu_management_view, name='temu_management'),  # 移到人员管理下避免循环导入问题
    # ⚠️ URL冲突注意：下面这行与Amazon的'api/operators/'冲突，建议保留一个或改名
    # path('api/operators/', views_temu_management.get_all_operators_api, name='get_operators'),
    path('api/temu-customers/', views_temu_management.get_customers_api, name='get_temu_customers'),
    path('api/temu-shops/', views_temu_management.get_temu_shops_api, name='get_temu_shops'),
    path('api/temu-shops/create/', views_temu_management.create_temu_shop_api, name='create_temu_shop'),
    path('api/temu-shops/<int:shop_id>/update/', views_temu_management.update_temu_shop_api, name='update_temu_shop'),
    path('api/temu-shops/bulk-update-project/', views_temu_management.bulk_update_project_api, name='temu_bulk_update_project'),
    path('api/temu-shops/bulk-update-operator/', views_temu_management.bulk_update_operator_api, name='temu_bulk_update_operator'),
    path('api/temu-shops/<int:shop_id>/update-dimensions/', views_temu_management.update_temu_shop_dimensions_api, name='update_temu_shop_dimensions'),

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

    # ========== 个人中心 ==========
    path('profile/', views_profile.profile_view, name='profile'),

    # ========== 搜索 ==========
    path('search/', views.search_view, name='search'),
    path('api/profile/avatar/', views_profile.upload_avatar_api, name='profile_upload_avatar'),
    path('api/profile/basic-info/', views_profile.update_basic_info_api, name='profile_update_basic_info'),
    path('api/profile/password/', views_profile.change_password_api, name='profile_change_password'),
]
