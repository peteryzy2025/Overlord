from django.apps import AppConfig
# import spacy
import sys


class ThemeConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'theme'

    # # 定义类变量，用于存储加载后的模型
    # nlp_trf = None
    #
    # def ready(self):
    #     # 避免在执行迁移(migrate)或导出数据(dumpdata)时也加载模型
    #     if 'runserver' not in sys.argv:
    #         return
    #
    #     # 确保只加载一次
    #     if ThemeConfig.nlp_trf is None:
    #         print("--- Loading spaCy Transformer model (en_core_web_trf)... ---")
    #         try:
    #             # 加载模型
    #             ThemeConfig.nlp_trf = spacy.load("en_core_web_trf")
    #             print("--- spaCy model loaded successfully! ---")
    #         except Exception as e:
    #             print(f"--- Error loading spaCy model: {e} ---")

    def ready(self):
        import theme.signals