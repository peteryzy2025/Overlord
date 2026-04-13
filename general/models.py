# General/models.py

from django.contrib.auth.models import AbstractUser, Group, Permission
from django.db import models
from django.core.exceptions import ValidationError
from django.utils import timezone
from datetime import timedelta


class PermissionConfig(models.Model):
    """
    业务权限配置表
    示例数据：555=管理员, 5555=开发管理员, 551=店铺管理员
    """
    code = models.IntegerField('权限码', unique=True)
    name = models.CharField('权限名称', max_length=50)
    description = models.TextField('权限描述', blank=True)
    category = models.CharField('权限分类', max_length=50, blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        db_table = 'user_permission_configs'
        verbose_name = '权限配置'
        ordering = ['code']

    def __str__(self):
        return f"{self.code}-{self.name}"


class Company(models.Model):
    """
    公司模型：多租户数据硬隔离边界
    所有业务数据必须挂靠 Company，且不可更改（跨公司=数据导出）
    """
    id = models.BigAutoField(primary_key=True, verbose_name='主键')
    name = models.CharField('公司名称', max_length=200, unique=True)
    code = models.CharField('公司代码', max_length=50, unique=True, blank=True, null=True)
    status = models.IntegerField('状态', choices=[(1, '正常'), (2, '停用')], default=1)

    # 可选：公司级配置（如功能开关）
    settings = models.JSONField('公司配置', default=dict, blank=True,
                                help_text='{"enable_risk_check": true, "max_shops": 100}')  # 预留字段，暂时没用

    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        db_table = 'companies'
        verbose_name = '公司'
        verbose_name_plural = '公司'

    def __str__(self):
        return self.name


class Project(models.Model):
    """
    项目模型：公司内逻辑分组（软标签）
    - 店铺可跨项目迁移（改 project_id 即可）
    - 同一公司内项目数据完全互通
    - 用于分类、报表、默认筛选，不做权限隔离
    """
    id = models.BigAutoField(primary_key=True, verbose_name='主键')

    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name='projects',
        verbose_name='所属公司',
        db_comment='项目所属公司'
    )

    # 项目基本信息
    name = models.CharField('项目名称', max_length=100, db_index=True)
    code = models.CharField('项目代码', max_length=50,
                            help_text='公司内唯一标识，如 "CNXH001"')
    description = models.TextField('项目描述', blank=True, null=True)

    # 负责人（可选）
    manager = models.ForeignKey(
        'User',  # 字符串引用避免循环导入
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='managed_projects',
        verbose_name='项目负责人'
    )

    # 控制字段
    sort_order = models.IntegerField('排序号', default=0,
                                     help_text='数字越小越靠前，用于前端展示')
    is_active = models.BooleanField('是否启用', default=True,
                                    db_comment='停用后不允许店铺挂靠，但已有数据保留')
    lingxing_app_id = models.CharField(
        '领星AppID',
        max_length=100,
        blank=True,
        null=True,
        db_comment='领星开放平台的应用ID，如 ak_P211HcxRxAZ8x',
        help_text='对应领星开发者后台的 appId 字段'
    )

    lingxing_app_secret = models.CharField(
        '领星AppSecret',
        max_length=255,
        blank=True,
        null=True,
        db_comment='领星开放平台密钥，用于生成请求签名',
        help_text='对应领星开发者后台的 appSecret，用于接口签名'
    )

    divi_partner_code = models.CharField(
        'Divi合作方编码 (PARTNER_CODE)',
        max_length=100,
        blank=True, null=True,
        db_comment='固定分配的应用标识，如 7607f3480484b48235',
        help_text='对应 DIVI 的 PARTNER_CODE'
    )

    divi_secret = models.CharField(
        'Divi密钥 (SECRET)',
        max_length=255,
        blank=True, null=True,
        db_comment='用于生成请求签名，切勿泄露',
        help_text='对应 DIVI 的 SECRET，用于接口签名验证'
    )

    # 可选：是否启用自动同步（开关控制，避免频繁调用）
    lingxing_sync_enabled = models.BooleanField(
        '启用领星自动同步',
        default=False,
        db_comment='控制是否允许定时任务拉取领星数据'
    )

    divi_sync_enabled = models.BooleanField(
        '启用Divi自动同步',
        default=False,
        db_comment='控制是否允许调用Divi接口查侵权词'
    )
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        db_table = 'companies_projects'
        verbose_name = '项目'
        verbose_name_plural = '项目'
        # 核心约束：公司内项目代码唯一
        unique_together = [['company', 'code']]
        ordering = ['company', 'sort_order', '-created_at']
        indexes = [
            models.Index(fields=['company', 'is_active'], name='idx_company_active'),
        ]

    def __str__(self):
        return f"{self.company.name} / {self.name} ({self.code})"

    def clean(self):
        # 确保项目名称在公司内唯一（可选，看业务需求）
        if self.name:
            qs = Project.objects.filter(company=self.company, name=self.name)
            if self.pk:
                qs = qs.exclude(pk=self.pk)
            # 如果业务需要允许同名项目，注释掉下面这行
            if qs.exists():
                raise ValidationError({'name': '该公司下已存在同名项目'})


class User(AbstractUser):
    """
    自定义用户模型，继承Django AbstractUser
    保留原有ID并添加业务相关字段
    """

    # 覆盖默认ID字段，保留原数据中的bigint类型
    id = models.BigAutoField(primary_key=True, verbose_name='主键')
    company = models.ForeignKey(
        'Company',
        on_delete=models.PROTECT,  # 防止误删公司导致用户数据丢失

        related_name='users',  # 关键！让 Company 能通过 .users 反向查用户
        verbose_name='所属公司',
        help_text='用户所属的公司，多租户隔离用'
    )
    permission_configs = models.ManyToManyField(
        PermissionConfig,
        blank=True,
        verbose_name='业务权限列表',
        related_name='users',  # 反向查询：perm.users.all() 获取有该权限的所有用户
        db_table='user_permission_config'  # 自定义中间表名
    )
    # 基础业务字段
    phone = models.CharField('联系电话', max_length=20, blank=True, null=True)

    class Status(models.IntegerChoices):
        NORMAL = 1, '正常'
        DISABLED = 2, '停用'

    status = models.IntegerField('状态', choices=Status.choices,  # type: ignore
                                 default=Status.NORMAL)

    class Department(models.TextChoices):
        DATA = 'data', '数据部'
        OPERATION = 'operation', '运营部'
        HR = 'hr', '人事部'
        SUPPLY_CHAIN = 'supply_chain', '供应链部'
        ASSISTANT = 'assistant', '助理部'
        FINANCE = 'finance', '财务部'

    department = models.CharField(
        '部门',
        max_length=20,  # 存英文代号，长度可缩短
        choices=Department.choices,  # type: ignore
        blank=True,
        null=True,
        db_comment='部门（静态选项：数据部、运营部、人事部、供应链部、助理部）'
    )
    role = models.CharField('角色', max_length=100, blank=True, null=True)  # 旧字段，后续不要了
    company_name = models.CharField('公司名称', max_length=100, blank=True, null=True)  # # 旧字段，后续不要了
    platform = models.CharField('平台', max_length=255, blank=True, null=True)  # 旧字段，后续不要了
    permission = models.CharField("权限", max_length=255, blank=True, null=True)  # 老权限字段，逗号分隔的权限码列表，如"123,555" 已经不用了
    wx_url = models.CharField('企业微信消息通知url', max_length=500, blank=True, null=True)  # 企业微信通知url
    remark = models.TextField('备注', blank=True, null=True)
    # ========== 关键修复：显式定义groups和user_permissions以避免冲突 ==========
    # 下面两个是django自带的权限系统字段，必须显式定义以避免与自定义permission_configs冲突
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

    theme = models.CharField(
        '主题偏好',
        max_length=10,
        choices=[('light', '浅色'), ('dark', '深色')],
        default='light'
    )

    avatar = models.ImageField(
        '头像',
        upload_to='avatars/%Y/%m/',
        blank=True,
        null=True,
        help_text='用户头像图片'
    )

    # ========== 上下级关系 ==========
    manager = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='subordinates',
        verbose_name='直接上级',
        help_text='该用户的直接汇报对象，必须同公司'
    )

    class Meta:
        db_table = 'users'
        verbose_name = '用户信息'
        verbose_name_plural = verbose_name

    def __str__(self):
        return f"{self.first_name} ({self.id})"

    def is_active_status(self):
        """检查用户状态是否为正常（status=1 且 Django用户可用）"""
        return self.is_active and self.status == self.Status.NORMAL

    def get_ops_group(self):
        """获取用户的运营分组"""
        if hasattr(self, 'operational_account') and self.operational_account.ops_group:
            return self.operational_account.ops_group
        return None

    def can_manage_group_targets(self):
        """检查用户是否可以管理组绩效目标（permission包含555）"""
        return self.permission_configs.filter(code=555).exists()

    def is_group_leader(self):
        """检查用户是否为运营组长"""
        if hasattr(self, 'operational_account') and self.operational_account.role:
            return self.operational_account.role == OperationalAccount.Role.LEADER
        return False

    def clean(self):
        """校验上下级关系"""
        super().clean()

        # 1. 防止循环引用
        if self.manager_id == self.pk:
            raise ValidationError({'manager': '不能将自己设为上级'})

        if self.manager:
            # 2. 必须同公司
            if self.manager.company_id != self.company_id:
                raise ValidationError({'manager': '上级必须与该用户同属一个公司'})

            # 3. 防止循环：检查上级的上级链中是否包含自己
            current = self.manager
            visited = {self.pk}
            while current:
                if current.pk in visited:
                    raise ValidationError({'manager': '设置的上级会形成循环汇报关系'})
                visited.add(current.pk)
                current = current.manager

    def get_reporting_chain(self):
        """
        获取完整汇报链（从直接上级一直到根）
        返回: [直接上级, 上级的上级, ... , 最高级]
        """
        chain = []
        current = self.manager
        visited = {self.pk}

        while current and current.pk not in visited:
            chain.append(current)
            visited.add(current.pk)
            current = current.manager

        return chain

    def get_all_subordinates(self):
        """
        获取所有下级（包括直接和间接下级）
        返回: QuerySet 包含所有下级用户
        """
        all_ids = set()

        def collect_subordinate_ids(user_id):
            sub_ids = list(User.objects.filter(manager_id=user_id).values_list('id', flat=True))
            for sid in sub_ids:
                if sid not in all_ids:
                    all_ids.add(sid)
                    collect_subordinate_ids(sid)

        collect_subordinate_ids(self.pk)
        return User.objects.filter(id__in=all_ids)

    def is_descendant_of(self, user_id):
        """判断当前用户是否是某人的下级（用于权限判断）"""
        current = self.manager
        visited = {self.pk}

        while current:
            if current.pk == user_id:
                return True
            if current.pk in visited:
                break
            visited.add(current.pk)
            current = current.manager

        return False


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

    class Platform(models.TextChoices):
        AMAZON = 'amazon', 'Amazon'
        TEMU = 'temu', 'Temu'

    platform = models.CharField(
        '平台',
        max_length=50,
        choices=Platform.choices,  # type: ignore
        blank=True,
        null=True
    )

    class Role(models.TextChoices):
        LEADER = 'leader', '运营组长'
        STAFF = 'staff', '运营'
        ASSISTANT = 'assistant', '运营助理'

    role = models.CharField(
        '角色',
        max_length=50,
        choices=Role.choices,  # type: ignore
        default=Role.STAFF,
        blank=True,
        null=True
    )

    ad_requires_approval = models.BooleanField(
        '广告需审批',
        default=False,  # 默认不需要，如需全员默认审批改为 True
        help_text='该账号的广告投放/调整操作是否需要组长/管理员审批',
        blank=True,
        null=True  # 允许 NULL，方便后续批量设置
    )
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
    divi_username = models.CharField('迪唯用户名', max_length=100, blank=True, null=True)
    diwei_account = models.CharField('迪唯账号', max_length=100, blank=True, null=True)
    diwei_password = models.CharField('迪唯密码', max_length=100, blank=True, null=True)

    class Meta:
        db_table = 'operational_accounts'
        verbose_name = '运营外部账号'
        verbose_name_plural = verbose_name

    def __str__(self):
        return f"{self.user.first_name} - 运营账号"

    def is_group_leader(self):
        """判断是否为运营组长"""
        return self.role == self.Role.LEADER


class AmazonShop(models.Model):
    class ShopStatus(models.TextChoices):
        ACTIVE = 'status-active', '正常'
        INACTIVE = 'status-inactive', '停用'
        CANCELLED = 'status-cancelled', '注销'
        WARNING = 'status-warning', '救店中'
        PENDING = 'status-pending', '审核中'
        UNKNOWN = 'status-unknown', '待定'

    id = models.BigAutoField(primary_key=True, db_comment='主键')
    company = models.ForeignKey(
        'general.Company',
        on_delete=models.PROTECT,
        related_name='amazon_shops',
        verbose_name='所属公司',
        null=True,
        blank=True,
        db_comment='数据隔离边界'
    )

    project = models.ForeignKey(
        'general.Project',
        on_delete=models.SET_NULL,
        related_name='amazon_shops',
        verbose_name='所属项目',
        null=True,
        blank=True,
        db_comment='业务分组标签'
    )
    ops = models.ForeignKey(
        'general.User',
        on_delete=models.SET_NULL,  # 用户删除时店铺保留
        null=True,
        blank=True,
        db_column='ops',  # 数据库列名保持 ops_id
        db_comment='运营id',
        verbose_name='运营人员'
    )
    shop_status = models.CharField(
        max_length=50,
        choices=ShopStatus.choices,  # type:ignore
        default=ShopStatus.ACTIVE,
        null=True,
        blank=True,
        verbose_name='amazon_shop_status',
        db_comment='店铺情况',
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
    registered_phone = models.CharField(max_length=20, blank=True, null=True, db_comment='注册手机号')
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
    company_name = models.CharField(max_length=200, blank=True, null=True, db_comment='公司名称')
    license_number = models.CharField(max_length=100, blank=True, null=True, db_comment='执照号')
    business_license_date = models.DateField(blank=True, null=True, db_comment='营业执照日期')
    birth_date = models.DateField(blank=True, null=True, db_comment='出生日期')
    id_expiry_date = models.CharField(max_length=100, blank=True, null=True, db_comment='身份证到期日')
    additional_remark = models.TextField(blank=True, null=True, db_comment='备注')
    created_at = models.DateTimeField(db_comment='创建时间')
    updated_at = models.DateTimeField(db_comment='更新时间')
    qu_dao = models.CharField(max_length=255, blank=True, null=True, db_comment='店铺渠道')  # 旧字段，后续代码请勿使用该字段
    channel_risk = models.ForeignKey(
        'ShopChannelRisk',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='amazon_shops',
        verbose_name='店铺渠道配置',
        db_comment='关联渠道风险表（qu_dao保留仅作历史显示）'
    )
    img1 = models.CharField(max_length=255, blank=True, null=True, db_comment='图片')

    voucher_163 = models.CharField(max_length=255, blank=True, null=True, db_comment='163邮箱凭证')
    email_163_account = models.CharField(max_length=255, blank=True, null=True, db_comment='163大师账号')
    ling_xing_if = models.SmallIntegerField(db_comment='是否绑定领星')
    browser = models.CharField(max_length=255, db_comment='浏览器')
    divi_shop_id = models.IntegerField(blank=True, null=True, unique=True,db_comment='迪唯店铺id')
    qupital_if = models.BooleanField(db_comment='是否绑定qupital', default=False)

    class Meta:
        db_table = 'amazon_shop'
        db_table_comment = '亚马逊店铺信息表'
        indexes = [
            models.Index(fields=['company', 'project'], name='idx_shop_company_project'),
            models.Index(fields=['company', 'ops'], name='idx_shop_company_ops'),
        ]

    def clean(self):
        # 关键校验：如果填了 project，必须与 company 一致
        if self.project and self.project.company_id != self.company_id:
            raise ValidationError('所选项目不属于当前公司')

    def migrate_project(self, new_project):
        """店铺跨项目迁移方法"""
        if new_project.company_id != self.company_id:
            raise ValueError('不能跨公司迁移项目')
        self.project = new_project
        self.save(update_fields=['project'])


class TemuShop(models.Model):
    id = models.BigIntegerField(primary_key=True, db_comment='主键')
    company = models.ForeignKey(
        'general.Company',
        on_delete=models.PROTECT,  # 公司不能删，除非先处理店铺
        related_name='temu_shops',
        verbose_name='所属公司',
        db_comment='数据隔离边界，不可变更'
    )

    project = models.ForeignKey(
        'general.Project',
        on_delete=models.PROTECT,  # 项目删了店铺还在，只是没项目
        related_name='temu_shops',
        verbose_name='所属项目',
        null=True,
        blank=True,
        db_comment='业务分组标签，可自由迁移'
    )
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

    # 包装规格 尺寸和重量信息
    length = models.FloatField('长(inch)', blank=True, null=True, default=None, db_comment='包裹长度，单位inch')
    width = models.FloatField('宽(inch)', blank=True, null=True, default=None, db_comment='包裹宽度，单位inch')
    height = models.FloatField('高(inch)', blank=True, null=True, default=None, db_comment='包裹高度，单位inch')
    weight = models.FloatField('重量(lb)', blank=True, null=True, default=None, db_comment='包裹重量，单位lb')

    class Meta:
        db_table = 'temu_shop'
        db_table_comment = 'temu店铺表'


class GroupPerformanceTarget(models.Model):
    """
    运营组绩效目标表
    只有permission包含555的用户可以创建
    """
    id = models.BigAutoField(primary_key=True, verbose_name='主键')
    company = models.ForeignKey(
        'general.Company',
        on_delete=models.PROTECT,
        related_name='group_targets',
        verbose_name='所属公司',
        db_comment='数据隔离边界'
    )
    # 目标月份 (格式: YYYY-MM)
    month = models.DateField('目标月份', default=timezone.now)

    # 运营分组（从OperationalAccount.ops_group去重获取）
    ops_group = models.CharField('运营分组', max_length=255)

    # 组目标业绩（单量）
    target_performance = models.IntegerField('组目标业绩/单', default=0)

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
        unique_together = ['company', 'ops_group', 'month']

        indexes = [
            models.Index(fields=['company', 'month', 'ops_group']),
        ]

    def __str__(self):
        return f"{self.company.name} - {self.ops_group} - {self.month}: {self.target_performance}单"

    def clean(self):
        """模型验证"""
        # 确保日期总是该月的第一天
        if self.month and self.month.day != 1:
            self.month = self.month.replace(day=1)

    @property
    def month_display(self):
        """返回 YYYY-MM 格式的月份显示"""
        return self.month.strftime('%Y-%m')

    @classmethod
    def get_by_month(cls, ops_group, year_month):
        """根据 YYYY-MM 格式查询"""
        from datetime import datetime
        date_obj = datetime.strptime(year_month, '%Y-%m').date()
        return cls.objects.get(ops_group=ops_group, month=date_obj)

    def get_current_member_total(self):
        """获取当前该组所有成员的个人目标总和"""
        from django.db.models import Sum
        total = PersonalPerformanceTarget.objects.filter(
            ops_group=self.ops_group,
            month=self.month
        ).aggregate(Sum('target_performance'))['target_performance__sum'] or 0

        return {
            'target_total': total,
            'matches_group_target': total == self.target_performance
        }


class PersonalPerformanceTarget(models.Model):
    """
    个人绩效目标表
    由运营组长为自己的组员批量设置
    """
    id = models.BigAutoField(primary_key=True, verbose_name='主键')
    company = models.ForeignKey(
        'general.Company',
        on_delete=models.PROTECT,
        related_name='personal_targets',
        verbose_name='所属公司',
    )
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
    month = models.DateField('目标月份', default=timezone.now)

    # 目标业绩（单量）
    target_performance = models.IntegerField('个人目标业绩/单', default=0)

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
        unique_together = ['company', 'user', 'month']
        indexes = [
            models.Index(fields=['company', 'month', 'ops_group']),
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
        # 确保日期总是该月的第一天
        if self.month and self.month.day != 1:
            self.month = self.month.replace(day=1)

    @property
    def month_display(self):
        """返回 YYYY-MM 格式的月份显示"""
        return self.month.strftime('%Y-%m')


def get_default_valid_to():
    """默认过期时间为7天后"""
    return timezone.now() + timedelta(days=7)


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
    valid_to = models.DateTimeField(
        '过期时间',
        default=get_default_valid_to,  # 关键：传函数对象，不是调用结果
        db_comment='公告停止显示时间'
    )

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


class UserOperationLog(models.Model):
    """
    用户操作日志表
    记录所有用户的关键操作，便于审计和追踪
    """

    # ============= 内置 Choices 类 =============
    class OperationType(models.IntegerChoices):
        """操作类型：1xxx用户, 2xxx店铺, 3xxx订单, 4xxx邮件, 6xxx考核, 7xxx物流"""
        # 1xxx: 用户管理类操作
        USER_CREATE = 1001, '新增用户'
        USER_UPDATE = 1002, '修改用户信息'
        USER_DELETE = 1003, '删除用户'

        # 2xxx: 店铺管理类操作
        SHOP_CREATE = 2001, '新增店铺'
        SHOP_UPDATE = 2002, '修改店铺'
        SHOP_DELETE = 2003, '删除店铺'

        # 3xxx: 订单管理类操作
        ORDER_IMPORT = 3001, '订单导单'
        ORDER_SHIP = 3002, '订单发货'
        ORDER_MARK_REAL = 3003, '订单标注真发'
        ORDER_RPA_LOGISTICS = 3004, 'RPA真物流覆盖假物流'
        ORDER_AUTO_SHIP = 3005, '自动发货'

        # 4xxx: 邮件管理类操作
        EMAIL_MARK_PROCESSED = 4001, '标记邮件已处理'
        EMAIL_NOTIFY_OPERATORS = 4002, '批量通知运营邮件'
        DAILY_CHECK_RESET = 4011, '重置巡店'
        PERFORMANCE_NOTIFY_OPERATORS = 4021, '绩效通知-批量通知运营'

        # 6xxx: 考核流程操作
        ASSESSMENT_BATCH_REFRESH = 6001, '绩效考核-批量刷新订单'
        ASSESSMENT_SUBMIT = 6002, '绩效考核-组长评分提交'  # type: ignore
        ASSESSMENT_MEMBER_CONFIRM = 6003, '绩效考核-组员评分确认'
        ASSESSMENT_LEADER_CONFIRM = 6004, '绩效考核-组长评分确认'
        ASSESSMENT_CREATE = 6005, '考核创建'
        ASSESSMENT_MEMBER_REJECT = 6006, '绩效考核-组员评分驳回'

        # 7xxx: 物流追踪管理类操作
        TRACKING_MARK_CANCELLED = 7101, '物流追踪-标记运单取消'
        TRACKING_UNDO_CANCEL = 7102, '物流追踪-恢复运单状态'

        # 8xxx: 侵权词库操作
        TRO_CREATE = 8001, '新增侵权词'
        TRO_UPDATE = 8002, '修改侵权词'
        TRO_DELETE = 8003, '删除侵权词'
        TRO_IMPORT = 8004, '批量导入侵权词'
        TRO_SEARCH = 8005, '查询侵权词'

    # ============= 字段定义 =============
    company = models.ForeignKey(
        'general.Company',
        on_delete=models.PROTECT,
        related_name='operation_logs',
        verbose_name='操作所属公司',
        null=True,
        blank=True,
        db_comment='记录操作时的公司归属，用于审计和按公司查询'
    )

    id = models.BigAutoField(primary_key=True, verbose_name='主键')

    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name='操作人',
        related_name='operation_logs',
        db_comment='执行操作的用户'
    )

    # 使用 Choices 类
    operation_type = models.IntegerField(
        '操作类型',
        choices=OperationType.choices,  # type: ignore
        db_index=True,
        db_comment='4位数字类型：1xxx用户操作，2xxx店铺操作，3xxx订单操作，4xxx邮件，6xxx考核，7xxx物流'
    )

    operation_record = models.CharField(
        '操作记录',
        max_length=255,
        db_index=True,
        db_comment='自由记录的文本内容'
    )

    created_at = models.DateTimeField(
        '操作时间',
        auto_now_add=True,
        db_index=True,
        db_comment='自动写入的操作时间'
    )

    class Meta:
        db_table = 'user_operation_logs'
        verbose_name = '用户操作日志'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']

        indexes = [
            # 按公司+时间查（高频：查本公司最近操作）
            models.Index(fields=['company', '-created_at'], name='idx_company_time'),
            # 按公司+类型查（高频：查本公司所有店铺操作）
            models.Index(fields=['company', 'operation_type'], name='idx_company_type'),
            # 按用户+时间查（低频：查某人操作历史）
            models.Index(fields=['user', '-created_at'], name='idx_user_time'),
        ]

    def __str__(self):
        return f"{self.user} - {self.get_operation_type_display()} - {self.created_at.strftime('%Y-%m-%d %H:%M:%S')}"


class ShopChannelRisk(models.Model):
    """店铺渠道风险（独立表）"""

    id = models.AutoField(primary_key=True, verbose_name='ID')

    LEVEL_CHOICES = [
        ('low', '低'),
        ('medium', '中'),
        ('high', '高'),
        ('none', '无'),
    ]
    channel_name = models.CharField(max_length=50, unique=True, verbose_name='店铺渠道', blank=True)

    risk_level = models.CharField(
        max_length=20,
        choices=LEVEL_CHOICES,
        default='none',
        verbose_name='渠道风险等级',
        db_index=True

    )

    channel_remark = models.CharField(max_length=100, verbose_name='渠道备注', blank=True, null=True)

    class Meta:
        db_table = 'amazon_channel_risk'
        verbose_name = '店铺渠道风险'
        verbose_name_plural = '店铺渠道风险'
        indexes = [
            models.Index(fields=['risk_level', 'channel_name']),
        ]

    def __str__(self):
        return f"{self.channel_name}"


