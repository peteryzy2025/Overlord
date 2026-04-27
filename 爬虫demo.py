"""
Amazon Scraper Demo — 直接运行版
搜索商品并提取：ASIN / Title / Image URL / Monthly Sales / Review Count / Rank

依赖安装:
    pip install aiohttp lxml

运行:
    python amazon_scraper_demo.py
"""
import asyncio
import re
import ssl
import json
import time
import random
import string
from urllib.parse import quote

import aiohttp
from lxml import html

# ============ 配置 ============
KEYWORD = "250 T-shirt"      # 搜索关键词
MAX_PAGES = 3                # 爬取页数
OUTPUT_FILE = "scraping_result.json"  # 输出文件

# ============ SSL (跳过验证) ============
ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE


# ============ 搜索会话管理 ============
class AmazonSearchSession:
    """管理一次 Amazon 搜索会话的参数状态。"""

    def __init__(self, keyword: str):
        self.keyword = keyword
        self.encoded_kw = keyword.replace(' ', '+')
        self.crid = self._generate_crid()
        self.sprefix = self._build_sprefix()
        self.first_page_url = None

    @staticmethod
    def _generate_crid() -> str:
        """生成 Amazon 风格的 crid：15位大写字母+数字"""
        return ''.join(random.choices(string.ascii_uppercase + string.digits, k=15))

    @staticmethod
    def _generate_xpid() -> str:
        """生成 xpid"""
        chars = string.ascii_lowercase + string.ascii_uppercase + string.digits + '-'
        return ''.join(random.choices(chars, k=random.randint(13, 15)))

    def _build_sprefix(self) -> str:
        """构建 sprefix 参数"""
        pos = random.randint(330, 370)
        raw = f"{self.encoded_kw.lower()},aps,{pos}"
        return quote(raw, safe='')

    def build_url(self, page_num: int) -> str:
        """根据页码构建完整的 Amazon 搜索 URL"""
        if page_num == 1:
            params = {
                'k': self.encoded_kw,
                'crid': self.crid,
                'sprefix': self.sprefix,
                'ref': 'nb_sb_noss_1',
            }
            url = f"https://www.amazon.com/s?{self._encode_params(params)}"
            self.first_page_url = url
            return url
        else:
            params = {
                'k': self.encoded_kw,
                'page': str(page_num),
                'crid': self.crid,
                'qid': str(int(time.time())),
                'sprefix': self.sprefix,
                'xpid': self._generate_xpid(),
                'ref': f'sr_pg_{page_num}',
            }
            return f"https://www.amazon.com/s?{self._encode_params(params)}"

    @staticmethod
    def _encode_params(params: dict) -> str:
        """将字典编码为 URL 查询字符串"""
        parts = []
        for k, v in params.items():
            parts.append(f"{quote(str(k))}={quote(str(v))}")
        return '&'.join(parts)

    def get_referer(self, page_num: int) -> str | None:
        """获取当前页应该使用的 Referer"""
        if page_num == 1:
            return "https://www.amazon.com/"
        return self.first_page_url


# ============ 工具函数 ============
def convert_to_original(url: str) -> str:
    """将缩略图URL转换为原图URL（去除尺寸限制）"""
    if not url:
        return url
    filename = url.split('/')[-1]
    clean_filename = re.sub(r'\._[^.]+_', '', filename)
    base_url = '/'.join(url.split('/')[:-1])
    return f"{base_url}/{clean_filename}"


def parse_product_from_item(item_div, rank: int) -> dict:
    """从单个商品 div 解析用户需要的字段"""
    result = {
        'asin': '',
        'title': '',
        'image_url': '',
        'monthly_sales': '',
        'review_count': '',
        'rank': rank,
    }

    # ASIN
    result['asin'] = item_div.get('data-asin', '')

    # Title - 尝试多个选择器
    for xpath in [
        './/h2[contains(@class,"a-size-base-plus")]//text()',
        './/h2//a//span//text()',
        './/h2//span//text()',
        './/h2//text()',
    ]:
        texts = item_div.xpath(xpath)
        if texts:
            title = ''.join(t.strip() for t in texts).strip()
            if title:
                result['title'] = title
                break

    # Image URL (取高清原图)
    img = item_div.xpath('.//img[@class="s-image"]')
    if img:
        thumb_url = img[0].get('src', '')
        result['image_url'] = convert_to_original(thumb_url)
    else:
        # 备用：找任何img
        img_any = item_div.xpath('.//img')
        if img_any:
            result['image_url'] = convert_to_original(img_any[0].get('src', ''))

    # Monthly Sales: "500+ bought in past month"
    # 先在新结构里找
    sales_spans = item_div.xpath('.//span[contains(@class,"a-color-secondary")]')
    found_sales = False
    for s in sales_spans:
        text = s.text_content().strip()
        match = re.search(r'(\d+)\+?\s*bought', text, re.IGNORECASE)
        if match:
            result['monthly_sales'] = match.group(1)
            found_sales = True
            break

    # 再在任意span里搜索（备用）
    if not found_sales:
        all_spans = item_div.xpath('.//span//text()')
        for text in all_spans:
            text = str(text).strip()
            match = re.search(r'(\d+)\+?\s*bought', text, re.IGNORECASE)
            if match:
                result['monthly_sales'] = match.group(1)
                break

    # Review Count
    review_els = item_div.xpath('.//span[contains(@class,"s-underline-text")]//text()')
    for text in review_els:
        text = str(text).strip()
        match = re.search(r'\(([\d,]+)\)', text)
        if match:
            result['review_count'] = match.group(1).replace(',', '')
            break

    # 备用review选择器
    if not result['review_count']:
        alt_reviews = item_div.xpath('.//a[contains(@href,"customerReviews")]//span//text()')
        for text in alt_reviews:
            text = str(text).strip()
            match = re.search(r'([\d,]+)', text)
            if match:
                result['review_count'] = match.group(1).replace(',', '')
                break

    return result


# ============ 核心请求逻辑 ============
async def fetch_page(session: aiohttp.ClientSession, session_mgr: AmazonSearchSession, page_num: int, global_rank_offset: int) -> tuple[list[dict], int]:
    """获取单页数据，返回(商品列表, 下一个rank起始值)"""
    if page_num > 1:
        await asyncio.sleep(random.uniform(0.8, 2.0))

    search_url = session_mgr.build_url(page_num)
    referer = session_mgr.get_referer(page_num)

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Accept-Language": "en-US;q=0.8,en;q=0.7",
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

    print(f"\n[请求] 第 {page_num} 页")
    print(f"[URL] {search_url[:120]}...")

    async with session.get(search_url, headers=headers, ssl=ssl_context) as response:
        html_content = await response.text()
        print(f"[响应] 状态码: {response.status}, 内容长度: {len(html_content)}")

        if response.status != 200:
            print(f"[警告] 非200状态码, 跳过本页")
            return [], global_rank_offset

        lower_html = html_content.lower()

        # 检查拦截
        if "dogs of amazon" in lower_html:
            print("[警告] 检测到拦截页面(dogs of amazon)")
            return [], global_rank_offset

        if any(x in lower_html for x in [
            "automated access",
            "api-services-support",
            "sorry, we just need to make sure you're not a robot",
            "enter the characters you see below"
        ]):
            print("[警告] 检测到反机器人验证页面")
            return [], global_rank_offset

        tree = html.fromstring(html_content)
        item_divs = tree.xpath('//div[@role="listitem" and @data-asin]')
        print(f"[解析] 找到 {len(item_divs)} 个商品节点")

        products = []
        current_rank = global_rank_offset

        for item_div in item_divs:
            current_rank += 1
            product = parse_product_from_item(item_div, current_rank)
            # 只保留有 image_url 的
            if product['image_url']:
                products.append(product)

        return products, current_rank


async def search_amazon(keyword: str, max_pages: int = 3) -> list[dict]:
    """搜索 Amazon 商品，支持多页"""
    home_url = "https://www.amazon.com/"
    base_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "DNT": "1",
        "Pragma": "no-cache",
        "sec-ch-ua": '"Google Chrome";v="135"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-User": "?1",
        "Sec-Fetch-Dest": "document",
        "Upgrade-Insecure-Requests": "1",
    }

    session_mgr = AmazonSearchSession(keyword)
    all_products = []
    rank_counter = 0

    async with aiohttp.ClientSession() as session:
        # 预热：访问首页建立 Cookie
        print(f"\n[预热] 访问首页...")
        async with session.get(home_url, headers={**base_headers, "Host": "www.amazon.com"}, ssl=ssl_context) as home_resp:
            print(f"[预热] 状态码: {home_resp.status}")

        # 逐页爬取
        for page in range(1, max_pages + 1):
            products, rank_counter = await fetch_page(session, session_mgr, page, rank_counter)

            if not products:
                if page == 1:
                    print("[终止] 第1页无数据，停止爬取")
                    break
                print(f"[终止] 第{page}页无数据，停止爬取")
                break

            all_products.extend(products)
            print(f"[本页] 提取 {len(products)} 个商品 | 累计: {len(all_products)}")

    return all_products


async def main():
    print("=" * 60)
    print(f"  Amazon Scraper Demo")
    print(f"  关键词: {KEYWORD}")
    print(f"  页数: {MAX_PAGES}")
    print(f"  字段: ASIN, Title, Image URL, Monthly Sales, Review Count, Rank")
    print("=" * 60)

    products = await search_amazon(KEYWORD, MAX_PAGES)

    print("\n" + "=" * 60)
    print(f"  爬取完成！共 {len(products)} 个商品")
    print("=" * 60)

    for p in products:
        print(f"\n  Rank #{p['rank']} | ASIN: {p['asin']}")
        print(f"  Title: {p['title'][:70]}{'...' if len(p['title']) > 70 else ''}")
        print(f"  Sales: {p['monthly_sales'] or 'N/A'} | Reviews: {p['review_count'] or 'N/A'}")
        print(f"  Image: {p['image_url'][:80]}...")

    # 保存 JSON
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(products, f, ensure_ascii=False, indent=2)

    print(f"\n{'=' * 60}")
    print(f"  结果已保存: {OUTPUT_FILE}")
    print(f"  总商品数: {len(products)}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    asyncio.run(main())



    def mode(t:int):
        if t==1:
            tips = "生图。。。"
            path_file = ""
        elif t==2:
            tips = "抠图。。。"
            path_file = ""
        else:
            tips = ""

        print(tips)