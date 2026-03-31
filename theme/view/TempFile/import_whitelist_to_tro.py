"""
将侵权白名单.xlsx导入到theme_tro_table表
使用方法: python import_whitelist_to_tro.py
"""
import os
import sys
import django

project_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(project_path)

# 2. 设置环境变量，指向你的 settings.py 文件
# 这里的 'Overlord.settings' 需要根据你项目实际的 settings 路径修改
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Overlord.settings')

# 3. 启动 Django
django.setup()

import pandas as pd
from theme.models import TroTable


def import_whitelist_to_tro(excel_file_path, name_type=9, created_by=None):
    """
    将侵权白名单Excel文件导入到TroTable表

    Args:
        excel_file_path: Excel文件路径
        name_type: 侵权类型码，默认9（自定义白名单）
        created_by: 创建人名称，可选
    """
    try:
        # 读取Excel文件
        df = pd.read_excel(excel_file_path)
        print(f"读取Excel文件成功，共 {len(df)} 行")

        # 获取第一列的列名（假设侵权词在第一列）
        first_column = df.columns[0]
        print(f"侵权词列名: {first_column}")

        # 统计
        success_count = 0
        skip_count = 0
        error_count = 0

        # 遍历每一行
        for idx, row in df.iterrows():
            theme_name = str(row[first_column]).strip()

            # 跳过空值
            if pd.isna(theme_name) or theme_name == '' or theme_name == 'nan':
                skip_count += 1
                continue

            try:
                # 检查是否已存在
                existing = TroTable.objects.filter(theme_name__iexact=theme_name).first()

                if existing:
                    print(f"跳过已存在: {theme_name}")
                    skip_count += 1
                else:
                    # 创建新记录
                    TroTable.objects.create(
                        theme_name=theme_name,
                        name_type=name_type,
                        created_by=created_by
                    )
                    print(f"导入成功: {theme_name}")
                    success_count += 1

            except Exception as e:
                print(f"导入失败 [{theme_name}]: {e}")
                error_count += 1

        print(f"\n导入完成!")
        print(f"成功: {success_count} 条")
        print(f"跳过: {skip_count} 条")
        print(f"失败: {error_count} 条")

    except FileNotFoundError:
        print(f"错误: 文件不存在 - {excel_file_path}")
    except Exception as e:
        print(f"错误: {e}")


if __name__ == '__main__':
    # Excel文件路径
    EXCEL_FILE = '侵权白名单.xlsx'

    # name_type: 9=自定义白名单, 1=系统白名单
    # 根据需要修改
    import_whitelist_to_tro(
        excel_file_path=EXCEL_FILE,
        name_type=1,
        created_by='陈柔'
    )
