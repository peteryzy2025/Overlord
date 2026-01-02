import os
import sys
import django
import logging
from datetime import datetime, timedelta
import requests

# ========== Django环境初始化 ==========
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
sys.path.append(PROJECT_ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Overlord.settings")
django.setup()

# ========== 配置常量 ==========
# 未揽收状态集合
UNCOLLECTED_STATUSES = ['INIT', 'NO_RECORD', 'INFO_RECEIVED']

# 筛选配置：天数阈值（互斥的两组）
UNCOLLECTED_DAYS = [3, 5, 7, 10]  # 只显示未揽收
EXCLUDE_UNCOLLECTED_DAYS = [3, 5, 10, 15, 20]  # 排除未揽收后

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# ========== 导入Django模型 ==========
from Track.models import Tracking
from General.models import User
# 导入 Django 的 timezone
from django.utils import timezone


def calculate_stale_hours(last_update_time):
    """计算停滞小时数"""
    if not last_update_time:
        return 0

    now = datetime.now()
    try:
        last_time = last_update_time.replace(tzinfo=None)
        hours_diff = (now - last_time).total_seconds() / 3600
        return int(hours_diff)
    except:
        return 0


import random  # 在文件顶部添加这个导入


def build_notification_message(operator_name, uncollected_stats, exclude_stats):
    """
    构建企业微信Markdown消息（随机选择温馨开头）

    参数:
        operator_name: 运营姓名
        uncollected_stats: {3: [track1, track2], 5: [track3, track4]}  # 未揽收统计
        exclude_stats: {3: [track5, track6], 5: [track7, track8]}  # 排除未揽收统计
    """

    # 🔵 五个温馨开头版本，随机选择
    greetings = [
        f"**📦 物流小助手呼叫 {operator_name}～**\n\n✨ 发现了一些需要您关注的订单哦：\n",

        f"**【物流状态提醒】  {operator_name}，您好！**\n\n🌟 以下订单的物流状态需要您留意一下：\n",

        f"**嗨，{operator_name}，物流小管家提醒 💌**\n\n发现了几个订单需要您看看：\n",

        f"**📮 物流小助手来咯～**\n\n👋 哈喽 {operator_name}，\n以下订单的物流状态有更新哦：\n",

        f"**Hi {operator_name}，物流提醒 🚀**\n\n以下订单需要您关注：\n"
    ]

    # 随机选择一个开头
    lines = [random.choice(greetings)]

    # 未揽收部分
    if uncollected_stats:
        lines.append("\n**📦 待揽收异常订单：**")
        for days in sorted(uncollected_stats.keys()):
            tracks = uncollected_stats[days]
            if tracks:
                # 按停滞天数降序排列
                tracks_sorted = sorted(tracks, key=lambda x: x['stale_hours'], reverse=True)
                track_list = "，".join([t['track_no'] for t in tracks_sorted])
                lines.append(f"\n**超过{days}天待揽收的有{len(tracks)}个：**")
                lines.append(f"{track_list}")

    # 排除未揽收部分
    if exclude_stats:
        lines.append("\n**🚚 在途异常订单：**")
        for days in sorted(exclude_stats.keys()):
            tracks = exclude_stats[days]
            if tracks:
                # 按停滞天数降序排列
                tracks_sorted = sorted(tracks, key=lambda x: x['stale_hours'], reverse=True)
                track_list = "，".join([t['track_no'] for t in tracks_sorted])
                lines.append(f"\n**停滞超过{days}天的有{len(tracks)}个：**")
                lines.append(f"{track_list}")

    lines.append("\n**操作**：请及时登录系统查看并处理")
    return "\n".join(lines)


def send_wechat_notification(wx_url, message):
    """
    发送企业微信通知（同步）
    返回: bool - 是否发送成功
    """
    if not wx_url:
        logger.warning("未配置企业微信通知地址")
        return False

    try:
        response = requests.post(
            wx_url,
            json={
                "msgtype": "markdown",
                "markdown": {"content": message}
            },
            timeout=5
        )

        if response.status_code == 200 and response.json().get('errcode') == 0:
            logger.info(f"通知发送成功")
            return True
        else:
            logger.error(f"通知发送失败: {response.text}")
            return False
    except Exception as e:
        logger.error(f"通知发送异常: {e}")
        return False


def get_operator_stats():
    """
    按运营分组统计异常运单

    返回:
        {
            '张三': {
                'wx_url': 'http://...',
                'uncollected': {3: [{'track_no': '...', 'stale_hours': 96, ...}], 5: [...]},
                'exclude_uncollected': {3: [...], 5: [...]}
            },
            '李四': {...}
        }
    """
    logger.info("开始统计异常运单数据...")

    # 基础查询：只查询ops_name不为空且未取消的运单
    base_query = Tracking.objects.filter(
        cancel_bool=False,  # 🔴 排除已取消的运单
        ops_name__isnull=False
    ).exclude(
        ops_name=''  # 排除空字符串
    ).exclude(
        transit_status__in=['DELIVERED', 'EXPIRED']  # 排除已签收和已过期
    )

    operator_stats = {}

    # ===== 处理未揽收筛选 =====
    logger.info(f"处理未揽收状态: {UNCOLLECTED_STATUSES}")
    for days in UNCOLLECTED_DAYS:
        hours_threshold = days * 24
        logger.info(f"查询超过{days}天({hours_threshold}小时)未揽收的运单...")

        tracks = base_query.filter(
            transit_status__in=UNCOLLECTED_STATUSES,
            last_update_time__lte=timezone.now() - timedelta(hours=hours_threshold)
        ).values(
            'track_no', 'ops_name', 'transit_status',
            'courier__name_cn', 'order_id', 'last_update_time'
        )

        track_count = tracks.count()
        logger.info(f"查询到 {track_count} 个符合条件的运单")

        for track in tracks:
            ops_name = track['ops_name']
            if ops_name not in operator_stats:
                operator_stats[ops_name] = {
                    'wx_url': None,
                    'uncollected': {d: [] for d in UNCOLLECTED_DAYS},
                    'exclude_uncollected': {d: [] for d in EXCLUDE_UNCOLLECTED_DAYS}
                }

            stale_hours = calculate_stale_hours(track['last_update_time'])
            operator_stats[ops_name]['uncollected'][days].append({
                'track_no': track['track_no'],
                'stale_hours': stale_hours,
                'status': track['transit_status'],
                'courier': track['courier__name_cn'] or '-',
                'order_id': track['order_id'] or '-'
            })

    # ===== 处理排除未揽收筛选 =====
    logger.info("处理排除未揽收后的其他状态...")
    for days in EXCLUDE_UNCOLLECTED_DAYS:
        hours_threshold = days * 24
        logger.info(f"查询排除未揽收后超过{days}天({hours_threshold}小时)的运单...")

        tracks = base_query.exclude(
            transit_status__in=UNCOLLECTED_STATUSES
        ).filter(
            last_update_time__lte=timezone.now() - timedelta(hours=hours_threshold)
        ).values(
            'track_no', 'ops_name', 'transit_status',
            'courier__name_cn', 'order_id', 'last_update_time'
        )

        track_count = tracks.count()
        logger.info(f"查询到 {track_count} 个符合条件的运单")

        for track in tracks:
            ops_name = track['ops_name']
            if ops_name not in operator_stats:
                operator_stats[ops_name] = {
                    'wx_url': None,
                    'uncollected': {d: [] for d in UNCOLLECTED_DAYS},
                    'exclude_uncollected': {d: [] for d in EXCLUDE_UNCOLLECTED_DAYS}
                }

            stale_hours = calculate_stale_hours(track['last_update_time'])
            operator_stats[ops_name]['exclude_uncollected'][days].append({
                'track_no': track['track_no'],
                'stale_hours': stale_hours,
                'status': track['transit_status'],
                'courier': track['courier__name_cn'] or '-',
                'order_id': track['order_id'] or '-'
            })

    # ===== 获取企业微信通知地址 =====
    ops_names = list(operator_stats.keys())
    logger.info(f"正在获取以下运营人员的通知地址: {ops_names}")

    users = User.objects.filter(first_name__in=ops_names).values('first_name', 'wx_url')
    user_count = users.count()
    logger.info(f"找到 {user_count} 个匹配的用户")

    for user in users:
        ops_name = user['first_name']
        if ops_name in operator_stats:
            operator_stats[ops_name]['wx_url'] = user['wx_url']
            logger.info(f"运营 {ops_name} 的通知地址: {user['wx_url'] or '未配置'}")

    # 过滤掉没有wx_url的运营
    final_stats = {k: v for k, v in operator_stats.items() if v.get('wx_url')}

    logger.info(f"统计完成，共有 {len(final_stats)} 个运营可接收通知")
    return final_stats


def execute_tracking_notification():
    """主执行函数（同步版）"""
    logger.info("=" * 50)
    logger.info("开始执行物流异常通知任务...")
    logger.info("=" * 50)

    # 获取统计数据
    operator_stats = get_operator_stats()

    if not operator_stats:
        logger.info("暂无异常运单需要通知")
        return

    logger.info(f"检测到 {len(operator_stats)} 个运营有异常运单需要通知")

    # 逐个发送通知
    success_count = 0
    total_count = 0

    for ops_name, stats in operator_stats.items():
        wx_url = stats['wx_url']
        total_count += 1

        logger.info(f"准备通知运营 {ops_name}...")

        # 过滤掉空的数据
        uncollected_filtered = {k: v for k, v in stats['uncollected'].items() if v}
        exclude_filtered = {k: v for k, v in stats['exclude_uncollected'].items() if v}

        if not uncollected_filtered and not exclude_filtered:
            logger.info(f"运营 {ops_name} 没有符合条件的异常运单，跳过")
            continue

        # 构建消息
        message = build_notification_message(
            ops_name,
            uncollected_filtered,
            exclude_filtered
        )
        print(message)
        # 发送通知
        logger.info(f"正在向 {ops_name} 发送通知...")
        success = send_wechat_notification(wx_url, message)

        if success:
            success_count += 1
            logger.info(f"通知 {ops_name} 成功")
        else:
            logger.error(f"通知 {ops_name} 失败")

    logger.info("=" * 50)
    logger.info(f"通知任务完成：成功 {success_count}/{total_count} 个")
    logger.info("=" * 50)


if __name__ == '__main__':
    # 手动执行入口
    try:
        execute_tracking_notification()
        logger.info("脚本执行完成")
    except Exception as e:
        logger.error(f"脚本执行失败: {e}", exc_info=True)
        sys.exit(1)