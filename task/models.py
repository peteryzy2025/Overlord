# Task/models.py

from django.db import models
from general.models import User
from django.utils import timezone


class TaskStatus(models.TextChoices):
    """任务状态"""
    DRAFT = 'draft', '草稿'
    PENDING = 'pending', '待执行'
    IN_PROGRESS = 'in_progress', '进行中'
    COMPLETED = 'completed', '已完成'
    FAILED = 'failed', '执行失败'
    CANCELLED = 'cancelled', '已取消'


class TaskType(models.TextChoices):
    """任务类型"""
    STANDARD = 'standard', '标准任务'
    PRODUCT_REQUIREMENT = 'product_requirement', '产品需求'


class Task(models.Model):
    """
    主任务表
    存储任务的基本信息和状态
    """

    id = models.BigAutoField(primary_key=True, verbose_name='主键ID', db_comment='任务主键ID')

    # 任务基本信息
    title = models.CharField('任务标题', max_length=200, db_comment='任务标题')
    task_no = models.CharField('任务单号', max_length=50, unique=True, editable=False, db_comment='自动生成的任务单号')

    # 任务状态
    status = models.CharField(
        '任务状态',
        max_length=20,
        choices=TaskStatus.choices,
        default=TaskStatus.DRAFT,
        db_comment='任务当前状态'
    )

    # 任务类型
    task_type = models.CharField(
        '任务类型',
        max_length=50,
        choices=TaskType.choices,
        default=TaskType.STANDARD,
        db_comment='任务类型：standard/product_requirement'
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
        db_table = 'task_tasks'
        verbose_name = '任务'
        verbose_name_plural = '任务列表'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'created_at'], name='idx_task_status_created'),
            models.Index(fields=['owner', 'status'], name='idx_task_owner_status'),
            models.Index(fields=['task_no'], name='idx_task_no_unique'),
        ]

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
            if self.status in [TaskStatus.PENDING, TaskStatus.IN_PROGRESS] and not self.submitted_at:
                self.submitted_at = timezone.now()

        super().save(*args, **kwargs)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._original_status = self.status



class SubTaskType(models.TextChoices):
    """子任务类型"""
    CUSTOM_UPLOAD = 'custom_upload', '定制上架'
    TEMU_EXPORT = 'temu_export', 'Temu导单'
    PRINT_EXTERNAL = 'print_external', '印花外采'
    DIVI_MULTI_SIDE_CUSTOM = 'divi_multi_side_custom', '迪唯多面定制'
    AMAZON_UPLOAD = 'amazon_upload', 'Amazon上架'
    DIVI_AUTO_UPLOAD = 'divi_auto_upload', 'Divi自动上架'  # 兼容旧数据
    DIVI_GALLERY_UPLOAD = 'divi_gallery_upload', 'DIVI图库上传'
    DIVI_CUSTOM = 'divi_custom', '迪唯定制'
    DIVI_EXPORT = 'divi_export', '迪唯汇出'


class SubTaskStatus(models.TextChoices):
    """子任务状态"""
    DRAFT = 'draft', '草稿'
    PENDING = 'pending', '待执行'
    IN_PROGRESS = 'in_progress', '进行中'
    COMPLETED = 'completed', '已完成'
    FAILED = 'failed', '执行失败'
    CANCELLED = 'cancelled', '已取消'


class SubTask(models.Model):
    """
    子任务表
    存储任务的子任务详情和参数
    """
    # 子任务类型定义
    TYPE_CUSTOM_UPLOAD = 'custom_upload'
    TYPE_TEMU_EXPORT = 'temu_export'
    TYPE_PRINT_EXTERNAL = 'print_external'
    TYPE_DIVI_MULTI_SIDE_CUSTOM = 'divi_multi_side_custom'
    TYPE_AMAZON_UPLOAD = 'amazon_upload'
    TYPE_DIVI_AUTO_UPLOAD = 'divi_auto_upload'
    TYPE_DIVI_GALLERY_UPLOAD = 'divi_gallery_upload'
    TYPE_DIVI_CUSTOM = 'divi_custom'
    TYPE_DIVI_EXPORT = 'divi_export'

    # 子任务状态定义
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

    TYPE_CHOICES = [
        (TYPE_DIVI_MULTI_SIDE_CUSTOM, '迪唯多面定制'),
        (TYPE_DIVI_CUSTOM, '迪唯批量定制'),
        (TYPE_DIVI_EXPORT, '迪唯汇出'),
        (TYPE_DIVI_GALLERY_UPLOAD, 'DIVI图库上传'),
        (TYPE_CUSTOM_UPLOAD, '定制上架'),
        (TYPE_TEMU_EXPORT, 'Temu导单'),
        (TYPE_PRINT_EXTERNAL, '印花外采'),
        (TYPE_AMAZON_UPLOAD, 'Amazon上架'),
        (TYPE_DIVI_AUTO_UPLOAD, 'Divi自动上架'),  # 兼容旧数据
    ]

    id = models.BigAutoField(primary_key=True, verbose_name='主键ID', db_comment='子任务主键ID')

    # 关联主任务
    task = models.ForeignKey(
        'Task',  # 建议用字符串引用，避免循环导入
        on_delete=models.CASCADE,
        related_name='subtasks',
        verbose_name='所属任务',
        db_comment='关联的主任务ID'
    )

    # 子任务基本信息
    subtask_type = models.CharField(
        '子任务类型',
        max_length=30,
        choices=TYPE_CHOICES,
        db_comment='子任务类型：divi_multi_side_custom/divi_custom/divi_export/divi_gallery_upload'
    )

    # 子任务状态
    subtask_status = models.CharField(
        '任务状态',
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_DRAFT,
        db_comment='任务当前状态'
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
        db_table = 'task_subtasks'
        verbose_name = '子任务'
        verbose_name_plural = '子任务列表'
        ordering = ['order', 'id']
        indexes = [
            models.Index(fields=['task', 'order'], name='idx_subtask_task_order'),
            models.Index(fields=['subtask_type', 'is_executed'], name='idx_subtask_type_status'),
        ]

    def __str__(self):
        return f"{self.task.task_no} - {self.get_subtask_type_display()} #{self.order + 1}"

    @classmethod
    def get_initial_status(cls, is_draft=False):
        return cls.STATUS_DRAFT if is_draft else cls.STATUS_PENDING

    def sync_amazon_upload_status(self, save=True):
        """
        根据 Amazon 文件上传进度汇总子任务状态。
        """
        if self.subtask_type != self.TYPE_AMAZON_UPLOAD:
            return self.subtask_status

        file_statuses = list(self.amazon_upload_files.values_list('status', flat=True))
        if not file_statuses:
            next_status = self.get_initial_status(is_draft=self.task.status == TaskStatus.DRAFT)
        elif all(status == AmazonUploadFile.STATUS_COMPLETED for status in file_statuses):
            next_status = self.STATUS_COMPLETED
        elif any(status == AmazonUploadFile.STATUS_FAILED for status in file_statuses):
            next_status = self.STATUS_FAILED
        elif any(status in {AmazonUploadFile.STATUS_UPLOADING, AmazonUploadFile.STATUS_COMPLETED} for status in file_statuses):
            next_status = self.STATUS_IN_PROGRESS
        else:
            next_status = self.STATUS_PENDING

        if not save or next_status == self.subtask_status:
            return next_status

        update_fields = ['subtask_status']
        self.subtask_status = next_status
        if next_status in {self.STATUS_COMPLETED, self.STATUS_FAILED}:
            if not self.is_executed:
                self.is_executed = True
                update_fields.append('is_executed')
            if not self.executed_at:
                self.executed_at = timezone.now()
                update_fields.append('executed_at')
        self.save(update_fields=update_fields)
        return next_status

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


class ProductRequirement(models.Model):
    """
    产品需求表
    存放艺之冠等平台的产品需求
    """
    # 状态定义
    # ① 创建阶段
    STATUS_DRAFT = 'draft'  # 草稿（未提交）
    STATUS_CREATED = 'created'  # 创建完成（已提交）

    # ② 数据抓取阶段（RPA路径）
    STATUS_PENDING_CRAWL = 'pending_crawl'  # 等待数据抓取（触发RPA）
    STATUS_CRAWLED = 'crawled'  # 数据抓取完成

    # ③ 数据确认阶段（产品管理员岗）
    STATUS_PENDING_CONFIRM = 'pending_confirm'  # 等待数据确认（待产品管理员确认）
    STATUS_CONFIRMED = 'confirmed'  # 数据确认完成

    # ④ 审核阶段（管理员岗）
    STATUS_PENDING_REVIEW = 'pending_review'  # 等待审核
    STATUS_REVIEWED = 'reviewed'  # 审核完成

    # ⑤ 美工阶段
    STATUS_PENDING_DESIGN = 'pending_design'  # 等待美工领取需求
    STATUS_DESIGNING = 'designing'  # 美工处理样机中
    STATUS_DESIGNED = 'designed'  # 样机处理成功

    # ⑥ DIVI测试阶段
    STATUS_PENDING_DIVI_TEST = 'pending_divi_test'  # 等待系统上传DIVI测试
    STATUS_DIVI_TESTED = 'divi_tested'  # 上传DIVI测试已完成

    # ⑦ 最终上传阶段
    STATUS_UPLOADING = 'uploading'  # 系统上传DIVI中
    STATUS_COMPLETED = 'completed'  # 上传DIVI已完成（全流程结束）

    # ========== 异常状态（必须独立）==========
    STATUS_REJECTED = 'rejected'  # 审核驳回（可退回至confirmed）
    STATUS_CRAWL_FAILED = 'crawl_failed'  # 抓取失败（RPA异常）
    STATUS_CANCELLED = 'cancelled'  # 已取消

    STATUS_CHOICES = [
        # 正向流程（按顺序排列）
        (STATUS_DRAFT, '草稿'),
        (STATUS_CREATED, '创建完成'),
        (STATUS_PENDING_CRAWL, '等待数据抓取'),
        (STATUS_CRAWLED, '数据抓取完成'),
        (STATUS_PENDING_CONFIRM, '等待数据确认'),
        (STATUS_CONFIRMED, '数据确认完成'),
        (STATUS_PENDING_REVIEW, '等待审核'),
        (STATUS_REVIEWED, '审核完成'),
        (STATUS_PENDING_DESIGN, '等待美工领取需求'),
        (STATUS_DESIGNING, '美工处理样机中'),
        (STATUS_DESIGNED, '样机处理成功'),
        (STATUS_PENDING_DIVI_TEST, '等待系统上传DIVI测试'),
        (STATUS_DIVI_TESTED, '上传DIVI测试已完成'),
        (STATUS_UPLOADING, '系统上传DIVI中'),
        (STATUS_COMPLETED, '上传DIVI已完成'),
        # 异常状态
        (STATUS_REJECTED, '已驳回'),
        (STATUS_CRAWL_FAILED, '抓取失败'),
        (STATUS_CANCELLED, '已取消'),
    ]

    id = models.BigAutoField(primary_key=True, verbose_name='主键ID', db_comment='产品需求主键ID')

    # 关联关系
    owner = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='owned_product_requirements',
        verbose_name='负责人',
        db_comment='需求负责人',
        null=True, 
        blank=True
    )

    designer = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        related_name='designed_product_requirements',
        verbose_name='美工',
        db_comment='美工负责人',
        null=True,
        blank=True
    )

    # 关联任务 (可选 - 逐渐废弃，改为独立)
    task = models.OneToOneField(
        Task,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='product_requirement',
        verbose_name='关联任务',
        db_comment='关联的任务ID (旧数据兼容)'
    )

    status = models.CharField(
        '状态',
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_DRAFT,
        db_comment='需求状态'
    )

    # 外采平台
    PLATFORM_YIZHIGUAN = 'yizhiguan'
    PLATFORM_S2B = 's2b'
    PLATFORM_CHOICES = [
        (PLATFORM_YIZHIGUAN, '艺之冠'),
        (PLATFORM_S2B, 'S2B'),
    ]

    platform = models.CharField(
        '外采平台',
        max_length=50,
        choices=PLATFORM_CHOICES,
        default=PLATFORM_YIZHIGUAN,
        db_comment='外采平台：yizhiguan, s2b'
    )
    product_url = models.URLField('产品链接', max_length=500, blank=True, null=True, db_comment='外采产品链接')
    product_id = models.CharField('平台产品ID', max_length=100, blank=True, null=True, db_comment='从URL提取的平台唯一ID')

    # 上架平台
    LISTING_PLATFORM_AMAZON = 'amazon'
    LISTING_PLATFORM_TEMU = 'temu'
    LISTING_PLATFORM_CHOICES = [
        (LISTING_PLATFORM_AMAZON, 'Amazon'),
        (LISTING_PLATFORM_TEMU, 'Temu'),
    ]
    listing_platform = models.CharField(
        '上架平台',
        max_length=50,
        choices=LISTING_PLATFORM_CHOICES,
        blank=True,
        null=True,
        db_comment='上架平台：amazon, temu'
    )

    # 产品详情
    product_name = models.CharField('产品名称', max_length=200, blank=True, null=True)
    product_abbr = models.CharField('产品简称', max_length=100, blank=True, null=True)
    english_name = models.CharField('英文名称', max_length=200, blank=True, null=True)
    material = models.CharField('产品材质', max_length=100, blank=True, null=True)
    CRAFT_PRINT = '印花'
    CRAFT_EMBROIDERY = '刺绣'
    CRAFT_LASER = '镭射'
    CRAFT_FINISHED = '成品'
    
    CRAFT_CHOICES = [
        (CRAFT_PRINT, '印花'),
        (CRAFT_EMBROIDERY, '刺绣'),
        (CRAFT_LASER, '镭射'),
        (CRAFT_FINISHED, '成品'),
    ]

    craft = models.CharField(
        '生产工艺', 
        max_length=50, 
        choices=CRAFT_CHOICES, 
        blank=True, 
        null=True, 
        db_comment='单选：生产工艺'
    )
    unit = models.CharField('计量单位', max_length=20, blank=True, null=True)

    # 冗余字段（方便查询展示，数据源自Task）
    requirement_no = models.CharField('需求单号', max_length=50, blank=True, null=True, db_comment='冗余：对应Task的task_no')
    # title 字段已移除
    
    # 报关信息
    customs_cn_name = models.CharField('报关中文名称', max_length=200, blank=True, null=True)
    customs_en_name = models.CharField('报关英文名称', max_length=200, blank=True, null=True)
    declared_weight = models.IntegerField('申报重量(克)', blank=True, null=True)
    declared_price = models.DecimalField('海关申报单价(USD)', max_digits=10, decimal_places=2, blank=True, null=True)
    customs_code = models.CharField('海关申报编码', max_length=50, blank=True, null=True)
    material_cn = models.CharField('产品材质(中文)', max_length=100, blank=True, null=True)
    material_en = models.CharField('产品材质(英文)', max_length=100, blank=True, null=True)

    # 其他描述
    material_desc = models.TextField('材质说明', blank=True, null=True)
    accessory_struct = models.TextField('配件构造', blank=True, null=True)
    product_performance = models.TextField('产品性能', blank=True, null=True)
    applicable_scenario = models.TextField('适用情景', blank=True, null=True)
    washing_instructions = models.TextField('洗涤说明', blank=True, null=True)
    special_note = models.TextField('特别说明', blank=True, null=True)
    reminder = models.TextField('温馨提醒', blank=True, null=True)

    # 包装信息
    packaging_specification = models.JSONField('包装规格', default=list, blank=True, null=True)
    product_size = models.JSONField('产品尺码表', default=list, blank=True, null=True)

    # 报关额外信息
    trademark_category = models.CharField('商标类目', max_length=100, blank=True, null=True, default='')
    category = models.CharField('所属分类', max_length=100, blank=True, null=True)
    special_cargo_type = models.CharField('特殊货物类型', max_length=100, blank=True, null=True)
    product_label = models.CharField('产品标识', max_length=100, blank=True, null=True)

    # 额外信息
    color_name = models.JSONField('颜色列表', default=list, blank=True, null=True)
    size_list = models.JSONField('尺码列表', default=list, blank=True, null=True)
    img_urls_list = models.JSONField('图片链接', default=list, blank=True, null=True)

    # 设计说明
    design_desc = models.TextField('设计说明', blank=True, null=True)
    design_area = models.TextField('设计区域', blank=True, null=True)
    image_requirement = models.TextField('图片要求', blank=True, null=True)
    remark = models.TextField('备注', blank=True, null=True)

    # 元数据
    created_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='created_product_requirements',
        verbose_name='创建人',
        db_comment='创建人'
    )
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        db_table = 'task_product_requirements'
        verbose_name = '产品需求'
        verbose_name_plural = '产品需求列表'
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        """
        保存时自动生成需求单号
        """
        if not self.requirement_no and self.created_by:
            from task.utils.task_utils import generate_task_no
            self.requirement_no = generate_task_no(self.created_by)
            
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.product_name or '未命名'} ({self.get_status_display()})"


class ExternalPlatformProduct(models.Model):
    """
    外采平台产品表
    用于管理从外部采购平台导入的产品信息
    """

    # 产品编号（唯一标识）
    product_divi_code = models.CharField(
        max_length=100,
        unique=True,
        verbose_name='产品编号',
        help_text='divi_产品编码'
    )

    # 产品名称
    product_name = models.CharField(
        max_length=255,
        verbose_name='产品名称',
        help_text='产品完整名称'
    )

    # 是否上架
    is_listed = models.BooleanField(
        default=False,
        verbose_name='是否上架',
        help_text='True=已上架，False=未上架'
    )

    # 产品属性
    color = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        verbose_name='颜色'
    )

    specification = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name='规格'
    )

    # DIVI系统专用字段
    divi_color = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        verbose_name='DIVI颜色'
    )

    divi_specification = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        verbose_name='DIVI规格'
    )

    # 采购信息
    min_order_quantity = models.IntegerField(
        default=1,
        verbose_name='起批量',
        help_text='单次采购最低数量'
    )

    purchase_unit_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name='采购原单价',
        help_text='原始采购单价（元）',
        blank=True,
        null=True,
    )
    new_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name='采购现单价',
        help_text='现采购单价（元）',
        blank=True,
        null=True,
    )
    # 平台信息
    platform_name = models.CharField(
        max_length=100,
        verbose_name='外采平台',
        help_text='如：艺之冠等'
    )

    order_link = models.URLField(
        max_length=500,
        blank=True,
        null=True,
        verbose_name='下单链接',
        help_text='外部平台的产品下单页面URL'
    )

    # 时间戳（建议保留，便于数据追踪）
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='创建时间'
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='更新时间'
    )


    class Meta:
        verbose_name = '外采平台产品'
        verbose_name_plural = verbose_name
        db_table = 'procurement_external_platform_product'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.product_divi_code} - {self.product_name}"


class AmazonUploadFile(models.Model):
    """
    Amazon上传文件追踪表
    用于记录每个Excel文件的上传状态和SKU进度
    """
    # 状态定义
    STATUS_PENDING = 'pending'
    STATUS_UPLOADING = 'uploading'
    STATUS_COMPLETED = 'completed'
    STATUS_FAILED = 'failed'

    STATUS_CHOICES = [
        (STATUS_PENDING, '待上传'),
        (STATUS_UPLOADING, '上传中'),
        (STATUS_COMPLETED, '已完成'),
        (STATUS_FAILED, '上传失败'),
    ]

    id = models.BigAutoField(primary_key=True, verbose_name='主键ID')

    # 关联关系
    task = models.ForeignKey(
        'Task',
        on_delete=models.CASCADE,
        related_name='amazon_upload_files',
        verbose_name='所属任务',
        db_comment='关联的主任务'
    )
    subtask = models.ForeignKey(
        'SubTask',
        on_delete=models.CASCADE,
        related_name='amazon_upload_files',
        verbose_name='所属子任务',
        db_comment='关联的子任务'
    )
    amazon_shop = models.ForeignKey(
        'general.AmazonShop',
        on_delete=models.CASCADE,
        related_name='upload_files',
        verbose_name='所属店铺',
        db_comment='关联的Amazon店铺'
    )

    # 文件信息
    shop_name_suffix = models.CharField(
        '店铺后缀',
        max_length=100,
        db_comment='提取的数字法人间，如"16蔡婉婷"'
    )
    excel_filename = models.CharField(
        'Excel文件名',
        max_length=255,
        db_comment='完整的Excel文件名'
    )
    target_path = models.CharField(
        '目标路径',
        max_length=500,
        db_comment='完整的UNC路径'
    )

    # 状态与进度
    status = models.CharField(
        '上传状态',
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
        db_comment='文件上传状态'
    )
    success_sku = models.IntegerField(
        '成功SKU数',
        null=True,
        blank=True,
        db_comment='成功上传的SKU数量'
    )
    total_sku = models.IntegerField(
        '总SKU数',
        null=True,
        blank=True,
        db_comment='Excel中的总SKU数量'
    )

    # 时间戳
    uploaded_at = models.DateTimeField(
        '上传完成时间',
        null=True,
        blank=True,
        db_comment='影刀标记完成的时间'
    )
    created_at = models.DateTimeField(
        '创建时间',
        auto_now_add=True,
        db_comment='记录创建时间'
    )

    class Meta:
        db_table = 'task_amazon_upload_files'
        verbose_name = 'Amazon上传文件'
        verbose_name_plural = 'Amazon上传文件列表'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['task', 'status'], name='idx_amazon_upload_task_status'),
            models.Index(fields=['amazon_shop', 'status'], name='idx_amazon_upload_shop_status'),
            models.Index(fields=['created_at'], name='idx_amazon_upload_created'),
        ]

    def __str__(self):
        return f"{self.excel_filename} ({self.get_status_display()})"

    def update_status(self, status, success_sku=None, total_sku=None):
        """
        更新上传状态
        """
        self.status = status
        if success_sku is not None:
            self.success_sku = success_sku
        if total_sku is not None:
            self.total_sku = total_sku
        if status == self.STATUS_COMPLETED:
            self.uploaded_at = timezone.now()
        self.save()
