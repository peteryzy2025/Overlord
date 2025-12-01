# amazon/models.py

from django.db import models


class LingXingAmazonShop(models.Model):
    """
    领星-亚马逊店铺（按站点维度存储）
    映射领星返回的店铺列表：一个 AmazonShop 可对应多个站点（US/CA/MX…）
    """

    # ========== 领星原始字段 ==========

    sid = models.BigIntegerField(
        primary_key=True,
        db_comment='领星店铺 sid（主键）'
    )

    mid = models.IntegerField(
        db_comment='领星店铺 mid（账号内唯一）'
    )

    name = models.CharField(
        max_length=150,
        blank=True,
        null=True,
        db_comment='领星店铺名称（例如：黄志雄-19高强-US）'
    )

    seller_id = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        db_comment='领星 seller_id'
    )

    account_name = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        db_comment='领星账号名称（例如：黄志雄-19高强）'
    )

    seller_account_id = models.BigIntegerField(
        blank=True,
        null=True,
        db_comment='领星 seller_account_id'
    )

    region = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        db_comment='区域（如 NA/EU）'
    )

    country = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        db_comment='国家（如 美国/加拿大）'
    )

    marketplace_id = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        db_comment='亚马逊 marketplace_id（如 ATVPDKIKX0DER）'
    )

    status = models.SmallIntegerField(
        blank=True,
        null=True,
        db_comment='领星店铺状态（1=正常等）'
    )

    has_ads_setting = models.SmallIntegerField(
        blank=True,
        null=True,
        db_comment='是否有广告配置（0/1）'
    )

    # ========== 绑定你本地 AmazonShop ==========

    amazon_shop = models.ForeignKey(
        'General.AmazonShop',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='lingxing_amazon_shops',
        db_comment='绑定的本地亚马逊店铺'
    )

    # ========== 记录时间 ==========
    created_at = models.DateTimeField(
        auto_now_add=True,
        db_comment='创建时间（插入本地记录时间）'
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        db_comment='更新时间（最后同步时间）'
    )

    class Meta:
        db_table = 'lingxing_amazon_shop'
        db_table_comment = '领星-亚马逊店铺信息表'
        verbose_name = '领星亚马逊店铺'
        verbose_name_plural = verbose_name

        # 保证同一个领星账号下的 mid 不重复（符合领星数据结构）
        constraints = [
            models.UniqueConstraint(
                fields=['seller_account_id', 'mid'],
                name='uniq_lingxing_seller_mid'
            )
        ]

    def __str__(self):
        if self.amazon_shop:
            return f'{self.account_name}-{self.name}(sid={self.sid}) → {self.amazon_shop.shop_name}'
        return f'{self.account_name}-{self.name}(sid={self.sid})'


class AmazonOrders(models.Model):
    """
    亚马逊订单主表
    """
    # 修改：使用自增主键，避免不同店铺订单号重复问题
    id = models.BigAutoField(primary_key=True, db_comment='自增主键')

    amazon_order_id = models.CharField(
        max_length=50,
        db_index=True,
        db_comment='亚马逊订单ID'
    )
    order_no = models.CharField(
        max_length=50,
        db_index=True,
        db_comment="领星订单号",
        blank=True,

    )
    # 绑定到 LingXingAmazonShop（反向可查订单）
    lingxing_shop = models.ForeignKey(
        'LingXingAmazonShop',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='amazon_orders',
        db_comment='关联的领星店铺'
    )

    # 绑定到本地 AmazonShop
    amazon_shop = models.ForeignKey(
        'General.AmazonShop',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='amazon_orders',
        db_comment='关联的本地亚马逊店铺'
    )

    # 基本信息
    order_status = models.CharField(max_length=50, blank=True, null=True)
    order_total_amount = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    order_total_currency_code = models.CharField(max_length=10, blank=True, null=True)
    fulfillment_channel = models.CharField(max_length=20, blank=True, null=True)
    sales_channel = models.CharField(max_length=50, blank=True, null=True)

    # 买家信息
    buyer_email = models.CharField(max_length=200, blank=True, null=True)
    buyer_name = models.CharField(max_length=200, blank=True, null=True)
    phone = models.CharField(max_length=50, blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    postal_code = models.CharField(max_length=20, blank=True, null=True)

    # 物流
    tracking_number = models.CharField(max_length=100, blank=True, null=True)

    # 状态位
    is_return = models.SmallIntegerField(default=0)
    is_mcf_order = models.SmallIntegerField(default=0)
    is_assessed = models.SmallIntegerField(default=0)
    is_replaced_order = models.SmallIntegerField(default=0)
    is_replacement_order = models.SmallIntegerField(default=0)
    is_return_order = models.SmallIntegerField(default=0)
    refund_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    # 日期
    purchase_date_local = models.DateTimeField(blank=True, null=True)
    purchase_date_utc = models.DateTimeField(blank=True, null=True)
    shipment_date_local = models.DateTimeField(blank=True, null=True)
    shipment_date_utc = models.DateTimeField(blank=True, null=True)
    last_update_date_local = models.DateTimeField(blank=True, null=True)
    last_update_date_utc = models.DateTimeField(blank=True, null=True)
    gmt_modified = models.DateTimeField(blank=True, null=True)
    gmt_modified_utc = models.DateTimeField(blank=True, null=True)
    hide_time = models.DateTimeField(blank=True, null=True)
    is_exported_to_divi = models.BooleanField(
        default=False,
        verbose_name='是否已导出DIVI',
        help_text='勾选表示该订单已同步至DIVI系统'
    )

    created_at = models.DateTimeField(auto_now_add=True, db_comment='创建时间')
    updated_at = models.DateTimeField(auto_now=True, db_comment='更新时间')

    # ===== DIVI系统专用字段（全部带divi_前缀） =====
    divi_import_time = models.DateTimeField(
        blank=True, null=True,
        verbose_name='DIVI导入时间',
        db_comment='订单导入DIVI系统时间(createTime)'
    )

    divi_payment_time = models.DateTimeField(
        blank=True, null=True,
        verbose_name='DIVI付款时间',
        db_comment='买家付款时间(paymentTime)'
    )

    divi_audit_time = models.DateTimeField(
        blank=True, null=True,
        verbose_name='DIVI审核时间',
        db_comment='订单审核通过时间'
    )

    divi_dispatch_time = models.DateTimeField(
        blank=True, null=True,
        verbose_name='DIVI派单时间',
        db_comment='订单派发给仓库时间(sendOrderTime)'
    )

    divi_shipment_time = models.DateTimeField(
        blank=True, null=True,
        verbose_name='DIVI发货时间',
        db_comment='仓库实际发货时间(sendGoodsTime)'
    )

    divi_logistics_method = models.CharField(
        max_length=100,
        blank=True, null=True,
        verbose_name='DIVI物流方式',
        db_comment='物流渠道名称(logisticsMethodName)'
    )

    divi_tracking_number = models.CharField(
        max_length=100,
        blank=True, null=True,
        verbose_name='DIVI跟踪号',
        db_comment='物流跟踪号(trackingNumber)'
    )
    divi_shipping_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        blank=True,
        null=True,
        db_comment='运费金额'
    )
    divi_goods_payment_total = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        blank=True,
        null=True,
        db_comment='货款总计'
    )

    # DIVI订单状态
    DIVI_STATUS_CHOICES = [
        (0, '取消订单'),
        (1, '未付货款'),
        (2, '未审核'),
        (3, '排单中'),
        (4, '生产中'),
        (5, '已发货'),
    ]
    divi_order_status = models.SmallIntegerField(
        choices=DIVI_STATUS_CHOICES,
        blank=True, null=True,
        verbose_name='DIVI订单状态',
        db_comment='DIVI系统订单状态(status)'
    )
    masked_single = models.BooleanField(
        default=False,
        verbose_name="假发货",
        db_comment="是否假面单"
    )

    class Meta:
        db_table = 'amazon_orders'
        db_table_comment = '亚马逊订单主表'

        # 关键：使用店铺+订单号作为唯一约束
        constraints = [
            models.UniqueConstraint(
                fields=['lingxing_shop', 'amazon_order_id'],
                name='uniq_lingxing_shop_order_id'
            )
        ]

    def __str__(self):
        shop_name = self.lingxing_shop.name if self.lingxing_shop else '未知店铺'
        return f"{shop_name} - {self.amazon_order_id} ({self.order_status})"


class AmazonOrderItem(models.Model):
    """
    亚马逊订单 - 商品明细
    """
    order = models.ForeignKey(
        AmazonOrders,
        on_delete=models.CASCADE,
        related_name='items',
        db_comment='关联的订单'
    )

    asin = models.CharField(max_length=30)
    seller_sku = models.CharField(max_length=100, blank=True, null=True)
    local_sku = models.CharField(max_length=100, blank=True, null=True)
    local_name = models.CharField(max_length=200, blank=True, null=True)
    order_status = models.CharField(max_length=50, blank=True, null=True)
    quantity_ordered = models.IntegerField(default=1)
    divi_product_name = models.CharField(
        max_length=200,
        blank=True, null=True,
        verbose_name='DIVI商品名称',
        db_comment='商品名称(productName)'
    )

    class Meta:
        db_table = 'amazon_order_item'
        db_table_comment = '亚马逊订单商品明细'
        unique_together = ['order', 'seller_sku']


class AmazonShopDailyCheck(models.Model):
    """
    亚马逊巡店日报模型
    记录运营人员每日对店铺的巡检操作
    """

    id = models.BigAutoField(primary_key=True, db_comment='主键')

    # 关联亚马逊店铺
    shop = models.ForeignKey(
        'General.AmazonShop',
        on_delete=models.CASCADE,
        related_name='daily_checks',
        db_comment='关联的亚马逊店铺'
    )

    # 巡检日期
    check_date = models.DateField(
        db_comment='巡店日期'
    )

    # 巡检操作状态（布尔值）
    visited = models.BooleanField(
        default=False,
        db_comment='是否进入店铺'
    )

    performance_checked = models.BooleanField(
        default=False,
        db_comment='是否进行绩效通知检查'
    )

    withdrawal_processed = models.BooleanField(
        default=False,
        db_comment='是否进行提现操作'
    )

    # 记录时间
    created_at = models.DateTimeField(
        auto_now_add=True,
        db_comment='创建时间'
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        db_comment='更新时间'
    )

    class Meta:
        db_table = 'amazon_shop_daily_check'
        db_table_comment = '亚马逊巡店日报表'
        verbose_name = '亚马逊巡店日报'
        verbose_name_plural = verbose_name

        # 核心约束：每个店铺每天只能有一条记录
        constraints = [
            models.UniqueConstraint(
                fields=['shop', 'check_date'],
                name='uniq_shop_daily_check'
            )
        ]

        # 常用查询索引
        indexes = [
            models.Index(fields=['shop', 'check_date'], name='idx_check_shop_date'),
            models.Index(fields=['check_date'], name='idx_check_date'),
            models.Index(fields=['visited'], name='idx_check_visited'),
            models.Index(fields=['performance_checked'], name='idx_check_performance'),
            models.Index(fields=['withdrawal_processed'], name='idx_check_withdrawal'),
        ]

    def __str__(self):
        shop_name = self.shop.shop_name if self.shop else '未知店铺'
        return f"{shop_name} - {self.check_date} 巡检记录"


class AmazonPerformanceNotification(models.Model):
    """
    亚马逊绩效通知模型
    用于记录店铺收到的绩效通知，如政策警告、绩效指标异常等
    """

    id = models.BigAutoField(primary_key=True, db_comment='主键')

    # 关联店铺
    shop = models.ForeignKey(
        'General.AmazonShop',
        on_delete=models.CASCADE,
        related_name='performance_notifications',
        db_comment='关联的亚马逊店铺'
    )

    # 通知主题（限250字符）
    subject = models.CharField(
        max_length=250,
        db_comment='通知主题'
    )

    # 通知日期
    date = models.DateField(
        db_comment='通知日期'
    )

    # 状态标记字段
    needs_attention = models.SmallIntegerField(
        default=0,
        db_comment='是否需要注意（0=否，1=是）',
        verbose_name='需要注意'
    )

    is_processed = models.SmallIntegerField(
        default=0,
        db_comment='是否已处理（0=否，1=是）',
        verbose_name='已处理'
    )

    # 记录时间
    created_at = models.DateTimeField(
        auto_now_add=True,
        db_comment='创建时间'
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        db_comment='更新时间'
    )

    class Meta:
        db_table = 'amazon_performance_notification'
        db_table_comment = '亚马逊绩效通知表'
        verbose_name = '亚马逊绩效通知'
        verbose_name_plural = verbose_name
        constraints = [
            models.UniqueConstraint(
                fields=['shop', 'subject', 'date'],
                name='uniq_shop_subject_date'
            )
        ]
        # 建议添加索引优化查询
        indexes = [
            models.Index(fields=['shop', 'date'], name='idx_shop_date'),
            models.Index(fields=['needs_attention'], name='idx_needs_attention'),
            models.Index(fields=['is_processed'], name='idx_is_processed'),
        ]

    def __str__(self):
        return f"{self.shop.shop_name} - {self.subject[:50]} ({self.date})"
