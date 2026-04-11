#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DIVI 图库分类同步爬虫
用于获取 dividiy.com 的图库目录树并保存到数据库
"""

import os
import sys

# 添加项目路径并设置 Django 环境
sys.path.append(r'D:\Y-Project\Overlord')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Overlord.settings')
import django
django.setup()

import requests
from divi.models import DiviImageClassify


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


def fetch_image_classify_tree(cookie=None, technology_classify_id=100002):
    """
    获取图库分类树
    
    Args:
        cookie: 自定义 cookie
        technology_classify_id: 技术分类ID，默认100002
        
    Returns:
        list: 树形结构数据
    """
    url = "http://www.dividiy.com/product/classifyImage/treeClassifyImage"
    headers = _get_headers(cookie)
    
    payload = {
        "technologyClassifyId": technology_classify_id
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        result = response.json()
        
        if result and result.get("code") == 200:
            return result.get("data", [])
        print(f"API 返回错误: {result.get('msg')}")
        return []
    except requests.exceptions.RequestException as e:
        print(f"请求失败: {e}")
        return []


def save_tree_to_db(nodes, parent=None, level=0, path="", sort_order=0):
    """
    递归保存树节点到数据库
    
    Args:
        nodes: 节点列表
        parent: 父节点实例
        level: 当前层级
        path: 当前路径
        sort_order: 排序
        
    Returns:
        tuple: (created_count, updated_count)
    """
    created_count = 0
    updated_count = 0
    
    for idx, node_data in enumerate(nodes):
        node_id = node_data.get('id')
        node_label = node_data.get('label', '')
        node_technology = node_data.get('classifyTechnologyName', '')
        children = node_data.get('children', [])
        
        # 构建当前节点的路径
        current_path = f"{path}/{node_id}" if path else f"/{node_id}"
        
        # 更新或创建节点
        node, created = DiviImageClassify.objects.update_or_create(
            id=node_id,
            defaults={
                'parent': parent,
                'label': node_label,
                'technology_name': node_technology,
                'level': level,
                'path': current_path,
                'sort_order': sort_order + idx,
            }
        )
        
        if created:
            created_count += 1
        else:
            updated_count += 1
        
        # 递归处理子节点
        if children:
            child_created, child_updated = save_tree_to_db(
                children, 
                parent=node, 
                level=level + 1, 
                path=current_path,
                sort_order=0
            )
            created_count += child_created
            updated_count += child_updated
    
    return created_count, updated_count


def sync_image_classify(cookie=None, technology_classify_id=100002):
    """
    同步图库分类到数据库
    
    Args:
        cookie: 自定义 cookie
        technology_classify_id: 技术分类ID
        
    Returns:
        dict: 同步统计
    """
    stats = {
        'fetched': 0,
        'created': 0,
        'updated': 0,
        'failed': 0,
    }
    
    print("=" * 50)
    print("开始同步 DIVI 图库分类...")
    print(f"技术分类ID: {technology_classify_id}")
    print("=" * 50)
    
    # 1. 获取树形数据
    tree_data = fetch_image_classify_tree(cookie, technology_classify_id)
    
    if not tree_data:
        print("❌ 未获取到数据")
        stats['failed'] = 1
        return stats
    
    # 统计节点数量
    def count_nodes(nodes):
        count = len(nodes)
        for node in nodes:
            count += count_nodes(node.get('children', []))
        return count
    
    total_nodes = count_nodes(tree_data)
    stats['fetched'] = total_nodes
    print(f"✅ 获取到 {total_nodes} 个节点")
    
    # 2. 清空旧数据（全量更新）
    print("🗑️  清空旧数据...")
    DiviImageClassify.objects.all().delete()
    print("✅ 已清空")
    
    # 3. 保存到数据库
    print("💾 保存到数据库...")
    created, updated = save_tree_to_db(tree_data)
    stats['created'] = created
    stats['updated'] = updated
    
    print("\n" + "=" * 50)
    print("同步完成!")
    print("=" * 50)
    print(f"获取节点: {stats['fetched']} 个")
    print(f"新建: {stats['created']} 个")
    print(f"更新: {stats['updated']} 个")
    print(f"失败: {stats['failed']} 个")
    
    return stats


def main():
    """主函数"""
    stats = sync_image_classify()
    return stats


if __name__ == "__main__":
    main()
