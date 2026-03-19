"""
个人中心视图
包含个人中心页面、头像上传、基本信息修改、密码修改等功能
"""
import os
import uuid
from django.contrib.auth.decorators import login_required
from django.contrib.auth.hashers import check_password, make_password
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST
import json

from general.models import UserOperationLog


# 部门显示映射
DEPARTMENT_MAP = {
    'data': '数据部',
    'operation': '运营部',
    'hr': '人事部',
    'supply_chain': '供应链部',
    'assistant': '助理部',
    'finance': '财务部',
}


@login_required(login_url='/login/')
def profile_view(request):
    """
    个人中心页面视图
    """
    user = request.user
    
    # 获取用户头像URL（如果有自定义头像）
    user_avatar = None
    if hasattr(user, 'avatar') and user.avatar:
        user_avatar = user.avatar.url
    
    # 获取部门显示名称
    department_display = DEPARTMENT_MAP.get(user.department, user.department)
    
    # 获取主题显示
    theme_display = '深色' if user.theme == 'dark' else '浅色'
    
    # 获取运营账号信息
    operational_account = None
    if hasattr(user, 'operational_account'):
        operational_account = user.operational_account
    
    # 获取最近5条操作日志
    recent_logs = UserOperationLog.objects.filter(
        user=user
    ).select_related('company').order_by('-created_at')[:5]
    
    # 为日志添加图标
    for log in recent_logs:
        log.icon = get_operation_icon(log.operation_type)
    
    context = {
        'user_avatar': user_avatar,
        'department_display': department_display,
        'theme_display': theme_display,
        'operational_account': operational_account,
        'recent_logs': recent_logs,
    }
    
    return render(request, 'profile/profile.html', context)


def get_operation_icon(operation_type):
    """
    根据操作类型返回对应的图标
    """
    icon_map = {
        # 用户管理
        1001: 'user-plus',      # 新增用户
        1002: 'user-edit',      # 修改用户信息
        1003: 'user-minus',     # 删除用户
        # 店铺管理
        2001: 'store',          # 新增店铺
        2002: 'store-alt',      # 修改店铺
        2003: 'store-slash',    # 删除店铺
        # 订单管理
        3001: 'file-import',    # 订单导单
        3002: 'shipping-fast',  # 订单发货
        3003: 'check-circle',   # 订单标注真发
        3004: 'robot',          # RPA真物流覆盖假物流
        3005: 'auto-ship',      # 自动发货
        # 邮件管理
        4001: 'envelope-open',  # 标记邮件已处理
        4002: 'bell',           # 批量通知运营邮件
        4011: 'redo',           # 重置巡店
        # 考核
        6001: 'sync',           # 绩效考核-批量刷新订单
        6002: 'edit',           # 绩效考核-组长评分提交
        6003: 'check',          # 绩效考核-组员评分确认
        6004: 'check-double',   # 绩效考核-组长评分确认
        6005: 'plus-circle',    # 考核创建
        6006: 'times-circle',   # 绩效考核-组员评分驳回
        # 物流
        7101: 'ban',            # 物流追踪-标记运单取消
        7102: 'undo',           # 物流追踪-恢复运单状态
    }
    return icon_map.get(operation_type, 'circle')


@require_POST
@csrf_protect
@login_required
def upload_avatar_api(request):
    """
    上传头像 API
    POST /api/profile/avatar/
    """
    user = request.user
    
    if 'avatar' not in request.FILES:
        return JsonResponse({
            'success': False,
            'message': '请选择要上传的图片'
        }, status=400)
    
    avatar_file = request.FILES['avatar']
    
    # 验证文件类型
    allowed_types = ['image/jpeg', 'image/png', 'image/gif', 'image/webp']
    if avatar_file.content_type not in allowed_types:
        return JsonResponse({
            'success': False,
            'message': '仅支持 JPG、PNG、GIF、WebP 格式的图片'
        }, status=400)
    
    # 验证文件大小（最大2MB）
    max_size = 2 * 1024 * 1024
    if avatar_file.size > max_size:
        return JsonResponse({
            'success': False,
            'message': '图片大小不能超过2MB'
        }, status=400)
    
    try:
        # 生成唯一文件名
        ext = os.path.splitext(avatar_file.name)[1].lower()
        filename = f"avatars/{user.id}_{uuid.uuid4().hex[:8]}{ext}"
        
        # 保存文件
        path = default_storage.save(filename, ContentFile(avatar_file.read()))
        
        # 删除旧头像
        if hasattr(user, 'avatar') and user.avatar:
            try:
                old_path = user.avatar.path
                if os.path.exists(old_path):
                    os.remove(old_path)
            except Exception:
                pass
        
        # 更新用户头像字段
        user.avatar = path
        user.save(update_fields=['avatar'])
        
        # 记录操作日志
        UserOperationLog.objects.create(
            company=user.company,
            user=user,
            operation_type=1002,  # 修改用户信息
            operation_record=f'用户 {user.first_name or user.username} 修改了头像'
        )
        
        return JsonResponse({
            'success': True,
            'avatar_url': user.avatar.url
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'上传失败: {str(e)}'
        }, status=500)


@require_POST
@csrf_protect
@login_required
def update_basic_info_api(request):
    """
    更新基本信息 API
    POST /api/profile/basic-info/
    """
    user = request.user
    
    try:
        data = json.loads(request.body)
        
        # 获取要更新的字段
        first_name = data.get('first_name', '').strip()
        email = data.get('email', '').strip()
        phone = data.get('phone', '').strip()
        wx_url = data.get('wx_url', '').strip()
        
        # 验证邮箱格式
        if email and '@' not in email:
            return JsonResponse({
                'success': False,
                'message': '邮箱格式不正确'
            }, status=400)
        
        # 验证URL格式（如果填写了）
        if wx_url and not wx_url.startswith(('http://', 'https://')):
            return JsonResponse({
                'success': False,
                'message': '企业微信通知URL格式不正确，需以 http:// 或 https:// 开头'
            }, status=400)
        
        # 记录变更
        changes = []
        if first_name != user.first_name:
            changes.append(f'姓名: {user.first_name} -> {first_name}')
            user.first_name = first_name
        
        if email != user.email:
            changes.append(f'邮箱: {user.email} -> {email}')
            user.email = email
        
        if phone != user.phone:
            changes.append(f'手机号: {user.phone} -> {phone}')
            user.phone = phone
        
        if wx_url != (user.wx_url or ''):
            changes.append(f'企业微信通知URL: 已{"设置" if wx_url else "清空"}')
            user.wx_url = wx_url if wx_url else None
        
        if changes:
            user.save(update_fields=['first_name', 'email', 'phone', 'wx_url'])
            
            # 记录操作日志
            UserOperationLog.objects.create(
                company=user.company,
                user=user,
                operation_type=1002,  # 修改用户信息
                operation_record=f'用户 {user.first_name or user.username} 修改了基本信息: {", ".join(changes)}'
            )
        
        return JsonResponse({
            'success': True,
            'message': '保存成功'
        })
        
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'message': '请求数据格式错误'
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'保存失败: {str(e)}'
        }, status=500)


@require_POST
@csrf_protect
@login_required
def change_password_api(request):
    """
    修改密码 API
    POST /api/profile/password/
    """
    user = request.user
    
    try:
        data = json.loads(request.body)
        
        current_password = data.get('current_password', '')
        new_password = data.get('new_password', '')
        
        # 验证当前密码
        if not check_password(current_password, user.password):
            return JsonResponse({
                'success': False,
                'message': '当前密码不正确'
            }, status=400)
        
        # 验证新密码长度
        if len(new_password) < 6:
            return JsonResponse({
                'success': False,
                'message': '新密码至少需要6位'
            }, status=400)
        
        # 更新密码
        user.password = make_password(new_password)
        user.save(update_fields=['password'])
        
        # 记录操作日志（不记录密码内容）
        UserOperationLog.objects.create(
            company=user.company,
            user=user,
            operation_type=1002,  # 修改用户信息
            operation_record=f'用户 {user.first_name or user.username} 修改了登录密码'
        )
        
        return JsonResponse({
            'success': True,
            'message': '密码修改成功'
        })
        
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'message': '请求数据格式错误'
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'修改失败: {str(e)}'
        }, status=500)
