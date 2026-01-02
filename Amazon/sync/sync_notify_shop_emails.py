#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
亚马逊店铺邮件定时推送脚本
功能：自动检测未处理的邮件，并推送到企业微信
触发方式：ZTasker定时任务
"""

import os
import sys
import django
import logging

# ========== Django环境初始化 ==========
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
sys.path.append(PROJECT_ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Overlord.settings")
django.setup()

from Amazon.services.amazon_shop_email_service import execute_email_notification

# ========== 日志配置 ==========
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

if __name__ == '__main__':
    try:
        execute_email_notification()
        logger.info("脚本执行完成")
    except Exception as e:
        logger.error(f"脚本执行失败: {e}", exc_info=True)
        sys.exit(1)