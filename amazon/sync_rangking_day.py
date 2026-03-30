# sync_rangking_day.py
"""
运营日/周排名报告 v4
功能：从User模型出发，统计运营部所有人员的亚马逊+Temu业绩
发送：个人→自己，组长→组长，经理→user.id=1，均抄送自己一份
"""

from __future__ import annotations
import os
import sys
import django
from datetime import datetime, timedelta, date
from typing import Dict, Any, List, Optional, Tuple
import requests
import json
import time

# ===== Django环境设置 =====
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
sys.path.append(PROJECT_ROOT)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Overlord.settings")
django.setup()

# ===== 导入Django模型 =====
from general.models import User, AmazonShop, TemuShop, OperationalAccount
from amazon.models import LingXingAmazonShop, AmazonOrders, AmazonOrderItem
from temu.models import LingXingTemuShop, TemuOrder, TemuOrderItem
from general.models import PersonalPerformanceTarget, GroupPerformanceTarget
from django.db.models import Sum, Q, Count
# 导入新的鼓励语库
from encouragement_bank import get_encouragement

# ===== 运行配置 =====
PERIOD = "day"  # "day" 或 "week"
# PERIOD = "week"  # "day" 或 "week"
TEST_MODE = False  # True=只发自己；False=发自己+目标用户
# TEST_MODE = True  # True=只发自己；False=发自己+目标用户


# 企业微信Webhook配置
WX_MAIN = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=8ca94212-ea84-4b4e-a294-55e713dcef67"
WX_ALT_LIST = [
    "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=229c4401-fd45-49b1-b15e-3d46c8b9d7ac",
    "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=cc812cc6-1c28-4f3c-9806-d388e7940ab9",
    "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=b1f40747-a641-4886-b81d-a998f5e9095a",
]


# ===== Webhook发送函数（重写轮询逻辑）=====
def send_markdown_to_webhook(webhook_url: str, markdown_content: str) -> bool:
    """
    发送Markdown消息到企业微信，带备用URL轮询
    返回是否发送成功
    """
    headers = {'Content-Type': 'application/json'}
    payload = {
        "msgtype": "markdown",
        "markdown": {"content": markdown_content}
    }

    # 尝试主URL和所有备用URL
    urls_to_try = [webhook_url] + WX_ALT_LIST

    for url in urls_to_try:
        try:
            response = requests.post(
                url,
                headers=headers,
                data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
                timeout=10
            )

            if response.status_code == 200:
                result = response.json()
                if result.get('errcode') == 0:
                    print(f"[Send] ✅ 成功发送到: {url[:60]}...")
                    return True
                else:
                    print(f"[Send] ❌ 发送失败: {result.get('errmsg')}, URL: {url[:60]}...")
            else:
                print(f"[Send] ❌ HTTP错误: {response.status_code}, URL: {url[:60]}...")

        except Exception as e:
            print(f"[Send] ❌ 异常: {e}, URL: {url[:60]}...")

        # 失败后等待1秒再试下一个URL
        time.sleep(1)

    print(f"[Send] ❌ 所有URL都发送失败")
    return False


def send_markdown_with_backup(markdown_content: str, primary_url: Optional[str] = None) -> bool:
    """
    统一发送入口：
    - TEST_MODE=True: 只发给自己(WX_MAIN)
    - TEST_MODE=False: 发给自己 + primary_url（如果提供）
    """
    # 无论测试还是生产，都先发一份给自己
    self_sent = send_markdown_to_webhook(WX_MAIN, markdown_content)

    if TEST_MODE:
        print(f"[Mode] 测试模式，只发送给自己: {'✅成功' if self_sent else '❌失败'}")
        return self_sent

    # 生产模式：发送给目标用户
    if primary_url:
        target_sent = send_markdown_to_webhook(primary_url, markdown_content)
        print(
            f"[Mode] 生产模式 - 自己: {'✅成功' if self_sent else '❌失败'}, 目标: {'✅成功' if target_sent else '❌失败'}")
        return self_sent and target_sent

    return self_sent


# ===== 核心统计函数：获取单个运营数据 =====
def get_single_operator_stats(user_id: int, target_date: date, company_id: int = 1) -> Dict[str, Any]:
    """
    获取单个运营人员在指定日期的统计数据（亚马逊+Temu合并）
    返回: {
        'order_count': 订单量,
        'sales_quantity': 销售量(件),
        'idle_shops': {'amazon': [...], 'temu': [...]},
        'month_sales': 当月累计销售量
    }
    """
    result = {
        'order_count': 0,
        'sales_quantity': 0,
        'idle_shops': {'amazon': [], 'temu': []},
        'month_sales': 0,
        'has_amazon_shop': False,
        'has_temu_shop': False
    }

    # 获取用户和运营账号信息（修正department + 添加company过滤）
    # 注意：不排除禁用人员，用于支持组长/经理报告统计全部人员
    try:
        user = User.objects.get(
            id=user_id,
            department=User.Department.OPERATION,  # 修正：'operation'，不是'运营部'
            company_id=company_id  # 关键：必须筛选公司
        )
    except User.DoesNotExist:
        return result

    # ===== 1. 亚马逊统计（添加company过滤）=====
    # 获取所有状态的店铺（用于订单/销量统计）
    all_amazon_shops = AmazonShop.objects.filter(
        ops=user_id,
        company_id=company_id  # 关键修正：只查该公司下的店铺
    )
    all_amazon_shop_ids = list(all_amazon_shops.values_list('id', flat=True))

    if all_amazon_shop_ids:
        # 获取领星店铺ID
        lingxing_shops = LingXingAmazonShop.objects.filter(
            amazon_shop_id__in=all_amazon_shop_ids
        )
        lingxing_shop_ids = list(lingxing_shops.values_list('sid', flat=True))

        if lingxing_shop_ids:
            # 当日订单量（排除退货）
            amazon_orders_today = AmazonOrders.objects.filter(
                lingxing_shop_id__in=lingxing_shop_ids,
                purchase_date_local__date=target_date
            ).exclude(order_status='Canceled')

            result['order_count'] += amazon_orders_today.count()

            # 当日销售量（件）
            quantity_agg = AmazonOrderItem.objects.filter(
                order__lingxing_shop_id__in=lingxing_shop_ids,
                order__purchase_date_local__date=target_date
            ).exclude(order__order_status='Canceled').aggregate(
                total_quantity=Sum('quantity_ordered')
            )
            result['sales_quantity'] += int(quantity_agg['total_quantity'] or 0)

    # 获取正常状态的店铺（仅用于闲置判断）- 也要加company过滤
    normal_amazon_shops = AmazonShop.objects.filter(
        ops=user_id,
        shop_status='正常',
        company_id=company_id
    )

    # 闲置店铺判断：只检查正常状态的店铺
    seven_days_ago = target_date - timedelta(days=6)
    for shop in normal_amazon_shops:
        has_orders = AmazonOrders.objects.filter(
            lingxing_shop__amazon_shop_id=shop.id,
            purchase_date_local__date__gte=seven_days_ago,
            purchase_date_local__date__lte=target_date
        ).exists()
        if not has_orders:
            result['idle_shops']['amazon'].append(shop.shop_name)

    # ===== 2. Temu统计（添加company过滤）=====
    temu_shops = TemuShop.objects.filter(
        ops_id=user_id,
        company_id=company_id  # 关键修正：只查该公司下的店铺
    )
    temu_shop_ids = list(temu_shops.values_list('id', flat=True))

    if temu_shop_ids:
        # 获取当日所有订单
        all_orders_today = TemuOrder.objects.filter(
            lingxing_shop__temu_shop_id__in=temu_shop_ids,
            global_purchase_time__date=target_date
        ).values('global_order_no', 'platform_info')

        # 识别退货订单
        cancelled_order_nos = []
        for order in all_orders_today:
            platform_info = order.get('platform_info')
            if platform_info and isinstance(platform_info, list) and len(platform_info) > 0:
                if platform_info[0].get('status') == 'CANCELED':
                    cancelled_order_nos.append(order['global_order_no'])

        # 当日订单量（排除退货）
        temu_orders_today = TemuOrder.objects.filter(
            lingxing_shop__temu_shop_id__in=temu_shop_ids,
            global_purchase_time__date=target_date
        ).exclude(global_order_no__in=cancelled_order_nos)

        result['order_count'] += temu_orders_today.count()

        # 当日销售量（件）
        temu_quantity_agg = TemuOrderItem.objects.filter(
            order__lingxing_shop__temu_shop_id__in=temu_shop_ids,
            order__global_purchase_time__date=target_date
        ).exclude(order__global_order_no__in=cancelled_order_nos).aggregate(
            total_quantity=Sum('quantity')
        )
        result['sales_quantity'] += int(temu_quantity_agg['total_quantity'] or 0)

        # 闲置店铺判断：近7天是否有订单（Temu无店铺状态字段）
        for shop in temu_shops:
            has_orders = TemuOrder.objects.filter(
                lingxing_shop__temu_shop_id=shop.id,
                global_purchase_time__date__gte=seven_days_ago,
                global_purchase_time__date__lte=target_date
            ).exists()
            if not has_orders:
                result['idle_shops']['temu'].append(shop.shop_name)

    # ===== 3. 当月累计销售量 =====
    month_start = target_date.replace(day=1)

    # 亚马逊当月销量（使用所有店铺）
    if all_amazon_shop_ids:
        amz_month_qty = AmazonOrderItem.objects.filter(
            order__lingxing_shop__amazon_shop_id__in=all_amazon_shop_ids,
            order__purchase_date_local__date__gte=month_start,
            order__purchase_date_local__date__lte=target_date
        ).exclude(order__order_status='Canceled').aggregate(
            total=Sum('quantity_ordered')
        )
        result['month_sales'] += int(amz_month_qty['total'] or 0)
        result['has_amazon_shop'] = True

    # Temu当月销量
    if temu_shop_ids:
        # 当月所有订单
        all_month_orders = TemuOrder.objects.filter(
            lingxing_shop__temu_shop_id__in=temu_shop_ids,
            global_purchase_time__date__gte=month_start,
            global_purchase_time__date__lte=target_date
        ).values('global_order_no', 'platform_info')

        # 识别当月退货
        month_cancelled_nos = []
        for order in all_month_orders:
            platform_info = order.get('platform_info')
            if platform_info and isinstance(platform_info, list) and len(platform_info) > 0:
                if platform_info[0].get('status') == 'CANCELED':
                    month_cancelled_nos.append(order['global_order_no'])

        temu_month_qty = TemuOrderItem.objects.filter(
            order__lingxing_shop__temu_shop_id__in=temu_shop_ids,
            order__global_purchase_time__date__gte=month_start,
            order__global_purchase_time__date__lte=target_date
        ).exclude(order__global_order_no__in=month_cancelled_nos).aggregate(
            total=Sum('quantity')
        )
        result['month_sales'] += int(temu_month_qty['total'] or 0)
        result['has_temu_shop'] = True

    return result

# ===== 获取运营部所有用户 =====
def get_all_operators() -> List[User]:
    """获取所有运营部门且状态正常的用户（默认公司1）"""
    return User.objects.filter(
        status=User.Status.NORMAL,
        department=User.Department.OPERATION,  # 'operation'
        company_id=1  # 硬编码公司1，或改为参数传入
    ).select_related('operational_account')


def get_all_operators_include_inactive() -> List[User]:
    """获取公司全部运营人员（包括停用的，用于组长和经理报告）"""
    return User.objects.filter(
        department=User.Department.OPERATION,
        company_id=1
    ).select_related('operational_account')


# ===== 获取所有组长 =====
def get_all_leaders() -> List[User]:
    """获取所有运营组长且状态正常的用户（默认公司1）"""
    return User.objects.filter(
        status=User.Status.NORMAL,
        department=User.Department.OPERATION,  # 'operation'
        company_id=1,  # 硬编码公司1
        operational_account__role=OperationalAccount.Role.LEADER  # 'leader'
    ).select_related('operational_account')


# ===== 消息渲染函数：个人报告 =====
def render_personal_report(
        user: User,
        stats: Dict[str, Any],
        target_date: date,
        overall_rank: int,
        group_rank: int,
        total_operators: int,
        group_operators: int,
        period: str = "day"
) -> str:
    """渲染个人报告Markdown（含环比、店铺列表、新鼓励语）"""
    name = user.first_name or user.username
    group_name = user.get_ops_group() or '未分组'

    # ========== 1. 计算环比数据（方案A：实时计算） ==========
    # 确定对比日期
    if period == "day":
        # 昨天 vs 前天
        compare_date = target_date - timedelta(days=1)
        prev_compare_date = target_date - timedelta(days=2)
    else:  # week
        # 上周 vs 上上周（周报通常统计整周数据，这里简化为环比前一周同一天）
        compare_date = target_date - timedelta(days=7)
        prev_compare_date = target_date - timedelta(days=14)

    # 获取昨天/上周的统计数据
    prev_stats = get_single_operator_stats(user.id, compare_date)

    # 获取前天/上上周的排名（需要重新计算全局和组内排名）
    prev_operators = get_all_operators()
    prev_stats_cache = {u.id: get_single_operator_stats(u.id, prev_compare_date) for u in prev_operators}

    # 前天/上上周的全局排名
    prev_ranked_users = sorted(prev_operators, key=lambda u: -prev_stats_cache[u.id]['order_count'])
    prev_overall_rank_map = {u.id: i + 1 for i, u in enumerate(prev_ranked_users)}
    prev_overall_rank = prev_overall_rank_map.get(user.id, total_operators)

    # 前天/上上周的组内排名
    prev_group_members = [u for u in prev_operators if (u.get_ops_group() or '未分组') == group_name]
    prev_group_rank_map = {u.id: i + 1 for i, u in enumerate(
        sorted(prev_group_members, key=lambda u: -prev_stats_cache[u.id]['order_count'])
    )}
    prev_group_rank = prev_group_rank_map.get(user.id, group_operators)

    # ========== 2. 计算环比变化率和箭头 ==========
    def calc_change_emoji(current, previous):
        """计算变化率、箭头、颜色"""
        if previous == 0:
            # 如果前一天为0，今天>0视为上升100%
            rate = 100.0 if current > 0 else 0.0
        else:
            rate = ((current - previous) / previous) * 100

        if rate > 0:
            return f"<font color='red'>↑{rate:.1f}%</font>"
        elif rate < 0:
            return f"<font color='green'>↓{abs(rate):.1f}%</font>"
        else:
            return "持平"

    # 订单量环比
    order_change = calc_change_emoji(stats['order_count'], prev_stats['order_count'])

    # 销量环比
    sales_change = calc_change_emoji(stats['sales_quantity'], prev_stats['sales_quantity'])

    # 公司排名环比
    rank_change = prev_overall_rank - overall_rank  # 正数表示排名上升（数字变小）
    if rank_change > 0:
        rank_change_text = f"<font color='red'>上升{rank_change}名</font>"
    elif rank_change < 0:
        rank_change_text = f"<font color='green'>下降{abs(rank_change)}名</font>"
    else:
        rank_change_text = "持平"

    # 小组排名环比
    group_rank_change = prev_group_rank - group_rank
    if group_rank_change > 0:
        group_rank_change_text = f"<font color='red'>上升{group_rank_change}名</font>"
    elif group_rank_change < 0:
        group_rank_change_text = f"<font color='green'>下降{abs(group_rank_change)}名</font>"
    else:
        group_rank_change_text = "持平"

    # ========== 3. 负责店铺列表 ==========
    # 获取所有店铺（不过滤状态）
    amazon_shops = AmazonShop.objects.filter(ops=user.id)
    temu_shops = TemuShop.objects.filter(ops_id=user.id)

    shop_names = []
    shop_names.extend([s.shop_name for s in amazon_shops if s.shop_name])
    shop_names.extend([s.shop_name for s in temu_shops if s.shop_name])

    # 去重并格式化
    shop_names = list(set(shop_names))
    shop_list_str = "、".join(shop_names)
    shop_list_str += f"（共{len(shop_names)}个）"

    # ========== 4. 闲置店铺明细 ==========
    idle_amazon = stats['idle_shops']['amazon']
    idle_temu = stats['idle_shops']['temu']
    idle_detail_parts = []

    if idle_amazon:
        idle_detail_parts.append(
            f"亚马逊{len(idle_amazon)}家（{'、'.join(idle_amazon[:3])}{'...' if len(idle_amazon) > 3 else ''}）")
    if idle_temu:
        idle_detail_parts.append(
            f"Temu{len(idle_temu)}家（{'、'.join(idle_temu[:3])}{'...' if len(idle_temu) > 3 else ''}）")

    idle_detail = "；".join(idle_detail_parts) if idle_detail_parts else "无"

    # ========== 5. 月度目标进度 ==========
    month_start = target_date.replace(day=1)
    try:
        target = PersonalPerformanceTarget.objects.get(
            user=user,
            month=month_start
        ).target_performance
    except:
        target = None

    if target:
        progress_rate = stats['month_sales'] / target * 100
        progress_text = f"{stats['month_sales']}/{target}（{progress_rate:.2f}%）"
    else:
        progress_text = f"{stats['month_sales']}/—（未设置目标）"

    # ========== 6. 鼓励语（使用新的encouragement_bank） ==========
    # 判断趋势场景
    if group_rank == 1:
        scenario = "rise"  # 小组第一，视为上升
    elif stats['order_count'] == 0:
        scenario = "fall"  # 订单为0，视为下降
    else:
        scenario = "stable"  # 其他情况视为稳定

    # 从 encouragement_bank 获取鼓励语
    encouragement = get_encouragement(scenario)

    # ========== 7. 组装Markdown ==========
    md = f"""## {name} {'昨日' if period == 'day' else '上周'}数据（{target_date}）
> —— 专属数据小报告 ——

> **所属小组**：{group_name}
> **负责店铺**：{shop_list_str}

> **订单量**：<font color='skyblue'>{stats['order_count']}</font> 单 {order_change}
> **销量**：<font color='skyblue'>{stats['sales_quantity']}</font> 件 {sales_change}
> **公司排名**：第{overall_rank}/{total_operators}名（{rank_change_text}）
> **小组排名**：第{group_rank}/{group_operators}名（{group_rank_change_text}）

> **闲置店铺**（近7天无订单）：{idle_detail}

> **本月进度**（销量/目标）：{progress_text}

> {encouragement}"""

    return md


# ===== 消息渲染函数：组长报告 =====
def render_leader_report(
        leader: User,
        group_name: str,
        target_date: date,
        members_stats: List[Tuple[User, Dict[str, Any]]],
        group_month_sales: int,
        group_month_target: Optional[int],
        period: str = "day"
) -> str:
    """渲染组长报告Markdown（含环比、店铺明细、新鼓励语）"""
    # 组总计
    group_total_orders = sum(s['order_count'] for _, s in members_stats)
    group_total_sales = sum(s['sales_quantity'] for _, s in members_stats)

    # ========== 1. 计算组环比数据 ==========
    # 对比日期
    if period == "day":
        compare_date = target_date - timedelta(days=1)
    else:
        compare_date = target_date - timedelta(days=7)

    # 获取对比日期的组数据
    prev_group_orders = 0
    prev_group_sales = 0

    for member, _ in members_stats:
        prev_stats = get_single_operator_stats(member.id, compare_date)
        prev_group_orders += prev_stats['order_count']
        prev_group_sales += prev_stats['sales_quantity']

    # 计算环比
    def calc_group_change(current, previous):
        if previous == 0:
            return f"<font color='red'>↑100%</font>" if current > 0 else "持平"
        rate = ((current - previous) / previous) * 100
        if rate > 0:
            return f"<font color='red'>↑{rate:.1f}%</font>"
        elif rate < 0:
            return f"<font color='green'>↓{abs(rate):.1f}%</font>"
        return "持平"

    orders_change = calc_group_change(group_total_orders, prev_group_orders)
    sales_change = calc_group_change(group_total_sales, prev_group_sales)

    # ========== 2. 计算组在公司中的排名及环比 ==========
    # 获取全公司所有运营人员
    all_operators = get_all_operators()

    # 统计当前日期所有小组的订单量
    current_group_stats = {}
    for user in all_operators:
        stats = get_single_operator_stats(user.id, target_date)
        user_group = user.get_ops_group() or '未分组'
        if user_group not in current_group_stats:
            current_group_stats[user_group] = 0
        current_group_stats[user_group] += stats['order_count']

    # 当前小组排名
    sorted_current_groups = sorted(current_group_stats.items(), key=lambda x: -x[1])
    group_rank_map_current = {name: i + 1 for i, (name, _) in enumerate(sorted_current_groups)}
    current_rank = group_rank_map_current.get(group_name, len(sorted_current_groups))
    total_groups = len(sorted_current_groups)

    # 历史日期小组排名（用于环比）
    prev_group_stats = {}
    for user in all_operators:
        prev_stats = get_single_operator_stats(user.id, compare_date)
        user_group = user.get_ops_group() or '未分组'
        if user_group not in prev_group_stats:
            prev_group_stats[user_group] = 0
        prev_group_stats[user_group] += prev_stats['order_count']

    prev_sorted_groups = sorted(prev_group_stats.items(), key=lambda x: -x[1])
    group_rank_map_prev = {name: i + 1 for i, (name, _) in enumerate(prev_sorted_groups)}
    prev_rank = group_rank_map_prev.get(group_name, len(prev_sorted_groups))

    # 排名变化
    rank_change = prev_rank - current_rank
    if rank_change > 0:
        rank_change_text = f"<font color='red'>↑{rank_change}名</font>"
    elif rank_change < 0:
        rank_change_text = f"<font color='green'>↓{abs(rank_change)}名</font>"
    else:
        rank_change_text = "持平"

    group_rank_detail = f"【组排名{current_rank}/{total_groups}（{rank_change_text}）】"

    # ========== 3. 组内成员排序（区分活跃和禁用） ==========
    # 活跃组员参与排名
    active_members = [(u, s) for u, s in members_stats if u.status == User.Status.NORMAL]
    # 禁用组员不参与排名，但显示在列表中
    inactive_members = [(u, s) for u, s in members_stats if u.status != User.Status.NORMAL]
    
    # 活跃组员按订单量排序
    sorted_active_members = sorted(active_members, key=lambda x: (-x[1]['order_count'], x[0].id))
    # 禁用组员也按订单量排序，但放在最后
    sorted_inactive_members = sorted(inactive_members, key=lambda x: (-x[1]['order_count'], x[0].id))
    
    # 合并列表（活跃在前，禁用在后）
    sorted_members = sorted_active_members + sorted_inactive_members

    # ========== 4. 成员月度进度 ==========
    month_start = target_date.replace(day=1)
    member_progress = []
    for user, stats in sorted_members:
        try:
            target = PersonalPerformanceTarget.objects.get(
                user=user,
                month=month_start
            ).target_performance
        except:
            target = None

        member_sales = stats['month_sales']
        if target:
            rate = member_sales / target * 100
            progress_str = f"{member_sales}/{target}（{rate:.2f}%）"
        else:
            progress_str = f"{member_sales}/—"

        member_progress.append((user.first_name or user.username, progress_str))

    # ========== 5. 闲置店铺统计（带明细） ==========
    idle_summary = []
    for user, stats in sorted_members:
        if stats['idle_shops']['amazon'] or stats['idle_shops']['temu']:
            user_name = user.first_name or user.username
            details = []
            if stats['idle_shops']['amazon']:
                details.append(f"亚马逊：{'、'.join(stats['idle_shops']['amazon'])}")
            if stats['idle_shops']['temu']:
                details.append(f"Temu：{'、'.join(stats['idle_shops']['temu'])}")
            idle_summary.append(f"- {user_name}：{'；'.join(details)}")

    # ========== 6. 公司级排名及环比 ==========
    # 获取全公司当日统计数据（包含全部人员，与经理报告一致）
    all_operators = get_all_operators_include_inactive()
    all_stats_cache = {u.id: get_single_operator_stats(u.id, target_date) for u in all_operators}

    # 公司排名（仅活跃组员有排名）
    active_operators = [u for u in all_operators if u.status == User.Status.NORMAL]
    company_ranked = sorted(active_operators, key=lambda u: -all_stats_cache[u.id]['order_count'])
    company_rank_map = {u.id: i + 1 for i, u in enumerate(company_ranked)}

    # 公司前一天/上周排名（仅活跃组员）
    if period == "day":
        prev_company_date = target_date - timedelta(days=2)
    else:
        prev_company_date = target_date - timedelta(days=14)

    prev_company_cache = {u.id: get_single_operator_stats(u.id, prev_company_date) for u in all_operators}
    prev_company_ranked = sorted(active_operators, key=lambda u: -prev_company_cache[u.id]['order_count'])
    prev_company_rank_map = {u.id: i + 1 for i, u in enumerate(prev_company_ranked)}

    # 组内排名列表（含公司排名与环比）
    # 只针对活跃组员计算前日排名
    prev_group_rank_map = {}
    if period == "day":
        prev_compare_date = target_date - timedelta(days=2)
    else:
        prev_compare_date = target_date - timedelta(days=14)

    # 只获取活跃组员的前日数据用于排名
    prev_active_members_stats = [
        (member, get_single_operator_stats(member.id, prev_compare_date))
        for member, _ in members_stats 
        if member.status == User.Status.NORMAL
    ]
    prev_sorted = sorted(prev_active_members_stats, key=lambda x: (-x[1]['order_count'], x[0].id))
    prev_group_rank_map = {u.id: i + 1 for i, (u, _) in enumerate(prev_sorted)}

    rank_list = []
    active_rank_counter = 0  # 活跃组员排名计数器
    
    for user, stats in sorted_members:
        # 判断是否为活跃组员
        is_active = user.status == User.Status.NORMAL
        
        if is_active:
            active_rank_counter += 1
            current_group_rank = active_rank_counter
            prev_group_rank = prev_group_rank_map.get(user.id, len(sorted_active_members))
            rank_change = prev_group_rank - current_group_rank

            if rank_change > 0:
                rank_change_text = f"<font color='red'>↑{rank_change}名</font>"
            elif rank_change < 0:
                rank_change_text = f"<font color='green'>↓{abs(rank_change)}名</font>"
            else:
                rank_change_text = "持平"

            # 公司排名及变化（仅活跃组员有公司排名）
            current_company_rank = company_rank_map.get(user.id, len(all_operators))
            prev_company_rank = prev_company_rank_map.get(user.id, len(all_operators))
            company_rank_change = prev_company_rank - current_company_rank
            if company_rank_change > 0:
                company_rank_change_text = f"<font color='red'>↑{company_rank_change}名</font>"
            elif company_rank_change < 0:
                company_rank_change_text = f"<font color='green'>↓{abs(company_rank_change)}名</font>"
            else:
                company_rank_change_text = "持平"

            rank_list.append(
                f"- 第{current_group_rank}名 {user.first_name or user.username}：订单 <font color='skyblue'>{stats['order_count']}</font> 单，"
                f"销量 <font color='skyblue'>{stats['sales_quantity']}</font> 件（{rank_change_text}）"
                f"【公司排名{current_company_rank}（{company_rank_change_text}）】"
            )
        else:
            # 禁用组员：显示但不参与排名
            rank_list.append(
                f"- <font color='gray'>[已停用] {user.first_name or user.username}：订单 <font color='skyblue'>{stats['order_count']}</font> 单，"
                f"销量 <font color='skyblue'>{stats['sales_quantity']}</font> 件（不参与排名）</font>"
            )

    # ========== 7. 月度进度 ==========
    group_progress = f"{group_month_sales}/{group_month_target or '—'}（{group_month_sales / group_month_target * 100:.2f}%）" if group_month_target else f"{group_month_sales}/—（未设置目标）"

    # ========== 8. 鼓励语 ==========
    # 判断组整体趋势
    if group_total_orders > prev_group_orders:
        scenario = "rise"
    elif group_total_orders < prev_group_orders:
        scenario = "fall"
    else:
        scenario = "stable"

    encouragement = get_encouragement(scenario)

    # ========== 9. 组装Markdown ==========
    md = f"""## {group_name} {'昨日' if period == 'day' else '上周'}汇总（{target_date}）
> —— 组长专属数据小报告 ——

> **组总订单量**：<font color='skyblue'>{group_total_orders}</font> 单 {orders_change}
> **组总销量**：<font color='skyblue'>{group_total_sales}</font> 件 {sales_change}

### 本月进度（组，销量/目标）
- 全组：{group_progress}
> {group_rank_detail}

### 本月进度（组内成员，销量/目标）
{chr(10).join([f"- {name}：{prog}" for name, prog in member_progress])}

### 组内成员排名（按订单量）
{chr(10).join(rank_list)}

### 闲置店铺统计（近7天无订单）
{chr(10).join(idle_summary) or '> 无'}

> {encouragement}"""

    return md


# ===== 消息渲染函数：经理报告 =====
def render_manager_report(
        target_date: date,
        all_operators: List[Tuple[User, Dict[str, Any]]],
        groups_data: Dict[str, List[Tuple[User, Dict[str, Any]]]],
        period: str = "day"
) -> str:
    """渲染经理报告Markdown（含分平台数据、公司/小组目标进度）"""

    # ========== 1. 分平台统计公司数据 ==========
    amazon_total_orders = sum(
        s['order_count'] for _, s in all_operators
        if s['has_amazon_shop']
    )
    amazon_total_sales = sum(
        s['sales_quantity'] for _, s in all_operators
        if s['has_amazon_shop']
    )

    temu_total_orders = sum(
        s['order_count'] for _, s in all_operators
        if s['has_temu_shop']
    )
    temu_total_sales = sum(
        s['sales_quantity'] for _, s in all_operators
        if s['has_temu_shop']
    )

    total_orders = amazon_total_orders + temu_total_orders
    total_sales = amazon_total_sales + temu_total_sales

    # ========== 2. 计算公司环比 ==========
    if period == "day":
        compare_date = target_date - timedelta(days=1)
    else:
        compare_date = target_date - timedelta(days=7)

    prev_amazon_orders = 0
    prev_amazon_sales = 0
    prev_temu_orders = 0
    prev_temu_sales = 0

    for user, current_stats in all_operators:
        prev_stats = get_single_operator_stats(user.id, compare_date)
        if current_stats['has_amazon_shop']:
            prev_amazon_orders += prev_stats['order_count']
            prev_amazon_sales += prev_stats['sales_quantity']
        if current_stats['has_temu_shop']:
            prev_temu_orders += prev_stats['order_count']
            prev_temu_sales += prev_stats['sales_quantity']

    def calc_change(current, previous):
        if previous == 0:
            return f"<font color='red'>↑100%</font>" if current > 0 else ""
        rate = ((current - previous) / previous) * 100
        if rate > 0:
            return f"<font color='red'>↑{rate:.1f}%</font>"
        elif rate < 0:
            return f"<font color='green'>↓{abs(rate):.1f}%</font>"
        return ""

    amazon_orders_change = calc_change(amazon_total_orders, prev_amazon_orders)
    amazon_sales_change = calc_change(amazon_total_sales, prev_amazon_sales)
    temu_orders_change = calc_change(temu_total_orders, prev_temu_orders)
    temu_sales_change = calc_change(temu_total_sales, prev_temu_sales)
    total_orders_change = calc_change(total_orders, prev_amazon_orders + prev_temu_orders)
    total_sales_change = calc_change(total_sales, prev_amazon_sales + prev_temu_sales)

    # ========== 3. 小组排名 ==========
    prev_groups_data = {}
    for group_name, members in groups_data.items():
        prev_groups_data[group_name] = {
            'orders': sum(get_single_operator_stats(m.id, compare_date)['order_count'] for m, _ in members)
        }

    group_totals = []
    for group_name, members in groups_data.items():
        group_orders = sum(s['order_count'] for _, s in members)
        prev_orders = prev_groups_data.get(group_name, {'orders': 0})['orders']
        orders_chg = calc_change(group_orders, prev_orders)
        group_totals.append((group_name, group_orders, orders_chg))

    group_totals.sort(key=lambda x: -x[1])
    group_ranking = "\n".join([
        f"- 第{i}名 {group}：订单 <font color='skyblue'>{orders}</font> 单 {chg}"
        for i, (group, orders, chg) in enumerate(group_totals, 1)
    ])

    # ========== 4. 闲置店铺总计 ==========
    total_idle_amazon = sum(len(s['idle_shops']['amazon']) for _, s in all_operators)
    total_idle_temu = sum(len(s['idle_shops']['temu']) for _, s in all_operators)

    # ========== 5. 公司整体进度 + 小组目标进度 ==========
    month_start = target_date.replace(day=1)

    company_month_sales = sum(s['month_sales'] for _, s in all_operators)

    all_groups = list(groups_data.keys())
    company_month_target = 0
    for group_name in all_groups:
        try:
            group_target = GroupPerformanceTarget.objects.get(
                ops_group=group_name,
                month=month_start
            ).target_performance
            company_month_target += group_target or 0
        except:
            continue

    if company_month_target > 0:
        company_progress_rate = company_month_sales / company_month_target * 100
        company_progress_text = f"{company_month_sales}/{company_month_target}（{company_progress_rate:.2f}%）"
    else:
        company_progress_text = f"{company_month_sales}/—（未设置总目标）"

    group_progress = []
    for group_name in sorted(all_groups):
        group_month_sales = sum(
            s['month_sales'] for u, s in all_operators
            if (u.get_ops_group() or '未分组') == group_name
        )
        try:
            group_target = GroupPerformanceTarget.objects.get(
                ops_group=group_name,
                month=month_start
            ).target_performance
        except:
            group_target = None

        if group_target:
            rate = group_month_sales / group_target * 100
            progress_str = f"{group_month_sales}/{group_target}（{rate:.2f}%）"
        else:
            progress_str = f"{group_month_sales}/—（未设置目标）"
        group_progress.append((group_name, progress_str))

    # ========== 6. 鼓励语 ==========
    encouragement = get_encouragement("rise")

    # ========== 7. 组装Markdown ==========
    md = f"""## 公司整体{'昨日' if period == 'day' else '上周'}汇总（{target_date}）
> —— 公司整体经营看板 ——

> **亚马逊**：订单 <font color='skyblue'>{amazon_total_orders}</font> 单 {amazon_orders_change}，销量 <font color='skyblue'>{amazon_total_sales}</font> 件 {amazon_sales_change}
> **Temu**：订单 <font color='skyblue'>{temu_total_orders}</font> 单 {temu_orders_change}，销量 <font color='skyblue'>{temu_total_sales}</font> 件 {temu_sales_change}
> **合计**：订单 <font color='skyblue'>{total_orders}</font> 单 {total_orders_change}，销量 <font color='skyblue'>{total_sales}</font> 件 {total_sales_change}

### 小组排名（按订单量）
{group_ranking}

> **闲置店铺总计**：亚马逊 <font color='skyblue'>{total_idle_amazon}</font> 家，{f"Temu <font color='skyblue'>{total_idle_temu}</font> 家" if total_idle_temu > 0 else ""}

### 公司整体目标进度（当月，销量/目标）
- 全公司：{company_progress_text}

### 小组目标进度（当月，销量/目标，亚马逊+Temu）
{chr(10).join([f"- {name}：{prog}" for name, prog in group_progress])}

> {encouragement}"""

    return md


# ===== 三个发送模块 =====
def send_personal_report(target_date: date, period: str = "day"):
    """发送个人报告给每个运营人员"""
    print(f"\n{'=' * 70}")
    print(f"开始发送个人报告: {target_date} ({'日报' if period == 'day' else '周报'})")
    print(f"{'=' * 70}\n")

    operators = get_all_operators()
    if not operators:
        print("❌ 没有找到运营人员")
        return

    # 预计算所有统计数据
    stats_cache = {}
    for user in operators:
        stats_cache[user.id] = get_single_operator_stats(user.id, target_date)

    # 全局排名
    ranked_users = sorted(operators, key=lambda u: -stats_cache[u.id]['order_count'])
    overall_rank_map = {u.id: i + 1 for i, u in enumerate(ranked_users)}

    # 按组排名
    groups = {}
    for user in operators:
        group = user.get_ops_group() or '未分组'
        if group not in groups:
            groups[group] = []
        groups[group].append(user)

    group_rank_maps = {}
    for group, members in groups.items():
        ranked_members = sorted(members, key=lambda u: -stats_cache[u.id]['order_count'])
        group_rank_maps[group] = {u.id: i + 1 for i, u in enumerate(ranked_members)}

    # 发送个人报告
    for user in operators:
        stats = stats_cache[user.id]
        overall_rank = overall_rank_map[user.id]
        group_name = user.get_ops_group() or '未分组'
        group_rank = group_rank_maps[group_name][user.id]

        md = render_personal_report(
            user, stats, target_date,
            overall_rank, group_rank,
            len(operators), len(groups[group_name]),
            period=period
        )

        send_markdown_with_backup(md, user.wx_url)

    print(f"\n✅ 个人报告发送完成，共 {len(operators)} 人\n")


def send_leader_report(target_date: date, period: str = "day"):
    """发送组长报告给每个组长（包含禁用组员，但不参与排名）"""
    print(f"\n{'=' * 70}")
    print(f"开始发送组长报告: {target_date} ({'日报' if period == 'day' else '周报'})")
    print(f"{'=' * 70}\n")

    leaders = get_all_leaders()
    if not leaders:
        print("❌ 没有找到组长")
        return

    # 使用包含禁用人员的查询（组长报告需求）
    operators = get_all_operators_include_inactive()
    if not operators:
        return

    # 预计算统计数据
    stats_cache = {u.id: get_single_operator_stats(u.id, target_date) for u in operators}

    # 按组组织成员
    groups_data = {}
    for user in operators:
        group = user.get_ops_group() or '未分组'
        if group not in groups_data:
            groups_data[group] = []
        groups_data[group].append((user, stats_cache[user.id]))

    # 发送给每个组长
    for leader in leaders:
        leader_group = leader.get_ops_group()
        if not leader_group or leader_group not in groups_data:
            print(f"⚠️ 组长 {leader.first_name} 未匹配到组成员")
            continue

        members = groups_data[leader_group]

        # 计算组月度目标
        month_start = target_date.replace(day=1)
        try:
            group_target = GroupPerformanceTarget.objects.get(
                ops_group=leader_group,
                month=month_start
            ).target_performance
        except:
            group_target = None

        # 计算组当月销量
        group_month_sales = sum(s['month_sales'] for _, s in members)

        md = render_leader_report(
            leader, leader_group, target_date,
            members, group_month_sales, group_target,
            period=period
        )

        send_markdown_with_backup(md, leader.wx_url)

    print(f"\n✅ 组长报告发送完成，共 {len(leaders)} 人\n")


def send_manager_report(target_date: date, period: str = "day"):
    """发送经理报告给user.id=1（包含全部人员，不排除停用的）"""
    print(f"\n{'=' * 70}")
    print(f"开始发送经理报告: {target_date} ({'日报' if period == 'day' else '周报'})")
    print(f"{'=' * 70}\n")

    try:
        manager = User.objects.get(id=1, status=User.Status.NORMAL)
    except User.DoesNotExist:
        print("❌ 找不到经理用户 (id=1)")
        return

    # 使用包含禁用人员的查询（经理报告需求：统计全部人员）
    operators = get_all_operators_include_inactive()
    if not operators:
        print("❌ 没有运营人员数据")
        return

    # 预计算统计数据
    all_operators = []
    groups_data = {}

    for user in operators:
        stats = get_single_operator_stats(user.id, target_date)
        all_operators.append((user, stats))

        group = user.get_ops_group() or '未分组'
        if group not in groups_data:
            groups_data[group] = []
        groups_data[group].append((user, stats))

    # 注意：render_manager_report 已不需要 company_month_sales 和 company_month_target 参数
    md = render_manager_report(
        target_date, all_operators, groups_data,
        period=period  # 只传递 period 作为关键字参数
    )

    send_markdown_with_backup(md, manager.wx_url)

    print(f"\n✅ 经理报告发送完成\n")


def main(period: str = "day"):
    """
    主入口函数，直接调用执行

    Args:
        period: 报告周期，"day" 表示日报，"week" 表示周报，默认为日报
    """
    # 验证参数
    if period not in ["day", "week"]:
        raise ValueError("period 必须是 'day' 或 'week'")

    # 确定目标日期
    if period == "day":
        target_date = date.today() - timedelta(days=1)
    else:
        # 周报：上周一
        today = date.today()
        target_date = today - timedelta(days=today.weekday() + 7)

    print(f"\n{'=' * 70}")
    print(f"📊 开始执行{'日' if period == 'day' else '周'}报任务: {target_date}")
    print(f"{'=' * 70}\n")

    # 发送三个层级的报告
    send_personal_report(target_date, period=period)
    send_leader_report(target_date, period=period)
    send_manager_report(target_date, period=period)

    print(f"\n{'=' * 70}")
    print("✅ 所有报告发送完成！")
    print(f"{'=' * 70}\n")


if __name__ == "__main__":
    main(PERIOD)
