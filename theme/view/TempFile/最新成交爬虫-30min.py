from datetime import datetime, timezone
from subprocess import HIGH_PRIORITY_CLASS
import time
import psycopg2
from psycopg2.extras import Json
import requests
import base64
from DrissionPage import ChromiumPage, ChromiumOptions
from openai import OpenAI
from nltk.tokenize import TweetTokenizer
import nltk
import re
from collections import defaultdict
from nltk.stem import PorterStemmer
from nltk.corpus import stopwords
import string
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS

DB_HOST = "192.168.110.54"
DB_PORT = "5432"
DB_NAME = "overlord_db"
DB_USER = "user1"
DB_PASS = "user555Y1"

OPENAI_API_KEY = "sk-d84933834d374be9a7d814d79cbcad6e"
OPENAI_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
OPENAI_MODEL = "qwen-plus"

BEST_SELLER_START_URL = "https://www.amazon.com/s?k=Shirt&i=fashion-novelty&s=exact-aware-popularity-rank&crid=YLBANN75IKXD&qid=1767339117&sprefix=shirt%2Cfashion-novelty%2C462&xpid=BnGJNx0oBq0gz&ref=sr_st_exact-aware-popularity-rank&ds=v1%3AbGTG%2BvBKF3pkdWNuMKjeKqkR0rIwAXLQF%2BFxvBE96BY"

AMAZON_NOISE_WORDS = {
    'tshirt', 't-shirt', 'shirt', 'clothing', 'apparel', 'gift', 'size',
    'small', 'large', 'unisex', 'men', 'women', 'kids', 'adult', 'set',
    'pack', 'pcs', 'color', 'black', 'white', 'soft', 'vintage', 'retro'
}

SUBJECT_FILTER_WORDS = [
    'T-Shirt', 'Long Sleeve T-Shirt', 'V-Neck T-Shirt', 'Pullover Hoodie', 'Tank Top', 'Premium T-Shirt',
    'Sweatshirt', 'Funny T-Shirt', 'Funny V-Neck T-Shirt', 'Sweaters T-Shirt', 'funny T-Shirt',
    'funny V-Neck T-Shirt', 'Funny Tank Top', 'Funny Long Sleeve T-Shirt', 'funny Premium T-Shirt',
    'Tee Long Sleeve T-Shirt', 'Funny Premium T-Shirt', 'Shirt', 'Tee T-Shirt', 'Shirt Pullover Hoodie',
    'Shirt Long Sleeve T-Shirt', 'Shirt T-Shirt', 'funny Tank Top', 'Tshirt Funny Sweatshirt',
    'Tshirt Funny Long Sleeve T-Shirt', 'T-Shirt T-Shirt', 'T-Shirt Long Sleeve T-Shirt', 'T-Shirt Sweatshirt',
    'T-Shirt Tank Top', 'T-Shirt Pullover Hoodie', 't-shirt T-Shirt', 'funny Long Sleeve T-Shirt',
    'Shirt Funny Tank Top', 'Tee Tank Top', 'funny T-Shirt T-Shirt', 'Men Women T-Shirt', 'Tee Premium T-Shirt',
    'Funny Tee T-Shirt', 'Womens T-Shirt', 'Women Men T-Shirt', 'Men Women Tee T-Shirt',
    'Funny Pullover Hoodie', 'Funny Long Sleeve T-Shirt', 'Funny Sweatshirt', 'Funny Tee',
    'Men Women Long Sleeve T-Shirt', 'Funny T-Shirt', 'Men Women Tank Top', 'Funny Apparel Long Sleeve T-Shirt',
    'Funny design T-Shirt', 'funny design T-Shirt', 'Design T-Shirt', 'Funny Quote T-Shirt',
    'Funny Quote Long Sleeve T-Shirt', 'Funny Quote Tank Top', 'Apparel T-Shirt', 'Design Tank Top',
    'design Tank Top', 'Quote T-Shirt', 'Funny Apparel T-Shirt', 'Women T-Shirt', 'Design Long Sleeve T-Shirt',
    'design T-Shirt', 'design Premium T-Shirt', 'Funny Design T-Shirt', 'design Long Sleeve T-Shirt',
    'Men Women Funny Long Sleeve T-Shirt', 'Saying T-Shirt', 'Funny Saying T-Shirt', 'Vintage Tank Top',
    'Vintage T-Shirt', 'Mens Women T-Shirt', 'Men T-Shirt', 'Shirt Tank Top', 'Shirt Premium T-Shirt',
    'V-Neck Long Sleeve T-Shirt', 'Tshirt T-Shirt', 'funny Pullover Hoodie', 'Mens Womens Long Sleeve T-Shirt',
    'funny design Long Sleeve T-Shirt', 'Apparel Tank Top', 'Teacher T-Shirt', 'Quote Long Sleeve T-Shirt',
    'Apparel Long Sleeve T-Shirt', 'Funny Apparel Tank Top', 'Retro T-Shirt', 'Men Women Shirt T-Shirt',
    'Funny Men Women T-Shirt', 't-shirt Pullover Hoodie', 'Funny Shirt T-Shirt', 'Womens Men Women V-Neck T-Shirt',
    'Men T-Shirt T-Shirt', 'Vintage Women T-Shirt', 'Vintage Long Sleeve T-Shirt', 'Tee Funny T-Shirt',
    'Funny Quotes T-Shirt', 'Funny design Tank Top', 'Funny design Long Sleeve T-Shirt', 'basketball cap',
    'basketball hat', 'baseball hat', 'baseball cap', 'Baseball Cap Adjustable Hat'
]

_stemmer = PorterStemmer()
try:
    _stop_words = set(stopwords.words("english"))
except Exception:
    _stop_words = set()


class DatabaseManager:
    def __init__(self):
        self.conn = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASS,   
        )
        self.cursor = self.conn.cursor()
        self.before_STATUS_CODES = {
        616, 630, 638, 640, 641, 642, 643, 644, 645, 646, 647, 648,
        649, 650, 651, 652, 653, 654, 655, 656, 657, 658, 659, 660,
        661, 663, 665, 666, 672, 680, 681, 746, 760, 969, 686
    }
        self.live_pending = {
            410, 413, 616, 620, 630, 631, 638, 640, 641, 642, 643, 644,
            645, 646, 647, 648, 649, 650, 651, 652, 653, 654, 655, 656,
            657, 658, 659, 660, 661, 663, 664, 665, 666, 667, 668, 672,
            680, 681, 682, 686, 688, 689, 690, 692, 693, 694, 718, 719,
            720, 721, 722, 724, 725, 730, 731, 732, 733, 734, 740, 744,
            745, 746, 748, 752, 753, 756, 757, 760, 762, 763, 764, 772,
            773, 774, 777, 779, 794, 801, 802, 803, 804, 806, 807, 808,
            809, 810, 811, 812, 813, 814, 815, 816, 817, 818, 819, 820,
            821, 822, 823, 824, 825, 969, 973
        }
        self.live_registered_query = """SELECT status_code FROM "public"."theme_status_code_mapping" WHERE status_type = %s """
        self.cursor.execute(self.live_registered_query, ('Registered',))
        self.live_registered = set([int(row[0]) for row in self.cursor.fetchall()])   
        self.last_STATUS_CODES = self.live_pending - self.before_STATUS_CODES    
        self.all_live = self.last_STATUS_CODES.union(self.live_registered)


    def close(self):
        if self.cursor:
            self.cursor.close()
        if self.conn:
            self.conn.close()

    def commit(self):
        self.conn.commit()

    def record_exists(self, asin, crawl_date):
        query = """
        SELECT EXISTS(
            SELECT 1
            FROM theme_daily_data
            WHERE product_id = %s
            AND crawl_date = %s
        )
        """
        self.cursor.execute(query, (asin, crawl_date))
        return self.cursor.fetchone()[0]

    def theme_record_exists(self, asin):
        query = "SELECT EXISTS(SELECT 1 FROM theme_record WHERE product_id = %s)"
        self.cursor.execute(query, (asin,))
        return self.cursor.fetchone()[0]

    def product_exists(self, asin):
        query = """
        SELECT EXISTS(
            SELECT 1
            FROM theme_amazon_novelty
            WHERE asin = %s
        )
        """
        self.cursor.execute(query, (asin,))
        return self.cursor.fetchone()[0]

    def get_product_subject(self, asin):
        query = "SELECT subject FROM theme_amazon_novelty WHERE asin = %s"
        self.cursor.execute(query, (asin,))
        row = self.cursor.fetchone()
        if not row:
            return None
        return row[0]

    def update_theme_subject_if_changed(self, asin, subject, subject_translation, crawl_at):
        if subject is None:
            return 0
        query = """
        UPDATE theme_amazon_novelty
        SET subject = %s,
            subject_translation = %s,
            updated_at = %s
        WHERE asin = %s
          AND subject IS DISTINCT FROM %s
        """
        self.cursor.execute(query, (subject, subject_translation, crawl_at, asin, subject))
        return self.cursor.rowcount

    def is_in_trash_bin(self, asin):
        query = "SELECT EXISTS(SELECT 1 FROM theme_trash_bin WHERE asin = %s)"
        self.cursor.execute(query, (asin,))
        return self.cursor.fetchone()[0]

    def insert_theme_trash_bin(self, asin):
        query = "INSERT INTO theme_trash_bin (asin) VALUES (%s) ON CONFLICT (asin) DO NOTHING"
        self.cursor.execute(query, (asin,))

    def insert_theme_amazon_novelty(
        self,
        asin,
        title,
        title_translation,
        subject,
        subject_translation,
        image_url,
        launch_date,
        crawl_at,
    ):
        query = """
        INSERT INTO theme_amazon_novelty (  
            asin, title, title_translation, subject, subject_translation,
            image_url, launch_date, created_at, is_latest_deal, updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 't', %s)
        ON CONFLICT (asin) DO UPDATE SET
            title = EXCLUDED.title,
            title_translation = EXCLUDED.title_translation,
            subject = EXCLUDED.subject,
            subject_translation = EXCLUDED.subject_translation,
            image_url = EXCLUDED.image_url,
            launch_date = EXCLUDED.launch_date,
            is_latest_deal = EXCLUDED.is_latest_deal,
            updated_at = EXCLUDED.updated_at
        RETURNING asin
        """
        self.cursor.execute(
            query,
            (
                asin,
                title,
                title_translation,
                subject,
                subject_translation,
                image_url,
                launch_date,
                crawl_at,
                crawl_at,
            ),
        )
        return self.cursor.fetchone()[0]

    def insert_theme_daily_data(self, asin, crawl_date, rank, rank_category, crawl_at):
        query = """
        INSERT INTO theme_daily_data (crawl_date, rank, rank_category, crawled_at, product_id, appear_count, score)
        VALUES (%s, %s, %s, %s, %s, 1, 0)
        ON CONFLICT (crawl_date, product_id) DO UPDATE SET
            rank = EXCLUDED.rank,
            rank_category = EXCLUDED.rank_category,
            crawled_at = EXCLUDED.crawled_at,
            appear_count = theme_daily_data.appear_count + 1
        RETURNING crawl_date, product_id
        """
        self.cursor.execute(query, (crawl_date, rank, rank_category, crawl_at, asin))
        return self.cursor.fetchone()

    def update_theme_daily_appear_counts(self, crawl_date, asin_to_count):
        if not asin_to_count:
            return 0
        data = [(count, crawl_date, asin) for asin, count in asin_to_count.items()]
        self.cursor.executemany(
            "UPDATE theme_daily_data SET appear_count = %s WHERE crawl_date = %s AND product_id = %s",
            data,
        )
        return len(data)

    def update_theme_daily_counts_and_scores(self, crawl_date, asin_to_count, asin_to_score):
        if not asin_to_count:
            return 0
        data = [
            (asin_to_count[asin], asin_to_score.get(asin, 0), crawl_date, asin)
            for asin in asin_to_count.keys()
        ]
        self.cursor.executemany(
            "UPDATE theme_daily_data SET appear_count = %s, score = %s WHERE crawl_date = %s AND product_id = %s",
            data,
        )
        return len(data)

    def insert_theme_record(
        self,
        product_id,
        infringement_level,
        infringement_words,
        ai_infringement_level,
        ai_infringement_words,
        record_time,
    ):
        if record_time is None:
            record_time = datetime.now(timezone.utc)
        record_date = record_time.date()
        infringement_level = str(infringement_level) if infringement_level is not None else "Unknown"
        ai_infringement_level = str(ai_infringement_level) if ai_infringement_level is not None else "Unknown"
        if infringement_words is None:
            infringement_words = []
        if ai_infringement_words is None:
            ai_infringement_words = []

        if isinstance(infringement_words, str):
            infringement_words = [w.strip() for w in infringement_words.split(",") if w.strip()]
        elif isinstance(infringement_words, (set, tuple)):
            infringement_words = list(infringement_words)
        elif not isinstance(infringement_words, list):
            infringement_words = [infringement_words]

        if isinstance(ai_infringement_words, str):
            ai_infringement_words = [w.strip() for w in ai_infringement_words.split(",") if w.strip()]
        elif isinstance(ai_infringement_words, (set, tuple)):
            ai_infringement_words = list(ai_infringement_words)
        elif not isinstance(ai_infringement_words, list):
            ai_infringement_words = [ai_infringement_words]

        infringement_words = [str(w).strip() for w in infringement_words if w is not None and str(w).strip()]
        ai_infringement_words = [str(w).strip() for w in ai_infringement_words if w is not None and str(w).strip()]
        query = """
        INSERT INTO theme_record (
            infringement_level,
            infringement_words,
            ai_infringement_level,
            ai_infringement_words,
            record_date,
            record_time,
            product_id
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT DO NOTHING
        """
        self.cursor.execute(
            query,
            (
                infringement_level,
                Json(infringement_words),
                ai_infringement_level,
                Json(ai_infringement_words),
                record_date,
                record_time,
                product_id,
            ),
        )
    
    def clean_subject(self, subject):
        #清理主题中的特殊字符和空格，为分词做准备
        if not subject:
            return ""
        # 保护 's (不区分大小写)
        subject = re.sub(r"('s)", "___POSS___", subject, flags=re.IGNORECASE)
        # 移除除了字母、数字、空格以外的字符
        subject = re.sub(r"[^a-zA-Z0-9\s]", " ", subject)
        # 恢复 's
        subject = subject.replace("___POSS___", "'s")
        # 规范化空格
        subject = re.sub(r'\s+', ' ', subject).strip()
        subject = subject.lower()
        return subject



    def nltk_split_subject(self, subject):
        #主题分词器
        nltk.download('punkt')
        tokenizer = TweetTokenizer()
        tokens = tokenizer.tokenize(subject)
        return tokens

    def should_skip_word(self, word):
        if not word:
            return True
        word = word.strip().lower()
        if len(word) <= 1:
            return True
        if all(c in string.punctuation for c in word):
            return True
        if word in ENGLISH_STOP_WORDS:
            return True
        if word in AMAZON_NOISE_WORDS:
            return True
        if word.isdigit():
            return True
        if not any(c.isalnum() for c in word):
            return True
        return False

    def sync_report_status(self, asin, subject):
        if not subject:
            return
        
        query = """
        INSERT INTO theme_reports (product_id, reporter_id, is_active, created_at)
        SELECT %s, tr.reporter_id, true, NOW()
        FROM theme_reports tr
        JOIN theme_amazon_novelty tan ON tr.product_id = tan.asin
        WHERE tan.subject = %s 
          AND tr.is_active = true
          AND tan.asin != %s
        ON CONFLICT (product_id, reporter_id) DO NOTHING
        """
        self.cursor.execute(query, (asin, subject, asin))
        if self.cursor.rowcount > 0:
            print(f"[SYNC][REPORT] Synced {self.cursor.rowcount} report(s) for ASIN {asin}")

    def judge_risk_data_from_db(self,subject):
        """
        从数据库加载风险数据
        :param subject: 待判断的主题(已清理过特殊字符和空格)
        :return: 包含高风险词和中风险词的元组
        """
        print("从数据库加载风险数据...")
        subject_tokens = self.nltk_split_subject(subject)
        judge_high_risk_query = "SELECT name_type FROM theme_tro_table WHERE theme_name = %s"
        high_risk_words_list = []
        mid_risk_words_list = []  # Candidates for USPTO check
        
        # Track risk counts
        low_risk_words_count = 0
        
        uspto_candidates = set()
        whitelist_tokens = set()

        # 1. Check TRO Table
        for token in subject_tokens:
            if self.should_skip_word(token):
                low_risk_words_count += 1
                continue
                
            self.cursor.execute(judge_high_risk_query, (token,))
            result = self.cursor.fetchone()
            
            # Case A: Not in TRO -> Check USPTO
            if not result or result[0] is None:
                uspto_candidates.add(token)
                continue
                
            name_type = str(result[0])
            
            # Case B: Whitelist (1, 9) -> Low Risk (Skip USPTO)
            if name_type in ("1", "9"):
                low_risk_words_count += 1
                whitelist_tokens.add(token)
                
            # Case C: High Risk -> High Risk
            elif name_type in ("4", "5", "6", "7", "10"):
                high_risk_words_list.append(token)
                
            # Case D: Other -> Check USPTO
            else:
                uspto_candidates.add(token)

        # 2. Check USPTO for candidates (excluding whitelist)
        # Ensure whitelist tokens are definitely removed from candidates (just in case)
        final_uspto_candidates = [t for t in uspto_candidates if t not in whitelist_tokens]
        
        if final_uspto_candidates:
            # Optimize: Batch Query
            placeholders = ','.join(['%s'] * len(final_uspto_candidates))
            query = f"SELECT LOWER(TRIM(word_mark)), status_code FROM trademark_info WHERE LOWER(TRIM(word_mark)) IN ({placeholders}) AND mark_drawing_type in ('1','3','4','5','0')"
            
            self.cursor.execute(query, tuple(final_uspto_candidates))
            
            word_status_map = {}
            for word_lower, status_code in self.cursor.fetchall():
                if word_lower not in word_status_map:
                    word_status_map[word_lower] = set()
                if status_code:
                    word_status_map[word_lower].add(int(status_code))
            
            # Determine Risk for candidates
            for token in final_uspto_candidates:
                token_lower = token.lower()
                status_codes = word_status_map.get(token_lower, set())
                
                if status_codes & self.all_live:
                    mid_risk_words_list.append(token)
                else:
                    low_risk_words_count += 1

        # 3. Determine Final Risk Level
        if high_risk_words_list:
            risk_level = "High Risk"
        elif mid_risk_words_list:
            risk_level = "Mid Risk"
        else:
            risk_level = "Low Risk"

        return risk_level, high_risk_words_list, mid_risk_words_list

class ContentProcessor:
    def __init__(self):
        self.client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)

    def _call_openai(self, messages, model=OPENAI_MODEL):
        try:
            response = self.client.chat.completions.create(model=model, messages=messages)
            content = response.choices[0].message.content
            return content.replace("'", "''")
        except Exception as e:
            print(f"API调用出错: {e}")
            return "识别失败"

    def recognize_text_from_image(self, image_url):
        try:
            # 获取图片并转为base64
            response = requests.get(image_url)
            if response.status_code != 200:
                return "图片获取失败"
            
            encoded_string = base64.b64encode(response.content).decode('utf-8')
            
            prompt = """Process the image content strictly by following these prioritized rules and output only the final English result:

                                1. **Solid Color Check**:  
                                - If the item has a solid color background with no text/graphics → Output "no text"

                                2. **Flag Graphic Detection**:  
                                - If any flag-like graphic is present (national flags, symbolic banners) → Output "just graphic"

                                3. **Text Processing**:  
                                a. Remove decorative symbols/invalid characters while preserving semantic coherence  
                                b. Normalize spacing: single space between words, line breaks → space  
                                c. Preserve proper nouns/capitalization (e.g., "New York")  
                                d. If text exceeds 20 words: Extract the most prominent headline/title (prioritize centered/large-font text)  
                                e. Remove product category terms (e.g., "hat", "shirt", "mug") from output  

                                4. **Non-Flag Graphics**:  
                                - If no valid text remains after processing AND non-flag graphics exist → Output "just graphic\""""
            
            messages = [{
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": prompt
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{encoded_string}",
                            "detail": "high"
                        }
                    }
                ]
            }]
            
            return self._call_openai(messages, model="qwen-vl-plus")
        except Exception as e:
            print(f"图片识别出错: {e}")
            return "识别失败"

    def recognize_text_from_title(self, title):
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
        messages = [{"role": "user", "content": prompt}]
        return self._call_openai(messages)

    def ai_infringement_judge(self, subject):
        # ai判断主题是否侵权
        prompt = f""""You are an Amazon US compliance and intellectual property risk detection assistant. Your task is to analyze any input theme, keyword, phrase, slogan, design concept, or product idea intended for sale on Amazon.com (US marketplace), especially for POD products.

CRITICAL ENFORCEMENT RULES:

Analysis MUST focus on Amazon enforcement standards during store sweeps, not general legality. Amazon's "guilty until proven innocent" automated system is the benchmark.
RECENT EVENTS & TRENDS: If the theme involves recent events, social movements, political topics, or viral phrases, you MUST treat it as potentially high-risk.
TRADEMARKS: Analyze Nice Classification (e.g., Class 25). Check for "phantom" or recently registered trademarks.
UNCERTAINTY: If status is unclear, lean toward "Medium" or "High" risk. Do NOT assume safety.
NO FAIR USE: Amazon bots do not recognize fair use defenses.
NO DISCLAIMERS: Do not provide legal advice disclaimers. Focus on enforcement reality.
Perform 4 specific checks:
Trademark Risk: Brand names, slogans, variations, Nice Classes.
Copyright Risk: Movies, characters, quotes, memes, celebrities.
Amazon Platform Policy: Brand misuse, prohibited content, sensitivities.
POD Enforcement Sensitivity: Trigger keywords, official look-alike structures.
OUTPUT SPECIFICATION:
You MUST output ONLY a valid Python dictionary/JSON.
Risk Level (Key): Must be exactly one of: "高", "中", or "低".and do not show any other text including "Risk Level" this phrase.

Risk Word List (Value): Must be a list of the specific English words/phrases that triggered the risk. Keep these in English.
Format: {{"Risk Level": ["Risk Word 1", "Risk Word 2"]}}
Constraint: DO NOT provide any analysis, markdown text outside the dictionary, or explanations.

Now process this subject: {subject}"""
        messages = [{"role": "user", "content": prompt}]
        return self._call_openai(messages)
    


    
    
    


    def translate_subject(self, subject):
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
   - 不要出现如 "\\n" 等特殊字符

## 待翻译的主题标签：
{subject}

## 请开始翻译："""
        messages = [{"role": "user", "content": prompt}]
        result = self._call_openai(messages)
        return result.replace("\n", "")

    def translate_title(self, title):
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
        messages = [{"role": "user", "content": prompt}]
        result = self._call_openai(messages)
        return result.replace("\n", "")




class ThemeAnalyzer:
    def __init__(self, stemmer=_stemmer, stop_words=_stop_words):
        self.stemmer = stemmer
        self.stop_words = stop_words

    def preprocess_phrase(self, phrase, keep_stopwords=False):
        phrase = phrase.lower()
        words = re.findall(r"\b[\w'-]+\b", phrase)

        if keep_stopwords:
            keep_words = words
        else:
            filtered_words = [word for word in words if word not in self.stop_words]
            keep_words = filtered_words if filtered_words else words

        processed_words = []
        for word in keep_words:
            if word.endswith("ly"):
                word = word[:-2]
            processed_words.append(self.stemmer.stem(word))

        return set(processed_words)

    def fuzzy_match_all_themes(self, all_themes):
        theme_sets = {}
        theme_lengths = {}

        for theme in all_themes:
            words = re.findall(r"\b[\w'-]+\b", theme.lower())
            orig_len = len(words)
            theme_lengths[theme] = orig_len
            keep_stopwords = orig_len < 3
            theme_sets[theme] = self.preprocess_phrase(theme, keep_stopwords)

        inverted_index = defaultdict(list)
        for theme, words in theme_sets.items():
            for word in words:
                inverted_index[word].append(theme)

        matches_dict = {}

        for theme, words in theme_sets.items():
            candidate_themes = set()
            for word in words:
                candidate_themes.update(inverted_index[word])

            matched = []
            len_theme = len(words)
            orig_len = theme_lengths[theme]

            for cand in candidate_themes:
                if cand == theme:
                    matched.append(theme)
                    continue

                cand_set = theme_sets[cand]
                len_cand = len(cand_set)
                max_len = max(len_theme, len_cand)

                if orig_len < 3:
                    if words == cand_set:
                        matched.append(cand)
                    continue

                if max_len > 12:
                    if abs(len_theme - len_cand) > 2:
                        continue
                elif max_len > 6:
                    if abs(len_theme - len_cand) > 1:
                        continue

                intersection = len(words & cand_set)

                if max_len > 12:
                    if intersection >= max_len - 2:
                        matched.append(cand)
                elif max_len > 6:
                    if intersection >= max_len - 1:
                        matched.append(cand)
                else:
                    if words == cand_set:
                        matched.append(cand)

            matches_dict[theme] = matched

        return matches_dict

    def fuzzy_match_and_count(self, subjects):
        raw_occurrence = defaultdict(int)
        for s in subjects:
            if s:
                raw_occurrence[s] += 1

        unique_themes = list(set(raw_occurrence.keys()))
        matches_dict = self.fuzzy_match_all_themes(unique_themes)

        theme_total_counts = {}
        for theme, matched_list in matches_dict.items():
            theme_total_counts[theme] = sum(raw_occurrence[m] for m in matched_list)

        return sorted(theme_total_counts.items(), key=lambda x: x[1], reverse=True)

    def group_asins_by_fuzzy_theme(self, asin_subject_pairs):
        theme_to_asins = defaultdict(set)
        for asin, subject in asin_subject_pairs:
            if asin and subject:
                theme_to_asins[subject].add(asin)

        if not theme_to_asins:
            return {}

        unique_themes = list(theme_to_asins.keys())
        matches_dict = self.fuzzy_match_all_themes(unique_themes)

        adjacency = defaultdict(set)
        for theme, matched_list in matches_dict.items():
            for cand in matched_list:
                adjacency[theme].add(cand)
                adjacency[cand].add(theme)

        seen = set()
        theme_to_rep = {}
        rep_to_themes = {}

        for theme in unique_themes:
            if theme in seen:
                continue
            stack = [theme]
            component = set()
            seen.add(theme)
            while stack:
                cur = stack.pop()
                component.add(cur)
                for nxt in adjacency.get(cur, ()):
                    if nxt not in seen:
                        seen.add(nxt)
                        stack.append(nxt)

            rep = min(
                component,
                key=lambda t: (-len(theme_to_asins.get(t, ())), t),
            )
            rep_to_themes[rep] = component
            for t in component:
                theme_to_rep[t] = rep

        result = {}
        for rep, themes in rep_to_themes.items():
            asins = set()
            for t in themes:
                asins.update(theme_to_asins.get(t, ()))
            asin_list = sorted(asins)
            result[rep] = (asin_list, len(asin_list))

        return result

    def _parse_ymd_date(self, value):
        if not value:
            return None
        if isinstance(value, datetime):
            return value.date()
        s = str(value).strip()
        if not s:
            return None
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
            try:
                return datetime.strptime(s, fmt).date()
            except Exception:
                continue
        return None

    def calculate_score(self, count, launch_date, rank):
        try:
            c = int(count)
        except Exception:
            c = 0

        count_score = 5 if c > 10 else 4 if c > 6 else 3 if c > 3 else 2 if c > 1 else 1

        today = datetime.now().date()
        listing_date = self._parse_ymd_date(launch_date)
        if listing_date is None:
            time_score = 1
        else:
            days_diff = (today - listing_date).days
            time_score = 5 if days_diff <= 1 else 4 if days_diff <= 3 else 3 if days_diff <= 7 else 2 if days_diff <= 15 else 1

        rank_score = 5 if rank not in (None, "") else 0
        return count_score + time_score + rank_score


class AmazonScraper:
    def __init__(self, db_manager, content_processor):
        co = ChromiumOptions()
        co.set_local_port(9222)
        # co.set_argument('--disable-blink-features=AutomationControlled')
        self.driver = ChromiumPage(addr_or_opts=co)
        self.db = db_manager
        self.processor = content_processor
        self.title_list = []

    def get_items_index_list(self, list_selector):
        data_index_list = []
        max_retries = 3
        
        for attempt in range(max_retries):
            try:
                item_outer_blocks = self.driver.eles(list_selector)
                if item_outer_blocks:
                    for item_outer_block in item_outer_blocks:
                        data_index = item_outer_block.attr("data-index")
                        if data_index is None:
                            continue
                        data_index = str(data_index).strip()
                        if not data_index:
                            continue
                        data_index_list.append(data_index)
                    
                    # If we found items, break the retry loop
                    if data_index_list:
                        break
            except Exception as e:
                print(f"Error finding items (Attempt {attempt+1}/{max_retries}): {e}")
            
            # If no items found or error occurred
            print(f"No items found. Waiting 10 seconds... (Attempt {attempt+1}/{max_retries})")
            time.sleep(10)
            
            # If this wasn't the last attempt, refresh and try again
            if attempt < max_retries - 1:
                print("Refreshing page...")
                self.driver.refresh()
                time.sleep(10)
            else:
                print("Failed to find items after 3 attempts. Quitting browser.")
                self.driver.quit()
                import sys
                sys.exit(1)
                
        return data_index_list

    def get_exact_item_xpath(self, index):
        return f'xpath://span[@class="rush-component s-latency-cf-section"]//div[@role="listitem" and @data-index="{index}"]'

    def get_title(self, index):
        title_xpath = self.get_exact_item_xpath(index) + "//a//h2"
        title = self.driver.ele(title_xpath)
        title = title.texts()[0]
        return title.replace("'", "''")

    def get_picture(self, index):
        picture_xpath = self.get_exact_item_xpath(index) + "//img"
        picture = self.driver.ele(picture_xpath)
        return picture.attr("src")

    def get_ASIN(self, index):
        ASIN_xpath = (
            self.get_exact_item_xpath(index)
            + '//span[@class="word-title" and text()="ASIN:"]//following-sibling::span[@class="font-weight-b"]'
        )
        ASIN = self.driver.ele(ASIN_xpath)
        return ASIN.texts()[0].strip()

    def get_launch_date(self, index):
        try:
            launch_date_xpath = self.get_exact_item_xpath(index) + '//span[@class="mr-ext-1 mt-ext-3"]'
            launch_date_info = self.driver.ele(launch_date_xpath)
            launch_date_info = launch_date_info.texts()[1]
            launch_date = launch_date_info.split("(")[0].replace(" ", "")
            launched_time = launch_date_info.split("(")[1].split(")")[0]
            return str(launch_date), str(launched_time)
        except:
            return None, None

    def get_item_rank(self, index):
        try:
            rank_xpath = self.get_exact_item_xpath(index) + '//span[@class="font-weight-b"]/span[contains(@class,"rank-box")]'
            rank = self.driver.eles(rank_xpath)[0].texts()[0]
            rank = rank.replace("#", "").replace(",", "")
            return int(rank)
        except:
            return None

    def get_item_rank_category(self, index):
        try:
            rank_category_xpath = self.get_exact_item_xpath(index) + '//p[@class="bsr-list-item"][1]/span[contains(@class,"exts-color-blue")]'
            rank_category = self.driver.eles(rank_category_xpath)[0].texts()[0]
            return rank_category
        except:
            return None

    def get_current_page_number(self):
        try:
            ele = self.driver.ele(
                'xpath://span[contains(@class,"s-pagination-item") and contains(@class,"s-pagination-selected")]',
                timeout=2,
            )
            if not ele:
                return None
            text = None
            try:
                texts = ele.texts()
                text = texts[0] if texts else None
            except Exception:
                text = getattr(ele, "text", None)
            if not text:
                return None
            return int(str(text).strip())
        except Exception:
            return None

    def next_page(self):
        try:
            btn = self.driver.ele('xpath://a[contains(@class,"s-pagination-next")]', timeout=5)
            if not btn:
                print("Error clicking next page: next button not found")
                return False
            btn.click()
            return True
        except Exception as e:
            print(f"Error clicking next page: {e}")
            return False

    def days_to_int(self, days_str):
        try:
            return int(days_str.replace(",", ""))
        except:
            return 0

    def created_time(self):
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _format_db_error(self, e):
        try:
            import psycopg2
            if isinstance(e, psycopg2.Error):
                diag = getattr(e, "diag", None)
                return (
                    "{"
                    f"'pgcode': {getattr(e, 'pgcode', None)!r}, "
                    f"'constraint': {getattr(diag, 'constraint_name', None)!r}, "
                    f"'table': {getattr(diag, 'table_name', None)!r}, "
                    f"'message': {getattr(diag, 'message_primary', None)!r}, "
                    f"'detail': {getattr(diag, 'message_detail', None)!r}"
                    "}"
                )
        except Exception:
            pass
        return repr(e)

    def _parse_ai_infringement_result(self, text):
        if not text:
            return "Unknown", []
        obj = None
        try:
            import json
            obj = json.loads(text)
        except Exception:
            try:
                import ast
                obj = ast.literal_eval(text)
            except Exception:
                return "Unknown", []

        if not isinstance(obj, dict):
            return "Unknown", []

        if "Risk Level" in obj:
            v = obj.get("Risk Level")
            if isinstance(v, str):
                level = v
                words = obj.get("Risk Word List", [])
            elif isinstance(v, list):
                level = obj.get("level") or obj.get("Level") or "Unknown"
                words = v
            else:
                level = obj.get("level") or obj.get("Level") or "Unknown"
                words = obj.get("Risk Word List", [])
        else:
            if len(obj) == 1:
                (level, words) = next(iter(obj.items()))
            else:
                level = obj.get("level") or obj.get("Level") or "Unknown"
                words = obj.get("Risk Word List", [])

        if isinstance(words, str):
            words = [w.strip() for w in words.split(",") if w.strip()]
        elif isinstance(words, (set, tuple)):
            words = list(words)
        elif not isinstance(words, list):
            words = [words]

        final_words = []
        for w in words:
            if w is None:
                continue
            s = str(w).strip()
            if s:
                final_words.append(s)
        return str(level) if level is not None else "Unknown", final_words

    def filter_subject_words(self, subject):
        if not subject:
            return subject
        filtered = subject
        for word in SUBJECT_FILTER_WORDS:
            filtered = re.sub(re.escape(word), " ", filtered, flags=re.IGNORECASE)
        filtered = self.normalize_subject(filtered)
        return filtered

    def normalize_subject(self, subject):
        text = str(subject).strip()
        text = re.sub(r"[\"“”`]+", "", text)
        text = re.sub(r"\s*&\s*", " & ", text)
        text = re.sub(r"[^A-Za-z0-9\s'&/+\-#.]", " ", text)
        text = re.sub(r"(?<![A-Za-z0-9])['/+\-#.]+", " ", text)
        text = re.sub(r"['/+\-#.]+(?![A-Za-z0-9])", " ", text)
        text = re.sub(r"(?<![A-Za-z0-9])&+(?![A-Za-z0-9])", " & ", text)
        text = re.sub(r"(?<![A-Za-z0-9])'+", " ", text)
        text = re.sub(r"'+(?![A-Za-z0-9])", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def update_subject_if_needed(self, asin, title, crawl_at):
        subject = self.processor.recognize_text_from_title(title)
        if not subject:
            return False
        subject = self.filter_subject_words(subject)
        if self.is_invalid_subject(subject):
            return False
        existing_subject = self.db.get_product_subject(asin)
        if existing_subject is not None and str(existing_subject).strip() == str(subject).strip():
            return False
        subject_translation = self.processor.translate_subject(subject)
        updated = self.db.update_theme_subject_if_changed(asin, subject, subject_translation, crawl_at)
        if updated:
            self.db.commit()
            print(f"[{crawl_at}][OK][THEME_SUBJECT_UPDATE] asin={asin}")
        return updated

    def is_invalid_subject(self, subject):
        if subject is None:
            return True
        v = str(subject).strip().lower()
        return v in {"just graphic", "no text"}

    def process_item(self, data_index, product_type):
        crawl_at = self.created_time()
        crawl_date = crawl_at.split(" ")[0]
        ASIN = self.get_ASIN(data_index)

        if self.db.is_in_trash_bin(ASIN):
            print(f"[{crawl_at}][SKIP][TRASH_BIN] asin={ASIN}")
            return

        record_exists = self.db.record_exists(ASIN, crawl_date)
        product_exists = self.db.product_exists(ASIN)
        theme_record_exists = self.db.theme_record_exists(ASIN)

        if product_exists:
            try:
                title_for_update = self.get_title(data_index)
                self.update_subject_if_needed(ASIN, title_for_update, crawl_at)
            except Exception as e:
                print(f"[{crawl_at}][FAIL][THEME_SUBJECT_UPDATE] asin={ASIN} err={self._format_db_error(e)}")
                self.db.conn.rollback()

        if product_exists and (not theme_record_exists):
            subject = self.db.get_product_subject(ASIN)
            if not subject:
                title = self.get_title(data_index)
                subject = self.processor.recognize_text_from_title(title)
            if subject:
                try:
                    subject = self.filter_subject_words(subject)
                    if self.is_invalid_subject(subject):
                        return
                    ai_infringement_result = self.processor.ai_infringement_judge(subject)
                    ai_infringement_level, ai_infringement_words = self._parse_ai_infringement_result(ai_infringement_result)

                    cleaned_subject = self.db.clean_subject(subject)
                    infringement_level, high_risk_words_list, mid_risk_words_list = self.db.judge_risk_data_from_db(cleaned_subject)
                    infringement_words = sorted(set((high_risk_words_list or []) + (mid_risk_words_list or [])))

                    self.db.insert_theme_record(
                        product_id=ASIN,
                        infringement_level=infringement_level,
                        infringement_words=infringement_words,
                        ai_infringement_level=ai_infringement_level,
                        ai_infringement_words=ai_infringement_words,
                        record_time=datetime.now(timezone.utc),
                    )
                    self.db.commit()
                    print(f"[{crawl_at}][OK][THEME_RECORD] inserted=theme_record asin={ASIN}")
                    theme_record_exists = True
                except Exception as e:
                    print(
                        f"[{crawl_at}][FAIL][THEME_RECORD] insert_failed=theme_record asin={ASIN} err={self._format_db_error(e)}"
                    )
                    self.db.conn.rollback()

        if record_exists:
            if product_exists:
                print(f"[{crawl_at}][SKIP][BOTH_EXIST] asin={ASIN} crawl_date={crawl_date}")
            else:
                print(f"[{crawl_at}][SKIP][HISTORY_EXIST] asin={ASIN} crawl_date={crawl_date}")
            return

        if product_exists:
            rank = self.get_item_rank(data_index)
            rank_category = self.get_item_rank_category(data_index)

            print(
                f"[{crawl_at}][INSERT][HISTORY_ONLY] table=theme_daily_data asin={ASIN} crawl_date={crawl_date} rank={rank} rank_category={rank_category}"
            )

            try:
                self.db.insert_theme_daily_data(ASIN, crawl_date, rank, rank_category, crawl_at)
                self.db.commit()
                print(f"[{crawl_at}][OK][HISTORY_ONLY] inserted=theme_daily_data asin={ASIN} crawl_date={crawl_date}")
                if not self.db.record_exists(ASIN, crawl_date):
                    print(
                        f"[{crawl_at}][WARN][NOT_FOUND_AFTER_COMMIT] table=theme_daily_data asin={ASIN} crawl_date={crawl_date}"
                    )
            except Exception as e:
                print(
                    f"[{crawl_at}][FAIL][HISTORY_ONLY] insert_failed=theme_daily_data asin={ASIN} crawl_date={crawl_date} err={e}"
                )
                self.db.conn.rollback()
            return

        image_url = self.get_picture(data_index)
        try:
            launch_date, launched_time = self.get_launch_date(data_index)
        except Exception:
            launch_date, launched_time = None, None
        recognition_result = self.processor.recognize_text_from_image(image_url)
        if str(recognition_result).strip().lower() in {"no text", "just graphic"}:
            print(f"[{crawl_at}][SKIP][IMAGE_RECOGNITION] asin={ASIN} result={recognition_result} launch_date={launch_date}")
            try:
                self.db.insert_theme_trash_bin(ASIN)
                self.db.commit()
            except Exception as e:
                print(f"[{crawl_at}][FAIL][TRASH_BIN] insert_failed=theme_trash_bin asin={ASIN} err={e} launch_date={launch_date}")
                self.db.conn.rollback()
            return

        product_words = [" cap", " hat", "t-shirt", " socks"]
        error_results = ["识别失败", "图片获取失败"]
        
        if recognition_result in error_results or any(word.lower() in recognition_result.lower() for word in product_words):
            title = self.get_title(data_index)
            subject = self.processor.recognize_text_from_title(title)
        else:
            subject = recognition_result
            title = self.get_title(data_index)

        subject = self.filter_subject_words(subject)
        if self.is_invalid_subject(subject):
            print(f"[{crawl_at}][SKIP][SUBJECT_INVALID] asin={ASIN} subject={subject}")
            return
        title_translation = self.processor.translate_title(title)
        subject_translation = self.processor.translate_subject(subject)
        
        # 侵权检测
        ai_infringement_result = self.processor.ai_infringement_judge(subject)
        ai_infringement_level, ai_infringement_words = self._parse_ai_infringement_result(ai_infringement_result)

        cleaned_subject = self.db.clean_subject(subject)
        infringement_level, high_risk_words_list, mid_risk_words_list = self.db.judge_risk_data_from_db(cleaned_subject)
        infringement_words = sorted(set((high_risk_words_list or []) + (mid_risk_words_list or [])))

        rank = self.get_item_rank(data_index)
        rank_category = self.get_item_rank_category(data_index)
        if launch_date is None:
            launch_date = None

        self.title_list.append(title)

        print(
            f"[{crawl_at}][INSERT][PRODUCT+HISTORY] tables=theme_amazon_novelty,theme_daily_data asin={ASIN} crawl_date={crawl_date} launch_date={launch_date} rank={rank} rank_category={rank_category}"
        )
        try:
            self.db.insert_theme_amazon_novelty(
                ASIN,
                title,
                title_translation,
                subject,
                subject_translation,
                image_url,
                launch_date,
                crawl_at,
            )
            self.db.sync_report_status(ASIN, subject)
            if not theme_record_exists:
                self.db.insert_theme_record(
                    product_id=ASIN,
                    infringement_level=infringement_level,
                    infringement_words=infringement_words,
                    ai_infringement_level=ai_infringement_level,
                    ai_infringement_words=ai_infringement_words,
                    record_time=datetime.now(timezone.utc),
                )
            self.db.insert_theme_daily_data(ASIN, crawl_date, rank, rank_category, crawl_at)
            self.db.commit()
            print(
                f"[{crawl_at}][OK][PRODUCT+HISTORY] inserted=theme_amazon_novelty,theme_daily_data asin={ASIN} crawl_date={crawl_date} launch_date={launch_date}"
            )
            if not self.db.record_exists(ASIN, crawl_date):
                print(
                    f"[{crawl_at}][WARN][NOT_FOUND_AFTER_COMMIT] table=theme_daily_data asin={ASIN} crawl_date={crawl_date} launch_date={launch_date}"
                )
        except Exception as e:
            print(
                f"[{crawl_at}][FAIL][PRODUCT+HISTORY] insert_failed=theme_amazon_novelty,theme_daily_data,theme_record asin={ASIN} crawl_date={crawl_date} err={self._format_db_error(e)} launch_date={launch_date}"
            )
            self.db.conn.rollback()
            return

    def _scrape_category_logic(self, url, product_type, days_limit, list_selector):
        self.driver.get(url)
        time.sleep(10)

        for page in range(3):
            page_no = self.get_current_page_number() or (page + 1)
            print(f"现在开始爬第{page_no}页")
            data_index_list = self.get_items_index_list(list_selector)
            for data_index in data_index_list:
                self.process_item(data_index, product_type)

            if not self.next_page():
                return
            time.sleep(10)

        should_stop = False

        while not should_stop:
            current_page = self.get_current_page_number()
            current_page_display = current_page if current_page is not None else "未知"
            print(f"现在开始爬第{current_page_display}页")
            data_index_list = self.get_items_index_list(list_selector)

            for cur_index, data_index in enumerate(data_index_list):
                _, launched_time_str = self.get_launch_date(data_index)

                if launched_time_str is None:
                    continue

                launched_days = self.days_to_int(launched_time_str.split("days")[0])
                print(cur_index, launched_days)

                if launched_days > days_limit:
                    should_stop = True
                    print(
                        f"第{current_page_display}页，第{cur_index + 1}个商品，距离发布时间已经超过{days_limit}天，停止爬取"
                    )
                    break
                else:
                    self.process_item(data_index, product_type)

            if should_stop:
                break

            if not self.next_page():
                break
            time.sleep(10)

        self.db.commit()

    def scrape_best_seller(self):
        self._scrape_category_logic(
            BEST_SELLER_START_URL,
            "new_peculiar",
            7,
            'xpath://div[@data-component-type="s-search-result"]',
        )

#===================主题模糊匹配函数===============================#
    def analyze_today_themes(self):
        print("开始进行今日主题汇总与模糊匹配...")
        today_str = datetime.now().strftime('%Y-%m-%d')

        cur = self.db.conn.cursor()
        try:
            cur.execute(
                """
                SELECT d.product_id, n.subject, n.launch_date, d.rank
                FROM theme_daily_data d
                JOIN theme_amazon_novelty n ON n.asin = d.product_id
                WHERE d.crawl_date = %s
                """,
                (today_str,),
            )
            rows = cur.fetchall()
        finally:
            cur.close()

        asin_subject_pairs = [(row[0], row[1]) for row in rows if row and row[0] and row[1]]
        if not asin_subject_pairs:
            print("今日无可用主题。")
            return {}

        analyzer = ThemeAnalyzer()
        grouped = analyzer.group_asins_by_fuzzy_theme(asin_subject_pairs)

        asin_to_count = {}
        asin_to_meta = {}
        for row in rows:
            if not row or not row[0]:
                continue
            asin_to_meta[row[0]] = (row[2], row[3])

        for _, (asin_list, count) in grouped.items():
            for asin in asin_list:
                asin_to_count[asin] = count

        try:
            asin_to_score = {}
            for asin, count in asin_to_count.items():
                launch_date, rank = asin_to_meta.get(asin, (None, None))
                asin_to_score[asin] = analyzer.calculate_score(count, launch_date, rank)

            updated = self.db.update_theme_daily_counts_and_scores(today_str, asin_to_count, asin_to_score)
            self.db.commit()
            print(f"appear_count已更新，共计 {updated} 条记录。")
        except Exception as e:
            self.db.conn.rollback()
            print(f"appear_count更新失败: {e}")

        print(f"处理完成，共计 {len(grouped)} 个唯一主题。")
        return grouped


def main():
    db_manager = DatabaseManager()
    content_processor = ContentProcessor()
    scraper = AmazonScraper(db_manager, content_processor)

    try:
        # 执行爬取
        scraper.scrape_best_seller()
        
        # 爬取完成后执行分析汇总
        grouped = scraper.analyze_today_themes()
        
        # 打印前5条示例
        top5 = sorted(grouped.items(), key=lambda kv: kv[1][1], reverse=True)
        for theme, (asin_list, count) in top5:
            print(f"theme: {theme}, count: {count}, asins: {asin_list}")
            
    finally:
        scraper.driver.quit()
        db_manager.close()
    # db_manager = DatabaseManager()
    # content_processor = ContentProcessor()
    # scraper = AmazonScraper(db_manager, content_processor)

    # try:
    #     scraper.scrape_best_seller()
    # finally:
    #     db_manager.close()


if __name__ == "__main__":
    main()
    # f = DatabaseManager()
    # subject = "Netflix Stranger Things Steve The Babysitter Portrait T-Shirt FACETIME aabbitt"

    # subject = f.clean_subject(subject)
    # print(subject)
    # subject_tokens = f.nltk_split_subject(subject)
    # print(subject_tokens)
    # print(f.judge_risk_data_from_db(subject))



