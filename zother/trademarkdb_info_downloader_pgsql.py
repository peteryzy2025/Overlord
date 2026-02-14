from DrissionPage import ChromiumPage, ChromiumOptions
from datetime import datetime
import os, re, shutil, json
import time
import xml.etree.ElementTree as ET
import pandas as pd
import zipfile
from io import BytesIO
from datetime import datetime
import logging
import base64
import requests
from PIL import Image
import io
from pathlib import Path
import time
import psycopg2

def parse_and_update(zip_path: str, excel_file_path: str):
    # ----------------------------------------------------------
    # 2.1 解析 XML → DataFrame
    # ----------------------------------------------------------
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        xml_files = [f for f in zip_ref.namelist() if f.lower().endswith('.xml')]
        if not xml_files:
            print("ZIP 文件中没有找到 XML 文件。")
            return

        all_rows = []
        for xml_file in xml_files:
            with zip_ref.open(xml_file) as file:
                with BytesIO(file.read()) as xml_data:
                    tree = ET.parse(xml_data)
                    root = tree.getroot()

                    for case_file in root.findall('.//case-file'):
                        serial_number = case_file.findtext('./serial-number', default='').strip()
                        status_code   = case_file.findtext('./case-file-header/status-code', default='').strip()
                        word_mark     = case_file.findtext('./case-file-header/mark-identification', default='').strip()
                        registration_number = case_file.findtext('./registration-number', default='').strip()
                        filing_date   = case_file.findtext('./case-file-header/filing-date', default='').strip()
                        registration_date = case_file.findtext('./case-file-header/registration-date', default='').strip()
                        transaction_date  = case_file.findtext('./transaction-date', default='').strip()

                        intl_codes = case_file.findall('./classifications/classification/international-code')
                        raw_codes  = [c.text.strip() for c in intl_codes if c.text and c.text.strip()]
                        intl_class = ','.join(set(raw_codes))

                        if not serial_number:
                            continue

                        status_code_int = int(status_code) if status_code.isdigit() else None
                        mark_drawing_type = case_file.findtext('.//case-file-header/mark-drawing-code') or ''
                        owner_name        = case_file.findtext('.//case-file-owners/case-file-owner/party-name') or ''
                        legal_entity_type = case_file.findtext('.//case-file-owners/case-file-owner/legal-entity-type-code') or ''
                        entity_statement  = case_file.findtext('.//case-file-owners/case-file-owner/entity-statement', default='').strip()

                        all_rows.append({
                            'word_mark': re.sub(r'\s+', ' ', word_mark).strip(),
                            'serial_number': serial_number,
                            'status_code': status_code_int,
                            'registration_number': registration_number,
                            'filing_date': filing_date,
                            'registration_date': registration_date,
                            'transaction_date': transaction_date,
                            'intl_class': intl_class,
                            'mark_drawing_type': mark_drawing_type,
                            'owner_name': owner_name,
                            'legal_entity_type': legal_entity_type,
                            'entity_statement': entity_statement
                        })

        df = pd.DataFrame(all_rows)

    # ----------------------------------------------------------
    # 2.2 DataFrame → Excel（删除真空白 word_mark）
    # ----------------------------------------------------------
    df = df.fillna('')                              # NaN → ''
    df = df[df['word_mark'].str.strip().astype(bool)]  # 删除真空白
    df.to_excel(excel_file_path, index=False)
    print(f"删除真空白后保留 {len(df)} 行，已写出到 {excel_file_path}")

    # ----------------------------------------------------------
    # 2.3 再次读 Excel → 去重（不再删除空 word_mark）
    # ----------------------------------------------------------
    # 强制读取 serial_number 为字符串，防止数据库类型不匹配 (varchar vs integer)
    # 同时强制读取日期字段为字符串，防止出现 "20240312.0" 这种浮点数字符串
    df_from_excel = pd.read_excel(excel_file_path, dtype={
        'serial_number': str,
        'registration_number': str,
        'filing_date': str,
        'registration_date': str,
        'transaction_date': str
    }).fillna('')
    initial_rows = len(df_from_excel)
    df_from_excel = df_from_excel.drop_duplicates()
    print(f"删除了 {initial_rows - len(df_from_excel)} 行重复数据。")

    tmp_rows = len(df_from_excel)
    df_from_excel = df_from_excel.drop_duplicates(subset=['serial_number'], keep='last')
    print(f"根据 serial_number 去重后，删除了 {tmp_rows - len(df_from_excel)} 行数据。")

    # ----------------------------------------------------------
    # 2.4 连接数据库并批量更新
    # ----------------------------------------------------------
    conn = None
    cursor = None
    try:
        # print(f"DEBUG - DB Config: {db_config}")
        conn = psycopg2.connect(
            host="192.168.110.54",
            port=5432,
            dbname="overlord_db",
            user="user1",
            password="user555Y1",
            connect_timeout=10
        )
        cursor = conn.cursor()
        print("数据库连接成功。")

        # 获取已存在的 serial_number 和对应的 transaction_date
        cursor.execute("SELECT serial_number, transaction_date FROM theme_trademark_info")
        existing_records = {
            str(row[0]): (row[1].strftime("%Y-%m-%d") if row[1] else None)
            for row in cursor.fetchall()
        }
        print(f"数据库中现有 {len(existing_records)} 条记录。")

        deletes, inserts, updates = [], [], []

        for _, row in df_from_excel.iterrows():
            serial_number = row['serial_number']
            status_code   = row['status_code']

            # 统一截断长度
            def clean_val(v):
                s = str(v).strip()
                if s.endswith('.0'): 
                    s = s[:-2]
                return s

            word_mark = str(row['word_mark'])[:500]
            registration_number = clean_val(row['registration_number'])[:100]
            filing_date = clean_val(row['filing_date'])[:25]  or None
            registration_date = clean_val(row['registration_date'])[:25]  or None
            transaction_date = clean_val(row['transaction_date'])[:25]   or None
            intl_class = str(row['intl_class'])[:500]  or None
            mark_drawing_type = str(row['mark_drawing_type'])[:10] or None
            owner_name = str(row['owner_name'])[:500] or None
            entity_statement = str(row['entity_statement'])[:500] or None

            # legal_entity_type 处理
            let = str(row['legal_entity_type']).strip()
            legal_entity_type = ''
            if let and let != 'nan':
                try:
                    legal_entity_type = f"{int(float(let)):02d}"
                except ValueError:
                    pass
            
            # 构造参数
            if str(serial_number) in existing_records:
                # 比较 transaction_date
                db_transaction_date = existing_records[str(serial_number)]
                # 2. 比较前把当前字符串统一成 YYYY-MM-DD（如果为空就保持 None）
                current_transaction_date = None
                if transaction_date:
                    current_transaction_date = str(transaction_date)[:10]   # 取前 10 位即可
                
                # 如果数据库中的 transaction_date 为空，或者当前记录的 transaction_date 更大，则更新
                if (db_transaction_date is None or 
                    current_transaction_date is None or 
                    current_transaction_date >= db_transaction_date):
                    # 数据库中的 transaction_date 为空，或者当前记录的 transaction_date 更大，更新
                    # print(f"序列号为{serial_number},状态码为{status_code},transaction_date为{transaction_date},更新数据库")
                    deletes.append(serial_number)
                    updates.append(serial_number)
                    inserts.append((
                        word_mark, serial_number, registration_number, filing_date,
                        registration_date, transaction_date, status_code, intl_class,
                        mark_drawing_type, owner_name, legal_entity_type, entity_statement
                    ))
            else:
                # 新记录，直接插入
                # print(f"序列号为{serial_number},状态码为{status_code},transaction_date为{transaction_date},新记录，直接插入")
                inserts.append((
                    word_mark, serial_number, registration_number, filing_date,
                    registration_date, transaction_date, status_code, intl_class,
                    mark_drawing_type, owner_name, legal_entity_type, entity_statement
                ))

        # 批量删除
        if deletes:
            placeholders = ', '.join(['%s'] * len(deletes))
            # print(f"待删除的序列号有：{deletes},状态码为{status_code}")
            cursor.execute(f"DELETE FROM theme_trademark_info WHERE serial_number IN ({placeholders})", deletes)
            print(f"已删除 {cursor.rowcount} 条数据，其中包含 {len(updates)} 条更新数据，真实删除了 {cursor.rowcount - len(updates)} 条数据。")

        # 批量插入
        if inserts:
            # print(f"待插入的新记录有：{inserts}")
            sql_insert = """
            INSERT INTO theme_trademark_info
            (word_mark, serial_number, registration_number, filing_date,
             registration_date, transaction_date, status_code, intl_class,
             mark_drawing_type, owner_name, legal_entity_type, entity_statement)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """
            cursor.executemany(sql_insert, inserts)
            print(f"已插入 {cursor.rowcount} 条数据，其中包含 {len(updates)} 条更新数据，真实插入了 {cursor.rowcount - len(updates)} 条数据。")

        conn.commit()
        print("数据已批量更新至数据库。")

    except psycopg2.Error as err:
        print(f"数据库错误: {err}")
        if conn is not None:
            conn.rollback()

    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()

def recognize_captcha(canvas_element):
    """
    使用打码平台识别Canvas验证码
    """
    try:
        # 对Canvas元素进行截图
        screenshot = canvas_element.get_screenshot(as_bytes=True)
        b = base64.b64encode(screenshot).decode()
        
        # 调用打码平台API
        url = "http://api.jfbym.com/api/YmServer/customApi"
        data = {
            "token": "CsFaE-Bzce3A1zshAdWrMDOV2BKtgCFHaRbe_bXyXRw",  # 替换为您的token
            "type": "50100",  # 验证码类型，可根据实际情况调整
            "image": b,
        }
        headers = {
            "Content-Type": "application/json"
        }
        
        response = requests.post(url, headers=headers, json=data)
        result = response.json()
        
        if result.get('code') == 10000:
            inner_data = result.get('data', {})
            if inner_data.get('code') == 0:
                captcha_text = inner_data.get('data', '')
                print(f"验证码识别结果: {captcha_text}")
                return captcha_text
            else:
                print(f"验证码识别失败，内部错误码: {inner_data.get('code')}")
        else:
            print(f"验证码识别失败，接口错误码: {result.get('code')}")
        return None
            
    except Exception as e:
        print(f"验证码识别过程中发生错误: {e}")
        return None

def handle_captcha_dialog(page):
    """
    仅输入验证码并返回成功/失败；由外部在监听启动后再点 Continue
    """
    max_retries = 3
    retry_count = 0

    while retry_count < max_retries:
        try:
            print("检测到验证码弹框，开始处理...")
            time.sleep(2)

            canvas_element = page.ele('xpath://canvas[contains(@class, "jCaptchaCanvas")]', timeout=10)
            if not canvas_element:
                print("未找到验证码Canvas元素")
                return False

            captcha_text = recognize_captcha(canvas_element)
            if not captcha_text:
                print("验证码识别失败")
                return False

            captcha_input = page.ele('xpath://input[@id="jCaptcha" or contains(@class, "jCaptcha")]')
            if captcha_input:
                captcha_input.clear()
                captcha_input.input(captcha_text)
                print("已输入验证码")
                return True          # 只负责输入成功
            else:
                print("未找到验证码输入框")
                return False

        except Exception as e:
            print(f"处理验证码弹框时发生错误: {e}")
            retry_count += 1
            time.sleep(2)

    print("验证码处理失败，达到最大重试次数")
    return False


def download_file(SAVE_DIR: str) -> str:
    today_str = datetime.today().strftime('%Y-%m-%d')
    url = f'https://data.uspto.gov/bulkdata/datasets/trtdxfap?fileDataFromDate=2025-01-01&fileDataToDate={today_str}'

    os.makedirs(SAVE_DIR, exist_ok=True)

    co = ChromiumOptions()
    profile_path = r"D:\software\Data\chrome_profile"
    co.set_user_data_path(profile_path)
    co.set_pref('credentials_enable_service', False)
    co.no_imgs(True)
    # 关键：强制修改下载目录
    co.set_pref('download.default_directory', SAVE_DIR)
    co.set_pref('download.prompt_for_download', False)

    page = ChromiumPage(co)
    try:
        page.get(url)
        page.wait.load_start()

        link = page.ele('xpath://*[@id="pn_id_1-table"]/tbody/tr[1]/td[1]/a', timeout=30)
        if not link:
            print("未找到下载链接")
            return '0'

        file_name = link.text.strip()
        local_path = Path(SAVE_DIR) / file_name
        if local_path.exists():
            if local_path.stat().st_size > 0:
                print(f'{file_name} 已存在，跳过下载，直接使用本地文件。')
                return str(local_path)
            local_path.unlink()

        print(f'开始下载 {file_name}...')

        # 点击下载链接
        link.click()
        time.sleep(2)

        # 验证码处理（仅输入）
        captcha_dialog = page.ele('xpath://div[@role="dialog" and contains(@class, "p-dialog")]', timeout=10)
        if captcha_dialog and ("Captcha" in captcha_dialog.text or "验证码" in captcha_dialog.text):
            print("下载过程中出现验证码弹框，开始处理...")
            if not handle_captcha_dialog(page):
                print("验证码处理失败")
                return '0'
            print("验证码输入完成，即将点击 Continue...")

        # 点击 Continue（下载立即触发）
        continue_btn = page.ele('xpath://button[contains(text(), "Continue") and @type="submit"]', timeout=5)
        if continue_btn:
            continue_btn.click()
            print('已点击 Continue，等待文件落盘...')

        # 轮询文件出现（兼容 Chrome 临时文件名）
        import glob
        target_stem = Path(file_name).stem          # 不带扩展名
        for _ in range(600):                        # 最多 10 min
            # 1. 先找已完成的文件
            if local_path.exists() and local_path.stat().st_size > 0:
                print(f'文件已保存到: {local_path}')
                time.sleep(3)
                return str(local_path)

            # 2. 再找正在下载的临时文件（Chrome 写法）
            tmp_pattern = str(Path(SAVE_DIR) / f'{target_stem}*.crdownload')
            if glob.glob(tmp_pattern):
                print('下载仍在进行，继续等待...')
                time.sleep(2)
                continue

            # 3. 都没找到，再等 1 s 继续
            time.sleep(1)

        print('下载超时或失败')
        return '0'

    except Exception as e:
        print(f"下载过程中发生错误: {e}")
        import traceback
        traceback.print_exc()
        return '0'

    finally:
        page.quit()


# ================= 主流程 =================
SAVE_DIR = r'D:\共享文件夹\数据库'
output_excel_dir = r'D:\zm\数据库文件\日常更新\解析文件'

# 确保输出目录存在
os.makedirs(output_excel_dir, exist_ok=True)

# 下载文件
download_result = download_file(SAVE_DIR)
zip_path = download_result

if zip_path == '0':
    print('下载失败或未获取到文件。')
    time.sleep(5)
    exit()

excel_full = os.path.join(output_excel_dir, f'{os.path.splitext(os.path.basename(zip_path))[0]}.xlsx')

# 数据库配置
# db_config = {
#     'user': 'root',
#     'password': 'root',
#     'host': '192.168.110.8',
#     'database': 'TrademarkDB'
# }

# 数据库配置


print(f'开始解析入库：{zip_path}')
parse_and_update(zip_path, excel_full)
print("处理完成")
