from django.utils import timezone
from datetime import timedelta
from django.db.models import Q, Prefetch


class AnnouncementMiddleware:
    """
    公告系统中间件
    自动为每个页面请求注入未读公告列表
    不依赖缓存，通过优化查询实现性能
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # 只处理GET请求的页面（排除API/Ajax/静态文件）
        should_check_announcements = (
                request.method == 'GET'
                and not request.path.startswith('/api/')
                and not request.path.startswith('/static/')
                and not request.path.startswith('/media/')
                and request.user.is_authenticated
        )

        if should_check_announcements:
            # 调用注入方法
            self.inject_announcements(request)

        # 继续处理请求
        response = self.get_response(request)
        return response

    def inject_announcements(self, request):
        """注入未读公告到请求对象"""
        from General.models import Announcement, UserAnnouncementRead

        now = timezone.now()

        # 1. 查询3天内生效且未过期的公告（最多10条）
        recent_announcements = Announcement.objects.filter(
            is_active=True,
            valid_to__gte=now
        ).select_related('created_by').order_by('-priority', '-created_at')[:10]

        if not recent_announcements:
            request.unread_announcements = []
            return

        # 2. 检查用户已读记录（一次查询获取所有已读ID）
        read_ids = set(
            UserAnnouncementRead.objects.filter(
                user=request.user,
                announcement__in=recent_announcements
            ).values_list('announcement_id', flat=True)
        )

        # 3. 筛选出未读公告
        unread_announcements = [
            {
                'id': ann.id,
                'title': ann.title,
                'content': ann.content,
                'priority': ann.priority,
                'is_dismissible': ann.is_dismissible,
                'can_mark_read': ann.can_mark_read,
                'created_at': ann.created_at.strftime('%Y-%m-%d %H:%M:%S')
            }
            for ann in recent_announcements
            if ann.id not in read_ids
        ]

        request.unread_announcements = unread_announcements