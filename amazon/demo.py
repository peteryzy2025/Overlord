import os
import sys
import django

# ====== Django 初始化 ======
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
sys.path.append(PROJECT_ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Overlord.settings")
django.setup()

from django.db.models import Q
from general.models import User, Announcement, UserAnnouncementRead

# ====== 1. 获取所有运营用户（只查一次）======
ops_users = User.objects.filter(role__in=['运营', '运营助理', '运营组长']).only('id', 'first_name', 'role')
ops_user_dict = {u.id: f"{u.first_name}({u.role})" for u in ops_users}
print(f"运营用户总数: {len(ops_user_dict)} 人")

# ====== 2. 遍历所有公告 ======
all_announcements = Announcement.objects.all().order_by('-created_at')

print(f"\n{'=' * 90}")
print(f"共 {all_announcements.count()} 条公告，逐条检查未读运营人员")
print("=" * 90)

# ====== 3. 核心逻辑：找出每个公告的未读运营 ======
for ann in all_announcements:
    # 获取已读此公告的运营用户ID集合
    read_ops_ids = set(
        UserAnnouncementRead.objects.filter(
            announcement=ann,
            user_id__in=ops_user_dict.keys()  # 只查运营用户
        ).values_list('user_id', flat=True)
    )

    # 找出未读的运营
    unread_ops_ids = set(ops_user_dict.keys()) - read_ops_ids

    # 输出结果
    print(f"\n📢 公告ID: {ann.id} | {ann.title}")
    print(f"   发布时间: {ann.created_at.strftime('%Y-%m-%d %H:%M')} | 优先级: {ann.get_priority_display()}")

    if unread_ops_ids:
        print(f"   🔴 未读运营 ({len(unread_ops_ids)}人):")
        # 按姓名排序输出
        unread_names = [ops_user_dict[u] for u in sorted(unread_ops_ids)]
        for name in unread_names:
            print(f"      - {name}")
    else:
        print(f"   ✅ 所有运营均已阅读")

print("\n" + "=" * 90)
print("查询完成！")