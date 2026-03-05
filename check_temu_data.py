#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os
import sys
import django

# 设置 Django 环境
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Overlord.settings')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
django.setup()

from temu.models import TemuOrder, TemuOrderItem

print('=== TemuOrder 字段 ===')
order = TemuOrder.objects.first()
if order:
    print(f'global_order_no: {order.global_order_no}')
    print(f'reference_no: {order.reference_no}')
    print(f'order_from_name: {order.order_from_name}')
    print(f'status: {order.status}')
    print(f'delivery_type: {order.delivery_type}')
    print()
    
    # 查看所有字段
    print('=== TemuOrder 所有非空字段 ===')
    for field in TemuOrder._meta.fields:
        value = getattr(order, field.name)
        if value:
            print(f'{field.name}: {value}')
    print()
    
    # 查看关联的订单商品
    print('=== 关联的 TemuOrderItem ===')
    items = TemuOrderItem.objects.filter(order=order)
    print(f'商品数量: {items.count()}')
    for item in items[:3]:
        print(f'  - global_item_no: {item.global_item_no}')
        print(f'    platform_order_no: {item.platform_order_no}')
        print(f'    order_item_no: {item.order_item_no}')
        print(f'    msku: {item.msku}')
        print(f'    quantity: {item.quantity}')
        print()
else:
    print('没有订单数据')
