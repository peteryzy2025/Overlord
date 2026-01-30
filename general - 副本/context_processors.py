# General/context_processors.py

import json
from django.utils.safestring import mark_safe

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