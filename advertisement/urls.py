# advertisement/urls.py
from django.urls import path
from advertisement.view import views_campaign, views_asin

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
]
