# Amazon/urls.py
from django.urls import path
from amazon import (
    amazon_views,
    amazon_views_jc,
    views_ranking,
)
from amazon.view import views_dashboard, views_amazon_listing_management
from amazon.view import views_amazon_order, views_amazon_performance, views_amazon_shop_emails,views_amazon_daily_check
from amazon.view import views_rpa_sync, views_risk_keywords,views_amazon_listing_management
from amazon.view import views_amazon_upload_records, views_amazon_profit
from amazon.api.shop_check import init_daily_shop_check, get_daily_check_list, update_daily_check, save_upload_record, get_upload_record_by_filename
from amazon.api.shop_info import get_shop_info_by_name


app_name = 'amazon'

urlpatterns = [
    # ========== 驾驶舱/仪表板 ==========
    path('dashboard/', views_dashboard.dashboard_page, name='dashboard'),
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
    path('ranking/', views_dashboard.ranking_page, name='ranking_page'),
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

    # ========== 影刀 RPA 同步接口 ==========
    path('api/rpa/amazon-emails/sync/', views_rpa_sync.sync_email_api, name='rpa_sync_email'),
    path('api/rpa/amazon-performance/sync/', views_rpa_sync.sync_performance_api, name='rpa_sync_performance'),

    # ========== 深渊 - 风险关键词管理 ==========
    path('amazon/risk-keywords/', views_risk_keywords.amazon_risk_keywords_page, name='amazon_risk_keywords'),
    path('api/amazon-risk-keywords/', views_risk_keywords.RiskKeywordListAPI.as_view(), name='api_amazon_risk_keywords_list'),
    path('api/amazon-risk-keywords/create/', views_risk_keywords.RiskKeywordCreateAPI.as_view(), name='api_amazon_risk_keywords_create'),
    path('api/amazon-risk-keywords/update/', views_risk_keywords.RiskKeywordUpdateAPI.as_view(), name='api_amazon_risk_keywords_update'),
    path('api/amazon-risk-keywords/delete/', views_risk_keywords.RiskKeywordDeleteAPI.as_view(), name='api_amazon_risk_keywords_delete'),
    path('api/amazon-risk-keywords/options/', views_risk_keywords.RiskKeywordOptionsAPI.as_view(), name='api_amazon_risk_keywords_options'),

 #=====Amazon Listing管理页面==============
    path(
        'amazon-listing-management/',
        views_amazon_listing_management.views_amazon_listing_management,
        name='amazon_listing_management'
    ),
    path(
        'api/amazon-listing-management/list/',
        views_amazon_listing_management.get_amazon_listing_management_list_api,
        name='api_amazon_listing_management_list'
    ),
    path(
        'api/amazon-listing-management/filter-options/',
        views_amazon_listing_management.get_amazon_listing_management_filter_options_api,
        name='api_amazon_listing_management_filter_options'
    ),
    path(
        'api/amazon-listing-management/risk-stats/',
        views_amazon_listing_management.get_amazon_listing_management_risk_stats_api,
        name='api_amazon_listing_management_risk_stats'
    ),
    path(
        'api/amazon-listing-management/batch-risk-check/',
        views_amazon_listing_management.get_amazon_listing_batch_risk_check_api,
        name='api_amazon_listing_batch_risk_check'
    ),
    path(
        'api/amazon-listing-management/<int:listing_id>/word-sources/',
        views_amazon_listing_management.get_amazon_listing_word_sources_api,
        name='api_amazon_listing_word_sources'
    ),
    
    # ========== 巡店外部 API 接口（供影刀调用） ==========
    # 初始化当日巡店记录
    path('amazon/api/shop-check/init/', init_daily_shop_check, name='api_shop_check_init'),
    # 获取巡店日报列表
    path('amazon/api/shop-check/list/', get_daily_check_list, name='api_shop_check_list'),
    # 更新巡店日报记录
    path('amazon/api/shop-check/update/', update_daily_check, name='api_shop_check_update'),
    # 保存店铺上货记录（新建/更新）
    path('amazon/api/upload-record/save/', save_upload_record, name='api_upload_record_save'),
    # 根据文件名查询上货记录
    path('api/amazon/upload-record/', get_upload_record_by_filename, name='api_upload_record_by_filename'),
    
    # 根据店铺名称查询店铺信息
    path('amazon/api/shop-info/', get_shop_info_by_name, name='api_shop_info_by_name'),
    
    # ========== Amazon店铺上货情况 ==========
    path('amazon/upload-records/', views_amazon_upload_records.amazon_upload_records_page, name='amazon_upload_records'),
    path('api/amazon/upload-records/', views_amazon_upload_records.get_amazon_upload_records_api, name='api_amazon_upload_records'),

    # ========== 利润明细 ==========
    path('amazon/profit-detail/', views_amazon_profit.amazon_profit_detail_page, name='amazon_profit_detail'),
    path('api/amazon-profit-detail/', views_amazon_profit.get_amazon_profit_detail_api, name='api_amazon_profit_detail'),
    path('api/amazon-profit-filter-options/', views_amazon_profit.get_amazon_profit_filter_options_api, name='api_amazon_profit_filter_options'),
]
