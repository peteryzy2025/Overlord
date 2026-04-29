#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
自动发货脚本 - 终极版
每30分钟运行一次

优先级1：即将超时订单（红色预警且已有物流单号）
- LS开头单号 → 假物流发货 → 标记 masked_single=True

优先级2：正常发货订单（divi_order_status == 5）

日志：记录到UserOperationLog，操作人ID=56，类型=3005（自动发货）
"""

import os
import sys
import django
import argparse
from datetime import datetime, timedelta
from django.utils import timezone
import logging

# ========== Django环境初始化 ==========
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
sys.path.insert(0, PROJECT_ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Overlord.settings")
django.setup()

from amazon.models import AmazonOrders
from api.lingxing_p.lingxing_fh import lingxing_ship_order
from api.Y.y_tiem import Timer
from general.models import User, UserOperationLog  # 导入日志模型


def parse_args():
    parser = argparse.ArgumentParser(description="自动发货脚本")
    parser.add_argument("--project-id", type=int, help="指定项目 ID 同步")
    parser.add_argument("--project-name", type=str, help="指定项目名称同步（支持模糊匹配）")
    return parser.parse_args()

# ========== 日志配置 ==========
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger(__name__)

# ========== 核心配置 ==========
ENABLE_AUTO_SHIP = True
START_DATE = "2025-11-19"
MAX_BATCH_SIZE = 500

# ========== 筛选条件常量 ==========
DIVI_STATUS_SHIPPED = 5
AMAZON_STATUS_UNSHIPPED = 'Unshipped'
FULFILLMENT_CHANNEL_MFN = 'MFN'
RED_DEADLINE_HOURS = 24
BEIJING_OFFSET_HOURS = 16

# ========== 系统用户配置 ==========
SYSTEM_USER_ID = 56  # 指定系统用户ID


def is_red_deadline(order):
    """
    判断订单是否为红色预警（即将超时）
    返回：bool
    """
    NON_DEADLINE_STATUSES = ['PendingAvailability', 'Pending', 'Canceled', 'Shipped']

    if not order.earliest_ship_date_utc:
        return False

    if order.order_status in NON_DEADLINE_STATUSES:
        return False

    # 计算北京时间下的截止时间
    beijing_deadline = order.earliest_ship_date_utc + timedelta(hours=BEIJING_OFFSET_HOURS)
    now = timezone.now()
    time_diff = beijing_deadline - now
    hours_remaining = time_diff.total_seconds() / 3600

    return hours_remaining <= RED_DEADLINE_HOURS


def query_red_deadline_orders(start_date_str=None, max_batch_size=None, project_id=None, project_name=None):
    """
    查询即将超时待发货的订单（红色预警）
    """
    if start_date_str:
        start_datetime = timezone.make_aware(datetime.strptime(f"{start_date_str} 00:00:00", "%Y-%m-%d %H:%M:%S"))
    else:
        start_datetime = timezone.make_aware(datetime.min)

    filters = {
        'fulfillment_channel': FULFILLMENT_CHANNEL_MFN,
        'order_status': AMAZON_STATUS_UNSHIPPED,
        'purchase_date_local__gte': start_datetime,
        'amazon_shop__isnull': False,
        'divi_tracking_number__isnull': False,
    }
    
    if project_id:
        filters['amazon_shop__project_id'] = project_id
    elif project_name:
        filters['amazon_shop__project__name__icontains'] = project_name

    base_query = AmazonOrders.objects.filter(
        **filters
    ).exclude(
        amazon_shop__shop_status__in=['status-inactive', 'status-cancelled', 'status-warning']
    ).exclude(
        divi_tracking_number=''
    ).select_related(
        'lingxing_shop', 'amazon_shop'
    ).order_by('purchase_date_local')

    red_orders = []
    for order in base_query:
        if is_red_deadline(order):
            red_orders.append(order)
            if max_batch_size and len(red_orders) >= max_batch_size:
                break

    return red_orders


def query_normal_ship_orders(start_date_str=None, max_batch_size=None, project_id=None, project_name=None):
    """
    查询正常可发货订单（divi_order_status == 5）
    """
    if start_date_str:
        start_datetime = timezone.make_aware(datetime.strptime(f"{start_date_str} 00:00:00", "%Y-%m-%d %H:%M:%S"))
    else:
        start_datetime = timezone.make_aware(datetime.min)

    filters = {
        'divi_order_status': DIVI_STATUS_SHIPPED,
        'fulfillment_channel': FULFILLMENT_CHANNEL_MFN,
        'order_status': AMAZON_STATUS_UNSHIPPED,
        'purchase_date_local__gte': start_datetime,
        'amazon_shop__isnull': False,
    }
    
    if project_id:
        filters['amazon_shop__project_id'] = project_id
    elif project_name:
        filters['amazon_shop__project__name__icontains'] = project_name

    orders = AmazonOrders.objects.filter(
        **filters
    ).exclude(
        amazon_shop__shop_status__in=['status-inactive', 'status-cancelled', 'status-warning']
    ).select_related(
        'lingxing_shop', 'amazon_shop'
    ).order_by('purchase_date_local')

    if max_batch_size:
        orders = orders[:max_batch_size]

    return orders


def process_auto_ship(project_id=None, project_name=None):
    """
    主流程：按优先级自动发货

    返回：
        tuple: (批次1成功数, 批次1失败数, 批次2成功数, 批次2失败数)
    """
    if not ENABLE_AUTO_SHIP:
        logger.warning("自动发货功能已禁用")
        return 0, 0, 0, 0

    # 获取系统用户
    try:
        system_user = User.objects.get(id=SYSTEM_USER_ID)
    except User.DoesNotExist:
        logger.error(f"系统用户(ID={SYSTEM_USER_ID})不存在，无法记录日志！")
        return 0, 0, 0, 0

    logger.info("=" * 80)
    logger.info("自动发货任务启动")
    logger.info(f"日志操作人: {system_user.username}(ID:{SYSTEM_USER_ID})")
    logger.info(f"优先级1: 红色预警 + 有物流单号")
    logger.info(f"优先级2: divi_order_status={DIVI_STATUS_SHIPPED}")
    logger.info(f"日期范围: {START_DATE} 及之后")
    logger.info(f"批次限制: 每优先级最多 {MAX_BATCH_SIZE} 单")
    if project_id:
        logger.info(f"按项目 ID 过滤：{project_id}")
    elif project_name:
        logger.info(f"按项目名称过滤：'{project_name}'")
    logger.info("=" * 80)

    # ========== 优先级1：即将超时订单 ==========
    logger.info("\n【优先级1】查询即将超时订单...")
    red_deadline_orders = query_red_deadline_orders(
        start_date_str=START_DATE,
        max_batch_size=MAX_BATCH_SIZE,
        project_id=project_id,
        project_name=project_name
    )

    red_total = len(red_deadline_orders)
    red_success = 0
    red_error = 0

    if red_total > 0:
        logger.info(f"找到 {red_total} 条即将超时订单，开始处理...\n")

        for idx, order in enumerate(red_deadline_orders, 1):
            amazon_order_id = order.amazon_order_id
            sid = order.lingxing_shop.sid if order.lingxing_shop else None
            tracking_number = order.divi_tracking_number or ''
            shop_name = order.lingxing_shop.name if order.lingxing_shop else '未知店铺'
            divi_status = order.divi_order_status if order.divi_order_status is not None else '-'

            if not sid:
                error_msg = "没有关联的领星店铺SID"
                logger.error(f"[{idx:>3}/{red_total}] 订单 {amazon_order_id} | 错误: {error_msg}")
                # 记录失败日志
                UserOperationLog.objects.create(
                    user=system_user,
                    operation_type=UserOperationLog.OperationType.ORDER_AUTO_SHIP,
                    operation_record=f"店铺[{shop_name}]自动发货 | 订单[{amazon_order_id}]失败 | 原因[{error_msg}] | DIVI状态[{divi_status}]"
                )
                red_error += 1
                continue

            logger.info(f"[{idx:>3}/{red_total}] 订单 {amazon_order_id} | SID: {sid}")
            logger.info(
                f"  跟踪号: {tracking_number} | 类型: {'假物流' if tracking_number.startswith('LS') else '真物流'}")

            try:
                # 执行发货
                lingxing_ship_order(sid, amazon_order_id, mode="full_shipment")

                # 如果是LS开头的假物流单号，标记
                if tracking_number.startswith('LS') or tracking_number.startswith('999999LS'):
                    order.masked_single = True
                    order.save(update_fields=['masked_single'])
                    logger.info("  ✓ 发货成功（已标记为假物流）")
                    # 记录成功日志（假物流）
                    UserOperationLog.objects.create(
                        user=system_user,
                        operation_type=UserOperationLog.OperationType.ORDER_AUTO_SHIP,
                        operation_record=f"店铺[{shop_name}]自动发货 | 订单[{amazon_order_id}]成功 | DIVI状态[{divi_status}] | 跟踪号[{tracking_number}] | 假物流[是]"
                    )
                else:
                    logger.info("  ✓ 发货成功")
                    # 记录成功日志（真物流）
                    UserOperationLog.objects.create(
                        user=system_user,
                        operation_type=UserOperationLog.OperationType.ORDER_AUTO_SHIP,
                        operation_record=f"店铺[{shop_name}]自动发货 | 订单[{amazon_order_id}]成功 | DIVI状态[{divi_status}] | 跟踪号[{tracking_number}] | 假物流[否]"
                    )

                red_success += 1

            except Exception as e:
                error_msg = str(e)
                logger.error(f"  × 发货失败: {error_msg}")
                # 记录失败日志
                UserOperationLog.objects.create(
                    user=system_user,
                    operation_type=UserOperationLog.OperationType.ORDER_AUTO_SHIP,
                    operation_record=f"店铺[{shop_name}]自动发货 | 订单[{amazon_order_id}]失败 | 原因[{error_msg}] | DIVI状态[{divi_status}] | 跟踪号[{tracking_number}]"
                )
                red_error += 1
    else:
        logger.info("未找到即将超时订单\n")

    # ========== 优先级2：正常发货订单 ==========
    logger.info("\n【优先级2】查询正常发货订单...")
    normal_orders = query_normal_ship_orders(
        start_date_str=START_DATE,
        max_batch_size=MAX_BATCH_SIZE,
        project_id=project_id,
        project_name=project_name
    )

    normal_total = len(normal_orders)
    normal_success = 0
    normal_error = 0

    if normal_total > 0:
        logger.info(f"找到 {normal_total} 条正常发货订单，开始处理...\n")

        for idx, order in enumerate(normal_orders, 1):
            amazon_order_id = order.amazon_order_id
            sid = order.lingxing_shop.sid if order.lingxing_shop else None
            shop_name = order.lingxing_shop.name if order.lingxing_shop else '未知店铺'
            divi_status = order.divi_order_status if order.divi_order_status is not None else '-'

            if not sid:
                error_msg = "没有关联的领星店铺SID"
                logger.error(f"[{idx:>3}/{normal_total}] 订单 {amazon_order_id} | 错误: {error_msg}")
                # 记录失败日志
                UserOperationLog.objects.create(
                    user=system_user,
                    operation_type=UserOperationLog.OperationType.ORDER_AUTO_SHIP,
                    operation_record=f"店铺[{shop_name}]自动发货 | 订单[{amazon_order_id}]失败 | 原因[{error_msg}] | DIVI状态[{divi_status}]"
                )
                normal_error += 1
                continue

            logger.info(f"[{idx:>3}/{normal_total}] 订单 {amazon_order_id} | SID: {sid}")

            try:
                # 执行发货
                lingxing_ship_order(sid, amazon_order_id, mode="full_shipment")
                logger.info("  ✓ 发货成功")
                # 记录成功日志
                UserOperationLog.objects.create(
                    user=system_user,
                    operation_type=UserOperationLog.OperationType.ORDER_AUTO_SHIP,
                    operation_record=f"店铺[{shop_name}]自动发货 | 订单[{amazon_order_id}]成功 | DIVI状态[{divi_status}]"
                )
                normal_success += 1

            except Exception as e:
                error_msg = str(e)
                logger.error(f"  × 发货失败: {error_msg}")
                # 记录失败日志
                UserOperationLog.objects.create(
                    user=system_user,
                    operation_type=UserOperationLog.OperationType.ORDER_AUTO_SHIP,
                    operation_record=f"店铺[{shop_name}]自动发货 | 订单[{amazon_order_id}]失败 | 原因[{error_msg}] | DIVI状态[{divi_status}]"
                )
                normal_error += 1
    else:
        logger.info("未找到正常发货订单\n")

    return red_success, red_error, normal_success, normal_error


def amazon_shipment(project_id=None, project_name=None):
    """主函数入口"""
    timer = Timer()
    timer.start()

    try:
        red_success, red_error, normal_success, normal_error = process_auto_ship(
            project_id=project_id, project_name=project_name
        )

        # 打印最终统计
        logger.info("=" * 80)
        logger.info("自动发货任务完成！")
        logger.info(f"即将超时订单: 成功={red_success} | 失败={red_error}")
        logger.info(f"正常发货订单: 成功={normal_success} | 失败={normal_error}")

        total_success = red_success + normal_success
        total_error = red_error + normal_error

        if total_error > 0:
            logger.warning(f"总计失败: {total_error} 个订单")
        logger.info("=" * 80)

    except Exception as e:
        logger.exception(f"任务执行异常: {str(e)}")
        sys.exit(1)

    timer.stop()
    logger.info(f"运行时长: {timer}")


if __name__ == '__main__':
    args = parse_args()
    amazon_shipment(project_id=args.project_id, project_name=args.project_name)