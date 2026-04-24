content = open(r'D:\Y-Project\Overlord\theme\templates\amazon_data_crawler.html', 'r', encoding='utf-8').read()

occurrences = []
idx = -1
while True:
    idx = content.find('showNotification', idx+1)
    if idx == -1:
        break
    occurrences.append(idx)

pos = occurrences[2]
target = content[pos:pos+45]
print('TARGET:', repr(target))

replacement = "showNotification(`已保存 ${paths.length} 个路径`, 'success');"
print('REPLACEMENT:', repr(replacement))

prefix = content[:pos]
suffix = content[pos+45:]
new_content = prefix + replacement + suffix
open(r'D:\Y-Project\Overlord\theme\templates\amazon_data_crawler.html', 'w', encoding='utf-8').write(new_content)
print('done')
