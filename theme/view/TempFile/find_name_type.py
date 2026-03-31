import json

result = []
with open('divi侵权词库全量数据.json', 'r', encoding='utf-8') as f:
    for line in f.readlines():      # 也可以用 for line in f: 更省内存
        line = line.strip()
        if not line:                # 跳过空行
            continue
        try:
            obj = json.loads(line)
            if obj.get('nameType') == 1:
                result.append(obj)
        except json.JSONDecodeError:
            continue   # 可选的错误处理

# result 就是所有 nameType=2 的字典
print(f"找到 {len(result)} 条记录")