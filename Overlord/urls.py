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

urlpatterns = [
    path('admin/', admin.site.urls),
    path('login/', views.user_login, name='login'),
    path('logout/', views.user_logout, name='logout'),
    path('main/', views.main_page, name='main'),
    path('management/', views.management_page, name='management'),
    path('management/users/', views_user_management.user_management_view, name='user_management'),
    path('api/users/create/', views_user_management.create_user_api, name='create_user_api'),
    path('api/users/<int:user_id>/update/', views_user_management.update_user_api, name='update_user_api'),
    path('management/amazon/', views_user_management.amazon_management_view, name='amazon_management'),
    path('management/temu/', views_user_management.temu_management_view, name='temu_management'),
    path('amazon-dashboard/', views.amazon_dashboard_page, name='amazon_dashboard'),
    path('csrf/', views.csrf_token_view, name='csrf_token'),
    path('api/update-theme/', views.update_theme, name='update_theme'),
    path('api/users/', views_user_management.get_users_api, name='get_users_api'),

    path('api/roles/', views_user_management.get_roles_api, name='get_roles_api'),

    # Amazon店铺管理

    path('amazon-management/', views_amazon_management.amazon_management_view, name='amazon_management'),
    path('api/amazon-shops/', views_amazon_management.get_amazon_shops_api, name='get_amazon_shops_api'),
    path('api/amazon-shops/create/', views_amazon_management.create_amazon_shop_api, name='create_amazon_shop_api'),
    path('api/amazon-shops/<int:shop_id>/update/', views_amazon_management.update_amazon_shop_api,
         name='update_amazon_shop_api'),
    path('api/operators/', views_amazon_management.get_operators_api, name='get_operators_api'),
    path('api/ops-groups/', views_amazon_management.get_ops_groups_api, name='get_ops_groups_api'),
    path('api/customers/', views_amazon_management.get_customers_api, name='get_customers_api'),
]
