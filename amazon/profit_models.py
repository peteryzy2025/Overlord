# amazon/profit_models.py
"""
领星 MSKU维度订单利润报表模型
从 /basicOpen/finance/mreport/OrderProfit 接口同步
"""

from django.db import models


class AmazonMSKUDailyProfit(models.Model):
    """
    领星 - MSKU维度每日利润报表
    唯一键：sid + seller_sku(MSKU) + sync_date
    """

    # ========== 关联键 ==========
    lxshop = models.ForeignKey(
        'amazon.LingXingAmazonShop',
        on_delete=models.CASCADE,
        related_name='msku_daily_profits',
        db_comment='关联的领星店铺'
    )

    sid = models.BigIntegerField(
        db_index=True,
        db_comment='店铺ID（冗余，用于唯一键）'
    )

    seller_sku = models.CharField(
        max_length=100,
        db_index=True,
        db_comment='MSKU（卖家SKU）'
    )

    sync_date = models.DateField(
        db_index=True,
        db_comment='数据日期（YYYY-MM-DD）'
    )

    # ========== 币种 ==========
    currency_code = models.CharField(
        max_length=10,
        blank=True, null=True,
        db_comment='币种代码'
    )

    currency_icon = models.CharField(
        max_length=10,
        blank=True, null=True,
        db_comment='币种符号'
    )

    # ========== 销量 ==========
    volume = models.IntegerField(
        default=0,
        db_comment='总销量'
    )

    afn_volume = models.IntegerField(
        default=0,
        db_comment='FBA销量'
    )

    mfn_volume = models.IntegerField(
        default=0,
        db_comment='FBM销量'
    )

    ad_volume = models.IntegerField(
        default=0,
        db_comment='广告销量'
    )

    replacement_quantity = models.IntegerField(
        default=0,
        db_comment='补换货量'
    )

    multi_channel_volume = models.IntegerField(
        default=0,
        db_comment='多渠道销量'
    )

    avg_volume = models.DecimalField(
        max_digits=12, decimal_places=2,
        default=0,
        db_comment='平均日销'
    )

    # ========== 退货退款 ==========
    return_quantity = models.IntegerField(
        default=0,
        db_comment='退货量'
    )

    return_rate = models.DecimalField(
        max_digits=8, decimal_places=4,
        blank=True, null=True,
        db_comment='退货率'
    )

    refund_quantity = models.DecimalField(
        max_digits=12, decimal_places=2,
        blank=True, null=True,
        db_comment='退款量'
    )

    refund_amount = models.DecimalField(
        max_digits=12, decimal_places=2,
        blank=True, null=True,
        db_comment='退款金额'
    )

    refund_amount_rate = models.DecimalField(
        max_digits=8, decimal_places=4,
        blank=True, null=True,
        db_comment='退款率'
    )

    # ========== 销售额 ==========
    amount = models.DecimalField(
        max_digits=12, decimal_places=2,
        blank=True, null=True,
        db_comment='销售额'
    )

    tax_amount = models.DecimalField(
        max_digits=12, decimal_places=2,
        blank=True, null=True,
        db_comment='含税销售额'
    )

    net_amount = models.DecimalField(
        max_digits=12, decimal_places=2,
        blank=True, null=True,
        db_comment='净销售额'
    )

    avg_net_amount = models.DecimalField(
        max_digits=12, decimal_places=2,
        blank=True, null=True,
        db_comment='平均售价'
    )

    afn_amount = models.DecimalField(
        max_digits=12, decimal_places=2,
        blank=True, null=True,
        db_comment='FBA销售额'
    )

    mfn_amount = models.DecimalField(
        max_digits=12, decimal_places=2,
        blank=True, null=True,
        db_comment='FBM销售额'
    )

    shipping_cost = models.DecimalField(
        max_digits=12, decimal_places=2,
        blank=True, null=True,
        db_comment='买家运费'
    )

    promotion_discount = models.DecimalField(
        max_digits=12, decimal_places=2,
        blank=True, null=True,
        db_comment='促销折扣'
    )

    pm_discount = models.DecimalField(
        max_digits=12, decimal_places=2,
        blank=True, null=True,
        db_comment='价格折扣'
    )

    sp_discount = models.DecimalField(
        max_digits=12, decimal_places=2,
        blank=True, null=True,
        db_comment='配送折扣'
    )

    # ========== 广告销售 ==========
    ad_sales_amount = models.DecimalField(
        max_digits=12, decimal_places=2,
        blank=True, null=True,
        db_comment='广告销售额'
    )

    ad_sales_amount_sp = models.DecimalField(
        max_digits=12, decimal_places=2,
        blank=True, null=True,
        db_comment='SP广告销售额'
    )

    ad_sales_amount_sd = models.DecimalField(
        max_digits=12, decimal_places=2,
        blank=True, null=True,
        db_comment='SD广告销售额'
    )

    ad_sales_amount_sb = models.DecimalField(
        max_digits=12, decimal_places=2,
        blank=True, null=True,
        db_comment='SB广告销售额'
    )

    ad_sales_amount_sbv = models.DecimalField(
        max_digits=12, decimal_places=2,
        blank=True, null=True,
        db_comment='SBV广告销售额'
    )

    ad_volume_sp = models.BigIntegerField(
        blank=True, null=True,
        db_comment='SP广告销量'
    )

    ad_volume_sd = models.BigIntegerField(
        blank=True, null=True,
        db_comment='SD广告销量'
    )

    ad_volume_sb = models.BigIntegerField(
        blank=True, null=True,
        db_comment='SB广告销量'
    )

    ad_volume_sbv = models.BigIntegerField(
        blank=True, null=True,
        db_comment='SBV广告销量'
    )

    # ========== 平台/FBA费用 ==========
    selling_fee = models.DecimalField(
        max_digits=12, decimal_places=2,
        blank=True, null=True,
        db_comment='平台费'
    )

    fulfillment_fee = models.DecimalField(
        max_digits=12, decimal_places=2,
        blank=True, null=True,
        db_comment='FBA发货费（含退货费）'
    )

    other_order_fee = models.DecimalField(
        max_digits=12, decimal_places=2,
        blank=True, null=True,
        db_comment='其他订单费用'
    )

    fba_fulfillment_fee = models.DecimalField(
        max_digits=12, decimal_places=2,
        blank=True, null=True,
        db_comment='FBA发货费（订单列表对应）'
    )

    fba_storage_fee = models.DecimalField(
        max_digits=12, decimal_places=2,
        blank=True, null=True,
        db_comment='月仓储费'
    )

    # ========== 广告花费 ==========
    spend = models.DecimalField(
        max_digits=12, decimal_places=2,
        blank=True, null=True,
        db_comment='总花费'
    )

    ads_sp_cost = models.DecimalField(
        max_digits=12, decimal_places=2,
        blank=True, null=True,
        db_comment='SP花费'
    )

    ads_sb_cost = models.DecimalField(
        max_digits=12, decimal_places=2,
        blank=True, null=True,
        db_comment='SB花费'
    )

    ads_sbv_cost = models.DecimalField(
        max_digits=12, decimal_places=2,
        blank=True, null=True,
        db_comment='SBV花费'
    )

    ads_sd_cost = models.DecimalField(
        max_digits=12, decimal_places=2,
        blank=True, null=True,
        db_comment='SD花费'
    )

    # ========== 成本 ==========
    purchase_costs = models.DecimalField(
        max_digits=12, decimal_places=2,
        blank=True, null=True,
        db_comment='采购成本'
    )

    avg_purchase_costs = models.DecimalField(
        max_digits=12, decimal_places=2,
        blank=True, null=True,
        db_comment='采购均价'
    )

    logistics_costs = models.DecimalField(
        max_digits=12, decimal_places=2,
        blank=True, null=True,
        db_comment='头程成本'
    )

    avg_logistics_costs = models.DecimalField(
        max_digits=12, decimal_places=2,
        blank=True, null=True,
        db_comment='头程均价'
    )

    other_costs = models.DecimalField(
        max_digits=12, decimal_places=2,
        blank=True, null=True,
        db_comment='其他成本'
    )

    avg_other_costs = models.DecimalField(
        max_digits=12, decimal_places=2,
        blank=True, null=True,
        db_comment='其他均价'
    )

    total_costs = models.DecimalField(
        max_digits=12, decimal_places=2,
        blank=True, null=True,
        db_comment='合计成本'
    )

    # ========== 利润 ==========
    gross_profit = models.DecimalField(
        max_digits=12, decimal_places=2,
        blank=True, null=True,
        db_comment='毛利润'
    )

    gross_margin = models.DecimalField(
        max_digits=8, decimal_places=4,
        blank=True, null=True,
        db_comment='毛利率'
    )

    avg_gross_profit = models.DecimalField(
        max_digits=12, decimal_places=2,
        blank=True, null=True,
        db_comment='平均毛利润'
    )

    net_gross_margin = models.DecimalField(
        max_digits=8, decimal_places=4,
        blank=True, null=True,
        db_comment='净毛利率'
    )

    # ========== 占比/率 ==========
    selling_fee_rate = models.DecimalField(
        max_digits=8, decimal_places=4,
        blank=True, null=True,
        db_comment='平台费占比'
    )

    fulfillment_fee_rate = models.DecimalField(
        max_digits=8, decimal_places=4,
        blank=True, null=True,
        db_comment='FBA发货费占比'
    )

    spend_rate = models.DecimalField(
        max_digits=8, decimal_places=4,
        blank=True, null=True,
        db_comment='广告费率'
    )

    total_stock_fee_rate = models.DecimalField(
        max_digits=8, decimal_places=4,
        blank=True, null=True,
        db_comment='仓储费占比'
    )

    # ========== 推广/仓储/其他核心费用 ==========
    promotion_fee = models.DecimalField(
        max_digits=12, decimal_places=2,
        blank=True, null=True,
        db_comment='推广费'
    )

    off_site_promotion_fee = models.DecimalField(
        max_digits=12, decimal_places=2,
        blank=True, null=True,
        db_comment='站外推广费'
    )

    total_stock_fee = models.DecimalField(
        max_digits=12, decimal_places=2,
        blank=True, null=True,
        db_comment='仓储费'
    )

    # ========== shared_ 核心费用字段（参与利润计算） ==========
    shared_fba_inbound_convenience_fee = models.DecimalField(
        max_digits=12, decimal_places=2,
        blank=True, null=True,
        db_comment='入库配置费'
    )

    shared_fba_customer_return_fee = models.DecimalField(
        max_digits=12, decimal_places=2,
        blank=True, null=True,
        db_comment='FBA退回卖家费'
    )

    shared_fba_overage_fee = models.DecimalField(
        max_digits=12, decimal_places=2,
        blank=True, null=True,
        db_comment='超量仓储费'
    )

    shared_fba_disposal_fee = models.DecimalField(
        max_digits=12, decimal_places=2,
        blank=True, null=True,
        db_comment='FBA销毁费'
    )

    shared_fba_removal_fee = models.DecimalField(
        max_digits=12, decimal_places=2,
        blank=True, null=True,
        db_comment='FBA移除费'
    )

    shared_reimbursements = models.DecimalField(
        max_digits=12, decimal_places=2,
        blank=True, null=True,
        db_comment='赔偿收入'
    )

    shared_fba_liquidation_proceeds = models.DecimalField(
        max_digits=12, decimal_places=2,
        blank=True, null=True,
        db_comment='清算收入'
    )

    shared_fba_liquidation_proceeds_adjustments = models.DecimalField(
        max_digits=12, decimal_places=2,
        blank=True, null=True,
        db_comment='清算调整'
    )

    shared_adjustments_fee = models.DecimalField(
        max_digits=12, decimal_places=2,
        blank=True, null=True,
        db_comment='调整费'
    )

    shared_fba_storage_fee = models.DecimalField(
        max_digits=12, decimal_places=2,
        blank=True, null=True,
        db_comment='月仓储费差异'
    )

    shared_long_term_storage_fee = models.DecimalField(
        max_digits=12, decimal_places=2,
        blank=True, null=True,
        db_comment='长期仓储费差异'
    )

    shared_fba_inbound_defect_fee = models.DecimalField(
        max_digits=12, decimal_places=2,
        blank=True, null=True,
        db_comment='入库缺陷费'
    )

    shared_fba_international_inbound_fee = models.DecimalField(
        max_digits=12, decimal_places=2,
        blank=True, null=True,
        db_comment='FBA国际物流运费'
    )

    shared_amazon_partnered_carrier_shipment_fee = models.DecimalField(
        max_digits=12, decimal_places=2,
        blank=True, null=True,
        db_comment='合作承运费'
    )

    shared_other_fba_inventory_fees = models.DecimalField(
        max_digits=12, decimal_places=2,
        blank=True, null=True,
        db_comment='其他仓储费'
    )

    shared_fba_transaction_customer_return_fee = models.DecimalField(
        max_digits=12, decimal_places=2,
        blank=True, null=True,
        db_comment='亚马逊物流客户退货费'
    )

    shared_item_fee_adjustment = models.DecimalField(
        max_digits=12, decimal_places=2,
        blank=True, null=True,
        db_comment='库存调整费用'
    )

    shared_cost_of_advertising = models.DecimalField(
        max_digits=12, decimal_places=2,
        blank=True, null=True,
        db_comment='差异分摊'
    )

    shared_safe_t_reimbursement = models.DecimalField(
        max_digits=12, decimal_places=2,
        blank=True, null=True,
        db_comment='Safe-T索赔'
    )

    shared_netco_transaction = models.DecimalField(
        max_digits=12, decimal_places=2,
        blank=True, null=True,
        db_comment='Netco交易'
    )

    shared_clawbacks = models.DecimalField(
        max_digits=12, decimal_places=2,
        blank=True, null=True,
        db_comment='追索收入'
    )

    shared_commingling_vat_income = models.DecimalField(
        max_digits=12, decimal_places=2,
        blank=True, null=True,
        db_comment='混合VAT收入'
    )

    shared_amazon_shipping_reimbursement = models.DecimalField(
        max_digits=12, decimal_places=2,
        blank=True, null=True,
        db_comment='亚马逊运费赔偿'
    )

    shared_others = models.DecimalField(
        max_digits=12, decimal_places=2,
        blank=True, null=True,
        db_comment='其他'
    )

    # ========== 收入类 ==========
    inventory_credit = models.DecimalField(
        max_digits=12, decimal_places=2,
        blank=True, null=True,
        db_comment='FBA库存赔偿'
    )

    cost_of_points_granted = models.DecimalField(
        max_digits=12, decimal_places=2,
        blank=True, null=True,
        db_comment='积分收入'
    )

    total_other_granted = models.DecimalField(
        max_digits=12, decimal_places=2,
        blank=True, null=True,
        db_comment='其它收入'
    )

    gift_wrap_credits = models.DecimalField(
        max_digits=12, decimal_places=2,
        blank=True, null=True,
        db_comment='包装收入'
    )

    a_to_z_guarantee_claims = models.DecimalField(
        max_digits=12, decimal_places=2,
        blank=True, null=True,
        db_comment='买家交易保障索赔额'
    )

    selling_other_fee = models.DecimalField(
        max_digits=12, decimal_places=2,
        blank=True, null=True,
        db_comment='平台其他费'
    )

    # ========== 商品信息 ==========
    item_name = models.CharField(
        max_length=500,
        blank=True, null=True,
        db_comment='品名'
    )

    small_image_url = models.URLField(
        max_length=500,
        blank=True, null=True,
        db_comment='图片链接'
    )

    principal_names = models.CharField(
        max_length=200,
        blank=True, null=True,
        db_comment='listing负责人'
    )

    is_parent = models.BooleanField(
        default=False,
        db_comment='是否有子项'
    )

    # ========== 简单数组（JSONField） ==========
    parent_asins = models.JSONField(
        default=list,
        blank=True, null=True,
        db_comment='父ASIN列表'
    )

    categories = models.JSONField(
        default=list,
        blank=True, null=True,
        db_comment='分类列表'
    )

    brands = models.JSONField(
        default=list,
        blank=True, null=True,
        db_comment='品牌列表'
    )

    # ========== 时间戳 ==========
    created_at = models.DateTimeField(
        auto_now_add=True,
        db_comment='创建时间'
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        db_comment='更新时间'
    )

    class Meta:
        db_table = 'amazon_msku_daily_profit'
        db_table_comment = '领星-MSKU维度每日利润报表'
        verbose_name = 'MSKU每日利润'
        verbose_name_plural = verbose_name

        constraints = [
            models.UniqueConstraint(
                fields=['sid', 'seller_sku', 'sync_date'],
                name='uniq_msku_profit_sid_sku_date'
            )
        ]

        indexes = [
            models.Index(fields=['sid', 'sync_date'], name='idx_msku_profit_sid_date'),
            models.Index(fields=['sync_date'], name='idx_msku_profit_date'),
            models.Index(fields=['seller_sku'], name='idx_msku_profit_sku'),
            models.Index(fields=['lxshop'], name='idx_msku_profit_shop'),
        ]

    def __str__(self):
        return f"{self.lxshop.name if self.lxshop else self.sid} - {self.seller_sku} - {self.sync_date}"


class AmazonMSKUDailyProfitPriceList(models.Model):
    """
    MSKU每日利润 - 商品基础信息列表（price_list）
    """

    profit = models.ForeignKey(
        'amazon.AmazonMSKUDailyProfit',
        on_delete=models.CASCADE,
        related_name='price_list',
        db_comment='关联的利润记录'
    )

    principal_uids = models.CharField(
        max_length=100,
        blank=True, null=True,
        db_comment='负责人UID'
    )

    local_sku = models.CharField(
        max_length=100,
        blank=True, null=True,
        db_comment='本地SKU'
    )

    item_name = models.CharField(
        max_length=500,
        blank=True, null=True,
        db_comment='标题'
    )

    cate_title = models.CharField(
        max_length=200,
        blank=True, null=True,
        db_comment='分类'
    )

    local_name = models.CharField(
        max_length=200,
        blank=True, null=True,
        db_comment='本地名称'
    )

    sid = models.CharField(
        max_length=20,
        blank=True, null=True,
        db_comment='店铺ID'
    )

    is_delete = models.CharField(
        max_length=10,
        blank=True, null=True,
        db_comment='是否删除'
    )

    brand_title = models.CharField(
        max_length=200,
        blank=True, null=True,
        db_comment='品牌'
    )

    volume = models.IntegerField(
        default=0,
        db_comment='销量'
    )

    small_main_image_url = models.URLField(
        max_length=500,
        blank=True, null=True,
        db_comment='缩略图'
    )

    site_url = models.URLField(
        max_length=500,
        blank=True, null=True,
        db_comment='站点链接'
    )

    parent_asin = models.CharField(
        max_length=30,
        blank=True, null=True,
        db_comment='父ASIN'
    )

    seller_sku = models.CharField(
        max_length=100,
        blank=True, null=True,
        db_comment='MSKU'
    )

    asin = models.CharField(
        max_length=30,
        blank=True, null=True,
        db_comment='ASIN'
    )

    status = models.CharField(
        max_length=20,
        blank=True, null=True,
        db_comment='状态'
    )

    class Meta:
        db_table = 'amazon_msku_daily_profit_price_list'
        db_table_comment = 'MSKU每日利润-商品基础信息列表'
        verbose_name = '利润商品信息'
        verbose_name_plural = verbose_name

    def __str__(self):
        return f"{self.asin} - {self.seller_sku}"


class AmazonMSKUDailyProfitLocalInfo(models.Model):
    """
    MSKU每日利润 - 本地商品信息（local_infos）
    """

    profit = models.ForeignKey(
        'amazon.AmazonMSKUDailyProfit',
        on_delete=models.CASCADE,
        related_name='local_infos',
        db_comment='关联的利润记录'
    )

    local_sku = models.CharField(
        max_length=100,
        blank=True, null=True,
        db_comment='本地SKU'
    )

    local_name = models.CharField(
        max_length=200,
        blank=True, null=True,
        db_comment='本地名称'
    )

    class Meta:
        db_table = 'amazon_msku_daily_profit_local_info'
        db_table_comment = 'MSKU每日利润-本地商品信息'
        verbose_name = '利润本地商品信息'
        verbose_name_plural = verbose_name

    def __str__(self):
        return f"{self.local_sku} - {self.local_name}"


class AmazonMSKUDailyProfitASIN(models.Model):
    """
    MSKU每日利润 - ASIN列表（asins）
    """

    profit = models.ForeignKey(
        'amazon.AmazonMSKUDailyProfit',
        on_delete=models.CASCADE,
        related_name='asins',
        db_comment='关联的利润记录'
    )

    asin = models.CharField(
        max_length=30,
        blank=True, null=True,
        db_comment='ASIN'
    )

    asin_url = models.URLField(
        max_length=500,
        blank=True, null=True,
        db_comment='ASIN链接'
    )

    class Meta:
        db_table = 'amazon_msku_daily_profit_asin'
        db_table_comment = 'MSKU每日利润-ASIN列表'
        verbose_name = '利润ASIN'
        verbose_name_plural = verbose_name

    def __str__(self):
        return self.asin


class AmazonMSKUDailyProfitCountry(models.Model):
    """
    MSKU每日利润 - 店铺国家列表（seller_store_countries）
    """

    profit = models.ForeignKey(
        'amazon.AmazonMSKUDailyProfit',
        on_delete=models.CASCADE,
        related_name='seller_store_countries',
        db_comment='关联的利润记录'
    )

    country = models.CharField(
        max_length=100,
        blank=True, null=True,
        db_comment='国家'
    )

    name = models.CharField(
        max_length=100,
        blank=True, null=True,
        db_comment='名称'
    )

    class Meta:
        db_table = 'amazon_msku_daily_profit_country'
        db_table_comment = 'MSKU每日利润-店铺国家列表'
        verbose_name = '利润店铺国家'
        verbose_name_plural = verbose_name

    def __str__(self):
        return self.country
