from django.urls import path
from . import views

app_name = 'inventory'

urlpatterns = [
    path('list/', views.inventory_list_page, name='inventory_list'),
    path('api/list/', views.get_inventory_list_api, name='get_inventory_list_api'),
    path('api/upload/', views.upload_inventory_file, name='upload_inventory_file'),
]
