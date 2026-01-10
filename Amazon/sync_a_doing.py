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

if __name__ == '__main__':
    num = 0
    while True:
        try:
            num+=1
            if num >10:
                num = 0
                amazon_shipment()  # 发货
            amazon_order_divi_guer()
            lx_shop_main()
            try:
                lx_shop_main2()  # Temu店铺数据
            except Exception as e:
                print(f"错误: {e}")
            lx_order_main() # 亚马逊订单
            asyncio.run(lx_zf_main()) #自发货订单号同步
            asyncio.run(lx_order_info_main())# 更新发货时限
            divi_process_orders("2025-11-19", True) # 导单
            temu_orders() # temu订单
        except Exception as e:
            print(f"错误: {e}")



