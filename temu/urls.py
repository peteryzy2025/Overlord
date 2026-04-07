# Temu/urls.py
from django.urls import path
from temu.view import views_temu_order
from temu.view.api import sku_api

app_name = 'temu'

urlpatterns = [
    # ========== Temu订单管理 ==========
    path('temu-order-management/', views_temu_order.temu_order_management_page, name='temu_order_management'),
    path('api/temu-orders-list/', views_temu_order.get_temu_orders_list_api, name='get_temu_orders_list_api'),
    path('api/update-temu-divi-export-status/', views_temu_order.update_temu_divi_export_status_api,
         name='update_temu_divi_export_status'),
    path('api/export-temu-orders-excel/', views_temu_order.export_temu_orders_excel,
         name='export_temu_orders_excel'),
    path('api/refresh-temu-divi-status/', views_temu_order.refresh_temu_divi_status_api,
         name='refresh_temu_divi_status'),
    path('api/temu-order-to-divi-and-lingxing/', views_temu_order.temu_order_to_divi_and_lingxing_api,
         name='temu_order_to_divi_and_lingxing'),
    path('api/download-temu-label/', views_temu_order.download_temu_label_api,
         name='download_temu_label'),
    
    # ========== Temu SKU 管理 ==========
    path('api/batch-upsert-sku/', sku_api.batch_upsert_sku_api, name='batch_upsert_sku'),
    
    # ========== Temu 店铺管理 ==========
    path('api/get-temu-shop-password/', sku_api.get_temu_shop_password_api, name='get_temu_shop_password'),
]
