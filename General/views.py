# General/views.py
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponseRedirect
from django.shortcuts import render
from django.middleware.csrf import get_token
from django.views.decorators.csrf import ensure_csrf_cookie, csrf_exempt
from General.models import User
from django.forms.models import model_to_dict
import json


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

@login_required(login_url='/login/')
def amazon_dashboard_page(request):
    """Amazon驾驶舱"""
    theme = request.COOKIES.get('theme', 'light')
    return render(request, 'amazon_dashboard.html', {
        'theme': theme,
        'active_nav': 'amazon'
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