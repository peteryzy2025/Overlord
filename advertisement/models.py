from django.db import models
from django.db.models import Sum


class LingXingCampaign(models.Model):
    """
    Campaign 维度表（缓慢变化维）
    存储广告活动的元数据，与事实表一对多
    """

    # ========== 枚举类定义 ==========
    class CampaignType(models.TextChoices):
        SP = 'SP', 'SP（商品推广）'
        SB = 'SB', 'SB（品牌推广）'
        SD = 'SD', 'SD（展示型推广）'

    class Status(models.TextChoices):
        ENABLED = 'enabled', '启用'
        PAUSED = 'paused', '暂停'
        ARCHIVED = 'archived', '归档'

    class ServingStatus(models.TextChoices):
        CAMPAIGN_PAUSED = 'CAMPAIGN_PAUSED', '活动暂停'
        CAMPAIGN_STATUS_ENABLED = 'CAMPAIGN_STATUS_ENABLED', '活动启用'
        CAMPAIGN_OUT_OF_BUDGET = 'CAMPAIGN_OUT_OF_BUDGET', '活动预算不足'
        CAMPAIGN_ARCHIVED = 'CAMPAIGN_ARCHIVED', '已归档'
        ACCOUNT_OUT_OF_BUDGET = 'ACCOUNT_OUT_OF_BUDGET', '账户预算不足'
        CAMPAIGN_INCOMPLETE = 'CAMPAIGN_INCOMPLETE', '设置不完整'

    class TargetingType(models.TextChoices):
        MANUAL = 'manual', '手动投放'
        AUTO = 'auto', '自动投放'

    # ========== 字段定义 ==========
    campaign_id = models.BigIntegerField(
        'Campaign ID',
        primary_key=True,
        db_comment='领星广告活动ID（亚马逊全局唯一）'
    )

    lingxing_shop = models.ForeignKey(
        'amazon.LingXingAmazonShop',
        on_delete=models.CASCADE,
        related_name='campaigns',
        verbose_name='领星店铺',
        db_comment='关联领星店铺'
    )

    campaign_name = models.CharField(
        '活动名称',
        max_length=200,
        blank=True,
        null=True,
        db_comment='广告活动名称（可修改，此处存最新值）'
    )

    campaign_type = models.CharField(
        '活动类型',
        max_length=20,
        choices=CampaignType.choices,
        blank=True,
        null=True,
        db_comment='广告活动类型'
    )

    status = models.CharField(
        '状态',
        max_length=20,
        choices=Status.choices,
        blank=True,
        null=True,
        db_comment='活动状态（enabled/paused/archived）'
    )

    serving_status = models.CharField(
        '投放状态',
        max_length=50,
        choices=ServingStatus.choices,
        blank=True,
        null=True,
        db_comment='实时投放状态'
    )

    targeting_type = models.CharField(
        '投放方式',
        max_length=20,
        choices=TargetingType.choices,
        blank=True,
        null=True,
        db_comment='targeting类型（manual/auto）'
    )

    daily_budget = models.DecimalField(
        '日预算',
        max_digits=12,
        decimal_places=2,
        blank=True,
        null=True,
        db_comment='每日预算（站点币种）'
    )

    bidding = models.JSONField(
        '竞价策略',
        default=dict,
        blank=True,
        null=True,
        db_comment='竞价策略JSON'
    )

    portfolio_id = models.BigIntegerField(
        'Portfolio ID',
        blank=True,
        null=True,
        db_comment='广告组合ID'
    )

    start_date = models.DateField(
        '开始日期',
        blank=True,
        null=True,
        db_comment='活动开始日期'
    )

    end_date = models.DateField(
        '结束日期',
        blank=True,
        null=True,
        db_comment='活动结束日期'
    )

    creation_date = models.DateField(
        '创建日期',
        blank=True,
        null=True,
        db_comment='活动创建日期'
    )

    first_seen_at = models.DateTimeField(
        '首次发现时间',
        auto_now_add=True,
        db_comment='首次同步到系统的时间'
    )

    last_updated_at = models.DateTimeField(
        '最后更新时间',
        auto_now=True,
        db_comment='最后同步更新时间'
    )

    class Meta:
        db_table = 'ad_lingxing_campaigns'
        verbose_name = '领星Campaign维度'
        verbose_name_plural = verbose_name
        indexes = [
            models.Index(fields=['lingxing_shop', 'status'], name='idx_campaign_shop_status'),
            models.Index(fields=['campaign_type'], name='idx_campaign_type'),
            models.Index(fields=['targeting_type'], name='idx_campaign_targeting'),
        ]

    def __str__(self):
        return f"{self.campaign_name or '未命名'} ({self.campaign_id})"


class LingXingAdHourlyData(models.Model):
    """
    领星广告小时数据（事实表）
    存储 spTargetHourData 接口返回的原始数据
    PostgreSQL 按月分区（Range Partitioning on report_date）
    """

    # ========== 枚举类定义 ==========
    class MatchType(models.TextChoices):
        BROAD = 'BROAD', '宽泛匹配'
        EXACT = 'EXACT', '精准匹配'
        PHRASE = 'PHRASE', '词组匹配'

    # ========== 字段定义 ==========
    id = models.BigAutoField(primary_key=True, db_comment='主键')

    lingxing_shop = models.ForeignKey(
        'amazon.LingXingAmazonShop',
        on_delete=models.CASCADE,
        related_name='ad_hourly_data',
        verbose_name='领星店铺',
        db_comment='关联领星店铺（级联删除）'
    )

    campaign_id = models.BigIntegerField(
        'Campaign ID',
        db_index=True,
        db_comment='广告活动ID（逻辑关联 LingXingCampaign）'
    )

    ad_group_id = models.BigIntegerField(
        'Ad Group ID',
        db_comment='广告组ID'
    )

    ad_id = models.BigIntegerField(
        '广告ID',
        db_index=True,
        db_comment='广告条目ID（Product Ad ID）'
    )

    targeting_id = models.BigIntegerField(
        '投放ID',
        db_comment='投放词ID（Targeting，同一个ad_id可能有多个targeting）'
    )

    report_date = models.DateField(
        '报表日期',
        db_comment='报表日期（YYYY-MM-DD），分区键',
        help_text='PostgreSQL按月分区'
    )

    hour = models.SmallIntegerField(
        '小时',
        db_comment='小时（0-23）'
    )

    asin = models.CharField(
        'ASIN',
        max_length=10,
        db_index=True,
        db_comment='亚马逊商品编码（冗余存储，用于分组查询）'
    )

    msku = models.CharField(
        'MSKU',
        max_length=100,
        blank=True,
        null=True,
        db_comment='本地SKU（冗余存储）'
    )

    targeting = models.CharField(
        '投放词',
        max_length=255,
        blank=True,
        null=True,
        db_comment='定位内容（可能是关键词、ASIN或类目）'
    )

    match_type = models.CharField(
        '匹配类型',
        max_length=20,
        choices=MatchType.choices,
        blank=True,
        null=True,
        db_comment='匹配类型（BROAD/EXACT/PHRASE，targeting为ASIN时可能为空）'
    )

    # ========== 核心指标（原始值，站点币种） ==========
    impressions = models.IntegerField(
        '曝光量',
        default=0,
        db_comment='曝光次数'
    )

    clicks = models.IntegerField(
        '点击量',
        default=0,
        db_comment='点击次数'
    )

    cost = models.DecimalField(
        '花费',
        max_digits=12,
        decimal_places=2,
        default=0,
        db_comment='广告花费（站点币种）'
    )

    orders = models.IntegerField(
        '订单数',
        default=0,
        db_comment='广告订单数'
    )

    sales = models.DecimalField(
        '销售额',
        max_digits=12,
        decimal_places=2,
        default=0,
        db_comment='广告销售额（站点币种）'
    )

    units = models.IntegerField(
        '销量',
        default=0,
        db_comment='售出商品数量'
    )

    same_orders = models.IntegerField(
        '同品类订单',
        default=0,
        db_comment='同品类订单数（品牌光环效应）'
    )

    same_sales = models.DecimalField(
        '同品类销售',
        max_digits=12,
        decimal_places=2,
        default=0,
        db_comment='同品类销售额'
    )

    same_units = models.IntegerField(
        '同品类销量',
        default=0,
        db_comment='同品类售出数量'
    )

    # ========== 元数据 ==========
    created_at = models.DateTimeField(auto_now_add=True, db_comment='写入时间')
    updated_at = models.DateTimeField(auto_now=True, db_comment='更新时间')

    class Meta:
        db_table = 'ad_hourly_data'
        verbose_name = '领星广告小时数据'
        verbose_name_plural = verbose_name

        unique_together = [
            ['lingxing_shop', 'report_date', 'hour', 'ad_id', 'targeting_id']
        ]

        indexes = [
            models.Index(
                fields=['lingxing_shop', 'asin', 'report_date'],
                name='idx_ad_asin_date'
            ),
            models.Index(
                fields=['report_date', 'hour'],
                name='idx_ad_datetime'
            ),
            models.Index(
                fields=['campaign_id', 'report_date'],
                name='idx_ad_campaign_date'
            ),
            models.Index(
                fields=['ad_id', 'report_date'],
                name='idx_ad_adid_date'
            ),
        ]

    def __str__(self):
        return f"{self.asin} | {self.report_date} {self.hour}:00 | 花费:${self.cost}"

    # ========== 实例方法：单条记录计算 ==========
    def get_acos(self):
        """单小时 ACOS（%）"""
        if self.sales and self.sales > 0:
            return (self.cost / self.sales) * 100
        return None

    def get_roas(self):
        """单小时 ROAS"""
        if self.cost and self.cost > 0:
            return self.sales / self.cost
        return None

    def get_ctr(self):
        """单小时 CTR（%）"""
        if self.impressions and self.impressions > 0:
            return (self.clicks / self.impressions) * 100
        return None

    def get_cvr(self):
        """单小时 CVR（%）"""
        if self.clicks and self.clicks > 0:
            return (self.orders / self.clicks) * 100
        return None

    def get_cpc(self):
        """单小时 CPC"""
        if self.clicks and self.clicks > 0:
            return self.cost / self.clicks
        return None

    def get_cpa(self):
        """单小时 CPA（单次获取成本）"""
        if self.orders and self.orders > 0:
            return self.cost / self.orders
        return None
    # ========== 类方法：QuerySet 聚合计算（推荐用于 ASIN 盈亏统计） ==========
    @classmethod
    def calculate_asin_metrics(cls, queryset):
        """
        对 QuerySet 聚合计算 ASIN 级别指标
        用法：LingXingAdHourlyData.calculate_asin_metrics(
            LingXingAdHourlyData.objects.filter(asin='B0XXX', report_date__gte='2026-02-01')
        )
        """
        result = queryset.aggregate(
            total_cost=Sum('cost'),
            total_sales=Sum('sales'),
            total_clicks=Sum('clicks'),
            total_impressions=Sum('impressions'),
            total_orders=Sum('orders'),
            total_units=Sum('units'),
        )

        total_cost = result.get('total_cost') or 0
        total_sales = result.get('total_sales') or 0
        total_clicks = result.get('total_clicks') or 0
        total_impressions = result.get('total_impressions') or 0
        total_orders = result.get('total_orders') or 0

        return {
            **result,
            'acos': (total_cost / total_sales * 100) if total_sales > 0 else None,
            'roas': (total_sales / total_cost) if total_cost > 0 else None,
            'ctr': (total_clicks / total_impressions * 100) if total_impressions > 0 else None,
            'cvr': (total_orders / total_clicks * 100) if total_clicks > 0 else None,
            'cpc': (total_cost / total_clicks) if total_clicks > 0 else None,
            'cpa': (total_cost / total_orders) if total_orders > 0 else None,
        }