import time
import json
import hashlib
import base64
from urllib.parse import quote_plus
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

    data_json_original = json.dumps(req_body, ensure_ascii=False, separators=(',', ':'))
    sorted_items = sorted(req_body.items(), key=lambda kv: kv[0])
    sorted_dict = {k: v for k, v in sorted_items}
    sorted_data_json = json.dumps(sorted_dict, ensure_ascii=False, separators=(',', ':'))
    # 3) timestamp（毫秒）
    timestamp = int(time.time() * 1000)
    # 4) 待签名字符串： sorted_data_json + timestamp + secret
    to_verify = f"{sorted_data_json}{timestamp}{secret}"
    # 5) URL 编码
    to_verify_encoded = quote_plus(to_verify, encoding='utf-8')
    # 6) MD5（utf-8），然后 Base64 编码
    md5_obj = hashlib.md5()
    md5_obj.update(to_verify_encoded.encode('utf-8'))
    md5_bytes = md5_obj.digest()
    digest_base64 = base64.b64encode(md5_bytes).decode('utf-8')
    # 7) 构造最终 payload
    payload = {
        "partnerCode": partner_code,
        "timestamp": timestamp,
        "data": data_json_original,
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
