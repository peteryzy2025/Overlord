#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
批量历史 MSKU-SKU Listing 配对
从 AmazonOrderItem 取所有不重复的 seller_sku，调用领星批量配对接口
"""

import os
import sys

# 修复 Windows GBK 控制台输出
sys.stdout.reconfigure(encoding='utf-8')

import django

# ========== Django环境初始化 ==========
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = CURRENT_DIR
sys.path.append(PROJECT_ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Overlord.settings")
django.setup()

import asyncio
from django.db import connection
from api.lingxing.Y_OpenApi import get_api_resp


def get_all_seller_skus():
    """使用原生 SQL 获取所有不重复的 seller_sku"""
    print("[步骤1] 从 AmazonOrderItem 提取不重复的 seller_sku...")
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT DISTINCT seller_sku 
            FROM amazon_order_item 
            WHERE seller_sku IS NOT NULL AND seller_sku != ''
            ORDER BY seller_sku
        """)
        skus = [row[0] for row in cursor.fetchall()]
    print(f"  -> 共找到 {len(skus)} 个不重复的 seller_sku")
    return skus


async def process_batch(batch, batch_num, total_batches):
    """处理单批数据"""
    print(f"\n--- 第 {batch_num}/{total_batches} 批 | 数量: {len(batch)} ---")
    
    data_list = []
    for sku in batch:
        data_list.append({
            "sku": sku,
            "msku": sku,
            "is_sync_pic": 1
        })
    
    req_body = {"data": data_list}
    
    try:
        resp = await asyncio.wait_for(
            get_api_resp(
                req_body=req_body,
                api_path="/erp/sc/storage/product/link"
            ),
            timeout=30
        )
        
        code = getattr(resp, 'code', None)
        data = getattr(resp, 'data', {})
        
        # code=0 或 code=1000 都表示接口调用成功
        # 业务结果在 data.success / data.error 中
        if code in (0, 1000):
            success = data.get('success', 0) if isinstance(data, dict) else 0
            error = data.get('error', 0) if isinstance(data, dict) else len(batch)
            print(f"  [完成] success={success}, error={error}")
            return success, error
        else:
            print(f"  [接口失败] code={code}")
            return 0, len(batch)
            
    except asyncio.TimeoutError:
        print(f"  [超时]")
        return 0, len(batch)
    except Exception as e:
        print(f"  [异常] {type(e).__name__}: {str(e)}")
        return 0, len(batch)


async def run_batches(seller_skus):
    """异步执行批量配对"""
    batch_size = 100
    total = len(seller_skus)
    total_batches = (total + batch_size - 1) // batch_size
    
    print(f"\n{'=' * 60}")
    print(f"开始批量配对 | 总数量: {total} | 每批: {batch_size} | 共 {total_batches} 批")
    print(f"{'=' * 60}\n")
    
    success_count = 0
    fail_count = 0
    
    for i in range(total_batches):
        batch = seller_skus[i * batch_size:(i + 1) * batch_size]
        s, f = await process_batch(batch, i + 1, total_batches)
        success_count += s
        fail_count += f
        
        # 每10批暂停一下
        if (i + 1) % 10 == 0:
            print(f"\n  [暂停] 已处理 {i+1} 批，休息2秒...")
            await asyncio.sleep(2)
    
    print(f"\n{'=' * 60}")
    print(f"批量配对完成 | 成功: {success_count} | 失败: {fail_count}")
    print(f"{'=' * 60}\n")


def main():
    """主流程"""
    print("\n" + "=" * 60)
    print("历史 MSKU-SKU Listing 批量配对工具")
    print("=" * 60)
    
    seller_skus = get_all_seller_skus()
    
    if len(seller_skus) == 0:
        print("  -> 没有数据需要处理，退出")
        return
    
    print(f"  -> 前5个示例: {seller_skus[:5]}")
    
    asyncio.run(run_batches(seller_skus))
    
    print("\n处理完毕！")


if __name__ == "__main__":
    main()
