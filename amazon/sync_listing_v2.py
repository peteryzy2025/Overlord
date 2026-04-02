#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Amazon Listing V2 同步脚本
从领星ERP同步Listing数据到新的V2数据结构
"""

import asyncio
import json
import logging
import os
import sys
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple

import django

# 设置Django环境
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Overlord.settings')
django.setup()

from asgiref.sync import sync_to_async
from tqdm.asyncio import tqdm

from amazon.models import LingXingAmazonShop, AmazonListingV2, AmazonListingSalesHistory
from api.lingxing.Y_OpenApi import get_api_resp

# 日志配置 - 简洁格式
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger(__name__)


async def fetch_shop_listing(
    sid: int,
    offset: int = 0,
    limit: int = 1000
) -> Tuple[List[Dict], int]:
    """
    获取店铺Listing数据
    Returns: (数据列表, 总数)
    """
    try:
        resp = await get_api_resp(
            req_body={
                "sid": sid,
                "offset": offset,
                "length": limit,
            },
            api_path="/erp/sc/data/mws/listing",
            method="POST",
        )

        if resp.code != 0:
            logger.warning(f"[API错误] sid={sid}, offset={offset}, code={resp.code}, msg={resp.message}")
            return [], 0

        data_list = resp.data or []
        total = resp.total or 0



        return data_list, total

    except Exception as e:
        logger.error(f"[API异常] sid={sid}, offset={offset}, error={e}")
        return [], 0


def extract_listing_fields(item: Dict) -> Dict:
    """从API数据中提取Listing字段（只包含AmazonListingV2模型存在的字段）"""
    
    # 状态转换：API返回的字符串转整数
    status_map = {
        'active': 1,
        'inactive': 0,
        'deleted': 0,
    }
    status_raw = str(item.get('status', '')).lower()
    status = status_map.get(status_raw, 1)  # 默认在售
    
    # 删除标记转换
    is_delete = 1 if item.get('is_deleted', False) else 0
    
    return {
        # 核心标识
        'parent_asin': item.get('parent_asin'),  # API就是parent_asin
        'fnsku': item.get('fnsku'),
        
        # 基础信息
        'title': item.get('item_name'),  # API是item_name
        'seller_sku': item.get('seller_sku'),
        'small_image_url': item.get('image_url') or item.get('small_image_url'),
        
        # 排名信息（small_rank是JSON字段）
        'small_rank': item.get('small_rank', []),
        
        # 评价信息
        'review_num': item.get('review_count', 0),
        'last_star': str(item.get('review_score', '')) if item.get('review_score') else None,
        
        # 状态字段
        'status': status,
        'is_delete': is_delete,
        'is_active': status == 1,
        
        # JSON扩展字段
        'dimension_info': item.get('dimension_info', {}),
        'global_tags': item.get('global_tags', []),
    }


def extract_sales_fields(item: Dict) -> Dict:
    """提取销售相关字段用于历史记录"""
    return {
        'volume_1d': item.get('yesterday_volume'),
        'amount_1d': item.get('yesterday_amount'),
        'volume_7d': item.get('total_volume'),
        'amount_7d': item.get('seven_amount'),
        'volume_14d': item.get('fourteen_volume'),
        'amount_14d': item.get('fourteen_amount'),
        'volume_30d': item.get('thirty_volume'),
        'amount_30d': item.get('thirty_amount'),
        'avg_volume_7d': item.get('average_seven_volume'),
        'avg_volume_14d': item.get('average_fourteen_volume'),
        'avg_volume_30d': item.get('average_thirty_volume'),
    }


async def process_listing_item(
    item: Dict,
    shop: LingXingAmazonShop,
    country: str,
    snapshot_date: date,
    stats: Dict
) -> bool:
    """处理单个Listing数据"""

    # 跳过已删除的数据 (is_delete=1)
    if item.get('is_delete') == 1:
        stats['跳过-已删除'] += 1
        return False

    # 跳过状态无效的数据 (status=0)
    if item.get('status') == 0:
        stats['跳过-状态无效'] += 1
        return False

    asin = item.get('asin')
    sid = item.get('sid')
    fulfillment_channel_type = item.get('fulfillment_channel_type', '')

    if not asin or not sid:
        stats['跳过-缺少ASIN'] += 1
        return False

    try:
        # 准备Listing数据
        listing_data = extract_listing_fields(item)
        listing_data['marketplace'] = country
        listing_data['sid'] = sid
        listing_data['lingxing_shop_id'] = shop.sid  # 主键是sid

        # 主表upsert
        listing, created = await sync_to_async(
            AmazonListingV2.objects.update_or_create,
            thread_sensitive=True
        )(
            asin=asin,
            sid=sid,
            fulfillment_channel_type=fulfillment_channel_type,
            defaults=listing_data
        )

        if created:
            stats['主表-新增'] += 1
        else:
            stats['主表-更新'] += 1

        # 创建历史记录
        sales_data = extract_sales_fields(item)
        await sync_to_async(
            AmazonListingSalesHistory.objects.update_or_create,
            thread_sensitive=True
        )(
            listing=listing,
            snapshot_date=snapshot_date,
            defaults=sales_data
        )

        if created:
            stats['历史表-新增'] += 1
        else:
            stats['历史表-更新'] += 1

        stats['有效数据'] += 1
        return True

    except Exception as e:
        logger.warning(f"处理失败 asin={asin}, sid={sid}: {e}")
        stats['数据库错误'] += 1
        return False


async def sync_single_shop(
    shop: LingXingAmazonShop,
    snapshot_date: date,
    pbar
) -> Dict:
    """同步单个店铺的Listing数据，返回统计信息"""

    sid = shop.sid
    shop_name = shop.name or f"Shop-{sid}"
    
    # 更新进度条显示当前店铺
    pbar.set_description(f"[{shop_name[:15]:<15} sid={sid}]")

    # 在同步上下文中获取国家信息
    country = shop.country or shop.region or ''

    stats = {
        '店铺': f"{shop_name}(sid={sid})",
        '拉取数据': 0,
        '处理页数': 0,
        '有效数据': 0,
        '跳过-已删除': 0,
        '跳过-状态无效': 0,
        '跳过-缺少ASIN': 0,
        '跳过-缺少SID': 0,
        '主表-新增': 0,
        '主表-更新': 0,
        '主表-失败': 0,
        '历史表-新增': 0,
        '历史表-更新': 0,
        '历史表-失败': 0,
        'API错误': 0,
        '数据库错误': 0,
    }

    offset = 0
    limit = 1000
    has_more = True

    while has_more:
        try:
            data_list, total = await fetch_shop_listing(sid, offset, limit)

            if not data_list:
                break

            stats['拉取数据'] += len(data_list)
            stats['处理页数'] += 1

            for item in data_list:
                await process_listing_item(item, shop, country, snapshot_date, stats)

            # 更新进度条后缀
            pbar.set_postfix({
                '拉取': stats['拉取数据'],
                '有效': stats['有效数据'],
                '新增': stats['主表-新增'],
                '更新': stats['主表-更新']
            })

            has_more = len(data_list) == limit
            offset += limit

            if has_more:
                await asyncio.sleep(0.5)

        except Exception as e:
            logger.warning(f"店铺 {shop_name}(sid={sid}) 同步失败: {e}")
            stats['API错误'] += 1
            break

    # 更新进度条
    pbar.update(1)

    return stats


async def sync_all_shops(snapshot_date: Optional[date] = None, max_shops: Optional[int] = None):
    """同步所有店铺的Listing数据"""

    if snapshot_date is None:
        snapshot_date = date.today()

    logger.info(f"开始同步Listing数据 | 快照日期: {snapshot_date}")

    # 获取所有店铺
    shops = await sync_to_async(list)(LingXingAmazonShop.objects.all())
    if max_shops:
        shops = shops[:max_shops]
    total_shops = len(shops)
    logger.info(f"加载店铺: {total_shops}个")

    all_stats = []

    # 创建进度条
    with tqdm(total=total_shops, desc="同步店铺", unit="个") as pbar:
        for i, shop in enumerate(shops):
            stats = await sync_single_shop(shop, snapshot_date, pbar)
            all_stats.append(stats)
            # 店铺间延迟，避免限流
            if i < len(shops) - 1:
                await asyncio.sleep(1)

    # 输出汇总统计
    logger.info("=" * 50)
    logger.info("同步完成！汇总统计：")

    total_fetched = sum(s['拉取数据'] for s in all_stats)
    total_main_created = sum(s['主表-新增'] for s in all_stats)
    total_main_updated = sum(s['主表-更新'] for s in all_stats)
    total_history_created = sum(s['历史表-新增'] for s in all_stats)
    total_history_updated = sum(s['历史表-更新'] for s in all_stats)
    total_api_errors = sum(s['API错误'] for s in all_stats)

    logger.info(f"店铺总数: {total_shops}")
    logger.info(f"拉取数据: {total_fetched}")
    logger.info(f"主表-新增: {total_main_created} | 更新: {total_main_updated}")
    logger.info(f"历史表-新增: {total_history_created} | 更新: {total_history_updated}")

    if total_api_errors > 0:
        logger.warning(f"API错误: {total_api_errors}")

    logger.info("=" * 50)


if __name__ == '__main__':
    # 默认同步所有店铺，可通过参数限制
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--max-shops', type=int, default=None, help='最多同步店铺数')
    args = parser.parse_args()
    asyncio.run(sync_all_shops(max_shops=args.max_shops))
