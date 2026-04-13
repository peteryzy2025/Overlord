from django.urls import path
from django.views.decorators.csrf import csrf_exempt
from theme.view import views, views_vocabulary, views_trend, views_dw_data, views_new_release, views_novelty_aggregation


app_name = 'theme'

urlpatterns = [
    # 页面渲染
    path('theme/products/', views.product_list_page, name='theme_product_list'),
    path('theme/new-release/', views_new_release.new_release_page, name='theme_new_release_page'),
    path('vocabulary/tro-table/', views_vocabulary.tro_table_page, name='tro_table_page'),
    path('vocabulary/trademark-info/', views_vocabulary.trademark_info_page, name='trademark_info_page'),
    path('Theme/trend',views_trend.trend_page, name='trend_page'),

    # 词库API
    path('api/tro-table/', views_vocabulary.api_tro_table_list, name='api_tro_table_list'),
    path('api/tro-table/create/', views_vocabulary.api_create_tro_record, name='api_create_tro_record'),
    path('api/tro-table/update/', views_vocabulary.api_update_tro_record, name='api_update_tro_record'),
    path('api/tro-table/delete/', views_vocabulary.api_delete_tro_record, name='api_delete_tro_record'),
    path('api/tro-table/download-template/', views_vocabulary.download_templates, name='download_tro_template'),
    path('api/tro-table/import/', views_vocabulary.api_import_tro_records, name='api_import_tro_records'),
    path('api/trademark-info/', views_vocabulary.api_trademark_info_list, name='api_trademark_info_list'),
    path('api/nice-classification/', views_vocabulary.api_nice_classification_list, name='api_nice_classification_list'),
    path('api/shops/', views_vocabulary.api_shop_list, name='api_shop_list'),

    # 产品数据API
    path('api/amazon-products/', views.api_amazon_products, name='api_amazon_products'),
    path('api/external/amazon-products/', views.external_api_amazon_products, name='external_api_amazon_products'),
    path('api/theme-new-release/', views_new_release.api_new_release_list, name='api_new_release_list'),
    path('api/theme-aggregation/', views_new_release.api_theme_aggregation_list, name='api_theme_aggregation_list'),
    path('api/theme-aggregation/asins/', views_new_release.api_theme_aggregation_asins, name='api_theme_aggregation_asins'),
    path('api/theme-novelty-aggregation/', views_novelty_aggregation.api_novelty_aggregation_list, name='api_novelty_aggregation_list'),
    path('api/theme-novelty-aggregation/asins/', views_novelty_aggregation.api_novelty_aggregation_asins, name='api_novelty_aggregation_asins'),
    path('api/amazon-products/batch-risk-check/', views.api_batch_risk_check, name='api_batch_risk_check'),

    # 产品操作API - 放在详情API之前
    path('api/amazon-products/create/', views.api_create_product, name='api_create_product'),
    
    # 批量操作 - 放在详情API之前
    path('api/amazon-products/bulk-update-type/', views.api_bulk_update_product_type,
         name='api_bulk_update_product_type'),

    # 举报功能 - 放在详情API之前
    path('api/amazon-products/report/', views.api_report_product, name='api_report_product'),
    path('api/amazon-products/unreport/', views.api_unreport_product, name='api_unreport_product'),

    # 导出功能
    path('amazon/products/export/csv/', views.export_products_csv, name='export_products_csv'),
    path('amazon/products/export/excel/', views.export_products_excel, name='export_products_excel'),

    # 统计报表 - 放在详情API之前
    path('api/amazon-products/statistics/', views.api_product_statistics, name='api_product_statistics'),

    # 搜索建议 - 放在详情API之前
    path('api/amazon-products/suggestions/', views.api_product_suggestions, name='api_product_suggestions'),

    # 产品详情API (捕获 <str:asin>) - 必须放在所有特定动作URL之后
    path('api/amazon-products/<str:asin>/', views.api_product_detail, name='api_product_detail'),
    path('api/amazon-products/<str:asin>/update/', views.api_update_product, name='api_update_product'),
    path('api/amazon-products/<str:asin>/delete/', views.api_delete_product, name='api_delete_product'),

    # 健康检查
    path('api/health-check/', views.api_health_check, name='api_health_check'),

    # 分词模块
    path('api/vocabulary/words-split/', views_trend.words_split_api, name='words_split_api'),

    # 侵权词搜索
    path('api/trend/search/', views_trend.trend_search, name='trend_search'),

    # 迪唯产业大数据模型
    path('dw-data/', views_dw_data.dw_data_page, name='dw_data_page'),
    path('api/market-categories/', views_dw_data.api_market_categories, name='api_market_categories'),
    path('api/niche-markets/', views_dw_data.api_niche_markets, name='api_niche_markets'),
]

