# advertisement/urls.py
from django.urls import path
from advertisement.view import views_campaign

app_name = 'advertisement'

urlpatterns = [
    # ========== 广告活动管理 ==========
    path('advertisement/campaigns/', views_campaign.campaign_list_page, name='campaign_list'),
    path('api/advertisement/campaigns/list/', views_campaign.get_campaign_list_api, name='get_campaign_list_api'),
    path('api/advertisement/campaigns/<int:campaign_id>/detail/', views_campaign.get_campaign_detail_api, name='get_campaign_detail_api'),
    path('api/advertisement/campaigns/batch-update-status/', views_campaign.batch_update_campaign_status_api, name='batch_update_campaign_status_api'),
]
