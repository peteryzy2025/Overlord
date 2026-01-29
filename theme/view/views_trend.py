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
SPECIAL_INTL_CLASSES = {'006', '015', '016', '018', '024', '025', '027', '035'}


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

    data = analyze_theme_trend(query)
    return JsonResponse(data, json_dumps_params={'ensure_ascii': False})


def batch_analyze_theme_trend(themes):
    """
    批量分析主题词的侵权风险趋势。
    Args:
        themes (list): 主题词列表
    Returns:
        dict: {theme: analysis_result}
    """
    results = {}
    unique_tokens = set()
    theme_tokens_map = {}
    
    # 1. 预处理所有主题，收集 tokens
    for theme in themes:
        if not theme:
            continue
        # 尝试从缓存获取
        cache_key = f'risk_analysis:{hash(theme)}'
        cached_result = cache.get(cache_key)
        if cached_result:
            results[theme] = cached_result
            continue
            
        tokens = words_split(theme.strip())
        valid_tokens = [t for t in tokens if not should_skip_word(t)]
        
        if not valid_tokens:
            # 空结果直接缓存
            empty_result = {
                'query': theme, 'tokens': tokens,
                'uspto_keywords': [], 'uspto_details': {},
                'tro_keywords': [], 'tro_details': {},
                'word_risk_map': {},
                'high_risk_words': [], 'medium_risk_words': [], 'low_risk_words': [],
                'theme_risk_level': 'low', 'theme_risk_text': '低风险',
            }
            cache.set(cache_key, empty_result, 3600)  # 缓存1小时
            results[theme] = empty_result
            continue
            
        theme_tokens_map[theme] = valid_tokens
        for token in valid_tokens:
            unique_tokens.add(token)

    if not unique_tokens:
        return results

    # 2. 批量查询数据库
    token_uppers = list({t.upper() for t in unique_tokens})
    
    # 美标查询
    trademark_records = TrademarkInfo.objects.filter(
        word_mark__in=token_uppers
    ).values('word_mark', 'serial_number', 'intl_class', 'status_code')
    
    # 构建美标数据结构
    uspto_details_global = defaultdict(list)
    word_status_codes_global = defaultdict(set)
    word_intl_classes_global = defaultdict(set)
    uspto_word_lower_map_global = {}
    
    for record in trademark_records:
        word = record['word_mark']
        word_lower = word.lower()
        
        uspto_details_global[word].append({
            'serial_number': record['serial_number'],
            'intl_class': record['intl_class'] or 'N/A',
            'status_code': record['status_code']
        })
        
        if record['status_code']:
            try:
                word_status_codes_global[word].add(int(record['status_code']))
            except (ValueError, TypeError):
                pass
                
        if record['intl_class']:
            word_intl_classes_global[word].add(record['intl_class'])
            
        uspto_word_lower_map_global[word_lower] = word

    # TRO查询
    q_tro = Q()
    for token in unique_tokens:
        q_tro |= Q(theme_name__iexact=token)
        
    tro_records = TroTable.objects.filter(q_tro).exclude(
        name_type__in=LOW_RISK_NAME_TYPES
    ).values('theme_name', 'name_type')
    
    tro_risk_map_global = {r['theme_name'].lower(): r['name_type'] for r in tro_records}
    tro_details_global = {r['theme_name']: r['name_type'] for r in tro_records}

    # 3. 为每个未缓存的主题生成结果
    all_live = last_STATUS_CODES.union(get_live_status_codes())
    
    for theme, valid_tokens in theme_tokens_map.items():
        uspto_matches = []
        uspto_details = {}
        tro_matches = []
        tro_details = {}
        
        high_risk_words = []
        medium_risk_words = []
        low_risk_words = []
        word_risk_map = {}
        
        for token in valid_tokens:
            token_lower = token.lower()
            token_upper = token.upper()
            
            # 收集匹配信息用于前端显示
            if token_lower in uspto_word_lower_map_global:
                original_word = uspto_word_lower_map_global[token_lower]
                if original_word not in uspto_details:
                    uspto_matches.append(original_word)
                    uspto_details[original_word] = uspto_details_global[original_word]
            
            if token_lower in tro_risk_map_global:
                # 查找原始大小写形式（从valid_tokens或数据库中恢复）
                # 这里简化处理，直接用token
                tro_matches.append(token)
                tro_details[token] = tro_risk_map_global[token_lower]

            # 风险判断逻辑
            # 高风险 (TRO)
            if token_lower in tro_risk_map_global:
                name_type = tro_risk_map_global[token_lower]
                original_word = uspto_word_lower_map_global.get(token_lower, token_upper)
                status_codes = word_status_codes_global.get(original_word, set())
                
                if name_type in HIGH_RISK_NAME_TYPES:
                    intl_classes = list(word_intl_classes_global.get(original_word, set()))
                    has_special_class = any(cls in SPECIAL_INTL_CLASSES for cls in intl_classes)
                    word_risk_map[original_word] = ['high', list(status_codes), intl_classes, has_special_class]
                    high_risk_words.append(original_word)
                    continue

            # 中风险 (美标)
            if token_lower in uspto_word_lower_map_global:
                original_word = uspto_word_lower_map_global[token_lower]
                status_codes = word_status_codes_global.get(original_word, set())
                intl_classes = list(word_intl_classes_global.get(original_word, set()))
                has_special_class = any(cls in SPECIAL_INTL_CLASSES for cls in intl_classes)

                if status_codes.intersection(all_live):
                    word_risk_map[original_word] = ['medium', list(status_codes), intl_classes, has_special_class]
                    medium_risk_words.append(original_word)
                else:
                    word_risk_map[original_word] = ['low', list(status_codes), intl_classes, has_special_class]
                    low_risk_words.append(original_word)
            else:
                # 低风险
                word_risk_map[token] = ['low', '', [], False]
                low_risk_words.append(token)

        # 整体风险等级
        if high_risk_words:
            theme_risk_level, theme_risk_text = 'high', '高风险'
        elif medium_risk_words:
            theme_risk_level, theme_risk_text = 'medium', '中风险'
        else:
            theme_risk_level, theme_risk_text = 'low', '低风险'

        result = {
            'query': theme, 'tokens': words_split(theme), # 返回原始tokens
            'uspto_keywords': uspto_matches, 'uspto_details': uspto_details,
            'tro_keywords': tro_matches, 'tro_details': tro_details,
            'word_risk_map': word_risk_map,
            'high_risk_words': high_risk_words,
            'medium_risk_words': medium_risk_words,
            'low_risk_words': low_risk_words,
            'theme_risk_level': theme_risk_level,
            'theme_risk_text': theme_risk_text,
        }
        
        # 存入缓存
        cache_key = f'risk_analysis:{hash(theme)}'
        cache.set(cache_key, result, 3600)
        results[theme] = result

    return results


def analyze_theme_trend(theme):
    """
    分析主题词的侵权风险趋势。

    Args:
        theme (str): 需要分析的主题词或短语。

    Returns:
        dict: 包含分析结果的字典，主要字段包括：
            - theme_risk_level (str): 风险等级 ('high', 'medium', 'low')
            - theme_risk_text (str): 风险描述 ('高风险', '中风险', '低风险')
            - word_risk_map (dict): 每个分词的详细风险数据
            - high_risk_words (list): 高风险词列表
            - medium_risk_words (list): 中风险词列表
            - low_risk_words (list): 低风险词列表
            - uspto_keywords (list): 命中的美标关键词
            - tro_keywords (list): 命中的TRO关键词
    """
    query = theme.strip()
    # 1. 分词处理
    tokens = words_split(query)
    valid_tokens = [t for t in tokens if not should_skip_word(t)]

    if not valid_tokens:
        return {
            'query': query, 'tokens': tokens,
            'uspto_keywords': [], 'uspto_details': {},
            'tro_keywords': [], 'tro_details': {},
            'word_risk_map': {},
            'high_risk_words': [], 'medium_risk_words': [], 'low_risk_words': [],
            'theme_risk_level': 'low', 'theme_risk_text': '低风险',
        }

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
    word_intl_classes = defaultdict(set)  # 收集每个词的国际分类
    uspto_word_lower_map = {}  # 小写映射用于后续匹配

    for record in trademark_records:
        word = record['word_mark']  # 这是大写的
        word_lower = word.lower()

        if word not in uspto_details:
            uspto_matches.append(word)
            uspto_details[word] = []
        uspto_details[word].append({
            'serial_number': record['serial_number'],
            'intl_class': record['intl_class'] or 'N/A',
            'status_code': record['status_code']
        })
        if record['status_code']:
            try:
                word_status_codes[word].add(int(record['status_code']))
            except (ValueError, TypeError):
                pass

        # 收集国际分类
        if record['intl_class']:
            word_intl_classes[word].add(record['intl_class'])

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
            # 获取状态码
            status_codes = word_status_codes.get(original_word, set())

            if name_type in HIGH_RISK_NAME_TYPES:
                intl_classes = list(word_intl_classes.get(original_word, set()))
                has_special_class = any(cls in SPECIAL_INTL_CLASSES for cls in intl_classes)
                word_risk_map[original_word] = ['high', list(status_codes), intl_classes, has_special_class]
                high_risk_words.append(original_word)
                continue
#peteryzy
        # 中风险判断（美标网状态码）
        if token_lower in uspto_word_lower_map:
            original_word = uspto_word_lower_map[token_lower]
            status_codes = word_status_codes.get(original_word, set())
            intl_classes = list(word_intl_classes.get(original_word, set()))
            has_special_class = any(cls in SPECIAL_INTL_CLASSES for cls in intl_classes)

            if status_codes.intersection(all_live):
                word_risk_map[original_word] = ['medium', list(status_codes), intl_classes, has_special_class]
                medium_risk_words.append(original_word)
            else:
                word_risk_map[original_word] = ['low', list(status_codes), intl_classes, has_special_class]
                low_risk_words.append(original_word)
        else:
            # 不在美标网中，低风险
            word_risk_map[token] = ['low', '', [], False]
            low_risk_words.append(token)

    # 5. 整体风险等级
    if high_risk_words:
        theme_risk_level, theme_risk_text = 'high', '高风险'
    elif medium_risk_words:
        theme_risk_level, theme_risk_text = 'medium', '中风险'
    else:
        theme_risk_level, theme_risk_text = 'low', '低风险'

    return {
        'query': query, 'tokens': tokens,
        'uspto_keywords': uspto_matches, 'uspto_details': uspto_details,
        'tro_keywords': tro_matches, 'tro_details': tro_details,
        'word_risk_map': word_risk_map,
        'high_risk_words': high_risk_words,
        'medium_risk_words': medium_risk_words,
        'low_risk_words': low_risk_words,
        'theme_risk_level': theme_risk_level,
        'theme_risk_text': theme_risk_text,
    }


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