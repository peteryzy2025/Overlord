#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import django
import logging

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
sys.path.append(PROJECT_ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Overlord.settings")
django.setup()

from amazon.services.amazon_performance_service import execute_performance_notification

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

if __name__ == '__main__':
    try:
        execute_performance_notification()
        logger.info("脚本执行完成")
    except Exception as e:
        logger.error(f"脚本执行失败: {e}", exc_info=True)
        sys.exit(1)