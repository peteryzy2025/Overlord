import requests
import logging
import random

# 配置日志
logger = logging.getLogger(__name__)

# 开发人员webhook列表（用于同步消息）
DEV_WEBHOOK_URLS = [
    "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=229c4401-fd45-49b1-b15e-3d46c8b9d7ac",
    "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=cc812cc6-1c28-4f3c-9806-d388e7940ab9",
    "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=b1f40747-a641-4886-b81d-a998f5e9095a",
    "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=8ca94212-ea84-4b4e-a294-55e713dcef67"
]


def _send_message(webhook_url, payload, max_retries=3, timeout=5):
    """
    内部通用发送方法

    参数:
        webhook_url (str): Webhook地址
        payload (dict): 请求payload
        max_retries (int): 最大重试次数
        timeout (int): 超时时间

    返回:
        dict: 发送结果
    """
    if not webhook_url:
        return {
            'success': False,
            'error_message': '未配置webhook地址',
            'retry_count': 0
        }

    retry_count = 0
    last_error = None

    while retry_count < max_retries:
        try:
            response = requests.post(
                webhook_url,
                json=payload,
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

    logger.warning(f"消息发送失败（重试{max_retries}次）: {last_error}")
    return {
        'success': False,
        'error_message': last_error,
        'retry_count': retry_count
    }


def _send_to_dev(markdown_content, max_total_attempts=10, timeout=5):
    """
    发送消息副本给开发人员（随机选择webhook，失败切换）

    参数:
        markdown_content (str): Markdown格式的消息内容
        max_total_attempts (int): 最大总尝试次数
        timeout (int): 请求超时时间

    返回:
        dict: 发送结果
    """
    if not DEV_WEBHOOK_URLS:
        logger.warning("未配置开发人员webhook列表")
        return {
            'success': False,
            'error_message': '未配置开发人员webhook列表',
            'retry_count': 0
        }

    # 随机打乱webhook顺序
    available_webhooks = DEV_WEBHOOK_URLS.copy()
    random.shuffle(available_webhooks)

    total_attempts = 0

    # 尝试不同的webhook直到成功或耗尽
    while available_webhooks and total_attempts < max_total_attempts:
        webhook_url = available_webhooks.pop(0)
        total_attempts += 1

        # 对单个webhook尝试发送（内部有3次重试）
        result = _send_message(
            webhook_url,
            {
                "msgtype": "markdown",
                "markdown": {"content": markdown_content}
            },
            max_retries=3,
            timeout=timeout
        )

        if result['success']:
            logger.info(f"开发人员消息发送成功，使用webhook #{total_attempts}")
            return {
                'success': True,
                'error_message': None,
                'retry_count': total_attempts - 1
            }

        # 失败则记录日志，尝试下一个webhook
        logger.warning(
            f"开发人员webhook #{total_attempts} 发送失败: {result['error_message']}，尝试下一个..."
        )

    # 所有webhook都失败
    error_msg = f"所有开发人员webhook均发送失败（共尝试{total_attempts}次）"
    logger.warning(error_msg)
    return {
        'success': False,
        'error_message': error_msg,
        'retry_count': total_attempts
    }


def send_wechat_work_message(webhook_url, markdown_content, max_retries=3, timeout=5):
    """
    发送企业微信Markdown消息（通用方法）
    每次发送都会同步一份给开发人员

    参数:
        webhook_url (str): 企业微信Webhook地址
        markdown_content (str): Markdown格式的消息内容
        max_retries (int): 最大重试次数，默认3次
        timeout (int): 请求超时时间（秒），默认5秒

    返回:
        dict: 包含发送结果的字典
            {
                'success': bool,  # 主消息是否发送成功
                'error_message': str,  # 错误信息（失败时）
                'retry_count': int,  # 主消息实际重试次数
                'dev_result': dict  # 开发人员消息发送结果
            }
    """
    if not webhook_url:
        return {
            'success': False,
            'error_message': '未配置企业微信通知地址',
            'retry_count': 0,
            'dev_result': None
        }

    # 1. 先发送主消息
    payload = {
        "msgtype": "markdown",
        "markdown": {"content": markdown_content}
    }

    main_result = _send_message(
        webhook_url,
        payload,
        max_retries=max_retries,
        timeout=timeout
    )

    # 2. 发送副本给开发人员（添加标识区分）
    dev_content = f"【消息副本】\n{markdown_content}"
    dev_result = _send_to_dev(dev_content, max_total_attempts=10, timeout=timeout)

    if not main_result['success']:
        logger.warning(f"主消息发送失败: {main_result['error_message']}")

    # 3. 返回合并结果
    return {
        'success': main_result['success'],
        'error_message': main_result['error_message'],
        'retry_count': main_result['retry_count'],
        'dev_result': dev_result
    }


def send_wechat_work_text_message(webhook_url, text_content, max_retries=3, timeout=5):
    """
    发送企业微信文本消息（可选功能，用于简单场景）
    每次发送都会同步一份给开发人员

    参数同上，content为纯文本
    """
    if not webhook_url:
        return {
            'success': False,
            'error_message': '未配置企业微信通知地址',
            'retry_count': 0,
            'dev_result': None
        }

    # 1. 先发送主消息
    payload = {
        "msgtype": "text",
        "text": {"content": text_content}
    }

    main_result = _send_message(
        webhook_url,
        payload,
        max_retries=max_retries,
        timeout=timeout
    )

    # 2. 发送副本给开发人员（转换为markdown格式）
    dev_content = f"【消息副本】\n**文本消息:**\n{text_content}"
    dev_result = _send_to_dev(dev_content, max_total_attempts=10, timeout=timeout)

    if not main_result['success']:
        logger.warning(f"主消息发送失败: {main_result['error_message']}")

    # 3. 返回合并结果
    return {
        'success': main_result['success'],
        'error_message': main_result['error_message'],
        'retry_count': main_result['retry_count'],
        'dev_result': dev_result
    }