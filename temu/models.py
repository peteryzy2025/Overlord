from django.db import models

# Create your models here.
# temu/models.py
from django.db import models, transaction
from django.utils import timezone
from django.contrib.postgres.fields import JSONField  # if using Postgres older versions
from django.db.models import JSONField as DjJSONField  # Django >= 3.1 has built-in JSONField
from decimal import Decimal
import datetime

# Use built-in JSONField if available
try:
    JSONFIELD = DjJSONField
except Exception:
    JSONFIELD = JSONField


class LingXingTemuShop(models.Model):
    """
    领星-Temu 店铺（使用 store_id 作为主键）
    例子来自你给的数据：store_id, sid, store_name, platform_code, ...
    """
    store_id = models.CharField(max_length=64, primary_key=True, db_comment='领星返回的 store_id（主键）')
    sid = models.CharField(max_length=64, blank=True, null=True, db_comment='原始 sid')
    store_name = models.CharField(max_length=255, blank=True, null=True, db_comment='店铺名称')
    platform_code = models.CharField(max_length=32, blank=True, null=True, db_comment='平台编码')
    platform_name = models.CharField(max_length=100, blank=True, null=True, db_comment='平台名称（Temu半托管）')
    currency = models.CharField(max_length=10, blank=True, null=True, db_comment='币种')
    is_sync = models.SmallIntegerField(blank=True, null=True, db_comment='是否同步（0/1）')
    status = models.SmallIntegerField(blank=True, null=True, db_comment='状态（1=正常等）')
    country_code = models.CharField(max_length=10, blank=True, null=True, db_comment='店铺国家码')

    # 绑定本地 Temu 店铺（General.TemuShop）
    temu_shop = models.ForeignKey(
        'general.TemuShop',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='lingxing_temu_shops',
        db_comment='绑定的本地Temu店铺'
    )

    created_at = models.DateTimeField(auto_now_add=True, db_comment='创建时间')
    updated_at = models.DateTimeField(auto_now=True, db_comment='更新时间')

    class Meta:
        db_table = 'lingxing_temu_shop'
        db_table_comment = '领星-Temu店铺信息表'

    def __str__(self):
        return f"{self.store_name} ({self.store_id})"


class TemuOrder(models.Model):
    """
    Temu 订单主表
    - global_order_no 作为主键
    - 提取高频查询字段，提升性能
    - 保留原始 JSON 数据作为快照
    """
    # ========== 主键与关联 ==========
    global_order_no = models.CharField(
        max_length=80,
        primary_key=True,
        db_comment='领星返回的 global_order_no（主键）'
    )

    # 关联领星店铺
    lingxing_shop = models.ForeignKey(
        'LingXingTemuShop',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='orders',
        db_comment='关联的领星 Temu 店铺',
        db_index=True,  # 显式添加索引
    )

    # 冗余的本地店铺关联（可选）
    temu_shop = models.ForeignKey(
        'general.TemuShop',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='temu_orders',
        db_comment='关联的本地 TemuShop（冗余）',
        db_index=True,
    )

    # ========== 订单基础信息 ==========
    reference_no = models.CharField(max_length=80, blank=True, null=True, db_comment='reference_no')
    order_from_name = models.CharField(max_length=100, blank=True, null=True, db_comment='订单来源')
    delivery_type = models.SmallIntegerField(blank=True, null=True, db_comment='配送类型')
    split_type = models.CharField(max_length=20, blank=True, null=True, db_comment='拆分类型')

    # 订单状态（不定义choices，避免猜测）
    status = models.SmallIntegerField(blank=True, null=True, db_comment='订单状态代码', db_index=True)

    # 仓库信息
    wid = models.CharField(max_length=64, blank=True, null=True, db_comment='仓库ID')
    warehouse_name = models.CharField(max_length=255, blank=True, null=True, db_comment='仓库名称')

    # ========== 关键时间字段（DateTimeField）==========
    # 注意：入库时需将 Unix 时间戳转换为 datetime 对象
    global_purchase_time = models.DateTimeField(blank=True, null=True, db_comment='下单时间', db_index=True)
    global_payment_time = models.DateTimeField(blank=True, null=True, db_comment='付款时间')
    global_review_time = models.DateTimeField(blank=True, null=True, db_comment='审核时间')
    global_distribution_time = models.DateTimeField(blank=True, null=True, db_comment='分配时间')
    global_print_time = models.DateTimeField(blank=True, null=True, db_comment='打印时间')
    global_mark_time = models.DateTimeField(blank=True, null=True, db_comment='标记时间')
    global_delivery_time = models.DateTimeField(blank=True, null=True, db_comment='发货时间')

    # 创建时间（字符串格式，保留原始值）
    global_create_time = models.CharField(max_length=50, blank=True, null=True, db_comment='创建时间字符串')

    # 币种
    amount_currency = models.CharField(max_length=10, blank=True, null=True, db_comment='币种')

    # ========== 从 JSON 中提取的高频查询字段 ==========
    # 地址信息（用于区域统计、物流筛选）
    receiver_country_code = models.CharField(
        max_length=10,
        blank=True,
        null=True,
        db_index=True,
        db_comment='收货国家码（从 address_info 提取）'
    )
    postal_code = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        db_index=True,
        db_comment='邮编（从 address_info 提取）'
    )
    city = models.CharField(max_length=100, blank=True, null=True, db_comment='城市（从 address_info 提取）')

    # 物流信息（用于物流追踪）
    tracking_number = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        db_index=True,
        db_comment='物流单号（从 logistics_info 提取）'
    )
    logistics_provider_name = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        db_comment='物流服务商（从 logistics_info 提取）'
    )

    # 订单金额（用于财务统计）
    order_total_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        blank=True,
        null=True,
        db_comment='订单总金额（从 transaction_info 提取）'
    )

    # 买家信息（部分脱敏）
    buyer_name_masked = models.CharField(max_length=200, blank=True, null=True, db_comment='买家姓名（脱敏）')
    buyer_email_masked = models.CharField(max_length=200, blank=True, null=True, db_comment='买家邮箱（脱敏）')

    # ========== 原始 JSON 数据（保留快照） ==========
    order_tag = JSONFIELD(blank=True, null=True, db_comment='订单标签数组')
    pending_order_tag = JSONFIELD(blank=True, null=True)
    exception_order_tag = JSONFIELD(blank=True, null=True)

    buyers_info = JSONFIELD(blank=True, null=True, db_comment='买家信息（原始 JSON）')
    address_info = JSONFIELD(blank=True, null=True, db_comment='收货地址（原始 JSON）')
    platform_info = JSONFIELD(blank=True, null=True, db_comment='平台信息数组')
    payment_info = JSONFIELD(blank=True, null=True, db_comment='支付信息数组')
    logistics_info = JSONFIELD(blank=True, null=True, db_comment='物流信息（原始 JSON）')
    transaction_info = JSONFIELD(blank=True, null=True, db_comment='交易信息数组')

    supplier_id = models.CharField(max_length=64, blank=True, null=True, db_comment='供应商ID')
    is_delete = models.SmallIntegerField(default=0, db_comment='是否删除标志')
    order_custom_fields = JSONFIELD(blank=True, null=True, db_comment='自定义字段')

    # ========== 本地记录时间 ==========
    created_at = models.DateTimeField(auto_now_add=True, db_comment='创建时间（本地）')
    updated_at = models.DateTimeField(auto_now=True, db_comment='更新时间（本地）')

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
    divi_if_order = models.BooleanField(
        default=False,
        verbose_name='是否DIVI订单',
        db_comment='是否在DIVI系统存在对应订单'
    )
    class Meta:
        db_table = 'temu_orders'
        db_table_comment = 'Temu 订单主表'

        # 关键索引
        indexes = [
            models.Index(fields=['status', 'global_purchase_time'], name='idx_status_time'),
            models.Index(fields=['lingxing_shop', 'status'], name='idx_shop_status'),
            models.Index(fields=['receiver_country_code', 'postal_code'], name='idx_address'),
            models.Index(fields=['tracking_number'], name='idx_tracking'),
        ]

    def __str__(self):
        shop_name = self.lingxing_shop.store_name if self.lingxing_shop else '未知店铺'
        return f"{shop_name} - {self.global_order_no}"


class TemuOrderItem(models.Model):
    """
    Temu 订单商品明细
    """
    # ========== 关联订单 ==========
    order = models.ForeignKey(
        TemuOrder,
        to_field="global_order_no",
        db_column="global_order_no",
        on_delete=models.CASCADE,
        related_name="items",
        db_index=True,
    )

    # ========== 商品基础信息 ==========
    global_item_no = models.CharField(max_length=80, blank=True, null=True, db_comment='globalItemNo')
    platform_order_no = models.CharField(max_length=120, blank=True, null=True, db_index=True, db_comment='平台订单号')
    order_item_no = models.CharField(max_length=120, blank=True, null=True, db_comment='订单项编号')
    item_from_name = models.CharField(max_length=80, blank=True, null=True, db_comment='商品来源')

    # SKU 信息
    msku = models.CharField(max_length=200, blank=True, null=True, db_index=True, db_comment='商品MSKU')
    local_sku = models.CharField(max_length=200, blank=True, null=True, db_index=True, db_comment='本地SKU')
    product_no = models.CharField(max_length=80, blank=True, null=True, db_comment='商品编号')

    # 商品描述
    title = models.TextField(blank=True, null=True, db_comment='商品标题')
    variant_attr = models.CharField(max_length=255, blank=True, null=True, db_comment='变体属性')

    # ========== 价格与数量 ==========
    unit_price_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'), db_comment='单价')
    item_price_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'),
                                            db_comment='商品总价')
    quantity = models.IntegerField(default=0, db_comment='数量')

    # ========== 状态与类型 ==========
    platform_status = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        db_comment='平台状态',
        db_index=True
    )
    type = models.CharField(max_length=50, blank=True, null=True, db_comment='商品类型')

    # ========== 原始 JSON 数据 ==========
    data_json = JSONFIELD(blank=True, null=True, db_comment='原始 data_json 字段')
    item_custom_fields = JSONFIELD(blank=True, null=True, db_comment='自定义字段')

    is_delete = models.SmallIntegerField(default=0, db_comment='是否删除')

    # ========== 本地记录时间 ==========
    created_at = models.DateTimeField(auto_now_add=True, db_comment='创建时间')
    updated_at = models.DateTimeField(auto_now=True, db_comment='更新时间')

    class Meta:
        db_table = 'temu_order_item'
        db_table_comment = 'Temu 订单商品明细'

        # 关键索引
        indexes = [
            models.Index(fields=['msku', 'platform_status'], name='idx_msku_status'),
            models.Index(fields=['platform_order_no'], name='idx_platform_order'),
        ]

    def __str__(self):
        return f"{self.order.global_order_no} - {self.msku or self.product_no}"




# class TemuSKU(models.Model):
#     """
#     Temu SKU 映射表
#     - 存储 Temu 平台的 SKU 与本地 SKU 的映射关系
#     """
#     temu_sku = models.CharField(max_length=200, primary_key=True, db_comment='Temu平台SKU货号（主键）')
#
#     created_at = models.DateTimeField(auto_now_add=True, db_comment='创建时间')
#     updated_at = models.DateTimeField(auto_now=True, db_comment='更新时间')
#
#     class Meta:
#         db_table = 'temu_sku_mapping'
#         db_table_comment = 'Temu SKU 映射表'
#
#         # 关键索引
#         indexes = [
#             models.Index(fields=['local_sku'], name='idx_local_sku'),
#         ]
#
#     def __str__(self):
#         return f"{self.temu_sku} -> {self.local_sku or '未映射'}"
#
# class TemuPackingSpecification():
#     """
#     Temu 包装规格表
#     - 存储 Temu 平台的包装规格信息
#     """
#     specification_id = models.CharField(max_length=64, primary_key=True, db_comment='包装规格ID（主键）')
#     length_cm = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True, db_comment='长度（cm）')
#     width_cm = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True, db_comment='宽度（cm）')
#     height_cm = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True, db_comment='高度（cm）')
#     weight_kg = models.DecimalField(max_digits=10, decimal_places=3, blank=True, null=True, db_comment='重量（kg）')
#
#     created_at = models.DateTimeField(auto_now_add=True, db_comment='创建时间')
#     updated_at = models.DateTimeField(auto_now=True, db_comment='更新时间')
#
#     class Meta:
#         db_table = 'temu_packing_specification'
#         db_table_comment = 'Temu 包装规格表'
#
#     def __str__(self):
#         return f"{self.specification_name} ({self.specification_id})"