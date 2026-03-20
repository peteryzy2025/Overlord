"""
ABA 数据管理视图
"""
import json
import re
import threading
import uuid
from collections import defaultdict
from datetime import datetime, timedelta

from django.core.cache import cache
from django.db.models import Case, Count, DecimalField, ExpressionWrapper, F, FloatField, IntegerField, Max, OuterRef, Subquery, Value, When
from django.db.models.functions import Cast, Coalesce
from django.db import close_old_connections
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

from aba.models import AbaReportWeek, SearchTerm, SearchTermMetric


CUSTOM_DENOISING_CACHE_PREFIX = 'aba:custom-denoising:'
CUSTOM_DENOISING_CACHE_TTL = 60 * 60
CUSTOM_DENOISING_SCAN_BATCH_SIZE = 200
CUSTOM_DENOISING_UPDATE_BATCH_SIZE = 500
HOT_WORD_PICKUP_RANK_THRESHOLD = 30000


def aba_data_page(request):
    """
    ABA 数据管理页面
    """
    return render(request, 'aba/aba_data.html', {'active_page': 'aba_data'})


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


def _apply_category_filter(queryset, category, term_field='search_term__term'):
    pattern_text = _build_whole_word_regex(category)
    if not pattern_text:
        return queryset

    return queryset.filter(**{f'{term_field}__iregex': pattern_text})


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
    if growth_percent is not None and growth_percent >= 50:
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
            history_queryset = _apply_category_filter(history_queryset, category)
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
        queryset = queryset.filter(rank_growth_percent__gte=50)
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


def _get_custom_denoising_progress(task_id):
    return cache.get(_custom_denoising_cache_key(task_id))


def _set_custom_denoising_progress(task_id, **kwargs):
    progress = _get_custom_denoising_progress(task_id) or _build_custom_denoising_progress()
    progress.update(kwargs)
    cache.set(_custom_denoising_cache_key(task_id), progress, CUSTOM_DENOISING_CACHE_TTL)
    return progress


def _flush_custom_denoising_updates(search_term_ids):
    if not search_term_ids:
        return 0

    return SearchTerm.objects.using('aba_db').filter(
        id__in=search_term_ids,
        denoising=False
    ).update(denoising=True)


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
    task_id = uuid.uuid4().hex
    total_terms = SearchTerm.objects.using('aba_db').count()
    initial_progress = _build_custom_denoising_progress(
        status='pending',
        processed_count=0,
        matched_count=0,
        updated_count=0,
        total_terms=total_terms,
        keyword_count=len(keywords),
        message='任务已创建，准备开始处理',
        error='',
    )
    cache.set(_custom_denoising_cache_key(task_id), initial_progress, CUSTOM_DENOISING_CACHE_TTL)

    worker = threading.Thread(
        target=_run_custom_denoising_task,
        args=(task_id, keywords, total_terms),
        daemon=True,
        name=f'aba-custom-denoising-{task_id[:8]}',
    )
    worker.start()

    return task_id, initial_progress


@require_http_methods(["GET"])
def get_aba_data_api(request):
    """
    获取 ABA 数据列表 API
    
    参数:
        week: 周期（日期，如 2026-02-15）
        search_term: 搜索词（模糊搜索）
        category: 品类英文关键词（按搜索词整词匹配）
        page: 页码，默认 1
        page_size: 每页条数，默认 50
    """
    try:
        # 获取参数
        week = request.GET.get('week', '')
        search_term = request.GET.get('search_term', '').strip()
        category = request.GET.get('category', '').strip()
        noise_status = request.GET.get('noise_status', 'all').strip()
        word_filter = request.GET.get('word_filter', 'all').strip()
        page = max(int(request.GET.get('page', 1)), 1)
        page_size = int(request.GET.get('page_size', 50))
        
        # 验证 page_size
        if page_size not in [20, 50, 100, 200]:
            page_size = 50

        if not week:
            return JsonResponse(_build_empty_aba_response(page, page_size, needs_week=True))

        try:
            week_date = datetime.strptime(week, "%Y-%m-%d").date()
        except ValueError:
            return JsonResponse(_build_empty_aba_response(page, page_size, needs_week=True))

        # 基础查询 - 使用 aba_db 数据库
        queryset = SearchTermMetric.objects.using('aba_db').select_related('search_term').filter(report_week=week_date)
        
        # 按搜索词筛选（支持不同匹配模式）
        search_mode = request.GET.get('search_mode', '0')
        queryset = _apply_search_term_filters(queryset, search_term, search_mode)

        if category:
            queryset = _apply_category_filter(queryset, category)

        if noise_status == 'noise':
            queryset = queryset.filter(search_term__denoising=True)
        elif noise_status == 'denoised':
            queryset = queryset.filter(search_term__denoising=False)

        queryset = _apply_hot_word_filter(
            queryset,
            week_date,
            word_filter,
            search_term=search_term,
            search_mode=search_mode,
            category=category,
            noise_status=noise_status,
        )

        has_extra_filters = bool(search_term or category or noise_status != 'all' or word_filter != 'all')
        # 任意额外筛选都改用轻分页，避免实时 count()
        use_simple_pagination = has_extra_filters

        if use_simple_pagination:
            total = 0
            total_pages = 0
        else:
            total = AbaReportWeek.objects.using('aba_db').filter(
                report_week=week_date,
                is_active=True,
                import_status='ready'
            ).values_list('record_count', flat=True).first() or 0

        if not use_simple_pagination:
            total_pages = (total + page_size - 1) // page_size if total > 0 else 0

        # 排序：按排名升序
        queryset = queryset.order_by('search_frequency_rank')

        offset = (page - 1) * page_size
        page_metrics = list(queryset[offset:offset + page_size + 1])
        has_next = len(page_metrics) > page_size
        if has_next:
            page_metrics = page_metrics[:page_size]

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
            'has_prev': page > 1,
            'has_next': has_next,
            'pagination_mode': 'simple' if use_simple_pagination else 'full',
            'needs_week': False,
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@require_http_methods(["GET"])
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
        category = request.GET.get('category', '').strip()
        search_mode = request.GET.get('search_mode', '0')
        noise_status = request.GET.get('noise_status', 'all').strip()
        page = max(int(request.GET.get('page', 1)), 1)
        page_size = int(request.GET.get('page_size', 50))

        if page_size not in [20, 50, 100, 200]:
            page_size = 50

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
            base_queryset = _apply_category_filter(base_queryset, category, term_field='term')

        if noise_status == 'noise':
            base_queryset = base_queryset.filter(denoising=True)
        elif noise_status == 'denoised':
            base_queryset = base_queryset.filter(denoising=False)

        candidate_queryset = base_queryset.order_by('-first_seen', 'id')

        total = 0
        total_pages = 0

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
            'pagination_mode': 'simple',
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
        updated_count = SearchTerm.objects.using('aba_db').filter(id__in=search_term_ids).update(denoising=denoising)

        if updated_count == 0:
            return JsonResponse({
                'success': False,
                'error': '搜索词不存在'
            }, status=404)

        return JsonResponse({
            'success': True,
            'message': f'已将 {updated_count} 条数据加入噪声页' if denoising else f'已将 {updated_count} 条数据恢复到去噪后页',
            'data': {
                'search_term_ids': search_term_ids,
                'updated_count': updated_count,
                'denoising': denoising,
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


@require_http_methods(["GET"])
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
