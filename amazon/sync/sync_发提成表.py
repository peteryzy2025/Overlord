import os
import sys
import django
import requests
import openpyxl
import random
import time
from pathlib import Path
from tqdm import tqdm
import logging

# ========== Django环境初始化 ==========
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
sys.path.append(PROJECT_ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Overlord.settings")
django.setup()

# ==================== 配置区域 ====================
# 测试模式开关：True=发送到测试群，False=发送到真实用户
TEST_MODE = True
TEST_WEBHOOK_URL = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=b1f40747-a641-4886-b81d-a998f5e9095a"

# 源Excel文件路径
SOURCE_FILE = r"D:\Y-Project\other\财务-提成表\亚马逊运营汇总利润提成-12月 - 确认版.xlsx"
# 拆分后文件存放目录
OUTPUT_DIR = r"D:\Y-Project\other\财务-提成表\亚马逊运营汇总利润提成-12月 - 确认版"

# 月份配置（可根据实际情况修改）
MONTH_DISPLAY = "2025年12月"

# 随机问候语列表
GREETING_TEMPLATES = [
    "Hi {name}，{month}提成表来啦！{random_msg}",
]

RANDOM_MESSAGES = [
    "请注意查收！",
    "记得核对哦！",
    "祝你业绩长虹！",
    "继续加油，继续爆单！",
    "数据亮眼，再接再厉！",
    "辛苦啦，喝杯咖啡休息一下~",
    "恭喜发财，红包拿来！",
    "天天爆单，月月超额！"
]

# 企业微信API配置
MAX_RETRIES = 20  # 最大重试次数
RETRY_DELAY = 10  # 限流时等待秒数
RATE_LIMIT_CODE = 45009  # 企业微信限流错误码

# 日志配置
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
# ==================================================

from general.models import User


def copy_cell_style(source_cell, target_cell):
    """复制单元格样式"""
    if source_cell.has_style:
        target_cell.font = source_cell.font.copy()
        target_cell.border = source_cell.border.copy()
        target_cell.fill = source_cell.fill.copy()
        target_cell.number_format = source_cell.number_format
        target_cell.protection = source_cell.protection.copy()
        target_cell.alignment = source_cell.alignment.copy()


def send_with_retry(send_func, *args, **kwargs):
    """
    统一重试包装器：处理企业微信限流问题
    :param send_func: 要执行的函数（send_text_message 或 send_file_to_wechat）
    :param args: 函数的位置参数
    :param kwargs: 函数的关键字参数
    :return: (success: bool, result: any)
    """
    retry_count = 0

    while retry_count < MAX_RETRIES:
        try:
            result = send_func(*args, **kwargs)

            # 如果发送成功，直接返回
            if result:
                return True, result

        except requests.exceptions.RequestException as e:
            # 网络请求异常也重试
            logger.warning(f"网络异常: {str(e)}, 第{retry_count + 1}次重试...")
        except Exception as e:
            # 其他异常检查是否是限流错误
            error_str = str(e)
            if f'"errcode":{RATE_LIMIT_CODE}' in error_str or '"errcode": 45009' in error_str:
                retry_count += 1
                logger.warning(
                    f"触发限流(45009)，等待{RETRY_DELAY}秒后重试... "
                    f"(第{retry_count}/{MAX_RETRIES}次)"
                )
                time.sleep(RETRY_DELAY)
                continue
            else:
                # 非限流错误，直接报错返回
                logger.error(f"发送失败: {error_str}")
                return False, None

        # 如果不是限流错误但返回False，也直接返回
        if retry_count == 0:
            return False, None

    # 超过最大重试次数
    logger.error(f"❌ 达到最大重试次数({MAX_RETRIES}次)，发送失败！")
    return False, None


def send_text_message(webhook_url, text_content, sender_name=""):
    """
    发送文本消息到企业微信（内部函数，由send_with_retry包装）
    """
    message = {
        "msgtype": "text",
        "text": {"content": text_content}
    }

    resp = requests.post(webhook_url, json=message, timeout=30)

    if resp.status_code == 200:
        result = resp.json()
        if result.get('errcode') == 0:
            logger.info(f"💬 文本消息发送成功: {sender_name}")
            return True
        elif result.get('errcode') == RATE_LIMIT_CODE:
            # 触发限流，抛出异常让外层捕获
            raise Exception(f'"errcode":{RATE_LIMIT_CODE} - {result}')
        else:
            logger.error(f"文本消息API返回错误: {result}")
            return False
    else:
        logger.error(f"文本消息HTTP请求失败: {resp.status_code} - {resp.text}")
        return False


def send_file_to_wechat(file_path, webhook_url, sender_name=""):
    """
    发送文件到企业微信（内部函数，由send_with_retry包装）
    """
    if not os.path.exists(file_path):
        logger.error(f"文件不存在: {file_path}")
        return False

    file_size = os.path.getsize(file_path) / (1024 * 1024)
    if file_size > 20:
        logger.error(f"文件超过20MB限制: {file_path} ({file_size:.2f}MB)")
        return False

    # Step 1: 上传文件获取media_id
    key = webhook_url.split('key=')[-1]
    upload_url = f"https://qyapi.weixin.qq.com/cgi-bin/webhook/upload_media?key={key}&type=file"

    with open(file_path, 'rb') as f:
        files = {'file': (os.path.basename(file_path), f)}
        upload_resp = requests.post(upload_url, files=files, timeout=30)

    if upload_resp.status_code != 200:
        logger.error(f"文件上传失败: {upload_resp.text}")
        return False

    upload_result = upload_resp.json()
    if upload_result.get('errcode') != 0:
        logger.error(f"上传API返回错误: {upload_result}")
        return False

    media_id = upload_result['media_id']

    # Step 2: 发送文件消息
    message = {"msgtype": "file", "file": {"media_id": media_id}}
    send_resp = requests.post(webhook_url, json=message, timeout=30)

    if send_resp.status_code == 200:
        result = send_resp.json()
        if result.get('errcode') == 0:
            logger.info(f"✅ 文件发送成功: {sender_name} <- {os.path.basename(file_path)}")
            return True
        elif result.get('errcode') == RATE_LIMIT_CODE:
            # 触发限流，抛出异常让外层捕获
            raise Exception(f'"errcode":{RATE_LIMIT_CODE} - {result}')
        else:
            logger.error(f"发送API返回错误: {result}")
            return False
    else:
        logger.error(f"发送HTTP请求失败: {send_resp.status_code} - {send_resp.text}")
        return False


def get_greeting_message(name, is_leader=False, is_total=False):
    """
    生成个性化问候语
    """
    if is_total:
        return f"管理员您好！这是{MONTH_DISPLAY}的提成总表，包含全体成员的详细数据。请查收！祝工作顺利，万事如意！🎉"

    template = random.choice(GREETING_TEMPLATES)
    random_msg = random.choice(RANDOM_MESSAGES)

    if is_leader:
        return f"{template.format(name=name, month=MONTH_DISPLAY, random_msg=random_msg)}\n\n📊 文件中包含您和组员的完整提成数据，请查收！"
    else:
        return f"{template.format(name=name, month=MONTH_DISPLAY, random_msg=random_msg)}"


def get_group_structure():
    """
    获取组结构：{组名: {leader: 组长对象, members: [所有成员列表]}}
    """
    group_structure = {}
    wb = openpyxl.load_workbook(SOURCE_FILE, read_only=True)
    all_sheets = set(wb.sheetnames)
    wb.close()

    print(f"[INFO] 源文件包含的sheet: {', '.join(sorted(all_sheets))}")

    group_leaders = User.objects.filter(role='运营组长').select_related('operational_account')

    for leader in group_leaders:
        ops_group = leader.get_ops_group()
        if not ops_group:
            continue

        group_members = User.objects.filter(
            operational_account__ops_group=ops_group
        ).select_related('operational_account')

        if not group_members.exists():
            continue

        # 过滤出有对应sheet的成员
        member_names = [m.first_name for m in group_members]
        existing_sheets = all_sheets.intersection(member_names)

        if not existing_sheets:
            logger.warning(f"⚠️ 分组 {ops_group} 无任何成员sheet，跳过")
            continue

        valid_members = [m for m in group_members if m.first_name in existing_sheets]

        group_structure[ops_group] = {
            'leader': leader,
            'members': valid_members
        }

        print(f"[INFO] 分组 {ops_group}: 组长={leader.first_name}, 有效成员={len(valid_members)}")

    return group_structure


def split_excel_by_groups(group_structure):
    """
    按组切表：组长文件包含全组sheet，组员文件只包含自己
    """
    print(f"\n{'=' * 80}")
    print("阶段1: 开始按组拆分Excel表格")
    print(f"{'=' * 80}")

    if not group_structure:
        return False

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    try:
        source_wb = openpyxl.load_workbook(SOURCE_FILE)
        total_files_created = 0

        for ops_group, group_data in tqdm(group_structure.items(), desc="切表进度", unit="组"):
            leader = group_data['leader']
            members = group_data['members']

            if not members:
                continue

            # ========== 1. 切组长文件（包含全组成员的sheet）==========
            leader_file = os.path.join(OUTPUT_DIR, f"{leader.first_name}.xlsx")
            leader_wb = openpyxl.Workbook()
            default_sheet = leader_wb.active
            leader_wb.remove(default_sheet)

            for member in members:
                member_name = member.first_name
                if member_name not in source_wb.sheetnames:
                    continue

                source_ws = source_wb[member_name]
                new_ws = leader_wb.create_sheet(title=member_name)

                for row in source_ws.iter_rows(values_only=False):
                    for cell in row:
                        new_cell = new_ws.cell(row=cell.row, column=cell.column, value=cell.value)
                        copy_cell_style(cell, new_cell)

                for col_letter, column_dim in source_ws.column_dimensions.items():
                    new_ws.column_dimensions[col_letter].width = column_dim.width
                for row_idx, row_dim in source_ws.row_dimensions.items():
                    new_ws.row_dimensions[row_idx].height = row_dim.height

            leader_wb.save(leader_file)
            leader_wb.close()
            total_files_created += 1
            logger.info(f"✅ 组长文件: {leader.first_name}.xlsx (含{len(members)}个sheet)")

            # ========== 2. 切组员文件（只包含自己的sheet）==========
            for member in members:
                if member.id == leader.id:
                    continue

                member_name = member.first_name
                if member_name not in source_wb.sheetnames:
                    continue

                member_file = os.path.join(OUTPUT_DIR, f"{member_name}.xlsx")
                member_wb = openpyxl.Workbook()
                default_sheet = member_wb.active
                member_wb.remove(default_sheet)

                source_ws = source_wb[member_name]
                new_ws = member_wb.create_sheet(title=member_name)

                for row in source_ws.iter_rows(values_only=False):
                    for cell in row:
                        new_cell = new_ws.cell(row=cell.row, column=cell.column, value=cell.value)
                        copy_cell_style(cell, new_cell)

                for col_letter, column_dim in source_ws.column_dimensions.items():
                    new_ws.column_dimensions[col_letter].width = column_dim.width
                for row_idx, row_dim in source_ws.row_dimensions.items():
                    new_ws.row_dimensions[row_idx].height = row_dim.height

                member_wb.save(member_file)
                member_wb.close()
                total_files_created += 1

        source_wb.close()
        print(f"\n✅ 切表完成！共创建 {total_files_created} 个文件")
        return True

    except Exception as e:
        logger.error(f"❌ 切表错误: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def send_total_file_to_admin():
    """
    单独发送总表给管理员（id=1的用户）
    """
    print(f"\n{'=' * 80}")
    print("阶段3: 发送总表给管理员")
    print(f"{'=' * 80}")

    try:
        admin = User.objects.get(id=1)
        webhook_url = TEST_WEBHOOK_URL if TEST_MODE else admin.wx_url

        if not webhook_url:
            logger.error("❌ 管理员未设置wx_url，无法发送总表")
            return

        total_file = SOURCE_FILE

        if not os.path.exists(total_file):
            logger.error(f"❌ 总表文件不存在: {total_file}")
            return

        # 发送问候语
        greeting = get_greeting_message(admin.first_name, is_total=True)
        success, _ = send_with_retry(send_text_message, webhook_url, greeting, f"管理员-{admin.first_name}")

        if not success:
            logger.error(f"❌ 管理员问候语发送失败，跳过文件发送")
            return

        # 发送文件
        logger.info(f"\n🎯 发送总表给管理员: {admin.first_name}")
        send_with_retry(send_file_to_wechat, total_file, webhook_url, f"管理员-{admin.first_name}")

    except User.DoesNotExist:
        logger.error("❌ 未找到id=1的管理员用户")
    except Exception as e:
        logger.error(f"发送总表异常: {str(e)}")


def send_files_to_users(group_structure):
    """
    发送文件给所有运营组长和成员
    """
    print(f"\n{'=' * 80}")
    print("阶段2: 开始发送文件到企业微信")
    print(f"测试模式: {'✅ 启用' if TEST_MODE else '❌ 禁用'}")
    print(f"{'=' * 80}")

    # 遍历每个组
    for ops_group, group_data in group_structure.items():
        leader = group_data['leader']
        members = group_data['members']

        if not members:
            continue

        # 1. 发送组长文件（包含全组）
        webhook_url = TEST_WEBHOOK_URL if TEST_MODE else leader.wx_url
        if not webhook_url:
            logger.warning(f"⚠️ 组长 {leader.first_name} 未设置wx_url，跳过")
        else:
            leader_file = os.path.join(OUTPUT_DIR, f"{leader.first_name}.xlsx")
            if os.path.exists(leader_file):
                # 发送问候语（带重试）
                greeting = get_greeting_message(leader.first_name, is_leader=True)
                success, _ = send_with_retry(
                    send_text_message,
                    webhook_url,
                    greeting,
                    f"组长-{leader.first_name}"
                )

                if success:
                    # 发送文件（带重试）
                    logger.info(f"\n🎯 发送给组长: {leader.first_name} (全组文件)")
                    send_with_retry(
                        send_file_to_wechat,
                        leader_file,
                        webhook_url,
                        f"组长-{leader.first_name}"
                    )
                else:
                    logger.error(f"❌ 组长 {leader.first_name} 的问候语发送失败，跳过文件")
            else:
                logger.error(f"❌ 组长文件不存在: {leader_file}")

        # 2. 发送组员文件
        for member in members:
            if member.id == leader.id:
                continue

            webhook_url = TEST_WEBHOOK_URL if TEST_MODE else member.wx_url
            if not webhook_url:
                logger.warning(f"⚠️ 组员 {member.first_name} 未设置wx_url，跳过")
                continue

            member_file = os.path.join(OUTPUT_DIR, f"{member.first_name}.xlsx")
            if os.path.exists(member_file):
                # 发送问候语（带重试）
                greeting = get_greeting_message(member.first_name, is_leader=False)
                success, _ = send_with_retry(
                    send_text_message,
                    webhook_url,
                    greeting,
                    f"组员-{member.first_name}"
                )

                if success:
                    # 发送文件（带重试）
                    logger.info(f"\n→ 发送给组员: {member.first_name}")
                    send_with_retry(
                        send_file_to_wechat,
                        member_file,
                        webhook_url,
                        f"组员-{member.first_name}"
                    )
                else:
                    logger.error(f"❌ 组员 {member.first_name} 的问候语发送失败，跳过文件")
            else:
                logger.warning(f"⚠️ 组员文件不存在: {member_file}")


def main():
    """
    主函数：先构建组结构，再切表，然后发送给用户，最后发送总表给管理员
    """
    print("\n" + "=" * 100)
    print("财务提成表自动拆分与发送系统 [完整版]")
    print("=" * 100)

    # 1. 获取组结构
    group_structure = get_group_structure()
    if not group_structure:
        logger.error("❌ 没有可用的分组结构，终止执行")
        return

    print(f"\n[INFO] 共加载 {len(group_structure)} 个有效分组")

    # 2. 按组切表
    success = split_excel_by_groups(group_structure)
    if not success:
        logger.error("❌ 切表失败，终止执行")
        return

    # 3. 发送给用户
    send_files_to_users(group_structure)

    # 4. 单独发送总表给管理员（id=1）
    send_total_file_to_admin()

    print("\n" + "=" * 100)
    print("执行完成！")
    print("=" * 100)


if __name__ == '__main__':
    main()