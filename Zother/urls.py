# Zother/urls.py
from django.urls import path
from .views import export_bargaining_orders  # 导入导出视图

app_name = 'Zother'  # 命名空间

urlpatterns = [
    # 页面路由
    path('bargaining/export/', export_bargaining_orders, name='export_bargaining_orders'),
    # ... 其他路由保持不变
]