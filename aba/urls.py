from django.urls import path
from aba.view import views

app_name = 'aba'

urlpatterns = [
    # ABA 数据管理页面
    path('aba', views.aba_data_page, name='aba_data'),
    path('aba/noise-words/', views.aba_noise_words_page, name='aba_noise_words'),
    
    # API 接口
    path('api/data/', views.get_aba_data_api, name='api_aba_data'),
    path('api/data/total/start/', views.start_aba_total_count_api, name='api_aba_total_count_start'),
    path('api/data/total/progress/', views.get_aba_total_count_progress_api, name='api_aba_total_count_progress'),
    path('api/new-words/', views.get_aba_new_words_api, name='api_aba_new_words'),
    path('api/update-denoising/', views.update_search_term_denoising_api, name='api_update_search_term_denoising'),
    path('api/noise-words/', views.get_aba_noise_words_api, name='api_aba_noise_words'),
    path('api/noise-words/add/start/', views.start_add_noise_words_api, name='api_start_add_noise_words'),
    path('api/noise-words/add/progress/', views.get_add_noise_words_progress_api, name='api_add_noise_words_progress'),
    path('api/noise-words/delete/', views.delete_aba_noise_word_api, name='api_delete_aba_noise_word'),
    path('api/custom-denoising/start/', views.start_custom_denoising_api, name='api_start_custom_denoising'),
    path('api/custom-denoising/progress/', views.get_custom_denoising_progress_api, name='api_custom_denoising_progress'),
    path('api/available-weeks/', views.get_available_weeks_api, name='api_aba_available_weeks'),
]
