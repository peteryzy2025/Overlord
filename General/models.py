# General/models.py

from django.contrib.auth.models import AbstractUser, Group, Permission
from django.db import models


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
    ops_group = models.CharField('分组', max_length=255, blank=True, null=True)
    wx_url = models.CharField('企业微信消息通知url', max_length=500, blank=True, null=True)

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
    is_consolidated = models.CharField(max_length=255, blank=True, null=True, db_comment='是否归集（寻汇子账号是否归集到寻汇总账号）')
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

