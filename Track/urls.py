# track/urls.py
from django.urls import path
from track.view import view_tracking_management

app_name = 'track'  # 命名空间

urlpatterns = [
    # 页面路由
    path('tracking-management/', view_tracking_management.tracking_management, name='tracking-management'),

    # API路由
    path('api/tracking-list/', view_tracking_management.tracking_list, name='tracking-list'),
    path('api/tracking-details/', view_tracking_management.tracking_details, name='tracking-details'),
    path('api/tracking-stats/', view_tracking_management.tracking_stats, name='stats'),
    path('api/import-tracking-excel/', view_tracking_management.import_tracking_excel, name='import-tracking-excel'),  #
    path('api/refresh-tracking/', view_tracking_management.refresh_tracking, name='refresh_tracking'),  #
    path('api/couriers/', view_tracking_management.get_couriers, name='couriers'),
    path('api/export-tracking-excel/', view_tracking_management.export_tracking_excel, name='export-excel'),

    path('api/factories/', view_tracking_management.get_factories, name='get_factories'),
    path('api/toggle-cancel-status/', view_tracking_management.toggle_cancel_status, name='toggle-cancel-status'),
    path('api/update-tracking-remark/', view_tracking_management.update_tracking_remark, name='update_tracking_remark'),
]
