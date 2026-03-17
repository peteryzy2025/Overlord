from django.db import models


class SearchTerm(models.Model):
    """
    搜索词维度表（必须保留，去重存储）
    50万条 vs 6亿条重复存储，空间差异1.2万倍（20MB vs 240GB）
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
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="创建时间"
    )
    denoising = models.BooleanField(
        default=False,
        verbose_name="是否已降噪",
        help_text="人工标记已降噪的搜索词，后续导入"
    )
    class Meta:
        db_table = 'search_terms'
        verbose_name = "搜索词"
        verbose_name_plural = "搜索词"


class SearchTermMetric(models.Model):
    """
    搜索词周表现数据（事实大表，按年分区）
    - 6亿级数据，PostgreSQL原生分区（RANGE BY report_week）
    - ASIN信息平铺存储（空间换时间，避免大数据量JOIN）
    - Decimal(6,4)确保能存储百分比如12.34%
    - 环比数据预计算（避免查询时实时计算）
    """
    # 分区键：数据所属周（周日日期，如2026-02-15）
    report_week = models.DateField(
        verbose_name="数据周",
        db_index=True,
        help_text="格式：YYYY-MM-DD（周日），作为分区键"
    )
    
    # 外键关联：指向SearchTerm（非分区表，内存缓存，JOIN无压力）
    search_term = models.ForeignKey(
        SearchTerm,
        on_delete=models.CASCADE,
        db_index=True,
        verbose_name="搜索词"
    )
    
    # 搜索排名
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
    # 修正：max_digits=6才能存下12.34%（原5位最大只能存9.9999）
    asin_1_click_share = models.DecimalField(
        max_digits=6, 
        decimal_places=4,
        verbose_name="点击份额-1"
    )
    asin_1_conversion_share = models.DecimalField(
        max_digits=6, 
        decimal_places=4,
        verbose_name="转化份额-1"
    )
    
    # ASIN 2（点击份额第二，可能为空）
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
        max_digits=6, 
        decimal_places=4,
        null=True, 
        blank=True,
        verbose_name="点击份额-2"
    )
    asin_2_conversion_share = models.DecimalField(
        max_digits=6, 
        decimal_places=4,
        null=True, 
        blank=True,
        verbose_name="转化份额-2"
    )
    
    # ASIN 3（点击份额第三，可能为空）
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
        max_digits=6, 
        decimal_places=4,
        null=True, 
        blank=True,
        verbose_name="点击份额-3"
    )
    asin_3_conversion_share = models.DecimalField(
        max_digits=6, 
        decimal_places=4,
        null=True, 
        blank=True,
        verbose_name="转化份额-3"
    )
    
    # 环比预计算字段（导入时计算，避免查询时跨周JOIN）
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
    
    # 数据追踪（可选，有助于排查问题）
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="记录创建时间"
    )
    
    class Meta:
        db_table = 'search_term_metrics'
        verbose_name = "搜索词周数据"
        verbose_name_plural = "搜索词周数据"
        
        # 关键：Django不管理这张表，因为需要手动创建分区
        managed = False
        
        # 联合唯一约束：防止同一周同一搜索词重复导入
        unique_together = [['report_week', 'search_term']]
        
        # SSD优化索引（分区表会自动应用到各子分区）
        indexes = [
            # 查询1：查某周排行榜（最常用，配合LIMIT 50）
            models.Index(
                fields=['report_week', 'search_frequency_rank'], 
                name='week_rank_idx'
            ),
            # 查询2：查某个搜索词的历史趋势（画折线图）
            models.Index(
                fields=['search_term', 'report_week'], 
                name='term_trend_idx'
            ),
            # 查询3：反查ASIN出现在哪些热搜词下
            models.Index(
                fields=['asin_1_code', 'report_week'], 
                name='asin_week_idx'
            ),
        ]

class AbaReportWeek(models.Model):
    report_week = models.DateField(
        unique=True,
        db_index=True,
        verbose_name="数据周"
    )
    display_label = models.CharField(
        max_length=64,
        verbose_name="展示文案"
    )
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        verbose_name="是否启用"
    )
    import_status = models.CharField(
        max_length=20,
        default='ready',
        db_index=True,
        verbose_name="导入状态"
    )
    record_count = models.IntegerField(
        default=0,
        verbose_name="数据条数"
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="创建时间"
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="更新时间"
    )

    class Meta:
        db_table = 'aba_report_weeks'
        verbose_name = "ABA数据周期"
        verbose_name_plural = "ABA数据周期"
        ordering = ['-report_week']