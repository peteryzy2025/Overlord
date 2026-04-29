#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Amazon 同步主循环调度器（v2.0）
功能：定时调度各同步模块，模块级错误隔离，执行统计监控
"""

import os
import sys

# ========== 先添加项目根目录到 Python 路径 ==========
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
sys.path.insert(0, PROJECT_ROOT)  # 使用 insert(0, ...) 确保在最前面

import asyncio
import time
import logging
import argparse
from datetime import datetime, timedelta
from typing import List, Tuple, Callable, Any

# ========== Django 环境初始化 ==========
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Overlord.settings")
import django
django.setup()

# ========== 导入各模块 ==========
from amazon.sync_lingxing_shops import lx_shop_main, lx_shop_main2
from amazon.sync_lingxing_orders import lx_order_main
from amazon.sync_lingxing_zifa_order import lx_zf_main
from amazon.sync_check_divi_status_v4 import divi_process_orders
from amazon.sync_check_divi_k_v1 import amazon_order_divi_guer
from amazon.sync.sync_lingxing_order_info import lx_order_info_main
from amazon.sync.sync_amazon_shipment import amazon_shipment
from amazon.sync_lx_temu_orders import temu_orders
from api.Y.y_tiem import Timer
from general.models import Project

# ========== 日志配置 ==========
LOG_DIR = os.path.join(PROJECT_ROOT, 'logs')
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

LOG_FILE = os.path.join(LOG_DIR, 'sync_a_doing.log')

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger('sync_a_doing')

# ========== 配置 ==========
SLEEP_INTERVAL = 60  # 每轮循环间隔（秒）
NIGHT_START_HOUR = 1  # 夜间休眠开始时间
NIGHT_END_HOUR = 7    # 夜间休眠结束时间
SHIPMENT_INTERVAL = 10  # 发货模块执行间隔（轮数）
STATS_REPORT_INTERVAL = 10  # 统计报告输出间隔（轮数）
DIVI_DAYS_BACK = 30  # divi_process_orders 查询天数
SHOP_SYNC_INTERVAL = 60  # 店铺基础数据同步间隔（轮数），默认约每小时一次


# ========== 模块配置 ==========
class ModuleConfig:
    """模块配置类"""
    def __init__(
        self,
        name: str,
        func: Callable,
        args: Tuple = (),
        is_async: bool = False,
        enabled: bool = True,
        project_scoped: bool = True,
        run_interval: int = 1
    ):
        self.name = name
        self.func = func
        self.args = args
        self.is_async = is_async
        self.enabled = enabled
        self.project_scoped = project_scoped
        self.run_interval = max(int(run_interval or 1), 1)


# 模块列表（按执行顺序）
MODULES: List[ModuleConfig] = [
    ModuleConfig('divi_guer', amazon_order_divi_guer),
    # 店铺同步在模块内部按启用项目的领星凭证去重循环；同步前还没有本地 sid 可分组。
    ModuleConfig('lx_shop', lx_shop_main, project_scoped=False, run_interval=SHOP_SYNC_INTERVAL),
    ModuleConfig('lx_shop2', lx_shop_main2, project_scoped=False, run_interval=SHOP_SYNC_INTERVAL),
    ModuleConfig('lx_order', lx_order_main, project_scoped=False),
    ModuleConfig('lx_zf', lx_zf_main, is_async=True),
    ModuleConfig('lx_order_info', lx_order_info_main, is_async=True, project_scoped=False),
    # divi_process_orders 单独处理（需要动态日期）
    ModuleConfig('temu_orders', temu_orders, project_scoped=False),
]


# ========== 执行统计 ==========
class ModuleStats:
    """模块执行统计"""
    def __init__(self):
        self.runs = 0
        self.success = 0
        self.fail = 0
        self.total_time = 0.0
        self.last_error = None

    def record(self, success: bool, elapsed: float, error: str = None):
        self.runs += 1
        self.total_time += elapsed
        if success:
            self.success += 1
        else:
            self.fail += 1
            self.last_error = error

    @property
    def avg_time(self) -> float:
        return self.total_time / self.runs if self.runs > 0 else 0.0

    @property
    def success_rate(self) -> float:
        return (self.success / self.runs * 100) if self.runs > 0 else 0.0


class StatsManager:
    """统计管理器"""
    def __init__(self):
        self.stats = {}
        self.cycle_count = 0  # 当前周期内的执行次数

    def get(self, name: str) -> ModuleStats:
        if name not in self.stats:
            self.stats[name] = ModuleStats()
        return self.stats[name]

    def reset_cycle(self):
        """重置周期统计"""
        self.cycle_count = 0
        for stat in self.stats.values():
            stat.runs = 0
            stat.success = 0
            stat.fail = 0
            stat.total_time = 0.0
            stat.last_error = None

    def report(self) -> str:
        """生成统计报告"""
        lines = ["=" * 80, f"执行统计报告（最近 {self.cycle_count} 轮）", "=" * 80]
        
        for name, stat in sorted(self.stats.items()):
            if stat.runs > 0:
                status = "✓" if stat.fail == 0 else "✗"
                lines.append(
                    f"{status} {name:20s} | 成功率 {stat.success_rate:5.1f}% | "
                    f"执行 {stat.runs:3d} 次 | 平均耗时 {stat.avg_time:.2f}s"
                )
                if stat.fail > 0 and stat.last_error:
                    lines.append(f"   └─ 最后错误: {stat.last_error[:50]}...")
        
        lines.append("=" * 80)
        return "\n".join(lines)


stats_manager = StatsManager()


def parse_args():
    parser = argparse.ArgumentParser(description="Amazon 同步主循环调度器")
    parser.add_argument("--project-id", type=int, help="只运行指定项目 ID")
    parser.add_argument("--project-name", type=str, help="只运行指定项目名称（支持模糊匹配）")
    return parser.parse_args()


def get_active_projects(project_id=None, project_name=None):
    qs = Project.objects.filter(is_active=True).order_by('company_id', 'sort_order', 'id')
    if project_id:
        qs = qs.filter(id=project_id)
    elif project_name:
        qs = qs.filter(name__icontains=project_name)
    return list(qs.only('id', 'name', 'company_id'))


def project_label(project):
    return f"{project.name}(ID:{project.id})"


def project_filter_kwargs(project_id=None, project_name=None):
    kwargs = {}
    if project_id:
        kwargs['project_id'] = project_id
    elif project_name:
        kwargs['project_name'] = project_name
    return kwargs


# ========== 核心函数 ==========
def run_module(module: ModuleConfig, project=None, fallback_project_kwargs=None) -> bool:
    """
    执行单个模块，带错误隔离和统计
    返回: 是否成功
    """
    if not module.enabled:
        logger.info(f"[{module.name}] 已禁用，跳过")
        return True

    kwargs = {}
    display_name = module.name
    if project is not None:
        kwargs['project_id'] = project.id
        display_name = f"{module.name} | 项目 {project_label(project)}"
    elif fallback_project_kwargs:
        kwargs.update(fallback_project_kwargs)

    logger.info(f"[{display_name}] 开始执行")
    timer = Timer()
    timer.start()
    error_msg = None

    try:
        if module.is_async:
            asyncio.run(module.func(*module.args, **kwargs))
        else:
            module.func(*module.args, **kwargs)
        
        timer.stop()
        elapsed = timer.elapsed()
        logger.info(f"[{display_name}] 完成，耗时 {elapsed:.2f}s")
        stats_manager.get(module.name).record(True, elapsed)
        return True
        
    except Exception as e:
        timer.stop()
        elapsed = timer.elapsed()
        error_msg = str(e)
        logger.error(f"[{display_name}] 失败: {error_msg}")
        stats_manager.get(module.name).record(False, elapsed, error_msg)
        return False


def run_module_with_project_scope(module: ModuleConfig, projects, fallback_project_kwargs=None) -> bool:
    if not module.project_scoped:
        return run_module(module, fallback_project_kwargs=fallback_project_kwargs)

    if not projects:
        logger.warning(f"[{module.name}] 未找到启用项目，跳过")
        return True

    success = True
    for project in projects:
        success = run_module(module, project=project) and success
    return success


def should_run_module(module: ModuleConfig, round_no: int) -> bool:
    if module.run_interval <= 1:
        return True
    return round_no == 1 or (round_no - 1) % module.run_interval == 0


def run_divi_process_orders(projects) -> bool:
    """
    执行 divi_process_orders，动态计算日期
    """
    name = 'divi_process_orders'
    # 计算前30天的日期
    target_date = (datetime.now() - timedelta(days=DIVI_DAYS_BACK)).strftime("%Y-%m-%d")

    if not projects:
        logger.warning(f"[{name}] 未找到启用项目，跳过")
        return True

    success = True
    for project in projects:
        display_name = f"{name} | 项目 {project_label(project)}"
        logger.info(f"[{display_name}] 开始执行，日期范围: {target_date} 至今")
        timer = Timer()
        timer.start()

        try:
            divi_process_orders(target_date, True, project_id=project.id)
            timer.stop()
            elapsed = timer.elapsed()
            logger.info(f"[{display_name}] 完成，耗时 {elapsed:.2f}s")
            stats_manager.get(name).record(True, elapsed)

        except Exception as e:
            timer.stop()
            elapsed = timer.elapsed()
            error_msg = str(e)
            logger.error(f"[{display_name}] 失败: {error_msg}")
            stats_manager.get(name).record(False, elapsed, error_msg)
            success = False

    return success


def run_amazon_shipment(projects) -> bool:
    """
    执行 amazon_shipment
    """
    name = 'amazon_shipment'
    if not projects:
        logger.warning(f"[{name}] 未找到启用项目，跳过")
        return True

    success = True
    for project in projects:
        display_name = f"{name} | 项目 {project_label(project)}"
        logger.info(f"[{display_name}] 开始执行")
        timer = Timer()
        timer.start()

        try:
            amazon_shipment(project_id=project.id)
            timer.stop()
            elapsed = timer.elapsed()
            logger.info(f"[{display_name}] 完成，耗时 {elapsed:.2f}s")
            stats_manager.get(name).record(True, elapsed)

        except Exception as e:
            timer.stop()
            elapsed = timer.elapsed()
            error_msg = str(e)
            logger.error(f"[{display_name}] 失败: {error_msg}")
            stats_manager.get(name).record(False, elapsed, error_msg)
            success = False

    return success


def check_night_mode() -> bool:
    """
    检查是否处于夜间休眠时段
    返回: 是否应该休眠
    """
    now = datetime.now()
    current_hour = now.hour

    if NIGHT_START_HOUR <= current_hour < NIGHT_END_HOUR:
        target_time = now.replace(hour=NIGHT_END_HOUR, minute=0, second=0, microsecond=0)
        wait_seconds = (target_time - now).total_seconds()
        logger.info(
            f"当前时间 {now.strftime('%Y-%m-%d %H:%M:%S')}，"
            f"处于休眠时段({NIGHT_START_HOUR:02d}:00-{NIGHT_END_HOUR:02d}:00)，"
            f"等待 {int(wait_seconds / 60)} 分钟后继续..."
        )
        time.sleep(wait_seconds)
        return True
    
    return False


def main_loop(project_id=None, project_name=None):
    """
    主循环 - 7×24小时不间断运行，调度所有同步模块
    
    整体流程说明：
    1. 检查当前时间是否在夜间休眠时段（01:00-07:00），如果是则睡眠到7点
    2. 每轮循环按顺序执行：发货 → 各基础模块 → DIVI导单 → Temu订单
    3. 每10轮执行一次发货模块（amazon_shipment）
    4. 每10轮输出一次执行统计报告
    5. 每轮间隔60秒
    """
    num = 0  # 轮数计数器（1~10循环），用于控制发货频率。每执行10轮后归零
    total_round = 0  # 总轮数计数器，不归零，用于低频模块调度
    
    # ========== 启动日志：输出当前配置信息 ==========
    logger.info("=" * 80)
    logger.info("Amazon 同步主循环启动")
    logger.info(f"日志文件: {LOG_FILE}")
    logger.info(f"模块数量: {len(MODULES)}")
    logger.info(f"发货频率: 每 {SHIPMENT_INTERVAL} 轮")
    logger.info(f"店铺同步: 第 1 轮执行，之后每 {SHOP_SYNC_INTERVAL} 轮")
    logger.info(f"统计报告: 每 {STATS_REPORT_INTERVAL} 轮")
    logger.info(f"DIVI查询: 前 {DIVI_DAYS_BACK} 天")
    if project_id:
        logger.info(f"项目过滤: ID={project_id}")
    elif project_name:
        logger.info(f"项目过滤: 名称包含 '{project_name}'")
    else:
        logger.info("项目过滤: 全部启用项目")
    logger.info("=" * 80)

    # ========== 无限循环：7×24小时运行 ==========
    while True:
        # ========== 步骤1：检查夜间休眠模式 ==========
        # 获取当前时间，筛选出凌晨1点到7点之间的时段
        # 如果是休眠时段 → 计算到7点的剩余秒数，睡眠到7点后继续
        # 如果不是休眠时段 → 继续执行后续步骤
        if check_night_mode():
            continue  # 睡眠结束后的下一轮循环

        # ========== 步骤2：轮数计数器递增 ==========
        num += 1  # 当前轮数 +1（范围：1~10）
        total_round += 1
        stats_manager.cycle_count += 1  # 统计周期计数器 +1
        
        logger.info(f"\n{'=' * 40} 第 {num} 轮执行开始（总第 {total_round} 轮） {'=' * 40}")
        projects = get_active_projects(project_id=project_id, project_name=project_name)
        logger.info(f"本轮启用项目数: {len(projects)}")
        if projects:
            logger.info("本轮项目: " + "、".join(project_label(project) for project in projects))
        else:
            logger.warning("未找到启用项目，本轮跳过所有项目化模块")

        fallback_kwargs = project_filter_kwargs(project_id=project_id, project_name=project_name)

        # ========== 步骤3：执行发货模块（amazon_shipment）==========
        # 筛选条件：当 num >= 10（即每10轮执行一次）
        # 操作：调用 run_amazon_shipment()，然后重置计数器 num = 0
        # 说明：发货模块会检查 divi_order_status=5 且有物流单号的订单，调用领星API进行发货
        if num == 1 or num == SHIPMENT_INTERVAL + 1:
            if num == SHIPMENT_INTERVAL + 1:
                num = 1  # 重置计数器，下一轮从1开始
            run_amazon_shipment(projects)  # 执行发货

        # ========== 步骤4：执行基础同步模块列表 ==========
        # 遍历 MODULES 列表中的每个模块，依次执行：
        # 1. divi_guer - 检测DIVI孤儿订单（本地标记已导出但DIVI中不存在的订单，重置状态）
        # 2. lx_shop - 同步领星店铺基础数据（店铺信息、状态等）
        # 3. lx_shop2 - 同步Temu店铺数据
        # 4. lx_order - 同步亚马逊订单基础数据（买家信息、地址、金额等）
        # 5. lx_zf - 同步自发货订单号（从领星获取物流单号填充到本地order_no字段）【异步执行】
        # 6. lx_order_info - 更新订单发货时限（获取最晚发货时间）【异步执行】
        # 7. temu_orders - 同步Temu平台订单
        for module in MODULES:
            if not should_run_module(module, total_round):
                logger.info(f"[{module.name}] 低频模块，本轮跳过；每 {module.run_interval} 轮执行一次")
                continue
            run_module_with_project_scope(module, projects, fallback_project_kwargs=fallback_kwargs)  # 每个模块独立try-except，失败不影响下一个

        # ========== 步骤5：执行DIVI导单和状态同步 ==========
        # 筛选条件：查询 purchase_date_local >= 30天前 且未导出到DIVI的订单
        # 操作：
        #   1. 计算前30天的日期作为起始日期
        #   2. 调用 divi_process_orders(target_date, True) 执行：
        #      - 补导：将未导出的订单导入DIVI系统
        #      - 同步：从DIVI拉取订单状态、物流信息更新到本地
        # 涉及字段：divi_import_time, divi_logistics_method, divi_tracking_number 等
        run_divi_process_orders(projects)

        logger.info(f"{'=' * 40} 第 {num if num > 0 else SHIPMENT_INTERVAL} 轮执行完成 {'=' * 40}")

        # ========== 步骤6：输出统计报告 ==========
        # 筛选条件：当统计周期达到 STATS_REPORT_INTERVAL 轮（默认10轮）
        # 操作：
        #   1. 输出各模块的执行统计报告（成功率、平均耗时、失败次数等）
        #   2. 清空周期统计数据，开始新的统计周期
        if stats_manager.cycle_count >= STATS_REPORT_INTERVAL:
            logger.info("\n" + stats_manager.report())  # 输出报告
            stats_manager.reset_cycle()  # 重置周期统计

        # ========== 步骤7：休眠等待 ==========
        # 操作：暂停 SLEEP_INTERVAL 秒（默认60秒），避免CPU占用过高
        # 然后进入下一轮循环
        logger.info(f"等待 {SLEEP_INTERVAL} 秒后继续...\n")
        time.sleep(SLEEP_INTERVAL)


if __name__ == '__main__':
    args = parse_args()
    try:
        main_loop(project_id=args.project_id, project_name=args.project_name)
    except KeyboardInterrupt:
        logger.info("\n收到中断信号，程序退出")
    except Exception as e:
        logger.exception(f"主循环异常: {e}")
        sys.exit(1)
