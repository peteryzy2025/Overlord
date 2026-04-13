#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DIVI 亚马逊模板列表爬虫 + 入库
用于获取 dividiy.com 的模板数据并保存到数据库
"""

import os
import sys

# 添加项目路径并设置 Django 环境
sys.path.append(r'D:\Y-Project\Overlord')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Overlord.settings')
import django
django.setup()

import requests
from divi.models import DiviExportTemplate, Product
from general.models import AmazonShop


# 默认 Cookie，可以从浏览器复制
DEFAULT_COOKIE = "rememberMe=true; Admin-Expires-In=43200; password=RG0qULq5LNu08nFFc66rEgKgnrpRi3v+wBUL/mjkmF/X7c6icpRiCfhsYNvutwbZ9u3+3g7G9p1JaJIwbn0qsQ==; username=YMX-28; Admin-Token=ca902b22-bbc9-44ad-bd10-b12558f32ff7"


def _get_headers(cookie=None):
    """获取通用请求头，从 cookie 中提取 Admin-Token 设置 Authorization"""
    if cookie is None:
        cookie = DEFAULT_COOKIE
    
    # 从 cookie 中提取 Admin-Token
    authorization = "Bearer "
    for item in cookie.split('; '):
        if item.startswith('Admin-Token='):
            authorization += item.split('=', 1)[1]
            break
    
    return {
        "Accept": "application/json, text/plain, */*",
        "Accept-Encoding": "gzip, deflate",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
        "Authorization": authorization,
        "Connection": "keep-alive",
        "Content-Type": "application/json;charset=UTF-8",
        "Cookie": cookie,
        "Host": "www.dividiy.com",
        "LanguageType": "CN",
        "Origin": "http://www.dividiy.com",
        "Referer": "http://www.dividiy.com/views/studio.html",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36 Edg/146.0.0.0",
    }


def fetch_template_list(
    page_num=1,
    page_size=50,
    template_name=None,
    start_time=None,
    end_time=None,
    order_by=2,
    brand_id=None,
    product_ids=None,
    cookie=None,
):
    """
    获取亚马逊模板列表中的 amazonTemplateId

    Args:
        page_num: 页码，默认1
        page_size: 每页数量，默认50
        template_name: 模板名称筛选
        start_time: 开始时间
        end_time: 结束时间
        order_by: 排序方式，默认2
        brand_id: 品牌ID
        product_ids: 产品ID列表
        cookie: 自定义 cookie，不传则使用默认

    Returns:
        list: amazonTemplateId 列表
    """
    url = "http://www.dividiy.com/product/amazonTemplate/listTemplate"
    headers = _get_headers(cookie)

    payload = {
        "pageNum": page_num,
        "pageSize": page_size,
        "templateName": template_name,
        "startTime": start_time,
        "endTime": end_time,
        "time": None,
        "orderBy": order_by,
        "brandId": brand_id,
        "productIds": product_ids if product_ids else [],
        "params": {},
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        result = response.json()
        
        if result and result.get("code") == 200:
            data = result.get("data", {})
            template_list = data.get("list", [])
            return [item.get("amazonTemplateId") for item in template_list if item.get("amazonTemplateId")]
        return []
    except requests.exceptions.RequestException as e:
        print(f"请求失败: {e}")
        return []


def fetch_all_template_ids(cookie=None):
    """
    获取所有 amazonTemplateId（自动分页）
    
    Args:
        cookie: 自定义 cookie，不传则使用默认
        
    Returns:
        list: 所有 amazonTemplateId 组成的列表
    """
    all_ids = []
    page_num = 1
    page_size = 50

    while True:
        ids = fetch_template_list(page_num=page_num, page_size=page_size, cookie=cookie)

        if not ids:
            break

        all_ids.extend(ids)

        if len(ids) < page_size:
            break

        page_num += 1

    return all_ids


def get_custom_product_template_info(template_id, cookie=None):
    """
    获取自定义产品模板详情

    Args:
        template_id: 模板ID (amazonTemplateId)
        cookie: 自定义 cookie，不传则使用默认
        
    Returns:
        dict: API返回的完整JSON数据
    """
    url = "http://www.dividiy.com/product/amazonTemplate/getCustomProductTemplateInfo"
    
    if cookie is None:
        cookie = DEFAULT_COOKIE
    
    # 从 cookie 中提取 Admin-Token
    authorization = "Bearer "
    for item in cookie.split('; '):
        if item.startswith('Admin-Token='):
            authorization += item.split('=', 1)[1]
            break
        
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Accept-Encoding": "gzip, deflate",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
        "Authorization": authorization,
        "Connection": "keep-alive",
        "Content-Type": "multipart/form-data; boundary=----WebKitFormBoundaryqLuGcSQoh940IX0C",
        "Cookie": cookie,
        "Host": "www.dividiy.com",
        "LanguageType": "CN",
        "Origin": "http://www.dividiy.com",
        "Referer": "http://www.dividiy.com/views/studio.html",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36 Edg/146.0.0.0",
    }

    # 构造 form-data 请求体
    boundary = "----WebKitFormBoundaryqLuGcSQoh940IX0C"
    body = (
        f"------{boundary}\r\n"
        f'Content-Disposition: form-data; name="templateId"\r\n\r\n'
        f"{template_id}\r\n"
        f"------{boundary}--\r\n"
    )
    headers["Content-Type"] = f"multipart/form-data; boundary=----{boundary}"

    try:
        response = requests.post(url, headers=headers, data=body.encode('utf-8'), timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"请求失败: {e}")
        return None


def extract_username_from_cookie(cookie):
    """从 cookie 中提取 username"""
    if not cookie:
        return None
    for item in cookie.split('; '):
        if item.startswith('username='):
            return item.split('=', 1)[1]
    return None


def sync_templates_to_db(cookie=None, company_id=None):
    """
    同步 DIVI 模板到数据库
    
    Args:
        cookie: 自定义 cookie
        company_id: 所属公司ID，用于数据隔离
        
    Returns:
        dict: 同步统计信息
    """
    stats = {
        'total_fetched': 0,
        'created': 0,
        'updated': 0,
        'failed': 0,
        'skipped_products': 0,
        'skipped_shops': 0,
    }
    
    # 从 cookie 提取 username
    username = extract_username_from_cookie(cookie) if cookie else None
    if not username:
        username = 'unknown'
        print("⚠️ 未从 cookie 中提取到 username，使用默认值")
    
    print("=" * 50)
    print("开始同步 DIVI 模板...")
    print(f"账号: {username}")
    print("=" * 50)
    
    # 1. 获取所有模板ID
    template_ids = fetch_all_template_ids(cookie)
    stats['total_fetched'] = len(template_ids)
    print(f"共获取 {len(template_ids)} 个模板ID")
    
    # 2. 逐个处理模板
    for idx, template_id in enumerate(template_ids, 1):
        print(f"\n[{idx}/{len(template_ids)}] 处理模板 {template_id}...")
        
        # 获取模板详情
        info = get_custom_product_template_info(template_id, cookie)
        if not info or info.get('code') != 200:
            print(f"  ❌ 获取模板详情失败: {template_id}")
            stats['failed'] += 1
            continue
        
        data = info.get('data', {})
        
        try:
            # 3. 更新或创建模板记录（按 template_id + username 区分不同账号）
            template, created = DiviExportTemplate.objects.update_or_create(
                template_id=template_id,
                username=username,
                defaults={
                    'template_name': data.get('templateName'),
                    'product_type': data.get('productType'),
                    'template_type': data.get('templateType', 0),
                }
            )
            
            # 如果有 company_id，设置所属公司
            if company_id:
                from general.models import Company
                try:
                    company = Company.objects.get(id=company_id)
                    template.company = company
                    template.save(update_fields=['company'])
                except Company.DoesNotExist:
                    print(f"  ⚠️ 公司ID {company_id} 不存在，跳过设置公司")
            
            if created:
                stats['created'] += 1
                print(f"  ✅ 新建模板: {template.template_name}")
            else:
                stats['updated'] += 1
                print(f"  🔄 更新模板: {template.template_name}")
            
            # 4. 处理 products 关联 (productIds)
            product_ids = data.get('productIds', [])
            if product_ids:
                existing_products = Product.objects.filter(id__in=product_ids)
                found_count = existing_products.count()
                missing_count = len(product_ids) - found_count
                if missing_count > 0:
                    stats['skipped_products'] += missing_count
                    print(f"  ⚠️ 跳过 {missing_count} 个不存在的产品")
                template.products.set(existing_products)
                print(f"  📦 关联产品: {found_count} 个")
            
            # 5. 处理 shops 关联 (brandIds -> divi_shop_id)
            brand_ids = data.get('brandIds', [])
            if brand_ids:
                existing_shops = AmazonShop.objects.filter(divi_shop_id__in=brand_ids)
                found_count = existing_shops.count()
                missing_count = len(brand_ids) - found_count
                if missing_count > 0:
                    stats['skipped_shops'] += missing_count
                    print(f"  ⚠️ 跳过 {missing_count} 个不存在的店铺")
                template.shops.set(existing_shops)
                print(f"  🏪 关联店铺: {found_count} 个")
                
        except Exception as e:
            print(f"  ❌ 保存模板失败: {e}")
            stats['failed'] += 1
    
    # 6. 打印统计
    print("\n" + "=" * 50)
    print("同步完成!")
    print("=" * 50)
    print(f"总获取: {stats['total_fetched']} 个模板")
    print(f"新建: {stats['created']} 个")
    print(f"更新: {stats['updated']} 个")
    print(f"失败: {stats['failed']} 个")
    print(f"跳过产品: {stats['skipped_products']} 个")
    print(f"跳过店铺: {stats['skipped_shops']} 个")
    
    return stats


def main():
    """
    主函数 - 使用示例
    """
    # 方式1: 仅获取所有模板ID（不入库）
    # print("=" * 50)
    # print("示例1: 获取所有 amazonTemplateId")
    # print("=" * 50)
    # all_ids = fetch_all_template_ids()
    # print(f"共获取 {len(all_ids)} 个ID: {all_ids[:20]}...")
    
    # 方式2: 同步到数据库（指定公司ID）
    print("=" * 50)
    print("示例2: 同步模板到数据库")
    print("=" * 50)
    stats = sync_templates_to_db(company_id=1)  # 修改为公司ID
    
    # 方式3: 使用自定义 cookie
    # custom_cookie = "your_cookie_here"
    # stats = sync_templates_to_db(cookie=custom_cookie, company_id=1)


if __name__ == "__main__":
    main()
