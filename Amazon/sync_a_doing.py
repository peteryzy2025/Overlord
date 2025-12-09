from Amazon.sync_lingxing_shops import lx_shop_main, lx_shop_main2
from Amazon.sync_lingxing_orders import lx_order_main
from Amazon.sync_lingxing_zifa_order import lx_zf_main
from Amazon.sync_check_divi_status_v4 import divi_process_orders
from Amazon.sync_check_divi_k_v1 import amazon_order_divi_guer
from Amazon.sync_fh import amazon_fh
from Amazon.sync_lx_temu_orders import temu_orders
from Api.Y.y_tiem import Timer
import asyncio
import time

if __name__ == '__main__':
    while True:
        try:
            t = Timer()
            t.start()
            amazon_order_divi_guer()
            lx_shop_main()
            lx_shop_main2()  # Temu店铺数据
            t.stop()
            print(f"时间：{t}")
            lx_order_main() # 亚马逊订单
            t.stop()
            print(f"时间：{t}")
            asyncio.run(lx_zf_main()) #自发货订单号同步
            t.stop()
            print(f"时间：{t}")
            divi_process_orders("2025-11-19", True) # 导单
            t.stop()
            print(f"时间：{t}")
            amazon_fh() # 发货
            t.stop()
            print(f"时间：{t}")
            temu_orders() # temu订单
            t.stop()
            print(f"时间：{t}")
        except Exception as e:
            print(f"错误: {e}")



