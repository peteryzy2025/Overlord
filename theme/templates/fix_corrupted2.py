content = open(r'D:\Y-Project\Overlord\theme\templates\amazon_data_crawler.html', 'r', encoding='utf-8').read()

idx = content.find('showNotification', content.find('showNotification', content.find('showNotification')+1)+1)
target = content[idx:idx+70]
print('TARGET:', repr(target))

replacement = "showNotification(`已保存 ${paths.length} 个路径`, 'success');\n    closeSettingsModal();"
print('REPLEN:', len(replacement))

content = content.replace(target, replacement)
open(r'D:\Y-Project\Overlord\theme\templates\amazon_data_crawler.html', 'w', encoding='utf-8').write(content)
print('done')
