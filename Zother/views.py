from django.http import HttpResponse
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment
from datetime import datetime
from .models import BargainingOrder  # 根据实际app名称调整


def export_bargaining_orders(request):
    """
    导出议价订单表为Excel文件
    访问地址: /zother/bargaining/export/
    """
    # 创建Excel工作簿
    wb = Workbook()
    ws = wb.active
    ws.title = "议价订单表"

    # 设置表头
    headers = ['订单号', '创建时间', '更新时间']
    ws.append(headers)

    # 表头样式
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal="center")

    # 查询并写入数据
    orders = BargainingOrder.objects.all().order_by('-created_at')
    for order in orders:
        ws.append([
            order.order_id,
            order.created_at.strftime('%Y-%m-%d %H:%M:%S') if order.created_at else '',
            order.updated_at.strftime('%Y-%m-%d %H:%M:%S') if order.updated_at else ''
        ])

    # 调整列宽
    ws.column_dimensions['A'].width = 25  # 订单号
    ws.column_dimensions['B'].width = 20  # 创建时间
    ws.column_dimensions['C'].width = 20  # 更新时间

    # 创建HTTP响应
    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = 'attachment; filename="议价订单表_{}.xlsx"'.format(
        datetime.now().strftime('%Y%m%d_%H%M%S')
    )

    # 保存工作簿到响应
    wb.save(response)

    return response