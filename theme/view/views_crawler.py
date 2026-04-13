"""
Amazon数据抓取工具视图
包含：页面渲染、搜索API
"""
import os
import re
import asyncio
import aiohttp
import ssl
from lxml import html
from datetime import datetime

from django.shortcuts import render
from django.http import JsonResponse
from django.core.cache import cache
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from django.conf import settings

# 禁用SSL验证（解决部分SSL证书问题）
ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE


def convert_to_original(url):
    """将亚马逊缩略图URL转换为原图URL"""
    if not url:
        return url
    filename = url.split('/')[-1]
    clean_filename = re.sub(r'\._[^.]+_', '', filename)
    base_url = '/'.join(url.split('/')[:-1])
    return f"{base_url}/{clean_filename}"


async def search_amazon_images_async(keyword):
    """异步搜索Amazon图片"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36 Edg/145.0.0.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Connection": "keep-alive",
        "Host": "www.amazon.com",
        "Pragma": "no-cache",
        "Cache-Control": "no-cache",
        "sec-ch-ua": '"Chromium";v="128", "Not;A=Brand";v="24", "Google Chrome";v="128"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-User": "?1",
        "Sec-Fetch-Dest": "document",
        "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    }

    search_url = f"https://www.amazon.com/s?k={keyword.replace(' ', '+')}"
    print(f"搜索URL: {search_url}")
    async with aiohttp.ClientSession() as session:
        async with session.get(search_url, headers=headers, ssl=ssl_context) as response:
            html_content = await response.text()


            if "dogs of amazon" in html_content.lower() or response.status != 200:
                return [], f"访问被拦截 (Status: {response.status})"

            tree = html.fromstring(html_content)
            image_urls = tree.xpath('//div[@role="listitem"]//img[@class="s-image"]/@src')

            if not image_urls:
                return [], "未找到图片"

            results = []
            for idx, url in enumerate(image_urls):
                original_url = convert_to_original(url)
                results.append({
                    "thumb_url": url,
                    "original_url": original_url,
                    "id": idx
                })

            return results, f"找到 {len(image_urls)} 张图片"


def has_crawler_permission(user):
    """检查用户是否有数据抓取工具权限 (code=555 或 code=9)"""
    if not user.is_authenticated:
        return False
    return user.permission_configs.filter(code__in=[555, 9]).exists()


@login_required
def amazon_data_crawler_page(request):
    """
    Amazon数据抓取工具页面
    权限要求：code=555 或 code=9
    """
    if not has_crawler_permission(request.user):
        return render(request, 'error/403.html', {
            'message': '您没有权限访问此页面，需要数据抓取工具权限'
        }, status=403)

    return render(request, 'amazon_data_crawler.html', {
        'active_page': 'amazon_data_crawler',
        'active_nav': 'theme'
    })


@login_required
@require_POST
def api_amazon_search(request):
    """
    Amazon图片搜索API
    权限要求：code=555 或 code=9
    缓存时间：60分钟
    """
    if not has_crawler_permission(request.user):
        return JsonResponse({
            'success': False,
            'message': '权限不足'
        }, status=403)

    try:
        import json
        data = json.loads(request.body)
        keyword = data.get('keyword', '').strip()

        if not keyword:
            return JsonResponse({
                'success': False,
                'message': '请输入搜索关键词'
            })

        # 构建缓存key
        cache_key = f"amazon_crawler:search:{keyword.lower().replace(' ', '_')}"
        
        # 尝试从缓存获取
        cached_result = cache.get(cache_key)
        if cached_result:
            return JsonResponse({
                'success': True,
                'images': cached_result['images'],
                'message': f"找到 {len(cached_result['images'])} 张图片（缓存）",
                'cached': True
            })

        # 异步执行搜索
        if os.name == 'nt':
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        results, msg = loop.run_until_complete(search_amazon_images_async(keyword))
        loop.close()

        if not results:
            return JsonResponse({
                'success': False,
                'message': msg
            })

        # 存入缓存（60分钟）
        cache.set(cache_key, {
            'images': results,
            'keyword': keyword,
            'cached_at': datetime.now().isoformat()
        }, timeout=60 * 60)  # 60分钟

        return JsonResponse({
            'success': True,
            'images': results,
            'message': msg,
            'cached': False
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'搜索失败: {str(e)}'
        })
