from django.db import models

class BaseModel(models.Model):# 基础模型,为所有模型提供创建时间和更新时间
    create_time = models.DateTimeField(auto_now_add=True, verbose_name='创建时间', db_index=True)
    update_time = models.DateTimeField(auto_now=True, verbose_name='更新时间', db_index=True)

    class Meta:
        abstract = True

#店铺风险
class ShopRisk(BaseModel):# 店铺风险
    SHOP_TYPE_CHOICES = [
        ('old', '旧店铺'),
        ('new', '新店铺'),
        ('none', '无'),
    ]
    ALERT_LEVEL_CHOICES = [
        ('low', '低'),
        ('medium', '中'),
        ('high', '高'),
        ('none', '无'),
    ]

    shop_id = models.OneToOneField('general.AmazonShop', on_delete=models.CASCADE, related_name='shop_risk', verbose_name='店铺ID')
    shop_type = models.CharField(max_length=50, choices=SHOP_TYPE_CHOICES, verbose_name='店铺类型', db_index=True)
    alert_threshold_min = models.IntegerField(verbose_name='告警阈值最小值')
    alert_threshold_mid = models.IntegerField(verbose_name='告警阈值中值')
    alert_threshold_max = models.IntegerField(verbose_name='告警阈值最大值')
    is_in_risk = models.BooleanField(default=False, verbose_name='是否在风险范围内')#无风险 低风险 中风险 高风险
    alert_level = models.CharField(max_length=50, choices=ALERT_LEVEL_CHOICES, verbose_name='告警等级', db_index=True)

    class Meta:
        db_table = 'shop_guard_shop_risk'
        verbose_name = '店铺风险'
        verbose_name_plural = '店铺风险'
        indexes = [
            models.Index(fields=['shop_type', 'alert_level']),
        ]

    def __str__(self):
        return self.shop_id.name


#消费者法案
class CustomerProtectionAct(BaseModel):
    PROTECTION_ACT_STATUS_CHOICES = [
        ('unsolved', '未解决'),
        ('solved', '已解决'),
        ('none', '无'),
    ]

    shop_id = models.OneToOneField('general.AmazonShop', on_delete=models.CASCADE, related_name='customer_protection_act', verbose_name='店铺ID')
    protection_act_status = models.CharField(max_length=50, choices=PROTECTION_ACT_STATUS_CHOICES, verbose_name='消费者法案状态', db_index=True)
    operating_date = models.DateField(verbose_name='操作日期', null=True, blank=True)

    class Meta:
        db_table = 'shop_guard_customer_protection_act'
        verbose_name = '消费者法案'
        verbose_name_plural = '消费者法案'

    def __str__(self):
        return self.shop_id.name


# 法人配合度
class LawPersonContactLevel(BaseModel):
    CONTACT_LEVEL_CHOICES = [
        ('low', '低'),
        ('medium', '中'),
        ('high', '高'),
        ('none', '无'),
    ]

    shop_id = models.OneToOneField('general.AmazonShop', on_delete=models.CASCADE, related_name='law_person_contact_level', verbose_name='店铺ID')
    contact_level = models.CharField(max_length=50, choices=CONTACT_LEVEL_CHOICES, verbose_name='法人配合度', db_index=True)

    class Meta:
        db_table = 'shop_guard_law_person_contact_level'
        verbose_name = '法人配合度'
        verbose_name_plural = '法人配合度'

    def __str__(self):
        return self.shop_id.name


# 店铺渠道风险
class ShopChannelRisk(BaseModel):
    CHANNEL_RISK_CHOICES = [
        ('low', '低'),
        ('medium', '中'),
        ('high', '高'),
        ('none', '无'),
    ]
    shop_channel = models.CharField(max_length=50, verbose_name='店铺渠道', unique=True)
    channel_risk = models.CharField(max_length=50, choices=CHANNEL_RISK_CHOICES, verbose_name='店铺渠道风险', db_index=True)

    class Meta:
        db_table = 'shop_guard_shop_channel_risk'
        verbose_name = '店铺渠道风险'
        verbose_name_plural = '店铺渠道风险'

    def __str__(self):
        return self.shop_channel


class CompanyHealthCheck(BaseModel):
    STATUS_CHOICES = [
        ('healthy', '健康'),
        ('unhealthy', '不健康'),
        ('none', '无'),
    ]
    BUSINESS_LICENSE_STATUS_CHOICES = [
        ('active', '存续'),
        ('cancelled', '注销'),
        ('revoked', '撤销'),
        ('none', '无'),
    ]
    LAW_PERSON_STATUS_CHOICES = [
        ('changed', '变更'),
        ('unchanged', '未变更'),
        ('none', '无'),
    ]
    OPERATING_STATUS_CHOICES = [
        ('normal', '正常经营'),
        ('abnormal', '异常经营'),
        ('none', '无'),
    ]

    shop_id = models.OneToOneField('general.AmazonShop', on_delete=models.CASCADE, related_name='company_health_check', verbose_name='店铺ID')
    status = models.CharField(max_length=50, choices=STATUS_CHOICES, verbose_name='公司健康状态', db_index=True)
    business_license_status = models.CharField(max_length=50, choices=BUSINESS_LICENSE_STATUS_CHOICES, verbose_name='公司营业执照状态', db_index=True)
    law_person_status = models.CharField(max_length=50, choices=LAW_PERSON_STATUS_CHOICES, verbose_name='公司法人状态', db_index=True)
    operating_status = models.CharField(max_length=50, choices=OPERATING_STATUS_CHOICES, verbose_name='公司经营状态', db_index=True)

    class Meta:
        db_table = 'shop_guard_company_health_check'
        verbose_name = '公司健康检查'
        verbose_name_plural = '公司健康检查'
        indexes = [
            models.Index(fields=['status', 'operating_status']),
        ]

    def __str__(self):
        return self.shop_id.name


class ShopHealthCheck(BaseModel):
    THREE_LEVEL_HEALTH_RANK_CHOICES = [
        ('healthy', '健康'),
        ('risky', '存在风险'),
        ('inactive', '停用'),
        ('none', '无'),
    ]

    shop_id = models.OneToOneField('general.AmazonShop', on_delete=models.CASCADE, related_name='shop_health_check', verbose_name='店铺ID')
    country = models.CharField(max_length=50, verbose_name='国家', null=True, blank=True, db_index=True)
    health_rank_arh = models.CharField(max_length=50, verbose_name='店铺健康等级(ARH)')
    three_level_health_rank = models.CharField(max_length=50, choices=THREE_LEVEL_HEALTH_RANK_CHOICES, verbose_name='店铺三级健康等级', db_index=True)

    class Meta:
        db_table = 'shop_guard_shop_health_check'
        verbose_name = '店铺健康检查'
        verbose_name_plural = '店铺健康检查'
        indexes = [
            models.Index(fields=['country', 'three_level_health_rank']),
        ]

    def __str__(self):
        return self.shop_id.name


class LingxingOrderData(BaseModel):
    ORDER_STATUS_CHOICES = [
        ('pending', '待处理'),
        ('shipped', '已发货'),
        ('delivered', '已交付'),
        ('canceled', '已取消'),
        ('none', '无'),
    ]

    shop_id = models.OneToOneField('general.AmazonShop', on_delete=models.CASCADE, related_name='lingxing_order_data', verbose_name='店铺ID')
    order_id = models.CharField(max_length=50, verbose_name='订单ID', unique=True)
    order_date = models.DateTimeField(verbose_name='订单日期', db_index=True)
    order_status = models.CharField(max_length=50, choices=ORDER_STATUS_CHOICES, verbose_name='订单状态', db_index=True)

    class Meta:
        db_table = 'shop_guard_lingxing_order_data'
        verbose_name = '领星订单数据'
        verbose_name_plural = '领星订单数据'
        indexes = [
            models.Index(fields=['shop_id', 'order_date']),
            models.Index(fields=['shop_id', 'order_status']),
        ]

    def __str__(self):
        return self.shop_id.name


class CorePerformanceMetrics(BaseModel):  # 核心绩效指标
    shop_id = models.OneToOneField('general.AmazonShop', on_delete=models.CASCADE, related_name='core_performance_metrics', verbose_name='店铺ID')
    ODR = models.DecimalField(max_digits=5, decimal_places=2, verbose_name='订单缺陷率(%)', help_text='0-100之间')
    CR = models.DecimalField(max_digits=5, decimal_places=2, verbose_name='订单取消率(%)', help_text='0-100之间')
    VTR = models.DecimalField(max_digits=5, decimal_places=2, verbose_name='延迟发货率(%)', help_text='0-100之间')
    OnTimeRate = models.DecimalField(max_digits=5, decimal_places=2, verbose_name='准时交付率(%)', help_text='0-100之间')

    class Meta:
        db_table = 'shop_guard_core_performance_metrics'
        verbose_name = '核心绩效指标'
        verbose_name_plural = '核心绩效指标'
    def __str__(self):
        return self.shop_id.name


class PolicyCompliance(BaseModel):  #  政策合规性
    shop_id = models.OneToOneField('general.AmazonShop', on_delete=models.CASCADE, related_name='policy_compliance', verbose_name='店铺ID')
    policy_compliance_status = models.CharField(max_length=50, verbose_name='政策合规性状态', db_index=True)

    class Meta:
        db_table = 'shop_guard_policy_compliance'
        verbose_name = '政策合规性'
        verbose_name_plural = '政策合规性'
    def __str__(self):
        return self.shop_id.name



class LingxingThemeNovelty(BaseModel):
    RISK_LEVEL_CHOICES = [
        ('low', '低'),
        ('medium', '中'),
        ('high', '高'),
        ('none', '无'),
    ]

    shop_id = models.OneToOneField('general.AmazonShop', on_delete=models.CASCADE, related_name='lingxing_theme_novelty', verbose_name='店铺ID')
    risk_level = models.CharField(max_length=50, choices=RISK_LEVEL_CHOICES, verbose_name='店铺风险等级', db_index=True)

    class Meta:
        db_table = 'shop_guard_lingxing_theme_novelty'
        verbose_name = '领星主题新奇特'
        verbose_name_plural = '领星主题新奇特'

    def __str__(self):
        return self.shop_id.name
