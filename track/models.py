# Track/models.py
from django.db import models
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType


class Factory(models.Model):
    """工厂信息表"""
    name = models.CharField(max_length=100, unique=True, db_comment="工厂名称")

    def __str__(self):
        return self.name

    class Meta:
        db_table="Track_factory"
        verbose_name = "工厂"
        verbose_name_plural = "工厂"


class Courier(models.Model):
    """物流商信息表"""

    code = models.CharField(max_length=50, unique=True, db_comment="物流商代码，如 'usps'")
    name_cn = models.CharField(max_length=100, blank=True, db_comment="物流商中文名称")
    name_en = models.CharField(max_length=100, blank=True, db_comment="物流商英文名称")
    homepage = models.URLField(blank=True, db_comment="物流商官网地址")

    def __str__(self):
        return f"{self.name_en or self.name_cn} ({self.code})"

    class Meta:
        db_table = "Track_courier"
        verbose_name = "物流商基础信息表"
        verbose_name_plural = "物流商"


class Tracking(models.Model):
    """物流运单主表（新增6个字段）"""
    track_no = models.CharField(max_length=100, unique=True, db_index=True, db_comment="运单号（唯一标识）")

    courier = models.ForeignKey(Courier, on_delete=models.SET_NULL, null=True, blank=True, db_comment="关联物流商")
    factory = models.ForeignKey(
        Factory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_index=True,
        db_comment="关联工厂"
    )

    transit_status = models.CharField(max_length=50, blank=True, db_index=True,
                                      db_comment="当前运输状态，如 'DELIVERED'、'IN_TRANSIT'")
    transit_sub_status = models.CharField(max_length=50, blank=True, db_comment="运输子状态")
    cancel_bool= models.BooleanField(default=False, db_comment="运单是否取消")
    remark = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        db_comment="物流单号备注信息"
    )

    order_time = models.DateTimeField(null=True, blank=True, db_comment="订单下单时间")
    delivered_time = models.DateTimeField(null=True, blank=True, db_index=True, db_comment="签收时间")
    last_update_time = models.DateTimeField(null=True, blank=True, db_index=True,
                                            db_comment="最后轨迹更新时间（用于异常监控）")
    create_time = models.DateTimeField(auto_now_add=True, db_comment="本系统导入时间（北京时间）")
    next_update_time = models.DateTimeField(null=True, blank=True, db_comment="建议下次查询时间")

    stay_days = models.PositiveIntegerField(null=True, blank=True, db_comment="停滞天数")
    transit_days = models.PositiveIntegerField(null=True, blank=True, db_comment="运输天数")
    delivered_days = models.PositiveIntegerField(null=True, blank=True, db_comment="总签收天数")

    ship_from = models.CharField(max_length=10, blank=True, db_comment="发货地国家代码")
    ship_to = models.CharField(max_length=10, blank=True, db_comment="收货地国家代码")
    shipment_type = models.CharField(max_length=100, blank=True, db_comment="运输方式")

    raw_data = models.JSONField(null=True, blank=True, db_comment="原始API返回数据（备份用）")

    # ===== 新增：订单关联与冗余字段 =====
    # 1. 平台来源（amazon/temu/other）
    platform = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        db_index=True,
        db_comment="平台来源（amazon/temu/other）"
    )

    # 2. 订单号（显示用）
    order_id = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        db_index=True,
        db_comment="订单号（冗余）"
    )

    # 3. 运营分组
    ops_group = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        db_index=True,
        db_comment="运营分组（冗余）"
    )

    # 4. 运营姓名
    ops_name = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        db_index=True,
        db_comment="运营姓名（冗余）"
    )

    # 5. 6. GenericForeignKey关联字段
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        db_comment="关联订单类型"
    )
    object_id = models.PositiveIntegerField(
        null=True,
        blank=True,
        db_comment="关联订单ID"
    )
    content_object = GenericForeignKey('content_type', 'object_id')

    def __str__(self):
        return self.track_no

    class Meta:
        db_table = "Track_tracking"
        verbose_name = "物流运单主表"
        verbose_name_plural = "运单"
        ordering = ['-create_time']
        indexes = [
            models.Index(fields=['transit_status']),
            models.Index(fields=['delivered_time']),
            models.Index(fields=['last_update_time']),
            models.Index(fields=['courier']),
            models.Index(fields=['platform']),  # 新增索引
            models.Index(fields=['order_id']),  # 新增索引
            models.Index(fields=['ops_group']),  # 新增索引
            models.Index(fields=['ops_name']),  # 新增索引
        ]


class TrackingDetail(models.Model):
    """物流轨迹明细表"""

    tracking = models.ForeignKey(Tracking, on_delete=models.CASCADE, related_name='details', db_comment="关联运单")

    event_time = models.DateTimeField(db_index=True, db_comment="事件发生时间（原样存储API返回的本地时间）")
    address = models.CharField(max_length=200, blank=True, db_comment="事件地点")
    event_detail = models.CharField(max_length=500, db_comment="事件描述，如 'Delivered, In/At Mailbox'")
    transit_sub_status = models.CharField(max_length=50, blank=True, db_comment="该事件子状态")

    def __str__(self):
        return f"{self.event_time} | {self.event_detail[:50]}"

    class Meta:
        db_table = "Track_trackingdetail"
        verbose_name = "物流轨迹明细表"
        verbose_name_plural = "轨迹明细"
        ordering = ['-event_time']
        indexes = [
            models.Index(fields=['event_time']),
        ]


class PlatformChoice(models.TextChoices):
    YZG = "yzg", "艺之冠"
    SDS = "sds", "SDS"
    FN = "fn", "蜂鸟"
    S2B = "s2b", "S2B"
    YJL = "yjl", "艺捷乐"
    ZW = "zw", "指纹"

class ExternalProcurementProduct(models.Model):
    """外采平台产品总表"""
    product_id = models.PositiveIntegerField(blank=True, null=True, db_comment="产品编号")
    product_name = models.CharField(max_length=255, null=True, blank=True, db_comment="产品名称")
    is_listed = models.BooleanField(default=False, db_comment="是否上架")
    color = models.CharField(max_length=50, null=True, blank=True, db_comment="颜色")
    size = models.CharField(max_length=255, null=True, blank=True, db_comment="规格")
    divi_color = models.CharField(max_length=50, null=True, blank=True, db_comment="divi颜色")
    divi_size = models.CharField(max_length=255, null=True, blank=True, db_comment="divi尺码")
    min_order_qty = models.CharField(max_length=100, null=True, blank=True, db_comment="起批量")
    purchase_unit_origin_price = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, db_comment="采购原单价")
    purchase_unit_now_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, db_comment="采购现单价")
    platform = models.CharField(max_length=20, choices=PlatformChoice.choices, db_comment="外采平台")

    class Meta:
        db_table = "Track_external_procurement_products"
        verbose_name = "外采平台产品"
        verbose_name_plural = "外采平台产品"
        indexes = [
            models.Index(fields=['platform', 'product_id']),
            models.Index(fields=['platform', 'is_listed']),
            models.Index(fields=['platform', 'color', 'size']),
        ]

    def __str__(self):
        return self.product_name or f"{self.get_platform_display()}-{self.product_id or self.pk or 'unknown'}"

