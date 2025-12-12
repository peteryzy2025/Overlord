# amazon_order_view.py
import json
from django.http import JsonResponse

from asgiref.sync import async_to_sync

from Amazon.models import AmazonOrders
from Api.lingxing_p.lingxing_fh import lingxing_ship_order  # 你已经改好的发货程序入口

# ✅ 新增：日志模型导入
from django.contrib.auth.decorators import login_required
from General.models import UserOperationLog




