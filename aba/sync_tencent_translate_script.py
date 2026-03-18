import os
import sys
import django
import time
from django.utils import timezone
import logging

# ========== Django环境初始化 ==========
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
sys.path.append(PROJECT_ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Overlord.settings")
django.setup()

from django.db.models import Q
from aba.models import SearchTerm
from tencentcloud.common import credential
from tencentcloud.common.exception.tencent_cloud_sdk_exception import TencentCloudSDKException
from tencentcloud.tmt.v20180321 import models, tmt_client


SECRET_ID = "AKIDj4EF7mFVYO3UkneKp7TfgYEl7IJBsOkz"
SECRET_KEY = "EH9rUxEActxzqYP5bvdDakiUzMbieR5a"


REGION = "ap-guangzhou"


def translate_zh_to_en(text: str) -> str:
    cred = credential.Credential(SECRET_ID, SECRET_KEY)
    client = tmt_client.TmtClient(cred, REGION)

    req = models.TextTranslateRequest()
    req.SourceText = text
    req.Source = "en"
    req.Target = "zh"
    req.ProjectId = 0

    resp = client.TextTranslate(req)
    return resp.TargetText



def translate_search_term():
    queryset = SearchTerm.objects.using("aba_db").filter(Q(translation_cn__isnull=True) | Q(translation_cn="")).exclude(term="").order_by("id").only("id","term")
    for item in queryset.iterator(chunk_size=100):
        try:
            translated_text = translate_zh_to_en(item.term)
            SearchTerm.objects.using("aba_db").filter(id=item.id).update(
                  translation_cn=translated_text
              )
            print(f"完成:{item.id}:{item.term}->{translated_text}")
            # time.sleep(0.25)
        except Exception as e:
            print(f"{item.id}:{item.term}翻译失败,{e}")


if __name__ == "__main__":
    translate_search_term()
