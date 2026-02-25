import os
import sys
import asyncio
import time
import logging
from datetime import datetime, timedelta
from typing import List, Optional

# ========== Django 环境初始化 ==========
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
sys.path.append(PROJECT_ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Overlord.settings")
import django

django.setup()

# ========== 导入模型和API ==========
from asgiref.sync import sync_to_async
from django.db import IntegrityError
from api.lingxing.Y_OpenApi import get_api_resp
from advertisement.models import LingXingAdHourlyData, LingXingCampaign
from amazon.models import LingXingAmazonShop

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def fetch_campaign_hourly_data(
        campaign_id: int,
        report_date: str,
        lingxing_shop_id: int,
        app_id: str = "",
        app_secret: str = ""
) -> tuple[int, int]:
    """
    获取单个 Campaign 的小时数据并写入数据库
    返回: (处理条数, 新增条数)
    """
    length = 200  # 每页条数
    offset = 0
    total_processed = 0
    total_created = 0

    logger.info(f"开始获取 Campaign {campaign_id} 的 {report_date} 小时数据...")

    while True:
        req_body = {
            "campaign_id": str(campaign_id),
            "report_date": report_date,
            "agg_dimension": "both_ad_target",
            "length": length,
            "offset": offset
        }

        try:
            resp = await get_api_resp(
                req_body,
                api_path="/pb/openapi/newad/spTargetHourData",
                app_id=app_id,
                app_secret=app_secret
            )

            if resp.code != 0:
                logger.error(f"API 请求失败: {resp.message}")
                break

            total = resp.total
            data_list = resp.data

            if not data_list:
                break

            logger.info(f"Campaign {campaign_id}: 获取 {len(data_list)} 条 (offset={offset}, total={total})")

            # 批量处理写入
            for data in data_list:
                try:
                    # 字段映射（API字段 -> 模型字段）
                    defaults = {
                        'lingxing_shop_id': lingxing_shop_id,
                        'campaign_id': data.get('campaign_id'),
                        'ad_group_id': data.get('group_id'),  # API返回group_id，模型是ad_group_id
                        'ad_id': data.get('ad_id'),
                        'targeting_id': data.get('targeting_id'),
                        'report_date': data.get('report_date'),  # 已经是 '2026-02-24' 格式
                        'hour': data.get('hour'),
                        'asin': data.get('asin'),
                        'msku': data.get('msku'),
                        'targeting': data.get('targeting'),
                        'match_type': data.get('match_type'),  # BROAD/EXACT/PHRASE
                        'impressions': data.get('impressions', 0) or 0,
                        'clicks': data.get('clicks', 0) or 0,
                        'cost': data.get('cost', 0) or 0,
                        'orders': data.get('orders', 0) or 0,
                        'sales': data.get('sales', 0) or 0,
                        'units': data.get('units', 0) or 0,
                        'same_orders': data.get('same_orders', 0) or 0,
                        'same_sales': data.get('same_sales', 0) or 0,
                        'same_units': data.get('same_units', 0) or 0,
                    }

                    # 使用 update_or_create 防止重复
                    # 注意：unique_together 是 ['lingxing_shop', 'report_date', 'hour', 'ad_id', 'targeting_id']
                    # 但这里 lingxing_shop_id 已知，可以直接用
                    obj, created = await sync_to_async(
                        LingXingAdHourlyData.objects.update_or_create,
                        thread_sensitive=True
                    )(
                        lingxing_shop_id=lingxing_shop_id,
                        report_date=data.get('report_date'),
                        hour=data.get('hour'),
                        ad_id=data.get('ad_id'),
                        targeting_id=data.get('targeting_id'),
                        defaults=defaults
                    )

                    if created:
                        total_created += 1
                    total_processed += 1

                except Exception as e:
                    logger.error(f"写入数据失败 (ad_id={data.get('ad_id')}): {e}")
                    continue

            # 检查是否还有下一页
            offset += length
            if offset >= total:
                break

            # 防限流
            await asyncio.sleep(0.3)

        except Exception as e:
            logger.error(f"获取 Campaign {campaign_id} 数据失败: {e}")
            break

    logger.info(f"Campaign {campaign_id} 完成: 处理 {total_processed} 条，新增 {total_created} 条")
    return total_processed, total_created


async def sync_all_campaigns_hourly(
        report_date: str,
        sid: Optional[str] = None,
        app_id: str = "",
        app_secret: str = ""
):
    """
    同步所有 Campaign 的小时数据
    如果指定 sid，只同步该店铺下的 Campaign
    """
    # 获取 Campaign 列表（带店铺信息）
    campaigns_qs = LingXingCampaign.objects.select_related('lingxing_shop')

    if sid:
        campaigns_qs = campaigns_qs.filter(lingxing_shop__sid=sid)

    campaigns = await sync_to_async(list)(campaigns_qs)

    logger.info(f"共找到 {len(campaigns)} 个 Campaign 需要同步")

    total_records = 0
    total_new = 0

    for campaign in campaigns:
        # 获取该 Campaign 对应的店铺ID（用于外键）
        lingxing_shop_id = campaign.lingxing_shop_id

        processed, created = await fetch_campaign_hourly_data(
            campaign_id=campaign.campaign_id,
            report_date=report_date,
            lingxing_shop_id=lingxing_shop_id,
            app_id=app_id,
            app_secret=app_secret
        )

        total_records += processed
        total_new += created

        # 每个 Campaign 处理完休息一下，避免限流
        await asyncio.sleep(0.5)

    logger.info(f"全部完成: 共处理 {total_records} 条小时数据，新增 {total_new} 条")


async def demo_single():
    """单 Campaign 测试（你的 demo4 扩展版）"""
    SID = "508575"
    CAMPAIGN_ID = "167060198167068"
    REPORT_DATE = "2026-02-24"
    APP_ID = ""
    APP_SECRET = ""

    # 获取店铺ID
    try:
        shop = await sync_to_async(LingXingAmazonShop.objects.get)(sid=SID)
        shop_id = shop.sid  # 注意：LingXingAmazonShop 的主键是 sid（BigInteger）
    except LingXingAmazonShop.DoesNotExist:
        logger.error(f"店铺 {SID} 不存在")
        return

    processed, created = await fetch_campaign_hourly_data(
        campaign_id=int(CAMPAIGN_ID),
        report_date=REPORT_DATE,
        lingxing_shop_id=shop_id,
        app_id=APP_ID,
        app_secret=APP_SECRET
    )

    print(f"单 Campaign 同步完成: 处理 {processed} 条，新增 {created} 条")


async def demo_all():
    """同步所有 Campaign（指定日期）"""
    REPORT_DATE = "2026-02-24"  # 修改为你需要的日期
    SID = "508575"  # 如果只想同步特定店铺，指定sid；注释掉这行则同步全部
    APP_ID = ""
    APP_SECRET = ""

    await sync_all_campaigns_hourly(
        report_date=REPORT_DATE,
        sid=SID,  # 如果不需要限定店铺，删除这行或改为 None
        app_id=APP_ID,
        app_secret=APP_SECRET
    )


if __name__ == '__main__':
    # 二选一运行：
    asyncio.run(demo_single())  # 单 Campaign 测试
    # asyncio.run(demo_all())  # 全部 Campaign 同步