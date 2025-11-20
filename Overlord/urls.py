"""
URL configuration for Overlord project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path
from General import views, views_user_management, views_amazon_management
from Amazon import amazon_views, amazon_divi_views, amazon_order_views,amazon_views_jc

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', views.user_login, name='login'),
    path('login/', views.user_login, name='login'), # 登录
    path('logout/', views.user_logout, name='logout'),# 登出
    path('main/', views.main_page, name='main'),# 主页
    path('management/', views.management_page, name='management'),# 管理主页
    path('management/users/', views_user_management.user_management_view, name='user_management'), # 管理用户主页
    path('api/users/create/', views_user_management.create_user_api, name='create_user_api'), # 用户新增api
    path('api/users/<int:user_id>/update/', views_user_management.update_user_api, name='update_user_api'), # 更新用户数据api
    path('management/temu/', views_user_management.temu_management_view, name='temu_management'),# 管理temu店铺主页
    path('amazon-dashboard/', amazon_views.amazon_dashboard_page, name='amazon_dashboard'),# 亚马逊驾驶舱
    path('csrf/', views.csrf_token_view, name='csrf_token'),
    path('api/update-theme/', views.update_theme, name='update_theme'), # 主题api
    path('api/users/', views_user_management.get_users_api, name='get_users_api'), # 获取用户数据，这个api接口只给人员管理用！
    path('api/roles/', views_user_management.get_roles_api, name='get_roles_api'), # 获取角色数据，这个api接口只给人员管理用！

    # Amazon店铺管理
    path('amazon-management/', views_amazon_management.amazon_management_view, name='amazon_management'),# 管理亚马逊店铺主页
    path('api/amazon-shops/', views_amazon_management.get_amazon_shops_api, name='get_amazon_shops_api'), # 获取亚马逊店铺数据
    path('api/amazon-shops/create/', views_amazon_management.create_amazon_shop_api, name='create_amazon_shop_api'),
    path('api/amazon-shops/<int:shop_id>/update/', views_amazon_management.update_amazon_shop_api,
         name='update_amazon_shop_api'),
    path('api/operators/', views_amazon_management.get_all_operators_api, name='get_operators_api'), #  重写2份
    path('api/ops-groups/', views_amazon_management.get_all_ops_groups_api, name='get_ops_groups_api'),#  重写2份
    path('api/customers/', views_amazon_management.get_customers_api, name='get_customers_api'),  # 亚马逊店铺管理的 项目api

    path('api/filter-amazon-data/', amazon_views.filter_amazon_data_api, name='filter_amazon_data'), # 亚马逊驾驶舱筛选数据
    path('api/amazon/operators/', amazon_views_jc.get_operators_api), # 亚马逊筛选数据
    path('api/amazon/ops-groups/', amazon_views_jc.get_ops_groups_api), # 亚马逊筛选数据

    path('amazon-order-management/', amazon_order_views.amazon_order_management_page, name='amazon_order_management'), # 亚马逊订单管理页面
    path('api/amazon-orders-list/', amazon_order_views.get_amazon_orders_list_api, name='get_amazon_orders_list_api'), # 亚马逊订单api
    path('api/add_divi_amazon_order/', amazon_divi_views.add_divi_amazon_order, name='add_divi_amazon_order'), # 导单接口
    # path('api/test/', amazon_divi_views.add_divi_order, name='test'),
    path('api/update-divi-export-status/', amazon_views.update_divi_export_status_api,
         name='update_divi_export_status'),

]
