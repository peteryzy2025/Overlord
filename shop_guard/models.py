# from django.db import models
#
#
# class ShopAlertThreshold(models.Model):
#     """店铺告警阈值配置（新/旧店铺各一套）"""
#
#     class ShopType(models.TextChoices):
#         NEW = 'new', '新店铺'
#         OLD = 'old', '旧店铺'
#
#     shop_type = models.CharField(
#         '店铺类型',
#         max_length=10,
#         choices=ShopType.choices,  # type: ignore
#         unique=True,
#         db_comment='new=新店铺阈值配置, old=旧店铺阈值配置'
#     )
#
#     alert_threshold_min = models.IntegerField('告警阈值最小值', null=True, blank=True)
#     alert_threshold_mid = models.IntegerField('告警阈值中值', null=True, blank=True)
#     alert_threshold_max = models.IntegerField('告警阈值最大值', null=True, blank=True)
#
#     class Meta:
#         db_table = 'shop_alert_thresholds'
#         verbose_name = '店铺告警阈值'
#         verbose_name_plural = '店铺告警阈值'
#         ordering = ['shop_type']
#
#     def __str__(self):
#         return f"{self.get_shop_type_display()}: {self.alert_threshold_min}/{self.alert_threshold_mid}/{self.alert_threshold_max}"
#
#
# class ShopCompliance(models.Model):
#     """店铺合规总表（已移除渠道相关字段）"""
#
#     # ==================== 通用 Choices ====================
#     LEVEL_CHOICES = [
#         ('low', '低'),
#         ('medium', '中'),
#         ('high', '高'),
#         ('none', '无'),
#     ]
#
#     SHOP_TYPE_CHOICES = [
#         ('old', '旧店铺'),
#         ('new', '新店铺'),
#         ('none', '无'),
#     ]
#
#     PROTECTION_STATUS_CHOICES = [
#         ('unsolve', '未解决'),
#         ('solved', '已解决'),
#         ('none', '无'),
#     ]
#
#     COMPANY_STATUS_CHOICES = [
#         ('healthy', '健康'),
#         ('unhealthy', '不健康'),
#         ('none', '无'),
#     ]
#
#     LICENSE_STATUS_CHOICES = [
#         ('active', '存续'),
#         ('cancelled', '注销'),
#         ('revoked', '撤销'),
#         ('none', '无'),
#     ]
#
#     LAW_PERSON_CHANGE_CHOICES = [
#         ('changed', '变更'),
#         ('unchanged', '未变更'),
#         ('none', '无'),
#     ]
#
#     OPERATING_STATUS_CHOICES = [
#         ('normal', '正常经营'),
#         ('abnormal', '异常经营'),
#         ('none', '无'),
#     ]
#
#     HEALTH_RANK_CHOICES = [
#         ('healthy', '健康'),
#         ('risky', '存在风险'),
#         ('inactive', '停用'),
#         ('none', '无'),
#     ]
#
#     ORDER_STATUS_CHOICES = [
#         ('pending', '待处理'),
#         ('shipped', '已发货'),
#         ('delivered', '已交付'),
#         ('canceled', '已取消'),
#         ('none', '无'),
#     ]
#
#     # ==================== 外键 ====================
#     shop_id = models.OneToOneField(
#         'general.AmazonShop',
#         on_delete=models.CASCADE,
#         related_name='compliance',
#         verbose_name='店铺'
#     )
#
#     # ==================== 字段定义 ====================
#     shop_type = models.CharField(max_length=50, choices=SHOP_TYPE_CHOICES, verbose_name='店铺类型', db_index=True)
#
#     # 1. 店铺风险等级（高中低）
#     alert_level = models.CharField(max_length=20, choices=LEVEL_CHOICES, verbose_name='店铺风险等级', db_index=True)
#     alert_threshold_min = models.IntegerField(verbose_name='告警阈值最小值', null=True, blank=True)
#     alert_threshold_mid = models.IntegerField(verbose_name='告警阈值中值', null=True, blank=True)
#     alert_threshold_max = models.IntegerField(verbose_name='告警阈值最大值', null=True, blank=True)
#     is_in_risk = models.BooleanField(default=False, verbose_name='是否在风险范围内')
#
#     # 2. 消费者法案
#     protection_act_status = models.CharField(
#         max_length=20,
#         choices=PROTECTION_STATUS_CHOICES,
#         verbose_name='消费者法案状态',
#         db_index=True
#     )
#     protection_operating_date = models.DateField(verbose_name='法案操作日期', null=True, blank=True)
#
#     # 3. 法人配合度（高中低）
#     law_contact_level = models.CharField(
#         max_length=20,
#         choices=LEVEL_CHOICES,
#         verbose_name='法人配合度',
#         db_index=True
#     )
#
#     # 4. 公司健康检查
#     company_health_status = models.CharField(
#         max_length=20,
#         choices=COMPANY_STATUS_CHOICES,
#         verbose_name='公司健康状态',
#         db_index=True
#     )
#     business_license_status = models.CharField(
#         max_length=20,
#         choices=LICENSE_STATUS_CHOICES,
#         verbose_name='营业执照状态',
#         db_index=True
#     )
#     company_law_person_change_status = models.CharField(
#         max_length=20,
#         choices=LAW_PERSON_CHANGE_CHOICES,
#         verbose_name='法人变更状态',
#         db_index=True
#     )
#     company_operating_status = models.CharField(
#         max_length=20,
#         choices=OPERATING_STATUS_CHOICES,
#         verbose_name='公司经营状态',
#         db_index=True
#     )
#
#     # 5. 店铺健康检查
#     shop_country = models.CharField(max_length=50, verbose_name='国家', null=True, blank=True, db_index=True)
#     health_rank_arh = models.CharField(max_length=50, verbose_name='店铺健康等级(ARH)', blank=True)
#     three_level_health_rank = models.CharField(
#         max_length=20,
#         choices=HEALTH_RANK_CHOICES,
#         verbose_name='店铺三级健康等级',
#         db_index=True
#     )
#
#     # 6. 领星主题新奇特（高中低）
#     theme_novelty_risk = models.CharField(
#         max_length=20,
#         choices=LEVEL_CHOICES,
#         verbose_name='主题新奇特风险',
#         db_index=True
#     )
#
#     # 7. 订单统计
#     recent_order_count = models.IntegerField(default=0, verbose_name='近期订单数量(近30天)')
#     pending_order_count = models.IntegerField(default=0, verbose_name='待处理订单数量')
#     last_order_date = models.DateTimeField(null=True, blank=True, verbose_name='最后订单日期', db_index=True)
#     last_order_status = models.CharField(
#         max_length=20,
#         choices=ORDER_STATUS_CHOICES,
#         default='none',
#         verbose_name='最后订单状态'
#     )
#     created_at = models.DateTimeField('创建时间', auto_now_add=True)
#     updated_at = models.DateTimeField('更新时间', auto_now=True)
#
#     class Meta:
#         db_table = 'shop_guard_compliance'
#         verbose_name = '店铺合规检查'
#         verbose_name_plural = '店铺合规检查'
#         indexes = [
#             models.Index(fields=['alert_level', 'is_in_risk']),
#             models.Index(fields=['law_contact_level']),  # 移除了 channel_risk_level
#             models.Index(fields=['shop_country', 'three_level_health_rank']),
#             models.Index(fields=['company_health_status', 'business_license_status']),
#             models.Index(fields=['protection_act_status', 'alert_level']),
#             models.Index(fields=['last_order_date', 'recent_order_count']),
#             models.Index(fields=['pending_order_count', 'alert_level']),
#         ]
#
#     def __str__(self):
#         return f"{self.shop_id.shop_name}"
