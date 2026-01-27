from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from django.db.models import Q
from django.core.cache import cache
import nltk
import string
from collections import defaultdict
from nltk.tokenize import TweetTokenizer
from django.contrib.auth.decorators import login_required
from theme.models import *

# 状态码集合（保持不变）
before_STATUS_CODES = {
    616, 630, 638, 640, 641, 642, 643, 644, 645, 646, 647, 648,
    649, 650, 651, 652, 653, 654, 655, 656, 657, 658, 659, 660,
    661, 663, 665, 666, 672, 680, 681, 746, 760, 969, 686
}

live_pending = {
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

last_STATUS_CODES = live_pending - before_STATUS_CODES
HIGH_RISK_NAME_TYPES = {4, 5, 6, 7, 10}
LOW_RISK_NAME_TYPES = {1, 9}


def get_live_status_codes():
    """缓存获取 live_registered 状态码"""
    cache_key = 'live_registered_status_codes'
    live_registered = cache.get(cache_key)
    if live_registered is None:
        live_registered = set(
            StatusCodeMapping.objects.filter(
                status_type='Registered'
            ).values_list('status_code', flat=True)
        )
        cache.set(cache_key, live_registered, 3600)
    return live_registered


@login_required
def trend_page(request):
    return render(request, 'trend.html', {'active_nav': 'theme_products'})


@require_POST
@csrf_exempt
def trend_search(request):
    query = request.POST.get('trendQueryInput', '').strip()
    if not query:
        return JsonResponse({'error': '请输入搜索关键词'}, status=400)

    # 1. 分词处理
    tokens = words_split(query)
    valid_tokens = [t for t in tokens if not should_skip_word(t)]

    if not valid_tokens:
        return JsonResponse({
            'query': query, 'tokens': tokens,
            'uspto_keywords': [], 'uspto_details': {},
            'tro_keywords': [], 'tro_details': {},
            'word_risk_map': {},
            'high_risk_words': [], 'medium_risk_words': [], 'low_risk_words': [],
            'theme_risk_level': 'low', 'theme_risk_text': '低风险',
        })

    # ==========================================
    # 核心优化：美标网全大写，直接转大写用 __in 走索引！
    # ==========================================
    token_uppers = [t.upper() for t in valid_tokens]

    # 单次查询，word_mark__in 能完美利用数据库索引，500万数据毫秒级
    trademark_records = TrademarkInfo.objects.filter(
        word_mark__in=token_uppers
    ).values('word_mark', 'serial_number', 'intl_class', 'status_code')

    # 构建内存数据结构
    uspto_matches = []
    uspto_details = {}
    word_status_codes = defaultdict(set)
    uspto_word_lower_map = {}  # 小写映射用于后续匹配

    for record in trademark_records:
        word = record['word_mark']  # 这是大写的
        word_lower = word.lower()

        if word not in uspto_details:
            uspto_matches.append(word)
            uspto_details[word] = []
        uspto_details[word].append({
            'serial_number': record['serial_number'],
            'intl_class': record['intl_class'] or 'N/A'
        })
        if record['status_code']:
            try:
                word_status_codes[word].add(int(record['status_code']))
            except (ValueError, TypeError):
                pass

        # 记录小写映射，方便后续风险判断
        uspto_word_lower_map[word_lower] = word

    # ==========================================
    # TroTable 查询（假设可能大小写混合，用 __iexact）
    # 如果 TroTable 也是全大写，同样改成 __in 即可
    # ==========================================
    q_tro = Q()
    for token in valid_tokens:
        q_tro |= Q(theme_name__iexact=token)

    tro_records = TroTable.objects.filter(q_tro).exclude(
        name_type__in=LOW_RISK_NAME_TYPES
    ).values('theme_name', 'name_type')

    tro_matches = []
    tro_details = {}
    tro_risk_map = {}  # 小写 -> name_type

    for record in tro_records:
        word = record['theme_name']
        name_type = record['name_type']
        tro_matches.append(word)
        tro_details[word] = name_type
        tro_risk_map[word.lower()] = name_type

    # 4. 风险判断（纯内存操作）
    all_live = last_STATUS_CODES.union(get_live_status_codes())
    high_risk_words, medium_risk_words, low_risk_words = [], [], []
    word_risk_map = {}

    for token in valid_tokens:
        token_lower = token.lower()
        token_upper = token.upper()

        # 高风险判断（TroTable）
        if token_lower in tro_risk_map:
            name_type = tro_risk_map[token_lower]
            # 获取美标网原始大写形式，如果没有就用原词
            original_word = uspto_word_lower_map.get(token_lower, token_upper)

            if name_type in HIGH_RISK_NAME_TYPES:
                word_risk_map[original_word] = 'high'
                high_risk_words.append(original_word)
                continue

        # 中风险判断（美标网状态码）
        if token_lower in uspto_word_lower_map:
            original_word = uspto_word_lower_map[token_lower]
            status_codes = word_status_codes.get(original_word, set())

            if status_codes.intersection(all_live):
                word_risk_map[original_word] = 'medium'
                medium_risk_words.append(original_word)
            else:
                word_risk_map[original_word] = 'low'
                low_risk_words.append(original_word)
        else:
            # 不在美标网中，低风险
            word_risk_map[token] = 'low'
            low_risk_words.append(token)

    # 5. 整体风险等级
    if high_risk_words:
        theme_risk_level, theme_risk_text = 'high', '高风险'
    elif medium_risk_words:
        theme_risk_level, theme_risk_text = 'medium', '中风险'
    else:
        theme_risk_level, theme_risk_text = 'low', '低风险'

    return JsonResponse({
        'query': query, 'tokens': tokens,
        'uspto_keywords': uspto_matches, 'uspto_details': uspto_details,
        'tro_keywords': tro_matches, 'tro_details': tro_details,
        'word_risk_map': word_risk_map,
        'high_risk_words': high_risk_words,
        'medium_risk_words': medium_risk_words,
        'low_risk_words': low_risk_words,
        'theme_risk_level': theme_risk_level,
        'theme_risk_text': theme_risk_text,
    })


def words_split(theme):
    tokenizer = TweetTokenizer()
    return tokenizer.tokenize(theme or '')


def should_skip_word(word):
    """判断是否应该跳过该词的检测"""
    word = word.strip()
    if not word or len(word) == 1:
        return True
    if all(c in string.punctuation for c in word):
        return True
    if not any(c.isalnum() for c in word):
        return True
    return False


@login_required
def words_split_api(request):
    theme = (request.POST.get('theme') or request.GET.get('theme') or '').strip()
    if not theme:
        return JsonResponse({'error': '请输入 theme'}, status=400)
    tokens = words_split(theme)
    return JsonResponse({'theme': theme, 'tokens': tokens})