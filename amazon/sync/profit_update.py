# amazon/sync/profit_update.py
"""
领星 MSKU维度每日利润数据同步
从 /basicOpen/finance/mreport/OrderProfit 接口同步

使用方式:
    python amazon/sync/profit_update.py
"""

import os
import sys

# 将项目根目录加入 Python 路径（确保模块导入正常）
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import asyncio
from datetime import datetime, timedelta

from asgiref.sync import sync_to_async


# ========== 延迟导入（在 django.setup() 之后） ==========
# 这些模块在文件顶部导入会导致 Django 配置错误
# 实际使用时在 main() 或各函数内部导入

def _get_models():
    """延迟导入 Django 模型"""
    from amazon.models import (
        LingXingAmazonShop,
        AmazonMSKUDailyProfit,
        AmazonMSKUDailyProfitPriceList,
        AmazonMSKUDailyProfitLocalInfo,
        AmazonMSKUDailyProfitASIN,
        AmazonMSKUDailyProfitCountry,
    )
    from general.models import AmazonShop
    from django.db import models as django_models
    return (
        LingXingAmazonShop, AmazonMSKUDailyProfit,
        AmazonMSKUDailyProfitPriceList, AmazonMSKUDailyProfitLocalInfo,
        AmazonMSKUDailyProfitASIN, AmazonMSKUDailyProfitCountry,
        AmazonShop, django_models
    )


def _get_api():
    """延迟导入 API 模块"""
    from api.lingxing.Y_OpenApi import get_api_resp
    return get_api_resp


# API字段名 -> 模型字段名 映射
API_FIELD_MAPPING = {
    # 销量
    'volume': 'volume',
    'afn_volume': 'afn_volume',
    'mfn_volume': 'mfn_volume',
    'ad_volume': 'ad_volume',
    'replacement_quantity': 'replacement_quantity',
    'multi_channel_volume': 'multi_channel_volume',
    'avg_volume': 'avg_volume',
    # 退货退款
    'return_quantity': 'return_quantity',
    'return_rate': 'return_rate',
    'refund_quantity': 'refund_quantity',
    'refund_amount': 'refund_amount',
    'refund_amount_rate': 'refund_amount_rate',
    # 销售额
    'amount': 'amount',
    'tax_amount': 'tax_amount',
    'net_amount': 'net_amount',
    'avg_net_amount': 'avg_net_amount',
    'afn_amount': 'afn_amount',
    'mfn_amount': 'mfn_amount',
    'shipping_cost': 'shipping_cost',
    'promotion_discount': 'promotion_discount',
    'pm_discount': 'pm_discount',
    'sp_discount': 'sp_discount',
    # 广告销售
    'ad_sales_amount': 'ad_sales_amount',
    'ad_sales_amount_sp': 'ad_sales_amount_sp',
    'ad_sales_amount_sd': 'ad_sales_amount_sd',
    'ad_sales_amount_sb': 'ad_sales_amount_sb',
    'ad_sales_amount_sbv': 'ad_sales_amount_sbv',
    'ad_volume_sp': 'ad_volume_sp',
    'ad_volume_sd': 'ad_volume_sd',
    'ad_volume_sb': 'ad_volume_sb',
    'ad_volume_sbv': 'ad_volume_sbv',
    # 平台/FBA费用
    'selling_fee': 'selling_fee',
    'fulfillment_fee': 'fulfillment_fee',
    'other_order_fee': 'other_order_fee',
    'fba_fulfillment_fee': 'fba_fulfillment_fee',
    'fba_storage_fee': 'fba_storage_fee',
    # 广告花费
    'spend': 'spend',
    'ads_sp_cost': 'ads_sp_cost',
    'ads_sb_cost': 'ads_sb_cost',
    'ads_sbv_cost': 'ads_sbv_cost',
    'ads_sd_cost': 'ads_sd_cost',
    # 成本
    'purchase_costs': 'purchase_costs',
    'avg_purchase_costs': 'avg_purchase_costs',
    'logistics_costs': 'logistics_costs',
    'avg_logistics_costs': 'avg_logistics_costs',
    'other_costs': 'other_costs',
    'avg_other_costs': 'avg_other_costs',
    'total_costs': 'total_costs',
    # 利润
    'gross_profit': 'gross_profit',
    'gross_margin': 'gross_margin',
    'avg_gross_profit': 'avg_gross_profit',
    'net_gross_margin': 'net_gross_margin',
    # 占比/率
    'selling_fee_rate': 'selling_fee_rate',
    'fulfillment_fee_rate': 'fulfillment_fee_rate',
    'spend_rate': 'spend_rate',
    'total_stock_fee_rate': 'total_stock_fee_rate',
    # 推广/仓储
    'promotion_fee': 'promotion_fee',
    'off_site_promotion_fee': 'off_site_promotion_fee',
    'total_stock_fee': 'total_stock_fee',
    # shared_ 费用
    'shared_fba_inbound_convenience_fee': 'shared_fba_inbound_convenience_fee',
    'shared_fba_customer_return_fee': 'shared_fba_customer_return_fee',
    'shared_fba_overage_fee': 'shared_fba_overage_fee',
    'shared_fba_disposal_fee': 'shared_fba_disposal_fee',
    'shared_fba_removal_fee': 'shared_fba_removal_fee',
    'shared_reimbursements': 'shared_reimbursements',
    'shared_fba_liquidation_proceeds': 'shared_fba_liquidation_proceeds',
    'shared_fba_liquidation_proceeds_adjustments': 'shared_fba_liquidation_proceeds_adjustments',
    'shared_adjustments_fee': 'shared_adjustments_fee',
    'shared_fba_storage_fee': 'shared_fba_storage_fee',
    'shared_long_term_storage_fee': 'shared_long_term_storage_fee',
    'shared_fba_inbound_defect_fee': 'shared_fba_inbound_defect_fee',
    'shared_fba_international_inbound_fee': 'shared_fba_international_inbound_fee',
    'shared_amazon_partnered_carrier_shipment_fee': 'shared_amazon_partnered_carrier_shipment_fee',
    'shared_other_fba_inventory_fees': 'shared_other_fba_inventory_fees',
    'shared_fba_transaction_customer_return_fee': 'shared_fba_transaction_customer_return_fee',
    'shared_item_fee_adjustment': 'shared_item_fee_adjustment',
    'shared_cost_of_advertising': 'shared_cost_of_advertising',
    'shared_safe_t_reimbursement': 'shared_safe_t_reimbursement',
    'shared_netco_transaction': 'shared_netco_transaction',
    'shared_clawbacks': 'shared_clawbacks',
    'shared_commingling_vat_income': 'shared_commingling_vat_income',
    'shared_amazon_shipping_reimbursement': 'shared_amazon_shipping_reimbursement',
    'shared_others': 'shared_others',
    # 收入类
    'inventory_credit': 'inventory_credit',
    'cost_of_points_granted': 'cost_of_points_granted',
    'total_other_granted': 'total_other_granted',
    'gift_wrap_credits': 'gift_wrap_credits',
    'a_to_z_guarantee_claims': 'a_to_z_guarantee_claims',
    'selling_other_fee': 'selling_other_fee',
    # 商品信息
    'item_name': 'item_name',
    'small_image_url': 'small_image_url',
    'principal_names': 'principal_names',
    'is_parent': 'is_parent',
}


def _parse_int(value):
    """解析API返回值为int，空字符串转为0"""
    if value is None or value == '':
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


@sync_to_async
def _save_profit_data(lx_shop, sid, sync_date, data_list):
    """同步保存利润数据到数据库（在async中调用需用sync_to_async包装）"""
    (
        LingXingAmazonShop, AmazonMSKUDailyProfit,
        AmazonMSKUDailyProfitPriceList, AmazonMSKUDailyProfitLocalInfo,
        AmazonMSKUDailyProfitASIN, AmazonMSKUDailyProfitCountry,
        AmazonShop, django_models
    ) = _get_models()

    created_count = 0
    updated_count = 0

    for item in data_list:
        # 获取 seller_sku（从 price_list 中取第一个）
        price_list_data = item.get('price_list', [])
        seller_sku = ''
        if price_list_data and len(price_list_data) > 0:
            seller_sku = price_list_data[0].get('seller_sku', '')

        if not seller_sku:
            print(f"[警告] sid={sid}, date={sync_date} 的数据缺少 seller_sku，跳过")
            continue

        # 构建主表字段值
        profit_defaults = {
            'lxshop': lx_shop,
        }

        # 遍历映射，填充字段
        for api_field, model_field in API_FIELD_MAPPING.items():
            value = item.get(api_field)
            model_field_obj = AmazonMSKUDailyProfit._meta.get_field(model_field)

            if value is None or value == '':
                # 空值处理：根据字段类型给默认值
                if isinstance(model_field_obj, django_models.DecimalField):
                    profit_defaults[model_field] = 0
                elif isinstance(model_field_obj, django_models.IntegerField):
                    profit_defaults[model_field] = 0
                elif isinstance(model_field_obj, django_models.BigIntegerField):
                    profit_defaults[model_field] = 0
                elif isinstance(model_field_obj, django_models.BooleanField):
                    profit_defaults[model_field] = False
                else:
                    profit_defaults[model_field] = None
            else:
                profit_defaults[model_field] = value

        # 处理 JSONField 数组
        profit_defaults['parent_asins'] = item.get('parent_asins', []) or []
        profit_defaults['categories'] = item.get('categories', []) or []
        profit_defaults['brands'] = item.get('brands', []) or []

        # update_or_create 主表
        profit_obj, created = AmazonMSKUDailyProfit.objects.update_or_create(
            sid=sid,
            seller_sku=seller_sku,
            sync_date=sync_date,
            defaults=profit_defaults
        )

        if created:
            created_count += 1
        else:
            updated_count += 1

        # 清空并重建子表数据
        # 1. price_list
        profit_obj.price_list.all().delete()
        for pl in item.get('price_list', []):
            AmazonMSKUDailyProfitPriceList.objects.create(
                profit=profit_obj,
                principal_uids=pl.get('principal_uids', ''),
                local_sku=pl.get('local_sku', ''),
                item_name=pl.get('item_name', ''),
                cate_title=pl.get('cate_title', ''),
                local_name=pl.get('local_name', ''),
                sid=str(pl.get('sid', '')),
                is_delete=str(pl.get('is_delete', '')),
                brand_title=pl.get('brand_title', ''),
                volume=_parse_int(pl.get('volume')),
                small_main_image_url=pl.get('small_main_image_url', ''),
                site_url=pl.get('site_url', ''),
                parent_asin=pl.get('parent_asin', ''),
                seller_sku=pl.get('seller_sku', ''),
                asin=pl.get('asin', ''),
                status=str(pl.get('status', '')),
            )

        # 2. local_infos
        profit_obj.local_infos.all().delete()
        for li in item.get('local_infos', []):
            AmazonMSKUDailyProfitLocalInfo.objects.create(
                profit=profit_obj,
                local_sku=li.get('local_sku', ''),
                local_name=li.get('local_name', ''),
            )

        # 3. asins
        profit_obj.asins.all().delete()
        for ai in item.get('asins', []):
            AmazonMSKUDailyProfitASIN.objects.create(
                profit=profit_obj,
                asin=ai.get('asin', ''),
                asin_url=ai.get('asin_url', ''),
            )

        # 4. seller_store_countries
        profit_obj.seller_store_countries.all().delete()
        for sc in item.get('seller_store_countries', []):
            AmazonMSKUDailyProfitCountry.objects.create(
                profit=profit_obj,
                country=sc.get('country', ''),
                name=sc.get('name', ''),
            )

    return created_count, updated_count


async def update_profit(sid, start_date, end_date):
    """
    同步指定店铺和日期范围的 MSKU 利润数据

    Args:
        sid: 领星店铺ID
        start_date: 开始日期 (YYYY-MM-DD)
        end_date: 结束日期 (YYYY-MM-DD)

    Returns:
        tuple: (created_count, updated_count) 或 None（出错/跳过）
    """
    (
        LingXingAmazonShop, AmazonMSKUDailyProfit,
        AmazonMSKUDailyProfitPriceList, AmazonMSKUDailyProfitLocalInfo,
        AmazonMSKUDailyProfitASIN, AmazonMSKUDailyProfitCountry,
        AmazonShop, django_models
    ) = _get_models()
    get_api_resp = _get_api()

    # 1. 通过 sid 找到 LingXingAmazonShop
    try:
        lx_shop = await sync_to_async(LingXingAmazonShop.objects.get)(sid=sid)
    except LingXingAmazonShop.DoesNotExist:
        print(f"[跳过] 未找到 sid={sid} 对应的领星店铺")
        return None

    # 2. 找到绑定的本地 AmazonShop
    amazon_shop = await sync_to_async(lambda: lx_shop.amazon_shop)()
    if not amazon_shop:
        print(f"[跳过] sid={sid} 的领星店铺未绑定本地 AmazonShop")
        return None

    # 3. 找到所属 Project
    project = await sync_to_async(lambda: amazon_shop.project)()
    if not project:
        print(f"[跳过] sid={sid} 的本地店铺未绑定项目")
        return None

    # 4. 检查是否启用领星同步
    lingxing_sync_enabled = await sync_to_async(lambda: project.lingxing_sync_enabled)()
    if not lingxing_sync_enabled:
        print(f"[跳过] 项目 {project.name} 的领星同步已禁用 (lingxing_sync_enabled=False)")
        return None

    # 获取店铺名称（用于日志）
    shop_name = await sync_to_async(lambda: amazon_shop.shop_name or amazon_shop.amazon_shop_name or f"ID={amazon_shop.id}")()

    # 5. 获取领星 API 凭证
    app_id = await sync_to_async(lambda: project.lingxing_app_id)()
    app_secret = await sync_to_async(lambda: project.lingxing_app_secret)()
    if not app_id or not app_secret:
        print(f"[跳过] 项目 {project.name} 未配置领星 API 凭证, 店铺={shop_name}, sid={sid}")
        return None

    # 6. 调用 API 获取利润数据
    req_body = {
        "offset": 0,
        "length": 5000,
        "sids": [sid],
        "startDate": start_date,
        "endDate": end_date,
    }

    try:
        resp = await get_api_resp(
            req_body=req_body,
            api_path="/basicOpen/finance/mreport/OrderProfit",
            app_id=app_id,
            app_secret=app_secret
        )
    except Exception as e:
        print(f"[错误] sid={sid} API请求失败: {e}")
        return None

    # 7. 检查响应状态
    if resp.code != 0:
        print(
            f"[错误] 店铺={shop_name}, sid={sid}, 项目={project.name}, "
            f"API返回错误: code={resp.code}, message={resp.message}, "
            f"入参: req_body={req_body}, app_id={app_id}, app_secret={app_secret}"
        )
        return None

    data_list = resp.data or []
    if not data_list:
        print(f"[信息] sid={sid}, {start_date}~{end_date} 无数据返回")
        return 0, 0

    # 8. 保存数据到数据库
    sync_date = start_date  # 假设单日查询

    created_count, updated_count = await _save_profit_data(
        lx_shop=lx_shop,
        sid=sid,
        sync_date=sync_date,
        data_list=data_list
    )

    print(f"[完成] sid={sid}, date={sync_date}: 新增 {created_count} 条, 更新 {updated_count} 条")
    return created_count, updated_count


async def update_profit_daily(sid, date_str):
    """
    同步指定店铺某一天的利润数据（推荐入口）

    Args:
        sid: 领星店铺ID
        date_str: 日期 (YYYY-MM-DD)

    Returns:
        tuple: (created_count, updated_count) 或 None
    """
    return await update_profit(sid, date_str, date_str)


@sync_to_async
def _get_active_sids(country='美国'):
    """
    获取所有状态为 ACTIVE 的本地店铺对应的领星 sid 列表
    默认只取美国站点

    Args:
        country: 国家筛选，默认'美国'
    """
    (
        LingXingAmazonShop, AmazonMSKUDailyProfit,
        AmazonMSKUDailyProfitPriceList, AmazonMSKUDailyProfitLocalInfo,
        AmazonMSKUDailyProfitASIN, AmazonMSKUDailyProfitCountry,
        AmazonShop, django_models
    ) = _get_models()

    # 查询所有状态为 ACTIVE 的 AmazonShop
    active_shops = AmazonShop.objects.filter(
        shop_status=AmazonShop.ShopStatus.ACTIVE
    )

    sids = []
    for shop in active_shops:
        # 通过反向关联获取绑定的 LingXingAmazonShop，并筛选国家
        lx_shops = shop.lingxing_amazon_shops.filter(country=country)
        for lx in lx_shops:
            if lx.sid:
                sids.append(lx.sid)

    return sids


async def sync_all_shops_profit(days=7):
    """
    同步所有活跃店铺近 N 天的利润数据（默认7天，到昨天）

    Args:
        days: 回溯天数（默认7天）

    Returns:
        dict: 统计结果
    """
    # 1. 获取所有活跃店铺的 sid
    sids = await _get_active_sids()
    if not sids:
        print("[信息] 没有找到状态为 ACTIVE 的店铺")
        return {"total_shops": 0, "total_created": 0, "total_updated": 0, "errors": 0}

    print(f"[开始] 共 {len(sids)} 个活跃店铺需要同步，回溯 {days} 天")

    # 2. 计算日期范围（昨天往前推 days 天）
    yesterday = datetime.now().date() - timedelta(days=1)
    date_list = []
    for i in range(days):
        d = yesterday - timedelta(days=i)
        date_list.append(d.strftime("%Y-%m-%d"))

    # 按日期正序排列（先同步旧的）
    date_list.reverse()

    total_created = 0
    total_updated = 0
    errors = 0

    # 3. 循环店铺 × 日期
    for sid in sids:
        for date_str in date_list:
            try:
                result = await update_profit_daily(sid, date_str)
                if result:
                    created, updated = result
                    total_created += created
                    total_updated += updated
                elif result is None:
                    # 跳过或出错，已在函数内打印
                    errors += 1
            except Exception as e:
                print(f"[错误] sid={sid}, date={date_str} 同步异常: {e}")
                errors += 1

    print(f"[完成] 总计: 新增 {total_created} 条, 更新 {total_updated} 条, 异常 {errors} 次")
    return {
        "total_shops": len(sids),
        "total_created": total_created,
        "total_updated": total_updated,
        "errors": errors,
    }


def main():
    """
    入口函数：同步所有活跃店铺近7天到昨天的利润数据
    每天调用一次
    """
    import django

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Overlord.settings")
    django.setup()

    result = asyncio.run(sync_all_shops_profit(days=7))
    return result


if __name__ == "__main__":
    main()
