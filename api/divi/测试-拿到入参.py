# get_payload.py (保存在 D:\Y-Project\Overlord\Api\divi\ 目录下)
# !/usr/bin/env python3
import os
import sys
import django
import json

# ================== 关键配置：修改这里 ==================
# 添加项目根目录到 Python 路径
PROJECT_ROOT = r"D:\Y-Project\Overlord"  # 根据你的实际路径修改
sys.path.insert(0, PROJECT_ROOT)

# Django settings 模块路径（通常是 项目名.settings）
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Overlord.settings')  # 修改 Overlord 为你的项目名
django.setup()

from api.divi.divi_order_service import build_order_payload_from_amazon_order_id

if __name__ == '__main__':
    # 测试订单号
    AMAZON_ORDER_ID = "114-0416254-3657869"

    print(f"正在获取订单 {AMAZON_ORDER_ID} 的 payload...\n")

    payload = build_order_payload_from_amazon_order_id(
        amazon_order_id=AMAZON_ORDER_ID,
        print_if=True
    )

    if payload:
        # 可选：保存到文件
        output_file = f"payload_{AMAZON_ORDER_ID.replace('-', '_')}.json"
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print(f"\n✅ Payload 已保存到: {os.path.abspath(output_file)}")
    else:
        print("\n❌ 获取 payload 失败")
        sys.exit(1)