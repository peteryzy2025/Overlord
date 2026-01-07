# sync_export.py
import os
import sys
import django
from datetime import datetime, timedelta
from collections import defaultdict

# 设置Django环境
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
sys.path.append(PROJECT_ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Overlord.settings")
django.setup()

# 导入模型
from django.db.models import F, Count, Sum, Q
from django.db.models.functions import TruncDate
from General.models import User, TemuShop
from Temu.models import TemuOrder, TemuOrderItem, LingXingTemuShop

# 导入Excel库
try:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Border, Side, Alignment
except ImportError:
    print("❌ 请先安装openpyxl: pip install openpyxl")
    sys.exit(1)


def create_excel_for_operator(ops_id, start_date, end_date, output_dir):
    """
    导出运营人员的Temu店铺订单统计到Excel（排除退货）
    """
    print(f"\n{'=' * 80}")
    print(f"📊 导出统计Excel | 运营人员ID: {ops_id} | 📅 {start_date} 至 {end_date}")
    print(f"📝 已排除退货订单")
    print(f"{'=' * 80}\n")

    # 1. 获取运营人员信息
    try:
        user = User.objects.get(id=ops_id)
        operator_name = user.first_name or user.username
    except User.DoesNotExist:
        print(f"❌ 未找到运营人员(ID: {ops_id})")
        return None

    # 2. 获取Temu店铺
    temu_shops = TemuShop.objects.filter(ops_id=ops_id)
    if not temu_shops:
        print(f"⚠️ 未找到运营人员 {operator_name} 的Temu店铺")
        return None

    shop_ids = list(temu_shops.values_list('id', flat=True))
    lingxing_shops = LingXingTemuShop.objects.filter(temu_shop_id__in=shop_ids)
    if not lingxing_shops:
        print(f"⚠️ 未找到领星店铺信息")
        return None

    lingxing_shop_ids = list(lingxing_shops.values_list('store_id', flat=True))
    store_id_to_name = {shop.store_id: shop.store_name for shop in lingxing_shops}

    # 3. 创建统计工作簿
    wb = Workbook()
    if wb.active:
        wb.remove(wb.active)

    # 4. 为每个店铺创建统计sheet
    for store_id in lingxing_shop_ids:
        shop_name = store_id_to_name.get(store_id, store_id)
        sheet_name = "".join(c for c in shop_name[:30] if c not in r'\/:*?[]')
        if not sheet_name:
            sheet_name = f"店铺_{store_id[:8]}"

        ws = wb.create_sheet(title=sheet_name)

        # 查询每日统计（排除退货）
        base_filter = Q(
            lingxing_shop_id=store_id,
            global_purchase_time__date__gte=start_date,
            global_purchase_time__date__lte=end_date
        ) & ~Q(platform_info__0__status='CANCELED')

        daily_stats = TemuOrder.objects.filter(base_filter).values(
            date=TruncDate('global_purchase_time')
        ).annotate(
            order_count=Count('global_order_no'),
            sales_quantity=Sum('items__quantity')
        ).order_by('date')

        date_data = {stat['date']: {
            'orders': stat['order_count'],
            'sales': stat['sales_quantity'] or 0
        } for stat in daily_stats}

        # 写入标题和表头
        ws['A1'] = f"店铺: {shop_name}（已排除退货）"
        ws.merge_cells('A1:D1')
        title_font = Font(size=14, bold=True, color="4472C4")
        ws['A1'].font = title_font

        ws['A2'] = '日期'
        ws['B2'] = '订单数'
        ws['C2'] = '销量'
        ws['D2'] = '单均销量'

        # 设置表头样式
        header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
        header_font = Font(color="FFFFFF", bold=True)
        for cell in ws[2]:
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center")

        # 写入数据
        current_date, row = start_date, 3
        shop_total_orders, shop_total_sales = 0, 0

        while current_date <= end_date:
            data = date_data.get(current_date, {'orders': 0, 'sales': 0})
            orders, sales = data['orders'], data['sales']
            shop_total_orders += orders
            shop_total_sales += sales

            ws[f'A{row}'] = current_date.strftime('%Y-%m-%d')
            ws[f'B{row}'] = orders
            ws[f'C{row}'] = sales
            ws[f'D{row}'] = round(sales / orders, 1) if orders > 0 else 0

            row += 1
            current_date += timedelta(days=1)

        # 总计行
        ws[f'A{row}'] = '总计'
        ws[f'B{row}'] = f"=SUM(B3:B{row - 1})"
        ws[f'C{row}'] = f"=SUM(C3:C{row - 1})"
        ws[f'D{row}'] = round(shop_total_sales / shop_total_orders, 1) if shop_total_orders > 0 else 0

        total_font = Font(bold=True)
        for col in ['A', 'B', 'C', 'D']:
            ws[f'{col}{row}'].font = total_font

        # 设置列宽和边框
        ws.column_dimensions['A'].width = 12
        ws.column_dimensions['B'].width = 10
        ws.column_dimensions['C'].width = 10
        ws.column_dimensions['D'].width = 12

        border = Border(
            left=Side(style='thin'),
            right=Side(style='thin'),
            top=Side(style='thin'),
            bottom=Side(style='thin')
        )
        for i in range(2, row + 1):
            for j in range(1, 5):
                cell = ws.cell(row=i, column=j)
                cell.border = border
                if i >= 3 and j >= 2:
                    cell.alignment = Alignment(horizontal="right")

        print(f"✅ 统计sheet: {sheet_name} | 订单: {shop_total_orders:,} | 销量: {shop_total_sales:,}")

    # 5. 创建统计汇总sheet
    ws_summary = wb.create_sheet(title="汇总统计", index=0)

    shop_totals = []
    for store_id in lingxing_shop_ids:
        shop_name = store_id_to_name.get(store_id, store_id)
        base_filter = Q(
            lingxing_shop_id=store_id,
            global_purchase_time__date__gte=start_date,
            global_purchase_time__date__lte=end_date
        ) & ~Q(platform_info__0__status='CANCELED')

        total_orders = TemuOrder.objects.filter(base_filter).count()
        total_sales = TemuOrderItem.objects.filter(
            order__lingxing_shop_id=store_id,
            order__global_purchase_time__date__gte=start_date,
            order__global_purchase_time__date__lte=end_date
        ).exclude(order__platform_info__0__status='CANCELED').aggregate(total=Sum('quantity'))['total'] or 0

        shop_totals.append((shop_name, total_orders, total_sales))

    shop_totals.sort(key=lambda x: x[1], reverse=True)

    ws_summary['A1'] = f"运营人员: {operator_name} | 周期: {start_date} 至 {end_date}（已排除退货）"
    ws_summary.merge_cells('A1:E1')
    ws_summary['A1'].font = Font(size=16, bold=True, color="4472C4")

    ws_summary['A2'] = '店铺名称'
    ws_summary['B2'] = '订单数'
    ws_summary['C2'] = '销量'
    ws_summary['D2'] = '单均销量'
    ws_summary['E2'] = '占比'

    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    header_font = Font(color="FFFFFF", bold=True)
    for cell in ws_summary[2]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center")

    grand_total_orders = sum(total for _, total, _ in shop_totals)
    grand_total_sales = sum(sales for _, _, sales in shop_totals)
    row = 3

    for shop_name, orders, sales in shop_totals:
        ws_summary[f'A{row}'] = shop_name
        ws_summary[f'B{row}'] = orders
        ws_summary[f'C{row}'] = sales
        ws_summary[f'D{row}'] = round(sales / orders, 1) if orders > 0 else 0
        percentage = (orders / grand_total_orders * 100) if grand_total_orders > 0 else 0
        ws_summary[f'E{row}'] = f"{percentage:.1f}%"
        row += 1

    ws_summary[f'A{row}'] = '合计'
    ws_summary[f'B{row}'] = f"=SUM(B3:B{row - 1})"
    ws_summary[f'C{row}'] = f"=SUM(C3:C{row - 1})"
    ws_summary[f'D{row}'] = round(grand_total_sales / grand_total_orders, 1) if grand_total_orders > 0 else 0
    ws_summary[f'E{row}'] = '100%'

    total_font = Font(bold=True)
    for col in ['A', 'B', 'C', 'D', 'E']:
        ws_summary[f'{col}{row}'].font = total_font

    ws_summary.column_dimensions['A'].width = 30
    ws_summary.column_dimensions['B'].width = 12
    ws_summary.column_dimensions['C'].width = 12
    ws_summary.column_dimensions['D'].width = 12
    ws_summary.column_dimensions['E'].width = 10

    border = Border(
        left=Side(style='thin'),
        right=Side(style='thin'),
        top=Side(style='thin'),
        bottom=Side(style='thin')
    )
    for i in range(2, row + 1):
        for j in range(1, 6):
            cell = ws_summary.cell(row=i, column=j)
            cell.border = border
            if i >= 3 and j >= 2:
                cell.alignment = Alignment(horizontal="right")

    print(f"\n✅ 统计汇总sheet | 订单: {grand_total_orders:,} | 销量: {grand_total_sales:,}")

    # 6. 保存统计Excel
    output_dir = output_dir.rstrip('\\')
    os.makedirs(output_dir, exist_ok=True)

    month_str = start_date.strftime('%Y年%m月')
    safe_name = "".join(c for c in operator_name if c not in r'\/:*?"<>|')
    if not safe_name:
        safe_name = f"ops_{ops_id}"

    stats_filename = f"{safe_name}_{month_str}统计（排除退货）.xlsx"
    stats_filepath = os.path.join(output_dir, stats_filename)
    wb.save(stats_filepath)
    print(f"\n{'=' * 80}")
    print(f"✅ 统计Excel已保存: {stats_filepath}")
    print(f"{'=' * 80}")

    return stats_filepath, operator_name, lingxing_shop_ids, store_id_to_name


def create_detail_excel_for_operator(ops_id, start_date, end_date, output_dir, operator_name, lingxing_shop_ids,
                                     store_id_to_name):
    """
    导出订单明细到单独的Excel文件（包含所有订单，不剔除退货）
    """
    print(f"\n{'=' * 80}")
    print(f"📋 导出明细Excel | 运营人员ID: {ops_id} | 📅 {start_date} 至 {end_date}")
    print(f"📝 明细包含: 店铺名、订单号、日期、件数、订单状态、MSKU、收货国家")
    print(f"{'=' * 80}\n")

    # 创建明细工作簿
    wb = Workbook()
    ws = wb.active
    ws.title = "订单明细"

    # 写入表头
    headers = ['店铺名称', '订单号', '下单日期', '订单状态', '商品件数', 'MSKU', '收货国家', '物流单号']
    for col, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
        cell.alignment = Alignment(horizontal="center")

    # 查询所有订单明细
    row = 2
    total_records = 0

    for store_id in lingxing_shop_ids:
        shop_name = store_id_to_name.get(store_id, store_id)

        # 查询该店铺的所有订单项（不过滤退货，保留原始状态）
        order_items = TemuOrderItem.objects.filter(
            order__lingxing_shop_id=store_id,
            order__global_purchase_time__date__gte=start_date,
            order__global_purchase_time__date__lte=end_date
        ).select_related('order').values(
            'order__global_order_no',
            'order__global_purchase_time',
            'order__platform_info',
            'order__tracking_number',
            'order__address_info',
            'msku',
            'quantity'
        ).order_by('order__global_purchase_time', 'order__global_order_no')

        # 写入数据
        for item in order_items:
            # 提取订单状态
            platform_info = item['order__platform_info'] or []
            order_status = platform_info[0]['status'] if platform_info and len(platform_info) > 0 else 'UNKNOWN'

            # 提取收货国家
            address_info = item['order__address_info'] or {}
            country = address_info.get('country', '') if isinstance(address_info, dict) else ''

            # 写入行数据
            ws.cell(row=row, column=1, value=shop_name)  # 店铺名称
            ws.cell(row=row, column=2, value=item['order__global_order_no'])  # 订单号
            ws.cell(row=row, column=3, value=item['order__global_purchase_time'].strftime('%Y-%m-%d'))  # 下单日期
            ws.cell(row=row, column=4, value=order_status)  # 订单状态
            ws.cell(row=row, column=5, value=item['quantity'])  # 商品件数
            ws.cell(row=row, column=6, value=item['msku'] or '')  # MSKU
            ws.cell(row=row, column=7, value=country)  # 收货国家
            ws.cell(row=row, column=8, value=item['order__tracking_number'] or '')  # 物流单号

            row += 1
            total_records += 1

        print(f"✅ 已添加店铺: {shop_name} | 记录数: {order_items.count():,}")

    # 设置列宽
    ws.column_dimensions['A'].width = 25
    ws.column_dimensions['B'].width = 25
    ws.column_dimensions['C'].width = 12
    ws.column_dimensions['D'].width = 15
    ws.column_dimensions['E'].width = 10
    ws.column_dimensions['F'].width = 20
    ws.column_dimensions['G'].width = 15
    ws.column_dimensions['H'].width = 25

    # 设置表格边框
    border = Border(
        left=Side(style='thin'),
        right=Side(style='thin'),
        top=Side(style='thin'),
        bottom=Side(style='thin')
    )
    for i in range(1, row + 1):
        for j in range(1, 9):
            cell = ws.cell(row=i, column=j)
            cell.border = border
            if i >= 2 and j >= 5:  # 数字列右对齐
                cell.alignment = Alignment(horizontal="right")

    print(f"\n✅ 明细记录总数: {total_records:,}")

    # 保存明细Excel
    month_str = start_date.strftime('%Y年%m月')
    safe_name = "".join(c for c in operator_name if c not in r'\/:*?"<>|')
    if not safe_name:
        safe_name = f"ops_{ops_id}"

    detail_filename = f"{safe_name}_{month_str}订单明细.xlsx"
    detail_filepath = os.path.join(output_dir, detail_filename)
    wb.save(detail_filepath)

    print(f"\n{'=' * 80}")
    print(f"✅ 明细Excel已保存: {detail_filepath}")
    print(f"{'=' * 80}")

    return detail_filepath


if __name__ == '__main__':
    # 设置参数
    year = 2025
    ops_id = 28
    output_directory = r"D:\自动化数据\Temu\订单核对"

    try:
        start_date = datetime(year, 12, 1).date()
        end_date = datetime(year, 12, 31).date()

        # 1. 先导出统计Excel
        result = create_excel_for_operator(ops_id, start_date, end_date, output_directory)

        if result:
            stats_filepath, operator_name, lingxing_shop_ids, store_id_to_name = result

            # 2. 再导出明细Excel
            detail_filepath = create_detail_excel_for_operator(
                ops_id, start_date, end_date, output_directory,
                operator_name, lingxing_shop_ids, store_id_to_name
            )

            print(f"\n🎉 全部导出成功！")
            print(f"📊 统计文件: {stats_filepath}")
            print(f"📋 明细文件: {detail_filepath}")
        else:
            print("\n❌ 统计导出失败，明细导出已跳过！")

    except Exception as e:
        print(f"\n{'=' * 80}")
        print(f"❌ 执行出错: {str(e)}")
        import traceback

        traceback.print_exc()
        print(f"{'=' * 80}")