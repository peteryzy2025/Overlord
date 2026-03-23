# !/usr/bin/env python3
import os
import sys
import django

# ================== 关键配置：修改这里 ==================
# 添加项目根目录到 Python 路径
PROJECT_ROOT = r"D:\Y-Project\Overlord"  # 根据你的实际路径修改
sys.path.insert(0, PROJECT_ROOT)

# Django settings 模块路径（通常是 项目名.settings）
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Overlord.settings')  # 修改 Overlord 为你的项目名
django.setup()

from api.divi.divi_order_service import get_divi_api_resp
from divi.models import Product, ProductColor, ProductSize


def fetch_products():
    """从API获取产品数据"""
    resp = get_divi_api_resp(
        endpoint_path="/partnerProduct/listProductColorSize",
        data_dict={},
        timeout=15,
    )
    print(resp.json())
    return resp.json()


def sync_products():
    """同步产品数据到数据库"""
    result = fetch_products()
    
    if result.get('code') != 200:
        print(f"API请求失败: {result.get('msg')}")
        return
    
    data_list = result.get('data', [])
    
    synced_count = 0
    for product_data in data_list:
        product_id = product_data.get('id')
        product_name = product_data.get('name')
        
        # 同步产品
        product, created = Product.objects.update_or_create(
            id=product_id,
            defaults={'name': product_name}
        )
        action = "创建" if created else "更新"
        print(f"[{action}] 产品: {product_name} (ID: {product_id})")
        
        # 同步颜色
        color_infos = product_data.get('productColorInfos', [])
        for color in color_infos:
            color_obj, color_created = ProductColor.objects.update_or_create(
                product=product,
                color_classify_id=color.get('colorClassifyId'),
                defaults={
                    'color_name': color.get('colorName'),
                    'en_name': color.get('enName'),
                }
            )
            color_action = "创建" if color_created else "更新"
            print(f"  [{color_action}] 颜色: {color.get('colorName')}")
        
        # 同步尺寸 (从颜色的 sizeInfos 中提取)
        # 先收集所有颜色下的尺寸，去重
        size_dict = {}  # 用 dict 去重，key 为 productSizeId
        for color in color_infos:
            size_infos = color.get('sizeInfos', [])
            for size in size_infos:
                size_id = size.get('productSizeId')
                size_name = size.get('productSizeName')
                # 只保存有 ID 且有名称的尺寸
                if size_id and size_name and size_id not in size_dict:
                    size_dict[size_id] = size_name
        
        # 写入数据库
        for size_id, size_name in size_dict.items():
            size_obj, size_created = ProductSize.objects.update_or_create(
                product=product,
                product_size_id=size_id,
                defaults={
                    'product_size_name': size_name,
                }
            )
            size_action = "创建" if size_created else "更新"
            print(f"  [{size_action}] 尺寸: {size_name} (ID: {size_id})")
        
        synced_count += 1
    
    print(f"\n同步完成，共处理 {synced_count} 个产品")


def get_empty_size_ids():
    """获取 productSizeName 为空的 productSizeId 列表"""
    result = fetch_products()
    
    if result.get('code') != 200:
        print(f"API请求失败: {result.get('msg')}")
        return []
    
    data_list = result.get('data', [])
    
    # 收集所有 productSizeId 和对应的名称
    size_map = {}  # {productSizeId: productSizeName}
    
    for product_data in data_list:
        color_infos = product_data.get('productColorInfos', [])
        for color in color_infos:
            for size in color.get('sizeInfos', []):
                size_id = size.get('productSizeId')
                size_name = size.get('productSizeName')
                if size_id is not None:
                    size_map[size_id] = size_name
    
    # 筛选出名称为空的 productSizeId
    empty_size_ids = [size_id for size_id, size_name in size_map.items() if size_name is None]
    
    return sorted(empty_size_ids)


if __name__ == "__main__":
    # sync_products()
    # fetch_products()
    empty_ids = get_empty_size_ids()
    print(empty_ids)