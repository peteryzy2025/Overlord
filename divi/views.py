# -*- coding: utf-8 -*-
"""
Divi 应用视图
"""
import json
import threading
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .api.update_template import sync_templates_to_db


# CORS 响应头
CORS_HEADERS = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
}


def cors_json_response(data, status=200):
    """返回带 CORS 头的 JsonResponse"""
    response = JsonResponse(data, status=status)
    for key, value in CORS_HEADERS.items():
        response[key] = value
    return response


@csrf_exempt
def sync_templates_api(request):
    """
    接收 cookie 并异步执行模板同步
    
    POST 参数:
        cookie: str - DIVI 网站的 cookie 字符串
        company_id: int - 公司ID（可选，默认1）
    
    Returns:
        {"success": true, "message": "任务已提交，后台同步中..."}
    """
    # 处理 OPTIONS 预检请求
    if request.method == 'OPTIONS':
        response = JsonResponse({})
        for key, value in CORS_HEADERS.items():
            response[key] = value
        return response
    
    if request.method != 'POST':
        return cors_json_response({
            'success': False,
            'message': '只支持 POST 请求'
        }, 405)
    
    try:
        data = json.loads(request.body)
        cookie = data.get('cookie', '')
        company_id = data.get('company_id', 1)
        
        if not cookie:
            return cors_json_response({
                'success': False,
                'message': '缺少 cookie 参数'
            }, 400)
        
        # 启动后台线程执行同步任务
        def run_sync():
            try:
                print(f"[后台任务] 开始同步模板，company_id={company_id}")
                stats = sync_templates_to_db(cookie=cookie, company_id=company_id)
                print(f"[后台任务] 同步完成: {stats}")
            except Exception as e:
                print(f"[后台任务] 同步失败: {e}")
        
        thread = threading.Thread(target=run_sync, daemon=True)
        thread.start()
        
        return cors_json_response({
            'success': True,
            'message': '任务已提交，后台同步中...\n请稍后查看数据库更新结果'
        })
        
    except json.JSONDecodeError:
        return cors_json_response({
            'success': False,
            'message': '请求格式错误，需要 JSON'
        }, 400)
    except Exception as e:
        return cors_json_response({
            'success': False,
            'message': f'服务器错误: {str(e)}'
        }, 500)
