# General/models.py

from django.contrib.auth.models import AbstractUser, Group, Permission
from django.db import models
from pydantic import ValidationError
from django.utils import timezone
from datetime import timedelta

class User(AbstractUser):
    """
    自定义用户模型，继承Django AbstractUser
    保留原有ID并添加业务相关字段
    """

    # 覆盖默认ID字段，保留原数据中的bigint类型
    id = models.BigAutoField(primary_key=True, verbose_name='主键')

    # 基础业务字段
    phone = models.CharField('联系电话', max_length=20, blank=True, null=True)

    # 状态：1=正常，2=停用，3=注销
    STATUS_NORMAL = 1
    STATUS_DISABLED = 2
    STATUS_CANCELLED = 3
    STATUS_CHOICES = [
        (STATUS_NORMAL, '正常'),
        (STATUS_DISABLED, '停用'),
        (STATUS_CANCELLED, '注销'),
    ]
    status = models.IntegerField('状态', choices=STATUS_CHOICES, default=STATUS_NORMAL)

    department = models.CharField('部门', max_length=100, blank=True, null=True)
    role = models.CharField('角色', max_length=100, blank=True, null=True)
    company_name = models.CharField('公司名称', max_length=100, blank=True, null=True)
    platform = models.CharField('平台', max_length=255, blank=True, null=True)
    # ops_group = models.CharField('分组-弃用', max_length=255, blank=True, null=True)
    permission = models.CharField("权限", max_length=255, blank=True, null=True)
    wx_url = models.CharField('企业微信消息通知url', max_length=500, blank=True, null=True)
    remark = models.TextField('备注', blank=True, null=True)
    # ========== 关键修复：显式定义groups和user_permissions以避免冲突 ==========
    groups = models.ManyToManyField(
        Group,
        verbose_name='groups',
        blank=True,
        related_name='general_user_groups',  # 自定义反向名称
        help_text='The groups this user belongs to.'
    )

    user_permissions = models.ManyToManyField(
        Permission,
        verbose_name='user permissions',
        blank=True,
        related_name='general_user_permissions',  # 自定义反向名称
        help_text='Specific permissions for this user.'
    )

    # 配置认证字段
    USERNAME_FIELD = 'username'
    REQUIRED_FIELDS = []

    class Meta:
        db_table = 'users'
        verbose_name = '用户信息'
        verbose_name_plural = verbose_name

    def __str__(self):
        return f"{self.first_name} ({self.id})"

    def is_active_status(self):
        """检查用户状态是否为正常"""
        return self.status == self.STATUS_NORMAL

    def is_group_leader(self):
        """判断用户是否为运营组长"""
        return self.role == '运营组长'

    def get_ops_group(self):
        """获取用户的运营分组"""
        if hasattr(self, 'operational_account') and self.operational_account.ops_group:
            return self.operational_account.ops_group
        return None

    def can_manage_group_targets(self):
        """判断是否可以管理组目标（permission包含555）"""
        return self.permission and '555' in self.permission.split(',')


class OperationalAccount(models.Model):
    """
    运营人员外部系统账号信息
    仅运营人员需要填写，与用户表一对一关联
    """

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        primary_key=True,
        verbose_name='关联用户',
        related_name='operational_account'
    )
    ops_group = models.CharField('分组', max_length=255, blank=True, null=True)
    # 闪电云账号信息
    shandianyun_account = models.CharField('闪电云账号', max_length=100, blank=True, null=True)
    shandianyun_username = models.CharField('闪电云用户名', max_length=100, blank=True, null=True)
    shandianyun_password = models.CharField('闪电云密码', max_length=100, blank=True, null=True)

    # 领星账号信息
    lingxing_username = models.CharField('领星用户名', max_length=100, blank=True, null=True)
    lingxing_password = models.CharField('领星密码', max_length=100, blank=True, null=True)

    # 紫鸟账号信息
    ziniao_company = models.CharField('紫鸟公司', max_length=200, blank=True, null=True)
    ziniao_username = models.CharField('紫鸟用户名', max_length=100, blank=True, null=True)
    ziniao_password = models.CharField('紫鸟密码', max_length=100, blank=True, null=True)

    # 迪唯账号信息
    diwei_account = models.CharField('迪唯账号', max_length=100, blank=True, null=True)
    diwei_password = models.CharField('迪唯密码', max_length=100, blank=True, null=True)

    class Meta:
        db_table = 'operational_accounts'
        verbose_name = '运营外部账号'
        verbose_name_plural = verbose_name

    def __str__(self):
        return f"{self.user.first_name} - 运营账号"


class AmazonShop(models.Model):
    id = models.BigIntegerField(primary_key=True, db_comment='主键')
    ops = models.ForeignKey(
        'General.User',
        on_delete=models.SET_NULL,  # 用户删除时店铺保留
        null=True,
        blank=True,
        db_column='ops',  # 数据库列名保持 ops_id
        db_comment='运营id',
        verbose_name='运营人员'
    )
    customer = models.CharField(max_length=100, blank=True, null=True, db_comment='客户')
    shop_number = models.IntegerField(blank=True, null=True, db_comment='店铺序号')
    shop_name = models.CharField(max_length=100, blank=True, null=True, db_comment='店铺名')
    whitelist = models.CharField(max_length=255, blank=True, null=True, db_comment='白名单')
    seller_mark = models.CharField(max_length=100, blank=True, null=True, db_comment='卖家记号')
    amazon_shop_name = models.CharField(max_length=150, blank=True, null=True, db_comment='亚马逊-店铺名称')
    remark = models.TextField(blank=True, null=True, db_comment='备注')
    shop_date = models.DateField(blank=True, null=True, db_comment='下店日期')
    ip_address = models.CharField(max_length=45, blank=True, null=True, db_comment='IP')
    email_account = models.CharField(max_length=150, blank=True, null=True, db_comment='邮箱账号（店铺账号）')
    email_password = models.CharField(max_length=100, blank=True, null=True, db_comment='邮箱密码')
    shop_password = models.CharField(max_length=100, blank=True, null=True, db_comment='店铺密码')
    backup_email_or_phone = models.CharField(max_length=100, blank=True, null=True, db_comment='备用邮箱或手机号')
    credit_card_channel = models.CharField(max_length=100, blank=True, null=True, db_comment='信用卡渠道')
    credit_card_number = models.CharField(max_length=40, blank=True, null=True, db_comment='信用卡')
    credit_card_expiry = models.CharField(max_length=10, blank=True, null=True, db_comment='有效期')
    credit_card_cvv = models.CharField(max_length=3, blank=True, null=True, db_comment='信用卡安全码后3位')
    is_consolidated = models.CharField(max_length=255, blank=True, null=True,
                                       db_comment='是否归集（寻汇子账号是否归集到寻汇总账号）')
    bind_collection = models.CharField(max_length=50, blank=True, null=True, db_comment='绑定收款')
    collection_channel = models.CharField(max_length=50, blank=True, null=True, db_comment='收款渠道')
    xunhui_login_account = models.CharField(max_length=150, blank=True, null=True, db_comment='寻汇登录账号')
    login_password = models.CharField(max_length=100, blank=True, null=True, db_comment='登录密码')
    bind_phone = models.CharField(max_length=20, blank=True, null=True, db_comment='绑定手机号')
    collection_card_number = models.CharField(max_length=30, blank=True, null=True, db_comment='收款卡号')
    payment_password = models.CharField(max_length=100, blank=True, null=True, db_comment='支付密码')
    id_number = models.CharField(max_length=100, blank=True, null=True, db_comment='身份证号')
    legal_person_phone = models.CharField(max_length=20, blank=True, null=True, db_comment='法人手机号码')
    company_name = models.CharField(max_length=200, blank=True, null=True, db_comment='单位名称')
    license_number = models.CharField(max_length=100, blank=True, null=True, db_comment='执照号')
    business_license_date = models.DateField(blank=True, null=True, db_comment='营业执照日期')
    birth_date = models.DateField(blank=True, null=True, db_comment='出生日期')
    id_expiry_date = models.CharField(max_length=100, blank=True, null=True, db_comment='身份证到期日')
    additional_remark = models.TextField(blank=True, null=True, db_comment='备注')
    created_at = models.DateTimeField(db_comment='创建时间')
    updated_at = models.DateTimeField(db_comment='更新时间')
    qu_dao = models.CharField(max_length=255, blank=True, null=True, db_comment='店铺渠道')
    img1 = models.CharField(max_length=255, blank=True, null=True, db_comment='图片')
    shop_status = models.CharField(max_length=255, blank=True, null=True, db_comment='店铺情况')
    voucher_163 = models.CharField(max_length=255, blank=True, null=True, db_comment='163邮箱凭证')
    email_163_account = models.CharField(max_length=255, blank=True, null=True, db_comment='163大师账号')
    ling_xing_if = models.SmallIntegerField(db_comment='是否绑定领星')
    browser = models.CharField(max_length=255, db_comment='浏览器')
    divi_shop_id = models.IntegerField(blank=True, null=True, db_comment='迪唯店铺id')

    class Meta:
        db_table = 'amazon_shop'
        db_table_comment = '亚马逊店铺信息表'


class TemuShop(models.Model):
    id = models.BigIntegerField(primary_key=True, db_comment='主键')
    shop_name = models.CharField(max_length=255, blank=True, null=True, db_comment='店铺名称')
    ops_id = models.IntegerField(blank=True, null=True, db_comment='运营id')
    divi_shop_id = models.IntegerField(blank=True, null=True, db_comment='迪唯店铺id')
    shop_entity = models.CharField(max_length=255, blank=True, null=True, db_comment='主体公司')
    shop_account = models.CharField(max_length=255, blank=True, null=True, db_comment='登录账号')
    shop_password = models.CharField(max_length=255, blank=True, null=True, db_comment='店铺的登录密码')
    invitation_code = models.CharField(max_length=255, blank=True, null=True, db_comment='邀请码')
    verification_email = models.CharField(max_length=255, blank=True, null=True, db_comment='邮箱地址')
    email_password = models.CharField(max_length=255, blank=True, null=True, db_comment='登录密码')
    shop_temu_id = models.CharField(max_length=255, blank=True, null=True, db_comment='店铺Temu_ID')
    compliance_center = models.CharField(max_length=255, blank=True, null=True, db_comment='合规中心')
    new_principal_info = models.CharField(max_length=255, blank=True, null=True,
                                          db_comment='负责人信息申报新增负责人信息')
    new_manufacturer_info = models.CharField(max_length=255, blank=True, null=True,
                                             db_comment='制造商信息申报新增制造商信息申报')
    phone_account_holder = models.CharField(max_length=255, blank=True, null=True, db_comment='手机号码开户人')
    phone_current_location = models.CharField(max_length=255, blank=True, null=True, db_comment='手机号码现存放')
    shop_nature = models.CharField(max_length=255, blank=True, null=True, db_comment='性质')
    place_of_origin = models.CharField(max_length=255, blank=True, null=True, db_comment='归属地')
    legal_person = models.CharField(max_length=255, blank=True, null=True, db_comment='法人')
    customer = models.CharField(max_length=255, blank=True, null=True, db_comment='客户')
    shop_status = models.SmallIntegerField(blank=True, null=True, db_comment='店铺状态')

    class Meta:
        db_table = 'temu_shop'
        db_table_comment = 'temu店铺表'


class GroupPerformanceTarget(models.Model):
    """
    运营组绩效目标表
    只有permission包含555的用户可以创建
    """
    id = models.BigAutoField(primary_key=True, verbose_name='主键')

    # 目标月份 (格式: YYYY-MM)
    month = models.CharField('目标月份', max_length=7)

    # 运营分组（从OperationalAccount.ops_group去重获取）
    ops_group = models.CharField('运营分组', max_length=255)

    # 组目标业绩（单量）
    target_performance = models.IntegerField('组目标业绩/单', default=0)

    # 冲单业绩目标
    stretch_target = models.IntegerField('组冲单目标/单', default=0)

    # 备注
    note = models.TextField('备注', blank=True, null=True)

    # 创建人（permission包含555的用户）
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_group_targets',
        verbose_name='创建人'
    )

    # 创建和更新时间
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        db_table = 'group_performance_targets'
        verbose_name = '组绩效目标'
        verbose_name_plural = verbose_name
        # 每个分组每月只能有一个目标
        unique_together = ['ops_group', 'month']
        indexes = [
            models.Index(fields=['month', 'ops_group']),
        ]

    def __str__(self):
        return f"{self.ops_group} - {self.month}: {self.target_performance}单"

    def clean(self):
        """模型验证"""
        if self.stretch_target <= self.target_performance:
            raise ValidationError('组冲单目标必须大于组目标业绩')

    def get_current_member_total(self):
        """获取当前该组所有成员的个人目标总和"""
        from django.db.models import Sum
        total = PersonalPerformanceTarget.objects.filter(
            ops_group=self.ops_group,
            month=self.month
        ).aggregate(Sum('target_performance'))['target_performance__sum'] or 0

        stretch_total = PersonalPerformanceTarget.objects.filter(
            ops_group=self.ops_group,
            month=self.month
        ).aggregate(Sum('stretch_target'))['stretch_target__sum'] or 0

        return {
            'target_total': total,
            'stretch_total': stretch_total,
            'matches_group_target': total == self.target_performance and stretch_total == self.stretch_target
        }


class PersonalPerformanceTarget(models.Model):
    """
    个人绩效目标表
    由运营组长为自己的组员批量设置
    """
    id = models.BigAutoField(primary_key=True, verbose_name='主键')

    # 关联的运营人员
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        verbose_name='运营人员',
        related_name='personal_performance_targets'
    )

    # 运营分组（冗余字段，方便查询）
    ops_group = models.CharField('运营分组', max_length=255, blank=True, null=True)

    # 目标月份 (格式: YYYY-MM)
    month = models.CharField('目标月份', max_length=7)

    # 目标业绩（单量）
    target_performance = models.IntegerField('个人目标业绩/单', default=0)

    # 冲单业绩目标
    stretch_target = models.IntegerField('个人冲单目标/单', default=0)

    # 备注
    note = models.TextField('备注', blank=True, null=True)

    # 创建人（通常是运营组长）
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_personal_targets',
        verbose_name='创建人'
    )

    # 创建和更新时间
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        db_table = 'personal_performance_targets'
        verbose_name = '个人绩效目标'
        verbose_name_plural = verbose_name
        # 每个人每月只能有一个目标
        unique_together = ['user', 'month']
        indexes = [
            models.Index(fields=['month', 'ops_group']),
            models.Index(fields=['user', 'month']),
        ]

    def __str__(self):
        return f"{self.user.first_name} - {self.month}: {self.target_performance}单"

    def save(self, *args, **kwargs):
        # 自动从user的operational_account获取ops_group
        if self.user:
            self.ops_group = self.user.get_ops_group()
        super().save(*args, **kwargs)

    def clean(self):
        """模型验证"""
        if self.stretch_target <= self.target_performance:
            raise ValidationError('个人冲单目标必须大于个人目标业绩')


class Announcement(models.Model):
    """
    系统公告表
    存储所有系统公告内容，支持多公告并行展示
    """
    PRIORITY_HIGH = 'high'
    PRIORITY_MEDIUM = 'medium'
    PRIORITY_LOW = 'low'
    PRIORITY_CHOICES = [
        (PRIORITY_HIGH, '高优先级'),
        (PRIORITY_MEDIUM, '中优先级'),
        (PRIORITY_LOW, '低优先级'),
    ]

    id = models.BigAutoField(primary_key=True, verbose_name='主键', db_comment='公告唯一标识ID')
    title = models.CharField('公告标题', max_length=200, db_comment='公告标题，显示在弹窗顶部')
    content = models.TextField('公告内容', db_comment='公告正文内容，支持HTML格式')
    priority = models.CharField('优先级', max_length=10, choices=PRIORITY_CHOICES,
                                default=PRIORITY_MEDIUM, db_comment='公告优先级：high/medium/low')

    # 有效期控制
    valid_from = models.DateTimeField('生效时间', default=timezone.now, db_comment='公告开始显示时间')
    valid_to = models.DateTimeField('过期时间', default=timezone.now() + timedelta(days=7),
                                    db_comment='公告停止显示时间')

    # 状态控制
    is_active = models.BooleanField('是否激活', default=True, db_comment='后台控制是否启用该公告')

    # 弹窗控制
    is_dismissible = models.BooleanField('允许关闭', default=True, db_comment='是否显示"关闭"按钮')
    can_mark_read = models.BooleanField('允许标记已读', default=True, db_comment='是否显示"不再提示"按钮')

    created_at = models.DateTimeField('创建时间', auto_now_add=True, db_comment='公告创建时间')
    updated_at = models.DateTimeField('更新时间', auto_now=True, db_comment='公告最后修改时间')
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True,
                                   verbose_name='创建人', related_name='created_announcements',
                                   db_comment='发布公告的用户ID')

    class Meta:
        db_table = 'system_announcements'
        verbose_name = '系统公告'
        verbose_name_plural = verbose_name
        ordering = ['-priority', '-created_at']  # 按优先级和时间排序
        indexes = [
            models.Index(fields=['is_active', 'valid_from', 'valid_to', 'priority'],
                         name='idx_announcement_active_time'),
        ]

    def __str__(self):
        return f"[{self.get_priority_display()}] {self.title}"

    def is_currently_valid(self):
        """检查公告当前是否在有效期内"""
        now = timezone.now()
        return self.is_active and self.valid_from <= now <= self.valid_to


class UserAnnouncementRead(models.Model):
    """
    用户公告已读记录表
    记录每个用户已读过的公告，用于下次不再显示
    """
    id = models.BigAutoField(primary_key=True, verbose_name='主键', db_comment='记录ID')
    user = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name='用户',
                             db_comment='已读公告的用户ID', related_name='read_announcements')
    announcement = models.ForeignKey(Announcement, on_delete=models.CASCADE, verbose_name='公告',
                                     db_comment='被标记已读的的公告ID', related_name='user_reads')
    read_at = models.DateTimeField('已读时间', auto_now_add=True, db_comment='用户点击"不再提示"的时间')
    dismissed_at = models.DateTimeField('关闭时间', null=True, blank=True,
                                        db_comment='用户仅点击关闭的时间（可记录但不影响逻辑）')

    class Meta:
        db_table = 'user_announcement_reads'
        verbose_name = '用户已读记录'
        verbose_name_plural = verbose_name
        unique_together = ['user', 'announcement']  # 确保每个用户对每条公告只记录一次
        indexes = [
            models.Index(fields=['user', 'read_at'], name='idx_user_read_time'),
        ]

    def __str__(self):
        return f"{self.user.first_name} - {self.announcement.title}"


