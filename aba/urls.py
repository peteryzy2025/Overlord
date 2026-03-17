from django.urls import path
from aba import views

app_name = 'aba'

urlpatterns = [
    # ABA 数据管理页面
    path('aba', views.aba_data_page, name='aba_data'),
    
    # API 接口
    path('api/data/', views.get_aba_data_api, name='api_aba_data'),
    path('api/update-denoising/', views.update_search_term_denoising_api, name='api_update_search_term_denoising'),
    path('api/available-weeks/', views.get_available_weeks_api, name='api_aba_available_weeks'),
]
