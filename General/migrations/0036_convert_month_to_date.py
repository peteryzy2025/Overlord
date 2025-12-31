from django.db import migrations, models
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


def convert_char_to_date(apps, schema_editor):
    """将 CharField 的 YYYY-MM 格式转换为 DateField"""
    GroupPerformanceTarget = apps.get_model('General', 'GroupPerformanceTarget')
    PersonalPerformanceTarget = apps.get_model('General', 'PersonalPerformanceTarget')

    # 处理组绩效目标
    for target in GroupPerformanceTarget.objects.all().iterator():
        if target.month_old and isinstance(target.month_old, str):
            try:
                # 转换 YYYY-MM 到 YYYY-MM-01
                date_obj = datetime.strptime(target.month_old, '%Y-%m').date()
                target.month = date_obj
                target.save(update_fields=['month'])
            except ValueError as e:
                logger.warning(f"组绩效目标 ID {target.id} 的月份格式无效: {target.month_old}, 错误: {e}")

    # 处理个人绩效目标
    for target in PersonalPerformanceTarget.objects.all().iterator():
        if target.month_old and isinstance(target.month_old, str):
            try:
                date_obj = datetime.strptime(target.month_old, '%Y-%m').date()
                target.month = date_obj
                target.save(update_fields=['month'])
            except ValueError as e:
                logger.warning(f"个人绩效目标 ID {target.id} 的月份格式无效: {target.month_old}, 错误: {e}")


class Migration(migrations.Migration):
    # ⚠️⚠️⚠️ 务必修改为实际的上一版迁移文件名 ⚠️⚠️⚠️
    dependencies = [
        ('General', '0035_alter_announcement_valid_to'),  # ← 改成你的实际文件名，不要.py
    ]

    operations = [
        # 1. 临时移除唯一约束（必须先做，避免后续操作冲突）
        migrations.AlterUniqueTogether(
            name='groupperformancetarget',
            unique_together=set(),
        ),
        migrations.AlterUniqueTogether(
            name='personalperformancetarget',
            unique_together=set(),
        ),

        # 2. 重命名字段：month → month_old
        migrations.RenameField(
            model_name='groupperformancetarget',
            old_name='month',
            new_name='month_old',
        ),
        migrations.RenameField(
            model_name='personalperformancetarget',
            old_name='month',
            new_name='month_old',
        ),

        # 3. 创建新字段 month (DateField)
        migrations.AddField(
            model_name='groupperformancetarget',
            name='month',
            field=models.DateField(null=True, blank=True, verbose_name='目标月份'),
        ),
        migrations.AddField(
            model_name='personalperformancetarget',
            name='month',
            field=models.DateField(null=True, blank=True, verbose_name='目标月份'),
        ),

        # 4. 从旧字段转换数据到新字段
        migrations.RunPython(convert_char_to_date, reverse_code=migrations.RunPython.noop),

        # 5. 删除旧字段 month_old
        migrations.RemoveField(
            model_name='groupperformancetarget',
            name='month_old',
        ),
        migrations.RemoveField(
            model_name='personalperformancetarget',
            name='month_old',
        ),

        # 6. 恢复唯一约束（必须在新字段创建完成后）
        migrations.AlterUniqueTogether(
            name='groupperformancetarget',
            unique_together={('ops_group', 'month')},
        ),
        migrations.AlterUniqueTogether(
            name='personalperformancetarget',
            unique_together={('user', 'month')},
        ),

        # 7. 创建索引
        migrations.AddIndex(
            model_name='groupperformancetarget',
            index=models.Index(fields=['month', 'ops_group'], name='group_perf_month_ops_group_idx'),
        ),
        migrations.AddIndex(
            model_name='personalperformancetarget',
            index=models.Index(fields=['month', 'ops_group'], name='personal_perf_month_ops_group_idx'),
        ),
        migrations.AddIndex(
            model_name='personalperformancetarget',
            index=models.Index(fields=['user', 'month'], name='personal_perf_user_month_idx'),
        ),
    ]