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

from .models import User, OperationalAccount


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