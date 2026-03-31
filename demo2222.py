# 获取有物流单号的 Temu 订单并下载面单

import os
import sys
import django
import asyncio

# 设置环境变量避免编码问题
os.environ['PYTHONIOENCODING'] = 'utf-8'

# ====== Django 初始化 ======
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = CURRENT_DIR
sys.path.append(PROJECT_ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Overlord.settings")
django.setup()

from asgiref.sync import sync_to_async
from temu.models import TemuOrder
from api.lingxing_p.lingxing_temu import get_wms_orders_by_order_numbers


async def get_orders_with_tracking():
    """异步获取有物流单号的订单"""
    @sync_to_async
    def _get_orders():
        return list(TemuOrder.objects.filter(
            tracking_number__isnull=False
        ).exclude(
            tracking_number=''
        ).order_by('-global_purchase_time'))
    
    return await _get_orders()


async def download_labels_for_orders():
    """获取有物流单号的订单并下载面单"""
    # 获取订单列表
    orders = await get_orders_with_tracking()
    total = len(orders)
    
    print(f"共有 {total} 个订单有物流单号，开始下载面单...")
    print("=" * 60)
    
    success_count = 0
    skip_count = 0
    fail_count = 0
    
    for index, order in enumerate(orders, 1):
        print(f"\n[{index}/{total}] 处理订单: {order.global_order_no}")
        print(f"  平台单号: {order.reference_no or '-'}")
        print(f"  物流单号: {order.tracking_number}")
        
        try:
            # 调用领星 API 下载面单
            await get_wms_orders_by_order_numbers(order.global_order_no)
            success_count += 1
        except UnicodeEncodeError:
            # 编码问题但可能下载已成功，继续下一个
            print(f"  [注意] 输出编码问题（可能已下载成功）")
            success_count += 1
        except Exception as e:
            print(f"  [失败] 下载失败: {str(e)[:100]}")
            fail_count += 1
            # 继续处理下一个订单，不中断
            continue
    
    print("\n" + "=" * 60)
    print(f"下载完成统计:")
    print(f"  总订单数: {total}")
    print(f"  成功/跳过: {success_count}")
    print(f"  失败: {fail_count}")


if __name__ == '__main__':
    # 尝试设置控制台编码
    try:
        import codecs
        # Windows 下设置 stdout 编码
        if sys.platform == 'win32':
            sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'replace')
            sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'replace')
    except Exception:
        pass
    
    asyncio.run(download_labels_for_orders())
