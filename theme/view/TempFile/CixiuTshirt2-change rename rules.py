import os
import re
import time
import zipfile
import shutil
import sqlite3
import glob
import random
import base64
from datetime import datetime, timedelta
from DrissionPage import ChromiumPage, ChromiumOptions
from RecaptchaSolver import RecaptchaSolver
from openai import OpenAI

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "sk-d84933834d374be9a7d814d79cbcad6e")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "qwen-plus")
OPENAI_VL_MODEL = os.getenv("OPENAI_VL_MODEL", "qwen-vl-plus")

AMAZON_NOISE_WORDS = {
    "tshirt", "t-shirt", "shirt", "clothing", "apparel", "gift", "size",
    "small", "large", "unisex", "men", "women", "kids", "adult", "set",
    "pack", "pcs", "color", "black", "white", "soft", "vintage", "retro"
}

SUBJECT_FILTER_WORDS = [
    "T-Shirt", "Long Sleeve T-Shirt", "V-Neck T-Shirt", "Pullover Hoodie", "Tank Top", "Premium T-Shirt",
    "Sweatshirt", "Funny T-Shirt", "Funny V-Neck T-Shirt", "Sweaters T-Shirt", "funny T-Shirt",
    "funny V-Neck T-Shirt", "Funny Tank Top", "Funny Long Sleeve T-Shirt", "funny Premium T-Shirt",
    "Tee Long Sleeve T-Shirt", "Funny Premium T-Shirt", "Shirt", "Tee T-Shirt", "Shirt Pullover Hoodie",
    "Shirt Long Sleeve T-Shirt", "Shirt T-Shirt", "funny Tank Top", "Tshirt Funny Sweatshirt",
    "Tshirt Funny Long Sleeve T-Shirt", "T-Shirt T-Shirt", "T-Shirt Long Sleeve T-Shirt", "T-Shirt Sweatshirt",
    "T-Shirt Tank Top", "T-Shirt Pullover Hoodie", "t-shirt T-Shirt", "funny Long Sleeve T-Shirt",
    "Shirt Funny Tank Top", "Tee Tank Top", "funny T-Shirt T-Shirt", "Men Women T-Shirt", "Tee Premium T-Shirt",
    "Funny Tee T-Shirt", "Womens T-Shirt", "Women Men T-Shirt", "Men Women Tee T-Shirt",
    "Funny Pullover Hoodie", "Funny Long Sleeve T-Shirt", "Funny Sweatshirt", "Funny Tee",
    "Men Women Long Sleeve T-Shirt", "Funny T-Shirt", "Men Women Tank Top", "Funny Apparel Long Sleeve T-Shirt",
    "Funny design T-Shirt", "funny design T-Shirt", "Design T-Shirt", "Funny Quote T-Shirt",
    "Funny Quote Long Sleeve T-Shirt", "Funny Quote Tank Top", "Apparel T-Shirt", "Design Tank Top",
    "design Tank Top", "Quote T-Shirt", "Funny Apparel T-Shirt", "Women T-Shirt", "Design Long Sleeve T-Shirt",
    "design T-Shirt", "design Premium T-Shirt", "Funny Design T-Shirt", "design Long Sleeve T-Shirt",
    "Men Women Funny Long Sleeve T-Shirt", "Saying T-Shirt", "Funny Saying T-Shirt", "Vintage Tank Top",
    "Vintage T-Shirt", "Mens Women T-Shirt", "Men T-Shirt", "Shirt Tank Top", "Shirt Premium T-Shirt",
    "V-Neck Long Sleeve T-Shirt", "Tshirt T-Shirt", "funny Pullover Hoodie", "Mens Womens Long Sleeve T-Shirt",
    "funny design Long Sleeve T-Shirt", "Apparel Tank Top", "Teacher T-Shirt", "Quote Long Sleeve T-Shirt",
    "Apparel Long Sleeve T-Shirt", "Funny Apparel Tank Top", "Retro T-Shirt", "Men Women Shirt T-Shirt",
    "Funny Men Women T-Shirt", "t-shirt Pullover Hoodie", "Funny Shirt T-Shirt", "Womens Men Women V-Neck T-Shirt",
    "Men T-Shirt T-Shirt", "Vintage Women T-Shirt", "Vintage Long Sleeve T-Shirt", "Tee Funny T-Shirt",
    "Funny Quotes T-Shirt", "Funny design Tank Top", "Funny design Long Sleeve T-Shirt", "basketball cap",
    "basketball hat", "baseball hat", "baseball cap", "Baseball Cap Adjustable Hat"
]

class DatabaseManager:
    def __init__(self, db_path="scraped_urls.db"):
        self.conn = sqlite3.connect(db_path)
        self.cursor = self.conn.cursor()
        self._init_db()

    def _init_db(self):
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS scraped_urls (
                url TEXT PRIMARY KEY,
                scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'pending',
                error_message TEXT DEFAULT '',
                download_path TEXT DEFAULT ''
            )
        ''')
        self.conn.commit()
        self.cursor.execute("PRAGMA table_info(scraped_urls)")
        cols = {row[1] for row in self.cursor.fetchall()}
        if 'scraped_at' not in cols:
            self.cursor.execute("ALTER TABLE scraped_urls ADD COLUMN scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
        if 'status' not in cols:
            self.cursor.execute("ALTER TABLE scraped_urls ADD COLUMN status TEXT DEFAULT 'pending'")
        if 'error_message' not in cols:
            self.cursor.execute("ALTER TABLE scraped_urls ADD COLUMN error_message TEXT DEFAULT ''")
        if 'download_path' not in cols:
            self.cursor.execute("ALTER TABLE scraped_urls ADD COLUMN download_path TEXT DEFAULT ''")
        self.conn.commit()

    def is_scraped(self, url):
        # 只要状态是 success、downloaded 或 partial_success 都视为已爬取，避免重复
        self.cursor.execute("SELECT 1 FROM scraped_urls WHERE url = ? AND status IN ('success', 'downloaded', 'partial_success')", (url,))
        return self.cursor.fetchone() is not None

    def mark_scraped(self, url, status="success", error_message="", download_path=""):
        try:
            self.cursor.execute('''
                INSERT OR REPLACE INTO scraped_urls (url, scraped_at, status, error_message, download_path) 
                VALUES (?, CURRENT_TIMESTAMP, ?, ?, ?)
            ''', (url, status, error_message, download_path))
            self.conn.commit()
        except sqlite3.IntegrityError:
            pass

    def close(self):
        self.conn.close()

class AntiAntiCrawler:
    def __init__(self):
        self.WAIT_CONFIG = {
            "page_load": (3, 8),
            "element_find": (2, 5),
            "between_actions": (4, 10),
            "between_pages": (10, 20),
            "download_timeout": 60,
            "captcha_solve": 10,
        }

        self.day_mode_multiplier = 1.0
        self.night_mode_multiplier = 0.8

        self.random_actions = [
            "scroll_up_down",
            "move_mouse",
            "short_pause",
            "change_viewport",
        ]

        self.request_count = 0
        self.session_start_time = time.time()

        self.max_continuous_hours = 12
        self.big_break_hours = 1
        self.short_break_interval = 50
        self.short_break_duration = (30, 60)

    def get_current_mode_multiplier(self):
        current_hour = datetime.now().hour
        if 0 <= current_hour <= 7:
            return self.night_mode_multiplier
        if (9 <= current_hour <= 12) or (14 <= current_hour <= 18):
            return 1.2
        return self.day_mode_multiplier

    def smart_wait(self, wait_type="between_actions", min_time=None, max_time=None):
        multiplier = self.get_current_mode_multiplier()
        request_factor = 1.0 + (self.request_count // 200) * 0.1
        request_factor = min(request_factor, 2.0)

        if wait_type in self.WAIT_CONFIG:
            config = self.WAIT_CONFIG[wait_type]
            if isinstance(config, tuple):
                config_min, config_max = config
            else:
                config_min = config_max = config
        else:
            config_min, config_max = self.WAIT_CONFIG["between_actions"]

        if min_time is None:
            min_time = config_min
        if max_time is None:
            max_time = config_max

        min_time = min_time * multiplier * request_factor
        max_time = max_time * multiplier * request_factor

        if random.random() < 0.2:
            max_time = max_time * 1.5

        wait_time = random.uniform(min_time, max_time)
        self.request_count += 1

        if self.request_count % 50 == 0:
            elapsed_hours = (time.time() - self.session_start_time) / 3600
            requests_per_hour = self.request_count / elapsed_hours if elapsed_hours > 0 else 0
            print(
                f"请求统计：总数={self.request_count}，用时={elapsed_hours:.1f}小时，"
                f"平均速度={requests_per_hour:.1f}/小时，时段系数={multiplier:.2f}"
            )

        time.sleep(wait_time)
        return wait_time

    def random_behavior(self):
        if random.random() < 0.2:
            action = random.choice(self.random_actions)

            if action == "scroll_up_down":
                time.sleep(random.uniform(0.5, 1.5))
            elif action == "move_mouse":
                time.sleep(random.uniform(0.3, 1.0))
            elif action == "short_pause":
                time.sleep(random.uniform(0.5, 2.0))
            elif action == "change_viewport":
                time.sleep(random.uniform(0.5, 1.0))

    def check_long_run_protection(self, items_processed):
        elapsed_hours = (time.time() - self.session_start_time) / 3600
        if elapsed_hours >= self.max_continuous_hours:
            print(f"已连续运行 {elapsed_hours:.1f} 小时，执行长时间休息")
            return True

        if items_processed % 500 == 0 and items_processed > 0:
            if random.random() < 0.4:
                return True
        return False

    def take_big_break(self):
        break_hours = self.big_break_hours + random.uniform(0, 0.5)
        break_seconds = break_hours * 3600
        print(f"长时间休息：{break_hours:.1f} 小时")
        time.sleep(break_seconds)
        self.session_start_time = time.time()

    def check_short_break(self, items_processed):
        if items_processed % self.short_break_interval == 0 and items_processed > 0:
            print(f"已处理 {items_processed} 条，执行短休息")
            return True
        return False

    def take_short_break(self):
        break_duration = random.uniform(*self.short_break_duration)
        print(f"短休息：{break_duration:.1f} 秒")
        time.sleep(break_duration)

class CreativeFabricaScraper:
    CHROME_ARGUMENTS = [
    "-no-first-run",
    "-force-color-profile=srgb",
    "-metrics-recording-only",
    "-password-store=basic",
    "-use-mock-keychain",
    "-export-tagged-pdf",
    "-no-default-browser-check",
    "-disable-background-mode",
    "-enable-features=NetworkService,NetworkServiceInProcess",
    "-disable-features=FlashDeprecationWarning",
    "-deny-permission-prompts",
    "-disable-gpu",
    "-accept-lang=en-US",
    "--disable-usage-stats",
    "--disable-crash-reporter",
    "--no-sandbox"
    ]
    def __init__(self):
        co = ChromiumOptions()
        for argument in CreativeFabricaScraper.CHROME_ARGUMENTS:
            co.set_argument(argument)
        co.set_local_port(9224)
        co.set_user_data_path(r"d:\Code\UserData_Tshirt")
        
        # co.headless(True) # Uncomment for headless mode
        self.page = ChromiumPage(addr_or_opts=co)
        self.recaptcha_solver = RecaptchaSolver(self.page)
        self.db = DatabaseManager()
        self.anti_anti = AntiAntiCrawler()
        self.total_processed = 0
        self.date_parse_fail_count = 0
        self.base_url = "https://www.creativefabrica.com/subscriptions/graphics/t-shirt-designs/page/{}/?orderby=date"
        self.today = datetime.now()
        self.save_root = f"D:/印花图/T恤/{self.today.strftime('%Y%m%d')}"
        os.makedirs(self.save_root, exist_ok=True)
        self.ai_client = None
        api_key = str(OPENAI_API_KEY or "").strip()
        base_url = str(OPENAI_BASE_URL or "").strip()
        if api_key:
            try:
                self.ai_client = OpenAI(api_key=api_key, base_url=base_url)
                print(f"Qwen 客户端初始化成功，文本模型: {OPENAI_MODEL}，视觉模型: {OPENAI_VL_MODEL}")
            except Exception as e:
                print(f"初始化 Qwen 客户端失败: {e}")
        else:
            print("未配置 OPENAI_API_KEY，图片识别将跳过并保留原文件名")

    def smart_wait(self, min_s=3.0, max_s=6.0, long_prob=0.25, long_min=8.0, long_max=15.0):
        self.page.wait.doc_loaded()
        self.anti_anti.random_behavior()

        if random.random() < long_prob:
            min_time, max_time = long_min, long_max
        else:
            min_time, max_time = min_s, max_s

        wait_time = self.anti_anti.smart_wait("between_actions", min_time, max_time)
        print(f"智能等待：{wait_time:.2f} 秒")
        return wait_time

    def parse_date(self, date_str):
        # 示例：Listed on Jan 09, 2026 - ID 139659888
        try:
            if isinstance(date_str, (list, tuple)):
                text = " ".join([str(x) for x in date_str if x is not None])
            else:
                text = str(date_str or "")

            text = text.replace("\u00a0", " ")
            text = re.sub(r"\s+", " ", text).strip()

            months = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)"

            m1 = re.search(rf"(?:Listed\s+on\s+)?({months}[a-z]*\s+\d{{1,2}},\s+\d{{4}})", text, flags=re.IGNORECASE)
            if m1:
                date_part = m1.group(1).strip()
                if date_part.lower().startswith("sept"):
                    date_part = "Sep" + date_part[4:]
                for fmt in ("%b %d, %Y", "%B %d, %Y"):
                    try:
                        return datetime.strptime(date_part, fmt)
                    except ValueError:
                        pass

            m2 = re.search(rf"(?:Listed\s+on\s+)?(\d{{1,2}}\s+{months}[a-z]*\s+\d{{4}})", text, flags=re.IGNORECASE)
            if m2:
                date_part = m2.group(1).strip()
                if date_part.lower().split(" ", 2)[1].startswith("sept"):
                    parts = date_part.split(" ")
                    parts[1] = "Sep"
                    date_part = " ".join(parts)
                for fmt in ("%d %b %Y", "%d %B %Y"):
                    try:
                        return datetime.strptime(date_part, fmt)
                    except ValueError:
                        pass
        except Exception as e:
            print(f"解析日期失败，原始文本: {date_str}，错误: {e}")
        return None

    def clean_title(self, title):
        patterns = [
            r"\bT[\s-]?shirts?\b",
            r"\bPNG\b",
            r"\bSVG\b",
            r"\bJPG\b",
            # r"\bDesigns?\b",
            r"(?i)\bdesigns?\b",
        ]

        cleaned = title
        for pattern in patterns:
            cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)

        cleaned = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", " ", cleaned)
        cleaned = re.sub(r"[^A-Za-z0-9\u4e00-\u9fff\s\(\)']", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip().strip(" .-_")
        cleaned = cleaned[:150].rstrip(" .")
        return cleaned if cleaned else "未命名"

    def normalize_subject_text(self, subject):
        text = str(subject).strip()
        text = re.sub(r"[\"“”‘’`]+", "", text)
        text = re.sub(r"\s*&\s*", " & ", text)
        text = re.sub(r"[^A-Za-z0-9\u4e00-\u9fff\s'&/+\-#.]", " ", text)
        text = re.sub(r"(?<![A-Za-z0-9\u4e00-\u9fff])['/+\-#.]+", " ", text)
        text = re.sub(r"['/+\-#.]+(?![A-Za-z0-9\u4e00-\u9fff])", " ", text)
        text = re.sub(r"(?<![A-Za-z0-9\u4e00-\u9fff])&+(?![A-Za-z0-9\u4e00-\u9fff])", " & ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def remove_subject_filter_words(self, subject):
        filtered = subject
        for word in SUBJECT_FILTER_WORDS:
            filtered = re.sub(re.escape(word), " ", filtered, flags=re.IGNORECASE)
        return filtered

    def remove_noise_words(self, subject):
        filtered = subject
        for word in sorted(AMAZON_NOISE_WORDS, key=len, reverse=True):
            pattern = rf"(?<![A-Za-z0-9]){re.escape(word)}(?![A-Za-z0-9])"
            filtered = re.sub(pattern, " ", filtered, flags=re.IGNORECASE)
        return filtered

    def sanitize_filename(self, text):
        cleaned = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", " ", str(text))
        cleaned = re.sub(r"\s+", " ", cleaned).strip().strip(" .-_")
        cleaned = cleaned[:150].rstrip(" .")
        return cleaned

    def filter_subject_for_filename(self, subject):
        if not subject:
            return ""

        lowered = str(subject).strip().lower()
        if lowered in {"no text", "just graphic", "识别失败", "图片获取失败"}:
            return ""

        filtered = self.remove_subject_filter_words(str(subject))
        filtered = self.remove_noise_words(filtered)
        filtered = self.normalize_subject_text(filtered)
        filtered = self.sanitize_filename(filtered)

        lowered_filtered = filtered.lower()
        if lowered_filtered in {"no text", "just graphic"}:
            return ""
        return filtered

    def _call_openai(self, messages, model):
        if not self.ai_client:
            return ""
        try:
            response = self.ai_client.chat.completions.create(model=model, messages=messages)
            content = response.choices[0].message.content if response and response.choices else ""
            if isinstance(content, list):
                parts = []
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        parts.append(str(item.get("text", "")))
                    elif isinstance(item, str):
                        parts.append(item)
                content = " ".join(parts)

            text = re.sub(r"\s+", " ", str(content or "")).strip().strip("\"'")
            text = re.sub(r"^```(?:text|json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
            text = re.sub(r"^(output|result)\s*:\s*", "", text, flags=re.IGNORECASE).strip()
            return text
        except Exception as e:
            print(f"Qwen API 调用失败: {e}")
            return ""

    def recognize_text_from_image(self, image_path):
        if not self.ai_client:
            return ""

        try:
            with open(image_path, "rb") as f:
                image_bytes = f.read()
        except Exception as e:
            print(f"读取图片失败 {image_path}: {e}")
            return ""

        image_ext = os.path.splitext(image_path)[1].lower()
        mime_type = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
        }.get(image_ext, "image/png")

        encoded_string = base64.b64encode(image_bytes).decode("utf-8")
        prompt = """Process the image content strictly by following these prioritized rules and output only the final English result:

1. **Solid Color Check**:
- If the design area has no readable text, output exactly: no text

2. **Graphic-Only Detection**:
- If the image has graphics/icons only and no meaningful text, output exactly: just graphic

3. **Text Processing**:
a. Remove decorative symbols and invalid characters while preserving semantics
b. Normalize spacing: single spaces only, line breaks become spaces
c. Keep proper nouns and meaningful phrase structure
d. If text is very long, keep the most prominent core phrase
e. Remove product category words (e.g., hat, shirt, t-shirt, hoodie, tank top, apparel)

4. **Output Rules**:
- Output only one concise English phrase
- No explanation, no punctuation-only output, no markdown"""

        messages = [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{mime_type};base64,{encoded_string}",
                        "detail": "high",
                    },
                },
            ],
        }]

        subject = self._call_openai(messages, model=OPENAI_VL_MODEL)
        print(f"图片识别完成：{os.path.basename(image_path)} -> {subject}")
        return subject

    def get_unique_filename(self, directory, filename):
        name, ext = os.path.splitext(filename)
        counter = 1
        new_filename = filename
        while os.path.exists(os.path.join(directory, new_filename)):
            new_filename = f"{name}({counter}){ext}"
            counter += 1
        return new_filename

    def solve_captcha_and_click_submit(self):
        
        try:
            print("开始解决验证码")
            t0 = time.time()

            try:
                self.recaptcha_solver.solveCaptcha()
            except Exception as e:
                print(f"验证码解决过程中抛出异常: {e}")
                # 不做任何操作，等待2秒
                print("验证码解决异常，等待2秒")
                time.sleep(2)

            solve_time = time.time() - t0
            print(f"验证码处理完成，总耗时: {solve_time:.2f}秒")

            
            submit_button = self.page.ele(
                'xpath://button[@class="btn c-button c-button--green c-button--md u-mt-10 u-mb-10 u-semibold" and @type="submit"]'
            )

            if submit_button:
                print("找到提交按钮，点击提交")
                submit_button.click()
                
                # 点击后等待一下，确认页面响应
                time.sleep(3)
                return True
            else:
                print("未找到提交按钮")
                return False

        except Exception as e:
            print(f"解决验证码流程失败: {e}")
            return False

    def download_zip_file(self, download_path, subpage_url):
        """
        下载 ZIP 压缩文件（参考 CIXIU2.0.py 的实现）
        
        返回:
            Tuple[是否成功, ZIP 文件路径（如果成功）]
        """
        max_retries = 3

        for attempt in range(max_retries):
            try:
                print(f"下载 ZIP 文件尝试 {attempt + 1}/{max_retries}")

                # 查找下载按钮
                download_selectors = [
                    'xpath://a[contains(@class, "download-link") and contains(@class, "c-button--green")]',
                    'xpath://a[contains(@class, "product-download-button")]',
                    'xpath://a[contains(text(), "Download") and contains(@class, "c-button")]'
                ]

                download_button = None
                for selector in download_selectors:
                    download_button = self.page.ele(selector, timeout=8)
                    if download_button:
                        print(f"使用选择器找到下载按钮: {selector}")
                        break

                if not download_button:
                    print("未找到下载按钮")
                    if attempt < max_retries - 1:
                        print("刷新页面后继续循环")
                        self.page.refresh()
                        self.page.wait.doc_loaded()
                        self.smart_wait(2.0, 4.0, 0.2, 5.0, 9.0)
                        continue
                    else:
                        return False, None

                # 记录下载前的文件列表
                before_files = set(os.listdir(download_path)) if os.path.exists(download_path) else set()

                # 尝试点击下载
                try:
                    print("尝试点击下载按钮")
                    self.smart_wait()
                    download_result = download_button.click.to_download(
                        save_path=download_path,
                        timeout=60
                    )

                    # 情况1：正常下载
                    if download_result:
                        print("ZIP 文件下载成功启动")

                        # 等待下载完成，查找新出现的 ZIP 文件
                        zip_file_path = None
                        zip_found = False

                        for wait_attempt in range(60):  # 等待 60 秒
                            time.sleep(1)

                            if os.path.exists(download_path):
                                current_files = set(os.listdir(download_path))
                                new_files = current_files - before_files

                                zip_files = [f for f in new_files if f.lower().endswith('.zip')]

                                if zip_files:
                                    zip_filename = zip_files[0]
                                    zip_file_path = os.path.join(download_path, zip_filename)
                                    print(f"发现新的 ZIP 文件: {zip_filename}")
                                    zip_found = True
                                    break

                        if zip_found:
                            return True, zip_file_path
                        else:
                            print("未检测到 ZIP 文件被创建")
                            # 继续重试

                    # 情况2：click.to_download 返回 False，检查是否有验证码
                    else:
                        print("click.to_download 返回 False，检查是否存在验证码")
                        
                        has_captcha = False
                        captcha_selectors = [
                            'xpath://div[contains(@class, "recaptcha")]',
                            'xpath://iframe[contains(@title, "reCAPTCHA")]'
                        ]
                        
                        for captcha_selector in captcha_selectors:
                            if self.page.ele(captcha_selector, timeout=2):
                                has_captcha = True
                                print("检测到验证码")
                                break
                        
                        if has_captcha:
                            # 调用验证码解决函数
                            if self.solve_captcha_and_click_submit():
                                print("验证码已解决并点击提交按钮，等待下载开始")
                                # before_files 已在上方记录

                                # 等待下载完成，查找新出现的 ZIP 文件
                                zip_found = False
                                zip_file_path = None

                                for wait_attempt in range(60):
                                    time.sleep(1)

                                    if os.path.exists(download_path):
                                        current_files = set(os.listdir(download_path))
                                        new_files = current_files - before_files

                                        zip_files = [f for f in new_files if f.lower().endswith('.zip')]

                                        if zip_files:
                                            zip_filename = zip_files[0]
                                            zip_file_path = os.path.join(download_path, zip_filename)
                                            print(f"通过验证码解决后下载发现 ZIP 文件: {zip_filename}")
                                            zip_found = True
                                            break

                                if zip_found:
                                    return True, zip_file_path
                                else:
                                    print("验证码解决后等待仍未检测到 ZIP 文件")
                            else:
                                print("验证码解决失败")

                        # 如果没有验证码或验证码解决失败，重新定位下载按钮并再次尝试点击下载
                        print("未触发下载，重新定位下载按钮并再次尝试点击")
                        try:
                            retry_button = None
                            for selector in download_selectors:
                                retry_button = self.page.ele(selector, timeout=6)
                                if retry_button:
                                    print(f"重新定位下载按钮成功: {selector}")
                                    break

                            if retry_button:
                                self.smart_wait()
                                retry_result = retry_button.click.to_download(
                                    save_path=download_path,
                                    timeout=60
                                )
                                if retry_result:
                                    print("重新点击下载按钮成功启动下载")
                                    zip_found = False
                                    zip_file_path = None

                                    for wait_attempt in range(60):
                                        time.sleep(1)

                                        if os.path.exists(download_path):
                                            current_files = set(os.listdir(download_path))
                                            new_files = current_files - before_files

                                            zip_files = [f for f in new_files if f.lower().endswith('.zip')]

                                            if zip_files:
                                                zip_filename = zip_files[0]
                                                zip_file_path = os.path.join(download_path, zip_filename)
                                                print(f"重新点击后发现 ZIP 文件: {zip_filename}")
                                                zip_found = True
                                                break

                                    if zip_found:
                                        return True, zip_file_path
                                    else:
                                        print("重新点击后未检测到 ZIP 文件")
                                else:
                                    print("重新点击下载按钮未启动下载")
                            else:
                                print("重新定位下载按钮失败")
                        except Exception as retry_error:
                            print(f"重新定位并点击下载按钮失败: {retry_error}")

                except Exception as click_error:
                    print(f"点击下载按钮时出错: {click_error}")

                    # 点击失败后重新定位下载按钮并再次尝试点击
                    print("点击失败，重新定位下载按钮并再次尝试点击")
                    try:
                        retry_button = None
                        for selector in download_selectors:
                            retry_button = self.page.ele(selector, timeout=6)
                            if retry_button:
                                print(f"重新定位下载按钮成功: {selector}")
                                break

                        if retry_button:
                            self.smart_wait()
                            retry_result = retry_button.click.to_download(
                                save_path=download_path,
                                timeout=60
                            )
                            if retry_result:
                                print("重新点击下载按钮成功启动下载")
                                zip_found = False
                                zip_file_path = None

                                for wait_attempt in range(60):
                                    time.sleep(1)

                                    if os.path.exists(download_path):
                                        current_files = set(os.listdir(download_path))
                                        new_files = current_files - before_files
                                        zip_files = [f for f in new_files if f.lower().endswith('.zip')]

                                        if zip_files:
                                            zip_filename = zip_files[0]
                                            zip_file_path = os.path.join(download_path, zip_filename)
                                            print(f"重新点击后发现 ZIP 文件: {zip_filename}")
                                            zip_found = True
                                            break

                                if zip_found:
                                    return True, zip_file_path
                                else:
                                    print("重新点击后未检测到 ZIP 文件")
                            else:
                                print("重新点击下载按钮未启动下载")
                        else:
                            print("重新定位下载按钮失败")

                    except Exception as final_error:
                        print(f"重新定位并点击下载按钮失败: {final_error}")

            except Exception as e:
                error_type = type(e).__name__
                print(f"下载尝试 {attempt + 1} 失败（{error_type}）: {e}")

                if attempt == max_retries - 1:
                    print(f"ZIP 文件下载失败，已达最大重试次数")
                    return False, None

                # 刷新页面后继续循环
                print("刷新当前页面")
                self.page.refresh()
                self.page.wait.doc_loaded()
                self.smart_wait(2.0, 4.0, 0.2, 5.0, 9.0)

        return False, None

    def process_download(self, zip_path, final_title, url):
        try:
            zip_dir = os.path.dirname(zip_path)
            zip_name = os.path.basename(zip_path)
            extract_folder_name = os.path.splitext(zip_name)[0]
            extract_path = os.path.join(zip_dir, extract_folder_name)
            
            # 解压 ZIP
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(extract_path)
            
            # 查找 PNG 文件
            png_files = []
            for root, dirs, files in os.walk(extract_path):
                for file in files:
                    if file.lower().endswith('.png'):
                        png_files.append(os.path.join(root, file))
            
            # 移动并重命名 PNG
            if not png_files:
                print(f"未在 {zip_name} 中找到 PNG 文件")
                self.db.mark_scraped(url, status="partial_success", error_message="ZIP 中未发现 PNG 文件")
            else:
                before_files = {
                    os.path.abspath(os.path.join(self.save_root, name))
                    for name in os.listdir(self.save_root)
                    if os.path.isfile(os.path.join(self.save_root, name))
                }

                moved_files = []
                for png_file in png_files:
                    original_name = os.path.basename(png_file)
                    unique_original_name = self.get_unique_filename(self.save_root, original_name)
                    destination_path = os.path.join(self.save_root, unique_original_name)
                    shutil.move(png_file, destination_path)
                    moved_files.append(os.path.abspath(destination_path))
                    print(f"已移动：{unique_original_name}")

                after_files = {
                    os.path.abspath(os.path.join(self.save_root, name))
                    for name in os.listdir(self.save_root)
                    if os.path.isfile(os.path.join(self.save_root, name))
                }

                new_files_set = after_files - before_files
                new_image_files = [path for path in moved_files if path in new_files_set]
                if not new_image_files:
                    new_image_files = moved_files

                for image_path in sorted(new_image_files, key=lambda p: os.path.basename(p).lower()):
                    recognized_subject = self.recognize_text_from_image(image_path)
                    filtered_subject = self.filter_subject_for_filename(recognized_subject)
                    current_name = os.path.basename(image_path)

                    if filtered_subject:
                        ext = os.path.splitext(current_name)[1] or ".png"
                        target_name = f"{filtered_subject}{ext.lower()}"
                        unique_target_name = self.get_unique_filename(self.save_root, target_name)
                        target_path = os.path.join(self.save_root, unique_target_name)

                        if os.path.normcase(os.path.abspath(target_path)) != os.path.normcase(os.path.abspath(image_path)):
                            os.rename(image_path, target_path)
                            print(f"AI 重命名：{current_name} -> {unique_target_name}")
                        else:
                            print(f"AI 命名与当前文件名一致，保持不变：{current_name}")
                    else:
                        fallback_name = f"{final_title}.png" if final_title else current_name
                        unique_fallback_name = self.get_unique_filename(self.save_root, fallback_name)
                        fallback_path = os.path.join(self.save_root, unique_fallback_name)
                        if os.path.normcase(os.path.abspath(fallback_path)) != os.path.normcase(os.path.abspath(image_path)):
                            os.rename(image_path, fallback_path)
                            print(f"AI 识别为空或过滤后为空，回退旧命名：{current_name} -> {unique_fallback_name}")
                        else:
                            print(f"AI 识别为空或过滤后为空，回退旧命名后名称不变：{current_name}")
                
                # 标记为成功
                self.db.mark_scraped(url, status="success", download_path=zip_path)

            # 清理临时文件
            os.remove(zip_path)
            shutil.rmtree(extract_path)
            
        except Exception as e:
            print(f"处理下载出错 {url}: {e}")
            self.db.mark_scraped(url, status="failed", error_message=f"处理下载出错: {str(e)}")

    def scrape(self):
        page_num = 1
        stop_scraping = False

        while not stop_scraping:
            current_url = self.base_url.format(page_num)
            print(f"抓取第 {page_num} 页：{current_url}")
            self.page.get(current_url)
            self.smart_wait()

            # Get all product links
            # //div[@class="c-headline c-headline--3"]/a
            links = self.page.eles('xpath://div[contains(@class, "c-headline--3")]/a')
            product_urls = [link.attr('href').strip() for link in links if link.attr('href')]
            
            if not product_urls:
                print("本页未发现产品，停止抓取。")
                break

            for url in product_urls:
                if self.anti_anti.check_long_run_protection(self.total_processed):
                    self.anti_anti.take_big_break()

                if self.anti_anti.check_short_break(self.total_processed):
                    self.anti_anti.take_short_break()

                if stop_scraping:
                    break
                
                print(f"访问子页面：{url}")
                
                # Check if already scraped
                if self.db.is_scraped(url):
                    print("该链接已抓取，跳过。")
                    continue
                
                try:
                    self.page.get(url)
                    self.smart_wait()

                    # 1. 检查上架日期
                    date_ele = self.page.ele('xpath://div[contains(@class, "u-mt-10")]/span[contains(@class, "u-font-12") and contains(@class, "u-gray")]')
                    if date_ele:
                        date_text = date_ele.text
                        listed_date = self.parse_date(date_text)
                        
                        if listed_date:
                            # 超过 2 天则停止全局抓取
                            diff = self.today - listed_date
                            if diff.days > 2:
                                print(f"上架日期 {listed_date.date()} 超过 2 天，停止全局抓取。")
                                stop_scraping = True
                                break
                        else:
                            self.date_parse_fail_count += 1
                            if self.date_parse_fail_count <= 5:
                                print(f"无法解析日期，继续安全处理。日期原文: {date_text}")
                            else:
                                print("无法解析日期，继续安全处理。")
                    
                    # 2. Download ZIP file
                    zip_success, zip_file_path = self.download_zip_file(self.save_root, url)
                    
                    if zip_success and zip_file_path:
                        # 立即记录子页面 URL 为 downloaded 状态
                        print(f"下载成功，记录子页面 URL：{url}")
                        self.db.mark_scraped(url, status="downloaded", download_path=zip_file_path)

                        # 3. Get Title
                        title_ele = self.page.ele('xpath://h1[contains(@class, "c-headline--h1")]')
                        raw_title = title_ele.text if title_ele else "未命名"

                        # 4. Clean Title
                        clean_title_text = self.clean_title(raw_title)

                        # 5. Process File（逐图 AI 识别并重命名，失败回退旧命名逻辑）
                        self.process_download(zip_file_path, clean_title_text, url)
                    else:
                        print(f"ZIP 下载失败：{url}")
                        self.db.mark_scraped(url, status="failed", error_message="ZIP 下载失败")
                        
                except Exception as e:
                    print(f"处理页面出错 {url}: {e}")
                    self.db.mark_scraped(url, status="failed", error_message=str(e))

                self.total_processed += 1

            page_num += 1

        self.db.close()
        self.page.quit()
        print("抓取完成。")

if __name__ == "__main__":
    scraper = CreativeFabricaScraper()
    scraper.scrape()
