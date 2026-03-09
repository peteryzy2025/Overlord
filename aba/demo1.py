import json
import os
from datetime import datetime
import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side


def load_json_file(json_file_path):
    """将 JSON 文件转换为 Python 对象"""
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


def process_data(t_data, shop_name="skc"):
    """处理数据并返回 DataFrame"""
    records = []
    subOrderList = t_data.get("result", {}).get("subOrderList", [])

    for sub in subOrderList:
        skc = sub.get("productSkcId")
        mark = sub.get("mark")  # 评分
        onSalesDurationOffline = sub.get("onSalesDurationOffline")  # 上架天数

        for sku_item in sub.get("skuQuantityDetailList", []):
            inventoryNumInfo = sku_item.get("inventoryNumInfo", {})

            record = {
                shop_name: skc,
                "SKU": sku_item.get("productSkuId"),
                "销售数据 - 今日": sku_item.get("todaySaleVolume"),
                "销售数据 - 近7天": sku_item.get("lastSevenDaysSaleVolume"),
                "销售数据 - 近30天": sku_item.get("lastThirtyDaysSaleVolume"),
                "库存数据 - 仓内可用库存": inventoryNumInfo.get("warehouseInventoryNum"),
                "库存数据 - 仓内暂不可用库存": inventoryNumInfo.get("unavailableWarehouseInventoryNum"),
                "库存数据 - 已发货库存": inventoryNumInfo.get("waitReceiveNum"),
                "库存数据 - 已下单待发货库存": inventoryNumInfo.get("waitDeliveryInventoryNum"),
                "建议备货量": sku_item.get("adviceQuantity"),
                "评分": mark,
                "加入站点时长": onSalesDurationOffline
            }
            records.append(record)

    return pd.DataFrame(records)


def process_shop_data(json_data, shop_name, excel_path):
    """
    核心函数：处理单个店铺数据并写入 Excel
    
    参数:
        json_data: JSON 数据（字典或文件路径）
        shop_name: 店铺名称，用作 sheet 名和首列列名
        excel_path: Excel 文件路径（由外部生成）
    
    返回:
        bool: 是否成功
    """
    # 如果传入的是文件路径，加载 JSON
    if isinstance(json_data, str):
        data = load_json_file(json_data)
    else:
        data = json_data
    
    if not data:
        print(f"❌ [{shop_name}] 没有数据可处理")
        return False
    
    # 处理数据
    df = process_data(data, shop_name)
    
    if df.empty:
        print(f"❌ [{shop_name}] 没有 SKU 数据")
        return False
    
    # 确保目录存在
    os.makedirs(os.path.dirname(excel_path), exist_ok=True)
    
    # 写入 Excel，使用店铺名作为 sheet 名
    mode = 'a' if os.path.exists(excel_path) else 'w'
    with pd.ExcelWriter(excel_path, engine='openpyxl', mode=mode) as writer:
        df.to_excel(writer, sheet_name=shop_name, index=False)
    
    print(f"✅ [{shop_name}] 数据已写入: {excel_path}")
    
    # 美化样式
    style_excel_sheet(excel_path, shop_name)
    
    return True


def style_excel_sheet(excel_path, sheet_name=None):
    """美化指定 sheet 的样式"""
    wb = load_workbook(excel_path)
    ws = wb[sheet_name] if sheet_name else wb.active

    # 定义样式
    header_fill = PatternFill(start_color="4F81BD", end_color="4F81BD", fill_type="solid")  # 深蓝
    header_font = Font(name='微软雅黑', size=11, bold=True, color="FFFFFF")
    cell_font = Font(name='微软雅黑', size=10)
    alignment_center = Alignment(horizontal='center', vertical='center', wrap_text=True)

    # 边框
    thin_border = Border(
        left=Side(style='thin', color='CCCCCC'),
        right=Side(style='thin', color='CCCCCC'),
        top=Side(style='thin', color='CCCCCC'),
        bottom=Side(style='thin', color='CCCCCC')
    )

    # 设置表头样式
    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = alignment_center
        cell.border = thin_border

    # 设置数据行样式
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row):
        for cell in row:
            cell.font = cell_font
            cell.border = thin_border
            cell.alignment = alignment_center
            # 隔行变色
            if cell.row % 2 == 0:
                cell.fill = PatternFill(start_color="F2F2F2", end_color="F2F2F2", fill_type="solid")

    # 调整列宽
    column_widths = {
        'A': 15,  # 店铺名/skc
        'B': 18,  # SKU
        'C': 12,  # 今日
        'D': 12,  # 近7天
        'E': 12,  # 近30天
        'F': 18,  # 仓内可用
        'G': 20,  # 仓内暂不可用
        'H': 18,  # 已发货
        'I': 22,  # 已下单待发货
        'J': 12,  # 建议备货量
        'K': 10,  # 评分
        'L': 15  # 加入站点时长
    }

    for col, width in column_widths.items():
        ws.column_dimensions[col].width = width

    # 冻结首行
    ws.freeze_panes = 'A2'

    wb.save(excel_path)
    print(f"✅ [{sheet_name}] 样式美化完成")


def style_excel(excel_path):
    """美化 Excel 样式（兼容旧版，美化所有 sheet）"""
    wb = load_workbook(excel_path)
    for sheet_name in wb.sheetnames:
        style_excel_sheet(excel_path, sheet_name)


def main():
    # 配置：json 文件路径 和 对应店铺名
    shops = [
        (r'D:\Y-Project\Ynb\test\j1.json', '1店'),
        (r'D:\Y-Project\Ynb\test\temu_j.json', '2店'),
        (r'D:\Y-Project\Ynb\test\temu_j2.json', '3店'),
    ]
    
    # 外部生成时间戳和文件路径（所有店铺写入同一个文件）
    timestamp = datetime.now().strftime("%Y-%m-%d__%H-%M")
    output_dir = r'D:\Project_Y\销售数据'
    excel_path = os.path.join(output_dir, f"{timestamp}.xlsx")
    
    # 处理每个店铺
    success_count = 0
    for json_file, shop_name in shops:
        success = process_shop_data(json_file, shop_name, excel_path)
        if success:
            success_count += 1
    
    print(f"📊 共处理 {success_count}/{len(shops)} 个店铺，文件保存至: {excel_path}")


def demo_multi_shops():
    """示例：处理多个店铺数据，每个店铺一个 sheet"""
    shops = [
        (r'D:\Y-Project\Ynb\test\j1.json', '店铺A'),
        (r'D:\Y-Project\Ynb\test\j2.json', '店铺B'),
        # 添加更多店铺...
    ]
    
    # 外部生成时间戳和文件路径
    timestamp = datetime.now().strftime("%Y-%m-%d__%H-%M")
    output_dir = r'D:\Project_Y\销售数据'
    excel_path = os.path.join(output_dir, f"{timestamp}.xlsx")
    
    total_sku = 0
    for json_file, shop_name in shops:
        success = process_shop_data(json_file, shop_name, excel_path)
        if success:
            # 读取该 sheet 的行数（减去表头）
            wb = load_workbook(excel_path)
            total_sku += wb[shop_name].max_row - 1
    
    print(f"📊 共处理 {len(shops)} 个店铺，{total_sku} 条 SKU 数据")
    print(f"📁 文件保存至: {excel_path}")


if __name__ == "__main__":
    # 单店铺示例
    main()
    
    # 多店铺示例（取消注释使用）
    # demo_multi_shops()