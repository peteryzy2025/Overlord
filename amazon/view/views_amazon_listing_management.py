import json
import time
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.db.models import Count, Q
from django.db.models.functions import Lower
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from amazon.models import AmazonListing
from general.models import OperationalAccount
from theme.models import TrademarkInfo


LIST_API_CACHE_TTL_SECONDS = 120
FILTER_OPTIONS_CACHE_TTL_SECONDS = 600
NAME_TYPE_MAPPING = {
    1: '\u7cfb\u7edf\u767d\u540d\u5355',
    2: '\u7528\u6237\u672a\u6307\u5b9a',
    3: '\u89c2\u5bdf\u540d\u5355',
    4: '\u4e9a\u9a6c\u900a\u6d89\u5acc\u4fb5\u6743',
    5: '\u5f8b\u5e08\u51fd',
    6: '\u6743\u5229\u4eba\u6295\u8bc9',
    7: '\u8fdd\u7981\u8bcd',
    8: '\u5546\u6807\u4fb5\u6743',
    9: '\u81ea\u5b9a\u4e49\u767d\u540d\u5355',
    10: '\u77e5\u540dIP',
}

LOW_RISK_NAME_TYPES = {1, 9}
HIGH_RISK_NAME_TYPES = {4, 5, 6, 7, 10, 11}
TRADEMARK_CHECK_NAME_TYPES = {2, 3, 8}
MEDIUM_RISK_STATUS_CODES = {
    0, 401, 404, 600, 601, 602, 604, 605, 606, 610, 616, 618, 620, 622, 624, 625,
    630, 631, 632, 638, 640, 641, 642, 643, 644, 645, 646, 647, 648, 649, 650, 651,
    652, 653, 654, 655, 656, 657, 658, 659, 660, 661, 663, 664, 665, 666, 667, 668,
    672, 680, 681, 682, 686, 688, 689, 690, 692, 693, 694, 710, 711, 712, 713, 715,
    717, 718, 719
}
RISK_RANK = {'low': 0, 'medium': 1, 'high': 2}


def _safe_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _norm_word(word):
    return (word or '').strip().lower()


def _ordered_unique(words):
    seen = set()
    result = []
    for word in words or []:
        key = _norm_word(word)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(word)
    return result


def _normalize_text_list(values, lower=False):
    if isinstance(values, (list, tuple, set)):
        source = values
    elif values is None:
        source = []
    else:
        source = [values]

    result = []
    seen = set()
    for item in source:
        text = str(item or '').strip()
        if not text:
            continue
        normalized = text.lower() if lower else text
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(normalized)
    return result


def _normalize_int_list(values):
    if isinstance(values, (list, tuple, set)):
        source = values
    elif values is None:
        source = []
    else:
        source = [values]

    result = []
    seen = set()
    for item in source:
        try:
            number = int(str(item).strip())
        except (TypeError, ValueError, AttributeError):
            continue
        if number <= 0 or number in seen:
            continue
        seen.add(number)
        result.append(number)
    return result


def _extract_operator_name(listing):
    amazon_shop = getattr(listing.lingxing_shop, 'amazon_shop', None)
    operator = getattr(amazon_shop, 'ops', None) if amazon_shop else None
    first_name = (getattr(operator, 'first_name', None) or '').strip()
    if first_name:
        return first_name
    username = (getattr(operator, 'username', None) or '').strip()
    return username


def _build_ops_group_map(user_ids):
    normalized_ids = []
    for user_id in user_ids or []:
        try:
            safe_id = int(user_id)
        except (TypeError, ValueError):
            continue
        if safe_id > 0:
            normalized_ids.append(safe_id)

    if not normalized_ids:
        return {}

    rows = OperationalAccount.objects.filter(user_id__in=normalized_ids).values_list('user_id', 'ops_group')
    return {
        user_id: (ops_group or '').strip()
        for user_id, ops_group in rows
    }


def _extract_ops_group_name(listing, ops_group_map=None):
    amazon_shop = getattr(listing.lingxing_shop, 'amazon_shop', None)
    operator_id = getattr(amazon_shop, 'ops_id', None) if amazon_shop else None
    if ops_group_map and operator_id in ops_group_map:
        return (ops_group_map.get(operator_id) or '').strip()

    operator = getattr(amazon_shop, 'ops', None) if amazon_shop else None
    operational_account = getattr(operator, 'operational_account', None) if operator else None
    return (getattr(operational_account, 'ops_group', None) or '').strip()


def _extract_amazon_shop_name(listing):
    amazon_shop = getattr(listing.lingxing_shop, 'amazon_shop', None)
    return (getattr(amazon_shop, 'shop_name', None) or '').strip()


def _to_int_or_none(value):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError, AttributeError):
        return None


def _max_risk_level(a, b):
    return a if RISK_RANK.get(a, 0) >= RISK_RANK.get(b, 0) else b


def _collect_status_words_from_listings(listings):
    words = set()
    for listing in listings:
        for tro in listing.tro_words.all():
            if tro.name_type in TRADEMARK_CHECK_NAME_TYPES and _norm_word(tro.theme_name):
                words.add(tro.theme_name)
        for tm in listing.trademarks.all():
            if _norm_word(tm.word_mark):
                words.add(tm.word_mark)
    return list(words)


def _build_status_code_map(words):
    lower_words = {_norm_word(word) for word in words or [] if _norm_word(word)}
    if not lower_words:
        return {}

    rows = (
        TrademarkInfo.objects
        .annotate(word_mark_lower=Lower('word_mark'))
        .filter(word_mark_lower__in=lower_words)
        .values_list('word_mark_lower', 'status_code_id')
    )
    result = {}
    for word_lower, status_code in rows:
        code_int = _to_int_or_none(status_code)
        if code_int is None:
            continue
        result.setdefault(word_lower, set()).add(code_int)
    return result


def _is_medium_by_status_codes(status_codes):
    return bool((status_codes or set()) & MEDIUM_RISK_STATUS_CODES)


def _build_listing_risk_data(listing, status_code_map=None):
    tro_objects = list(listing.tro_words.all())
    trademark_objects = list(listing.trademarks.all())

    if status_code_map is None:
        words_need_status = []
        for tro in tro_objects:
            if tro.name_type in TRADEMARK_CHECK_NAME_TYPES:
                words_need_status.append(tro.theme_name)
        words_need_status.extend(tm.word_mark for tm in trademark_objects)
        status_code_map = _build_status_code_map(words_need_status)
    merged = {}

    def ensure_item(word):
        norm = _norm_word(word)
        if not norm:
            return None, None
        if norm not in merged:
            merged[norm] = {
                'word': (word or '').strip(),
                'sources': [],
                'infringement_types': set(),
                'risk_level': 'low',
            }
        return norm, merged[norm]

    for tro in tro_objects:
        norm, item = ensure_item(tro.theme_name)
        if not item:
            continue

        if 'tro_words' not in item['sources']:
            item['sources'].append('tro_words')

        mapped_type = NAME_TYPE_MAPPING.get(tro.name_type)
        if mapped_type:
            item['infringement_types'].add(mapped_type)

        if tro.name_type in HIGH_RISK_NAME_TYPES:
            current_risk = 'high'
        elif tro.name_type in LOW_RISK_NAME_TYPES:
            current_risk = 'low'
        elif tro.name_type in TRADEMARK_CHECK_NAME_TYPES:
            current_risk = 'medium' if _is_medium_by_status_codes(status_code_map.get(norm, set())) else 'low'
        else:
            current_risk = 'low'

        item['risk_level'] = _max_risk_level(item['risk_level'], current_risk)

    for tm in trademark_objects:
        norm, item = ensure_item(tm.word_mark)
        if not item:
            continue

        if 'trademarks' not in item['sources']:
            item['sources'].append('trademarks')

        current_risk = 'medium' if _is_medium_by_status_codes(status_code_map.get(norm, set())) else 'low'
        item['risk_level'] = _max_risk_level(item['risk_level'], current_risk)

    high_risk_words = []
    medium_risk_words = []
    low_risk_words = []
    word_sources = []

    for item in merged.values():
        word = item['word']
        risk_level = item['risk_level']
        if risk_level == 'high':
            high_risk_words.append(word)
        elif risk_level == 'medium':
            medium_risk_words.append(word)
        else:
            low_risk_words.append(word)

        word_sources.append({
            'word': word,
            'risk_level': risk_level,
            'sources': item['sources'],
            'infringement_type': ', '.join(sorted(item['infringement_types'])) if item['infringement_types'] else '',
        })

    high_risk_words = _ordered_unique(high_risk_words)
    medium_risk_words = _ordered_unique(medium_risk_words)
    low_risk_words = _ordered_unique(low_risk_words)

    if high_risk_words:
        overall_risk = 'high'
    elif medium_risk_words:
        overall_risk = 'medium'
    else:
        overall_risk = 'low'

    word_sources.sort(key=lambda x: (-RISK_RANK.get(x['risk_level'], 0), x['word'].lower()))
    return {
        'risk_level': overall_risk,
        'high_risk_words': high_risk_words,
        'medium_risk_words': medium_risk_words,
        'low_risk_words': low_risk_words,
        'word_sources': word_sources,
    }


def _build_list_cache_key(payload):
    normalized_payload = {
        'shop_name': (payload.get('shop_name') or '').strip(),
        'shop_names': sorted(_normalize_text_list(payload.get('shop_names'))),
        'ops_groups': sorted(_normalize_text_list(payload.get('ops_groups'))),
        'operator_ids': sorted(_normalize_int_list(payload.get('operator_ids'))),
        'shop_owner': (payload.get('shop_owner') or '').strip(),
        'shop_owners': sorted(_normalize_text_list(payload.get('shop_owners'))),
        'asin': (payload.get('asin') or '').strip(),
        'infringement': (payload.get('infringement') or '').strip().lower(),
        'infringements': sorted(_normalize_text_list(payload.get('infringements'), lower=True)),
        'active_status': (payload.get('active_status') or 'all').strip().lower(),
        'active_statuses': sorted(_normalize_text_list(payload.get('active_statuses'), lower=True)),
        'listing_date_range': (payload.get('listing_date_range') or 'all').strip().lower(),
        'page': max(1, _safe_int(payload.get('page'), 1)),
        'page_size': min(max(1, _safe_int(payload.get('page_size'), 20)), 100),
    }
    return 'amazon_listing_mgmt:list:lite:' + json.dumps(normalized_payload, ensure_ascii=True, sort_keys=True)


def _build_stats_cache_key(payload):
    normalized_payload = {
        'shop_name': (payload.get('shop_name') or '').strip(),
        'shop_names': sorted(_normalize_text_list(payload.get('shop_names'))),
        'ops_groups': sorted(_normalize_text_list(payload.get('ops_groups'))),
        'operator_ids': sorted(_normalize_int_list(payload.get('operator_ids'))),
        'shop_owner': (payload.get('shop_owner') or '').strip(),
        'shop_owners': sorted(_normalize_text_list(payload.get('shop_owners'))),
        'asin': (payload.get('asin') or '').strip(),
        'infringement': (payload.get('infringement') or '').strip().lower(),
        'infringements': sorted(_normalize_text_list(payload.get('infringements'), lower=True)),
        'active_status': (payload.get('active_status') or 'all').strip().lower(),
        'active_statuses': sorted(_normalize_text_list(payload.get('active_statuses'), lower=True)),
        'listing_date_range': (payload.get('listing_date_range') or 'all').strip().lower(),
    }
    return 'amazon_listing_mgmt:stats:risk:' + json.dumps(normalized_payload, ensure_ascii=True, sort_keys=True)


def _aggregate_risk_totals(queryset):
    stats = queryset.aggregate(
        high_count=Count('id', filter=Q(risk_level='high')),
        medium_count=Count('id', filter=Q(risk_level='medium')),
    )
    return {
        'high_count': stats.get('high_count', 0) or 0,
        'medium_count': stats.get('medium_count', 0) or 0,
    }


def _compute_risk_totals(queryset):
    listings = list(queryset.prefetch_related('tro_words', 'trademarks'))
    if not listings:
        return {
            'high_count': 0,
            'medium_count': 0,
        }

    status_words = _collect_status_words_from_listings(listings)
    status_code_map = _build_status_code_map(status_words)

    high_count = 0
    medium_count = 0
    for listing in listings:
        risk = _build_listing_risk_data(listing, status_code_map=status_code_map)
        if risk['risk_level'] == 'high':
            high_count += 1
        elif risk['risk_level'] == 'medium':
            medium_count += 1

    return {
        'high_count': high_count,
        'medium_count': medium_count,
    }


def _build_filtered_listing_queryset(payload):
    shop_name_filter = (payload.get('shop_name') or '').strip()
    shop_name_filters = _normalize_text_list(payload.get('shop_names'))
    ops_group_filters = _normalize_text_list(payload.get('ops_groups'))
    operator_id_filters = _normalize_int_list(payload.get('operator_ids'))
    shop_owner_filter = (payload.get('shop_owner') or '').strip()
    shop_owner_filters = _normalize_text_list(payload.get('shop_owners'))
    asin_filter = (payload.get('asin') or '').strip()
    infringement_filter = (payload.get('infringement') or '').strip().lower()
    infringement_filters = set(_normalize_text_list(payload.get('infringements'), lower=True))
    active_status_filter = (payload.get('active_status') or 'all').strip().lower()
    active_status_filters = set(_normalize_text_list(payload.get('active_statuses'), lower=True))
    listing_date_range = (payload.get('listing_date_range') or 'all').strip().lower()

    queryset = AmazonListing.objects.select_related(
        'lingxing_shop',
        'lingxing_shop__amazon_shop',
        'lingxing_shop__amazon_shop__ops',
        'lingxing_shop__amazon_shop__ops__operational_account',
    ).filter(
        lingxing_shop__name__icontains='US',
    ).exclude(
        title__isnull=True,
    ).exclude(
        title__exact='',
    ).order_by('-updated_at')

    if shop_name_filters:
        queryset = queryset.filter(lingxing_shop__name__in=shop_name_filters)
    elif shop_name_filter:
        queryset = queryset.filter(lingxing_shop__name__icontains=shop_name_filter)

    if ops_group_filters:
        queryset = queryset.filter(
            lingxing_shop__amazon_shop__ops__operational_account__ops_group__in=ops_group_filters
        )
    if operator_id_filters:
        queryset = queryset.filter(lingxing_shop__amazon_shop__ops_id__in=operator_id_filters)

    # backward compatibility for legacy "shop_owner" filters
    if shop_owner_filters:
        queryset = queryset.filter(
            Q(lingxing_shop__amazon_shop__ops__first_name__in=shop_owner_filters)
            | Q(lingxing_shop__amazon_shop__ops__username__in=shop_owner_filters)
        )
    elif shop_owner_filter:
        queryset = queryset.filter(
            Q(lingxing_shop__amazon_shop__ops__first_name__icontains=shop_owner_filter)
            | Q(lingxing_shop__amazon_shop__ops__username__icontains=shop_owner_filter)
        )
    if asin_filter:
        queryset = queryset.filter(asin__icontains=asin_filter)
    if infringement_filters:
        selected_levels = {item for item in infringement_filters if item in {'high', 'medium', 'low', 'unknown'}}
        if selected_levels:
            risk_query = Q()
            direct_levels = selected_levels & {'high', 'medium', 'low'}
            if direct_levels:
                risk_query |= Q(risk_level__in=list(direct_levels))
            if 'unknown' in selected_levels:
                risk_query |= Q(risk_level='unknown') | Q(risk_level__isnull=True) | Q(risk_level='')
            queryset = queryset.filter(risk_query)
    elif infringement_filter in {'high', 'medium', 'low'}:
        queryset = queryset.filter(risk_level=infringement_filter)
    elif infringement_filter == 'unknown':
        queryset = queryset.filter(Q(risk_level='unknown') | Q(risk_level__isnull=True) | Q(risk_level=''))

    if active_status_filters:
        has_active = 'active' in active_status_filters
        has_inactive = 'inactive' in active_status_filters
        if has_active and not has_inactive:
            queryset = queryset.filter(is_active=True)
        elif has_inactive and not has_active:
            queryset = queryset.filter(is_active=False)
    elif active_status_filter == 'active':
        queryset = queryset.filter(is_active=True)
    elif active_status_filter == 'inactive':
        queryset = queryset.filter(is_active=False)

    date_range_days_map = {
        'last3days': 3,
        'last7days': 7,
        'last30days': 30,
    }
    if listing_date_range != 'all':
        days = date_range_days_map.get(listing_date_range, 3)
        queryset = queryset.filter(created_at__gte=timezone.now() - timedelta(days=days))

    return queryset


@login_required(login_url='/login/')
def views_amazon_listing_management(request):
    return render(request, 'amazon_listing_management.html', {
        'active_nav': 'amazon_orders',
        'active_page': 'amazon_listing_management',
    })


@login_required
@require_http_methods(['GET'])
def get_amazon_listing_management_filter_options_api(request):
    cache_key = 'amazon_listing_mgmt:filter_options:v2'
    cached_data = cache.get(cache_key)
    if cached_data is not None:
        return JsonResponse({'success': True, 'data': cached_data})

    base_queryset = AmazonListing.objects.filter(
        lingxing_shop__name__icontains='US',
    ).exclude(
        title__isnull=True,
    ).exclude(
        title__exact='',
    )

    raw_shop_names = base_queryset.values_list('lingxing_shop__name', flat=True).distinct()
    raw_ops_groups = base_queryset.values_list(
        'lingxing_shop__amazon_shop__ops__operational_account__ops_group',
        flat=True
    ).distinct()
    raw_operators = base_queryset.values(
        'lingxing_shop__amazon_shop__ops_id',
        'lingxing_shop__amazon_shop__ops__first_name',
        'lingxing_shop__amazon_shop__ops__username',
        'lingxing_shop__amazon_shop__ops__operational_account__ops_group',
    ).exclude(
        lingxing_shop__amazon_shop__ops_id__isnull=True
    ).distinct()

    shop_names = sorted(
        {(name or '').strip() for name in raw_shop_names if (name or '').strip()},
        key=lambda item: item.lower()
    )
    ops_groups = sorted(
        {(name or '').strip() for name in raw_ops_groups if (name or '').strip()},
        key=lambda item: item.lower()
    )
    operator_ids = [item.get('lingxing_shop__amazon_shop__ops_id') for item in raw_operators]
    ops_group_map = _build_ops_group_map(operator_ids)
    operators_map = {}
    for item in raw_operators:
        operator_id = item.get('lingxing_shop__amazon_shop__ops_id')
        if not operator_id:
            continue
        group_name = (
            (ops_group_map.get(operator_id) or '').strip()
            or (item.get('lingxing_shop__amazon_shop__ops__operational_account__ops_group') or '').strip()
            or '未分组'
        )
        display_name = (
            (item.get('lingxing_shop__amazon_shop__ops__first_name') or '').strip()
            or (item.get('lingxing_shop__amazon_shop__ops__username') or '').strip()
            or '-'
        )
        operators_map[operator_id] = {
            'value': operator_id,
            'label': f'{display_name} ({group_name})',
            'group': group_name,
        }

    operators = sorted(
        operators_map.values(),
        key=lambda row: ((row.get('group') or '').lower(), (row.get('label') or '').lower())
    )
    # backward compatibility for old owner dropdown
    shop_owners = sorted(
        {
            (item.get('lingxing_shop__amazon_shop__ops__first_name') or '').strip()
            or (item.get('lingxing_shop__amazon_shop__ops__username') or '').strip()
            for item in raw_operators
            if (
                (item.get('lingxing_shop__amazon_shop__ops__first_name') or '').strip()
                or (item.get('lingxing_shop__amazon_shop__ops__username') or '').strip()
            )
        },
        key=lambda text: text.lower()
    )

    response_data = {
        'shop_names': shop_names,
        'ops_groups': ops_groups,
        'operators': operators,
        # backward compatibility
        'shop_owners': shop_owners,
        'infringements': ['high', 'medium', 'low', 'unknown'],
        'active_statuses': ['active', 'inactive'],
    }
    cache.set(cache_key, response_data, FILTER_OPTIONS_CACHE_TTL_SECONDS)
    return JsonResponse({'success': True, 'data': response_data})


@login_required
@require_http_methods(['POST'])
def get_amazon_listing_management_list_api(request):
    """
    Light list API: returns listing fields and persisted risk level from DB.
    """
    try:
        payload = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'message': 'Invalid JSON body'}, status=400)

    req_started = time.perf_counter()
    cache_key = _build_list_cache_key(payload)
    cached_response = cache.get(cache_key)
    if cached_response is not None:
        cached_response['data']['server_timing_ms'] = {
            'total': round((time.perf_counter() - req_started) * 1000, 2),
            'cache_hit': True,
        }
        return JsonResponse(cached_response)

    page = max(1, _safe_int(payload.get('page'), 1))
    page_size = min(max(1, _safe_int(payload.get('page_size'), 20)), 100)
    queryset = _build_filtered_listing_queryset(payload)
    stats_data = _aggregate_risk_totals(queryset)

    paginator = Paginator(queryset, page_size)
    try:
        page_obj = paginator.page(page)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)

    listing_operator_ids = [
        getattr(getattr(getattr(item, 'lingxing_shop', None), 'amazon_shop', None), 'ops_id', None)
        for item in page_obj
    ]
    ops_group_map = _build_ops_group_map(listing_operator_ids)
    rows = []
    for listing in page_obj:
        risk_level = (listing.risk_level or '').strip().lower()
        if risk_level not in {'high', 'medium', 'low', 'unknown'}:
            risk_level = 'unknown' if risk_level else ''
        operator_name = _extract_operator_name(listing)
        rows.append({
            'id': listing.id,
            'amazon_shop_name': _extract_amazon_shop_name(listing),
            'shop_name': (listing.lingxing_shop.name or '').strip(),
            'operator_id': getattr(getattr(getattr(listing, 'lingxing_shop', None), 'amazon_shop', None), 'ops_id', None),
            'operator_name': operator_name,
            'ops_group': _extract_ops_group_name(listing, ops_group_map=ops_group_map),
            # backward compatibility
            'shop_owner': operator_name,
            'asin': listing.asin,
            'title': (listing.title or '').strip(),
            'risk_level': risk_level,
        })

    response_payload = {
        'success': True,
        'data': {
            'listings': rows,
            'total': paginator.count,
            'page': page_obj.number,
            'page_size': page_size,
            'total_pages': paginator.num_pages,
            'stats': {
                'total_count': paginator.count,
                'high_count': stats_data.get('high_count', 0),
                'medium_count': stats_data.get('medium_count', 0),
            },
            'server_timing_ms': {
                'total': round((time.perf_counter() - req_started) * 1000, 2),
                'cache_hit': False,
            },
        }
    }
    cache.set(cache_key, response_payload, LIST_API_CACHE_TTL_SECONDS)
    return JsonResponse(response_payload)


@login_required
@require_http_methods(['POST'])
def get_amazon_listing_management_risk_stats_api(request):
    try:
        payload = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'message': 'Invalid JSON body'}, status=400)

    stats_cache_key = _build_stats_cache_key(payload)
    stats_data = cache.get(stats_cache_key)
    if stats_data is None:
        queryset = _build_filtered_listing_queryset(payload)
        stats_data = _aggregate_risk_totals(queryset)
        cache.set(stats_cache_key, stats_data, LIST_API_CACHE_TTL_SECONDS)

    return JsonResponse({
        'success': True,
        'data': {
            'high_count': stats_data.get('high_count', 0),
            'medium_count': stats_data.get('medium_count', 0),
        }
    })


@login_required
@require_http_methods(['POST'])
def get_amazon_listing_batch_risk_check_api(request):
    """
    Batch risk API for current page titles, similar to theme/products flow.
    """
    try:
        payload = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'message': 'Invalid JSON body'}, status=400)

    listing_ids = payload.get('listing_ids') or []
    if not isinstance(listing_ids, list):
        return JsonResponse({'success': False, 'message': 'listing_ids must be a list'}, status=400)

    normalized_ids = []
    seen = set()
    for listing_id in listing_ids:
        safe_id = _safe_int(listing_id, 0)
        if safe_id <= 0 or safe_id in seen:
            continue
        seen.add(safe_id)
        normalized_ids.append(safe_id)

    if not normalized_ids:
        return JsonResponse({'success': True, 'data': {}})

    listings = list(
        AmazonListing.objects.prefetch_related('tro_words', 'trademarks').filter(id__in=normalized_ids)
    )
    listing_map = {item.id: item for item in listings}
    status_words = _collect_status_words_from_listings(listings)
    status_code_map = _build_status_code_map(status_words)

    response_data = {}
    for listing_id in normalized_ids:
        listing = listing_map.get(listing_id)
        if not listing:
            continue

        risk = _build_listing_risk_data(listing, status_code_map=status_code_map)
        response_data[str(listing_id)] = {
            'theme_risk_level': risk['risk_level'],
            'high_risk_words': risk['high_risk_words'],
            'medium_risk_words': risk['medium_risk_words'],
        }

    return JsonResponse({'success': True, 'data': response_data})


@login_required
@require_http_methods(['GET'])
def get_amazon_listing_word_sources_api(request, listing_id):
    listing = AmazonListing.objects.select_related(
        'lingxing_shop',
        'lingxing_shop__amazon_shop',
        'lingxing_shop__amazon_shop__ops',
    ).prefetch_related(
        'tro_words',
        'trademarks',
    ).filter(id=listing_id).first()

    if not listing:
        return JsonResponse({'success': False, 'message': 'Listing not found'}, status=404)

    status_words = _collect_status_words_from_listings([listing])
    status_code_map = _build_status_code_map(status_words)
    risk = _build_listing_risk_data(listing, status_code_map=status_code_map)
    word_sources = [item for item in risk['word_sources'] if item['risk_level'] != 'low']

    return JsonResponse({
        'success': True,
        'data': {
            'listing_id': listing.id,
            'asin': listing.asin,
            'title': (listing.title or '').strip(),
            'infringement_level': risk['risk_level'],
            'word_sources': word_sources,
        }
    })
