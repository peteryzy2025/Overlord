# task/approval_models.py

from django.db import models
from django.utils import timezone


class LibType(models.TextChoices):
    """词库类型"""
    OFFICIAL = 'official', '官方词库'
    PERSONAL = 'personal', '个人词库'


class ApprovalStatus(models.TextChoices):
    """审批状态"""
    DRAFT = 'draft', '草稿'
    PENDING = 'pending', '审批中'
    APPROVED = 'approved', '已通过'
    REJECTED = 'rejected', '已驳回'
    WAITING = 'waiting', '待执行'
    EXECUTING = 'executing', '执行中'
    SUCCESS = 'success', '执行成功'
    FAILED = 'failed', '执行失败'


class ApprovalType(models.TextChoices):
    """审批类型"""
    AMAZON_AD = 'amazon_ad', 'Amazon开广告'


class ExecStatus(models.TextChoices):
    """执行状态"""
    WAITING = 'waiting', '待执行'
    EXECUTING = 'executing', '执行中'
    COMPLETED = 'success', '执行成功'
    FAILED = 'failed', '执行失败'


class StepStatus(models.TextChoices):
    """步骤状态"""
    PENDING = 'pending', '待审批'
    COMPLETED = 'completed', '已完成'
    SKIPPED = 'skipped', '已跳过'
    WAITING = 'waiting', '待执行'
    EXECUTING = 'executing', '执行中'
    SUCCESS = 'success', '执行成功'
    FAILED = 'failed', '执行失败'


class RecordResult(models.TextChoices):
    """审批结果"""
    APPROVED = 'approved', '通过'
    REJECTED = 'rejected', '驳回'


class NegativeKeywordLibrary(models.Model):
    """
    否定词库表
    官方词库和个人词库统一存储
    """
    company = models.ForeignKey(
        'general.Company',
        on_delete=models.CASCADE,
        verbose_name='所属公司',
        db_comment='数据隔离边界'
    )

    lib_type = models.CharField(
        '词库类型',
        max_length=10,
        choices=LibType.choices,
        default=LibType.PERSONAL,
        db_comment='官方词库或个人词库'
    )

    name = models.CharField('词库名称', max_length=100)
    description = models.TextField('描述', blank=True)
    is_active = models.BooleanField('是否启用', default=True)

    # 否定词列表，简单字符串数组
    keywords = models.JSONField(
        '否定词列表',
        default=list,
        help_text='格式：["否定词1", "否定词2"]',
        db_comment='否定词字符串列表'
    )

    created_by = models.ForeignKey(
        'general.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name='创建人',
        db_comment='官方词库此字段为空'
    )

    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        db_table = 'approval_negative_keyword_libraries'
        verbose_name = '否定词库'
        verbose_name_plural = '否定词库列表'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['company', 'lib_type'], name='idx_nklib_company_type'),
            models.Index(fields=['company', 'is_active'], name='idx_nklib_company_active'),
        ]

    def __str__(self):
        return f"{self.name} ({self.get_lib_type_display()})"


class Approval(models.Model):
    """
    审批主表
    通用审批流程，支持多级审批（通过ApprovalStep动态定义级数）
    """
    company = models.ForeignKey(
        'general.Company',
        on_delete=models.CASCADE,
        verbose_name='所属公司',
        db_comment='数据隔离边界'
    )

    approval_no = models.CharField('审批单号', max_length=50, unique=True, db_index=True)

    approval_type = models.CharField(
        '审批类型',
        max_length=30,
        choices=ApprovalType.choices,
        default=ApprovalType.AMAZON_AD,
        db_comment='审批业务类型'
    )

    applicant = models.ForeignKey(
        'general.User',
        on_delete=models.CASCADE,
        related_name='approvals',
        verbose_name='申请人',
        db_comment='发起审批的用户'
    )

    status = models.CharField(
        '审批状态',
        max_length=20,
        choices=ApprovalStatus.choices,
        default=ApprovalStatus.DRAFT,
        db_comment='审批流程状态'
    )

    # 审批进度序号：-1草稿，0待组长，1待主管，2全部完成
    current_step_sequence = models.IntegerField('当前步骤序号', default=-1, db_comment='审批进度序号：-1草稿，0待组长，1待主管，2全部完成')

    # 总步骤数（创建时确定，方便判断进度）
    total_steps = models.IntegerField('总步骤数', default=0, db_comment='审批步骤总数')

    # 关联原始审批（驳回后重提时指向原审批）
    original_approval = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reapply_list',
        verbose_name='原始审批',
        db_comment='驳回后重新提交的原始审批单'
    )

    submitted_at = models.DateTimeField('提交时间', null=True, blank=True, db_comment='申请人提交审批时间')
    completed_at = models.DateTimeField('完成时间', null=True, blank=True, db_comment='审批流程结束时间')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        db_table = 'approval_main'
        verbose_name = '审批单'
        verbose_name_plural = '审批单列表'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['company', 'status'], name='idx_approval_company_status'),
            models.Index(fields=['company', 'approval_type'], name='idx_approval_company_type'),
            models.Index(fields=['applicant', 'status'], name='idx_approval_applicant_status'),
            models.Index(fields=['submitted_at'], name='idx_approval_submitted'),
        ]

    def __str__(self):
        return f"{self.approval_no} ({self.get_status_display()})"

    @staticmethod
    def get_total_steps_for_type(approval_type):
        total_steps_map = {
            ApprovalType.AMAZON_AD: 2,
        }
        return total_steps_map.get(approval_type, 0)

    @classmethod
    def generate_approval_no(cls, user):
        timestamp = timezone.now().strftime('%Y%m%d%H%M%S%f')
        return f"{user.id}_{timestamp}"

    @classmethod
    def build_draft(cls, applicant, approval_type=ApprovalType.AMAZON_AD, **extra_fields):
        approval = cls(
            company=applicant.company,
            applicant=applicant,
            approval_type=approval_type,
            status=ApprovalStatus.DRAFT,
            current_step_sequence=-1,
            total_steps=cls.get_total_steps_for_type(approval_type),
            **extra_fields,
        )
        if not approval.approval_no:
            approval.approval_no = cls.generate_approval_no(applicant)
        return approval

    def save(self, *args, **kwargs):
        if self.approval_type:
            self.total_steps = self.get_total_steps_for_type(self.approval_type)

        if self.current_step_sequence is None:
            self.current_step_sequence = -1

        if not self.approval_no and self.applicant_id:
            self.approval_no = self.generate_approval_no(self.applicant)

        super().save(*args, **kwargs)


class ApprovalStep(models.Model):
    """
    审批步骤表
    定义审批流程的每一步，创建审批时生成
    """
    company = models.ForeignKey(
        'general.Company',
        on_delete=models.CASCADE,
        verbose_name='所属公司',
        db_comment='数据隔离边界'
    )

    approval = models.ForeignKey(
        Approval,
        on_delete=models.CASCADE,
        related_name='steps',
        verbose_name='所属审批',
        db_comment='关联的审批主表'
    )

    sequence = models.IntegerField('步骤序号', db_comment='从1开始的步骤顺序')

    step_name = models.CharField('步骤名称', max_length=50, db_comment='如：组长审批、主管审批')

    # 指定的审批人（创建时就确定）
    approver = models.ForeignKey(
        'general.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approval_steps',
        verbose_name='指定审批人',
        db_comment='该步骤的审批人（创建时确定）'
    )

    status = models.CharField(
        '步骤状态',
        max_length=20,
        choices=StepStatus.choices,
        default=StepStatus.PENDING,
        db_comment='步骤执行状态'
    )

    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        db_table = 'approval_steps'
        verbose_name = '审批步骤'
        verbose_name_plural = '审批步骤列表'
        ordering = ['sequence']
        unique_together = ['approval', 'sequence']
        indexes = [
            models.Index(fields=['company', 'approval'], name='idx_step_company_approval'),
            models.Index(fields=['approval', 'status'], name='idx_step_approval_status'),
            models.Index(fields=['approver', 'status'], name='idx_step_approver_status'),
        ]

    def __str__(self):
        return f"{self.approval.approval_no} - 第{self.sequence}步 {self.step_name}"


class ApprovalRecord(models.Model):
    """
    审批记录表
    记录每一次实际的审批操作（通过/驳回）
    一个步骤可能有多个记录（如驳回后重提的新审批）
    """
    company = models.ForeignKey(
        'general.Company',
        on_delete=models.CASCADE,
        verbose_name='所属公司',
        db_comment='数据隔离边界'
    )

    step = models.ForeignKey(
        ApprovalStep,
        on_delete=models.CASCADE,
        related_name='records',
        verbose_name='所属步骤',
        db_comment='关联的审批步骤'
    )

    # 实际执行审批的人（可能与step.approver不同，如代理审批）
    approver = models.ForeignKey(
        'general.User',
        on_delete=models.SET_NULL,
        null=True,
        related_name='approval_records',
        verbose_name='审批人',
        db_comment='实际执行审批的用户'
    )

    result = models.CharField(
        '审批结果',
        max_length=20,
        choices=RecordResult.choices,
        db_comment='通过或驳回'
    )

    comment = models.TextField('审批意见', blank=True, db_comment='审批人的意见')

    created_at = models.DateTimeField('审批时间', auto_now_add=True)

    class Meta:
        db_table = 'approval_records'
        verbose_name = '审批记录'
        verbose_name_plural = '审批记录列表'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['company', 'step'], name='idx_record_company_step'),
            models.Index(fields=['step', 'result'], name='idx_record_step_result'),
            models.Index(fields=['approver'], name='idx_record_approver'),
            models.Index(fields=['created_at'], name='idx_record_created'),
        ]

    def __str__(self):
        return f"{self.step} - {self.get_result_display()}"


class AmazonAdApproval(models.Model):
    """
    Amazon开广告审批详情
    与审批主表一对一关联
    """
    company = models.ForeignKey(
        'general.Company',
        on_delete=models.CASCADE,
        verbose_name='所属公司',
        db_comment='数据隔离边界'
    )

    approval = models.OneToOneField(
        Approval,
        on_delete=models.CASCADE,
        related_name='ad_detail',
        verbose_name='关联审批单',
        db_comment='对应的审批主表'
    )

    remark = models.TextField('备注', blank=True)

    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        db_table = 'approval_amazon_ad'
        verbose_name = '开广告审批详情'
        verbose_name_plural = '开广告审批详情列表'

    def __str__(self):
        return f"开广告审批 - {self.approval.approval_no}"


class AmazonAdShopConfig(models.Model):
    """
    开广告店铺-ASIN配置
    一个审批单可以有多个店铺配置（同一店铺可多次出现，不同ASIN）
    每个配置独立执行，独立追踪状态
    """
    company = models.ForeignKey(
        'general.Company',
        on_delete=models.CASCADE,
        verbose_name='所属公司',
        db_comment='数据隔离边界'
    )

    amazon_ad = models.ForeignKey(
        AmazonAdApproval,
        on_delete=models.CASCADE,
        related_name='shop_configs',
        verbose_name='所属审批',
        db_comment='关联的开广告审批'
    )

    # 领星店铺
    lingxing_shop = models.ForeignKey(
        'amazon.LingXingAmazonShop',
        on_delete=models.CASCADE,
        verbose_name='领星店铺',
        db_comment='广告创建的店铺'
    )

    # ASIN列表（多对多）
    asins = models.ManyToManyField(
        'amazon.AmazonListingV2',
        verbose_name='ASIN列表',
    )

    # 否定词库
    negative_keyword_lib = models.ForeignKey(
        NegativeKeywordLibrary,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name='否定词库',
        db_comment='应用的否定词库'
    )

    # 执行状态（RPA按组独立执行）
    exec_status = models.CharField(
        '执行状态',
        max_length=20,
        choices=ExecStatus.choices,
        default=ExecStatus.WAITING,
        db_comment='RPA执行状态'
    )

    exec_result = models.JSONField(
        '执行结果',
        default=dict,
        blank=True,
        db_comment='RPA返回结果'
    )

    webhook_task_id = models.CharField(
        'RPA任务ID',
        max_length=100,
        blank=True,
        db_comment='用于匹配Webhook回调'
    )

    sequence = models.IntegerField(
        '执行顺序',
        default=0,
        db_comment='组间执行顺序'
    )

    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        db_table = 'approval_amazon_ad_shop_config'
        verbose_name = '开广告店铺配置'
        verbose_name_plural = '开广告店铺配置列表'
        ordering = ['sequence', 'created_at']
        indexes = [
            models.Index(fields=['company', 'amazon_ad'], name='idx_adshop_company_ad'),
            models.Index(fields=['company', 'exec_status'], name='idx_adshop_company_exec'),
            models.Index(fields=['lingxing_shop'], name='idx_adshop_shop'),
            models.Index(fields=['webhook_task_id'], name='idx_adshop_webhook'),
        ]

    def __str__(self):
        return f"{self.lingxing_shop.name} - {self.asins.count()}个ASIN"


class ApprovalFlowConfig(models.Model):
    """
    审批流程配置表
    为每个员工 + 审批类型独立配置审批流程
    """
    company = models.ForeignKey(
        'general.Company',
        on_delete=models.CASCADE,
        verbose_name='所属公司',
        db_comment='数据隔离边界'
    )

    applicant = models.ForeignKey(
        'general.User',
        on_delete=models.CASCADE,
        related_name='approval_flow_configs',
        verbose_name='被配置员工',
        db_comment='该配置适用的员工'
    )

    approval_type = models.CharField(
        '审批类型',
        max_length=30,
        choices=ApprovalType.choices,
        default=ApprovalType.AMAZON_AD,
        db_comment='审批业务类型'
    )

    skip_approval = models.BooleanField(
        '跳过审批',
        default=False,
        db_comment='为 True 时该员工提交此类型审批直接通过，不经过任何人'
    )

    proxy_approver = models.ForeignKey(
        'general.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='proxy_approval_configs',
        verbose_name='一级审批人',
        db_comment='代替组长审批该员工审批单的人（step1）'
    )

    step2_approver = models.ForeignKey(
        'general.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='step2_approval_configs',
        verbose_name='二级审批人',
        db_comment='代替主管审批该员工审批单的人（step2，可选）'
    )

    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        db_table = 'approval_flow_configs'
        verbose_name = '审批流程配置'
        verbose_name_plural = '审批流程配置列表'
        unique_together = ['company', 'applicant', 'approval_type']
        indexes = [
            models.Index(fields=['company', 'applicant'], name='idx_flowcfg_company_applicant'),
            models.Index(fields=['company', 'approval_type'], name='idx_flowcfg_company_type'),
        ]

    def __str__(self):
        return f"{self.applicant} - {self.approval_type}"
