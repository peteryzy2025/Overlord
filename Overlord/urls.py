# myproject/urls.py
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('general.urls')),  # 包含 General app 的所有路由
    path('', include('amazon.urls')),  # 包含 Amazon app 的所有路由
    path('', include('temu.urls')),
    path('', include('track.urls')),
    path('', include('yuser.urls')),  # 添加这一行
    path('', include('theme.urls')),  # 包含 Theme app 的路由
    path('', include('zother.urls')),  # 添加这一行
    path('', include('task.urls')),
    path('', include('aba.urls')),
    path('shop_guard/', include('shop_guard.urls')),
    path('inventory/', include('inventory.urls')),
    path('data_req/', include('data_req.urls')),
    path('', include('divi.urls')),  # 包含 Divi 应用的路由
]

# 开发环境下提供媒体文件服务
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
