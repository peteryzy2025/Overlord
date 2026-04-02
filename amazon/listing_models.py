# amazon/listing_models.py
# AmazonListing 优化后的模型（销量历史拆分版本）

from django.db import models


class AmazonListingV2(models.Model):
    """
    Amazon Listing 主表
    存储Listing的静态/准静态信息（基本信息、库存、价格等）
    
    唯一约束：asin + sid + fulfillment_channel_type
    说明：同一个ASIN在同一个店铺的FBA和FBM是两条记录
    """

    class RiskLevelChoice(models.TextChoices):
        UNKNOWN = 'unknown', '未知'
        LOW = 'low', '低'
        MEDIUM = 'medium', '中'
        HIGH = 'high', '高'

    class StatusChoice(models.IntegerChoices):
        INACTIVE = 0, '停售'
        ACTIVE = 1, '在售'

    class DeleteChoice(models.IntegerChoices):
        NO = 0, '未删除'
        YES = 1, '已删除'

    class StoreTypeChoice(models.IntegerChoices):
        NORMAL = 1, '非低价商店'
        LOW_PRICE = 2, '低价商店商品'

    # ========== 主键 ==========
    id = models.BigAutoField(
        primary_key=True,
        verbose_name='ID',
        db_comment='自增主键'
    )

    # ========== 核心标识（联合唯一约束） ==========
    asin = models.CharField(
        max_length=10,
        verbose_name='ASIN',
        db_comment='亚马逊商品编码'
    )

    sid = models.BigIntegerField(
        verbose_name='店铺ID',
        db_comment='领星店铺sid'
    )

    fulfillment_channel_type = models.CharField(
        max_length=10,
        null=True,
        blank=True,
        verbose_name='配送方式',
        db_comment='FBA/FBM'
    )

    listing_id = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        verbose_name='Listing ID',
        db_comment='亚马逊定义的listing ID（可能为空）'
    )

    marketplace = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        verbose_name='国家',
        db_comment='市场国家'
    )

    parent_asin = models.CharField(
        max_length=10,
        null=True,
        blank=True,
        verbose_name='父ASIN',
        db_comment='父ASIN（变体关系）'
    )

    fnsku = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        verbose_name='FNSKU',
        db_comment='亚马逊FNSKU'
    )

    # ========== 外键关联 ==========
    lingxing_shop = models.ForeignKey(
        'amazon.LingXingAmazonShop',
        on_delete=models.CASCADE,
        related_name='listings',
        verbose_name='所属领星店铺',
        db_comment='绑定的领星站点店铺'
    )

    tro_words = models.ManyToManyField(
        'theme.TroTable',
        related_name='listings',
        verbose_name='命中侵权词',
        blank=True,
    )

    trademarks = models.ManyToManyField(
        'theme.TrademarkInfo',
        related_name='listings',
        verbose_name='命中商标',
        blank=True,
    )

    # ========== 商品基础信息 ==========
    title = models.CharField(
        max_length=500,
        null=True,
        blank=True,
        verbose_name='标题',
        db_comment='Listing标题（item_name）'
    )

    seller_sku = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        verbose_name='MSKU',
        db_comment='卖家SKU（MSKU）'
    )

    local_sku = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        verbose_name='本地SKU',
        db_comment='本地产品SKU'
    )

    local_name = models.CharField(
        max_length=200,
        null=True,
        blank=True,
        verbose_name='品名',
        db_comment='本地产品品名'
    )

    seller_brand = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        verbose_name='品牌',
        db_comment='亚马逊品牌'
    )

    small_image_url = models.URLField(
        max_length=500,
        null=True,
        blank=True,
        verbose_name='缩略图',
        db_comment='商品缩略图URL'
    )

    # ========== 排名与评价 ==========
    seller_rank = models.IntegerField(
        null=True,
        blank=True,
        verbose_name='排名',
        db_comment='销售排名'
    )

    seller_category_new = models.JSONField(
        default=list,
        null=True,
        blank=True,
        verbose_name='排名类别',
        db_comment='排名所属的类别列表，如["Beauty & Personal Care"]'
    )

    review_num = models.IntegerField(
        default=0,
        null=True,
        blank=True,
        verbose_name='评论数',
        db_comment='评论条数'
    )

    last_star = models.CharField(
        max_length=10,
        null=True,
        blank=True,
        verbose_name='星级',
        db_comment='星级评分'
    )

    # ========== 状态字段 ==========
    status = models.SmallIntegerField(
        choices=StatusChoice.choices,
        default=StatusChoice.ACTIVE,
        null=True,
        blank=True,
        verbose_name='销售状态',
        db_comment='0停售/1在售'
    )

    is_delete = models.SmallIntegerField(
        choices=DeleteChoice.choices,
        default=DeleteChoice.NO,
        null=True,
        blank=True,
        verbose_name='删除标记',
        db_comment='0未删除/1已删除（亚马逊侧标记）'
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name='是否在售',
        db_comment='Listing是否处于在售状态（本地标记）'
    )

    store_type = models.SmallIntegerField(
        choices=StoreTypeChoice.choices,
        default=StoreTypeChoice.NORMAL,
        null=True,
        blank=True,
        verbose_name='店铺类型',
        db_comment='1非低价商店/2低价商店商品'
    )

    risk_level = models.CharField(
        max_length=10,
        choices=RiskLevelChoice.choices,
        default=RiskLevelChoice.UNKNOWN,
        verbose_name='风险等级',
        db_comment='主题风险等级'
    )

    # ========== 价格信息 ==========
    currency_code = models.CharField(
        max_length=10,
        null=True,
        blank=True,
        verbose_name='币种',
        db_comment='币种代码，如USD'
    )

    price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name='价格',
        db_comment='基础价格（不含促销、运费、积分）'
    )

    landed_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name='总价',
        db_comment='总价（含促销、运费、积分）'
    )

    listing_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name='优惠价',
        db_comment='Listing优惠价'
    )

    shipping = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name='运费',
        db_comment='运费金额'
    )

    points = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        verbose_name='积分',
        db_comment='积分（日本站才有）'
    )

    # ========== 库存信息 ==========
    quantity = models.IntegerField(
        default=0,
        null=True,
        blank=True,
        verbose_name='FBM库存',
        db_comment='FBM库存数量'
    )

    # FBA可售/不可售
    afn_fulfillable_quantity = models.IntegerField(
        default=0,
        null=True,
        blank=True,
        verbose_name='FBA可售',
        db_comment='FBA可售库存'
    )

    afn_unsellable_quantity = models.IntegerField(
        default=0,
        null=True,
        blank=True,
        verbose_name='FBA不可售',
        db_comment='FBA不可售库存'
    )

    # 预留库存
    reserved_fc_transfers = models.IntegerField(
        default=0,
        null=True,
        blank=True,
        verbose_name='待调仓',
        db_comment='预留-待调仓'
    )

    reserved_fc_processing = models.IntegerField(
        default=0,
        null=True,
        blank=True,
        verbose_name='调仓中',
        db_comment='预留-调仓中'
    )

    reserved_customerorders = models.IntegerField(
        default=0,
        null=True,
        blank=True,
        verbose_name='待发货',
        db_comment='预留-待发货'
    )

    # 入库相关
    afn_inbound_shipped_quantity = models.IntegerField(
        default=0,
        null=True,
        blank=True,
        verbose_name='在途',
        db_comment='入库-在途'
    )

    afn_inbound_working_quantity = models.IntegerField(
        default=0,
        null=True,
        blank=True,
        verbose_name='计划入库',
        db_comment='入库-计划'
    )

    afn_inbound_receiving_quantity = models.IntegerField(
        default=0,
        null=True,
        blank=True,
        verbose_name='入库中',
        db_comment='入库-接收中'
    )

    # ========== 时间信息 ==========
    open_date = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='创建时间',
        db_comment='商品创建时间（原始格式解析）'
    )

    open_date_display = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='创建时间（标准）',
        db_comment='商品创建时间（标准化格式）'
    )

    pair_update_time = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='配对更新时间',
        db_comment='配对更新时间（北京时间）'
    )

    first_order_time = models.DateField(
        null=True,
        blank=True,
        verbose_name='首单时间',
        db_comment='首单日期（Y-m-d）'
    )

    on_sale_time = models.DateField(
        null=True,
        blank=True,
        verbose_name='开售时间',
        db_comment='开售日期（Y-m-d）'
    )

    # ========== JSON扩展字段 ==========
    dimension_info = models.JSONField(
        default=dict,
        null=True,
        blank=True,
        verbose_name='尺寸信息',
        db_comment='商品尺寸重量信息（item/package）'
    )

    small_rank = models.JSONField(
        default=list,
        null=True,
        blank=True,
        verbose_name='小类排名',
        db_comment='小类排名信息列表'
    )

    global_tags = models.JSONField(
        default=list,
        null=True,
        blank=True,
        verbose_name='全局标签',
        db_comment='全局标签列表'
    )

    # ========== 系统时间 ==========
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='创建时间',
        db_comment='本地记录创建时间'
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='更新时间',
        db_comment='本地记录更新时间'
    )

    class Meta:
        db_table = 'amazon_listing_v2'
        db_table_comment = 'Amazon Listing主表V2（销量拆分版）'
        verbose_name = 'Amazon Listing'
        verbose_name_plural = 'Amazon Listings'

        # 核心约束：asin + sid + 配送方式 唯一
        constraints = [
            models.UniqueConstraint(
                fields=['asin', 'sid', 'fulfillment_channel_type'],
                name='uniq_asin_sid_channel_v2'
            )
        ]

        # 常用查询索引
        indexes = [
            models.Index(fields=['asin'], name='idx_listing_v2_asin'),
            models.Index(fields=['sid'], name='idx_listing_v2_sid'),
            models.Index(fields=['parent_asin'], name='idx_listing_v2_parent'),
            models.Index(fields=['seller_sku'], name='idx_listing_v2_sku'),
            models.Index(fields=['local_sku'], name='idx_listing_v2_local_sku'),
            models.Index(fields=['fnsku'], name='idx_listing_v2_fnsku'),
            models.Index(fields=['status'], name='idx_listing_v2_status'),
            models.Index(fields=['is_delete'], name='idx_listing_v2_is_delete'),
            models.Index(fields=['fulfillment_channel_type'], name='idx_listing_v2_channel'),
            models.Index(fields=['risk_level'], name='idx_listing_v2_risk'),
            models.Index(fields=['store_type'], name='idx_listing_v2_store_type'),
            models.Index(fields=['updated_at'], name='idx_listing_v2_updated'),
        ]

    def __str__(self):
        shop_name = self.lingxing_shop.name if self.lingxing_shop else f'sid_{self.sid}'
        return f"{shop_name} - {self.asin} ({self.fulfillment_channel_type})"


class AmazonListingSalesHistory(models.Model):
    """
    Amazon Listing 销量历史表
    每日快照存储销量、销售额、日均销量数据
    保留180天历史数据（需自行清理）
    """

    # ========== 主键 ==========
    id = models.BigAutoField(
        primary_key=True,
        verbose_name='ID',
        db_comment='自增主键'
    )

    # ========== 外键关联 ==========
    listing = models.ForeignKey(
        AmazonListingV2,
        on_delete=models.CASCADE,
        related_name='sales_history',
        verbose_name='Listing',
        db_comment='关联的AmazonListing'
    )

    # ========== 快照日期 ==========
    snapshot_date = models.DateField(
        verbose_name='快照日期',
        db_comment='数据统计日期'
    )

    # ========== 销量字段 ==========
    volume_1d = models.IntegerField(
        null=True,
        blank=True,
        verbose_name='销量-昨天',
        db_comment='昨天销量'
    )

    volume_7d = models.IntegerField(
        null=True,
        blank=True,
        verbose_name='销量-7天',
        db_comment='7天销量'
    )

    volume_14d = models.IntegerField(
        null=True,
        blank=True,
        verbose_name='销量-14天',
        db_comment='14天销量'
    )

    volume_30d = models.IntegerField(
        null=True,
        blank=True,
        verbose_name='销量-30天',
        db_comment='30天销量'
    )

    # ========== 销售额字段 ==========
    amount_1d = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name='销售额-昨天',
        db_comment='昨天销售额'
    )

    amount_7d = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name='销售额-7天',
        db_comment='7天销售额'
    )

    amount_14d = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name='销售额-14天',
        db_comment='14天销售额'
    )

    amount_30d = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name='销售额-30天',
        db_comment='30天销售额'
    )

    # ========== 日均销量字段 ==========
    avg_volume_7d = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name='日均销量-7日',
        db_comment='7日日均销量'
    )

    avg_volume_14d = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name='日均销量-14日',
        db_comment='14日日均销量'
    )

    avg_volume_30d = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name='日均销量-30日',
        db_comment='30日日均销量'
    )

    # ========== 系统时间 ==========
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='创建时间',
        db_comment='记录创建时间'
    )

    class Meta:
        db_table = 'amazon_listing_sales_history'
        db_table_comment = 'Amazon Listing销量历史表（每日快照）'
        verbose_name = 'Listing销量历史'
        verbose_name_plural = 'Listing销量历史'

        # 唯一约束：每个Listing每天一条记录
        constraints = [
            models.UniqueConstraint(
                fields=['listing', 'snapshot_date'],
                name='uniq_listing_date'
            )
        ]

        # 常用查询索引
        indexes = [
            models.Index(fields=['listing', 'snapshot_date'], name='idx_sales_listing_date'),
            models.Index(fields=['snapshot_date'], name='idx_sales_date'),
            models.Index(fields=['listing'], name='idx_sales_listing'),
        ]

        # 按时间倒序，方便查看最新数据
        ordering = ['-snapshot_date']

    def __str__(self):
        return f"{self.listing.asin} - {self.snapshot_date}"
