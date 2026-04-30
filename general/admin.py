# General/admin.py

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import UserCreationForm, UserChangeForm
from django.utils.translation import gettext_lazy as _
from django.utils.html import format_html
from django import forms
from django.db import models
from django.core.exceptions import ValidationError  # ✅ 修正错误导入
from django.http import HttpResponse
import csv
from datetime import datetime

from .models import (
    User,
    OperationalAccount,
    Announcement,
    UserAnnouncementRead,
    Company,
    Project,
    ProjectLingxingLogisticsCode,
    SystemModule,
    CompanyModuleGrant,
)


# ========== 内联管理运营账号（在User编辑页面显示） ==========
class OperationalAccountInline(admin.StackedInline):
    model = OperationalAccount
    can_delete = False
    verbose_name_plural = '运营账号详情'

    # 将密码字段显示为密码输入框（不显示明文）
    formfield_overrides = {
        models.CharField: {'widget': forms.PasswordInput(render_value=True)},
    }

    fieldsets = (
        ('通用信息', {  # ✅ 新增：放置 ops_group 字段
            'fields': ('ops_group',),
            'classes': ('collapse',)
        }),
        ('闪电云账号', {
            'fields': ('shandianyun_account', 'shandianyun_username', 'shandianyun_password'),
            'classes': ('collapse',)  # 可折叠
        }),
        ('领星账号', {
            'fields': ('lingxing_username', 'lingxing_password'),
            'classes': ('collapse',)
        }),
        ('紫鸟账号', {
            'fields': ('ziniao_company', 'ziniao_username', 'ziniao_password'),
            'classes': ('collapse',)
        }),
        ('迪唯账号', {
            'fields': ('diwei_account', 'diwei_password'),
            'classes': ('collapse',)
        }),
    )


# ========== 自定义用户表单 ==========
class CustomUserCreationForm(UserCreationForm):
    """自定义用户创建表单"""

    class Meta:
        model = User
        fields = ('username', 'first_name', 'phone', 'email', 'status')


class CustomUserChangeForm(UserChangeForm):
    """自定义用户修改表单"""

    class Meta:
        model = User
        fields = '__all__'


# ========== User模型管理配置 ==========
@admin.register(User)
class UserAdmin(BaseUserAdmin):
    # 使用的表单
    add_form = CustomUserCreationForm
    form = CustomUserChangeForm

    # 列表显示配置 - 修复：将'status'加入list_display
    list_display = (
        'username', 'first_name', 'phone', 'department', 'role',
        'status_colored', 'status', 'company_name', 'platform',  # ✅ 添加了'status'
        'is_staff', 'is_superuser', 'date_joined'
    )

    # 让status列可编辑
    list_editable = ('status', 'department', 'role')

    list_filter = (
        'status', 'is_staff', 'is_superuser', 'department',
        'role', 'platform', 'date_joined'  # ✅ 移除：'ops_group'
    )

    search_fields = (
        'username', 'first_name', 'phone', 'email',
        'department', 'role', 'company_name'
    )

    ordering = ('-date_joined',)

    # 自定义状态颜色显示
    def status_colored(self, obj):
        color_map = {
            User.STATUS_NORMAL: '#28a745',  # 绿色
            User.STATUS_DISABLED: '#ffc107',  # 黄色
            User.STATUS_CANCELLED: '#dc3545',  # 红色
        }
        color = color_map.get(obj.status, '#6c757d')  # 默认灰色
        return format_html(
            '<span style="background-color: {}; color: white; padding: 2px 6px; '
            'border-radius: 3px; font-size: 12px;">{}</span>',
            color,
            obj.get_status_display()
        )

    status_colored.short_description = '状态'

    # 内联模型（在User编辑页面显示运营账号）
    inlines = (OperationalAccountInline,)

    # 字段分组（编辑页面）
    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        (_('个人信息'), {
            'fields': (
                'first_name', 'phone', 'email', 'department',
                'role', 'company_name', 'platform'  # ✅ 移除：'ops_group'
            )
        }),
        (_('状态信息'), {'fields': ('status',)}),
        (_('权限信息'), {
            'fields': (
                'is_active', 'is_staff', 'is_superuser',
                'groups', 'user_permissions'
            )
        }),
        (_('重要日期'), {'fields': ('last_login', 'date_joined')}),
    )

    # 创建用户时的字段分组
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': (
                'username', 'password1', 'password2', 'first_name',
                'phone', 'email', 'status', 'is_staff', 'is_superuser'
            ),
        }),
    )

    # 自定义批量操作
    actions = ['make_active', 'make_disabled', 'make_cancelled']

    @admin.action(description='将选中用户设为【正常】状态')
    def make_active(self, request, queryset):
        queryset.update(status=User.STATUS_NORMAL)

    @admin.action(description='将选中用户设为【停用】状态')
    def make_disabled(self, request, queryset):
        queryset.update(status=User.STATUS_DISABLED)

    @admin.action(description='将选中用户设为【注销】状态')
    def make_cancelled(self, request, queryset):
        queryset.update(status=User.STATUS_CANCELLED)


# ========== 独立的运营账号管理（可选） ==========
@admin.register(OperationalAccount)
class OperationalAccountAdmin(admin.ModelAdmin):
    list_display = (
        'user', 'ops_group', 'shandianyun_account', 'lingxing_username',  # ✅ 新增：'ops_group'
        'ziniao_company', 'diwei_account'
    )

    search_fields = (
        'user__username', 'user__first_name',
        'shandianyun_account', 'lingxing_username', 'ziniao_username'
    )

    list_filter = ('ziniao_company', 'ops_group',)  # ✅ 新增：'ops_group' 过滤

    # 使用原始ID字段，避免用户下拉列表过长
    raw_id_fields = ('user',)

    # 密码字段显示为密码输入框
    formfield_overrides = {
        models.CharField: {'widget': forms.PasswordInput(render_value=True)},
    }

    fieldsets = (
        ('用户信息', {'fields': ('user', 'ops_group')}),  # ✅ 新增：'ops_group'
        ('闪电云账号', {
            'fields': ('shandianyun_account', 'shandianyun_username', 'shandianyun_password'),
            'classes': ('collapse',)
        }),
        ('领星账号', {
            'fields': ('lingxing_username', 'lingxing_password'),
            'classes': ('collapse',)
        }),
        ('紫鸟账号', {
            'fields': ('ziniao_company', 'ziniao_username', 'ziniao_password'),
            'classes': ('collapse',)
        }),
        ('迪唯账号', {
            'fields': ('diwei_account', 'diwei_password'),
            'classes': ('collapse',)
        }),
    )


# ========== 公告管理配置 ==========
@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    list_display = (
        'title', 'priority_colored', 'is_active',
        'valid_from', 'valid_to', 'created_by', 'created_at'
    )
    list_filter = ('priority', 'is_active', 'is_dismissible', 'can_mark_read', 'created_at')
    search_fields = ('title', 'content')
    readonly_fields = ('created_at', 'updated_at')
    ordering = ('-valid_from',)

    # 优先级颜色显示
    def priority_colored(self, obj):
        color_map = {
            Announcement.PRIORITY_HIGH: '#e53e3e',
            Announcement.PRIORITY_MEDIUM: '#dd6b20',
            Announcement.PRIORITY_LOW: '#3182ce',
        }
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color_map.get(obj.priority, '#718096'),
            obj.get_priority_display()
        )

    priority_colored.short_description = '优先级'

    fieldsets = (
        ('公告内容', {
            'fields': ('title', 'content', 'priority')
        }),
        ('有效期设置', {
            'fields': ('valid_from', 'valid_to'),
            'description': '设置公告的显示时间范围，超过有效期后将自动停止显示'
        }),
        ('显示控制', {
            'fields': ('is_active', 'is_dismissible', 'can_mark_read'),
            'description': 'is_active: 总开关；is_dismissible: 是否显示关闭按钮；can_mark_read: 是否允许用户标记已读'
        }),
        ('系统信息', {
            'fields': ('created_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def save_model(self, request, obj, form, change):
        """自动设置创建人"""
        if not obj.pk:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(UserAnnouncementRead)
class UserAnnouncementReadAdmin(admin.ModelAdmin):
    list_display = ('user', 'announcement', 'read_at')
    list_filter = ('read_at', 'announcement__priority')
    search_fields = ('user__username', 'user__first_name', 'announcement__title')
    readonly_fields = ('read_at', 'dismissed_at')
    ordering = ('-read_at',)

    def has_add_permission(self, request):
        """禁止手动添加已读记录（应该由用户操作自动生成）"""
        return False


class ProjectLingxingLogisticsCodeInline(admin.TabularInline):
    model = ProjectLingxingLogisticsCode
    extra = 0
    fields = ('logistics_key', 'logistics_name', 'logistics_type_id', 'enabled', 'remark')
    show_change_link = True


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = (
        'name', 'code', 'company', 'is_active', 'lingxing_sync_enabled',
        'divi_sync_enabled', 'sort_order', 'updated_at'
    )
    list_filter = ('company', 'is_active', 'lingxing_sync_enabled', 'divi_sync_enabled')
    search_fields = ('name', 'code', 'company__name')
    readonly_fields = ('created_at', 'updated_at')
    ordering = ('company', 'sort_order', '-created_at')
    inlines = (ProjectLingxingLogisticsCodeInline,)
    raw_id_fields = ('company', 'manager')
    fieldsets = (
        ('基本信息', {
            'fields': ('company', 'name', 'code', 'description', 'manager')
        }),
        ('同步配置', {
            'fields': (
                'lingxing_app_id', 'lingxing_app_secret',
                'divi_partner_code', 'divi_secret',
                'lingxing_sync_enabled', 'divi_sync_enabled',
            )
        }),
        ('状态与排序', {
            'fields': ('is_active', 'sort_order')
        }),
        ('系统信息', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(ProjectLingxingLogisticsCode)
class ProjectLingxingLogisticsCodeAdmin(admin.ModelAdmin):
    list_display = ('project', 'logistics_key', 'logistics_name', 'logistics_type_id', 'enabled', 'updated_at')
    list_filter = ('enabled', 'logistics_key', 'project__company', 'project')
    search_fields = ('project__name', 'project__code', 'logistics_key', 'logistics_name', 'logistics_type_id')
    readonly_fields = ('created_at', 'updated_at')
    raw_id_fields = ('project',)
    ordering = ('project', 'logistics_key')


@admin.register(SystemModule)
class SystemModuleAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'category', 'sort_order', 'is_active', 'is_builtin', 'updated_at')
    list_filter = ('category', 'is_active', 'is_builtin')
    search_fields = ('code', 'name', 'description')
    readonly_fields = ('created_at', 'updated_at')
    ordering = ('category', 'sort_order', 'code')


@admin.register(CompanyModuleGrant)
class CompanyModuleGrantAdmin(admin.ModelAdmin):
    list_display = ('company', 'module', 'enabled', 'starts_at', 'expires_at', 'updated_by', 'updated_at')
    list_filter = ('enabled', 'module__category', 'module', 'starts_at', 'expires_at')
    search_fields = ('company__name', 'company__code', 'module__code', 'module__name', 'remark')
    readonly_fields = ('created_at', 'updated_at')
    raw_id_fields = ('company', 'module', 'created_by', 'updated_by')
    ordering = ('company', 'module__sort_order')


# ========== 公司管理（多租户核心）==========
@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'status_colored', 'created_at', 'user_count')
    list_filter = ('status', 'created_at')
    search_fields = ('name', 'code')
    readonly_fields = ('created_at', 'updated_at')
    ordering = ('-created_at',)

    # 统计该公司下有多少用户（实时显示在列表中（超级实用！）
    def user_count(self, obj):
        count = obj.users.count()
        if count > 0:
            return format_html(
                '<b style="color:#28a745;">{}</b> 人',
                count
            )
        return "0 人"
    user_count.short_description = '用户数量'

    # 状态颜色美化
    def status_colored(self, obj):
        color = '#28a745' if obj.status == 1 else '#dc3545'
        text = '正常' if obj.status == 1 else '停用'
        return format_html(
            '<span style="background:{}; color:white; padding:2px 8px; border-radius:3px; font-size:11px;">{}</span>',
            color, text
        )
    status_colored.short_description = '状态'

    fieldsets = (
        ('基本信息', {
            'fields': ('name', 'code', 'status')
        }),
        ('统计信息', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    # 创建公司时自动记录创建时间（虽然auto_now_add已经有了，但保险）
    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)

    # 自定义动作：快速停用/启用公司
    actions = ['make_active', 'make_disabled']

    @admin.action(description='将选中公司设为【正常】')
    def make_active(self, request, queryset):
        updated = queryset.update(status=1)
        self.message_user(request, f'成功启用 {updated} 家公司。')

    @admin.action(description='将选中公司设为【停用】')
    def make_disabled(self, request, queryset):
        updated = queryset.update(status=2)
        self.message_user(request, f'成功停用 {updated} 家公司。')

    # 安全考虑：不允许删除已有用户的公司
    def has_delete_permission(self, request, obj=None):
        if obj and obj.users.exists():
            return False
        return super().has_delete_permission(request, obj)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        # 超级管理员看全部，普通管理员只能看自己公司（后续可扩展）
        if request.user.is_superuser:
            return qs
        return qs.filter(users=request.user)
