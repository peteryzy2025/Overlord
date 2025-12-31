# Yuser/models.py

from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()


# 1. 考核主表
class PerformanceAssessment(models.Model):
    ASSESSMENT_TYPES = [
        ('temu_operation', 'Temu运营'),
        ('amazon_operation', '亚马逊运营'),
        ('amazon_assistant', '亚马逊运营助理'),
    ]

    STATUS_DRAFT = 'draft'
    STATUS_PENDING_MEMBER = 'pending_member'
    STATUS_PENDING_LEADER = 'pending_leader'
    STATUS_CONFIRMED = 'confirmed'
    STATUS_CHOICES = [
        (STATUS_DRAFT, '组长评分中'),
        (STATUS_PENDING_MEMBER, '待组员确认'),
        (STATUS_PENDING_LEADER, '待组长最终确认'),
        (STATUS_CONFIRMED, '已确认锁定'),
    ]

    # 关联绩效目标（获取target_orders）
    performance_target = models.ForeignKey(
        'General.PersonalPerformanceTarget',
        on_delete=models.PROTECT,
        verbose_name='关联绩效目标'
    )

    # 基本信息
    assess_type = models.CharField('考核类型', max_length=20, choices=ASSESSMENT_TYPES)
    month = models.CharField('考核月份', max_length=7)  # YYYY-MM
    employee = models.ForeignKey(User, related_name='assessments', on_delete=models.PROTECT)
    leader = models.ForeignKey(User, related_name='assessments_as_leader', on_delete=models.SET_NULL, null=True)

    # 业绩指标（订单件数）
    target_orders = models.IntegerField('目标订单件数')
    actual_orders = models.IntegerField('实际订单件数')
    achievement_rate = models.DecimalField('达成率', max_digits=5, decimal_places=2)
    performance_score = models.DecimalField('业绩得分', max_digits=5, decimal_places=2)

    # 流程状态
    status = models.CharField('考核状态', max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    is_locked = models.BooleanField('是否锁定', default=False)

    # 确认记录
    member_confirmed_at = models.DateTimeField('组员确认时间', null=True, blank=True)
    leader_confirmed_at = models.DateTimeField('组长最终确认时间', null=True, blank=True)

    # 最终得分（冗余字段，优化查询）
    final_score = models.DecimalField('最终得分', max_digits=5, decimal_places=2, null=True, blank=True)

    # 时间戳
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        db_table = 'performance_assessments'
        verbose_name = '绩效考核记录'
        verbose_name_plural = verbose_name
        # 每个人每月每种类型只能有一条考核
        unique_together = ['employee', 'month', 'assess_type']
        indexes = [
            models.Index(fields=['month', 'employee', 'assess_type']),
            models.Index(fields=['leader', 'status', 'month']),
        ]


# 2. 评分明细表
class PerformanceScoreDetail(models.Model):
    assessment = models.ForeignKey(
        PerformanceAssessment,
        related_name='score_details',
        on_delete=models.CASCADE,
        verbose_name='关联考核'
    )
    item_key = models.CharField('评分项标识', max_length=50)
    score_value = models.DecimalField('得分', max_digits=5, decimal_places=2)

    class Meta:
        db_table = 'performance_score_details'
        verbose_name = '评分明细'
        verbose_name_plural = verbose_name
        unique_together = ['assessment', 'item_key']


# 3. 评分项配置表
class AssessmentItemConfig(models.Model):
    CATEGORIES = [
        ('performance', '业绩指标'),
        ('behavior', '行为考核'),
        ('bonus', '加分项'),
    ]
    INPUT_TYPES = [
        ('readonly', '只读显示'),
        ('number', '数字输入'),
        ('select', '下拉选择'),
    ]

    assess_type = models.CharField('考核类型', max_length=20, choices=PerformanceAssessment.ASSESSMENT_TYPES)
    item_key = models.CharField('评分项标识', max_length=50)
    item_name = models.CharField('评分项名称', max_length=200)
    scoring_criteria = models.TextField(
        '评分标准说明',
        blank=True,
        null=True,
        help_text='详细的评分规则和标准说明'
    )
    category = models.CharField('评分类别', max_length=20, choices=CATEGORIES)
    max_score = models.DecimalField('满分值', max_digits=5, decimal_places=2)
    weight = models.DecimalField('类别内权重', max_digits=3, decimal_places=2, default=1.0)
    input_type = models.CharField('输入类型', max_length=20, choices=INPUT_TYPES, default='number')
    options = models.JSONField('下拉选项配置', null=True, blank=True)
    sort_order = models.IntegerField('排序号', default=0)

    class Meta:
        db_table = 'assessment_item_configs'
        verbose_name = '评分项配置'
        verbose_name_plural = verbose_name
        unique_together = ['assess_type', 'item_key']
        ordering = ['assess_type', 'sort_order']


# 4. 历史快照表
class AssessmentHistory(models.Model):
    """仅在组长最终确认时生成一次快照"""
    assessment = models.ForeignKey(
        PerformanceAssessment,
        on_delete=models.CASCADE,
        verbose_name='原始考核记录'
    )
    snapshot_data = models.JSONField('快照数据')
    snapshot_type = models.CharField('快照类型', max_length=20, default='final_confirm')
    created_at = models.DateTimeField('提交的快照时间', auto_now_add=True)

    class Meta:
        db_table = 'assessment_histories'
        verbose_name = '考核历史快照'
        verbose_name_plural = verbose_name
        indexes = [
            models.Index(fields=['assessment', '-created_at']),
        ]

