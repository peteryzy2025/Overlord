"""
临时脚本：回填所有异常数据行
覆盖三种情况：
  1. title_translation='识别失败' （4条）
  2. subject='' （LLM返回空串，导致subject和subject_translation都坏）
  3. subject_translation='识别失败'
这些行互有重叠，统一用 OR 查询去重后一次性处理。

运行：
    python theme/fix_remaining_failures.py
    python theme/fix_remaining_failures.py --dry-run
"""

import argparse
import os
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Tuple

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Overlord.settings")

import django

django.setup()

from django.db.models import Q
from openai import OpenAI
from theme.models import AmazonThemeNovelty

OPENAI_API_KEY = "sk-c3f9ddb0b5454da2b9db130228049d84"
OPENAI_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
OPENAI_MODEL = "qwen-plus"
MAX_WORKERS = 10

client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)
_api_semaphore = threading.Semaphore(MAX_WORKERS)

SUBJECT_FILTER_WORDS = [
    "T-Shirt",
    "Long Sleeve T-Shirt",
    "V-Neck T-Shirt",
    "Pullover Hoodie",
    "Tank Top",
    "Premium T-Shirt",
    "Sweatshirt",
    "Funny T-Shirt",
    "Funny V-Neck T-Shirt",
    "Sweaters T-Shirt",
    "funny T-Shirt",
    "funny V-Neck T-Shirt",
    "Funny Tank Top",
    "Funny Long Sleeve T-Shirt",
    "funny Premium T-Shirt",
    "Tee Long Sleeve T-Shirt",
    "Funny Premium T-Shirt",
    "Shirt",
    "Tee T-Shirt",
    "Shirt Pullover Hoodie",
    "Shirt Long Sleeve T-Shirt",
    "Shirt T-Shirt",
    "funny Tank Top",
    "Tshirt Funny Sweatshirt",
    "Tshirt Funny Long Sleeve T-Shirt",
    "T-Shirt T-Shirt",
    "T-Shirt Long Sleeve T-Shirt",
    "T-Shirt Sweatshirt",
    "T-Shirt Tank Top",
    "T-Shirt Pullover Hoodie",
    "t-shirt T-Shirt",
    "funny Long Sleeve T-Shirt",
    "Shirt Funny Tank Top",
    "Tee Tank Top",
    "funny T-Shirt T-Shirt",
    "Men Women T-Shirt",
    "Tee Premium T-Shirt",
    "Funny Tee T-Shirt",
    "Womens T-Shirt",
    "Women Men T-Shirt",
    "Men Women Tee T-Shirt",
    "Funny Pullover Hoodie",
    "Funny Long Sleeve T-Shirt",
    "Funny Sweatshirt",
    "Funny Tee",
    "Men Women Long Sleeve T-Shirt",
    "Funny T-Shirt",
    "Men Women Tank Top",
    "Funny Apparel Long Sleeve T-Shirt",
    "Funny design T-Shirt",
    "funny design T-Shirt",
    "Design T-Shirt",
    "Funny Quote T-Shirt",
    "Funny Quote Long Sleeve T-Shirt",
    "Funny Quote Tank Top",
    "Apparel T-Shirt",
    "Design Tank Top",
    "design Tank Top",
    "Quote T-Shirt",
    "Funny Apparel T-Shirt",
    "Women T-Shirt",
    "Design Long Sleeve T-Shirt",
    "design T-Shirt",
    "design Premium T-Shirt",
    "Funny Design T-Shirt",
    "design Long Sleeve T-Shirt",
    "Men Women Funny Long Sleeve T-Shirt",
    "Saying T-Shirt",
    "Funny Saying T-Shirt",
    "Vintage Tank Top",
    "Vintage T-Shirt",
    "Mens Women T-Shirt",
    "Men T-Shirt",
    "Shirt Tank Top",
    "Shirt Premium T-Shirt",
    "V-Neck Long Sleeve T-Shirt",
    "Tshirt T-Shirt",
    "funny Pullover Hoodie",
    "Mens Womens Long Sleeve T-Shirt",
    "funny design Long Sleeve T-Shirt",
    "Apparel Tank Top",
    "Teacher T-Shirt",
    "Quote Long Sleeve T-Shirt",
    "Apparel Long Sleeve T-Shirt",
    "Funny Apparel Tank Top",
    "Retro T-Shirt",
    "Men Women Shirt T-Shirt",
    "Funny Men Women T-Shirt",
    "t-shirt Pullover Hoodie",
    "Funny Shirt T-Shirt",
    "Womens Men Women V-Neck T-Shirt",
    "Men T-Shirt T-Shirt",
    "Vintage Women T-Shirt",
    "Vintage Long Sleeve T-Shirt",
    "Tee Funny T-Shirt",
    "Funny Quotes T-Shirt",
    "Funny design Tank Top",
    "Funny design Long Sleeve T-Shirt",
    "basketball cap",
    "basketball hat",
    "baseball hat",
    "baseball cap",
    "Baseball Cap Adjustable Hat",
]


def _normalize_subject(subject: str) -> str:
    text = str(subject).strip()
    text = re.sub(r'["""`]+', "", text)
    text = re.sub(r"\s*&\s*", " & ", text)
    text = re.sub(r"[^A-Za-z0-9\s'&/+\-#.]", " ", text)
    text = re.sub(r"(?<![A-Za-z0-9])['/+\-#.]+", " ", text)
    text = re.sub(r"['/+\-#.]+(?![A-Za-z0-9])", " ", text)
    text = re.sub(r"(?<![A-Za-z0-9])&+(?![A-Za-z0-9])", " & ", text)
    text = re.sub(r"(?<![A-Za-z0-9])'+", " ", text)
    text = re.sub(r"'+(?![A-Za-z0-9])", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _filter_subject_words(subject: str) -> str:
    if not subject:
        return subject
    filtered = subject
    for word in SUBJECT_FILTER_WORDS:
        filtered = re.sub(re.escape(word), " ", filtered, flags=re.IGNORECASE)
    filtered = _normalize_subject(filtered)
    return filtered


def _is_invalid_subject(subject: str) -> bool:
    if subject is None:
        return True
    v = str(subject).strip().lower()
    return v in {"just graphic", "no text", ""}


def _call_openai(messages, model=OPENAI_MODEL) -> str:
    with _api_semaphore:
        try:
            response = client.chat.completions.create(model=model, messages=messages)
            return response.choices[0].message.content.strip()
        except Exception as e:
            print(f"[ERROR] API调用出错: {e}")
            return ""


def recognize_text_from_title(title: str) -> str:
    prompt = f""""Please extract the core thematic phrase from the product title following these rules:
1. **Structural Analysis**:
- Focus on phrases near product terms but exclude the product word itself
- Ignore product types (Hat/Cap), audiences (Men/Women), colors, materials,specifications and printing-related terms(Print/Printing)
2. **Cultural/Linguistic Features**:
- Preserve complete emotional expressions or humorous phrases
- Maintain cultural references/puns in their original phrase structures
3. **Selection Criteria**:
- When multiple candidates exist:
a) Choose longer phrases
b) Prioritize semantically concrete/complete expressions
c) Prefer complete sentence segments
4. **Final Validation**:
- Remove any remaining product terms before output
Examples:
Title: The Sao Tome and Principe Flag and Freedom Baseball Cap for Men Women Adjustable Breathable Mesh Trucker Hat Unisex
Extract: The Sao Tome and Principe Flag and Freedom

Title: Nufar I Don't Need Therapy I Have My Sister 11oz Fun Coffee Mugs Novelty Ceramics Cup
Extract: I Don't Need Therapy I Have My Sister
Now process this title: {title}
Output only the final English phrase without explanations"""
    return _call_openai([{"role": "user", "content": prompt}])


def translate_subject(subject: str) -> str:
    prompt = f""""# 角色设定
你是一位专业的亚马逊电商运营专家，专门负责产品主题标签的本地化翻译。

# 任务说明
请将以下亚马逊产品主题标签/关键词从英文翻译成中文。这些通常是：
- 产品主题标签（如节日、季节、活动主题）
- 产品风格关键词
- 目标人群标签
- 使用场景标签

# 翻译原则

## 核心要求：
1. **保持简洁**：中文表达要简短有力，控制在3-10个字
2. **准确传达主题**：完整表达原文的主题概念
3. **符合中文标签习惯**：使用中文用户熟悉的表达方式
4. **保留关键信息**：不丢失任何重要的主题元素

## 具体规则：

### A. 节日/季节主题：
- 准确翻译节日名称
- 保留节日氛围
- 符合中文节日表达习惯
- 例如：Valentine's Day → 情人节主题

### B. 情感/风格主题：
- 准确传达情感色彩
- 使用地道中文表达
- 保持风格一致性
- 例如：Romantic Love → 浪漫爱情

### C. 事件/活动主题：
- 准确翻译事件名称
- 保留事件特殊性
- 添加"主题"或"风格"后缀（如适用）
- 例如：Super Bowl → 超级碗主题

### D. 人群/场景主题：
- 准确描述目标人群
- 清晰表达使用场景
- 使用市场常用术语

## 翻译示例参考：

### 输入示例：
1. "Christmas Family Reunion Theme"
2. "Beach Summer Vacation Style"
3. "Gamer RGB Lighting Setup"
4. "Office Professional Business"

### 输出示例：
1. "圣诞家庭团圆主题"
2. "海滩夏日度假风"
3. "游戏玩家RGB光效"
4. "办公商务专业款"

## 特别注意：
1. **专有名词处理**：
   - 球队名、赛事名：保留核心意思，简短翻译
   - 地名：标准中文译名
   - 品牌名：一般不翻译

2. **文化适配**：
   - 西方节日要准确但符合中文习惯
   - 体育赛事用中国用户熟悉的表达
   - 避免直译造成的生硬感

3. **格式要求**：
   - 每行一个翻译结果
   - 不加引号
   - 不加解释说明
   - 保持原始顺序
   - 不要出现英文
   - 不要出现如 "\n" 等特殊字符

## 待翻译的主题标签：
{subject}

## 请开始翻译："""
    return _call_openai([{"role": "user", "content": prompt}]).replace("\n", "")


def translate_title(title: str) -> str:
    prompt = f"""# 角色设定
你是一名经验丰富的亚马逊跨境电商运营专家，专门负责产品标题的本地化翻译。

# 任务说明
请将以下亚马逊产品标题从英文翻译成中文。这些标题通常包含：
1. 产品类型（T-Shirt, Hoodie, Dress等）
2. 目标人群（Women's, Men's, Kids, Baby等）
3. 设计主题/图案
4. 产品特性（材质、款式、尺寸等）
5. 品牌/授权信息

# 翻译原则

## 核心要求：
1. **信息完整性**：保留原文所有关键信息
2. **准确性第一**：技术规格、尺寸、材质必须100%准确
3. **符合中文标题结构**：使用"人群+主题+特性+产品类型"结构
4. **可读性强**：中文表达自然流畅，符合电商标题习惯

# 格式要求：
1. 不加引号
2. 直接输出中文标题

# 待翻译标题：
{title}

# 中文标题："""
    return _call_openai([{"role": "user", "content": prompt}]).replace("\n", "")


def process_single_asin(asin_obj: AmazonThemeNovelty) -> Tuple[str, str, str]:
    title = asin_obj.title or ""
    if not title:
        return "", "", ""

    subject_en = recognize_text_from_title(title)
    if not subject_en:
        return "", "", ""

    subject_en = _filter_subject_words(subject_en)
    if _is_invalid_subject(subject_en):
        return "", "", ""

    title_cn = translate_title(title)
    subject_cn = translate_subject(subject_en)

    return title_cn, subject_en, subject_cn


def main():
    parser = argparse.ArgumentParser(description="回填所有异常数据行")
    parser.add_argument("--dry-run", action="store_true", help="只统计不写入")
    args = parser.parse_args()

    qs = AmazonThemeNovelty.objects.filter(
        Q(title_translation="识别失败")
        | Q(subject="")
        | Q(subject_translation="识别失败")
    )
    total = qs.count()

    title_fail = qs.filter(title_translation="识别失败").count()
    subject_empty = qs.filter(subject="").count()
    sub_trans_fail = qs.filter(subject_translation="识别失败").count()
    print(f"[INFO] 共找到 {total} 条异常 ASIN")
    print(f"  - title_translation='识别失败': {title_fail}")
    print(f"  - subject='': {subject_empty}")
    print(f"  - subject_translation='识别失败': {sub_trans_fail}")

    if total == 0:
        print("[INFO] 无需处理")
        return

    if args.dry_run:
        print(f"\n[DRY-RUN] 只统计，不写入数据库")
        for obj in qs[:20]:
            print(
                f"  ASIN={obj.asin} | title={obj.title[:80]}... "
                f"| subject='{obj.subject}' | sub_trans='{obj.subject_translation}'"
            )
        return

    asin_objs = list(qs)
    success_count = 0
    fail_count = 0

    print(f"[INFO] 开始并发处理 {total} 条，workers={MAX_WORKERS}...")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_asin = {
            executor.submit(process_single_asin, obj): obj for obj in asin_objs
        }
        for idx, future in enumerate(as_completed(future_to_asin), 1):
            obj = future_to_asin[future]
            try:
                title_cn, subject_en, subject_cn = future.result()
                if title_cn and subject_en and subject_cn:
                    obj.title_translation = title_cn
                    obj.subject = subject_en
                    obj.subject_translation = subject_cn
                    obj.theme_novelty_summary = None
                    obj.save(
                        update_fields=[
                            "title_translation",
                            "subject",
                            "subject_translation",
                            "theme_novelty_summary",
                            "updated_at",
                        ]
                    )
                    success_count += 1
                else:
                    fail_count += 1
                    print(f"[WARN] ASIN {obj.asin} 提炼结果为空，跳过")
            except Exception as e:
                fail_count += 1
                print(f"[ERROR] ASIN {obj.asin} 异常: {e}")

            if idx % 20 == 0 or idx == total:
                print(
                    f"[INFO] 进度 {idx}/{total} | "
                    f"成功 {success_count} | 失败 {fail_count}"
                )

    remaining = AmazonThemeNovelty.objects.filter(
        Q(title_translation="识别失败")
        | Q(subject="")
        | Q(subject_translation="识别失败")
    ).count()
    print(f"\n[DONE] 成功 {success_count} | 失败 {fail_count} | 剩余异常 {remaining}")


if __name__ == "__main__":
    main()
