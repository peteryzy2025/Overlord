"""
ABA 数据管理视图
"""
import json
import re
import threading
import uuid
from collections import defaultdict
from datetime import datetime, timedelta
from functools import wraps

from django.core.cache import cache
from django.db.models import Case, Count, DecimalField, ExpressionWrapper, F, FloatField, IntegerField, Max, OuterRef, Q, Subquery, Value, When
from django.db.models.functions import Cast, Coalesce
from django.db import close_old_connections, transaction
from django.http import JsonResponse
from django.shortcuts import render,redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods

from aba.models import AbaNoiseWord, AbaReportWeek, SearchTerm, SearchTermMetric


CUSTOM_DENOISING_CACHE_PREFIX = 'aba:custom-denoising:'
CUSTOM_DENOISING_CACHE_TTL = 60 * 60
CUSTOM_DENOISING_SCAN_BATCH_SIZE = 200
CUSTOM_DENOISING_UPDATE_BATCH_SIZE = 500
ADD_NOISE_WORDS_CACHE_PREFIX = 'aba:add-noise-words:'
ABA_TOTAL_COUNT_CACHE_PREFIX = 'aba:total-count:'
TERM_ID_LIST_CACHE_PREFIX = 'aba:term-ids:'
TERM_ID_LIST_CACHE_TTL = 180  # 3分钟，翻页缓存
ABA_METRIC_INDEX_CACHE_PREFIX = 'aba:metric-index:'
HOT_WORD_PICKUP_RANK_THRESHOLD = 30000
ABA_ACCESS_CODES = {555, 8}

def has_perm_code(user, code):
    """检查用户是否有特定权限码"""
    if not user or not user.is_authenticated:
        return False
    # code字段是IntegerField，尝试转为整数比较
    try:
        code_int = int(code)
        return user.permission_configs.filter(code=code_int).exists()
    except (ValueError, TypeError):
        return False


def can_access_aba(user):
    """ABA 页面权限：仅 555 或 8 可访问。"""
    if not user or not user.is_authenticated:
        return False

    user_codes = set(user.permission_configs.values_list('code', flat=True))
    return bool(user_codes & ABA_ACCESS_CODES)


def aba_permission_required(view_func):
    """统一保护 ABA 页面与 API。"""
    @login_required
    @wraps(view_func)
    def wrapped_view(request, *args, **kwargs):
        if can_access_aba(request.user):
            return view_func(request, *args, **kwargs)

        if request.path.startswith('/api/') or request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({
                'success': False,
                'message': '无权访问 ABA 页面',
            }, status=403)

        return redirect('general:main')

    return wrapped_view


@aba_permission_required
def aba_data_page(request):
    """
    ABA 数据管理页面
    """
    return render(request, 'aba/aba_data.html', {'active_page': 'aba_data'})


@aba_permission_required
def aba_noise_words_page(request):
    """
    ABA 去噪词表页面
    """
    return render(request, 'aba/aba_noiseword.html', {
        'active_page': 'aba_noise_words',
        'active_nav': 'aba_noise_words',
    })


def _normalize_search_term_ids(raw_ids):
    """
    将前端传入的 ID 列表标准化为去重后的整数列表
    """
    if not isinstance(raw_ids, list):
        return []

    normalized_ids = []
    seen = set()
    for raw_id in raw_ids:
        try:
            search_term_id = int(raw_id)
        except (TypeError, ValueError):
            continue

        if search_term_id in seen:
            continue

        seen.add(search_term_id)
        normalized_ids.append(search_term_id)

    return normalized_ids


def _normalize_boolean_value(raw_value, default=False):
    """
    兼容 JSON 布尔值与常见字符串布尔值，避免 bool("false") 被误判为 True
    """
    if isinstance(raw_value, bool):
        return raw_value

    if isinstance(raw_value, str):
        normalized = raw_value.strip().lower()
        if normalized in {'true', '1', 'yes', 'y', 'on'}:
            return True
        if normalized in {'false', '0', 'no', 'n', 'off', ''}:
            return False

    if raw_value is None:
        return default

    return bool(raw_value)


def _build_empty_aba_response(page, page_size, needs_week=False):
    return {
        'success': True,
        'data': [],
        'page': page,
        'page_size': page_size,
        'total': 0,
        'total_pages': 0,
        'has_prev': page > 1,
        'has_next': False,
        'pagination_mode': 'full',
        'needs_week': needs_week,
    }


def _build_empty_new_words_response(page, page_size, needs_week=False):
    response = _build_empty_aba_response(page, page_size, needs_week=needs_week)
    response['window_start'] = ''
    response['window_end'] = ''
    return response


def _build_empty_noise_words_response(page, page_size):
    return {
        'success': True,
        'data': {
            'list': [],
            'page': page,
            'page_size': page_size,
            'has_prev': page > 1,
            'has_next': False,
            'pagination_mode': 'simple',
        }
    }


def _normalize_custom_denoising_keywords(raw_text):
    """
    将多行文本标准化为去重后的关键词列表（按大小写不敏感去重）
    """
    if not isinstance(raw_text, str):
        return []

    normalized_keywords = []
    seen = set()

    for line in raw_text.splitlines():
        keyword = line.strip()
        if not keyword:
            continue

        dedupe_key = keyword.casefold()
        if dedupe_key in seen:
            continue

        seen.add(dedupe_key)
        normalized_keywords.append(keyword)

    return normalized_keywords


def _normalize_noise_words(raw_words):
    if not isinstance(raw_words, (list, tuple, set)):
        return []

    normalized_words = []
    seen = set()

    for raw_word in raw_words:
        if not isinstance(raw_word, str):
            continue

        word = raw_word.strip()
        dedupe_key = word.casefold()
        if not word or dedupe_key in seen:
            continue

        seen.add(dedupe_key)
        normalized_words.append(word)

    return normalized_words


def _create_noise_words(words):
    normalized_words = _normalize_noise_words(words)
    if not normalized_words:
        return [], 0

    noise_words = AbaNoiseWord.objects.using('aba_db')
    existing_query = Q()
    for word in normalized_words:
        existing_query |= Q(word__iexact=word)

    existing_words = set(
        noise_words.filter(existing_query).values_list('word', flat=True)
    )
    existing_keys = {word.casefold() for word in existing_words}
    words_to_create = [
        AbaNoiseWord(word=word)
        for word in normalized_words
        if word.casefold() not in existing_keys
    ]

    if words_to_create:
        noise_words.bulk_create(words_to_create, ignore_conflicts=True)

    return normalized_words, len(words_to_create)


def _set_search_terms_denoising(search_term_ids, denoising):
    normalized_ids = _normalize_search_term_ids(search_term_ids)
    if not normalized_ids:
        return 0, []

    queryset = SearchTerm.objects.using('aba_db').filter(id__in=normalized_ids)
    words = list(queryset.values_list('term', flat=True))
    if not words:
        return 0, []

    updated_count = queryset.update(denoising=denoising)
    
    # 去噪操作后，递增缓存版本号，使旧缓存失效
    # 使用版本号机制避免逐个删除缓存 key
    if updated_count > 0:
        _increment_term_ids_cache_version()
    
    return updated_count, words


def _get_term_ids_cache_version():
    """获取当前缓存版本号"""
    version = cache.get(f'{TERM_ID_LIST_CACHE_PREFIX}version')
    return version or 0


def _increment_term_ids_cache_version():
    """递增缓存版本号（去噪操作后调用）"""
    try:
        cache.incr(f'{TERM_ID_LIST_CACHE_PREFIX}version')
    except ValueError:
        # 版本号不存在，初始化为 1
        cache.set(f'{TERM_ID_LIST_CACHE_PREFIX}version', 1, 3600 * 24)


def _delete_noise_word(word):
    normalized_words = _normalize_noise_words([word])
    if not normalized_words:
        return 0

    normalized_word = normalized_words[0]
    deleted_count, _ = AbaNoiseWord.objects.using('aba_db').filter(word__iexact=normalized_word).delete()
    return deleted_count


def _normalize_custom_denoising_match_text(raw_text):
    if not isinstance(raw_text, str):
        return ''

    return re.sub(r'\s+', ' ', raw_text.casefold()).strip()


def _build_whole_word_regex(raw_text):
    normalized_text = _normalize_custom_denoising_match_text(raw_text)
    if not normalized_text:
        return ''

    escaped_text = re.escape(normalized_text)
    return rf'(^|[^0-9a-z]){escaped_text}([^0-9a-z]|$)'


def _normalize_category_value(raw_category):
    if not isinstance(raw_category, str):
        return ''

    return raw_category.strip().casefold()


def _build_custom_denoising_patterns(keywords):
    patterns = []

    for keyword in keywords:
        pattern_text = _build_whole_word_regex(keyword)
        if not pattern_text:
            continue

        patterns.append(re.compile(pattern_text))

    return patterns


def _matches_custom_denoising_term(term, keyword_patterns):
    normalized_term = _normalize_custom_denoising_match_text(term)
    if not normalized_term:
        return False

    return any(pattern.search(normalized_term) for pattern in keyword_patterns)


def _apply_category_filter(queryset, category, category_field=None):
    normalized_category = _normalize_category_value(category)
    if not normalized_category:
        return queryset

    if category_field:
        return queryset.filter(**{category_field: normalized_category})

    return queryset


def _build_filtered_term_queryset(category='', search_term='', noise_status='all', search_mode='0'):
    """
    在 SearchTerm 表上构建过滤 queryset。

    品类筛选仅依赖 SearchTerm.category 字段。
    """
    category = _normalize_category_value(category)
    qs = SearchTerm.objects.using('aba_db').all()

    if category:
        qs = qs.filter(category=category)

    if search_term:
        if search_mode == '0':
            qs = qs.filter(term__iexact=search_term)
        elif search_mode == '2':
            keywords = search_term.strip().split()
            for keyword in keywords:
                qs = qs.filter(term__iregex=rf'\y{re.escape(keyword)}\y')
        else:
            qs = qs.filter(term__icontains=search_term)

    if noise_status == 'noise':
        qs = qs.filter(denoising=True)
    elif noise_status == 'denoised':
        qs = qs.filter(denoising=False)

    return qs


def _get_filtered_term_ids(category='', search_term='', noise_status='all', search_mode='0'):
    """
    在 SearchTerm 表上过滤，返回匹配的 ID 列表。
    """
    qs = _build_filtered_term_queryset(
        category=category,
        search_term=search_term,
        noise_status=noise_status,
        search_mode=search_mode,
    )
    return list(qs.values_list('id', flat=True))


def _get_term_ids_cache_key(category, search_term, noise_status, search_mode):
    """构建缓存 key（包含版本号，去噪后自动失效）"""
    version = _get_term_ids_cache_version()
    normalized_category = _normalize_category_value(category)
    return f"{TERM_ID_LIST_CACHE_PREFIX}{version}:{normalized_category}:{noise_status}:{search_term}:{search_mode}"


def _get_metric_index_cache_key(week, category, search_term, noise_status, word_filter, search_mode):
    version = _get_term_ids_cache_version()
    normalized_category = _normalize_category_value(category)
    return (
        f"{ABA_METRIC_INDEX_CACHE_PREFIX}{version}:{week}:{normalized_category}:"
        f"{noise_status}:{word_filter}:{search_term}:{search_mode}"
    )


def _get_filtered_term_ids_with_cache(category='', search_term='', noise_status='all', search_mode='0'):
    """
    带缓存的版本：缓存符合条件的搜索词 ID 列表
    翻页时不需要重新执行 900万条的正则过滤
    去噪操作后缓存自动失效（版本号机制）
    """
    cache_key = _get_term_ids_cache_key(category, search_term, noise_status, search_mode)
    
    # 尝试从缓存读取
    cached_ids = cache.get(cache_key)
    if cached_ids is not None:
        return cached_ids
    
    # 缓存未命中，执行查询
    ids = _get_filtered_term_ids(category, search_term, noise_status, search_mode)
    
    # 存入缓存（即使为空列表也缓存，防止缓存穿透）
    cache.set(cache_key, ids, TERM_ID_LIST_CACHE_TTL)
    
    return ids


def _get_filtered_metric_index_with_cache(
    *,
    queryset,
    week,
    category='',
    search_term='',
    noise_status='all',
    word_filter='all',
    search_mode='0',
):
    cache_key = _get_metric_index_cache_key(
        week,
        category,
        search_term,
        noise_status,
        word_filter,
        search_mode,
    )
    cached_metric_ids = cache.get(cache_key)
    if cached_metric_ids is not None:
        return cached_metric_ids

    metric_ids = list(
        queryset.order_by('search_frequency_rank', 'id').values_list('id', flat=True)
    )
    cache.set(cache_key, metric_ids, TERM_ID_LIST_CACHE_TTL)
    return metric_ids


def _get_new_words_window_end(week_value):
    if not week_value:
        return None

    try:
        return datetime.strptime(week_value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _parse_week_value(week_value):
    if not week_value:
        return None

    try:
        return datetime.strptime(week_value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _get_new_words_window_start(window_end, weeks=13):
    if not window_end:
        return None

    return window_end - timedelta(days=(weeks - 1) * 7)


def _build_aba_total_count_progress(
    *,
    status='pending',
    total=0,
    total_pages=0,
    page_size=20,
    message='任务已创建，准备开始计算',
    error='',
):
    return {
        'status': status,
        'total': total,
        'total_pages': total_pages,
        'page_size': page_size,
        'message': message,
        'error': error,
    }


def _aba_total_count_cache_key(task_id):
    return f'{ABA_TOTAL_COUNT_CACHE_PREFIX}{task_id}'


def _get_aba_total_count_progress(task_id):
    return cache.get(_aba_total_count_cache_key(task_id))


def _set_aba_total_count_progress(task_id, **kwargs):
    progress = _get_aba_total_count_progress(task_id) or _build_aba_total_count_progress()
    progress.update(kwargs)
    cache.set(_aba_total_count_cache_key(task_id), progress, CUSTOM_DENOISING_CACHE_TTL)
    return progress


def _decimal_zero():
    return Value(0, output_field=DecimalField(max_digits=8, decimal_places=4))


def _sum_metric_share_expression(field_names):
    expression = _decimal_zero()
    for field_name in field_names:
        expression = expression + Coalesce(F(field_name), _decimal_zero())

    return ExpressionWrapper(
        expression,
        output_field=DecimalField(max_digits=8, decimal_places=4),
    )


def _rank_growth_percent_expression():
    previous_rank = Cast(F('last_week_rank'), FloatField())
    current_rank = Cast(F('search_frequency_rank'), FloatField())
    growth_expression = ExpressionWrapper(
        (previous_rank - current_rank) * Value(100.0) / previous_rank,
        output_field=FloatField(),
    )

    return Case(
        When(
            last_week_rank__gt=0,
            search_frequency_rank__gt=0,
            then=growth_expression,
        ),
        default=Value(None, output_field=FloatField()),
        output_field=FloatField(),
    )


def _calculate_rank_growth_percent(current_rank, previous_rank):
    if not current_rank or not previous_rank or previous_rank <= 0:
        return None

    return ((previous_rank - current_rank) * 100.0) / previous_rank


def _is_continuous_growth(rank_points):
    ordered_ranks = [rank for rank in rank_points if isinstance(rank, int) and rank > 0]
    if len(ordered_ranks) < 4:
        return False

    return all(current < previous for current, previous in zip(ordered_ranks[1:], ordered_ranks[:-1]))


def _get_hot_word_categories(metric, trend_rows):
    categories = []
    growth_percent = _calculate_rank_growth_percent(
        getattr(metric, 'search_frequency_rank', None),
        getattr(metric, 'last_week_rank', None),
    )
    total_click_share = (
        (getattr(metric, 'asin_1_click_share', None) or 0) +
        (getattr(metric, 'asin_2_click_share', None) or 0) +
        (getattr(metric, 'asin_3_click_share', None) or 0)
    ) * 100
    total_conversion_share = (
        (getattr(metric, 'asin_1_conversion_share', None) or 0) +
        (getattr(metric, 'asin_2_conversion_share', None) or 0) +
        (getattr(metric, 'asin_3_conversion_share', None) or 0)
    ) * 100

    recent_trend = sorted(trend_rows, key=lambda row: row['week'])[-4:]
    recent_ranks = [row['rank'] for row in recent_trend]

    if _is_continuous_growth(recent_ranks):
        categories.append('持续增长词')
    if growth_percent is not None and growth_percent > 70:
        categories.append('爆发词')
    if growth_percent is not None and 50 <= growth_percent <= 70:
        categories.append('飙升词')
    if growth_percent is not None and growth_percent >= 10:
        categories.append('潜力词')
    if total_click_share > 0 and total_conversion_share == 0:
        categories.append('黄金词')
    if total_click_share >= 70:
        categories.append('竞争词')
    if getattr(metric, 'search_frequency_rank', 0) >= HOT_WORD_PICKUP_RANK_THRESHOLD and total_conversion_share < 30:
        categories.append('捡漏词')

    return categories


def _apply_hot_word_filter(
    queryset,
    week_date,
    word_filter,
    *,
    search_term='',
    search_mode='0',
    category='',
    noise_status='all',
):
    category = _normalize_category_value(category)
    if not word_filter or word_filter == 'all':
        return queryset

    if word_filter in {'golden', 'competitive', 'pickup'}:
        queryset = queryset.annotate(
            total_click_share_ratio=_sum_metric_share_expression([
                'asin_1_click_share',
                'asin_2_click_share',
                'asin_3_click_share',
            ]),
            total_conversion_share_ratio=_sum_metric_share_expression([
                'asin_1_conversion_share',
                'asin_2_conversion_share',
                'asin_3_conversion_share',
            ]),
        )

    if word_filter in {'burst', 'surging', 'potential'}:
        queryset = queryset.annotate(rank_growth_percent=_rank_growth_percent_expression())

    if word_filter == 'continuous_growth':
        previous_week = week_date - timedelta(days=7)
        previous_two_weeks = week_date - timedelta(days=14)
        previous_three_weeks = week_date - timedelta(days=21)
        history_queryset = SearchTermMetric.objects.using('aba_db').filter(
            report_week__in=[week_date, previous_week, previous_two_weeks, previous_three_weeks],
        )
        history_queryset = _apply_search_term_filters(history_queryset, search_term, search_mode)
        if category:
            history_queryset = _apply_category_filter(
                history_queryset,
                category,
                category_field='search_term__category',
            )
        if noise_status == 'noise':
            history_queryset = history_queryset.filter(search_term__denoising=True)
        elif noise_status == 'denoised':
            history_queryset = history_queryset.filter(search_term__denoising=False)

        matching_term_ids = history_queryset.values('search_term_id').annotate(
            week_count=Count('report_week', distinct=True),
            current_rank=Max(Case(When(report_week=week_date, then=F('search_frequency_rank')), output_field=IntegerField())),
            previous_week_rank=Max(Case(When(report_week=previous_week, then=F('search_frequency_rank')), output_field=IntegerField())),
            previous_two_week_rank=Max(Case(When(report_week=previous_two_weeks, then=F('search_frequency_rank')), output_field=IntegerField())),
            previous_three_week_rank=Max(Case(When(report_week=previous_three_weeks, then=F('search_frequency_rank')), output_field=IntegerField())),
        ).filter(
            week_count=4,
            current_rank__isnull=False,
            previous_week_rank__isnull=False,
            previous_two_week_rank__isnull=False,
            previous_three_week_rank__isnull=False,
            current_rank__lt=F('previous_week_rank'),
            previous_week_rank__lt=F('previous_two_week_rank'),
            previous_two_week_rank__lt=F('previous_three_week_rank'),
        )
        queryset = queryset.filter(search_term_id__in=Subquery(matching_term_ids.values('search_term_id')))
    elif word_filter == 'burst':
        queryset = queryset.filter(rank_growth_percent__gt=70)
    elif word_filter == 'surging':
        queryset = queryset.filter(rank_growth_percent__gte=50, rank_growth_percent__lte=70)
    elif word_filter == 'potential':
        queryset = queryset.filter(rank_growth_percent__gte=10)
    elif word_filter == 'golden':
        queryset = queryset.filter(
            total_click_share_ratio__gt=0,
            total_conversion_share_ratio=0,
        )
    elif word_filter == 'competitive':
        queryset = queryset.filter(total_click_share_ratio__gte=0.7)
    elif word_filter == 'pickup':
        queryset = queryset.filter(
            search_frequency_rank__gte=HOT_WORD_PICKUP_RANK_THRESHOLD,
            total_conversion_share_ratio__lt=0.3,
        )

    return queryset


def _apply_search_term_filters(queryset, search_term, search_mode, term_field='search_term__term'):
    if not search_term:
        return queryset

    if search_mode == '0':
        return queryset.filter(**{f'{term_field}__iexact': search_term})

    if search_mode == '2':
        keywords = search_term.strip().split()
        for keyword in keywords:
            queryset = queryset.filter(**{f'{term_field}__iregex': rf'\y{keyword}\y'})
        return queryset

    return queryset.filter(**{f'{term_field}__icontains': search_term})


def _serialize_metric_asin(metric, index):
    code = getattr(metric, f'asin_{index}_code')
    title = getattr(metric, f'asin_{index}_title')
    click_share = getattr(metric, f'asin_{index}_click_share')
    conversion_share = getattr(metric, f'asin_{index}_conversion_share')

    if not code:
        return {
            'code': '',
            'title': '',
            'click_share': None,
            'conversion_share': None,
        }

    return {
        'code': code,
        'title': title,
        'click_share': round((click_share or 0) * 100, 2),
        'conversion_share': round((conversion_share or 0) * 100, 2),
    }


def _empty_asin_payload():
    return {
        'code': '',
        'title': '',
        'click_share': None,
        'conversion_share': None,
    }


def _serialize_top_share(metric, field_names):
    return round(sum((getattr(metric, field_name) or 0) for field_name in field_names) * 100, 2)


def _build_new_words_row(search_term, term_stats, metrics):
    metrics_by_week = {metric.report_week: metric for metric in metrics}
    first_seen = search_term.first_seen or term_stats['first_report_week']
    latest_seen = term_stats['latest_report_week']
    first_metric = metrics_by_week.get(first_seen)
    latest_metric = metrics_by_week.get(latest_seen)

    row_id = latest_metric.id if latest_metric else first_metric.id if first_metric else search_term.id
    latest_rank = latest_metric.search_frequency_rank if latest_metric else None

    return {
        'id': row_id,
        'search_term_id': search_term.id,
        'search_term': search_term.term,
        'search_term_translation_cn': search_term.translation_cn,
        'denoising': search_term.denoising,
        'first_seen': first_seen.strftime('%Y-%m-%d') if first_seen else '',
        'first_search_rank': first_metric.search_frequency_rank if first_metric else None,
        'is_first_seen_in_window': bool(
            first_seen and term_stats['window_start'] <= first_seen <= term_stats['window_end']
        ),
        'appearance_count': term_stats['appearance_count'],
        'trend': [
            {
                'week': metric.report_week.strftime('%Y-%m-%d'),
                'rank': metric.search_frequency_rank,
            }
            for metric in metrics
        ],
        'latest_seen': latest_seen.strftime('%Y-%m-%d') if latest_seen else '',
        'latest_search_rank': latest_rank,
        'total_click_share': _serialize_top_share(
            latest_metric,
            ['asin_1_click_share', 'asin_2_click_share', 'asin_3_click_share'],
        ) if latest_metric else 0,
        'total_conversion_share': _serialize_top_share(
            latest_metric,
            ['asin_1_conversion_share', 'asin_2_conversion_share', 'asin_3_conversion_share'],
        ) if latest_metric else 0,
        'asin_1': _serialize_metric_asin(latest_metric, 1) if latest_metric else _empty_asin_payload(),
        'asin_2': _serialize_metric_asin(latest_metric, 2) if latest_metric else _empty_asin_payload(),
        'asin_3': _serialize_metric_asin(latest_metric, 3) if latest_metric else _empty_asin_payload(),
    }


def _custom_denoising_cache_key(task_id):
    return f'{CUSTOM_DENOISING_CACHE_PREFIX}{task_id}'


def _add_noise_words_cache_key(task_id):
    return f'{ADD_NOISE_WORDS_CACHE_PREFIX}{task_id}'


def _build_custom_denoising_progress(
    *,
    status='pending',
    processed_count=0,
    matched_count=0,
    updated_count=0,
    total_terms=0,
    keyword_count=0,
    message='任务已创建，准备开始处理',
    error='',
):
    return {
        'status': status,
        'processed_count': processed_count,
        'matched_count': matched_count,
        'updated_count': updated_count,
        'total_terms': total_terms,
        'keyword_count': keyword_count,
        'message': message,
        'error': error,
    }


def _build_add_noise_words_progress(
    *,
    status='pending',
    processed_count=0,
    matched_count=0,
    updated_count=0,
    total_terms=0,
    keyword_count=0,
    inserted_word_count=0,
    message='任务已创建，准备开始处理',
    error='',
):
    return {
        'status': status,
        'processed_count': processed_count,
        'matched_count': matched_count,
        'updated_count': updated_count,
        'total_terms': total_terms,
        'keyword_count': keyword_count,
        'inserted_word_count': inserted_word_count,
        'message': message,
        'error': error,
    }


def _get_custom_denoising_progress(task_id):
    return cache.get(_custom_denoising_cache_key(task_id))


def _get_add_noise_words_progress(task_id):
    return cache.get(_add_noise_words_cache_key(task_id))


def _set_custom_denoising_progress(task_id, **kwargs):
    progress = _get_custom_denoising_progress(task_id) or _build_custom_denoising_progress()
    progress.update(kwargs)
    cache.set(_custom_denoising_cache_key(task_id), progress, CUSTOM_DENOISING_CACHE_TTL)
    return progress


def _set_add_noise_words_progress(task_id, **kwargs):
    progress = _get_add_noise_words_progress(task_id) or _build_add_noise_words_progress()
    progress.update(kwargs)
    cache.set(_add_noise_words_cache_key(task_id), progress, CUSTOM_DENOISING_CACHE_TTL)
    return progress


def _flush_custom_denoising_updates(search_term_ids):
    if not search_term_ids:
        return 0

    updated_count, _ = _set_search_terms_denoising(search_term_ids, True)
    return updated_count


def _run_custom_denoising_task(task_id, keywords, total_terms):
    keyword_patterns = _build_custom_denoising_patterns(keywords)
    processed_count = 0
    matched_count = 0
    updated_count = 0
    pending_update_ids = []

    try:
        close_old_connections()
        _set_custom_denoising_progress(
            task_id,
            status='running',
            processed_count=0,
            matched_count=0,
            updated_count=0,
            total_terms=total_terms,
            keyword_count=len(keywords),
            message='目前已处理 0 条',
            error='',
        )

        search_terms = SearchTerm.objects.using('aba_db').order_by('id').values_list('id', 'term')
        for search_term_id, term in search_terms.iterator(chunk_size=CUSTOM_DENOISING_SCAN_BATCH_SIZE):
            processed_count += 1

            if _matches_custom_denoising_term(term, keyword_patterns):
                matched_count += 1
                pending_update_ids.append(search_term_id)

            if len(pending_update_ids) >= CUSTOM_DENOISING_UPDATE_BATCH_SIZE:
                updated_count += _flush_custom_denoising_updates(pending_update_ids)
                pending_update_ids = []

            if processed_count % CUSTOM_DENOISING_SCAN_BATCH_SIZE == 0:
                _set_custom_denoising_progress(
                    task_id,
                    status='running',
                    processed_count=processed_count,
                    matched_count=matched_count,
                    updated_count=updated_count,
                    total_terms=total_terms,
                    keyword_count=len(keywords),
                    message=f'目前已处理 {processed_count} 条',
                    error='',
                )

        if pending_update_ids:
            updated_count += _flush_custom_denoising_updates(pending_update_ids)

        _set_custom_denoising_progress(
            task_id,
            status='success',
            processed_count=processed_count,
            matched_count=matched_count,
            updated_count=updated_count,
            total_terms=total_terms,
            keyword_count=len(keywords),
            message=f'处理完成，已处理 {processed_count} 条，命中 {matched_count} 条，更新 {updated_count} 条',
            error='',
        )
    except Exception as exc:
        _set_custom_denoising_progress(
            task_id,
            status='error',
            processed_count=processed_count,
            matched_count=matched_count,
            updated_count=updated_count,
            total_terms=total_terms,
            keyword_count=len(keywords),
            message=f'自定义去噪失败：{exc}',
            error=str(exc),
        )
    finally:
        close_old_connections()


def _launch_custom_denoising_task(keywords):
    normalized_keywords, _ = _create_noise_words(keywords)
    task_id = uuid.uuid4().hex
    total_terms = SearchTerm.objects.using('aba_db').count()
    initial_progress = _build_custom_denoising_progress(
        status='pending',
        processed_count=0,
        matched_count=0,
        updated_count=0,
        total_terms=total_terms,
        keyword_count=len(normalized_keywords),
        message='原始输入已记录，准备开始处理',
        error='',
    )
    cache.set(_custom_denoising_cache_key(task_id), initial_progress, CUSTOM_DENOISING_CACHE_TTL)

    worker = threading.Thread(
        target=_run_custom_denoising_task,
        args=(task_id, normalized_keywords, total_terms),
        daemon=True,
        name=f'aba-custom-denoising-{task_id[:8]}',
    )
    worker.start()

    return task_id, initial_progress


def _run_add_noise_words_task(task_id, keywords, total_terms, inserted_word_count):
    keyword_patterns = _build_custom_denoising_patterns(keywords)
    processed_count = 0
    matched_count = 0
    updated_count = 0
    pending_update_ids = []

    try:
        close_old_connections()
        _set_add_noise_words_progress(
            task_id,
            status='running',
            processed_count=0,
            matched_count=0,
            updated_count=0,
            total_terms=total_terms,
            keyword_count=len(keywords),
            inserted_word_count=inserted_word_count,
            message='词表已更新，正在扫描搜索词',
            error='',
        )

        search_terms = SearchTerm.objects.using('aba_db').order_by('id').values_list('id', 'term')
        for search_term_id, term in search_terms.iterator(chunk_size=CUSTOM_DENOISING_SCAN_BATCH_SIZE):
            processed_count += 1

            if _matches_custom_denoising_term(term, keyword_patterns):
                matched_count += 1
                pending_update_ids.append(search_term_id)

            if len(pending_update_ids) >= CUSTOM_DENOISING_UPDATE_BATCH_SIZE:
                updated_count += _flush_custom_denoising_updates(pending_update_ids)
                pending_update_ids = []

            if processed_count % CUSTOM_DENOISING_SCAN_BATCH_SIZE == 0:
                _set_add_noise_words_progress(
                    task_id,
                    status='running',
                    processed_count=processed_count,
                    matched_count=matched_count,
                    updated_count=updated_count,
                    total_terms=total_terms,
                    keyword_count=len(keywords),
                    inserted_word_count=inserted_word_count,
                    message=f'目前已处理 {processed_count} 条搜索词',
                    error='',
                )

        if pending_update_ids:
            updated_count += _flush_custom_denoising_updates(pending_update_ids)

        _set_add_noise_words_progress(
            task_id,
            status='success',
            processed_count=processed_count,
            matched_count=matched_count,
            updated_count=updated_count,
            total_terms=total_terms,
            keyword_count=len(keywords),
            inserted_word_count=inserted_word_count,
            message=f'添加完成，新增词 {inserted_word_count} 个，命中 {matched_count} 条，更新 {updated_count} 条',
            error='',
        )
    except Exception as exc:
        _set_add_noise_words_progress(
            task_id,
            status='error',
            processed_count=processed_count,
            matched_count=matched_count,
            updated_count=updated_count,
            total_terms=total_terms,
            keyword_count=len(keywords),
            inserted_word_count=inserted_word_count,
            message=f'添加去噪词失败：{exc}',
            error=str(exc),
        )
    finally:
        close_old_connections()


def _launch_add_noise_words_task(keywords):
    normalized_keywords = _normalize_custom_denoising_keywords('\n'.join(keywords))
    inserted_word_count = 0

    with transaction.atomic(using='aba_db'):
        _, inserted_word_count = _create_noise_words(normalized_keywords)

    task_id = uuid.uuid4().hex
    total_terms = SearchTerm.objects.using('aba_db').count()
    initial_progress = _build_add_noise_words_progress(
        status='pending',
        processed_count=0,
        matched_count=0,
        updated_count=0,
        total_terms=total_terms,
        keyword_count=len(normalized_keywords),
        inserted_word_count=inserted_word_count,
        message='词表已更新，准备开始扫描搜索词',
        error='',
    )
    cache.set(_add_noise_words_cache_key(task_id), initial_progress, CUSTOM_DENOISING_CACHE_TTL)

    worker = threading.Thread(
        target=_run_add_noise_words_task,
        args=(task_id, normalized_keywords, total_terms, inserted_word_count),
        daemon=True,
        name=f'aba-add-noise-words-{task_id[:8]}',
    )
    worker.start()

    return task_id, initial_progress


def _build_aba_hot_queryset_context(
    *,
    week,
    search_term='',
    category='',
    noise_status='all',
    word_filter='all',
    search_mode='0',
):
    category = _normalize_category_value(category)
    week_date = _parse_week_value(week)
    if not week_date:
        return None

    has_term_filters = bool(search_term or category or noise_status != 'all')
    queryset = SearchTermMetric.objects.using('aba_db').filter(report_week=week_date).select_related('search_term')

    if has_term_filters:
        if category:
            filtered_term_ids = _get_filtered_term_ids_with_cache(
                category=category,
                search_term=search_term,
                noise_status=noise_status,
                search_mode=search_mode,
            )
            if not filtered_term_ids:
                queryset = queryset.none()
            else:
                queryset = queryset.filter(search_term_id__in=filtered_term_ids)
        # 仅按去噪状态过滤时，直接 JOIN SearchTerm 更快。
        elif noise_status in {'noise', 'denoised'} and not search_term and not category:
            queryset = queryset.filter(search_term__denoising=(noise_status == 'noise'))
        else:
            filtered_term_ids = _build_filtered_term_queryset(
                category=category,
                search_term=search_term,
                noise_status=noise_status,
                search_mode=search_mode,
            ).values('id')
            queryset = queryset.filter(search_term_id__in=Subquery(filtered_term_ids))

    queryset = _apply_hot_word_filter(
        queryset,
        week_date,
        word_filter,
        search_term=search_term,
        search_mode=search_mode,
        category=category,
        noise_status=noise_status,
    )

    return {
        'week_date': week_date,
        'queryset': queryset,
        'has_extra_filters': bool(search_term or category or noise_status != 'all' or word_filter != 'all'),
    }


def _get_aba_hot_total_count(week_date, queryset, has_extra_filters):
    if has_extra_filters:
        return queryset.count()

    return AbaReportWeek.objects.using('aba_db').filter(
        report_week=week_date,
        is_active=True,
        import_status='ready'
    ).values_list('record_count', flat=True).first() or 0


def _parse_metric_cursor(raw_rank, raw_id):
    try:
        rank = int(raw_rank)
        metric_id = int(raw_id)
    except (TypeError, ValueError):
        return None

    return {
        'rank': rank,
        'id': metric_id,
    }


def _build_metric_page_cursor(metric):
    return {
        'rank': metric.search_frequency_rank,
        'id': metric.id,
    }


def _run_aba_total_count_task(task_id, filters):
    page_size = filters.get('page_size', 20)

    try:
        close_old_connections()
        _set_aba_total_count_progress(
            task_id,
            status='running',
            total=0,
            total_pages=0,
            page_size=page_size,
            message='正在计算总页数',
            error='',
        )

        context = _build_aba_hot_queryset_context(
            week=filters.get('week', ''),
            search_term=filters.get('search_term', ''),
            category=filters.get('category', ''),
            noise_status=filters.get('noise_status', 'all'),
            word_filter=filters.get('word_filter', 'all'),
            search_mode=filters.get('search_mode', '0'),
        )
        if not context:
            raise ValueError('缺少有效周期，无法计算总页数')

        total = _get_aba_hot_total_count(
            context['week_date'],
            context['queryset'],
            context['has_extra_filters'],
        )
        total_pages = (total + page_size - 1) // page_size if total > 0 else 0

        _set_aba_total_count_progress(
            task_id,
            status='success',
            total=total,
            total_pages=total_pages,
            page_size=page_size,
            message=f'计算完成，共 {total_pages} 页',
            error='',
        )
    except Exception as exc:
        _set_aba_total_count_progress(
            task_id,
            status='error',
            total=0,
            total_pages=0,
            page_size=page_size,
            message=f'总页数计算失败：{exc}',
            error=str(exc),
        )
    finally:
        close_old_connections()


def _launch_aba_total_count_task(filters):
    task_id = uuid.uuid4().hex
    page_size = filters.get('page_size', 20)
    initial_progress = _build_aba_total_count_progress(
        status='pending',
        total=0,
        total_pages=0,
        page_size=page_size,
        message='任务已创建，准备开始计算',
        error='',
    )
    cache.set(_aba_total_count_cache_key(task_id), initial_progress, CUSTOM_DENOISING_CACHE_TTL)

    worker = threading.Thread(
        target=_run_aba_total_count_task,
        args=(task_id, filters),
        daemon=True,
        name=f'aba-total-count-{task_id[:8]}',
    )
    worker.start()

    return task_id, initial_progress


@require_http_methods(["GET"])
@aba_permission_required
def get_aba_data_api(request):
    """
    获取 ABA 热词榜列表 API。

    参数:
        week: 周期（日期，如 2026-02-15）
        search_term: 搜索词（模糊搜索）
        category: 品类英文关键词（按搜索词整词匹配）
        page: 页码，默认 1
        page_size: 每页条数，默认 20
    """
    try:
        # 获取参数
        week = request.GET.get('week', '').strip()
        search_term = request.GET.get('search_term', '').strip()
        category = _normalize_category_value(request.GET.get('category', ''))
        noise_status = request.GET.get('noise_status', 'all').strip()
        word_filter = request.GET.get('word_filter', 'all').strip()
        search_mode = request.GET.get('search_mode', '0')
        cached_total_raw = request.GET.get('cached_total', '').strip()
        cursor_direction = request.GET.get('cursor_direction', '').strip().lower()
        cursor = _parse_metric_cursor(
            request.GET.get('cursor_rank', '').strip(),
            request.GET.get('cursor_id', '').strip(),
        )
        page = max(int(request.GET.get('page', 1)), 1)
        page_size = int(request.GET.get('page_size', 20))

        if page_size not in [20, 50, 100, 200]:
            page_size = 20

        if not week:
            return JsonResponse(_build_empty_aba_response(page, page_size, needs_week=True))

        week_date = _parse_week_value(week)
        if not week_date:
            return JsonResponse(_build_empty_aba_response(page, page_size, needs_week=True))

        context = _build_aba_hot_queryset_context(
            week=week,
            search_term=search_term,
            category=category,
            noise_status=noise_status,
            word_filter=word_filter,
            search_mode=search_mode,
        )
        if not context:
            return JsonResponse(_build_empty_aba_response(page, page_size, needs_week=True))

        known_total = False
        if context['has_extra_filters']:
            try:
                total = max(int(cached_total_raw), 0)
                known_total = True
            except (TypeError, ValueError):
                total = 0
            total_pages = (total + page_size - 1) // page_size if total > 0 else 0
            pagination_mode = 'full' if known_total else 'simple'
        else:
            total = _get_aba_hot_total_count(
                context['week_date'],
                context['queryset'],
                context['has_extra_filters'],
            )
            total_pages = (total + page_size - 1) // page_size if total > 0 else 0
            pagination_mode = 'full'

        base_queryset = context['queryset']
        metric_index_ids = None
        can_use_metric_index = bool(category and word_filter == 'all')
        if can_use_metric_index:
            metric_index_ids = _get_filtered_metric_index_with_cache(
                queryset=base_queryset,
                week=week,
                category=category,
                search_term=search_term,
                noise_status=noise_status,
                word_filter=word_filter,
                search_mode=search_mode,
            )
            total = len(metric_index_ids)
            total_pages = (total + page_size - 1) // page_size if total > 0 else 0
            pagination_mode = 'simple'
            offset = (page - 1) * page_size
            page_metric_ids = metric_index_ids[offset:offset + page_size + 1]
            has_next = len(page_metric_ids) > page_size
            if has_next:
                page_metric_ids = page_metric_ids[:page_size]
            has_prev = page > 1
            metrics_by_id = {
                metric.id: metric
                for metric in SearchTermMetric.objects.using('aba_db').filter(
                    id__in=page_metric_ids
                ).select_related('search_term')
            }
            page_metrics = [metrics_by_id[metric_id] for metric_id in page_metric_ids if metric_id in metrics_by_id]
            cursor_applied = False
        else:
            queryset = base_queryset.order_by('search_frequency_rank', 'id')
            cursor_applied = cursor and cursor_direction in {'next', 'prev'}

            if cursor_applied and cursor_direction == 'next':
                limit = page_size + 1
                page_metrics = list(
                    base_queryset.filter(
                        search_frequency_rank=cursor['rank'],
                        id__gt=cursor['id'],
                    ).order_by('id')[:limit]
                )
                remaining = limit - len(page_metrics)
                if remaining > 0:
                    page_metrics.extend(list(
                        base_queryset.filter(
                            search_frequency_rank__gt=cursor['rank'],
                        ).order_by('search_frequency_rank', 'id')[:remaining]
                    ))
            elif cursor_applied and cursor_direction == 'prev':
                limit = page_size + 1
                page_metrics = list(
                    base_queryset.filter(
                        search_frequency_rank=cursor['rank'],
                        id__lt=cursor['id'],
                    ).order_by('-id')[:limit]
                )
                remaining = limit - len(page_metrics)
                if remaining > 0:
                    page_metrics.extend(list(
                        base_queryset.filter(
                            search_frequency_rank__lt=cursor['rank'],
                        ).order_by('-search_frequency_rank', '-id')[:remaining]
                    ))
            else:
                cursor_applied = False
                if page > 1:
                    offset = (page - 1) * page_size
                    queryset = queryset[offset:]
                page_metrics = list(queryset[:page_size + 1])

            if cursor_applied and cursor_direction == 'prev':
                has_prev = len(page_metrics) > page_size
                if has_prev:
                    page_metrics = page_metrics[:page_size]
                page_metrics.reverse()
                has_next = page > 1 and bool(page_metrics)
            else:
                has_next = len(page_metrics) > page_size
                if has_next:
                    page_metrics = page_metrics[:page_size]
                has_prev = page > 1

        if not page_metrics:
            return JsonResponse({
                **_build_empty_aba_response(page, page_size),
                'pagination_mode': pagination_mode,
                'total': total,
                'total_pages': total_pages,
                'has_prev': has_prev if 'has_prev' in locals() else page > 1,
            })

        page_search_term_ids = [metric.search_term_id for metric in page_metrics]
        trend_by_term_id = defaultdict(list)
        if page_search_term_ids:
            trend_start_week = week_date - timedelta(days=91)
            trend_rows = SearchTermMetric.objects.using('aba_db').filter(
                search_term_id__in=page_search_term_ids,
                report_week__gte=trend_start_week,
                report_week__lte=week_date
            ).order_by('search_term_id', 'report_week').values(
                'search_term_id',
                'report_week',
                'search_frequency_rank'
            )

            for trend_row in trend_rows:
                trend_by_term_id[trend_row['search_term_id']].append({
                    'week': trend_row['report_week'].strftime('%Y-%m-%d'),
                    'rank': trend_row['search_frequency_rank'],
                })

        metrics_with_trend = []
        for metric in page_metrics:
            # 计算前三商品总份额
            total_click_share = (
                (metric.asin_1_click_share or 0) +
                (metric.asin_2_click_share or 0) +
                (metric.asin_3_click_share or 0)
            )
            total_conversion_share = (
                (metric.asin_1_conversion_share or 0) +
                (metric.asin_2_conversion_share or 0) +
                (metric.asin_3_conversion_share or 0)
            )
            
            metrics_with_trend.append({
                'id': metric.id,
                'search_term': metric.search_term.term,
                'search_term_translation_cn': metric.search_term.translation_cn,
                'search_term_id': metric.search_term.id,
                'denoising': metric.search_term.denoising,
                'search_frequency_rank': metric.search_frequency_rank,
                'rank_change': metric.rank_change,
                'trend': trend_by_term_id.get(metric.search_term_id, []),
                'word_categories': _get_hot_word_categories(
                    metric,
                    trend_by_term_id.get(metric.search_term_id, []),
                ),
                'total_click_share': round(total_click_share * 100, 2),  # 转为百分比
                'total_conversion_share': round(total_conversion_share * 100, 2),
                'report_week': metric.report_week.strftime('%Y-%m-%d'),
                # ASIN 详情
                'asin_1': {
                    'code': metric.asin_1_code,
                    'title': metric.asin_1_title,
                    'click_share': round((metric.asin_1_click_share or 0) * 100, 2),
                    'conversion_share': round((metric.asin_1_conversion_share or 0) * 100, 2),
                },
                'asin_2': {
                    'code': metric.asin_2_code,
                    'title': metric.asin_2_title,
                    'click_share': round((metric.asin_2_click_share or 0) * 100, 2) if metric.asin_2_click_share else None,
                    'conversion_share': round((metric.asin_2_conversion_share or 0) * 100, 2) if metric.asin_2_conversion_share else None,
                },
                'asin_3': {
                    'code': metric.asin_3_code,
                    'title': metric.asin_3_title,
                    'click_share': round((metric.asin_3_click_share or 0) * 100, 2) if metric.asin_3_click_share else None,
                    'conversion_share': round((metric.asin_3_conversion_share or 0) * 100, 2) if metric.asin_3_conversion_share else None,
                },
            })
        
        return JsonResponse({
            'success': True,
            'data': metrics_with_trend,
            'page': page,
            'page_size': page_size,
            'total': total,
            'total_pages': total_pages,
            'has_prev': has_prev,
            'has_next': has_next,
            'pagination_mode': 'simple',
            'next_cursor': _build_metric_page_cursor(page_metrics[-1]) if page_metrics else None,
            'prev_cursor': _build_metric_page_cursor(page_metrics[0]) if page_metrics else None,
            'needs_week': False,
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@require_http_methods(["GET"])
@aba_permission_required
def get_aba_new_words_api(request):
    """
    获取 ABA 新词榜列表 API

    优先使用显式的 start_week / end_week。
    为兼容旧调用方式，当缺少 start_week 时回退到 end_week 向前 13 周。
    """
    try:
        start_week_raw = request.GET.get('start_week', '').strip()
        end_week_raw = request.GET.get('end_week', '').strip() or request.GET.get('week', '').strip()
        search_term = request.GET.get('search_term', '').strip()
        category = _normalize_category_value(request.GET.get('category', ''))
        search_mode = request.GET.get('search_mode', '0')
        noise_status = request.GET.get('noise_status', 'all').strip()
        word_filter = request.GET.get('word_filter', 'all').strip()
        page = max(int(request.GET.get('page', 1)), 1)
        page_size = int(request.GET.get('page_size', 20))

        if page_size not in [20, 50, 100, 200]:
            page_size = 20

        window_end = _parse_week_value(end_week_raw)
        if not window_end:
            return JsonResponse(_build_empty_new_words_response(page, page_size, needs_week=True))

        window_start = _parse_week_value(start_week_raw) if start_week_raw else _get_new_words_window_start(window_end, weeks=13)
        if not window_start:
            return JsonResponse(_build_empty_new_words_response(page, page_size, needs_week=True))

        if window_start > window_end:
            return JsonResponse({
                'success': False,
                'error': '开始周期不能晚于结束周期'
            }, status=400)

        base_queryset = SearchTerm.objects.using('aba_db').filter(
            first_seen__gte=window_start,
            first_seen__lte=window_end,
        )

        base_queryset = _apply_search_term_filters(
            base_queryset,
            search_term,
            search_mode,
            term_field='term',
        )
        if category:
            base_queryset = _apply_category_filter(
                base_queryset,
                category,
                category_field='category',
            )

        if noise_status == 'noise':
            base_queryset = base_queryset.filter(denoising=True)
        elif noise_status == 'denoised':
            base_queryset = base_queryset.filter(denoising=False)

        if word_filter in {'burst', 'surging', 'potential'}:
            growth_filter_qs = SearchTermMetric.objects.using('aba_db').filter(
                report_week=window_end,
                last_week_rank__gt=0,
                search_frequency_rank__gt=0,
            ).annotate(
                growth_pct=ExpressionWrapper(
                    (Cast(F('last_week_rank'), FloatField()) - Cast(F('search_frequency_rank'), FloatField())) * Value(100.0) / Cast(F('last_week_rank'), FloatField()),
                    output_field=FloatField(),
                )
            )
            if word_filter == 'burst':
                growth_filter_qs = growth_filter_qs.filter(growth_pct__gt=70)
            elif word_filter == 'surging':
                growth_filter_qs = growth_filter_qs.filter(growth_pct__gte=50, growth_pct__lte=70)
            elif word_filter == 'potential':
                growth_filter_qs = growth_filter_qs.filter(growth_pct__gte=10)

            base_queryset = base_queryset.filter(
                id__in=Subquery(growth_filter_qs.values('search_term_id'))
            )

        candidate_queryset = base_queryset.order_by('-first_seen', 'id')

        total = candidate_queryset.count()
        total_pages = max(1, (total + page_size - 1) // page_size) if total > 0 else 0

        offset = (page - 1) * page_size
        page_terms = list(candidate_queryset[offset:offset + page_size + 1])
        has_next = len(page_terms) > page_size
        if has_next:
            page_terms = page_terms[:page_size]

        if not page_terms:
            response = _build_empty_new_words_response(page, page_size, needs_week=False)
            response['window_start'] = window_start.strftime('%Y-%m-%d')
            response['window_end'] = window_end.strftime('%Y-%m-%d')
            return JsonResponse(response)

        term_ids = [term.id for term in page_terms]
        page_terms_by_id = {term.id: term for term in page_terms}

        metrics = SearchTermMetric.objects.using('aba_db').filter(
            search_term_id__in=term_ids,
            report_week__gte=window_start,
            report_week__lte=window_end,
        ).order_by('search_term_id', 'report_week')

        metrics_by_term_id = defaultdict(list)
        for metric in metrics:
            metrics_by_term_id[metric.search_term_id].append(metric)

        data = []
        for term_id in term_ids:
            search_term_obj = page_terms_by_id.get(term_id)
            if not search_term_obj:
                continue

            term_metrics = metrics_by_term_id.get(term_id, [])
            latest_report_week = term_metrics[-1].report_week if term_metrics else search_term_obj.first_seen
            term_stats = {
                'first_report_week': search_term_obj.first_seen,
                'latest_report_week': latest_report_week,
                'appearance_count': len(term_metrics),
                'window_start': window_start,
                'window_end': window_end,
            }

            data.append(_build_new_words_row(
                search_term_obj,
                term_stats,
                term_metrics,
            ))

        return JsonResponse({
            'success': True,
            'data': data,
            'page': page,
            'page_size': page_size,
            'total': total,
            'total_pages': total_pages,
            'has_prev': page > 1,
            'has_next': has_next,
            'pagination_mode': 'full',
            'needs_week': False,
            'window_start': window_start.strftime('%Y-%m-%d'),
            'window_end': window_end.strftime('%Y-%m-%d'),
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)

#=========批量去噪接口====================
@require_http_methods(["POST"])
@aba_permission_required
def update_search_term_denoising_api(request):
    """
    更新搜索词的去噪状态
    """
    try:
        payload = json.loads(request.body or '{}')
        search_term_ids = _normalize_search_term_ids(payload.get('search_term_ids', []))
        single_search_term_id = payload.get('search_term_id')

        if not search_term_ids and single_search_term_id is not None:
            search_term_ids = _normalize_search_term_ids([single_search_term_id])

        if not search_term_ids:
            return JsonResponse({
                'success': False,
                'error': '缺少有效的 search_term_id'
            }, status=400)

        denoising = _normalize_boolean_value(payload.get('denoising', False), default=False)
        updated_count, affected_words = _set_search_terms_denoising(search_term_ids, denoising)

        if updated_count == 0:
            return JsonResponse({
                'success': False,
                'error': '搜索词不存在'
            }, status=404)

        return JsonResponse({
            'success': True,
            'message': f'已将 {updated_count} 条数据标记为噪声词' if denoising else f'已将 {updated_count} 条数据恢复为非噪声词',
            'data': {
                'search_term_ids': search_term_ids,
                'updated_count': updated_count,
                'denoising': denoising,
                'affected_words': affected_words,
            }
        })
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': '请求体不是合法 JSON'
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@require_http_methods(["POST"])
@aba_permission_required
def start_custom_denoising_api(request):
    """
    启动自定义批量去噪任务
    """
    try:
        payload = json.loads(request.body or '{}')
        keywords = _normalize_custom_denoising_keywords(payload.get('keywords_text', ''))

        if not keywords:
            return JsonResponse({
                'success': False,
                'error': '请输入至少一个有效的去噪词或词组'
            }, status=400)

        task_id, progress = _launch_custom_denoising_task(keywords)
        return JsonResponse({
            'success': True,
            'message': '自定义去噪任务已启动',
            'data': {
                'task_id': task_id,
                **progress,
            }
        })
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': '请求体不是合法 JSON'
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@require_http_methods(["GET"])
@aba_permission_required
def get_custom_denoising_progress_api(request):
    """
    获取自定义批量去噪任务进度
    """
    task_id = request.GET.get('task_id', '').strip()
    if not task_id:
        return JsonResponse({
            'success': False,
            'error': '缺少 task_id'
        }, status=400)

    progress = _get_custom_denoising_progress(task_id)
    if not progress:
        return JsonResponse({
            'success': False,
            'error': '任务不存在或已过期'
        }, status=404)

    return JsonResponse({
        'success': True,
        'data': progress,
    })


@require_http_methods(["POST"])
@aba_permission_required
def start_add_noise_words_api(request):
    """
    启动批量添加去噪词任务
    """
    try:
        payload = json.loads(request.body or '{}')
        keywords = _normalize_custom_denoising_keywords(payload.get('keywords_text', ''))

        if not keywords:
            return JsonResponse({
                'success': False,
                'error': '请输入至少一个有效的去噪词或词组'
            }, status=400)

        task_id, progress = _launch_add_noise_words_task(keywords)
        return JsonResponse({
            'success': True,
            'message': '添加去噪词任务已启动',
            'data': {
                'task_id': task_id,
                **progress,
            }
        })
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': '请求体不是合法 JSON'
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@require_http_methods(["GET"])
@aba_permission_required
def get_add_noise_words_progress_api(request):
    """
    获取批量添加去噪词任务进度
    """
    task_id = request.GET.get('task_id', '').strip()
    if not task_id:
        return JsonResponse({
            'success': False,
            'error': '缺少 task_id'
        }, status=400)

    progress = _get_add_noise_words_progress(task_id)
    if not progress:
        return JsonResponse({
            'success': False,
            'error': '任务不存在或已过期'
        }, status=404)

    return JsonResponse({
        'success': True,
        'data': progress,
    })


@require_http_methods(["GET"])
@aba_permission_required
def start_aba_total_count_api(request):
    """
    启动 ABA 热词榜总页数计算任务
    """
    try:
        week = request.GET.get('week', '').strip()
        search_term = request.GET.get('search_term', '').strip()
        category = _normalize_category_value(request.GET.get('category', ''))
        search_mode = request.GET.get('search_mode', '0')
        noise_status = request.GET.get('noise_status', 'all').strip()
        word_filter = request.GET.get('word_filter', 'all').strip()
        page_size = int(request.GET.get('page_size', 20))

        if page_size not in [20, 50, 100, 200]:
            page_size = 20

        if not _parse_week_value(week):
            return JsonResponse({
                'success': False,
                'error': '缺少有效周期，无法计算总页数'
            }, status=400)

        task_id, progress = _launch_aba_total_count_task({
            'week': week,
            'search_term': search_term,
            'category': category,
            'search_mode': search_mode,
            'noise_status': noise_status,
            'word_filter': word_filter,
            'page_size': page_size,
        })
        return JsonResponse({
            'success': True,
            'message': '总页数计算任务已启动',
            'data': {
                'task_id': task_id,
                **progress,
            }
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@require_http_methods(["GET"])
@aba_permission_required
def get_aba_total_count_progress_api(request):
    """
    获取 ABA 热词榜总页数计算任务进度
    """
    task_id = request.GET.get('task_id', '').strip()
    if not task_id:
        return JsonResponse({
            'success': False,
            'error': '缺少 task_id'
        }, status=400)

    progress = _get_aba_total_count_progress(task_id)
    if not progress:
        return JsonResponse({
            'success': False,
            'error': '任务不存在或已过期'
        }, status=404)

    return JsonResponse({
        'success': True,
        'data': progress,
    })


@require_http_methods(["GET"])
@aba_permission_required
def get_available_weeks_api(request):
    """
    获取可用的周期（周）列表
    格式：2026年第8周 (02.22-02.28)
    """
    try:
        weeks = AbaReportWeek.objects.using('aba_db').filter(
            is_active=True,
            import_status='ready'
        ).order_by('-report_week').values('report_week', 'display_label')

        week_list = [
            {
                'value': week['report_week'].strftime('%Y-%m-%d'),
                'label': week['display_label']
            }
            for week in weeks
        ]

        return JsonResponse({
            'success': True,
            'data': week_list
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@require_http_methods(["POST"])
@aba_permission_required
def get_aba_noise_words_api(request):
    """
    获取 ABA 去噪词表列表
    """
    try:
        payload = json.loads(request.body or '{}')
        word = payload.get('word', '').strip()
        fuzzy_search = _normalize_boolean_value(payload.get('fuzzy_search', True), default=True)
        page = max(int(payload.get('page', 1)), 1)
        page_size = int(payload.get('page_size', 20))

        if page_size not in [20, 50, 100, 200]:
            page_size = 20

        queryset = AbaNoiseWord.objects.using('aba_db').all()
        if word:
            if fuzzy_search:
                queryset = queryset.filter(word__icontains=word)
            else:
                queryset = queryset.filter(word__iexact=word)

        queryset = queryset.order_by('word')
        offset = (page - 1) * page_size
        page_words = list(queryset.values_list('word', flat=True)[offset:offset + page_size + 1])
        has_next = len(page_words) > page_size
        if has_next:
            page_words = page_words[:page_size]

        if not page_words:
            return JsonResponse(_build_empty_noise_words_response(page, page_size))

        data_list = [
            {'word': word_value}
            for word_value in page_words
        ]

        return JsonResponse({
            'success': True,
            'data': {
                'list': data_list,
                'page': page,
                'page_size': page_size,
                'has_prev': page > 1,
                'has_next': has_next,
                'pagination_mode': 'simple',
            }
        })
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': '请求体不是合法 JSON'
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@require_http_methods(["POST"])
@aba_permission_required
def delete_aba_noise_word_api(request):
    """
    删除 ABA 去噪词
    """
    try:
        payload = json.loads(request.body or '{}')
        word = payload.get('word', '')
        normalized_words = _normalize_noise_words([word])

        if not normalized_words:
            return JsonResponse({
                'success': False,
                'error': '缺少有效的 word'
            }, status=400)

        deleted_count = _delete_noise_word(normalized_words[0])
        if deleted_count == 0:
            return JsonResponse({
                'success': False,
                'error': '去噪词不存在'
            }, status=404)

        return JsonResponse({
            'success': True,
            'message': '已删除去噪词',
            'data': {
                'word': normalized_words[0],
                'deleted_count': deleted_count,
            }
        })
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': '请求体不是合法 JSON'
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)
