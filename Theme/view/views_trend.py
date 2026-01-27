from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.http import require_POST
import nltk
import re
from collections import defaultdict
from nltk.stem import PorterStemmer
from nltk.corpus import stopwords
from theme.models import *
from nltk.tokenize import TweetTokenizer
from django.contrib.auth.decorators import login_required

@login_required
def trend_page(request):
    return render(request, 'trend.html', {'active_nav': 'theme_products'})



@require_POST
@login_required
def trend_search(request):
    query = request.POST.get('trendQueryInput', '').strip()
    if not query:
        print('[trend_search] empty query')
        return JsonResponse({'error': '请输入搜索关键词'}, status=400)

    # 1. 分词处理
    tokens = words_split(query)

    # 2. 批量查询美标网商标
    from django.db.models import Q
    uspto_matches = []

    if tokens:
        # 构建批量查询条件（完全匹配）
        q_objects = Q()
        for token in tokens:
            if token.strip():
                q_objects |= Q(word_mark__iexact=token)

        # 执行查询（完全匹配，获取完整的商标信息）
        if q_objects:
            trademarks = TrademarkInfo.objects.filter(q_objects).values(
                'word_mark', 'serial_number', 'intl_class'
            ).distinct()

            # 构建匹配词列表
            uspto_matches = list(set([t['word_mark'] for t in trademarks]))

            # 构建详细信息字典：{word_mark: [{serial_number, intl_class}, ...]}
            uspto_details = {}
            for t in trademarks:
                word_mark = t['word_mark']
                if word_mark not in uspto_details:
                    uspto_details[word_mark] = []
                uspto_details[word_mark].append({
                    'serial_number': t['serial_number'],
                    'intl_class': t['intl_class'] or 'N/A'
                })
        else:
            uspto_matches = []
            uspto_details = {}
    else:
        uspto_matches = []
        uspto_details = {}

    # 3. 查询TroTable侵权词库（完全匹配）
    tro_matches = []

    if tokens:
        # 构建批量查询条件（完全匹配）
        tro_q_objects = Q()
        for token in tokens:
            if token.strip():
                tro_q_objects |= Q(theme_name__iexact=token)

        # 执行查询（完全匹配）
        if tro_q_objects:
            tro_records = TroTable.objects.filter(tro_q_objects).values(
                'theme_name', 'name_type'
            ).distinct()

            # 构建匹配词列表（去重）
            tro_matches = list(set([t['theme_name'] for t in tro_records]))

            # 构建详细信息字典：{theme_name: name_type}
            tro_details = {}
            for t in tro_records:
                theme_name = t['theme_name']
                if theme_name not in tro_details:
                    tro_details[theme_name] = t['name_type']
        else:
            tro_matches = []
            tro_details = {}
    else:
        tro_matches = []
        tro_details = {}

    # 4. 构建返回数据
    data = {
        'query': query,
        'tokens': tokens,
        'uspto_keywords': uspto_matches,
        'uspto_details': uspto_details,
        'tro_keywords': tro_matches,
        'tro_details': tro_details,  # NEW: Add TroTable name_type details
    }
    print('[trend_search] response =', data)
    return JsonResponse(data)


def words_split(theme):
    tokenizer = TweetTokenizer()
    return tokenizer.tokenize(theme or '')


@login_required
def words_split_api(request):
    theme = (request.POST.get('theme') or request.GET.get('theme') or '').strip()
    if not theme:
        return JsonResponse({'error': '请输入 theme'}, status=400)

    tokens = words_split(theme)
    data = {'theme': theme, 'tokens': tokens}
    print('[words_split_api] response =', data)
    return JsonResponse(data)