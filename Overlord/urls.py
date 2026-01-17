# myproject/urls.py
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('general.urls')),  # 包含 General app 的所有路由
    path('', include('amazon.urls')),  # 包含 Amazon app 的所有路由
    # path('', include('temu.urls')),
    path('', include('track.urls')),
    path('', include('yuser.urls')),  # 添加这一行
    path('', include('theme.urls')),  # 包含 Theme app 的路由
    path('', include('zother.urls')),  # 添加这一行
    path('', include('task.urls')),
    path('shop_guard/', include('shop_guard.urls')),
    path('inventory/', include('inventory.urls')),
]

