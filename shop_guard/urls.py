from django.urls import path
from .view import views

urlpatterns = [
    # 最终访问路径为 /shop_guard/dashboard/
    # 因为在 Overlord/urls.py 中已经配置了 path('shop_guard/', include('shop_guard.urls'))
    path('dashboard/', views.dashboard, name='shop_guard_dashboard'),
    path('', views.dashboard, name='shop_guard_home'), # Default to dashboard
]
