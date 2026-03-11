from django.db import migrations, models


def backfill_subtask_status(apps, schema_editor):
    SubTask = apps.get_model('task', 'SubTask')

    valid_statuses = {
        'draft',
        'pending',
        'in_progress',
        'completed',
        'failed',
        'cancelled',
    }

    for subtask in SubTask.objects.select_related('task').all():
        task_status = subtask.task.status
        subtask.subtask_status = task_status if task_status in valid_statuses else 'pending'
        subtask.save(update_fields=['subtask_status'])


class Migration(migrations.Migration):

    dependencies = [
        ('task', '0026_amazonuploadfile'),
    ]

    operations = [
        migrations.AddField(
            model_name='subtask',
            name='subtask_status',
            field=models.CharField(
                choices=[
                    ('draft', '草稿'),
                    ('pending', '待执行'),
                    ('in_progress', '进行中'),
                    ('completed', '已完成'),
                    ('failed', '执行失败'),
                    ('cancelled', '已取消'),
                ],
                db_comment='任务当前状态',
                default='draft',
                max_length=20,
                verbose_name='任务状态',
            ),
        ),
        migrations.RunPython(backfill_subtask_status, migrations.RunPython.noop),
    ]
