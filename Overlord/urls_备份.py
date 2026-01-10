"""
URL configuration for Overlord project.

The `urlpatterns` list routes URLs to view. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function view
    1. Add an import:  from my_app import view
    2. Add a URL to urlpatterns:  path('', view.home, name='home')
Class-based view
    1. Add an import:  from other_app.view import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path
from general import views, views_user_management, views_amazon_management, views_temu_management, views_performance, \
    demo_view
from amazon import amazon_views, amazon_divi_views, amazon_order_views, amazon_views_jc, amazon_order_api_views, \
    views_ranking,amazon_jx_views

urlpatterns = [
    path('test-error/', views.test_error, name='test_error'),
    path('admin/', admin.site.urls),
    path('', views.main_page),
    path('login/', views.user_login, name='login'),  # 登录
    path('logout/', views.user_logout, name='logout'),  # 登出
    path('main/', views.main_page, name='main'),  # 主页
    path('management/', views.management_page, name='management'),  # 管理主页
    path('management/users/', views_user_management.user_management_view, name='user_management'),  # 管理用户主页
    path('api/users/create/', views_user_management.create_user_api, name='create_user_api'),  # 用户新增api
    path('api/users/<int:user_id>/update/', views_user_management.update_user_api, name='update_user_api'),  # 更新用户数据api
    path('management/temu/', views_user_management.temu_management_view, name='temu_management'),  # 管理temu店铺主页
    path('dashboard/', amazon_views.amazon_dashboard_page, name='dashboard'),  # 驾驶舱 从亚马逊驾驶舱改编
    path('api/amazon/operator-pie-chart/', amazon_views.get_operator_pie_chart_api, name='amazon_operator_pie_chart'),
    path('csrf/', views.csrf_token_view, name='csrf_token'),
    path('api/update-theme/', views.update_theme, name='update_theme'),  # 主题api
    path('api/users/', views_user_management.get_users_api, name='get_users_api'),  # 获取用户数据，这个api接口只给人员管理用！
    path('api/roles/', views_user_management.get_roles_api, name='get_roles_api'),  # 获取角色数据，这个api接口只给人员管理用！

    # Amazon店铺管理
    path('amazon-management/', views_amazon_management.amazon_management_view, name='amazon_management'),  # 管理亚马逊店铺主页
    path('api/amazon-shops/', views_amazon_management.get_amazon_shops_api, name='get_amazon_shops_api'),  # 获取亚马逊店铺数据
    path('api/amazon-shops/create/', views_amazon_management.create_amazon_shop_api, name='create_amazon_shop_api'),
    path('api/amazon-shops/<int:shop_id>/update/', views_amazon_management.update_amazon_shop_api,
         name='update_amazon_shop_api'),
    path('api/operators/', views_amazon_management.get_all_operators_api, name='get_operators_api'),  # 重写2份
    path('api/ops-groups/', views_amazon_management.get_all_ops_groups_api, name='get_ops_groups_api'),  # 重写2份
    path('api/customers/', views_amazon_management.get_customers_api, name='get_customers_api'),  # 亚马逊店铺管理的 项目api

    path('api/filter-amazon-data/', amazon_views.filter_amazon_data_api, name='filter_amazon_data'),  # 亚马逊驾驶舱筛选数据
    path('api/amazon/operators/', amazon_views_jc.get_operators_api),  # 亚马逊筛选数据
    path('api/amazon/ops-groups/', amazon_views_jc.get_ops_groups_api),  # 亚马逊筛选数据

    path('amazon-order-management/', amazon_order_views.amazon_order_management_page, name='amazon_order_management'),
    # 亚马逊订单管理页面
    path('api/amazon-orders-list/', amazon_order_views.get_amazon_orders_list_api, name='get_amazon_orders_list_api'),
    # 亚马逊订单api
    path('api/add_divi_amazon_order/', amazon_divi_views.add_divi_amazon_order, name='add_divi_amazon_order'),  # 导单接口
    # path('api/test/', amazon_divi_views.add_divi_order, name='test'),
    path('api/update-divi-export-status/', amazon_order_views.update_divi_export_status_api,
         name='update_divi_export_status'),

    # ⭐ 一键发货 API
    path("api/ship-order/", amazon_order_api_views.api_ship_order, name="api_ship_order"),
    path("api/mark-real-shipment/", amazon_order_api_views.api_mark_real_shipment, name="api_mark_real_shipment"),
    # 标注真发

    # Temu API接口
    path('api/operators/', views_temu_management.get_all_operators_api, name='get_operators'),
    path('api/temu-customers/', views_temu_management.get_customers_api, name='get_temu_customers'),
    path('api/temu-shops/', views_temu_management.get_temu_shops_api, name='get_temu_shops'),
    path('api/temu-shops/create/', views_temu_management.create_temu_shop_api, name='create_temu_shop'),
    path('api/temu-shops/<int:shop_id>/update/', views_temu_management.update_temu_shop_api, name='update_temu_shop'),

    # 绩效管理页面
    path('performance/', views_performance.performance_targets_view, name='performance_targets'),

    # 组目标API
    path('api/performance/group_targets/', views_performance.get_group_targets_api, name='api_group_targets'),
    path('api/performance/group_targets/create/', views_performance.create_group_target_api, name='api_group_create'),
    path('api/performance/group_targets/<int:target_id>/update/', views_performance.update_group_target_api,
         name='api_group_update'),

    # 个人目标API
    path('api/performance/personal_targets/', views_performance.get_personal_targets_api, name='api_personal_targets'),
    path('api/performance/personal_targets/batch/', views_performance.batch_create_personal_targets_api,
         name='api_personal_batch'),

    # 筛选选项API
    path('api/performance/ops_groups/', views_performance.get_ops_groups_for_filter_api, name='api_ops_groups_filter'),
    path('api/performance/operators_by_group/', views_performance.get_operators_by_group_api,
         name='api_operators_by_group'),

    path('ranking/', views_ranking.ranking_page, name='ranking_page'),
    path('api/ranking-data/', views_ranking.get_ranking_data_api, name='ranking_data_api'),
    path('demo1/', demo_view.demo_view),
    path('api/announcement/mark-as-read/', views.mark_announcement_as_read, name='mark_announcement_read'),

    # 亚马逊绩效通知管理
    path('amazon/performance/notifications/',
         amazon_jx_views.amazon_performance_notifications_page,
         name='amazon_performance_notifications'),

    # 绩效通知API
    path('api/amazon-performance-notifications/',
         amazon_jx_views.get_amazon_performance_notifications_api,
         name='api_amazon_performance_notifications'),

    # 标记已处理API
    path('api/amazon-performance-notifications/<int:notification_id>/mark-processed/',
         amazon_jx_views.mark_notification_processed_api,
         name='mark_notification_processed'),

    # 绩效模块运营人员列表API
    path('api/amazon/performance/operators/',
         amazon_jx_views.get_performance_operators_api,
         name='api_performance_operators'),
# ⭐ 新增：通知运营人员预览API
path('api/amazon-performance-notifications/notify-operators/preview/',
     amazon_jx_views.notify_operators_preview_api,
     name='notify_operators_preview'),

# ⭐ 新增：执行通知运营人员API
path('api/amazon-performance-notifications/notify-operators/',
     amazon_jx_views.notify_operators_api,
     name='notify_operators'),
    # 饼图销量
path('api/amazon/operator-sales-pie-chart/',
     amazon_views.get_operator_sales_pie_chart_api,
     name='amazon_operator_sales_pie_chart'),
]
