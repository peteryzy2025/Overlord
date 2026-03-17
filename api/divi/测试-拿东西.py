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

from api.divi.divi_order_service import get_divi_api_resp


def demo():

    resp = get_divi_api_resp(
        endpoint_path="/partnerProduct/listProductColorSize",
        data_dict={},
        timeout=15,
    )
    print(resp.json())

if __name__ == "__main__":
    demo()




