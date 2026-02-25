# advertisement/urls.py
from django.urls import path
from advertisement.view import views_campaign, views_asin, views_asin_detail

app_name = 'advertisement'

urlpatterns = [
    # ========== 广告活动管理 ==========
    path('advertisement/campaigns/', views_campaign.campaign_list_page, name='campaign_list'),
    path('api/advertisement/campaigns/list/', views_campaign.get_campaign_list_api, name='get_campaign_list_api'),
    path('api/advertisement/campaigns/<int:campaign_id>/detail/', views_campaign.get_campaign_detail_api, name='get_campaign_detail_api'),
    path('api/advertisement/campaigns/batch-update-status/', views_campaign.batch_update_campaign_status_api, name='batch_update_campaign_status_api'),
    
    # ========== ASIN 广告管理 ==========
    path('advertisement/asin/', views_asin.asin_list_page, name='asin_list'),
    path('api/advertisement/asin/list/', views_asin.get_asin_list_api, name='get_asin_list_api'),
    path('api/advertisement/asin/<str:asin>/detail/', views_asin.get_asin_detail_api, name='get_asin_detail_api'),
    
    # ========== ASIN 详情页面 ==========
    path('advertisement/asin/<str:asin>/detail/', views_asin_detail.asin_detail_page, name='asin_detail'),
    path('api/advertisement/asin/<str:asin>/summary/', views_asin_detail.get_asin_summary_api, name='get_asin_summary_api'),
    path('api/advertisement/asin/<str:asin>/daily/', views_asin_detail.get_asin_daily_data_api, name='get_asin_daily_data_api'),
    path('api/advertisement/asin/<str:asin>/hourly/', views_asin_detail.get_asin_hourly_data_api, name='get_asin_hourly_data_api'),
    path('api/advertisement/asin/<str:asin>/hourly-distribution/', views_asin_detail.get_asin_hourly_distribution_api, name='get_asin_hourly_distribution_api'),
    path('api/advertisement/asin/<str:asin>/campaigns/', views_asin_detail.get_asin_campaigns_api, name='get_asin_campaigns_api'),
]
