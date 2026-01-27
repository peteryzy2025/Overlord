# Amazon/urls.py
from django.urls import path
from amazon import (
    amazon_views,
    amazon_views_jc,
    views_ranking,
)
from amazon.view import views_amazon_order, views_amazon_performance, views_amazon_shop_emails,views_amazon_daily_check
app_name = 'amazon'

urlpatterns = [
    # ========== 驾驶舱/仪表板 ==========
    path('dashboard/', amazon_views.amazon_dashboard_page, name='dashboard'),
    path('api/amazon/operator-pie-chart/', amazon_views.get_operator_pie_chart_api, name='amazon_operator_pie_chart'),
    path('api/amazon/operator-sales-pie-chart/', amazon_views.get_operator_sales_pie_chart_api,
         name='amazon_operator_sales_pie_chart'),
    path('api/filter-amazon-data/', amazon_views.filter_amazon_data_api, name='filter_amazon_data'),
    path('api/amazon/operators/', amazon_views_jc.get_operators_api),
    path('api/amazon/ops-groups/', amazon_views_jc.get_ops_groups_api),

    # ========== Amazon订单管理 ==========
    path('amazon-order-management/', views_amazon_order.amazon_order_management_page, name='amazon_order_management'),
    path('api/amazon-orders-list/', views_amazon_order.get_amazon_orders_list_api, name='get_amazon_orders_list_api'),
    path('api/add_divi_amazon_order/', views_amazon_order.add_divi_amazon_order, name='add_divi_amazon_order'),
    path('api/update-divi-export-status/', views_amazon_order.update_divi_export_status_api,
         name='update_divi_export_status'),
    path('api/ship-order/', views_amazon_order.api_ship_order, name='api_ship_order'),
    path('api/mark-real-shipment/', views_amazon_order.api_mark_real_shipment, name='api_mark_real_shipment'),
    path('api/export-amazon-orders-excel/', views_amazon_order.export_amazon_orders_excel,
         name='api_export_amazon_orders_excel'),
    # ========== 排名 ==========
    path('ranking/', views_ranking.ranking_page, name='ranking_page'),
    path('api/ranking-data/', views_ranking.get_ranking_data_api, name='ranking_data_api'),

    # ========== Amazon绩效通知 ==========
    path('amazon/performance/notifications/', views_amazon_performance.amazon_performance_notifications_page,
         name='amazon_performance_notifications'),
    path('api/amazon-performance-notifications/', views_amazon_performance.get_amazon_performance_notifications_api,
         name='api_amazon_performance_notifications'),
    path('api/amazon-performance-notifications/<int:notification_id>/mark-processed/',
         views_amazon_performance.mark_notification_processed_api, name='mark_notification_processed'),
    path('api/amazon/performance/operators/', views_amazon_performance.get_performance_operators_api,
         name='api_performance_operators'),
    path('api/amazon-performance-notifications/notify-operators/preview/',
         views_amazon_performance.notify_operators_preview_api, name='notify_operators_preview'),
    path('api/amazon-performance-notifications/notify-operators/', views_amazon_performance.notify_operators_api,
         name='notify_operators'),

    # ========== 店铺邮件管理 ==========
    path('amazon/shop-emails/', views_amazon_shop_emails.amazon_shop_emails_page,
         name='amazon_shop_emails'),
    path('api/amazon-shop-emails/', views_amazon_shop_emails.get_amazon_shop_emails_api,
         name='api_amazon_shop_emails'),
    path('api/amazon-shop-emails/<int:email_id>/mark-processed/',
         views_amazon_shop_emails.mark_email_processed_api, name='mark_email_processed'),
    path('api/amazon/shop-emails/operators/', views_amazon_shop_emails.get_shop_emails_operators_api,
         name='api_shop_emails_operators'),
    path('api/amazon-shop-emails/notify/preview/',
         views_amazon_shop_emails.notify_operators_preview_api, name='shop_emails_notify_preview'),
    path('api/amazon-shop-emails/notify/', views_amazon_shop_emails.notify_operators_api,
         name='shop_emails_notify'),
    path('api/amazon-shop-emails/<int:email_id>/', views_amazon_shop_emails.get_email_detail_api, name='get_email_detail'),  # 新增这一行

    # 巡店报告
    path('amazon/daily-check-report/', views_amazon_daily_check.amazon_daily_check_report_page, name='amazon_daily_check_report_page'),
    path('api/amazon-daily-check/', views_amazon_daily_check.get_amazon_daily_check_list_api, name='amazon_daily_check_list_api'),
    path('api/amazon-daily-check/operators/', views_amazon_daily_check.get_daily_check_operators_api, name='daily_check_operators_api'),
    path('api/amazon-daily-check/reset-today/', views_amazon_daily_check.reset_today_daily_check_api, name='reset_today_daily_check_api'),
]
