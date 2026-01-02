# Api/WX/wx.py

import requests
import logging

# 配置日志
logger = logging.getLogger(__name__)


def send_wechat_work_message(webhook_url, markdown_content, max_retries=3, timeout=5):
    """
    发送企业微信Markdown消息（通用方法）

    参数:
        webhook_url (str): 企业微信Webhook地址
        markdown_content (str): Markdown格式的消息内容
        max_retries (int): 最大重试次数，默认3次
        timeout (int): 请求超时时间（秒），默认5秒

    返回:
        dict: 包含发送结果的字典
            {
                'success': bool,  # 是否发送成功
                'error_message': str,  # 错误信息（失败时）
                'retry_count': int  # 实际重试次数
            }
    """
    if not webhook_url:
        return {
            'success': False,
            'error_message': '未配置企业微信通知地址',
            'retry_count': 0
        }

    retry_count = 0
    last_error = None

    while retry_count < max_retries:
        try:
            response = requests.post(
                webhook_url,
                json={
                    "msgtype": "markdown",
                    "markdown": {
                        "content": markdown_content
                    }
                },
                timeout=timeout
            )

            if response.status_code == 200:
                result = response.json()
                if result.get('errcode') == 0:
                    return {
                        'success': True,
                        'error_message': None,
                        'retry_count': retry_count
                    }
                else:
                    last_error = result.get('errmsg', '未知错误')
                    retry_count += 1
            else:
                last_error = f'HTTP {response.status_code}'
                retry_count += 1

        except requests.exceptions.Timeout:
            last_error = '请求超时'
            retry_count += 1
        except Exception as e:
            last_error = f'异常: {str(e)}'
            retry_count += 1

    # 超过最大重试次数仍然失败
    logger.warning(f"企业微信消息发送失败（重试{max_retries}次）: {last_error}")
    return {
        'success': False,
        'error_message': last_error,
        'retry_count': retry_count
    }


def send_wechat_work_text_message(webhook_url, text_content, max_retries=3, timeout=5):
    """
    发送企业微信文本消息（可选功能，用于简单场景）

    参数同上，content为纯文本
    """
    if not webhook_url:
        return {
            'success': False,
            'error_message': '未配置企业微信通知地址',
            'retry_count': 0
        }

    retry_count = 0
    last_error = None

    while retry_count < max_retries:
        try:
            response = requests.post(
                webhook_url,
                json={
                    "msgtype": "text",
                    "text": {
                        "content": text_content
                    }
                },
                timeout=timeout
            )

            if response.status_code == 200:
                result = response.json()
                if result.get('errcode') == 0:
                    return {
                        'success': True,
                        'error_message': None,
                        'retry_count': retry_count
                    }
                else:
                    last_error = result.get('errmsg', '未知错误')
                    retry_count += 1
            else:
                last_error = f'HTTP {response.status_code}'
                retry_count += 1

        except requests.exceptions.Timeout:
            last_error = '请求超时'
            retry_count += 1
        except Exception as e:
            last_error = f'异常: {str(e)}'
            retry_count += 1

    logger.warning(f"企业微信文本消息发送失败（重试{max_retries}次）: {last_error}")
    return {
        'success': False,
        'error_message': last_error,
        'retry_count': retry_count
    }