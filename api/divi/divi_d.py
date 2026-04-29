import time
import json
import hashlib
import base64
import urllib.parse
import requests
from typing import Any, Dict


def post_partner_list_partner_user_order(
        req_body: Dict[str, Any],
        api_path: str,
        partner_code: str,
        secret: str,
        timeout: int = 10,
        print_if: bool = False,
) -> requests.Response:
    """
    封装的请求函数
    参数（）：
    - api_path: 接口路径（例如 "/partnerTaskOrder/listPartnerUserOrder"）
    - req_body: 要发送的 data 字段（Python dict）：
        1) 把 req_body 转为未排序的 JSON 字符串放到 payload["data"]
        2) 对 req_body 按键名排序（模拟 Java 的 TreeMap），把排序后的 JSON 用于签名计算
    - timeout: requests 超时时间（秒）

    返回：
    - requests.Response 对象（根据需要处理 response.status_code/response.json() 等）
    """
    if not partner_code:
        partner_code = "7607f3480484b48235"
    if not secret:
        secret = "655d0d4e9534f0e37381"
    base_url = "http://www.dividiy.com/partner/use/service"

    # 1) JSON 序列化（排序 + 去空格，保证签名一致）
    data_json_str = json.dumps(req_body, separators=(',', ':'), sort_keys=True)
    # 2) timestamp（毫秒）
    timestamp = int(time.time() * 1000)
    # 3) 待签名字符串： data_json_str + timestamp + secret
    raw_text = data_json_str + str(timestamp) + secret
    # 4) URL 编码（Java URLEncoder 行为，空格转为 +）
    encoded_text = urllib.parse.quote_plus(raw_text)
    # 5) MD5 + Base64
    md5_hash = hashlib.md5(encoded_text.encode('utf-8')).digest()
    digest_base64 = base64.b64encode(md5_hash).decode('utf-8')
    # 6) 构造最终 payload
    payload = {
        "partnerCode": partner_code,
        "timestamp": timestamp,
        "data": data_json_str,
        "digest": digest_base64
    }
    url = base_url.rstrip('/') + api_path  # 拼接完整 URL
    headers = {
        "Content-Type": "application/json; charset=utf-8"
    }
    if print_if:
        print(f"请求url:{url}")
        print(f"partner_code：{partner_code}, secret:{secret}")
        print("-" * 60)
        print(f"请求参数：{payload}")
        print("-" * 60)
    response = requests.post(url, json=payload, headers=headers, timeout=timeout)
    response.raise_for_status()
    return response
