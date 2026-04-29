# API权限清单

生成说明：本清单基于 Django URL resolver、全局 LoginRequiredMiddleware、view 装饰器和源码关键词整理。用途描述按 URL/函数名归类，权限标注用于快速审计，最终仍以对应 view 代码为准。

- API-like 路由总数：257
- 全局规则：除白名单/外部/RPA特例外，LoginRequiredMiddleware 默认要求登录。
- 公司模块规则：logistics/theme/infringement 模块同时检查公司模块授权和用户权限码。公司已开模块但用户无权限时，返回“当前用户没有对应板块权限，请询问公司管理员。”

## 全局白名单/外部规则

| 路径 | 限制 |
| --- | --- |
| `/inventory/api/import/` | 免登录白名单：库存导入接口 |
| `/api/trend/search/` | 免登录白名单：侵权词查询接口；view 仍会执行模块权限检查 |
| `/api/market-categories/` | 免登录白名单：迪唯分类数据；view 仍会执行主题模块权限检查 |
| `/api/niche-markets/` | 免登录白名单：迪唯市场数据；view 仍会执行主题模块权限检查 |
| `/api/batch-upsert-sku/` | 免登录白名单：Temu SKU 批量新增/更新 |
| `/api/get-temu-shop-password/` | 免登录白名单：Temu 店铺密码查询 |
| `/amazon/api/*` | 免登录白名单：LoginRequiredMiddleware 放行 /amazon/api/*（按需求用于巡店等外部调用） |
| `/api/external/tasks/*` | 外部接口白名单：中间件放行，通常由接口自身业务校验/回调来源控制 |
| `/api/external/approval/*` | 外部接口白名单：中间件放行，通常由接口自身业务校验/回调来源控制 |
| `/api/external/amazon-shops/*` | 外部接口白名单：中间件放行 |
| `/api/external/amazon-products*` | 外部接口白名单：中间件放行，view 内应校验 X-RPA-Secret |
| `/api/external/divi-account/*` | 外部接口白名单：中间件放行 |
| `/api/rpa/*` | RPA接口：中间件要求 X-RPA-Secret，否则 401 |

## ABA主题（12）

| API | 用途 | 权限/限制 | View |
| --- | --- | --- | --- |
| `/api/available-weeks/` | get available weeks | 全局登录中间件：默认需要登录；公司模块+用户权限：主题板块/ABA（公司已授权主题模块，且用户需有权限码 8/555） | `aba.view.views.get_available_weeks_api` |
| `/api/custom-denoising/progress/` | get custom denoising progress | 全局登录中间件：默认需要登录；公司模块+用户权限：主题板块/ABA（公司已授权主题模块，且用户需有权限码 8/555） | `aba.view.views.get_custom_denoising_progress_api` |
| `/api/custom-denoising/start/` | start custom denoising | 全局登录中间件：默认需要登录；公司模块+用户权限：主题板块/ABA（公司已授权主题模块，且用户需有权限码 8/555） | `aba.view.views.start_custom_denoising_api` |
| `/api/data/` | get aba data | 全局登录中间件：默认需要登录；公司模块+用户权限：主题板块/ABA（公司已授权主题模块，且用户需有权限码 8/555） | `aba.view.views.get_aba_data_api` |
| `/api/data/total/progress/` | get aba total count progress | 全局登录中间件：默认需要登录；公司模块+用户权限：主题板块/ABA（公司已授权主题模块，且用户需有权限码 8/555） | `aba.view.views.get_aba_total_count_progress_api` |
| `/api/data/total/start/` | start aba total count | 全局登录中间件：默认需要登录；公司模块+用户权限：主题板块/ABA（公司已授权主题模块，且用户需有权限码 8/555） | `aba.view.views.start_aba_total_count_api` |
| `/api/new-words/` | get aba new words | 全局登录中间件：默认需要登录；公司模块+用户权限：主题板块/ABA（公司已授权主题模块，且用户需有权限码 8/555） | `aba.view.views.get_aba_new_words_api` |
| `/api/noise-words/` | get aba noise words | 全局登录中间件：默认需要登录；公司模块+用户权限：主题板块/ABA（公司已授权主题模块，且用户需有权限码 8/555） | `aba.view.views.get_aba_noise_words_api` |
| `/api/noise-words/add/progress/` | get add noise words progress | 全局登录中间件：默认需要登录；公司模块+用户权限：主题板块/ABA（公司已授权主题模块，且用户需有权限码 8/555） | `aba.view.views.get_add_noise_words_progress_api` |
| `/api/noise-words/add/start/` | start add noise words | 全局登录中间件：默认需要登录；公司模块+用户权限：主题板块/ABA（公司已授权主题模块，且用户需有权限码 8/555） | `aba.view.views.start_add_noise_words_api` |
| `/api/noise-words/delete/` | delete aba noise word | 全局登录中间件：默认需要登录；公司模块+用户权限：主题板块/ABA（公司已授权主题模块，且用户需有权限码 8/555） | `aba.view.views.delete_aba_noise_word_api` |
| `/api/update-denoising/` | update search term denoising | 全局登录中间件：默认需要登录；公司模块+用户权限：主题板块/ABA（公司已授权主题模块，且用户需有权限码 8/555） | `aba.view.views.update_search_term_denoising_api` |

## Amazon（58）

| API | 用途 | 权限/限制 | View |
| --- | --- | --- | --- |
| `/amazon/api/shop-check/init/` | init daily shop check | 免登录白名单：LoginRequiredMiddleware 放行 /amazon/api/*（按需求用于巡店等外部调用） | `amazon.api.shop_check.init_daily_shop_check` |
| `/amazon/api/shop-check/list/` | get daily check list | 免登录白名单：LoginRequiredMiddleware 放行 /amazon/api/*（按需求用于巡店等外部调用） | `amazon.api.shop_check.get_daily_check_list` |
| `/amazon/api/shop-check/update/` | update daily check | 免登录白名单：LoginRequiredMiddleware 放行 /amazon/api/*（按需求用于巡店等外部调用） | `amazon.api.shop_check.update_daily_check` |
| `/amazon/api/shop-info/` | get shop info by name | 免登录白名单：LoginRequiredMiddleware 放行 /amazon/api/*（按需求用于巡店等外部调用）；运营/店铺数据范围限制 | `amazon.api.shop_info.get_shop_info_by_name` |
| `/amazon/api/upload-record/save/` | save upload record | 免登录白名单：LoginRequiredMiddleware 放行 /amazon/api/*（按需求用于巡店等外部调用） | `amazon.api.shop_check.save_upload_record` |
| `/api/add_divi_amazon_order/` | add divi amazon order | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin | `amazon.view.views_amazon_order.add_divi_amazon_order` |
| `/api/amazon-daily-check/` | get amazon daily check list | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；运营/店铺数据范围限制 | `amazon.view.views_amazon_daily_check.get_amazon_daily_check_list_api` |
| `/api/amazon-daily-check/operators/` | get daily check operators | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；运营/店铺数据范围限制 | `amazon.view.views_amazon_daily_check.get_daily_check_operators_api` |
| `/api/amazon-daily-check/reset-today/` | reset today daily check | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；公司数据范围限制；运营/店铺数据范围限制 | `amazon.view.views_amazon_daily_check.reset_today_daily_check_api` |
| `/api/amazon-listing-management/<int:listing_id>/word-sources/` | get amazon listing word sources | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin | `amazon.view.views_amazon_listing_management.get_amazon_listing_word_sources_api` |
| `/api/amazon-listing-management/batch-risk-check/` | get amazon listing batch risk check | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin | `amazon.view.views_amazon_listing_management.get_amazon_listing_batch_risk_check_api` |
| `/api/amazon-listing-management/filter-options/` | get amazon listing management filter options | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；公司数据范围限制；运营/店铺数据范围限制 | `amazon.view.views_amazon_listing_management.get_amazon_listing_management_filter_options_api` |
| `/api/amazon-listing-management/list/` | get amazon listing management list | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；运营/店铺数据范围限制 | `amazon.view.views_amazon_listing_management.get_amazon_listing_management_list_api` |
| `/api/amazon-listing-management/risk-stats/` | get amazon listing management risk stats | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin | `amazon.view.views_amazon_listing_management.get_amazon_listing_management_risk_stats_api` |
| `/api/amazon-orders-list/` | Amazon 订单管理 | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；运营/店铺数据范围限制 | `amazon.view.views_amazon_order.get_amazon_orders_list_api` |
| `/api/amazon-performance-notifications/` | 绩效目标/通知 | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；公司数据范围限制；运营/店铺数据范围限制 | `amazon.view.views_amazon_performance.get_amazon_performance_notifications_api` |
| `/api/amazon-performance-notifications/<int:notification_id>/mark-processed/` | 绩效目标/通知 | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；运营/店铺数据范围限制 | `amazon.view.views_amazon_performance.mark_notification_processed_api` |
| `/api/amazon-performance-notifications/notify-operators/` | 绩效目标/通知 | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；运营/店铺数据范围限制 | `amazon.view.views_amazon_performance.notify_operators_api` |
| `/api/amazon-performance-notifications/notify-operators/preview/` | 绩效目标/通知 | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；运营/店铺数据范围限制 | `amazon.view.views_amazon_performance.notify_operators_preview_api` |
| `/api/amazon-profit-detail/` | Amazon 利润明细查询/筛选 | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin | `amazon.view.views_amazon_profit.get_amazon_profit_detail_api` |
| `/api/amazon-profit-filter-options/` | Amazon 利润明细查询/筛选 | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；用户权限码判断；运营/店铺数据范围限制 | `amazon.view.views_amazon_profit.get_amazon_profit_filter_options_api` |
| `/api/amazon-risk-keywords/` | RiskKeywordListAPI | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin | `amazon.view.views_risk_keywords.RiskKeywordListAPI` |
| `/api/amazon-risk-keywords/create/` | RiskKeywordCreateAPI | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin | `amazon.view.views_risk_keywords.RiskKeywordCreateAPI` |
| `/api/amazon-risk-keywords/delete/` | RiskKeywordDeleteAPI | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；用户权限码判断 | `amazon.view.views_risk_keywords.RiskKeywordDeleteAPI` |
| `/api/amazon-risk-keywords/options/` | RiskKeywordOptionsAPI | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin | `amazon.view.views_risk_keywords.RiskKeywordOptionsAPI` |
| `/api/amazon-risk-keywords/update/` | RiskKeywordUpdateAPI | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；用户权限码判断 | `amazon.view.views_risk_keywords.RiskKeywordUpdateAPI` |
| `/api/amazon-shop-emails/` | get amazon shop emails | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；用户权限码判断；公司数据范围限制；运营/店铺数据范围限制 | `amazon.view.views_amazon_shop_emails.get_amazon_shop_emails_api` |
| `/api/amazon-shop-emails/<int:email_id>/` | get email detail | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；运营/店铺数据范围限制 | `amazon.view.views_amazon_shop_emails.get_email_detail_api` |
| `/api/amazon-shop-emails/<int:email_id>/mark-processed/` | mark email processed | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；运营/店铺数据范围限制 | `amazon.view.views_amazon_shop_emails.mark_email_processed_api` |
| `/api/amazon-shop-emails/notify/` | notify operators | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；公司数据范围限制；运营/店铺数据范围限制 | `amazon.view.views_amazon_shop_emails.notify_operators_api` |
| `/api/amazon-shop-emails/notify/preview/` | notify operators preview | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；公司数据范围限制；运营/店铺数据范围限制 | `amazon.view.views_amazon_shop_emails.notify_operators_preview_api` |
| `/api/amazon-shops/` | Amazon 店铺管理 | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；公司数据范围限制；运营/店铺数据范围限制 | `general.views_amazon_management.get_amazon_shops_api` |
| `/api/amazon-shops/<int:shop_id>/authorized-users/` | Amazon 店铺管理 | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；公司数据范围限制；运营/店铺数据范围限制 | `general.views_amazon_management.update_authorized_users_api` |
| `/api/amazon-shops/<int:shop_id>/update/` | Amazon 店铺管理 | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin | `general.views_amazon_management.update_amazon_shop_api` |
| `/api/amazon-shops/bulk-update-authorized-users/` | Amazon 店铺管理 | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；公司数据范围限制；运营/店铺数据范围限制 | `general.views_amazon_management.bulk_update_authorized_users_api` |
| `/api/amazon-shops/bulk-update-operator/` | Amazon 店铺管理 | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；公司数据范围限制；运营/店铺数据范围限制 | `general.views_amazon_management.bulk_update_operator_api` |
| `/api/amazon-shops/bulk-update-project/` | Amazon 店铺管理 | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；公司数据范围限制 | `general.views_amazon_management.bulk_update_project_api` |
| `/api/amazon-shops/create/` | Amazon 店铺管理 | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；用户权限码判断；公司数据范围限制 | `general.views_amazon_management.create_amazon_shop_api` |
| `/api/amazon/operator-pie-chart/` | get operator pie chart | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；运营/店铺数据范围限制 | `amazon.amazon_views.get_operator_pie_chart_api` |
| `/api/amazon/operator-sales-pie-chart/` | get operator sales pie chart | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；运营/店铺数据范围限制 | `amazon.amazon_views.get_operator_sales_pie_chart_api` |
| `/api/amazon/operators/` | get operators | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；公司数据范围限制；运营/店铺数据范围限制 | `amazon.amazon_views_jc.get_operators_api` |
| `/api/amazon/ops-groups/` | get ops groups | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；公司数据范围限制 | `amazon.amazon_views_jc.get_ops_groups_api` |
| `/api/amazon/performance/operators/` | 绩效目标/通知 | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；公司数据范围限制；运营/店铺数据范围限制 | `amazon.view.views_amazon_performance.get_performance_operators_api` |
| `/api/amazon/shop-emails/operators/` | get shop emails operators | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；公司数据范围限制；运营/店铺数据范围限制 | `amazon.view.views_amazon_shop_emails.get_shop_emails_operators_api` |
| `/api/amazon/upload-record/` | get upload record by filename | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；公司数据范围限制 | `amazon.api.shop_check.get_upload_record_by_filename` |
| `/api/amazon/upload-records/` | get amazon upload records | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；公司数据范围限制；运营/店铺数据范围限制 | `amazon.view.views_amazon_upload_records.get_amazon_upload_records_api` |
| `/api/export-amazon-orders-excel/` | Amazon 订单管理 | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；运营/店铺数据范围限制 | `amazon.view.views_amazon_order.export_amazon_orders_excel` |
| `/api/external/amazon-shops/` | Amazon 店铺管理 | 外部接口白名单：中间件放行 | `general.views_amazon_management.external_amazon_shops_api` |
| `/api/filter-amazon-data/` | filter amazon data | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin | `amazon.amazon_views.filter_amazon_data_api` |
| `/api/mark-real-shipment/` | api mark real shipment | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin | `amazon.view.views_amazon_order.api_mark_real_shipment` |
| `/api/ranking-data/` | get ranking data | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；公司数据范围限制；运营/店铺数据范围限制 | `amazon.views_ranking.get_ranking_data_api` |
| `/api/rpa/amazon-emails/sync/` | RPA/影刀回调接口 | RPA接口：中间件要求 X-RPA-Secret，否则 401；接口密钥校验：X-RPA-Secret | `amazon.view.views_rpa_sync.sync_email_api` |
| `/api/rpa/amazon-performance/sync/` | 绩效目标/通知 | RPA接口：中间件要求 X-RPA-Secret，否则 401；接口密钥校验：X-RPA-Secret | `amazon.view.views_rpa_sync.sync_performance_api` |
| `/api/ship-order/` | api ship order | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin | `amazon.view.views_amazon_order.api_ship_order` |
| `/api/tasks/amazon-shops/` | Amazon 店铺管理 | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin | `task.view.task_upload_views.get_amazon_shops_api` |
| `/api/tasks/amazon-upload/pending-files/` | get pending files | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin | `task.view.task_detail_views.get_pending_files_api` |
| `/api/tasks/amazon-upload/update-status/` | update upload status | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin | `task.view.task_detail_views.update_upload_status_api` |
| `/api/update-divi-export-status/` | update divi export status | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；运营/店铺数据范围限制 | `amazon.view.views_amazon_order.update_divi_export_status_api` |

## Divi（11）

| API | 用途 | 权限/限制 | View |
| --- | --- | --- | --- |
| `/api/divi/export-templates/` | get divi export templates | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；公司数据范围限制 | `task.view.task_api_views.get_divi_export_templates_api` |
| `/api/divi/export-templates/by-shop/` | get divi export templates by shop | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；公司数据范围限制 | `task.view.task_api_views.get_divi_export_templates_by_shop_api` |
| `/api/divi/image-classifies/` | get divi image classifies | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin | `task.view.task_api_views.get_divi_image_classifies_api` |
| `/api/divi/products/` | get divi products | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin | `task.view.task_api_views.get_divi_products_api` |
| `/api/divi/products/<int:product_id>/detail/` | get divi product detail | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin | `task.view.task_api_views.get_divi_product_detail_api` |
| `/api/divi/sync-image-classify/` | sync image classify | 全局登录中间件：默认需要登录 | `divi.views.sync_image_classify_api` |
| `/api/divi/sync-templates/` | sync templates | 全局登录中间件：默认需要登录；公司数据范围限制 | `divi.views.sync_templates_api` |
| `/api/external/divi-account/` | 外部系统调用接口 | 外部接口白名单：中间件放行 | `general.api.divi_account_api.divi_account_query_api` |
| `/api/refresh-temu-divi-status/` | refresh temu divi status | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin | `temu.view.views_temu_order.refresh_temu_divi_status_api` |
| `/api/temu-order-to-divi-and-lingxing/` | temu order to divi and lingxing | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin | `temu.view.views_temu_order.temu_order_to_divi_and_lingxing_api` |
| `/api/update-temu-divi-export-status/` | update temu divi export status | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin | `temu.view.views_temu_order.update_temu_divi_export_status_api` |

## Temu（12）

| API | 用途 | 权限/限制 | View |
| --- | --- | --- | --- |
| `/api/batch-upsert-sku/` | batch upsert sku | 免登录白名单：Temu SKU 批量新增/更新 | `temu.view.api.sku_api.batch_upsert_sku_api` |
| `/api/download-temu-label/` | download temu label | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin | `temu.view.views_temu_order.download_temu_label_api` |
| `/api/export-temu-orders-excel/` | Temu 订单管理 | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin | `temu.view.views_temu_order.export_temu_orders_excel` |
| `/api/get-temu-shop-password/` | get temu shop password | 免登录白名单：Temu 店铺密码查询 | `temu.view.api.sku_api.get_temu_shop_password_api` |
| `/api/temu-customers/` | get customers | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；公司数据范围限制 | `general.views_temu_management.get_customers_api` |
| `/api/temu-orders-list/` | Temu 订单管理 | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；公司数据范围限制；运营/店铺数据范围限制 | `temu.view.views_temu_order.get_temu_orders_list_api` |
| `/api/temu-shops/` | Temu 店铺管理 | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；公司数据范围限制；运营/店铺数据范围限制 | `general.views_temu_management.get_temu_shops_api` |
| `/api/temu-shops/<int:shop_id>/update-dimensions/` | Temu 店铺管理 | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin | `general.views_temu_management.update_temu_shop_dimensions_api` |
| `/api/temu-shops/<int:shop_id>/update/` | Temu 店铺管理 | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin | `general.views_temu_management.update_temu_shop_api` |
| `/api/temu-shops/bulk-update-operator/` | Temu 店铺管理 | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；公司数据范围限制；运营/店铺数据范围限制 | `general.views_temu_management.bulk_update_operator_api` |
| `/api/temu-shops/bulk-update-project/` | Temu 店铺管理 | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；公司数据范围限制 | `general.views_temu_management.bulk_update_project_api` |
| `/api/temu-shops/create/` | Temu 店铺管理 | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；公司数据范围限制 | `general.views_temu_management.create_temu_shop_api` |

## 主题/侵权（40）

| API | 用途 | 权限/限制 | View |
| --- | --- | --- | --- |
| `/api/amazon-batch-download/` | api amazon batch download | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin | `theme.view.views_crawler.api_amazon_batch_download` |
| `/api/amazon-products/` | 主题产品库/亚马逊产品数据 | 全局登录中间件：默认需要登录；公司模块+用户权限：主题板块（公司已授权，且用户需有主题权限码 8/555） | `theme.view.views.api_amazon_products` |
| `/api/amazon-products/<str:asin>/` | 主题产品库/亚马逊产品数据 | 全局登录中间件：默认需要登录；公司模块+用户权限：主题板块（公司已授权，且用户需有主题权限码 8/555） | `theme.view.views.api_product_detail` |
| `/api/amazon-products/<str:asin>/delete/` | 主题产品库/亚马逊产品数据 | 全局登录中间件：默认需要登录；公司模块+用户权限：主题板块（公司已授权，且用户需有主题权限码 8/555） | `theme.view.views.api_delete_product` |
| `/api/amazon-products/<str:asin>/update/` | 主题产品库/亚马逊产品数据 | 全局登录中间件：默认需要登录；公司模块+用户权限：主题板块（公司已授权，且用户需有主题权限码 8/555） | `theme.view.views.api_update_product` |
| `/api/amazon-products/batch-risk-check/` | 主题产品库/亚马逊产品数据 | 全局登录中间件：默认需要登录；公司模块+用户权限：主题板块（公司已授权，且用户需有主题权限码 8/555） | `theme.view.views.api_batch_risk_check` |
| `/api/amazon-products/bulk-update-type/` | 主题产品库/亚马逊产品数据 | 全局登录中间件：默认需要登录；公司模块+用户权限：主题板块（公司已授权，且用户需有主题权限码 8/555） | `theme.view.views.api_bulk_update_product_type` |
| `/api/amazon-products/create/` | 主题产品库/亚马逊产品数据 | 全局登录中间件：默认需要登录；公司模块+用户权限：主题板块（公司已授权，且用户需有主题权限码 8/555） | `theme.view.views.api_create_product` |
| `/api/amazon-products/report/` | 主题产品库/亚马逊产品数据 | 全局登录中间件：默认需要登录；公司模块+用户权限：主题板块（公司已授权，且用户需有主题权限码 8/555） | `theme.view.views.api_report_product` |
| `/api/amazon-products/statistics/` | 主题产品库/亚马逊产品数据 | 全局登录中间件：默认需要登录；公司模块+用户权限：主题板块（公司已授权，且用户需有主题权限码 8/555） | `theme.view.views.api_product_statistics` |
| `/api/amazon-products/suggestions/` | 主题产品库/亚马逊产品数据 | 全局登录中间件：默认需要登录；公司模块+用户权限：主题板块（公司已授权，且用户需有主题权限码 8/555） | `theme.view.views.api_product_suggestions` |
| `/api/amazon-products/unreport/` | 主题产品库/亚马逊产品数据 | 全局登录中间件：默认需要登录；公司模块+用户权限：主题板块（公司已授权，且用户需有主题权限码 8/555） | `theme.view.views.api_unreport_product` |
| `/api/amazon-search-page/` | api amazon search page | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin | `theme.view.views_crawler.api_amazon_search_page` |
| `/api/amazon-search/` | api amazon search | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin | `theme.view.views_crawler.api_amazon_search` |
| `/api/external/amazon-products/` | 主题产品库/亚马逊产品数据 | 外部接口白名单：中间件放行，view 内应校验 X-RPA-Secret；接口密钥校验：X-RPA-Secret | `theme.view.views.external_api_amazon_products` |
| `/api/health-check/` | api health check | 全局登录中间件：默认需要登录 | `theme.view.views.api_health_check` |
| `/api/market-categories/` | 迪唯产业大数据分类 | 免登录白名单：迪唯分类数据；view 仍会执行主题模块权限检查；公司模块+用户权限：主题板块（公司已授权，且用户需有主题权限码 8/555） | `theme.view.views_dw_data.api_market_categories` |
| `/api/nice-classification/` | 尼斯分类列表 | 全局登录中间件：默认需要登录；公司模块+用户权限：侵权板块（公司已授权，且用户需有侵权权限码 556/555） | `theme.view.views_vocabulary.api_nice_classification_list` |
| `/api/niche-markets/` | 迪唯产业大数据市场列表 | 免登录白名单：迪唯市场数据；view 仍会执行主题模块权限检查；公司模块+用户权限：主题板块（公司已授权，且用户需有主题权限码 8/555） | `theme.view.views_dw_data.api_niche_markets` |
| `/api/shops/` | api shop list | 全局登录中间件：默认需要登录；公司模块+用户权限：侵权板块（公司已授权，且用户需有侵权权限码 556/555）；公司数据范围限制 | `theme.view.views_vocabulary.api_shop_list` |
| `/api/theme-aggregation/` | 亚马逊最热主题/聚合主题 | 全局登录中间件：默认需要登录；公司模块+用户权限：主题板块（公司已授权，且用户需有主题权限码 8/555） | `theme.view.views_new_release.api_theme_aggregation_list` |
| `/api/theme-aggregation/asins/` | 亚马逊最热主题/聚合主题 | 全局登录中间件：默认需要登录；公司模块+用户权限：主题板块（公司已授权，且用户需有主题权限码 8/555） | `theme.view.views_new_release.api_theme_aggregation_asins` |
| `/api/theme-cluster-aggregation/` | api cluster aggregation list | 全局登录中间件：默认需要登录；公司模块+用户权限：主题板块（公司已授权，且用户需有主题权限码 8/555） | `theme.view.views_new_release.api_cluster_aggregation_list` |
| `/api/theme-cluster-aggregation/asins/` | api cluster aggregation asins | 全局登录中间件：默认需要登录；公司模块+用户权限：主题板块（公司已授权，且用户需有主题权限码 8/555） | `theme.view.views_new_release.api_cluster_aggregation_asins` |
| `/api/theme-new-release/` | 亚马逊最新主题 | 全局登录中间件：默认需要登录；公司模块+用户权限：主题板块（公司已授权，且用户需有主题权限码 8/555） | `theme.view.views_new_release.api_new_release_list` |
| `/api/theme-novelty-aggregation/` | 最新成交主题/新品聚合 | 全局登录中间件：默认需要登录；公司模块+用户权限：主题板块（公司已授权，且用户需有主题权限码 8/555） | `theme.view.views_novelty_aggregation.api_novelty_aggregation_list` |
| `/api/theme-novelty-aggregation/asins/` | 最新成交主题/新品聚合 | 全局登录中间件：默认需要登录；公司模块+用户权限：主题板块（公司已授权，且用户需有主题权限码 8/555） | `theme.view.views_novelty_aggregation.api_novelty_aggregation_asins` |
| `/api/theme-novelty-cluster-aggregation/` | 最新成交主题/新品聚合 | 全局登录中间件：默认需要登录；公司模块+用户权限：主题板块（公司已授权，且用户需有主题权限码 8/555） | `theme.view.views_novelty_aggregation.api_novelty_cluster_aggregation_list` |
| `/api/theme-novelty-cluster-aggregation/asins/` | 最新成交主题/新品聚合 | 全局登录中间件：默认需要登录；公司模块+用户权限：主题板块（公司已授权，且用户需有主题权限码 8/555） | `theme.view.views_novelty_aggregation.api_novelty_cluster_aggregation_asins` |
| `/api/theme-recommended/` | 推荐主题 | 全局登录中间件：默认需要登录；公司模块+用户权限：主题板块（公司已授权，且用户需有主题权限码 8/555） | `theme.view.views_recommended_theme.api_recommended_theme_list` |
| `/api/theme-recommended/asins/` | 推荐主题 | 全局登录中间件：默认需要登录；公司模块+用户权限：主题板块（公司已授权，且用户需有主题权限码 8/555） | `theme.view.views_recommended_theme.api_recommended_theme_asins` |
| `/api/trademark-info/` | 美标网商标词库查询 | 全局登录中间件：默认需要登录；公司模块+用户权限：侵权板块（公司已授权，且用户需有侵权权限码 556/555） | `theme.view.views_vocabulary.api_trademark_info_list` |
| `/api/trend/search/` | 侵权风险查询 | 免登录白名单：侵权词查询接口；view 仍会执行模块权限检查；公司模块+用户权限：侵权板块（公司已授权，且用户需有侵权权限码 556/555） | `theme.view.views_trend.trend_search` |
| `/api/tro-table/` | 侵权词库增删改查/导入导出 | 全局登录中间件：默认需要登录；公司模块+用户权限：侵权板块（公司已授权，且用户需有侵权权限码 556/555） | `theme.view.views_vocabulary.api_tro_table_list` |
| `/api/tro-table/create/` | 侵权词库增删改查/导入导出 | 全局登录中间件：默认需要登录；公司模块+用户权限：侵权板块（公司已授权，且用户需有侵权权限码 556/555）；公司数据范围限制 | `theme.view.views_vocabulary.api_create_tro_record` |
| `/api/tro-table/delete/` | 侵权词库增删改查/导入导出 | 全局登录中间件：默认需要登录；公司模块+用户权限：侵权板块（公司已授权，且用户需有侵权权限码 556/555）；公司数据范围限制 | `theme.view.views_vocabulary.api_delete_tro_record` |
| `/api/tro-table/download-template/` | 侵权词库增删改查/导入导出 | 全局登录中间件：默认需要登录；公司模块+用户权限：侵权板块（公司已授权，且用户需有侵权权限码 556/555） | `theme.view.views_vocabulary.download_templates` |
| `/api/tro-table/import/` | 侵权词库增删改查/导入导出 | 全局登录中间件：默认需要登录；公司模块+用户权限：侵权板块（公司已授权，且用户需有侵权权限码 556/555）；公司数据范围限制 | `theme.view.views_vocabulary.api_import_tro_records` |
| `/api/tro-table/update/` | 侵权词库增删改查/导入导出 | 全局登录中间件：默认需要登录；公司模块+用户权限：侵权板块（公司已授权，且用户需有侵权权限码 556/555）；公司数据范围限制 | `theme.view.views_vocabulary.api_update_tro_record` |
| `/api/vocabulary/words-split/` | 词语分词 | 全局登录中间件：默认需要登录；公司模块+用户权限：侵权板块（公司已授权，且用户需有侵权权限码 556/555） | `theme.view.views_trend.words_split_api` |

## 任务/审批（56）

| API | 用途 | 权限/限制 | View |
| --- | --- | --- | --- |
| `/api/external/approval/update-exec-status/` | 外部系统调用接口 | 外部接口白名单：中间件放行，通常由接口自身业务校验/回调来源控制 | `task.view.approval_views.external_update_exec_status_api` |
| `/api/external/tasks/detail/` | 外部系统调用接口 | 外部接口白名单：中间件放行，通常由接口自身业务校验/回调来源控制 | `task.view.task_api_views.external_get_task_detail_api` |
| `/api/external/tasks/subtasks/detail/` | 外部系统调用接口 | 外部接口白名单：中间件放行，通常由接口自身业务校验/回调来源控制 | `task.view.task_api_views.external_get_subtask_detail_api` |
| `/api/external/tasks/subtasks/update-detail/` | 外部系统调用接口 | 外部接口白名单：中间件放行，通常由接口自身业务校验/回调来源控制 | `task.view.task_api_views.external_update_subtask_detail_api` |
| `/api/external/tasks/subtasks/update-status/` | 外部系统调用接口 | 外部接口白名单：中间件放行，通常由接口自身业务校验/回调来源控制 | `task.view.task_api_views.external_update_subtask_status_api` |
| `/api/external/tasks/update-status/` | 外部系统调用接口 | 外部接口白名单：中间件放行，通常由接口自身业务校验/回调来源控制 | `task.view.task_api_views.external_update_task_status_api` |
| `/api/products/<int:pk>/` | get product requirement detail | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin | `task.view.product_views.get_product_requirement_detail_api` |
| `/api/products/<int:pk>/claim/` | claim product requirement | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin | `task.view.product_views.claim_product_requirement_api` |
| `/api/products/<int:pk>/complete/` | complete product design | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin | `task.view.product_views.complete_product_design_api` |
| `/api/products/<int:pk>/export/` | export product requirement excel | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin | `task.view.product_views.export_product_requirement_excel_api` |
| `/api/products/<int:pk>/update/` | update product requirement | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin | `task.view.product_views.update_product_requirement_api` |
| `/api/products/create/` | create product requirement | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin | `task.view.product_views.create_product_requirement_api` |
| `/api/products/list/` | get product requirements | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin | `task.view.product_views.get_product_requirements_api` |
| `/api/products/recrawl/` | recrawl product requirement | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin | `task.view.product_views.recrawl_product_requirement_api` |
| `/api/products/reject/` | reject product requirements | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin | `task.view.product_views.reject_product_requirements_api` |
| `/api/products/status-choices/` | get status choices | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin | `task.view.product_views.get_status_choices_api` |
| `/api/task/approvals/<int:approval_id>/delete/` | approval delete | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；公司数据范围限制 | `task.view.approval_views.approval_delete_api` |
| `/api/task/approvals/<int:approval_id>/detail/` | approval detail | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；公司数据范围限制 | `task.view.approval_views.approval_detail_api` |
| `/api/task/approvals/ad/asins/` | approval asins | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin | `task.view.approval_views.approval_asins_api` |
| `/api/task/approvals/ad/create/` | create ad approval | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；公司数据范围限制 | `task.view.approval_views.create_ad_approval_api` |
| `/api/task/approvals/ad/drafts/` | approval draft list | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；公司数据范围限制 | `task.view.approval_views.approval_draft_list_api` |
| `/api/task/approvals/ad/drafts/<int:approval_id>/` | approval draft detail | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；公司数据范围限制 | `task.view.approval_views.approval_draft_detail_api` |
| `/api/task/approvals/ad/meta/` | approval meta | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin | `task.view.approval_views.approval_meta_api` |
| `/api/task/approvals/ad/stores/` | approval stores | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin | `task.view.approval_views.approval_stores_api` |
| `/api/task/approvals/flow-config/` | approval flow config list | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；公司数据范围限制 | `task.view.approval_views.approval_flow_config_list_api` |
| `/api/task/approvals/flow-config/delete/` | approval flow config delete | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；公司数据范围限制 | `task.view.approval_views.approval_flow_config_delete_api` |
| `/api/task/approvals/flow-config/save/` | approval flow config save | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；公司数据范围限制 | `task.view.approval_views.approval_flow_config_save_api` |
| `/api/task/approvals/leader/action/` | approval leader action | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；公司数据范围限制 | `task.view.approval_views.approval_leader_action_api` |
| `/api/task/approvals/leader/list/` | approval leader list | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；公司数据范围限制 | `task.view.approval_views.approval_leader_list_api` |
| `/api/task/approvals/list/action/` | approval list action | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；公司数据范围限制 | `task.view.approval_views.approval_list_action_api` |
| `/api/task/approvals/list/data/` | approval list data | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；公司数据范围限制 | `task.view.approval_views.approval_list_data_api` |
| `/api/task/approvals/list/stats/` | approval list stats | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；公司数据范围限制 | `task.view.approval_views.approval_list_stats_api` |
| `/api/tasks/<int:task_id>/delete/` | delete task | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin | `task.view.task_api_views.delete_task_api` |
| `/api/tasks/<int:task_id>/detail/` | get task detail | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin | `task.view.task_detail_views.get_task_detail_api` |
| `/api/tasks/<int:task_id>/resend-webhook/` | resend task webhook | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin | `task.view.task_api_views.resend_task_webhook_api` |
| `/api/tasks/available-owners/` | get available owners | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin | `task.view.task_api_views.get_available_owners_api` |
| `/api/tasks/create/` | create task | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin | `task.view.task_api_views.create_task_api` |
| `/api/tasks/creators/` | get task creators | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin | `task.view.task_api_views.get_task_creators_api` |
| `/api/tasks/diwei-accounts/` | get diwei accounts | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；公司数据范围限制 | `task.view.task_api_views.get_diwei_accounts_api` |
| `/api/tasks/drafts/` | get drafts | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin | `task.view.task_api_views.get_drafts_api` |
| `/api/tasks/drafts/<int:task_id>/delete/` | delete draft | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin | `task.view.task_api_views.delete_draft_api` |
| `/api/tasks/drafts/latest/` | get latest draft | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin | `task.view.task_api_views.get_latest_draft_api` |
| `/api/tasks/gallery-paths/suggest/` | suggest gallery paths | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin | `task.view.task_api_views.suggest_gallery_paths_api` |
| `/api/tasks/generate-copy-no/` | generate copy task no | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin | `task.view.task_api_views.generate_copy_task_no_api` |
| `/api/tasks/generate-no/` | generate task no | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin | `task.view.task_api_views.generate_task_no_api` |
| `/api/tasks/list/` | get tasks list | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin | `task.view.task_api_views.get_tasks_list_api` |
| `/api/tasks/save-draft/` | save draft | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin | `task.view.task_api_views.save_draft_api` |
| `/api/tasks/shops/` | get available shops | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；运营/店铺数据范围限制 | `task.view.task_api_views.get_available_shops_api` |
| `/api/tasks/stats/` | get task stats | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin | `task.view.task_api_views.get_task_stats_api` |
| `/api/tasks/templates/` | get task templates | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin | `task.view.task_api_views.get_task_templates_api` |
| `/api/tasks/templates/<int:template_id>/delete/` | delete template | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin | `task.view.task_api_views.delete_template_api` |
| `/api/tasks/templates/<int:template_id>/load/` | load template | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin | `task.view.task_api_views.load_template_api` |
| `/api/tasks/templates/save/` | save template | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin | `task.view.task_api_views.save_template_api` |
| `/api/tasks/upload-temp/` | upload temp file | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin | `task.view.task_upload_views.upload_temp_file_api` |
| `/api/user/export-shop-products/` | get user export shop products | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin | `task.view.task_api_views.get_user_export_shop_products_api` |
| `/api/user/export-shop-products/save/` | save user export shop products | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin | `task.view.task_api_views.save_user_export_shop_products_api` |

## 供应链/物流（14）

| API | 用途 | 权限/限制 | View |
| --- | --- | --- | --- |
| `/api/couriers/` | 物流商列表 | 全局登录中间件：默认需要登录；公司模块+用户权限：物流板块（公司已授权，且用户需有物流相关权限码 5/6/557/555） | `track.view.view_tracking_management.get_couriers` |
| `/api/export-tracking-excel/` | 物流运单 Excel 导出 | 全局登录中间件：默认需要登录；公司模块+用户权限：物流板块（公司已授权，且用户需有物流相关权限码 5/6/557/555）；运营/店铺数据范围限制 | `track.view.view_tracking_management.export_tracking_excel` |
| `/api/external-procurement-products/` | 外部系统调用接口 | 全局登录中间件：默认需要登录 | `track.view.view_external_procurement.wrapped_view` |
| `/api/external-procurement-products/<int:product_id>/` | 外部系统调用接口 | 全局登录中间件：默认需要登录 | `track.view.view_external_procurement.wrapped_view` |
| `/api/external-procurement-products/batch-delete/` | 外部系统调用接口 | 全局登录中间件：默认需要登录 | `track.view.view_external_procurement.wrapped_view` |
| `/api/external-procurement-products/batch-update/` | 外部系统调用接口 | 全局登录中间件：默认需要登录 | `track.view.view_external_procurement.wrapped_view` |
| `/api/factories/` | 工厂列表 | 全局登录中间件：默认需要登录；公司模块+用户权限：物流板块（公司已授权，且用户需有物流相关权限码 5/6/557/555） | `track.view.view_tracking_management.get_factories` |
| `/api/import-tracking-excel/` | 物流运单 Excel 导入 | 全局登录中间件：默认需要登录；公司模块+用户权限：物流板块（公司已授权，且用户需有物流相关权限码 5/6/557/555） | `track.view.view_tracking_management.import_tracking_excel` |
| `/api/refresh-tracking/` | 刷新物流轨迹 | 全局登录中间件：默认需要登录；公司模块+用户权限：物流板块（公司已授权，且用户需有物流相关权限码 5/6/557/555） | `track.view.view_tracking_management.refresh_tracking` |
| `/api/toggle-cancel-status/` | toggle cancel status | 全局登录中间件：默认需要登录；公司模块+用户权限：物流板块（公司已授权，且用户需有物流相关权限码 5/6/557/555） | `track.view.view_tracking_management.toggle_cancel_status` |
| `/api/tracking-details/` | 物流轨迹详情 | 全局登录中间件：默认需要登录；公司模块+用户权限：物流板块（公司已授权，且用户需有物流相关权限码 5/6/557/555） | `track.view.view_tracking_management.tracking_details` |
| `/api/tracking-list/` | 物流运单列表查询/筛选 | 全局登录中间件：默认需要登录；公司模块+用户权限：物流板块（公司已授权，且用户需有物流相关权限码 5/6/557/555）；运营/店铺数据范围限制 | `track.view.view_tracking_management.tracking_list` |
| `/api/tracking-stats/` | 物流统计 | 全局登录中间件：默认需要登录；公司模块+用户权限：物流板块（公司已授权，且用户需有物流相关权限码 5/6/557/555）；用户权限码判断；运营/店铺数据范围限制 | `track.view.view_tracking_management.tracking_stats` |
| `/api/update-tracking-remark/` | update tracking remark | 全局登录中间件：默认需要登录；公司模块+用户权限：物流板块（公司已授权，且用户需有物流相关权限码 5/6/557/555） | `track.view.view_tracking_management.update_tracking_remark` |

## 库存（3）

| API | 用途 | 权限/限制 | View |
| --- | --- | --- | --- |
| `/inventory/api/factories/` | 工厂列表 | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin | `inventory.views.get_factories_api` |
| `/inventory/api/import/` | 库存列表/导入 | 免登录白名单：库存导入接口 | `inventory.views.import_inventory_excel` |
| `/inventory/api/list/` | 库存列表/导入 | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin | `inventory.views.get_inventory_list_api` |

## 数据需求（7）

| API | 用途 | 权限/限制 | View |
| --- | --- | --- | --- |
| `/data_req/api/create/` | 数据需求 | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；运营/店铺数据范围限制 | `data_req.view.requirement.RequirementCreateAPI` |
| `/data_req/api/delete/` | 数据需求 | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin | `data_req.view.requirement.RequirementDeleteAPI` |
| `/data_req/api/detail/` | 数据需求 | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin | `data_req.view.requirement.RequirementDetailAPI` |
| `/data_req/api/list/` | 数据需求 | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin | `data_req.view.requirement.RequirementListAPI` |
| `/data_req/api/stats/` | 数据需求 | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin | `data_req.view.requirement.RequirementStatsAPI` |
| `/data_req/api/status/` | 数据需求 | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；用户权限码判断；运营/店铺数据范围限制 | `data_req.view.requirement.RequirementStatusAPI` |
| `/data_req/api/update/` | 数据需求 | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；运营/店铺数据范围限制 | `data_req.view.requirement.RequirementUpdateAPI` |

## 通用/管理（42）

| API | 用途 | 权限/限制 | View |
| --- | --- | --- | --- |
| `/api/announcement/mark-as-read/` | 公告管理/阅读记录 | 全局登录中间件：默认需要登录 | `general.views.mark_announcement_as_read` |
| `/api/announcements/` | 公告管理/阅读记录 | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；用户权限码判断 | `general.views_announcement_management.get_announcements_api` |
| `/api/announcements/<int:announcement_id>/delete/` | 公告管理/阅读记录 | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；用户权限码判断 | `general.views_announcement_management.delete_announcement_api` |
| `/api/announcements/<int:announcement_id>/read-records/` | 公告管理/阅读记录 | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；用户权限码判断 | `general.views_announcement_management.get_announcement_read_records_api` |
| `/api/announcements/<int:announcement_id>/update/` | 公告管理/阅读记录 | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；用户权限码判断 | `general.views_announcement_management.update_announcement_api` |
| `/api/announcements/create/` | 公告管理/阅读记录 | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；用户权限码判断 | `general.views_announcement_management.create_announcement_api` |
| `/api/company/projects/` | get company projects | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；公司数据范围限制 | `general.view.views_user_management.get_company_projects_api` |
| `/api/company/users/` | get company users | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；公司数据范围限制 | `general.view.views_user_management.get_company_users_api` |
| `/api/customers/` | get customers | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；公司数据范围限制 | `general.views_amazon_management.get_customers_api` |
| `/api/operation-log/types/` | 操作日志 | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin | `general.view.view_operation_log.get_operation_types_api` |
| `/api/operation-logs/` | 操作日志 | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin | `general.view.view_operation_log.get_operation_logs_api` |
| `/api/operators/` | get all operators | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；公司数据范围限制；运营/店铺数据范围限制 | `general.views_amazon_management.get_all_operators_api` |
| `/api/ops-groups/` | get all ops groups | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；公司数据范围限制 | `general.views_amazon_management.get_all_ops_groups_api` |
| `/api/ops-groups/list` | get ops groups | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin | `general.view.views_general.get_ops_groups_api` |
| `/api/ops/list` | get ops list | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；公司数据范围限制；运营/店铺数据范围限制 | `general.view.views_general.get_ops_list` |
| `/api/performance/group_targets/` | 绩效目标/通知 | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；公司数据范围限制 | `general.views_performance.get_group_targets_api` |
| `/api/performance/group_targets/<int:target_id>/update/` | 绩效目标/通知 | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；公司数据范围限制 | `general.views_performance.update_group_target_api` |
| `/api/performance/group_targets/create/` | 绩效目标/通知 | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；公司数据范围限制 | `general.views_performance.create_group_target_api` |
| `/api/performance/operators_by_group/` | 绩效目标/通知 | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；公司数据范围限制；运营/店铺数据范围限制 | `general.views_performance.get_operators_by_group_api` |
| `/api/performance/ops_groups/` | 绩效目标/通知 | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；公司数据范围限制 | `general.views_performance.get_ops_groups_for_filter_api` |
| `/api/performance/personal_targets/` | 绩效目标/通知 | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；公司数据范围限制 | `general.views_performance.get_personal_targets_api` |
| `/api/performance/personal_targets/batch/` | 绩效目标/通知 | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；公司数据范围限制 | `general.views_performance.batch_create_personal_targets_api` |
| `/api/permissions/` | get permission configs | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；用户权限码判断 | `general.view.views_user_management.get_permission_configs_api` |
| `/api/profile/avatar/` | 个人资料 | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；公司数据范围限制 | `general.views_profile.upload_avatar_api` |
| `/api/profile/basic-info/` | 个人资料 | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；公司数据范围限制 | `general.views_profile.update_basic_info_api` |
| `/api/profile/password/` | 个人资料 | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；公司数据范围限制 | `general.views_profile.change_password_api` |
| `/api/roles/` | get roles | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；公司数据范围限制 | `general.view.views_user_management.get_roles_api` |
| `/api/system-admin/companies/` | 平台总后台：公司、模块、权限与主账号管理 | 全局登录中间件：默认需要登录；平台总后台限制：仅 user.id == 555；用户权限码判断 | `general.view.views_system_admin.system_companies_api` |
| `/api/system-admin/companies/<int:company_id>/owners/create/` | 平台总后台：公司、模块、权限与主账号管理 | 全局登录中间件：默认需要登录；平台总后台限制：仅 user.id == 555；公司数据范围限制 | `general.view.views_system_admin.system_company_owner_create_api` |
| `/api/system-admin/companies/<int:company_id>/update/` | 平台总后台：公司、模块、权限与主账号管理 | 全局登录中间件：默认需要登录；平台总后台限制：仅 user.id == 555；公司数据范围限制 | `general.view.views_system_admin.system_company_update_api` |
| `/api/system-admin/companies/create/` | 平台总后台：公司、模块、权限与主账号管理 | 全局登录中间件：默认需要登录；平台总后台限制：仅 user.id == 555 | `general.view.views_system_admin.system_company_create_api` |
| `/api/system-admin/modules/` | 平台总后台：公司、模块、权限与主账号管理 | 全局登录中间件：默认需要登录；平台总后台限制：仅 user.id == 555 | `general.view.views_system_admin.system_modules_api` |
| `/api/system-admin/permissions/` | 平台总后台：公司、模块、权限与主账号管理 | 全局登录中间件：默认需要登录；平台总后台限制：仅 user.id == 555 | `general.view.views_system_admin.system_permissions_api` |
| `/api/update-theme/` | update theme | 全局登录中间件：默认需要登录 | `general.views.update_theme` |
| `/api/users/` | get users | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；用户权限码判断；公司数据范围限制 | `general.view.views_user_management.get_users_api` |
| `/api/users/<int:user_id>/update/` | update user | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；用户权限码判断；公司数据范围限制 | `general.view.views_user_management.update_user_api` |
| `/api/users/all/` | get all users | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin | `general.view.view_operation_log.get_all_users_api` |
| `/api/users/bulk-department/` | bulk update department | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；公司数据范围限制 | `general.view.views_user_management.bulk_update_department_api` |
| `/api/users/bulk-permissions/` | bulk update permissions | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；用户权限码判断；公司数据范围限制 | `general.view.views_user_management.bulk_update_permissions_api` |
| `/api/users/create/` | create user | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；用户权限码判断；公司数据范围限制 | `general.view.views_user_management.create_user_api` |
| `/api/users/departments/` | get departments | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；公司数据范围限制 | `general.view.views_user_management.get_departments_api` |
| `/api/users/ops-groups/` | get ops groups | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；公司数据范围限制 | `general.view.views_user_management.get_ops_groups_api` |

## 通用API（2）

| API | 用途 | 权限/限制 | View |
| --- | --- | --- | --- |
| `/api/general/operators/` | get operators | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；公司数据范围限制；运营/店铺数据范围限制 | `api.general.group_and_ops.get_operators_api` |
| `/api/general/ops-groups/` | get ops groups | 全局登录中间件：默认需要登录；显式 login_required/LoginRequiredMixin；公司数据范围限制 | `api.general.group_and_ops.get_ops_groups_api` |
