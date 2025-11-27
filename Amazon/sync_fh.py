#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
自动发货脚本 - 定时任务版
每30分钟运行一次，自动筛选并发货满足条件的订单

使用方式：
    1. 直接运行：python auto_ship_orders.py
    2. 或使用系统定时任务（推荐）：
       crontab -e
       # 添加以下行，每30分钟执行一次
       */30 * * * * /path/to/python /path/to/auto_ship_orders.py >> /path/to/logs/auto_ship.log 2>&1

配置项：
    ENABLE_AUTO_SHIP = True   # 总开关，是否启用自动发货
    START_DATE = "2025-11-19" # 处理此日期及之后的订单
    MAX_BATCH_SIZE = 100      # 单次处理最大订单数，防止任务超时
"""

import os
import sys
import django
from datetime import datetime
import logging

# ========== Django环境初始化 ==========
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
sys.path.append(PROJECT_ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Overlord.settings")
django.setup()

from Amazon.models import AmazonOrders
from Api.lingxing_p.lingxing_fh import lingxing_ship_order
from Api.Y.y_tiem import Timer  # 引入计时器工具（如无需可删除）

# ========== 日志配置 ==========
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),  # 输出到控制台
        # logging.FileHandler('/path/to/logs/auto_ship.log'),  # 如需文件日志，取消注释并修改路径
    ]
)
logger = logging.getLogger(__name__)

# ========== 核心配置 ==========
ENABLE_AUTO_SHIP = True  # 总开关，是否启用自动发货
START_DATE = "2025-11-19"  # 处理此日期及之后的订单
MAX_BATCH_SIZE = 100  # 单次处理最大订单数，防止任务超时

# ========== 筛选条件常量 ==========
DIVI_STATUS_SHIPPED = 5  # DIVI订单状态: 5=已发货
AMAZON_STATUS_UNSHIPPED = 'Unshipped'  # 亚马逊订单状态: Unshipped
FULFILLMENT_CHANNEL_MFN = 'MFN'  # 配送渠道: MFN (自发货)


def query_pending_ship_orders(start_date_str=None, max_batch_size=None):
    """
    查询待自动发货的订单

    筛选条件：
        - divi_order_status == 5 (DIVI已发货)
        - fulfillment_channel == 'MFN' (自发货)
        - order_status == 'Unshipped' (亚马逊未发货)
        - purchase_date_local >= start_date_str (指定日期及之后)

    返回：
        QuerySet: 待发货订单查询集
    """
    # 计算起始时间
    if start_date_str:
        start_datetime = datetime.strptime(f"{start_date_str} 00:00:00", "%Y-%m-%d %H:%M:%S")
    else:
        start_datetime = datetime.min

    # 构建基础查询
    orders = AmazonOrders.objects.filter(
        divi_order_status=DIVI_STATUS_SHIPPED,
        fulfillment_channel=FULFILLMENT_CHANNEL_MFN,
        order_status=AMAZON_STATUS_UNSHIPPED,
        purchase_date_local__gte=start_datetime
    ).select_related(
        'lingxing_shop'  # 预获取关联的领星店铺，用于获取sid
    ).order_by(
        'purchase_date_local'  # 按购买时间排序，先下单的先发货
    )

    # 限制批次大小
    if max_batch_size:
        orders = orders[:max_batch_size]

    return orders


def process_auto_ship():
    """
    主流程：自动发货处理

    返回：
        tuple: (成功数量, 失败数量)
    """
    if not ENABLE_AUTO_SHIP:
        logger.warning("自动发货功能已禁用（ENABLE_AUTO_SHIP = False）")
        return 0, 0

    logger.info("=" * 80)
    logger.info("自动发货任务启动")
    logger.info(
        f"筛选条件: divi_order_status={DIVI_STATUS_SHIPPED}, fulfillment_channel={FULFILLMENT_CHANNEL_MFN}, order_status={AMAZON_STATUS_UNSHIPPED}")
    logger.info(f"日期范围: {START_DATE} 及之后")
    logger.info(f"批次限制: 最多 {MAX_BATCH_SIZE} 单")
    logger.info("=" * 80)

    # 查询待发货订单
    try:
        pending_orders = query_pending_ship_orders(
            start_date_str=START_DATE,
            max_batch_size=MAX_BATCH_SIZE
        )
        total = pending_orders.count()
    except Exception as e:
        logger.error(f"查询订单时发生错误: {str(e)}")
        return 0, 0

    if total == 0:
        logger.info("未找到符合条件的待发货订单")
        return 0, 0

    logger.info(f"找到 {total} 条待发货订单，开始处理...\n")

    success_count = 0
    error_count = 0

    # 遍历处理每个订单
    for idx, order in enumerate(pending_orders, 1):
        amazon_order_id = order.amazon_order_id
        sid = order.lingxing_shop.sid if order.lingxing_shop else None

        # 前置检查：确保sid存在
        if not sid:
            logger.error(f"[{idx:>3}/{total}] 订单 {amazon_order_id} | 错误: 没有关联的领星店铺SID")
            error_count += 1
            continue

        logger.info(f"[{idx:>3}/{total}] 订单 {amazon_order_id} | SID: {sid} | 开始处理...")

        try:
            # 调用发货函数
            lingxing_ship_order(sid, amazon_order_id, mode="full_shipment")

            logger.info(f"  ✓ 发货流程执行成功")
            success_count += 1

        except Exception as e:
            logger.error(f"  × 发货失败: {str(e)}")
            error_count += 1

    return success_count, error_count


def main():
    """主函数入口"""
    timer = Timer()
    timer.start()

    try:
        success, error = process_auto_ship()

        # 打印最终统计
        logger.info("=" * 80)
        logger.info("自动发货任务完成！")
        logger.info(f"成功: {success} | 失败: {error}")
        if error > 0:
            logger.warning(f"有 {error} 个订单发货失败，请检查日志")
        logger.info("=" * 80)

    except Exception as e:
        logger.exception(f"任务执行异常: {str(e)}")
        sys.exit(1)  # 退出码1表示异常

    timer.stop()
    logger.info(f"运行时长: {timer}")


if __name__ == '__main__':
    main()