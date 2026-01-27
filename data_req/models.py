# data_req/models.py
from django.db import models
from general.models import User


class DataRequirement(models.Model):
    """数据部需求管理主表"""

    # 类型选择
    TYPE_CHOICES = [
        ('simple', '任务'),
        ('system', '系统'),
    ]

    # 状态选择（新增 claimed 状态）
    STATUS_CHOICES = [
        ('pending', '待领取'),
        ('claimed', '已领取'),
        ('developing', '开发中'),
        ('paused', '已暂停'),
        ('completed', '已完成'),
        ('cancelled', '已取消'),
    ]

    # 优先级选择
    PRIORITY_CHOICES = [
        ('P0', 'P0-紧急'),
        ('P1', 'P1-高'),
        ('P2', 'P2-中'),
        ('P3', 'P3-低'),
    ]

    # 基础信息
    name = models.CharField('需求名称', max_length=200)
    requirement_type = models.CharField('需求类型', max_length=10, choices=TYPE_CHOICES, default='simple')

    # 层级关系
    parent = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='children',
        verbose_name='父级需求(包含关系)'
    )
    extends_from = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='extended_tasks',
        verbose_name='延伸自(前置任务)'
    )

    # 人员信息
    requester = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='requested_requirements',
        verbose_name='需求人'
    )
    developer = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='developed_requirements',
        verbose_name='开发者'
    )

    # 状态与优先级
    status = models.CharField('状态', max_length=20, choices=STATUS_CHOICES, default='pending')
    priority = models.CharField('优先级', max_length=2, choices=PRIORITY_CHOICES, default='P2')

    # 难度系数（改为小数）
    score = models.FloatField('难度系数', null=True, blank=True, help_text='仅简单任务填写，系统任务自动计算子任务之和')

    # 备注与暂停原因
    remark = models.TextField('备注', blank=True)
    pause_reason = models.TextField('暂停原因', blank=True, help_text='暂停状态时填写')

    # 时间节点（新增 start_date）
    publish_date = models.DateField('需求发布日期')
    claim_date = models.DateTimeField('需求领取日期', null=True, blank=True)
    start_date = models.DateTimeField('开发开始日期', null=True, blank=True)  # 新增字段：点击"开始开发"时记录
    expected_finish = models.DateTimeField('预计完成时间', null=True, blank=True)
    finish_date = models.DateTimeField('实际完成日期', null=True, blank=True)

    # 系统字段
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '数据部需求'
        verbose_name_plural = '数据部需求'
        ordering = ['-created_at']
        db_table = 'data_requirement'

    def __str__(self):
        return f"{self.name} ({self.get_requirement_type_display()})"

    def get_actual_score(self):
        """获取实际难度系数（系统类型自动计算子任务之和）"""
        if self.requirement_type == 'simple':
            return self.score or 0
        else:
            # 递归计算所有子简单任务的难度系数之和
            total = 0
            for child in self.children.all():
                total += child.get_actual_score()
            return total

    def get_development_duration(self):
        """计算实际开发时长（小时），基于Timeline计算"""
        from datetime import timedelta

        # 获取所有开始和结束时间段
        timelines = self.timelines.filter(action__in=['start', 'pause', 'complete']).order_by('timestamp')

        total_duration = timedelta()
        current_start = None

        for timeline in timelines:
            if timeline.action == 'start':
                current_start = timeline.timestamp
            elif timeline.action in ['pause', 'complete'] and current_start:
                total_duration += timeline.timestamp - current_start
                current_start = None

        # 如果当前正在开发中，计算到当前时间
        if current_start and self.status == 'developing':
            from django.utils import timezone
            total_duration += timezone.now() - current_start

        return total_duration.total_seconds() / 3600  # 返回小时数


class RequirementTimeline(models.Model):
    """需求时间线（记录所有状态变更）"""

    ACTION_CHOICES = [
        ('claim', '领取任务'),
        ('unclaim', '退领任务'),      # 新增：退领
        ('start', '开始开发'),         # 新增：开始开发（从claimed到developing）
        ('pause', '暂停开发'),
        ('resume', '恢复开发'),
        ('complete', '完成开发'),
        ('cancel', '取消任务'),
        ('restart', '重新开发'),
    ]

    requirement = models.ForeignKey(
        DataRequirement,
        on_delete=models.CASCADE,
        related_name='timelines',
        verbose_name='关联需求'
    )
    action = models.CharField('操作类型', max_length=20, choices=ACTION_CHOICES)
    timestamp = models.DateTimeField('操作时间', auto_now_add=True)
    operator = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='requirement_operations',
        verbose_name='操作人'
    )
    reason = models.TextField('原因/备注', blank=True, help_text='退领、暂停、取消等操作时填写原因')

    class Meta:
        verbose_name = '需求时间线'
        verbose_name_plural = '需求时间线'
        ordering = ['-timestamp']
        db_table = 'requirement_timeline'

    def __str__(self):
        return f"{self.requirement.name} - {self.get_action_display()} - {self.timestamp.strftime('%Y-%m-%d %H:%M')}"