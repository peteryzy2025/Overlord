# -*- coding: utf-8 -*-
"""
Divi 应用视图
"""
import json
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .api.update_template import sync_templates_to_db
from .api.sync_image_classify import sync_image_classify


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
    接收 cookie 并同步执行模板同步，返回详细统计
    
    POST 参数:
        cookie: str - DIVI 网站的 cookie 字符串
        company_id: int - 公司ID（可选，默认1）
    
    Returns:
        {
            "success": true,
            "stats": {
                "total_fetched": 17,
                "created": 0,
                "updated": 17,
                "failed": 0,
                "skipped_products": 0,
                "skipped_shops": 0
            }
        }
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
        
        print(f"[同步模板] 开始执行，company_id={company_id}")
        print(f"[同步模板] Cookie: {cookie[:80]}...")
        
        # 同步执行，等待结果
        stats = sync_templates_to_db(cookie=cookie, company_id=company_id)
        
        print(f"[同步模板] 完成: {stats}")
        
        return cors_json_response({
            'success': True,
            'stats': stats
        })
        
    except json.JSONDecodeError:
        return cors_json_response({
            'success': False,
            'message': '请求格式错误，需要 JSON'
        }, 400)
    except Exception as e:
        import traceback
        print(f"[同步模板] 异常: {e}")
        print(traceback.format_exc())
        return cors_json_response({
            'success': False,
            'message': f'服务器错误: {str(e)}'
        }, 500)


@csrf_exempt
def sync_image_classify_api(request):
    """
    接收 cookie 并同步执行图库分类同步
    
    POST 参数:
        cookie: str - DIVI 网站的 cookie 字符串
    
    Returns:
        {
            "success": true,
            "stats": {
                "fetched": 100,
                "created": 100,
                "updated": 0,
                "failed": 0
            }
        }
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
        
        if not cookie:
            return cors_json_response({
                'success': False,
                'message': '缺少 cookie 参数'
            }, 400)
        
        print(f"[同步图库分类] 开始执行")
        print(f"[同步图库分类] Cookie: {cookie[:80]}...")
        
        # 同步执行，等待结果
        stats = sync_image_classify(cookie=cookie, technology_classify_id=100002)
        
        print(f"[同步图库分类] 完成: {stats}")
        
        return cors_json_response({
            'success': True,
            'stats': stats
        })
        
    except json.JSONDecodeError:
        return cors_json_response({
            'success': False,
            'message': '请求格式错误，需要 JSON'
        }, 400)
    except Exception as e:
        import traceback
        print(f"[同步图库分类] 异常: {e}")
        print(traceback.format_exc())
        return cors_json_response({
            'success': False,
            'message': f'服务器错误: {str(e)}'
        }, 500)
