import os
import sys
import django
import logging
import random
from datetime import datetime, timedelta

# ========== Django环境初始化 ==========
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(CURRENT_DIR))
sys.path.append(PROJECT_ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Overlord.settings")
django.setup()

# ========== 配置常量 ==========
# 温馨开头列表（字符串模板，运行时替换）
EMAIL_GREETINGS_TEMPLATES = [
    "**📧 邮件小助手呼叫 {operator_name}～**\n\n✨ 发现了一些需要您处理的邮件哦：\n",
    "**【店铺邮件提醒】  {operator_name}，下午好！**\n\n🎯 以下店铺的邮件状态需要您关注：\n",
    "**嗨，{operator_name}，邮件管家来报到 📊**\n\n提醒您及时查看店铺邮件：\n",
    "**📢 邮件小助手温馨提醒**\n\n👋 {operator_name}，您有以下邮件待处理：\n",
    "**Hello {operator_name}，邮件预警中心 🔔**\n\n检测到需要您处理的邮件通知：\n",
    "**⭐ 邮件小助手呼叫 {operator_name}～**\n\n✨ 发现了一些需要您处理的邮件哦：\n",
    "**【店铺邮件提醒】  {operator_name}，上午好！**\n\n🎯 以下店铺的邮件状态需要您关注：\n",
    "**嗨，{operator_name}，邮件管家来提醒 📊**\n\n提醒您及时查看店铺邮件：\n",
    "**📢 邮件小助手温馨提示**\n\n👋 {operator_name}，您有以下邮件待处理：\n",
    "**Hi {operator_name}，邮件管理中心 🔔**\n\n检测到需要您介入的邮件通知：\n"
]

# 积压天数阈值
BACKLOG_DAYS = [3, 7, 15]

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# ========== 导入Django模型 ==========
from django.db.models import Q, Count
from django.utils import timezone
from General.models import User
from Amazon.models import AmazonShopEmail
from Api.WX.wx import send_wechat_work_message


def calculate_backlog_days(receive_time):
    """计算积压天数"""
    if not receive_time:
        return 0
    now = timezone.now()
    try:
        days_diff = (now - receive_time).days
        return max(0, days_diff)
    except:
        return 0


def build_email_notification_message(operator_name, shop_details, total_count, backlog_stats):
    """
    构建邮件通知Markdown消息（完整显示所有标题明细）
    """
    template = random.choice(EMAIL_GREETINGS_TEMPLATES)
    greeting = template.format(operator_name=operator_name)
    lines = [greeting]

    lines.append("\n**📊 待处理邮件通知：**")
    lines.append(f"**待处理店铺数**：{len(shop_details)}个")
    lines.append(f"**待处理邮件总数**：{total_count}封\n")

    # 积压分级显示
    if backlog_stats:
        lines.append("**积压分级**：")
        for days in sorted(backlog_stats.keys()):
            count = backlog_stats[days]
            if count > 0:
                lines.append(f"**超过{days}天**：{count}封")
        lines.append("")

    # 店铺明细 + 完整标题
    if shop_details:
        lines.append("**店铺明细**：")
        for shop in shop_details:
            lines.append(f"- **{shop['shop_name']}（{shop['count']}封）**")
            # 完整显示所有邮件标题
            if shop.get('subjects'):
                for subject in shop['subjects']:
                    lines.append(f"  · {subject}")
            lines.append("")  # 空行分隔

    lines.append("**操作**：请及时登录系统查看并处理")
    return "\n".join(lines)

def get_pending_email_stats():
    """
    获取待处理邮件统计（含标题明细 + 积压分级）
    """
    logger.info("开始统计邮件数据...")

    # 基础查询
    base_query = AmazonShopEmail.objects.filter(
        is_attention_needed=True,
        is_processed=False
    ).exclude(
        shop__ops__first_name__isnull=True
    ).exclude(
        shop__ops__first_name=''
    )

    now = timezone.now()
    operator_stats = {}

    # 获取运营级统计
    ops_data = base_query.values(
        'shop__ops__first_name',
        'shop__ops_id',
        'shop__ops__wx_url',
        'shop__shop_name'
    ).annotate(
        count=Count('id')
    ).order_by('shop__ops__first_name', '-count')

    for item in ops_data:
        ops_name = item['shop__ops__first_name']
        if not ops_name:
            continue

        if ops_name not in operator_stats:
            operator_stats[ops_name] = {
                'wx_url': item['shop__ops__wx_url'],
                'shops': [],
                'total_count': 0,
                'backlog_stats': {3: 0, 7: 0, 15: 0}
            }

        # 获取店铺明细 + 前5条邮件标题
        shop_emails = AmazonShopEmail.objects.filter(
            is_attention_needed=True,
            is_processed=False,
            shop__ops_id=item['shop__ops_id'],
            shop__shop_name=item['shop__shop_name']
        ).values('subject')

        operator_stats[ops_name]['shops'].append({
            'shop_name': item['shop__shop_name'] or '未知店铺',
            'count': item['count'],
            'subjects': [s['subject'] for s in shop_emails]  # 新增：标题列表
        })
        operator_stats[ops_name]['total_count'] += item['count']

    # 计算积压统计
    for ops_name, stats in operator_stats.items():
        for days in BACKLOG_DAYS:
            backlog_count = AmazonShopEmail.objects.filter(
                is_attention_needed=True,
                is_processed=False,
                shop__ops_id=stats['shops'][0].get('ops_id') if stats['shops'] else None,
                receive_time__lte=now - timedelta(days=days)
            ).count()
            operator_stats[ops_name]['backlog_stats'][days] = backlog_count

    # 过滤无wx_url的运营
    final_stats = {
        k: v for k, v in operator_stats.items()
        if v.get('wx_url')
    }

    logger.info(f"统计完成，共有 {len(final_stats)} 个运营需要通知")
    return final_stats

def send_email_notifications(operator_stats):
    """
    发送邮件通知（调用wx.py，内部已处理开发副本）
    """
    success_count = 0
    fail_count = 0
    fail_details = []

    for ops_name, stats in operator_stats.items():
        wx_url = stats['wx_url']
        total_count = stats['total_count']
        shop_details = stats['shops']
        backlog_stats = stats['backlog_stats']

        logger.info(f"准备通知运营 {ops_name}，共{total_count}封邮件待处理...")

        # 构建消息
        message = build_email_notification_message(ops_name, shop_details, total_count, backlog_stats)

        # 发送消息（包含主消息+开发副本）
        logger.info(f"正在向 {ops_name} 发送通知...")
        result = send_wechat_work_message(wx_url, message)

        if result['success']:
            success_count += 1
            logger.info(f"通知 {ops_name} 成功")
        else:
            fail_count += 1
            fail_details.append(f'{ops_name}: {result["error_message"]}')
            logger.error(f"通知 {ops_name} 失败: {result['error_message']}")

    return {
        'success_count': success_count,
        'fail_count': fail_count,
        'fail_details': fail_details
    }


def execute_email_notification():
    """主执行函数"""
    logger.info("=" * 50)
    logger.info("开始执行邮件通知推送任务...")
    logger.info("=" * 50)

    operator_stats = get_pending_email_stats()

    if not operator_stats:
        logger.info("暂无待处理邮件")
        return

    logger.info(f"检测到 {len(operator_stats)} 个运营有待处理邮件")

    result = send_email_notifications(operator_stats)

    logger.info("=" * 50)
    logger.info(f"推送任务完成：成功 {result['success_count']}，失败 {result['fail_count']}")
    if result['fail_details']:
        logger.error(f"失败详情: {result['fail_details']}")
    logger.info("=" * 50)