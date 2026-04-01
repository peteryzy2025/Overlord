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
    profile_id = models.BigIntegerField(
        '领星ProfileID',
        blank=True,
        null=True,
        db_index=True,  # 方便反向查询
        db_comment='领星API返回的profile_id（与sid一一对应，用于数据校验）用于广告'
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
        'general.AmazonShop',
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
        'amazon.LingXingAmazonShop',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='amazon_orders',
        db_comment='关联的领星店铺'
    )

    # 绑定到本地 AmazonShop
    amazon_shop = models.ForeignKey(
        'general.AmazonShop',
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

    latest_ship_date = models.DateTimeField(
        blank=True, null=True,
        verbose_name='最晚发货时间',
        db_comment='承诺配送订单的最晚发货时间'
    )
    earliest_ship_date_local = models.DateTimeField(
        blank=True, null=True,
        db_comment='最晚发货时间（本地时间）列表的 - 放弃'
    )
    earliest_ship_date_utc = models.DateTimeField(
        blank=True, null=True,
        db_comment='最晚发货时间（UTC）列表的 - 放弃'
    )

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
        'general.AmazonShop',
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
    withdrawal_amount = models.DecimalField(
        max_digits=10,  # 总位数（可根据业务调整）
        decimal_places=2,  # 保留2位小数
        null=True,
        blank=True,
        default=None,
        db_comment='提现金额'
    )

    last_restock_date = models.DateField(
        null=True,  # 允许为空，因为可能还没有上货记录
        blank=True,
        db_comment='最后上货日期'
    )

    shop_status = models.CharField(
        max_length=100,  # 字符串长度限制为100个字符，可根据需要调整
        blank=True,  # 允许为空
        default='',  # 默认为空字符串
        null=True,
        db_comment='店铺状况'
    )
    
    # 店铺受限状态
    is_restricted = models.BooleanField(
        default=False,
        null=True,
        blank=True,
        db_comment='是否受限'
    )
    
    restricted_regions = models.JSONField(
        default=list,
        null=True,
        blank=True,
        db_comment='受限地区列表，如["加拿大", "美国", "墨西哥"]'
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



class RiskKeyword(models.Model):
    """
    平台风险关键词库
    适用于：店铺邮件(AmazonShopEmail)、绩效通知(AmazonPerformanceNotification) 等
    """

    MATCH_TYPE_CHOICES = [
        ('whole', '整词匹配'),  # \bkeyword\b，防止误触发
        ('contains', '包含匹配'),  # 简单 in 判断，性能最好
        ('regex', '正则表达式'),  # 复杂规则，如 .*suspended.*
        ('start', '开头匹配'),  # 标题以关键词开头
    ]

    # 风险大类（覆盖邮件+绩效通知场景）
    CATEGORY_CHOICES = [
        ('account_ban', '账户停用/冻结'),  # 如：Your account has been deactivated
        ('performance', '绩效/政策警告'),  # 如：Policy Warning, Order defect rate
        ('funds', '资金/提现异常'),  # 如：Funds Status, Payment hold
        ('listing', 'Listing下架/违规'),  # 如：Listings at risk, Intellectual property
        ('verification', '审核/验证通知'),  # 如：Account verification required
        ('tro', 'TRO/法律诉讼'),  # 如：Temporary Restraining Order
        ('inventory', '库存/物流异常'),  # 如：Stranded inventory, Removal required
        ('official', '官方通知'),  # 官方通知类
        ('other', '其他'),
    ]

    keyword = models.CharField('关键词/短语', max_length=255, db_index=True)
    category = models.CharField('风险分类', max_length=50, choices=CATEGORY_CHOICES, default='other')
    match_type = models.CharField('匹配方式', max_length=20, choices=MATCH_TYPE_CHOICES, default='whole')

    # 控制字段
    is_active = models.BooleanField('是否启用', default=True, db_index=True)
    priority = models.IntegerField('优先级', default=0, help_text='数值越大越优先，用于排序和显示')

    # 描述与示例
    description = models.CharField('规则说明', max_length=255, blank=True)
    example_text = models.CharField('示例文本', max_length=500, blank=True,
                                    help_text='该关键词通常出现的标题/内容示例，供参考')

    # 作用范围（可选，如果某些词只适用于邮件或只适用于绩效通知）
    APPLY_TO_CHOICES = [
        ('all', '全部'),
        ('email', '仅邮件'),
        ('performance', '仅绩效通知'),
    ]
    apply_to = models.CharField('适用范围', max_length=20, choices=APPLY_TO_CHOICES, default='all')

    created_by = models.ForeignKey('general.User', on_delete=models.SET_NULL, null=True, blank=True,
                                   verbose_name='创建人', related_name='created_risk_keywords')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        db_table = 'amazon_risk_keywords'
        verbose_name = '风险关键词'
        verbose_name_plural = '风险关键词'
        ordering = ['-priority', 'id']

    def __str__(self):
        return f"[{self.get_category_display()}] {self.keyword}"


class AmazonShopEmail(models.Model):
    id = models.BigAutoField(primary_key=True, verbose_name='主键')
    shop = models.ForeignKey(
        'general.AmazonShop',
        on_delete=models.CASCADE,
        related_name='shop_emails',
        db_comment='关联的亚马逊店铺'
    )
    subject = models.CharField('邮件标题', max_length=500)
    sender = models.CharField('发件人', max_length=255)
    email_body = models.TextField('邮件内容', blank=True, null=True)
    html_body = models.TextField('HTML邮件内容', blank=True, null=True)
    receive_time = models.DateTimeField('接收时间')
    is_attention_needed = models.BooleanField('是否需要注意', default=False)
    is_processed = models.BooleanField('是否已处理', default=False)
    remark = models.TextField('处理备注', blank=True, null=True)
    matched_keywords = models.ManyToManyField(
        RiskKeyword,
        blank=True,
        verbose_name='命中的风险关键词',
        db_table='amazon_email_risk_matches'
    )
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        db_table = 'amazon_shop_emails'
        verbose_name = '店铺邮件'
        verbose_name_plural = verbose_name

class AmazonPerformanceNotification(models.Model):
    """
    亚马逊绩效通知模型
    用于记录店铺收到的绩效通知，如政策警告、绩效指标异常等
    """

    id = models.BigAutoField(primary_key=True, db_comment='主键')

    # 关联店铺
    shop = models.ForeignKey(
        'general.AmazonShop',
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
    matched_keywords = models.ManyToManyField(
        RiskKeyword,
        blank=True,
        verbose_name='命中的风险关键词',
        db_table='amazon_performance_risk_matches'
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


class AmazonOrderFullDetail(models.Model):
    """
    亚马逊订单完整详情表（从 get_amazon_order_detail 接口获取）
    包含订单级所有字段，一次性写入后不再变更
    """

    order = models.OneToOneField(
        'AmazonOrders',
        on_delete=models.CASCADE,
        primary_key=True,
        related_name='full_detail',
        verbose_name='关联订单',
        db_comment='关联的亚马逊订单（一对一）'
    )

    # ===== 店铺信息 =====
    sid = models.BigIntegerField(
        verbose_name='店铺ID',
        db_comment='领星店铺ID'
    )

    # ===== 订单基础信息 =====
    amazon_order_id = models.CharField(
        max_length=50,
        verbose_name='亚马逊订单号',
        db_comment='亚马逊订单号'
    )

    fulfillment_channel = models.CharField(
        max_length=20,
        blank=True, null=True,
        verbose_name='发货渠道',
        db_comment='发货渠道（AFN/MFN）'
    )

    order_status_detail = models.CharField(
        max_length=50,
        blank=True, null=True,
        verbose_name='订单状态',
        db_comment='订单状态（Pending/Unshipped/Shipped/Canceled等）'
    )

    order_total_amount_detail = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        blank=True, null=True,
        verbose_name='订单总金额',
        db_comment='订单总金额'
    )

    currency = models.CharField(
        max_length=10,
        blank=True, null=True,
        verbose_name='订单币种',
        db_comment='订单金额币种'
    )

    icon = models.CharField(
        max_length=10,
        blank=True, null=True,
        verbose_name='币种符号',
        db_comment='订单金额币种符号'
    )

    # ===== 订单类型标志位 =====
    is_assessed = models.SmallIntegerField(
        default=0,
        verbose_name='是否为推广订单',
        db_comment='是否为推广订单：0否，1是'
    )

    is_mcf_order = models.SmallIntegerField(
        default=0,
        verbose_name='是否多渠道订单',
        db_comment='是否多渠道订单：0普通订单，1多渠道订单'
    )

    is_return_order = models.SmallIntegerField(
        default=0,
        verbose_name='是否为退货订单',
        db_comment='是否为退货订单：0否，1是'
    )

    is_replaced_order = models.SmallIntegerField(
        default=0,
        verbose_name='是否已换货',
        db_comment='是否已换货：0否，1是'
    )

    is_replacement_order = models.SmallIntegerField(
        default=0,
        verbose_name='是否为换货订单',
        db_comment='是否为换货订单：0否，1是'
    )

    is_business_order = models.SmallIntegerField(
        default=0,
        verbose_name='是否为B2B订单',
        db_comment='是否为B2B订单：0否，1是'
    )

    is_prime = models.SmallIntegerField(
        default=0,
        verbose_name='是否Prime订单',
        db_comment='是否Prime订单：0否，1是'
    )

    is_premium_order = models.SmallIntegerField(
        default=0,
        verbose_name='是否优先配送订单',
        db_comment='是否优先配送订单：0否，1是'
    )

    is_promotion = models.SmallIntegerField(
        default=0,
        verbose_name='是否促销订单',
        db_comment='是否促销订单：0否，1是'
    )

    # ===== 时间字段（站点时间）=====
    purchase_date_local_detail = models.DateTimeField(
        blank=True, null=True,
        verbose_name='订购时间（站点时间）',
        db_comment='订购时间（站点时间）'
    )

    last_update_date_detail = models.DateTimeField(
        blank=True, null=True,
        verbose_name='订单更新时间（站点时间）',
        db_comment='订单更新时间（站点时间）'
    )

    posted_date = models.DateTimeField(
        blank=True, null=True,
        verbose_name='结算时间（站点时间）',
        db_comment='结算时间（站点时间）'
    )

    shipment_date_detail = models.DateTimeField(
        blank=True, null=True,
        verbose_name='发货时间（站点时间）',
        db_comment='发货时间（站点时间）'
    )

    earliest_ship_date = models.DateTimeField(
        blank=True, null=True,
        verbose_name='发货时限（站点时间）',
        db_comment='发货时限（站点时间）'
    )

    # ===== 时间字段（UTC时间）=====
    purchase_date_utc_detail = models.DateTimeField(
        blank=True, null=True,
        verbose_name='订购时间（UTC）',
        db_comment='订购时间（UTC时间）'
    )

    last_update_date_utc_detail = models.DateTimeField(
        blank=True, null=True,
        verbose_name='订单更新时间（UTC）',
        db_comment='订单更新时间（UTC时间）'
    )

    earliest_ship_date_utc = models.DateTimeField(
        blank=True, null=True,
        verbose_name='发货时限（UTC）',
        db_comment='发货时限（UTC时间）'
    )

    # ===== 承诺配送时间（UTC）=====
    latest_ship_date = models.DateTimeField(
        blank=True, null=True,
        verbose_name='最晚发货时间',
        db_comment='承诺配送订单的最晚发货时间（UTC）'
    )

    earliest_delivery_date = models.DateTimeField(
        blank=True, null=True,
        verbose_name='最早送达时间',
        db_comment='承诺送达订单的最早送达时间（UTC）'
    )

    latest_delivery_date = models.DateTimeField(
        blank=True, null=True,
        verbose_name='最晚送达时间',
        db_comment='承诺送达订单的最晚送达时间（UTC）'
    )

    # ===== 物流信息 =====
    ship_service_level = models.CharField(
        max_length=100,
        blank=True, null=True,
        verbose_name='配送服务',
        db_comment='配送服务'
    )

    shipment_service_level_category = models.CharField(
        max_length=50,
        blank=True, null=True,
        verbose_name='装运服务级别',
        db_comment='装运服务级别'
    )

    number_of_items_shipped = models.IntegerField(
        default=0,
        verbose_name='已发货商品数',
        db_comment='已发货的商品数'
    )

    number_of_items_unshipped = models.IntegerField(
        default=0,
        verbose_name='未发货商品数',
        db_comment='未发货的商品数'
    )

    # ===== 销售渠道 =====
    sales_channel = models.CharField(
        max_length=100,
        blank=True, null=True,
        verbose_name='销售渠道',
        db_comment='销售渠道（如Amazon.com）'
    )

    # ===== 税费相关 =====
    taxes_included = models.SmallIntegerField(
        default=0,
        verbose_name='费用是否含税',
        db_comment='费用是否含税：1含税，2不含税（仅欧洲市场）'
    )

    # ===== 支付信息 =====
    payment_method = models.CharField(
        max_length=50,
        blank=True, null=True,
        verbose_name='付款方式',
        db_comment='付款方式：COD/CVS/Other'
    )

    cba_displayable_shipping_label = models.CharField(
        max_length=200,
        blank=True, null=True,
        verbose_name='CBA自定义发货标签',
        db_comment='亚马逊结账（CBA）的自定义发货标签'
    )

    # ===== 其他信息 =====
    purchase_order_number = models.CharField(
        max_length=100,
        blank=True, null=True,
        verbose_name='采购订单编号',
        db_comment='买家结账时输入的采购订单编号'
    )

    order_type = models.CharField(
        max_length=50,
        blank=True, null=True,
        verbose_name='订单类型',
        db_comment='订单类型'
    )

    # ===== 地址信息（结构化）=====
    buyer_name_detail = models.CharField(
        max_length=200,
        blank=True, null=True,
        verbose_name='买家姓名',
        db_comment='买家姓名（详情）'
    )

    buyer_phone_raw = models.CharField(
        max_length=100,
        blank=True, null=True,
        verbose_name='原始电话',
        db_comment='原始电话（含ext）'
    )

    buyer_phone_clean = models.CharField(
        max_length=50,
        blank=True, null=True,
        verbose_name='清洗后电话',
        db_comment='清洗后电话（去除ext）'
    )

    buyer_email_detail = models.CharField(
        max_length=200,
        blank=True, null=True,
        verbose_name='买家邮箱',
        db_comment='买家邮箱（详情）'
    )

    shipping_address_line1 = models.CharField(
        max_length=500,
        blank=True, null=True,
        verbose_name='地址行1',
        db_comment='地址第一行'
    )

    shipping_address_line2 = models.CharField(
        max_length=500,
        blank=True, null=True,
        verbose_name='地址行2',
        db_comment='地址第二行'
    )

    shipping_city = models.CharField(
        max_length=100,
        blank=True, null=True,
        verbose_name='城市',
        db_comment='城市'
    )

    shipping_state = models.CharField(
        max_length=100,
        blank=True, null=True,
        verbose_name='州/省',
        db_comment='州或省'
    )

    shipping_postal_code = models.CharField(
        max_length=20,
        blank=True, null=True,
        verbose_name='邮政编码',
        db_comment='邮政编码'
    )

    shipping_country_code = models.CharField(
        max_length=10,
        blank=True, null=True,
        verbose_name='国家代码',
        db_comment='国家代码（如US）'
    )

    shipping_address_full = models.TextField(
        blank=True, null=True,
        verbose_name='完整地址JSON',
        db_comment='完整收货地址JSON字符串'
    )

    # ===== 写入时间 =====
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='详情写入时间',
        db_comment='详情写入时间'
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='最后更新时间',
        db_comment='最后更新时间'
    )

    class Meta:
        db_table = 'amazon_order_full_detail'
        db_table_comment = '亚马逊订单完整详情表（从详情接口获取，一次性写入）'
        verbose_name = '亚马逊订单详情'
        verbose_name_plural = verbose_name

    def __str__(self):
        return f"{self.amazon_order_id} - 详情"


class AmazonOrderItemFullDetail(models.Model):
    """
    亚马逊订单商品完整明细表（从 item_list 获取）
    包含商品级所有费用和状态信息
    """

    # 使用 order_item_id 作为主键（亚马逊返回的唯一标识）
    order_item_id = models.CharField(
        max_length=100,
        primary_key=True,
        verbose_name='订单商品编码',
        db_comment='订单商品编码（订单下唯一，亚马逊返回值可能变更）'
    )

    order = models.ForeignKey(
        'AmazonOrders',
        on_delete=models.CASCADE,
        related_name='item_full_details',
        verbose_name='关联订单',
        db_comment='关联的亚马逊订单'
    )

    # ===== 商品基础信息 =====
    seller_sku = models.CharField(
        max_length=100,
        blank=True, null=True,
        verbose_name='MSKU',
        db_comment='卖家SKU（MSKU）'
    )

    asin = models.CharField(
        max_length=30,
        blank=True, null=True,
        verbose_name='ASIN',
        db_comment='商品ASIN编码'
    )

    title = models.CharField(
        max_length=500,
        blank=True, null=True,
        verbose_name='商品标题',
        db_comment='商品标题'
    )

    asin_url = models.URLField(
        max_length=500,
        blank=True, null=True,
        verbose_name='ASIN链接',
        db_comment='ASIN详情页链接'
    )

    pic_url = models.URLField(
        max_length=500,
        blank=True, null=True,
        verbose_name='商品图片',
        db_comment='商品主图URL'
    )

    # ===== 本地SKU关联 =====
    sku = models.CharField(
        max_length=100,
        blank=True, null=True,
        verbose_name='本地SKU',
        db_comment='本地系统SKU'
    )

    product_id = models.BigIntegerField(
        blank=True, null=True,
        verbose_name='本地产品ID',
        db_comment='本地系统产品ID'
    )

    product_name = models.CharField(
        max_length=200,
        blank=True, null=True,
        verbose_name='品名',
        db_comment='商品品名'
    )

    # ===== 数量信息 =====
    quantity_ordered = models.IntegerField(
        default=1,
        verbose_name='下单量',
        db_comment='下单数量'
    )

    quantity_shipped = models.IntegerField(
        default=0,
        verbose_name='已配送数量',
        db_comment='已配送数量'
    )

    # ===== 价格与费用（站点币种）=====
    item_price_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        verbose_name='商品支付金额',
        db_comment='商品支付金额'
    )

    item_tax_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        verbose_name='商品税',
        db_comment='商品税费'
    )

    shipping_price_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        verbose_name='买家运费',
        db_comment='买家支付的运费'
    )

    shipping_tax_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        verbose_name='运费税',
        db_comment='商品运费税'
    )

    gift_wrap_price_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        verbose_name='礼品包装费',
        db_comment='礼品包装费用'
    )

    gift_wrap_tax_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        verbose_name='礼品包装税',
        db_comment='礼品包装税'
    )

    shipping_discount_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        verbose_name='配送折扣',
        db_comment='配送折扣金额'
    )

    promotion_discount_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        verbose_name='商品促销折扣',
        db_comment='商品促销折扣金额'
    )

    # ===== FBA相关费用 =====
    fba_shipment_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        verbose_name='FBA发货费',
        db_comment='FBA发货费用（负数）'
    )

    commission_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        verbose_name='平台费',
        db_comment='亚马逊平台佣金（负数）'
    )

    # ===== 其他费用 =====
    cod_fee_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        verbose_name='COD服务费',
        db_comment='货到付款服务费'
    )

    other_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        verbose_name='其他费用',
        db_comment='其他亚马逊费用（如Amazon Exlusives Program）'
    )

    # ===== 成本与利润（本地币种）=====
    cg_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        verbose_name='采购成本',
        db_comment='商品采购成本（本地币种）'
    )

    cg_transport_costs = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        verbose_name='头程费用',
        db_comment='头程运输费用（本地币种）'
    )

    profit = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        verbose_name='毛利润',
        db_comment='订单商品毛利润（本地币种）'
    )

    # ===== 费用币种信息 =====
    fee_currency = models.CharField(
        max_length=10,
        blank=True, null=True,
        verbose_name='其他费币种',
        db_comment='其他费用币种（如推广费币种）'
    )

    fee_icon = models.CharField(
        max_length=10,
        blank=True, null=True,
        verbose_name='其他费币种符号',
        db_comment='其他费用币种符号'
    )

    fee_cost_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        verbose_name='自定义费用本金',
        db_comment='自定义费用本金（店铺对应币种）'
    )

    fee_cost = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        verbose_name='自定义费用本金',
        db_comment='自定义费用本金（fee_currency对应币种）'
    )

    # ===== 价格汇总 =====
    sales_price_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        verbose_name='销售收益',
        db_comment='商品销售收益'
    )

    unit_price_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        verbose_name='单价',
        db_comment='商品单价'
    )

    tax_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        verbose_name='税费',
        db_comment='商品税费汇总'
    )

    promotion_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        verbose_name='促销费',
        db_comment='促销费用'
    )

    item_discount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        verbose_name='商品折扣',
        db_comment='商品折扣金额'
    )

    # ===== 商品状态信息 =====
    condition_id = models.CharField(
        max_length=50,
        blank=True, null=True,
        verbose_name='商品状况',
        db_comment='商品状况（卖家提供）'
    )

    condition_subtype_id = models.CharField(
        max_length=50,
        blank=True, null=True,
        verbose_name='商品子状况',
        db_comment='商品子状况（卖家提供）'
    )

    condition_note = models.TextField(
        blank=True, null=True,
        verbose_name='商品状况说明',
        db_comment='商品状况说明（卖家提供）'
    )

    # ===== 礼品信息 =====
    gift_message_text = models.TextField(
        blank=True, null=True,
        verbose_name='礼品信息',
        db_comment='礼品信息（买家提供）'
    )

    gift_wrap_level = models.CharField(
        max_length=100,
        blank=True, null=True,
        verbose_name='礼品包装级别',
        db_comment='礼品包装级别（买家提供）'
    )

    # ===== 取消信息 =====
    is_buyer_requested_cancel = models.BooleanField(
        default=False,
        verbose_name='买家请求取消',
        db_comment='买家是否请求取消订单'
    )

    buyer_cancel_reason = models.TextField(
        blank=True, null=True,
        verbose_name='取消原因',
        db_comment='买家取消原因'
    )

    # ===== 促销信息 =====
    promotion_ids = models.JSONField(
        default=list,
        blank=True, null=True,
        verbose_name='商品促销ID',
        db_comment='商品促销ID列表'
    )

    # ===== 其他信息 =====
    points_monetary_value_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        verbose_name='积分成本',
        db_comment='积分成本（日本站会有此数据）'
    )

    scheduled_delivery_start_date = models.DateTimeField(
        blank=True, null=True,
        verbose_name='计划交货开始日期',
        db_comment='计划交货开始日期'
    )

    scheduled_delivery_end_date = models.DateTimeField(
        blank=True, null=True,
        verbose_name='计划交货结束日期',
        db_comment='计划交货结束日期'
    )

    price_designation = models.CharField(
        max_length=50,
        blank=True, null=True,
        verbose_name='B2B价格',
        db_comment='B2B价格标识'
    )

    customized_json = models.JSONField(
        default=dict,
        blank=True, null=True,
        verbose_name='订单定制化信息',
        db_comment='订单定制化信息JSON'
    )

    attachments = models.JSONField(
        default=list,
        blank=True, null=True,
        verbose_name='附件信息',
        db_comment='附件信息列表'
    )

    # ===== 写入时间 =====
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='创建时间',
        db_comment='明细写入时间'
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='更新时间',
        db_comment='最后更新时间'
    )

    class Meta:
        db_table = 'amazon_order_item_full_detail'
        db_table_comment = '亚马逊订单商品明细详情表（从详情接口获取，一次性写入）'
        verbose_name = '亚马逊订单商品详情'
        verbose_name_plural = verbose_name
        unique_together = [['order', 'order_item_id']]

    def __str__(self):
        return f"{self.order.amazon_order_id} - {self.seller_sku}"


class AmazonListing(models.Model):
    """
    Listing 数据库
    唯一约束：同一个领星店铺（站点）内，ASIN 不能重复
    """

    class RiskLevelChoice(models.TextChoices):
        UNKNOWN = 'unknown'
        LOW = 'low'
        MEDIUM = 'medium'
        HIGH = 'high'

    id = models.BigAutoField(
        primary_key=True,
        verbose_name='ID',
        db_comment='自增主键'
    )

    asin = models.CharField(
        max_length=10,
        db_index=True,  # 仍为查询热点，加索引
        verbose_name='ASIN',
        db_comment='亚马逊商品编码'
    )

    title = models.CharField(
        max_length=500,
        blank=True,
        null=True,
        verbose_name='标题',
        db_comment='Listing标题'
    )

    # 外键：一个 Listing 属于一个店铺（多对一）
    lingxing_shop = models.ForeignKey(
        'amazon.LingXingAmazonShop',
        on_delete=models.CASCADE,  # 店铺删除则 Listing 删除
        related_name='listings',
        verbose_name='所属领星店铺',
        db_comment='绑定的领星站点店铺'
    )

    # 多对多：侵权词库（一个 ASIN 可能命中多个词，一个词可能关联多个 ASIN）
    tro_words = models.ManyToManyField(
        'theme.TroTable',
        related_name='listings',
        verbose_name='命中侵权词',
        blank=True,
    )

    # 多对多：美标网
    trademarks = models.ManyToManyField(
        'theme.TrademarkInfo',
        related_name='listings',
        verbose_name='命中商标',
        blank=True,
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name='是否在售',
        db_comment='Listing是否处于在售状态'
    )

    risk_level = models.CharField(
        max_length=10,
        choices=RiskLevelChoice.choices,
        default=RiskLevelChoice.UNKNOWN,
        verbose_name="主题风险等级",
        db_comment="主题风险等级",
    )

    # ========== 商品信息字段 ==========

    small_image_url = models.URLField(
        max_length=500,
        blank=True,
        null=True,
        verbose_name='商品缩略图地址',
        db_comment='商品缩略图URL'
    )

    seller_sku = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name='MSKU',
        db_comment='卖家SKU（MSKU）'
    )

    seller_rank = models.IntegerField(
        blank=True,
        null=True,
        verbose_name='排名',
        db_comment='销售排名'
    )

    seller_category_new = models.JSONField(
        default=list,
        blank=True,
        null=True,
        verbose_name='排名所属类别',
        db_comment='排名所属的类别列表，如["Beauty & Personal Care"]'
    )

    # ========== 销量字段 ==========

    volume_1d = models.IntegerField(
        blank=True,
        null=True,
        verbose_name='销量-昨天',
        db_comment='昨天销量'
    )

    volume_7d = models.IntegerField(
        blank=True,
        null=True,
        verbose_name='销量-7天',
        db_comment='7天销量'
    )

    volume_14d = models.IntegerField(
        blank=True,
        null=True,
        verbose_name='销量-14天',
        db_comment='14天销量'
    )

    volume_30d = models.IntegerField(
        blank=True,
        null=True,
        verbose_name='销量-30天',
        db_comment='30天销量'
    )

    # ========== 销售额字段（保留2位小数） ==========

    amount_1d = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        blank=True,
        null=True,
        verbose_name='销售额-昨天',
        db_comment='昨天销售额'
    )

    amount_7d = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        blank=True,
        null=True,
        verbose_name='销售额-7天',
        db_comment='7天销售额'
    )

    amount_14d = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        blank=True,
        null=True,
        verbose_name='销售额-14天',
        db_comment='14天销售额'
    )

    amount_30d = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        blank=True,
        null=True,
        verbose_name='销售额-30天',
        db_comment='30天销售额'
    )

    # ========== 日均销量字段 ==========

    avg_volume_7d = models.IntegerField(
        blank=True,
        null=True,
        verbose_name='日均销量-7日',
        db_comment='7日日均销量'
    )

    avg_volume_14d = models.IntegerField(
        blank=True,
        null=True,
        verbose_name='日均销量-14日',
        db_comment='14日日均销量'
    )

    avg_volume_30d = models.IntegerField(
        blank=True,
        null=True,
        verbose_name='日均销量-30日',
        db_comment='30日日均销量'
    )

    # 下面是基础信息

    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'amazon_listing'
        db_table_comment = 'Listing主表（店铺+ASIN唯一）'
        verbose_name = 'Amazon Listing'
        verbose_name_plural = 'Amazon Listings'

        # 核心约束：同一个店铺内 ASIN 唯一
        constraints = [
            models.UniqueConstraint(
                fields=['lingxing_shop', 'asin'],
                name='uniq_lingxing_shop_asin'
            )
        ]

        # 常用查询索引
        indexes = [
            models.Index(fields=['asin'], name='idx_listing_asin'),
            models.Index(fields=['risk_level'], name='idx_listing_risk'),
            models.Index(fields=['is_active'], name='idx_listing_active'),
            models.Index(fields=['created_at'], name='idx_listing_created'),
        ]

    def __str__(self):
        shop_name = self.lingxing_shop.name if self.lingxing_shop else '未知店铺'
        return f"{shop_name} - {self.asin}"





class AmazonShopUploadRecord(models.Model):
    """
    亚马逊店铺上货记录
    记录每次批量上货的情况
    """
    
    class UploadStatus(models.TextChoices):
        """上货状态枚举"""
        QUEUED = 'queued', '队列中'
        PROCESSING = 'processing', '进行中'
        COMPLETED = 'completed', '完成'
        NEEDS_ACTION = 'needs_action', '需操作'
        DRAFT = 'draft', '已保存为草稿'
        PUBLISHED = 'published', '已发布'
        FAILED = 'failed', '失败'
    
    # 主键：批次编号
    batch_id = models.CharField(
        max_length=20,
        primary_key=True,
        db_comment='批次编号（主键）'
    )
    
    # 文件名
    file_name = models.CharField(
        max_length=255,
        db_comment='上传的文件名'
    )
    
    # 状态
    status = models.CharField(
        max_length=20,
        choices=UploadStatus.choices,
        default=UploadStatus.PROCESSING,
        db_comment='上货状态'
    )
    
    # 上传时间（精确到年月日时分）
    upload_time = models.DateTimeField(
        db_comment='上传时间（年月日时分）'
    )
    
    # 关联店铺
    shop = models.ForeignKey(
        'general.AmazonShop',
        on_delete=models.CASCADE,
        related_name='upload_records',
        db_comment='关联的亚马逊店铺'
    )
    
    # SKU数量统计
    sku_success = models.IntegerField(
        null=True,
        blank=True,
        db_comment='SKU成功数量'
    )
    
    submitted = models.IntegerField(
        null=True,
        blank=True,
        db_comment='已提交数量'
    )
    
    class Meta:
        db_table = 'amazon_shop_upload_record'
        db_table_comment = '亚马逊店铺上货记录表'
        verbose_name = '店铺上货记录'
        verbose_name_plural = verbose_name
        
        # 索引优化
        indexes = [
            models.Index(fields=['shop', 'upload_time'], name='idx_upload_shop_time'),
            models.Index(fields=['status'], name='idx_upload_status'),
            models.Index(fields=['upload_time'], name='idx_upload_time'),
        ]
    
    def __str__(self):
        shop_name = self.shop.shop_name if self.shop else '未知店铺'
        return f"{shop_name} - {self.batch_id} ({self.get_status_display()})"
