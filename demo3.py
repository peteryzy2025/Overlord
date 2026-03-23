import os
import sys
import time

import django
from datetime import datetime

from api.Y.y_tiem import Timer

# ========== Django环境初始化 ==========
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
sys.path.append(PROJECT_ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Overlord.settings")
django.setup()

from aba.models import SearchTerm
import pandas as pd
import re


def export_search_terms(keyword="hat"):
    """导出精确匹配搜索词到 Excel
    
    Args:
        keyword: 要匹配的搜索词，默认为 "hat"
                 匹配规则：必须是独立的单词，不是其他词的一部分
                 例如：keyword="hat" 会匹配 "hat", "red hat", "red hat 1", "red hat blue"
                 但不会匹配 "xxxhat" 或 "hatxx"
    """
    
    # 从 SearchTerm 表查询：使用正则表达式确保是独立单词
    # PostgreSQL 中 \y 表示单词边界（不同于 Python 的 \b）
    # 匹配 "hat", "red hat", "red hat 1", "red hat blue"
    # 但不匹配 "xxxhat" 或 "hatxx"
    search_terms = SearchTerm.objects.filter(
        term__iregex=rf'\y{re.escape(keyword)}\y'
    ).values_list('term', 'denoising')
    
    # 转换为列表
    data = list(search_terms)
    
    print(f"关键词: '{keyword}'")
    print(f"找到 {len(data)} 条记录")
    
    if data:
        # 创建 DataFrame，处理 denoising 列：True 显示"已去噪"，否则为空
        df = pd.DataFrame(data, columns=['搜索词', 'denoising'])
        df['状态'] = df['denoising'].apply(lambda x: '已去噪' if x else '')
        df = df[['搜索词', '状态']]  # 只保留需要的两列
        
        # 生成文件名
        output_file = f"search_terms_{keyword}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        
        # 保存到 Excel
        df.to_excel(output_file, index=False, engine='openpyxl')
        
        print(f"Excel 已生成: {output_file}")
        print(f"包含 {len(data)} 个搜索词")
    else:
        print("未找到符合条件的数据")


if __name__ == "__main__":
    # 默认搜索 "hat"，传入其他参数可搜索不同关键词
    export_search_terms("hat")
    export_search_terms("shirt")
