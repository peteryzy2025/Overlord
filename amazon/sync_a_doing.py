from amazon.sync_lingxing_shops import lx_shop_main, lx_shop_main2
from amazon.sync_lingxing_orders import lx_order_main
from amazon.sync_lingxing_zifa_order import lx_zf_main
from amazon.sync_check_divi_status_v4 import divi_process_orders
from amazon.sync_check_divi_k_v1 import amazon_order_divi_guer
from amazon.sync.sync_lingxing_order_info import lx_order_info_main
from amazon.sync.sync_amazon_shipment import amazon_shipment
from amazon.sync_lx_temu_orders import temu_orders
from api.Y.y_tiem import Timer
import asyncio
import time
from datetime import datetime, timedelta
# if __name__ == '__main__':
#     num = 0
#     while True:
#         try:
#             num+=1
#             if num >10:
#                 num = 0
#                 amazon_shipment()  # 发货
#             amazon_order_divi_guer()
#             lx_shop_main()
#             try:
#                 lx_shop_main2()  # Temu店铺数据
#             except Exception as e:
#                 print(f"错误: {e}")
#             lx_order_main() # 亚马逊订单
#             asyncio.run(lx_zf_main()) #自发货订单号同步
#             asyncio.run(lx_order_info_main())# 更新发货时限
#             divi_process_orders("2025-11-19", True) # 导单
#             temu_orders() # temu订单
#         except Exception as e:
#             print(f"错误: {e}")

if __name__ == '__main__':
    num = 0
    while True:
        # 判断当前时间是否在凌晨1点-7点之间
        now = datetime.now()
        current_hour = now.hour

        if 1 <= current_hour < 7:
            # 计算到7点的等待时间
            target_time = now.replace(hour=7, minute=0, second=0, microsecond=0)
            if current_hour >= 7:  # 如果已经过了7点（理论上不会进这个if，但保险起见）
                target_time += timedelta(days=1)
            wait_seconds = (target_time - now).total_seconds()
            print(
                f"当前时间 {now.strftime('%Y-%m-%d %H:%M:%S')}，处于休眠时段(01:00-07:00)，等待 {int(wait_seconds / 60)} 分钟后继续...")
            time.sleep(wait_seconds)
            continue  # 跳到下一次循环，此时应该已经过了7点

        try:
            num += 1
            if num > 10:
                num = 0
                amazon_shipment()  # 发货
            amazon_order_divi_guer()
            lx_shop_main()
            try:
                lx_shop_main2()  # Temu店铺数据
            except Exception as e:
                print(f"错误: {e}")
            lx_order_main()  # 亚马逊订单
            asyncio.run(lx_zf_main())  # 自发货订单号同步
            asyncio.run(lx_order_info_main())  # 更新发货时限
            divi_process_orders("2025-11-19", True)  # 导单
            temu_orders()  # temu订单
        except Exception as e:
            print(f"错误: {e}")

        # 建议加个休眠，避免CPU占满
        time.sleep(60)  # 每分钟检查一次，或者根据需要调整