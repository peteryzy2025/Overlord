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


def parse_product_from_item(item_div):
    """从单个商品div解析所有字段"""
    result = {
        'thumb_url': '',
        'original_url': '',
        'asin': '',
        'title': '',
        'monthly_sales': '',
        'rating_count': '',
    }

    # ASIN
    asin = item_div.get('data-asin', '')
    result['asin'] = asin

    # 图片
    img = item_div.xpath('.//img[@class="s-image"]')
    if img:
        thumb_url = img[0].get('src', '')
        result['thumb_url'] = thumb_url
        result['original_url'] = convert_to_original(thumb_url)

    # 标题: 从 h2 提取完整文本
    h2_elems = item_div.xpath('.//h2[contains(@class,"a-size-base-plus")]')
    if h2_elems:
        result['title'] = h2_elems[0].text_content().strip()

    # 月销量: 找包含数字+的 a-size-base a-color-secondary span
    sales_spans = item_div.xpath('.//span[@class="a-size-base a-color-secondary"]')
    for s in sales_spans:
        text = s.text_content().strip()
        match = re.search(r'(\d+\+?)', text)
        if match:
            result['monthly_sales'] = match.group(1)
            break

    # 评分数量: (6)
    rating_els = item_div.xpath('.//span[@class="a-size-mini puis-normal-weight-text s-underline-text"]/text()')
    for text in rating_els:
        text = text.strip()
        match = re.search(r'\((\d+)\)', text)
        if match:
            result['rating_count'] = match.group(1)
            break

    return result


def sort_products(products):
    """
    对商品列表进行排序
    规则:
    1. 有月销量优先，按销量降序
    2. 销量相同，按评分数量降序
    3. 无销量，按评分数量降序
    4. 都没有，保持原始顺序
    """
    def sort_key(product):
        sales_str = product.get('monthly_sales', '')
        rating_str = product.get('rating_count', '')
        
        # 提取销量数字
        sales_num = 0
        if sales_str:
            match = re.search(r'(\d+)', sales_str)
            if match:
                sales_num = int(match.group(1))
        
        # 提取评分数字
        rating_num = 0
        if rating_str:
            match = re.search(r'(\d+)', rating_str)
            if match:
                rating_num = int(match.group(1))
        
        # 排序键: (-是否有销量, -销量, -评分, 原始索引)
        # 有销量的 sales_num > 0，放前面
        has_sales = 1 if sales_num > 0 else 0
        
        return (-has_sales, -sales_num, -rating_num)
    
    # 保留原始索引用于同分时保持顺序
    indexed = [(i, p) for i, p in enumerate(products)]
    indexed.sort(key=lambda x: (sort_key(x[1]), x[0]))
    
    sorted_products = []
    for new_idx, (old_idx, product) in enumerate(indexed, 1):
        product['sort_order'] = new_idx
        sorted_products.append(product)
    
    return sorted_products


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
            # 获取每个商品div
            item_divs = tree.xpath('//div[@role="listitem" and @data-asin]')
            print(f"[Amazon爬虫] 解析到 {len(item_divs)} 个商品", flush=True)
            
            products = []
            for item_div in item_divs:
                product = parse_product_from_item(item_div)
                if product['thumb_url']:
                    products.append(product)
            
            return products
    except Exception as e:
        print(f"[Amazon爬虫] fetch_page异常: {type(e).__name__}: {e}", flush=True)
        raise


async def search_amazon_images_async(keyword, max_pages=3):
    """异步搜索Amazon图片，默认爬3页"""
    all_products = []
    
    # 预热：先访问首页建立 Cookie
    home_url = "https://www.amazon.com/"
    base_headers = headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36 Edg/146.0.0.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.amazon.com/",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1",
    "sec-ch-ua": "\"Chromium\";v=\"146\", \"Not-A.Brand\";v=\"24\", \"Microsoft Edge\";v=\"146\"",
    "sec-ch-ua-full-version-list": "\"Chromium\";v=\"146.0.7680.166\", \"Not-A.Brand\";v=\"24.0.0.0\", \"Microsoft Edge\";v=\"146.0.3856.84\"",
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": "\"Windows\"",
    "sec-ch-ua-platform-version": "\"15.0.0\"",
    "sec-ch-viewport-width": "1912",
    "sec-ch-dpr": "1",
    "sec-ch-device-memory": "8",
    "device-memory": "8",
    "viewport-width": "1912",
    "dpr": "1",
    "ect": "4g",
    "rtt": "150",
    "downlink": "8.7",
    "Connection": "keep-alive",
    "Cache-Control": "max-age=0",
}
    
    async with aiohttp.ClientSession() as session:
        print(f"[Amazon爬虫-批量] 预热: {home_url}", flush=True)
        async with session.get(home_url, headers={**base_headers, "Host": "www.amazon.com"}, ssl=ssl_context) as home_resp:
            home_html = await home_resp.text()
            print(f"[Amazon爬虫-批量] 首页状态码: {home_resp.status}, 长度: {len(home_html)}", flush=True)
        
        for page in range(1, max_pages + 1):
            products = await fetch_page(session, keyword, page, referer=home_url)
            
            if products is None:
                # 被拦截了，终止爬取
                if page == 1:
                    return [], "访问被拦截"
                break
            
            if not products:
                # 该页没有数据，结束
                break
            
            all_products.extend(products)
    
    if not all_products:
        return [], "未找到图片"
    
    # 去重（根据ASIN）
    seen = set()
    unique_results = []
    for product in all_products:
        key = product.get('asin', '') or product.get('thumb_url', '')
        if key and key not in seen:
            seen.add(key)
            unique_results.append(product)
    
    # 排序
    sorted_results = sort_products(unique_results)
    
    # 重新分配 id
    for idx, product in enumerate(sorted_results):
        product['id'] = idx
    
    return sorted_results, f"找到 {len(sorted_results)} 个商品"


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


# 可选：从环境变量读取代理配置
# 格式: http://host:port 或 http://user:pass@host:port
PROXY_URL = os.environ.get('AMAZON_PROXY', '')


async def fetch_single_page_async(keyword, page_num):
    """获取单页数据（用于逐页搜索API），带重试和超时机制"""
    base_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36 Edg/146.0.0.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": "https://www.amazon.com/",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-User": "?1",
        "sec-ch-ua": "\"Chromium\";v=\"146\", \"Not-A.Brand\";v=\"24\", \"Microsoft Edge\";v=\"146\"",
        "sec-ch-ua-full-version-list": "\"Chromium\";v=\"146.0.7680.166\", \"Not-A.Brand\";v=\"24.0.0.0\", \"Microsoft Edge\";v=\"146.0.3856.84\"",
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": "\"Windows\"",
        "sec-ch-ua-platform-version": "\"15.0.0\"",
        "sec-ch-viewport-width": "1912",
        "sec-ch-dpr": "1",
        "sec-ch-device-memory": "8",
        "device-memory": "8",
        "viewport-width": "1912",
        "dpr": "1",
        "ect": "4g",
        "rtt": "150",
        "downlink": "8.7",
        "Connection": "keep-alive",
        "Cache-Control": "max-age=0",
    }

    search_url = f"https://www.amazon.com/s?k={keyword.replace(' ', '+')}&page={page_num}"
    print(f"[Amazon爬虫-单页] 正在请求: {search_url}", flush=True)

    max_retries = 3
    # 调大超时：total=60, connect=20, sock_connect=20, sock_read=40
    timeout = aiohttp.ClientTimeout(total=60, connect=20, sock_connect=20, sock_read=40)

    for attempt in range(1, max_retries + 1):
        # 每次重试都创建新的 Connector 和 Session（避免 Session is closed）
        connector = aiohttp.TCPConnector(
            limit=10,
            limit_per_host=5,
            enable_cleanup_closed=True,
            force_close=True,  # 每次请求后强制关闭连接，避免复用问题
            ttl_dns_cache=300,
            use_dns_cache=True,
        )

        try:
            async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
                # 直接搜索，不再预热首页（减少一次请求，降低超时概率）
                search_headers = {
                    **base_headers,
                    "Host": "www.amazon.com",
                    "Sec-Fetch-Site": "none",
                    "Sec-Fetch-User": "?1",
                }

                request_kwargs = {
                    "headers": search_headers,
                    "ssl": ssl_context,
                }
                if PROXY_URL:
                    request_kwargs["proxy"] = PROXY_URL
                    print(f"[Amazon爬虫-单页] 使用代理: {PROXY_URL}", flush=True)

                print(f"[Amazon爬虫-单页] 请求搜索页 (尝试 {attempt}/{max_retries})", flush=True)
                async with session.get(search_url, **request_kwargs) as response:
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
                    item_divs = tree.xpath('//div[@role="listitem" and @data-asin]')
                    print(f"[Amazon爬虫-单页] 解析到 {len(item_divs)} 个商品", flush=True)

                    results = []
                    for item_div in item_divs:
                        product = parse_product_from_item(item_div)
                        if product['thumb_url']:
                            results.append(product)

                    # 排序
                    sorted_results = sort_products(results)
                    for idx, product in enumerate(sorted_results):
                        product['id'] = idx

                    return sorted_results, f"找到 {len(sorted_results)} 个商品"

        except (aiohttp.ClientConnectorError, aiohttp.ServerTimeoutError, asyncio.TimeoutError,
                aiohttp.ClientOSError, aiohttp.ClientHttpProxyError) as e:
            print(f"[Amazon爬虫-单页] 网络异常 (尝试 {attempt}/{max_retries}): {type(e).__name__}: {e}", flush=True)
            if attempt < max_retries:
                wait_time = 3 ** attempt  # 指数退避: 3, 9, 27秒
                print(f"[Amazon爬虫-单页] {wait_time}秒后重试...", flush=True)
                await asyncio.sleep(wait_time)
            else:
                print(f"[Amazon爬虫-单页] 重试 {max_retries} 次后仍然失败", flush=True)
                return None, f"网络连接超时，请稍后重试 ({type(e).__name__})"
        except Exception as e:
            print(f"[Amazon爬虫-单页] fetch_single_page_async异常: {type(e).__name__}: {e}", flush=True)
            raise
        finally:
            # 确保 connector 被关闭
            if connector:
                await connector.close()


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
def api_amazon_batch_download(request):
    """
    批量下载选中的Amazon图片到服务器指定路径
    请求体: { products: [{thumb_url, original_url, asin, brand, title, ...}], save_path: "\\\\ZT-NAS\\xxx", keyword: "250 T-shirt" }
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
        products = data.get('products', [])
        save_path = data.get('save_path', '').strip()
        keyword = data.get('keyword', '').strip()

        if not products:
            return JsonResponse({
                'success': False,
                'message': '未选择任何商品'
            })

        if not save_path:
            return JsonResponse({
                'success': False,
                'message': '保存路径不能为空'
            })

        # 安全检查：必须是 NAS 路径，以 \\ZT-NAS 开头（不区分大小写）
        save_path = os.path.normpath(save_path)
        if '..' in save_path:
            return JsonResponse({
                'success': False,
                'message': '保存路径不合法'
            })
        if not re.match(r'(?i)^\\\\ZT-NAS', save_path):
            return JsonResponse({
                'success': False,
                'message': '保存路径必须是 \\ZT-NAS 开头的 NAS 路径'
            })

        # 直接使用用户指定的路径，不再自动添加日期子文件夹
        target_dir = save_path
        os.makedirs(target_dir, exist_ok=True)

        # 下载headers
        download_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": "https://www.amazon.com/",
        }

        async def download_image(session, product, idx):
            """单张图片下载，文件名包含ASIN"""
            url = product.get('original_url') or product.get('thumb_url', '')
            asin = product.get('asin', '')
            brand = product.get('brand', '')
            title = product.get('title', '')
            
            if not url:
                return {'asin': asin, 'status': 'failed', 'error': '无图片URL'}
            
            try:
                # 构建文件名：ASIN_品牌_标题.jpg（清理非法字符）
                safe_brand = re.sub(r'[\\/:*?"<>|]', '_', brand)[:30] if brand else ''
                safe_title = re.sub(r'[\\/:*?"<>|]', '_', title)[:40] if title else ''
                
                if asin:
                    file_name = f"{asin}"
                    if safe_brand:
                        file_name += f"_{safe_brand}"
                    if safe_title:
                        file_name += f"_{safe_title}"
                else:
                    # 无ASIN时从URL取文件名
                    parsed = url.split('/')[-1]
                    file_name = re.sub(r'[\\/:*?"<>|]', '_', parsed)
                    if not file_name or file_name == '_':
                        file_name = f"image_{idx}"
                
                # 确保有扩展名
                if '.' not in file_name:
                    file_name += '.jpg'
                
                file_path = os.path.join(target_dir, file_name)
                # 如果文件名已存在，添加序号
                counter = 1
                original_file_path = file_path
                while os.path.exists(file_path):
                    name, ext = os.path.splitext(original_file_path)
                    file_path = f"{name}_{counter}{ext}"
                    counter += 1

                async with session.get(url, headers=download_headers, ssl=ssl_context, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    if resp.status == 200:
                        content = await resp.read()
                        with open(file_path, 'wb') as f:
                            f.write(content)
                        return {
                            'asin': asin,
                            'status': 'success',
                            'path': file_path,
                            'size': len(content),
                            'brand': brand,
                            'title': title
                        }
                    else:
                        return {'asin': asin, 'status': 'failed', 'error': f'HTTP {resp.status}'}
            except Exception as e:
                return {'asin': asin, 'status': 'failed', 'error': str(e)}

        async def download_all():
            async with aiohttp.ClientSession() as session:
                tasks = [download_image(session, product, i) for i, product in enumerate(products)]
                return await asyncio.gather(*tasks)

        # 执行异步下载
        if os.name == 'nt':
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        results = loop.run_until_complete(download_all())
        loop.close()

        success_count = sum(1 for r in results if r['status'] == 'success')
        failed_count = len(results) - success_count
        failed_items = [r for r in results if r['status'] == 'failed']

        return JsonResponse({
            'success': True,
            'message': f'下载完成：成功 {success_count} 张，失败 {failed_count} 张',
            'save_dir': target_dir,
            'total': len(products),
            'success_count': success_count,
            'failed_count': failed_count,
            'failed_items': failed_items
        })

    except Exception as e:
        import traceback
        print(f"[Amazon下载] 批量下载异常: {type(e).__name__}: {e}", flush=True)
        traceback.print_exc()
        return JsonResponse({
            'success': False,
            'message': f'下载失败: {str(e)}'
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
