import json
import os


def load_json_file(json_file_path):
    """
    将 JSON 文件转换为 Python 对象（字典或列表）

    Args:
        json_file_path: JSON 文件路径（字符串）

    Returns:
        dict/list: 解析后的 JSON 数据
        None: 加载失败时返回 None
    """
    # 检查文件是否存在
    if not os.path.exists(json_file_path):
        print(f"❌ 文件不存在: {json_file_path}")
        return None

    try:
        with open(json_file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data
    except json.JSONDecodeError as e:
        print(f"❌ JSON 格式错误: {e}")
        return None
    except UnicodeDecodeError:
        # 尝试用 gbk 编码（某些 Windows 生成的文件）
        try:
            with open(json_file_path, 'r', encoding='gbk') as f:
                data = json.load(f)
            return data
        except Exception as e:
            print(f"❌ 编码错误: {e}")
            return None
    except Exception as e:
        print(f"❌ 读取失败: {e}")
        return None


def chu_li(t_data):
    subOrderList = t_data.get("result").get("subOrderList", [])
    for sub in subOrderList:
        skc = sub.get("productSkcId")
        asfScore = sub.get("asfScore") #评分
        productDays = sub.get("productDays") #上架天数
        print(f"skc:{skc}\n 评分：{asfScore}\n 上架天数：{productDays}")
        for sku_item in sub.get("skuQuantityDetailList"):
            sku = sku_item.get("productSkuId")
            todaySaleVolume = sku_item.get("todaySaleVolume") #今日销量
            lastSevenDaysSaleVolume = sku_item.get("lastSevenDaysSaleVolume") #近7天销量
            lastThirtyDaysSaleVolume = sku_item.get("lastThirtyDaysSaleVolume") #近30天销量

            inventoryNumInfo = sku_item.get("inventoryNumInfo", {}) #库存信息
            warehouseInventoryNum = inventoryNumInfo.get("warehouseInventoryNum") #仓内可用库存
            unavailableWarehouseInventoryNum = inventoryNumInfo.get("unavailableWarehouseInventoryNum") #仓内暂不可用库存
            waitDeliveryInventoryNum = inventoryNumInfo.get("waitDeliveryInventoryNum") #已发货库存 ?真的吗
            expectedOccupiedInventoryNum = inventoryNumInfo.get(".expectedOccupiedInventoryNum") #已下单待发货库存
            adviceQuantity = sku_item.get("adviceQuantity") # 建议补货量

            print(f"  SKU: {sku}\n"
                  f"  销量 - 今日: {todaySaleVolume} | 近7天: {lastSevenDaysSaleVolume} | 近30天: {lastThirtyDaysSaleVolume}\n"
                  f"  库存 - 仓内可用: {warehouseInventoryNum} | 暂不可用: {unavailableWarehouseInventoryNum}\n"
                  f"  物流 - 已发货: {waitDeliveryInventoryNum} | 已下单待发货: {expectedOccupiedInventoryNum}\n"
                  f"  建议补货量: {adviceQuantity}\n")

# ========== 使用示例 ==========
if __name__ == "__main__":
    json_file = r'D:\Y-Project\Ynb\test\temu_j2.json'

    # 加载 JSON 文件
    data = load_json_file(json_file)

    if data:
        chu_li(data)
