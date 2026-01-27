from django.urls import path
from theme.view import views, views_vocabulary, views_trend

app_name = 'theme'

urlpatterns = [
    # 页面渲染
    path('theme/products/', views.product_list_page, name='theme_product_list'),
    path('theme/vocabulary/tro-table/', views_vocabulary.tro_table_page, name='tro_table_page'),
    path('theme/vocabulary/trademark-info/', views_vocabulary.trademark_info_page, name='trademark_info_page'),
    path('theme/trend', views_trend.trend_page, name='trend_page'),

    # 词库API
    path('api/tro-table/', views_vocabulary.api_tro_table_list, name='api_tro_table_list'),
    path('api/tro-table/create/', views_vocabulary.api_create_tro_record, name='api_create_tro_record'),
    path('api/tro-table/update/', views_vocabulary.api_update_tro_record, name='api_update_tro_record'),
    path('api/tro-table/delete/', views_vocabulary.api_delete_tro_record, name='api_delete_tro_record'),
    path('api/trademark-info/', views_vocabulary.api_trademark_info_list, name='api_trademark_info_list'),

    # 产品数据API
    path('api/amazon-products/', views.api_amazon_products, name='api_amazon_products'),

    path('api/amazon-products/<str:asin>/', views.api_product_detail, name='api_product_detail'),

    # 产品操作API
    path('api/amazon-products/create/', views.api_create_product, name='api_create_product'),
    path('api/amazon-products/<str:asin>/update/', views.api_update_product, name='api_update_product'),
    path('api/amazon-products/<str:asin>/delete/', views.api_delete_product, name='api_delete_product'),

    # 批量操作
    path('api/amazon-products/bulk-update-type/', views.api_bulk_update_product_type,
         name='api_bulk_update_product_type'),

    # 导出功能
    path('amazon/products/export/csv/', views.export_products_csv, name='export_products_csv'),
    path('amazon/products/export/excel/', views.export_products_excel, name='export_products_excel'),

    # 统计报表
    path('api/amazon-products/statistics/', views.api_product_statistics, name='api_product_statistics'),

    # 搜索建议
    path('api/amazon-products/suggestions/', views.api_product_suggestions, name='api_product_suggestions'),

    # 健康检查
    path('api/health-check/', views.api_health_check, name='api_health_check'),

    # 分词模块
    path('api/vocabulary/words-split/', views_trend.words_split_api, name='words_split_api'),

    # 侵权词搜索
    path('api/trend/search/', views_trend.trend_search, name='trend_search'),
]
