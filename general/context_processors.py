# General/context_processors.py

import json
from django.utils.safestring import mark_safe

from general.module_utils import get_user_accessible_company_module_codes, get_user_company_module_codes


def announcements_processor(request):
    """
    自动将未读公告添加到所有模板的全局变量
    返回JSON字符串，确保布尔值能被JS正确解析
    """
    unread_list = getattr(request, 'unread_announcements', [])
    # 序列化为JSON字符串并标记为安全（避免HTML转义）
    return {
        'unread_announcements': mark_safe(json.dumps(unread_list))
    }


def user_permissions_processor(request):
    """
    将用户权限码列表注入所有模板上下文
    供模板中 {% if 555 in user_permissions %} 使用
    """
    user_permissions = []
    company_module_codes = []
    accessible_company_module_codes = []
    if request.user.is_authenticated:
        user_permissions = list(request.user.permission_configs.values_list('code', flat=True))
        company_module_codes = sorted(get_user_company_module_codes(request.user))
        accessible_company_module_codes = sorted(get_user_accessible_company_module_codes(request.user))
    return {
        'user_permissions': user_permissions,
        'company_module_codes': company_module_codes,
        'accessible_company_module_codes': accessible_company_module_codes,
    }
