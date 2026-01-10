# Task/models.py

from django.db import models
from general.models import User
from django.utils import timezone


class Task(models.Model):
    """
    主任务表
    存储任务的基本信息和状态
    """
    # 状态定义
    STATUS_DRAFT = 'draft'
    STATUS_PENDING = 'pending'
    STATUS_IN_PROGRESS = 'in_progress'
    STATUS_COMPLETED = 'completed'
    STATUS_FAILED = 'failed'
    STATUS_CANCELLED = 'cancelled'

    STATUS_CHOICES = [
        (STATUS_DRAFT, '草稿'),
        (STATUS_PENDING, '待执行'),
        (STATUS_IN_PROGRESS, '进行中'),
        (STATUS_COMPLETED, '已完成'),
        (STATUS_FAILED, '执行失败'),
        (STATUS_CANCELLED, '已取消'),
    ]

    id = models.BigAutoField(primary_key=True, verbose_name='主键ID', db_comment='任务主键ID')

    # 任务基本信息
    title = models.CharField('任务标题', max_length=200, db_comment='任务标题')
    task_no = models.CharField('任务单号', max_length=50, unique=True, editable=False, db_comment='自动生成的任务单号')

    # 任务状态
    status = models.CharField(
        '任务状态',
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_DRAFT,
        db_comment='任务当前状态'
    )

    # 关联关系
    created_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='created_tasks',
        verbose_name='创建人',
        db_comment='任务的创建人'
    )
    owner = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='owned_tasks',
        verbose_name='任务所有者',
        db_comment='任务的所有者（执行人）'
    )

    # 时间戳
    created_at = models.DateTimeField('创建时间', auto_now_add=True, db_comment='任务创建时间')
    updated_at = models.DateTimeField('更新时间', auto_now=True, db_comment='任务最后更新时间')
    submitted_at = models.DateTimeField('提交时间', null=True, blank=True, db_comment='任务提交时间（非草稿状态）')

    class Meta:
        db_table = 'task_tasks'  # 数据库表名
        verbose_name = '任务'
        verbose_name_plural = '任务列表'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'created_at'], name='idx_task_status_created'),
            models.Index(fields=['owner', 'status'], name='idx_task_owner_status'),
            models.Index(fields=['task_no'], name='idx_task_no_unique'),
        ]

    def __str__(self):
        return f"{self.task_no} - {self.title}"

    def save(self, *args, **kwargs):
        """
        保存时自动生成任务单号
        """
        if not self.task_no:
            from task.utils.task_utils import generate_task_no
            self.task_no = generate_task_no(self.created_by)

        # 状态变更时更新时间
        if self.status != getattr(self, '_original_status', None):
            self.updated_at = timezone.now()
            if self.status in ['pending', 'in_progress'] and not self.submitted_at:
                self.submitted_at = timezone.now()

        super().save(*args, **kwargs)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._original_status = self.status


class SubTask(models.Model):
    """
    子任务表
    存储任务的子任务详情和参数
    """
    # 子任务类型定义
    TYPE_CUSTOM_UPLOAD = 'custom_upload'
    TYPE_TEMU_EXPORT = 'temu_export'

    TYPE_CHOICES = [
        (TYPE_CUSTOM_UPLOAD, '定制上架'),
        (TYPE_TEMU_EXPORT, 'Temu导单'),
    ]

    id = models.BigAutoField(primary_key=True, verbose_name='主键ID', db_comment='子任务主键ID')

    # 关联主任务
    task = models.ForeignKey(
        Task,
        on_delete=models.CASCADE,
        related_name='subtasks',
        verbose_name='所属任务',
        db_comment='关联的主任务ID'
    )

    # 子任务基本信息
    subtask_type = models.CharField(
        '子任务类型',
        max_length=20,
        choices=TYPE_CHOICES,
        db_comment='子任务类型：custom_upload/temu_export'
    )

    # 执行顺序
    order = models.IntegerField(
        '执行顺序',
        default=0,
        db_comment='子任务的执行顺序（用于前端拖拽排序）'
    )

    # 子任务参数（JSON存储）
    params = models.JSONField(
        '任务参数',
        default=dict,
        db_comment='子任务的具体参数（不同类型结构不同）'
    )
    """
    custom_upload参数示例：
    {
        "product_ids": ["1715", "1561"],      # 产品ID列表
        "mode": "adapt",                      # 模式：adapt/fill
        "gallery_account": "侯益山",          # 图库账号
        "gallery_path": "/path/to/gallery",   # 图库目录
        "craft_type": "print",                # 工艺类型：print/emboss/laser
        "recognize_theme": false,             # 是否识别主题
        "export_quantity": 50,                # 汇出数量
        "export_shop_ids": [1, 2, 3]          # 汇出店铺ID列表
    }

    temu_export参数示例：
    {
        "export_shop_ids": [101, 102]         # 导单店铺ID列表
    }
    """

    # 执行状态
    is_executed = models.BooleanField(
        '是否已执行',
        default=False,
        db_comment='子任务是否已执行'
    )
    executed_at = models.DateTimeField(
        '执行时间',
        null=True,
        blank=True,
        db_comment='子任务实际执行时间'
    )
    execution_result = models.JSONField(
        '执行结果',
        default=dict,
        null=True,
        blank=True,
        db_comment='子任务执行结果（成功/失败详情）'
    )

    # 时间戳
    created_at = models.DateTimeField('创建时间', auto_now_add=True, db_comment='子任务创建时间')
    updated_at = models.DateTimeField('更新时间', auto_now=True, db_comment='子任务最后更新时间')

    class Meta:
        db_table = 'task_subtasks'  # 数据库表名
        verbose_name = '子任务'
        verbose_name_plural = '子任务列表'
        ordering = ['order', 'id']
        indexes = [
            models.Index(fields=['task', 'order'], name='idx_subtask_task_order'),
            models.Index(fields=['subtask_type', 'is_executed'], name='idx_subtask_type_status'),
        ]

    def __str__(self):
        return f"{self.task.task_no} - {self.get_subtask_type_display()} #{self.order + 1}"

    def save(self, *args, **kwargs):
        """
        保存时自动更新主任务时间
        """
        super().save(*args, **kwargs)

        # 更新主任务更新时间
        if self.task:
            self.task.updated_at = timezone.now()
            self.task.save(update_fields=['updated_at'])


class TaskTemplate(models.Model):
    """
    任务模板表（个人级）
    存储用户自定义的任务模板配置
    """
    id = models.BigAutoField(primary_key=True, verbose_name='主键ID', db_comment='模板主键ID')

    # 模板基本信息
    name = models.CharField(
        '模板名称',
        max_length=100,
        db_comment='模板的名称'
    )
    description = models.TextField(
        '模板描述',
        blank=True,
        null=True,
        db_comment='模板的详细描述'
    )

    # 模板内容（JSON存储子任务配置）
    content = models.JSONField(
        '模板内容',
        default=list,
        db_comment='模板包含的子任务配置数组'
    )
    """
    内容示例：
    [
        {
            "type": "custom_upload",
            "params": {
                "mode": "adapt",
                "gallery_account": "侯益山",
                "craft_type": "print",
                "recognize_theme": false
            }
        },
        {
            "type": "temu_export",
            "params": {}
        }
    ]
    """

    # 创建信息
    created_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='created_templates',
        verbose_name='创建人',
        db_comment='模板的创建人'
    )
    created_at = models.DateTimeField('创建时间', auto_now_add=True, db_comment='模板创建时间')

    class Meta:
        db_table = 'task_templates'  # 数据库表名
        verbose_name = '任务模板'
        verbose_name_plural = '任务模板列表'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['created_by', 'created_at'], name='idx_template_user_created'),
            models.Index(fields=['name'], name='idx_template_name'),
        ]

    def __str__(self):
        return f"{self.name} - {self.created_by.first_name}"

    def is_owned_by(self, user):
        """
        检查模板是否属于指定用户
        """
        return self.created_by_id == user.id