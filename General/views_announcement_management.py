from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST, require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.db import transaction
from django.utils import timezone
import json
import traceback
from general.models import Announcement

@login_required
def announcement_management_view(request):
    """渲染公告管理页面（仅code=555权限可访问）"""
    if not (hasattr(request.user, 'permission_configs') and
            request.user.permission_configs.filter(code=555).exists()):
        return redirect('general:main')
    
    context = {
        'active_page': 'announcement_management'
    }
    return render(request, 'announcement_management.html', context)

@require_GET
@login_required
def get_announcements_api(request):
    """
    API接口：获取公告列表
    """
    try:
        # 权限检查
        if not (hasattr(request.user, 'permission_configs') and
                request.user.permission_configs.filter(code=555).exists()):
             return JsonResponse({'success': False, 'error': '无权限访问'}, status=403)

        announcements = Announcement.objects.all().order_by('-created_at')
        
        data = []
        for ann in announcements:
            data.append({
                'id': ann.id,
                'title': ann.title,
                'content': ann.content,
                'priority': ann.priority,
                'priority_display': ann.get_priority_display(),
                'valid_from': ann.valid_from.strftime('%Y-%m-%d %H:%M'),
                'valid_to': ann.valid_to.strftime('%Y-%m-%d %H:%M'),
                'is_active': ann.is_active,
                'is_dismissible': ann.is_dismissible,
                'can_mark_read': ann.can_mark_read,
                'created_at': ann.created_at.strftime('%Y-%m-%d %H:%M'),
                'created_by': ann.created_by.first_name if ann.created_by else '未知',
            })
            
        return JsonResponse({
            'success': True,
            'data': data
        })
    except Exception as e:
        traceback.print_exc()
        return JsonResponse({
            'success': False,
            'error': f'获取公告列表失败: {str(e)}'
        }, status=500)

@require_POST
@csrf_exempt
@login_required
def create_announcement_api(request):
    """
    API接口：创建公告
    """
    try:
        # 权限检查
        if not (hasattr(request.user, 'permission_configs') and
                request.user.permission_configs.filter(code=555).exists()):
             return JsonResponse({'success': False, 'error': '无权限访问'}, status=403)

        data = json.loads(request.body)
        
        # 简单验证
        if not data.get('title'):
             return JsonResponse({'success': False, 'error': '标题不能为空'}, status=400)
        
        with transaction.atomic():
            create_kwargs = {
                'title': data.get('title'),
                'content': data.get('content', ''),
                'priority': data.get('priority', 'medium'),
                'valid_from': data.get('valid_from') or timezone.now(),
                'is_active': data.get('is_active', True),
                'is_dismissible': data.get('is_dismissible', True),
                'can_mark_read': data.get('can_mark_read', True),
                'created_by': request.user
            }
            
            if data.get('valid_to'):
                create_kwargs['valid_to'] = data.get('valid_to')

            announcement = Announcement.objects.create(**create_kwargs)
            
        return JsonResponse({
            'success': True,
            'message': '公告创建成功',
            'data': {'id': announcement.id}
        })
        
    except Exception as e:
        traceback.print_exc()
        return JsonResponse({
            'success': False,
            'error': f'创建公告失败: {str(e)}'
        }, status=500)

@require_POST
@csrf_exempt
@login_required
def update_announcement_api(request, announcement_id):
    """
    API接口：更新公告
    """
    try:
        # 权限检查
        if not (hasattr(request.user, 'permission_configs') and
                request.user.permission_configs.filter(code=555).exists()):
             return JsonResponse({'success': False, 'error': '无权限访问'}, status=403)

        data = json.loads(request.body)
        announcement = Announcement.objects.get(id=announcement_id)
        
        with transaction.atomic():
            announcement.title = data.get('title', announcement.title)
            announcement.content = data.get('content', announcement.content)
            announcement.priority = data.get('priority', announcement.priority)
            if data.get('valid_from'):
                announcement.valid_from = data.get('valid_from')
            if data.get('valid_to'):
                announcement.valid_to = data.get('valid_to')
            
            announcement.is_active = data.get('is_active', announcement.is_active)
            announcement.is_dismissible = data.get('is_dismissible', announcement.is_dismissible)
            announcement.can_mark_read = data.get('can_mark_read', announcement.can_mark_read)
            
            announcement.save()
            
        return JsonResponse({
            'success': True,
            'message': '公告更新成功'
        })
        
    except Announcement.DoesNotExist:
        return JsonResponse({'success': False, 'error': '公告不存在'}, status=404)
    except Exception as e:
        traceback.print_exc()
        return JsonResponse({
            'success': False,
            'error': f'更新公告失败: {str(e)}'
        }, status=500)

@require_POST
@csrf_exempt
@login_required
def delete_announcement_api(request, announcement_id):
    """
    API接口：删除公告
    """
    try:
        # 权限检查
        if not (hasattr(request.user, 'permission_configs') and
                request.user.permission_configs.filter(code=555).exists()):
             return JsonResponse({'success': False, 'error': '无权限访问'}, status=403)

        announcement = Announcement.objects.get(id=announcement_id)
        announcement.delete()
        
        return JsonResponse({
            'success': True,
            'message': '公告已删除'
        })
        
    except Announcement.DoesNotExist:
        return JsonResponse({'success': False, 'error': '公告不存在'}, status=404)
    except Exception as e:
        traceback.print_exc()
        return JsonResponse({
            'success': False,
            'error': f'删除公告失败: {str(e)}'
        }, status=500)
