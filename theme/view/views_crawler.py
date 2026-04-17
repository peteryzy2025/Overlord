"""
Amazon数据抓取工具视图
包含：页面渲染、搜索API
"""
import os
import re
import random
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


async def fetch_page(session, keyword, page_num, referer=None):
    """获取单页数据"""
    # 页面间添加随机延迟，避免被拦截
    if page_num > 1:
        await asyncio.sleep(random.uniform(0.8, 2.0))
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "DNT": "1",
        "Host": "www.amazon.com",
        "Pragma": "no-cache",
        "sec-ch-ua": '"Google Chrome";v="135", "Not-A.Brand";v="8", "Chromium";v="135"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "Sec-Fetch-Site": "same-origin" if referer else "none",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-User": "?1",
        "Sec-Fetch-Dest": "document",
        "Upgrade-Insecure-Requests": "1",
    }
    
    if referer:
        headers["Referer"] = referer

    search_url = f"https://www.amazon.com/s?k={keyword.replace(' ', '+')}&page={page_num}"
    print(f"[Amazon爬虫] 正在请求: {search_url}", flush=True)
    
    try:
        async with session.get(search_url, headers=headers, ssl=ssl_context) as response:
            html_content = await response.text()
            print(f"[Amazon爬虫] 响应状态码: {response.status}, 内容长度: {len(html_content)}", flush=True)
            
            if response.status != 200:
                print(f"[Amazon爬虫] 非200状态码, status={response.status}", flush=True)
                print(f"[Amazon爬虫] HTML片段: {html_content[:800]}", flush=True)
                return None
            
            lower_html = html_content.lower()
            if "dogs of amazon" in lower_html:
                print(f"[Amazon爬虫] 检测到拦截页面(dogs of amazon)", flush=True)
                print(f"[Amazon爬虫] HTML片段: {html_content[:800]}", flush=True)
                return None
            
            if any(x in lower_html for x in [
                "automated access",
                "api-services-support",
                "sorry, we just need to make sure you're not a robot",
                "enter the characters you see below"
            ]):
                print(f"[Amazon爬虫] 检测到反机器人验证页面", flush=True)
                print(f"[Amazon爬虫] HTML片段: {html_content[:800]}", flush=True)
                return None
            
            tree = html.fromstring(html_content)
            image_urls = tree.xpath('//div[@role="listitem"]//img[@class="s-image"]/@src')
            print(f"[Amazon爬虫] 解析到 {len(image_urls)} 张图片", flush=True)
            
            return image_urls
    except Exception as e:
        print(f"[Amazon爬虫] fetch_page异常: {type(e).__name__}: {e}", flush=True)
        raise


async def search_amazon_images_async(keyword, max_pages=3):
    """异步搜索Amazon图片，默认爬3页"""
    all_image_urls = []
    
    # 预热：先访问首页建立 Cookie
    home_url = "https://www.amazon.com/"
    base_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "DNT": "1",
        "Pragma": "no-cache",
        "sec-ch-ua": '"Google Chrome";v="135", "Not-A.Brand";v="8", "Chromium";v="135"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-User": "?1",
        "Sec-Fetch-Dest": "document",
        "Upgrade-Insecure-Requests": "1",
    }
    
    async with aiohttp.ClientSession() as session:
        print(f"[Amazon爬虫-批量] 预热: {home_url}", flush=True)
        async with session.get(home_url, headers={**base_headers, "Host": "www.amazon.com"}, ssl=ssl_context) as home_resp:
            home_html = await home_resp.text()
            print(f"[Amazon爬虫-批量] 首页状态码: {home_resp.status}, 长度: {len(home_html)}", flush=True)
        
        for page in range(1, max_pages + 1):
            image_urls = await fetch_page(session, keyword, page, referer=home_url)
            
            if image_urls is None:
                # 被拦截了，终止爬取
                if page == 1:
                    return [], "访问被拦截"
                break
            
            if not image_urls:
                # 该页没有数据，结束
                break
            
            all_image_urls.extend(image_urls)
    
    if not all_image_urls:
        return [], "未找到图片"
    
    # 去重（根据缩略图URL）
    seen = set()
    unique_results = []
    idx = 0
    for url in all_image_urls:
        if url not in seen:
            seen.add(url)
            original_url = convert_to_original(url)
            unique_results.append({
                "thumb_url": url,
                "original_url": original_url,
                "id": idx
            })
            idx += 1
    
    return unique_results, f"找到 {len(unique_results)} 张图片"


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


async def fetch_single_page_async(keyword, page_num):
    """获取单页数据（用于逐页搜索API）"""
    base_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "DNT": "1",
        "Pragma": "no-cache",
        "sec-ch-ua": '"Google Chrome";v="135", "Not-A.Brand";v="8", "Chromium";v="135"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-User": "?1",
        "Sec-Fetch-Dest": "document",
        "Upgrade-Insecure-Requests": "1",
    }

    search_url = f"https://www.amazon.com/s?k={keyword.replace(' ', '+')}&page={page_num}"
    print(f"[Amazon爬虫-单页] 正在请求: {search_url}", flush=True)
    
    try:
        # 先访问首页建立 Cookie 会话，再搜索
        async with aiohttp.ClientSession() as session:
            # 1) 预热：访问首页
            home_url = "https://www.amazon.com/"
            print(f"[Amazon爬虫-单页] 预热: {home_url}", flush=True)
            async with session.get(home_url, headers={**base_headers, "Host": "www.amazon.com"}, ssl=ssl_context) as home_resp:
                home_html = await home_resp.text()
                print(f"[Amazon爬虫-单页] 首页状态码: {home_resp.status}, 长度: {len(home_html)}", flush=True)
            
            await asyncio.sleep(random.uniform(0.8, 1.5))
            
            # 2) 搜索请求，带上 Referer
            search_headers = {
                **base_headers,
                "Host": "www.amazon.com",
                "Referer": home_url,
                "Sec-Fetch-Site": "same-origin",
            }
            
            async with session.get(search_url, headers=search_headers, ssl=ssl_context) as response:
                html_content = await response.text()
                print(f"[Amazon爬虫-单页] 响应状态码: {response.status}, 内容长度: {len(html_content)}", flush=True)
                
                if response.status != 200:
                    print(f"[Amazon爬虫-单页] 非200状态码拦截, status={response.status}", flush=True)
                    print(f"[Amazon爬虫-单页] HTML片段: {html_content[:800]}", flush=True)
                    return None, f"访问被拦截 (Status: {response.status})"
                
                if "dogs of amazon" in html_content.lower():
                    print(f"[Amazon爬虫-单页] 检测到拦截页面(dogs of amazon)", flush=True)
                    print(f"[Amazon爬虫-单页] HTML片段: {html_content[:800]}", flush=True)
                    return None, f"访问被拦截 (Status: {response.status})"
                
                # 再检查是否返回了 robot/check 页面（常见反爬特征）
                lower_html = html_content.lower()
                if any(x in lower_html for x in [
                    "automated access",
                    "api-services-support",
                    "sorry, we just need to make sure you're not a robot",
                    "enter the characters you see below"
                ]):
                    print(f"[Amazon爬虫-单页] 检测到反机器人验证页面", flush=True)
                    print(f"[Amazon爬虫-单页] HTML片段: {html_content[:800]}", flush=True)
                    return None, f"访问被拦截 (Status: {response.status})"
                
                tree = html.fromstring(html_content)
                image_urls = tree.xpath('//div[@role="listitem"]//img[@class="s-image"]/@src')
                print(f"[Amazon爬虫-单页] 解析到 {len(image_urls)} 张图片", flush=True)
                
                results = []
                for idx, url in enumerate(image_urls):
                    original_url = convert_to_original(url)
                    results.append({
                        "thumb_url": url,
                        "original_url": original_url,
                        "id": idx
                    })
                
                return results, f"找到 {len(results)} 张图片"
    except Exception as e:
        print(f"[Amazon爬虫-单页] fetch_single_page_async异常: {type(e).__name__}: {e}", flush=True)
        raise


@login_required
@require_POST
def api_amazon_search_page(request):
    """
    Amazon图片单页搜索API（用于显示分页进度）
    权限要求：code=555 或 code=9
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
        page = int(data.get('page', 1))

        if not keyword:
            return JsonResponse({
                'success': False,
                'message': '请输入搜索关键词'
            })

        # 异步执行单页搜索
        if os.name == 'nt':
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        results, msg = loop.run_until_complete(fetch_single_page_async(keyword, page))
        loop.close()

        if results is None:
            return JsonResponse({
                'success': False,
                'message': msg
            })

        return JsonResponse({
            'success': True,
            'images': results,
            'page': page,
            'message': msg
        })

    except Exception as e:
        import traceback
        print(f"[Amazon爬虫-API] api_amazon_search_page异常: {type(e).__name__}: {e}", flush=True)
        traceback.print_exc()
        return JsonResponse({
            'success': False,
            'message': f'搜索失败: {str(e)}'
        })


@login_required
@require_POST
def api_amazon_search(request):
    """
    Amazon图片搜索API（一次性搜索多页，保留用于兼容性）
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
        pages = min(int(data.get('pages', 1)), 50)  # 最大50页

        if not keyword:
            return JsonResponse({
                'success': False,
                'message': '请输入搜索关键词'
            })

        # 构建缓存key
        cache_key = f"amazon_crawler:search:{keyword.lower().replace(' ', '_')}:p{pages}"
        
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
        results, msg = loop.run_until_complete(search_amazon_images_async(keyword, max_pages=pages))
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
        import traceback
        print(f"[Amazon爬虫-API] api_amazon_search异常: {type(e).__name__}: {e}", flush=True)
        traceback.print_exc()
        return JsonResponse({
            'success': False,
            'message': f'搜索失败: {str(e)}'
        })
