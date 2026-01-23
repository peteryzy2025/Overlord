from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('theme', '0007_rename_theme_trade_word_ma_8b78a9_idx_theme_trade_word_ma_31ebb4_idx_and_more'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            # 数据库啥也不做（因为你的列名已经是对的）
            database_operations=[],

            # 只更新Django的模型状态
            state_operations=[
                # 更新 legal_entity_type 字段状态
                migrations.AlterField(
                    model_name='trademarkinfo',
                    name='legal_entity_type',
                    field=models.ForeignKey(
                        to='theme.entitytypemapping',
                        to_field='code',
                        db_column='legal_entity_type',
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name='trademark_entities',
                        verbose_name='法律实体类型',
                        null=True,
                        blank=True,
                    ),
                ),
                # 更新 mark_drawing_type 字段状态
                migrations.AlterField(
                    model_name='trademarkinfo',
                    name='mark_drawing_type',
                    field=models.ForeignKey(
                        to='theme.markdrawingtypemapping',
                        to_field='code',
                        db_column='mark_drawing_type',
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name='trademarks',
                        verbose_name='商标绘制类型',
                        null=True,
                        blank=True,
                    ),
                ),
                # 更新 status_code 字段状态
                migrations.AlterField(
                    model_name='trademarkinfo',
                    name='status_code',
                    field=models.ForeignKey(
                        to='theme.statuscodemapping',
                        to_field='status_code',
                        db_column='status_code',
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name='trademarks',
                        verbose_name='商标状态码',
                        null=True,
                        blank=True,
                    ),
                ),
                # 删除旧的索引（如果存在）
                migrations.RemoveIndex(
                    model_name='trademarkinfo',
                    name='theme_trade_word_ma_8b78a9_idx',
                ),
                migrations.RemoveIndex(
                    model_name='trademarkinfo',
                    name='theme_trade_word_ma_d848e9_idx',
                ),
            ],
        )
    ]