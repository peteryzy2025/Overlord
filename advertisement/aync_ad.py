import os
import sys
import asyncio
import time
import logging
from datetime import datetime, timedelta
from typing import List, Tuple, Callable, Any

# ========== Django 环境初始化 ==========
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
sys.path.append(PROJECT_ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Overlord.settings")
import django

django.setup()

# ========== 导入模型和API ==========
from asgiref.sync import sync_to_async
from api.lingxing.Y_OpenApi import get_api_resp
from advertisement.models import LingXingCampaign
from amazon.models import LingXingAmazonShop

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def timestamp_to_date(timestamp_ms: int) -> datetime.date:
    """毫秒时间戳转 date"""
    if not timestamp_ms:
        return None
    # 毫秒转秒
    timestamp_s = timestamp_ms / 1000
    return datetime.fromtimestamp(timestamp_s).date()


def parse_date_str(date_str: str) -> datetime.date:
    """日期字符串 '2026-01-27 00:00:00' 转 date"""
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str.split(' ')[0], '%Y-%m-%d').date()
    except:
        return None


def map_campaign_type(api_type: str) -> str:
    """API campaign_type 映射到模型枚举"""
    type_mapping = {
        'sponsoredProducts': 'SP',
        'sponsoredBrands': 'SB',
        'sponsoredDisplay': 'SD',
    }
    return type_mapping.get(api_type, api_type)


async def fetch_and_save_campaigns(sid: str, app_id: str = "", app_secret: str = ""):
    """
    分页获取 Campaign 列表并写入数据库
    """
    length = 200
    offset = 0
    total_processed = 0
    total_created = 0
    total_updated = 0

    # 获取店铺对象（用于外键关联）
    try:
        lingxing_shop = await sync_to_async(LingXingAmazonShop.objects.get)(sid=sid)
    except LingXingAmazonShop.DoesNotExist:
        logger.error(f"店铺 sid={sid} 不存在，请先同步店铺列表")
        return

    logger.info(f"开始获取店铺 {sid} 的 Campaign 数据...")

    while True:
        req_body = {
            "sid": sid,
            "length": length,
            "offset": offset
        }

        try:
            resp = await get_api_resp(
                req_body,
                api_path="/pb/openapi/newad/spCampaigns",
                app_id=app_id,
                app_secret=app_secret
            )

            if resp.code != 0:
                logger.error(f"API 请求失败: {resp.message}")
                break

            total = resp.total
            data_list = resp.data

            if not data_list:
                logger.info("没有更多数据")
                break

            logger.info(f"获取到 {len(data_list)} 条记录 (offset={offset}, total={total})")

            # 处理并写入数据库
            for data in data_list:
                try:
                    campaign_id = data.get("campaign_id")

                    # 时间戳转换
                    creation_date = timestamp_to_date(data.get("creation_date"))

                    # 日期字符串转换
                    start_date = parse_date_str(data.get("start_date"))
                    end_date = parse_date_str(data.get("end_date"))

                    # 类型映射
                    campaign_type = map_campaign_type(data.get("campaign_type"))

                    # 状态标准化（转小写确保匹配）
                    status = data.get("state", "").lower() if data.get("state") else None
                    serving_status = data.get("serving_status")
                    targeting_type = data.get("targeting_type", "").lower() if data.get("targeting_type") else None

                    # bidding 是 JSON 字符串，直接存或解析后存
                    bidding = data.get("bidding")
                    if isinstance(bidding, str):
                        import json
                        try:
                            bidding = json.loads(bidding)
                        except:
                            bidding = {}

                    # update_or_create 写入数据库
                    obj, created = await sync_to_async(
                        LingXingCampaign.objects.update_or_create,
                        thread_sensitive=True
                    )(
                        campaign_id=campaign_id,  # 主键查找
                        defaults={
                            'lingxing_shop': lingxing_shop,
                            'campaign_name': data.get("name"),
                            'campaign_type': campaign_type,
                            'targeting_type': targeting_type,
                            'status': status,
                            'serving_status': serving_status,
                            'daily_budget': data.get("daily_budget"),
                            'bidding': bidding or {},
                            'portfolio_id': data.get("portfolio_id"),
                            'start_date': start_date,
                            'end_date': end_date,
                            'creation_date': creation_date,
                            # first_seen_at 和 last_updated_at 由模型自动处理
                        }
                    )

                    if created:
                        total_created += 1
                    else:
                        total_updated += 1
                    total_processed += 1

                except Exception as e:
                    logger.error(f"处理 campaign_id={data.get('campaign_id')} 时出错: {e}")
                    continue

            # 检查是否还有下一页
            offset += length
            if offset >= total:
                logger.info("已获取全部数据")
                break

            # 避免请求过快，稍作延时
            await asyncio.sleep(0.5)

        except Exception as e:
            logger.error(f"获取数据失败: {e}")
            break

    logger.info(f"处理完成: 共 {total_processed} 条，新建 {total_created} 条，更新 {total_updated} 条")


async def main():
    """主入口"""
    # 配置你的 sid 和凭证
    SID = "521754"  # 吴晓云-04李尧尧-US
    APP_ID = ""  # 你的 app_id
    APP_SECRET = ""  # 你的 app_secret

    await fetch_and_save_campaigns(SID, APP_ID, APP_SECRET)


if __name__ == '__main__':
    asyncio.run(main())