import os
import sys
import django
#
#
# 1. 将项目根目录添加到系统路径（防止导入 App 时报错）
# 假设脚本在 theme/view/ 目录下，我们需要定位到 Overlord 根目录
project_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(project_path)

# 2. 设置环境变量，指向你的 settings.py 文件
# 这里的 'Overlord.settings' 需要根据你项目实际的 settings 路径修改
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Overlord.settings')

# 3. 启动 Django
django.setup()

from amazon.models import AmazonShop
# from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS
# print(list(ENGLISH_STOP_WORDS))
# #
# #
# from sklearn.feature_extraction.text import CountVectorizer
# import spacy
# nlp = spacy.load("en_core_web_trf")
# title = ["Season 5 WSQK The Squawk 94.5 FM Retro Logo T-Shirt"]
# vectorizer = CountVectorizer(stop_words='english')
# X = vectorizer.fit_transform(title)
# print(vectorizer.get_feature_names_out())
#
# doc = nlp(title)
# for ent in doc.ents:
#     print(f"实体: {ent.text:30} 标签: {ent.label_}")
# print([chunk.text for chunk in doc.noun_chunks])



