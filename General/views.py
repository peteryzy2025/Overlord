# General/amazon_views.py
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponseRedirect
from django.shortcuts import render
from django.middleware.csrf import get_token
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie, csrf_exempt
from General.models import Announcement, UserAnnouncementRead
from django.forms.models import model_to_dict
import json
from django.views.decorators.http import require_http_methods, require_POST
from django.views.decorators.csrf import csrf_protect


@require_http_methods(["POST"])
@csrf_protect
def mark_announcement_as_read(request):
    """标记公告为已读"""
    if not request.user.is_authenticated:
        return JsonResponse({'error': '未登录'}, status=401)

    try:
        data = json.loads(request.body)
        announcement_id = data.get('announcement_id')

        announcement = Announcement.objects.get(id=announcement_id)

        # 创建或获取已读记录
        UserAnnouncementRead.objects.get_or_create(
            user=request.user,
            announcement=announcement,
            defaults={'read_at': timezone.now()}
        )

        return JsonResponse({'success': True})
    except Announcement.DoesNotExist:
        return JsonResponse({'error': '公告不存在'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
@ensure_csrf_cookie
def user_login(request):
    if request.method == 'GET':
        return render(request, 'login.html')

    if request.method == 'POST':
        # 处理JSON数据
        try:
            data = json.loads(request.body)
            username = data.get('username', '').strip()
            password = data.get('password', '').strip()
        except:
            username = request.POST.get('username', '').strip()
            password = request.POST.get('password', '').strip()

        # 验证必填项
        if not username or not password:
            return JsonResponse({
                'success': False,
                'message': '用户名和密码不能为空'
            }, status=400)

        # 正常认证流程
        user = authenticate(request, username=username, password=password)

        if user is not None:
            # 检查用户是否激活
            if not user.is_active:
                return JsonResponse({
                    'success': False,
                    'message': '用户账号已停用'
                }, status=403)

            login(request, user)

            # 返回用户基本信息
            user_data = model_to_dict(user, fields=['id', 'username', 'email', 'first_name', 'last_name'])
            return JsonResponse({
                'success': True,
                'redirect_url': '/main/',
                'user': user_data
            })

        # 认证失败
        return JsonResponse({
            'success': False,
            'message': '用户名或密码错误'
        }, status=401)


@login_required
def user_logout(request):
    logout(request)
    return HttpResponseRedirect('/login/')

@login_required(login_url='/login/')
def main_page(request):
    """主页"""
    theme = request.COOKIES.get('theme', 'light')
    return render(request, 'main.html', {
        'theme': theme,
        'active_nav': 'main'
    })

@login_required(login_url='/login/')
def management_page(request):
    """管理中心"""
    theme = request.COOKIES.get('theme', 'light')
    return render(request, 'management.html', {
        'theme': theme,
        'active_nav': 'management'
    })



def csrf_token_view(request):
    token = get_token(request)
    return JsonResponse({'csrfToken': token})

@csrf_exempt
@login_required
def update_theme(request):
    """更新主题设置"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            theme = data.get('theme', 'light')
            response = JsonResponse({'success': True, 'theme': theme})
            response.set_cookie('theme', theme, max_age=365*24*60*60)  # 1年
            return response
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)}, status=400)
    return JsonResponse({'success': False, 'message': '只支持POST请求'}, status=405)


@require_POST
def mark_announcement_as_read(request):
    """
    标记公告为已读 API
    POST /api/announcement/mark-as-read/
    请求体: {"announcement_id": 123}
    返回: {"success": true, "message": "已标记为已读"}

    幂等性：重复标记不报错
    """
    try:
        # 解析JSON请求体
        data = json.loads(request.body)
        announcement_id = data.get('announcement_id')

        if not announcement_id:
            return JsonResponse({
                'success': False,
                'message': '缺少announcement_id参数'
            }, status=400)

        # 验证公告是否存在
        if not Announcement.objects.filter(id=announcement_id).exists():
            return JsonResponse({
                'success': False,
                'message': '公告不存在'
            }, status=404)

        # 幂等处理：get_or_create 避免重复记录
        UserAnnouncementRead.objects.get_or_create(
            user=request.user,
            announcement_id=announcement_id,
            defaults={'read_at': timezone.now()}
        )

        return JsonResponse({
            'success': True,
            'message': '已标记为已读'
        })

    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'message': '请求数据格式错误（需JSON）'
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'服务器错误: {str(e)}'
        }, status=500)