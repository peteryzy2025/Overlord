import os
import sys
import django


# 1. 将项目根目录添加到系统路径（防止导入 App 时报错）
# 假设脚本在 theme/view/ 目录下，我们需要定位到 Overlord 根目录
project_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(project_path)

# 2. 设置环境变量，指向你的 settings.py 文件
# 这里的 'Overlord.settings' 需要根据你项目实际的 settings 路径修改
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Overlord.settings')

# 3. 启动 Django
django.setup()

import json
import pandas as pd
from theme.models import TroTable


NAME_TYPE_MAPPING = {
    1: '系统白名单',
    2: '用户未指定',
    3: '观察名单',
    4: '亚马逊涉嫌侵权',
    5: '律师函',
    6: '权利人投诉',
    7: '违禁词',
    8: '商标侵权',
    9: '自定义白名单',
    10: '知名IP'
}
def main():
    json_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'divi侵权词库全量数据.json')
    output_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'update.xlsx')

    print("正在读取 JSON 文件...")
    try:
        with open(json_file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            # 提取 themeName 和 nameType
            # 使用字典存储，key=themeName, value=nameType
            json_data_map = {}
            for item in data:
                if 'themeName' in item and item['themeName']:
                    t_name = item['themeName'].strip()
                    # 如果有重复，后面的覆盖前面的，或者保留第一个，这里假设直接覆盖
                    json_data_map[t_name] = item.get('nameType')
            
            json_themes = set(json_data_map.keys())
    except FileNotFoundError:
        print(f"错误: 找不到文件 {json_file_path}")
        return
    except json.JSONDecodeError:
        print(f"错误: JSON 文件格式不正确")
        return

    print(f"JSON 文件读取完成，共找到 {len(json_themes)} 个唯一 theme_name")

    print("正在读取数据库 theme_tro_table...")
    # 获取数据库中所有的 theme_name 和 name_type
    # 使用 values 获取字典列表
    db_themes_qs = TroTable.objects.values('theme_name', 'name_type')
    db_data_map = {}
    for item in db_themes_qs:
        if item['theme_name']:
            db_data_map[item['theme_name'].strip()] = item['name_type']
    
    db_themes = set(db_data_map.keys())
    
    print(f"数据库读取完成，共找到 {len(db_themes)} 个唯一 theme_name")

    results = []

    # Type 2: theme_tro_table有，但Json没有
    print("正在计算 Type 2 (DB有, Json无)...")
    type2_themes = db_themes - json_themes
    for name in type2_themes:
        n_type_code = db_data_map.get(name)
        n_type_str = NAME_TYPE_MAPPING.get(n_type_code, str(n_type_code)) # 如果映射不到，保留原值
        
        results.append({
            'theme_name': name, 
            '国家二字码': 'US',
            '类型': n_type_str,
            '商标类目': '025'
        })

    print(f"计算完成。Type 2 数量: {len(type2_themes)}")

    if not results:
        print("没有发现差异。")
        # 即使没有差异，按照要求也可以生成一个空表或者不做操作？
        # 用户要求“写入结果”，生成空表比较合适
    
    print(f"正在写入结果到 {output_file_path}...")
    df = pd.DataFrame(results)
    # 按照 theme_name 排序，方便查看
    if not df.empty:
        df = df.sort_values(by=['theme_name'])
    
    df.to_excel(output_file_path, index=False)
    print("完成！")

if __name__ == '__main__':
    main()

