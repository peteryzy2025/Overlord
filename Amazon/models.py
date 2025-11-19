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
    amazon_order_id = models.CharField(max_length=50, primary_key=True, db_comment='亚马逊订单ID')

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

    created_at = models.DateTimeField(auto_now_add=True, db_comment='创建时间')
    updated_at = models.DateTimeField(auto_now=True, db_comment='更新时间')

    class Meta:
        db_table = 'amazon_orders'
        db_table_comment = '亚马逊订单主表'

    def __str__(self):
        return f"{self.amazon_order_id} ({self.order_status})"


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

    class Meta:
        db_table = 'amazon_order_item'
        db_table_comment = '亚马逊订单商品明细'
