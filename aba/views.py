"""
ABA 数据管理视图
"""
import json
import threading
import uuid

from django.core.cache import cache
from django.db import close_old_connections
from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from datetime import datetime, timedelta
from collections import defaultdict

from aba.models import AbaReportWeek, SearchTerm, SearchTermMetric


CUSTOM_DENOISING_CACHE_PREFIX = 'aba:custom-denoising:'
CUSTOM_DENOISING_CACHE_TTL = 60 * 60
CUSTOM_DENOISING_SCAN_BATCH_SIZE = 200
CUSTOM_DENOISING_UPDATE_BATCH_SIZE = 500


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
        'needs_week': needs_week,
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
    keyword_patterns = [keyword.casefold() for keyword in keywords]
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
            normalized_term = (term or '').casefold()

            if any(keyword in normalized_term for keyword in keyword_patterns):
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
        category: 品类英文关键词（按搜索词子串匹配）
        page: 页码，默认 1
        page_size: 每页条数，默认 50
    """
    try:
        # 获取参数
        week = request.GET.get('week', '')
        search_term = request.GET.get('search_term', '').strip()
        category = request.GET.get('category', '').strip()
        noise_status = request.GET.get('noise_status', 'all').strip()
        cached_total = request.GET.get('cached_total', '').strip()
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
        if search_term:
            if search_mode == '0':  # 精准查询 - 完全匹配
                queryset = queryset.filter(search_term__term__iexact=search_term)
            elif search_mode == '2':  # 广泛匹配 - 空格分隔关键词，AND关系，整词匹配
                keywords = search_term.strip().split()
                if keywords:
                    # 必须同时包含所有关键词（AND关系），每个都是整词匹配
                    for keyword in keywords:
                        # 使用正则表达式实现整词匹配
                        # \y 是 PostgreSQL 的单词边界，匹配独立单词
                        queryset = queryset.filter(search_term__term__iregex=rf'\y{keyword}\y')
            else:  # 默认模糊查询 - 子串匹配
                queryset = queryset.filter(search_term__term__icontains=search_term)

        if category:
            queryset = queryset.filter(search_term__term__icontains=category)

        if noise_status == 'noise':
            queryset = queryset.filter(search_term__denoising=True)
        elif noise_status == 'denoised':
            queryset = queryset.filter(search_term__denoising=False)

        has_extra_filters = bool(search_term or category or noise_status != 'all')

        if has_extra_filters:
            if page == 1:
                total = queryset.count()
            else:
                try:
                    total = max(int(cached_total), 0)
                except (TypeError, ValueError):
                    total = queryset.count()
        else:
            total = AbaReportWeek.objects.using('aba_db').filter(
                report_week=week_date,
                is_active=True,
                import_status='ready'
            ).values_list('record_count', flat=True).first() or 0

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
            'needs_week': False,
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
