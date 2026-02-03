from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import AmazonThemeNovelty, ThemeReport

@receiver(post_save, sender=AmazonThemeNovelty)
def sync_report_status_signal(sender, instance, created, **kwargs):
    """
    当 AmazonThemeNovelty 保存时，检查该 subject 是否已被举报。
    如果是，则将举报状态同步到当前产品。
    """
    if not instance.subject:
        return

    # 查找针对相同 subject 的有效举报人
    # 逻辑：查找所有 subject 相同且 is_active=True 的 ThemeReport
    # 排除当前产品自身的举报记录（避免不必要的查询，虽然这里是找 reporter）
    active_reporters = ThemeReport.objects.filter(
        product__subject=instance.subject,
        is_active=True
    ).exclude(
        product=instance
    ).values_list('reporter', flat=True).distinct()

    if not active_reporters:
        return

    # 为当前产品创建举报记录
    new_reports = []
    for reporter_id in active_reporters:
        # 检查是否已经存在该 reporter 对当前产品的举报
        if not ThemeReport.objects.filter(product=instance, reporter_id=reporter_id).exists():
            new_reports.append(ThemeReport(
                product=instance,
                reporter_id=reporter_id,
                is_active=True
            ))

    if new_reports:
        ThemeReport.objects.bulk_create(new_reports)
        print(f"Synced {len(new_reports)} report(s) for ASIN {instance.asin} (Subject: {instance.subject})")
