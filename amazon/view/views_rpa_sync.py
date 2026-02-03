# amazon/view/views_rpa_sync.py
"""
影刀 RPA 数据同步接口
用于接收影刀抓取的亚马逊邮件和绩效通知
"""

import json
import re
from datetime import datetime
from functools import wraps

from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from general.models import AmazonShop
from amazon.models import RiskKeyword, AmazonShopEmail, AmazonPerformanceNotification

# ========== 简单认证配置 ==========
RPA_SECRET_KEY = "YXD555"  # 影刀请求头里必须带 X-RPA-Secret: YXD555


def rpa_auth_required(func):
    """简单的影刀接口认证装饰器"""

    @wraps(func)
    def wrapper(request, *args, **kwargs):
        secret = request.headers.get('X-RPA-Secret')
        if secret != RPA_SECRET_KEY:
            return JsonResponse({
                'success': False,
                'error': 'Unauthorized: Invalid or missing X-RPA-Secret header'
            }, status=401)
        return func(request, *args, **kwargs)

    return wrapper


# ========== 风险检测服务 ==========
def detect_risk(title, apply_scope='all'):
    """
    检测标题风险
    :param title: 待检测的标题/主题字符串
    :param apply_scope: 'all', 'email', 'performance'  用于筛选关键词适用范围
    :return: (is_risk: bool, matched_keywords: list[RiskKeyword], category: str)
    """
    if not title:
        return False, [], None

    # 获取适用的关键词（启用状态，且适用范围匹配）
    queryset = RiskKeyword.objects.filter(is_active=True)
    if apply_scope != 'all':
        queryset = queryset.filter(apply_to__in=['all', apply_scope])

    keywords = list(queryset)
    matched = []

    for kw in keywords:
        keyword_text = kw.keyword
        is_match = False

        if kw.match_type == 'whole':
            # 整词匹配：\bkeyword\b，忽略大小写
            pattern = re.compile(r'\b' + re.escape(keyword_text) + r'\b', re.IGNORECASE)
            is_match = bool(pattern.search(title))

        elif kw.match_type == 'contains':
            # 包含匹配：简单 in，忽略大小写
            is_match = keyword_text.lower() in title.lower()

        elif kw.match_type == 'regex':
            # 正则匹配：用户自定义正则
            try:
                pattern = re.compile(keyword_text, re.IGNORECASE)
                is_match = bool(pattern.search(title))
            except re.error:
                continue

        elif kw.match_type == 'start':
            # 开头匹配
            is_match = title.lower().startswith(keyword_text.lower())

        if is_match:
            matched.append(kw)

    if not matched:
        return False, [], None

    # 按优先级排序，取最高优先级作为代表分类
    matched.sort(key=lambda x: x.priority, reverse=True)
    is_risk = True
    risk_category = matched[0].category

    return is_risk, matched, risk_category


# ========== 邮件同步接口 ==========
@csrf_exempt
@require_http_methods(["POST"])
@rpa_auth_required
def sync_email_api(request):
    """
    影刀同步亚马逊邮件
    POST /api/rpa/amazon-emails/sync/
    Header: X-RPA-Secret: YXD555

    Body:
    {
        "shop_id": 123,
        "subject": "Your Amazon.com seller account has been deactivated",
        "sender": "seller-performance@amazon.com",
        "receive_time": "2025-01-27 14:30:00",
        "email_body": "纯文本正文...",
        "html_body": "<html>...</html>"
    }
    """
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)

    # 字段校验
    required_fields = ['shop_id', 'subject', 'sender', 'receive_time', 'email_body']
    for field in required_fields:
        if field not in data:
            return JsonResponse({'success': False, 'error': f'Missing field: {field}'}, status=400)

    shop_id = data['shop_id']
    subject = data['subject']
    sender = data['sender']
    receive_time_str = data['receive_time']
    email_body = data['email_body']
    html_body = data.get('html_body', '')

    # 校验店铺存在
    try:
        shop = AmazonShop.objects.get(id=shop_id)
    except AmazonShop.DoesNotExist:
        return JsonResponse({'success': False, 'error': '店铺不存在'}, status=404)

    # 时间解析（不转时区，按字符串解析为 naive datetime）
    try:
        receive_time = datetime.strptime(receive_time_str, '%Y-%m-%d %H:%M:%S')
    except ValueError:
        return JsonResponse({
            'success': False,
            'error': 'Invalid receive_time format, expected: YYYY-MM-DD HH:MM:SS'
        }, status=400)

    # 查重：shop + subject + receive_time
    exists = AmazonShopEmail.objects.filter(
        shop=shop,
        subject=subject,
        receive_time=receive_time
    ).first()

    if exists:
        return JsonResponse({
            'success': True,
            'is_new': False,
            'id': exists.id,
            'message': '记录已存在'
        })

    # 风险检测
    is_risk, matched_keywords, risk_category = detect_risk(subject, apply_scope='email')

    # 入库
    try:
        with transaction.atomic():
            email_obj = AmazonShopEmail.objects.create(
                shop=shop,
                subject=subject,
                sender=sender,
                receive_time=receive_time,
                email_body=email_body,
                html_body=html_body,
                is_attention_needed=is_risk,
                is_processed=False
            )

            # 关联命中的关键词
            if matched_keywords:
                email_obj.matched_keywords.set(matched_keywords)

            return JsonResponse({
                'success': True,
                'id': email_obj.id,
                'is_new': True,
                'is_attention_needed': is_risk,
                'matched_keywords': [k.keyword for k in matched_keywords],
                'category': risk_category,
                'shop_name': shop.shop_name
            }, status=201)

    except Exception as e:
        return JsonResponse({'success': False, 'error': f'Database error: {str(e)}'}, status=500)


# ========== 绩效通知同步接口 ==========
@csrf_exempt
@require_http_methods(["POST"])
@rpa_auth_required
def sync_performance_api(request):
    """
    影刀同步绩效通知
    POST /api/rpa/amazon-performance/sync/
    Header: X-RPA-Secret: YXD555

    Body:
    {
        "shop_id": 123,
        "subject": "Notice: Policy Warning",
        "date": "2025-01-27",
        "content": "可选的详细内容..."  # 如果有的话
    }
    """
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)

    # 字段校验（content 可选）
    required_fields = ['shop_id', 'subject', 'date']
    for field in required_fields:
        if field not in data:
            return JsonResponse({'success': False, 'error': f'Missing field: {field}'}, status=400)

    shop_id = data['shop_id']
    subject = data['subject']
    date_str = data['date']

    # 校验店铺
    try:
        shop = AmazonShop.objects.get(id=shop_id)
    except AmazonShop.DoesNotExist:
        return JsonResponse({'success': False, 'error': '店铺不存在'}, status=404)

    # 日期解析
    try:
        from datetime import date as date_obj
        notification_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return JsonResponse({
            'success': False,
            'error': 'Invalid date format, expected: YYYY-MM-DD'
        }, status=400)

    # 查重：shop + subject + date（模型里的 uniq_shop_subject_date）
    exists = AmazonPerformanceNotification.objects.filter(
        shop=shop,
        subject=subject,
        date=notification_date
    ).first()

    if exists:
        return JsonResponse({
            'success': True,
            'is_new': False,
            'id': exists.id,
            'message': '记录已存在'
        })

    # 风险检测
    is_risk, matched_keywords, risk_category = detect_risk(subject, apply_scope='performance')

    # 入库（needs_attention 是 SmallIntegerField：1=需要注意，0=不需要）
    try:
        with transaction.atomic():
            notification_obj = AmazonPerformanceNotification.objects.create(
                shop=shop,
                subject=subject,
                date=notification_date,
                needs_attention=1 if is_risk else 0,
                is_processed=0
            )

            # 关联命中的关键词
            if matched_keywords:
                notification_obj.matched_keywords.set(matched_keywords)

            return JsonResponse({
                'success': True,
                'id': notification_obj.id,
                'is_new': True,
                'needs_attention': 1 if is_risk else 0,
                'matched_keywords': [k.keyword for k in matched_keywords],
                'category': risk_category,
                'shop_name': shop.shop_name
            }, status=201)

    except Exception as e:
        return JsonResponse({'success': False, 'error': f'Database error: {str(e)}'}, status=500)