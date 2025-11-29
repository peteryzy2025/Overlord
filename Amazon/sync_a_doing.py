from Amazon.sync_lingxing_shops import lx_shop_main, lx_shop_main2
from Amazon.sync_lingxing_orders import lx_order_main
from Amazon.sync_lingxing_zifa_order import lx_zf_main
from Amazon.sync_check_divi_status_v2 import divi_process_orders
from Amazon.sync_lx_temu_orders import temu_orders
from Amazon.sync_fh import amazon_fh
from Amazon.sync_lx_temu_orders import temu_orders
from Api.Y.y_tiem import Timer
import asyncio
import time

if __name__ == '__main__':
    t = Timer()
    a = 0
    while True:
        try:
            a =a+1
            t.start()
            lx_shop_main()
            t.stop()
            print(f"时间：{t}")
            lx_order_main()
            lx_shop_main2()
            t.stop()
            print(f"时间：{t}")
            asyncio.run(lx_zf_main())
            t.stop()
            print(f"时间：{t}")
            divi_process_orders("2025-11-19", True)
            t.stop()
            print(f"时间：{t}")
            amazon_fh()
            t.stop()
            print(f"时间：{t}")
            if a == 20:
                a = 0
                temu_orders()
                t.stop()
                print(f"时间：{t}")
            time.sleep(60)
        except Exception as e:
            print(f"错误: {e}")
            time.sleep(5*60)


