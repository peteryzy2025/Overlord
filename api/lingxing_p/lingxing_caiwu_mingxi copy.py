import os
import sys
import django
import asyncio
from decimal import Decimal, ROUND_HALF_UP
from asgiref.sync import sync_to_async
from datetime import datetime, timedelta

# ========== Django环境初始化 ==========
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(CURRENT_DIR))
sys.path.append(PROJECT_ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Overlord.settings")
django.setup()

from api.lingxing.Y_OpenApi import get_api_resp
import pandas as pd
from tqdm import tqdm


async def demo():
    req_body = {
        "sids": [522034],
        "startDate": "2026-01-01",
        "endDate": "2026-02-28",
        "offset": 0,
        "length": 100,
    }
    resp = await get_api_resp(req_body=req_body, api_path="/basicOpen/finance/profitReport/order/transcation/list")
    print(resp.data)
    print(resp.data.get("total"))
if __name__ == '__main__':
    asyncio.run(demo())