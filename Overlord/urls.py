# myproject/urls.py
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('General.urls')),  # 包含 General app 的所有路由
    path('', include('Amazon.urls')),   # 包含 Amazon app 的所有路由
    # path('', include('Temu.urls')),
    path('', include('Track.urls')),
    path('', include('Yuser.urls')),  # 添加这一行
]