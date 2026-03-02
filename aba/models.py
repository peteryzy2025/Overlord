from django.db import models


class SearchTerm(models.Model):
    """
    搜索词维度表（去重，内存缓存）
    6亿条记录如果都存字符串会爆炸，单独一张表只需约20MB
    """
    term = models.CharField(
        max_length=500,
        unique=True,
        db_index=True,
        verbose_name="搜索词"
    )
    category = models.CharField(
        max_length=100,
        blank=True,
        verbose_name="品类"
    )
    first_seen = models.DateField(
        verbose_name="首次出现周"
    )
    last_seen = models.DateField(
        verbose_name="最后更新周"
    )

    class Meta:
        db_table = 'search_terms'
        verbose_name = "搜索词"
        verbose_name_plural = "搜索词"


class SearchTermMetric(models.Model):
    """
    搜索词周表现数据（事实大表）
    - 6亿级数据，必须按年分区（PostgreSQL原生分区）
    - ASIN信息平铺存储（空间换时间，避免JOIN）
    - 包含环比预计算字段（避免实时计算）
    """
    # 分区键：直接存日期，不依赖外键（减少JOIN）
    report_week = models.DateField(
        verbose_name="数据周",
        db_index=True,
        help_text="格式：2026-02-15（周日），作为分区键"
    )

    # 关联搜索词（唯一外键，内存缓存快）
    search_term = models.ForeignKey(
        SearchTerm,
        on_delete=models.CASCADE,
        db_index=True,
        verbose_name="搜索词"
    )

    # 排名信息
    search_frequency_rank = models.IntegerField(
        verbose_name="搜索频率排名",
        db_index=True
    )

    # ASIN 1（点击份额最高）
    asin_1_code = models.CharField(
        max_length=20,
        db_index=True,
        verbose_name="ASIN-1"
    )
    asin_1_title = models.TextField(
        verbose_name="标题-1"
    )
    asin_1_click_share = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        verbose_name="点击份额-1"
    )
    asin_1_conversion_share = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        verbose_name="转化份额-1"
    )

    # ASIN 2（可能为空）
    asin_2_code = models.CharField(
        max_length=20,
        blank=True,
        verbose_name="ASIN-2"
    )
    asin_2_title = models.TextField(
        blank=True,
        verbose_name="标题-2"
    )
    asin_2_click_share = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        null=True,
        blank=True,
        verbose_name="点击份额-2"
    )
    asin_2_conversion_share = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        null=True,
        blank=True,
        verbose_name="转化份额-2"
    )

    # ASIN 3（可能为空）
    asin_3_code = models.CharField(
        max_length=20,
        blank=True,
        verbose_name="ASIN-3"
    )
    asin_3_title = models.TextField(
        blank=True,
        verbose_name="标题-3"
    )
    asin_3_click_share = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        null=True,
        blank=True,
        verbose_name="点击份额-3"
    )
    asin_3_conversion_share = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        null=True,
        blank=True,
        verbose_name="转化份额-3"
    )

    # 环比数据（导入时预计算，避免查询时实时算）
    last_week_rank = models.IntegerField(
        null=True,
        blank=True,
        verbose_name="上周排名"
    )
    rank_change = models.IntegerField(
        null=True,
        blank=True,
        verbose_name="排名变化",
        help_text="正数表示上升（如+5），负数表示下降（如-3）"
    )

    class Meta:
        db_table = 'search_term_metrics'
        verbose_name = "搜索词周数据"
        verbose_name_plural = "搜索词周数据"

        # 关键：Django不管理这张表（因为需要手动分区）
        managed = False

        # 联合唯一约束：防止同一周同一搜索词重复导入
        unique_together = [['report_week', 'search_term']]

        # SSD优化索引
        indexes = [
            # 查某周排行榜（最常用）
            models.Index(
                fields=['report_week', 'search_frequency_rank'],
                name='week_rank_idx'
            ),
            # 查某个搜索词的历史趋势（画折线图）
            models.Index(
                fields=['search_term', 'report_week'],
                name='term_trend_idx'
            ),
            # 反查：某个ASIN出现在哪些热搜词下
            models.Index(
                fields=['asin_1_code', 'report_week'],
                name='asin_week_idx'
            ),
        ]