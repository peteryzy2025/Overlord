from django.urls import path
from data_req.view import requirement

app_name = 'data_req'

urlpatterns = [
    # 页面路由
    path('', requirement.RequirementListView.as_view(), name='list'),
    path('<int:pk>/', requirement.RequirementDetailView.as_view(), name='detail'),

    # API 路由
    path('api/create/', requirement.RequirementCreateAPI.as_view(), name='api_create'),
    path('api/update/', requirement.RequirementUpdateAPI.as_view(), name='api_update'),
    path('api/delete/', requirement.RequirementDeleteAPI.as_view(), name='api_delete'),
    path('api/detail/', requirement.RequirementDetailAPI.as_view(), name='api_detail'),
    path('api/stats/', requirement.RequirementStatsAPI.as_view(), name='api_stats'),
    path('api/status/', requirement.RequirementStatusAPI.as_view(), name='api_status'),
    path('api/list/', requirement.RequirementListAPI.as_view(), name='api_list'),
]