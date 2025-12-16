#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
物流轨迹同步脚本（优化版）
功能：批量查询未签收运单的最新轨迹，调用统一接口更新数据库
特性：排除已签收/过期运单、每批100条、完整日志记录
"""

import os
import sys
import django
import logging
from datetime import datetime

# ========== Django环境初始化 ==========
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
sys.path.append(PROJECT_ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Overlord.settings")
django.setup()

# 导入现有接口和模型
from Api.track.track_api import get_tracking_updates
from Track.models import Tracking

# ========== 日志配置 ==========
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),  # 输出到控制台
        logging.FileHandler(
            os.path.join(CURRENT_DIR, f"sync_{datetime.now().strftime('%Y%m%d')}.log"),
            encoding='utf-8'
        )  # 输出到日志文件
    ]
)
logger = logging.getLogger(__name__)


def get_pending_trackings():
    """
    获取所有需要同步的运单号（排除已签收和已过期）
    :return: 运单号列表
    """
    # 定义终态状态（这些状态不再更新）
    FINAL_STATUSES = ['DELIVERED', 'EXPIRED']

    trackings = Tracking.objects.exclude(
        transit_status__in=FINAL_STATUSES
    ).values_list('track_no', flat=True).distinct()

    track_nos = list(trackings)
    logger.info(f"查询数据库：共 {len(track_nos)} 个运单需要同步（已排除 {', '.join(FINAL_STATUSES)} 状态）")

    return track_nos


def sync_tracking_batch(track_nos_batch, batch_no):
    """
    同步一批运单（调用现有接口）
    :param track_nos_batch: 运单号列表（最多100条）
    :param batch_no: 批次编号（用于日志）
    :return: (成功数, 失败数)
    """
    batch_size = len(track_nos_batch)
    logger.info(f"【第 {batch_no} 批】开始同步 {batch_size} 个运单")

    try:
        # 调用现有的统一接口（内部已处理API调用和数据库更新）
        result = get_tracking_updates(track_nos_batch)

        if result.get('success'):
            success_count = result['data']['success_count']
            fail_count = result['data']['fail_count']

            # 记录错误详情（如果有）
            errors = result['data'].get('errors', [])
            if errors:
                for error in errors[:5]:  # 只记录前5条，避免日志过多
                    logger.warning(f"【第 {batch_no} 批】错误示例: {error}")
                if len(errors) > 5:
                    logger.warning(f"【第 {batch_no} 批】还有 {len(errors) - 5} 条错误未显示")

            logger.info(f"【第 {batch_no} 批】同步完成: 成功 {success_count} 条, 失败 {fail_count} 条")
            return success_count, fail_count
        else:
            error_msg = result.get('message', '接口返回失败')
            logger.error(f"【第 {batch_no} 批】接口调用失败: {error_msg}")
            return 0, batch_size

    except Exception as e:
        logger.exception(f"【第 {batch_no} 批】同步异常: {str(e)}")
        return 0, batch_size


def update_tracking_from_api():
    """
    主函数：分批同步所有待更新运单
    """
    # 1. 获取所有未签收的运单号
    track_nos = get_pending_trackings()

    if not track_nos:
        logger.warning("没有需要同步的运单，任务结束")
        return

    total_to_sync = len(track_nos)
    logger.info(f"{'=' * 60}")
    logger.info(f"开始执行轨迹同步任务，总计 {total_to_sync} 个运单")
    logger.info(f"{'=' * 60}")

    # 2. 分批处理（每批100条）
    BATCH_SIZE = 100
    total_success = 0
    total_fail = 0
    batch_count = 0

    for i in range(0, total_to_sync, BATCH_SIZE):
        batch_count += 1
        batch = track_nos[i:i + BATCH_SIZE]

        # 同步当前批次
        success, fail = sync_tracking_batch(batch, batch_count)

        total_success += success
        total_fail += fail

        # 每处理5批打印一次进度
        if batch_count % 5 == 0:
            progress = min(i + BATCH_SIZE, total_to_sync) / total_to_sync * 100
            logger.info(f"【进度】已处理 {progress:.1f}% ({i + BATCH_SIZE}/{total_to_sync})")

    # 3. 打印最终总结
    logger.info(f"{'=' * 60}")
    logger.info(f"同步任务完成！总计: {total_to_sync} 个运单")
    logger.info(f"成功更新: {total_success} 条")
    logger.info(f"失败: {total_fail} 条")
    logger.info(f"成功率: {(total_success / total_to_sync * 100):.1f}%")
    logger.info(f"{'=' * 60}")


if __name__ == '__main__':
    try:
        update_tracking_from_api()
    except KeyboardInterrupt:
        logger.warning("任务被用户中断")
        sys.exit(1)
    except Exception as e:
        logger.exception(f"任务执行失败: {str(e)}")
        sys.exit(1)