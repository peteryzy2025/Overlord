from Amazon.sync_lingxing_shops import lx_shop_main
from Amazon.sync_lingxing_orders import lx_order_main
from Amazon.sync_lingxing_zifa_order import lx_zf_main
from Amazon.sync_check_divi_status_v2 import divi_process_orders
from Api.Y.y_tiem import Timer
import asyncio
import time
if __name__ == '__main__':
    t = Timer()
    while True:
        t.start()
        lx_shop_main()

        t.stop()
        print(f"时间：{t}")
        lx_order_main()
        t.stop()
        print(f"时间：{t}")
        asyncio.run(lx_zf_main())
        t.stop()
        print(f"时间：{t}")
        divi_process_orders("2025-11-19", True)
        t.stop()
        print(f"时间：{t}")
        time.sleep(60)
    