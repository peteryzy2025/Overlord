#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os
import sys
import django
from datetime import datetime
from django.utils import timezone
from django.db import transaction
import logging

# ========== Django环境初始化 ==========
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
sys.path.append(PROJECT_ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Overlord.settings")
django.setup()

from api.track.track_api import query_tracking_v2
from track.models import Tracking, Courier, TrackingDetail

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def parse_datetime(dt_str):
    """解析时间字符串为datetime对象"""
    if not dt_str:
        return None
    try:
        # API返回的是字符串格式: "2025-12-11 14:28:57"
        return datetime.strptime(dt_str, '%Y-%m-%d %H:%M:%S')
    except Exception as e:
        logger.warning(f"时间解析失败 '{dt_str}': {e}")
        return None


def create_or_update_courier(local_info):
    """创建或更新物流商信息"""
    courier_code = local_info.get('courierCode')
    if not courier_code:
        return None

    courier, created = Courier.objects.update_or_create(
        code=courier_code,
        defaults={
            'name_cn': local_info.get('courierNameCN', ''),
            'name_en': local_info.get('courierNameEN', ''),
            'homepage': local_info.get('courierHomePage', ''),
        }
    )
    if created:
        logger.info(f"创建新物流商: {courier_code}")
    return courier


def update_tracking_detail(tracking, details_data):
    """更新轨迹明细（先删除旧数据，再插入新数据）"""
    if not details_data:
        return

    try:
        # 删除该运单原有轨迹
        deleted_count, _ = TrackingDetail.objects.filter(tracking=tracking).delete()
        if deleted_count > 0:
            logger.info(f"删除 {tracking.track_no} 的旧轨迹 {deleted_count} 条")

        # 批量创建新轨迹（按时间倒序排列）
        detail_objects = []
        for detail in details_data:
            detail_obj = TrackingDetail(
                tracking=tracking,
                event_time=parse_datetime(detail.get('eventTime')),
                address=detail.get('address', ''),
                event_detail=detail.get('eventDetail', ''),
                transit_sub_status=detail.get('transitSubStatus', ''),
            )
            detail_objects.append(detail_obj)

        # 批量创建（按event_time倒序插入）
        TrackingDetail.objects.bulk_create(detail_objects)
        logger.info(f"创建 {tracking.track_no} 的新轨迹 {len(detail_objects)} 条")

    except Exception as e:
        logger.error(f"更新轨迹明细失败 {tracking.track_no}: {e}")


def update_tracking_from_api():
    """
    主函数：查询API并更新数据库
    """
    # 1. 获取所有物流单号
    trackings = Tracking.objects.all()
    track_nos = list(trackings.values_list('track_no', flat=True))

    if not track_nos:
        logger.warning("数据库中没有物流单号需要更新")
        return

    logger.info(f"准备更新 {len(track_nos)} 个物流单号的信息")

    # 2. 分批查询API
    batch_size = 50
    success_count = 0
    fail_count = 0

    for i in range(0, len(track_nos), batch_size):
        batch = track_nos[i:i + batch_size]
        logger.info(f"处理第 {i // batch_size + 1} 批: {len(batch)} 个单号")

        try:
            result = query_tracking_v2(batch)

            if result.get('code') != '00000':
                logger.error(f"API返回错误: {result.get('msg')}")
                fail_count += len(batch)
                continue

            # 获取成功的数据
            content_list = result.get('data', {}).get('accepted', {}).get('content', [])

            # 3. 使用事务确保数据一致性
            with transaction.atomic():
                for item in content_list:
                    try:
                        track_no = item.get('trackNo')
                        if not track_no:
                            continue

                        # 3.1 处理物流商信息
                        local_info = item.get('localLogisticsInfo', {})
                        courier = create_or_update_courier(local_info) if local_info else None

                        # 3.2 准备主表数据
                        update_data = {
                            'transit_status': item.get('transitStatus', ''),
                            'transit_sub_status': item.get('transitSubStatus', ''),
                            'tracking_status': item.get('trackingStatus', ''),
                            'delivered_time': parse_datetime(item.get('deliveredTime')),
                            'last_update_time': parse_datetime(item.get('lastTrackingTime')),
                            'order_time': parse_datetime(item.get('orderTime')),
                            'next_update_time': parse_datetime(item.get('nextUpdateTime')),
                            'stay_days': item.get('stayDays'),
                            'transit_days': item.get('transitDays'),
                            'delivered_days': item.get('deliveredDays'),
                            'ship_from': item.get('shipFrom', ''),
                            'ship_to': item.get('shipTo', ''),
                            'shipment_type': item.get('shipmentType', ''),
                            'raw_data': item,  # 保存完整原始数据
                        }

                        if courier:
                            update_data['courier'] = courier

                        # 3.3 更新或创建运单主记录
                        tracking_obj, created = Tracking.objects.update_or_create(
                            track_no=track_no,
                            defaults=update_data
                        )

                        if created:
                            logger.info(f"✅ 创建新运单: {track_no}")
                        else:
                            logger.info(f"🔄 更新运单: {track_no} ({item.get('transitStatus')})")

                        # 3.4 更新轨迹明细
                        details = local_info.get('trackingDetails', [])
                        if details:
                            update_tracking_detail(tracking_obj, details)

                        success_count += 1

                    except Exception as e:
                        logger.error(f"处理单号 {track_no} 失败: {e}")
                        fail_count += 1
                        continue

            # 4. 处理被拒绝的单号
            rejected = result.get('data', {}).get('rejected', [])
            for rejected_item in rejected:
                logger.warning(f"❌ 单号被拒绝: {rejected_item}")
                fail_count += 1

        except Exception as e:
            logger.error(f"批量查询失败: {e}")
            fail_count += len(batch)
            continue

    # 5. 打印总结
    logger.info(f"\n{'=' * 50}")
    logger.info(f"更新完成！成功: {success_count}, 失败: {fail_count}")
    logger.info(f"{'=' * 50}")


if __name__ == '__main__':
    update_tracking_from_api()