from django.contrib.auth.decorators import login_required
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.db.models import Max, Min, OuterRef, Subquery
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from datetime import datetime, timedelta
import json

from theme.models import AmazonNewReleaseRank, ThemeNewDailyData


@login_required
def new_release_page(request):
    total_products = AmazonNewReleaseRank.objects.count()

    seven_days_ago = timezone.now().date() - timedelta(days=7)
    recent_subjects_7d = (
        AmazonNewReleaseRank.objects.filter(launch_date__gte=seven_days_ago)
        .exclude(subject__isnull=True)
        .exclude(subject='')
        .values('subject')
        .distinct()
        .count()
    )

    now = timezone.now()
    first_day_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    recent_products = AmazonNewReleaseRank.objects.filter(created_at__gte=first_day_of_month).count()

    product_date_range = AmazonNewReleaseRank.objects.aggregate(
        min_launch_date=Min('launch_date'),
        max_launch_date=Max('launch_date'),
    )
    daily_date_range = ThemeNewDailyData.objects.aggregate(
        min_crawl_date=Min('crawl_date'),
        max_crawl_date=Max('crawl_date'),
    )

    category_options = list(
        AmazonNewReleaseRank.objects.exclude(category__isnull=True)
        .exclude(category='')
        .values_list('category', flat=True)
        .distinct()
        .order_by('category')
    )

    context = {
        'page_title': '亚马逊最新成交主题',
        'active_nav': 'theme_new_release',
        'stats': {
            'total_products': total_products,
            'recent_subjects_7d': recent_subjects_7d,
            'recent_products': recent_products,
        },
        'date_range': {
            'min_launch_date': product_date_range['min_launch_date'],
            'max_launch_date': product_date_range['max_launch_date'],
            'min_crawl_date': daily_date_range['min_crawl_date'],
            'max_crawl_date': daily_date_range['max_crawl_date'],
        },
        'category_options': category_options,
    }
    return render(request, 'new_release.html', context)


@csrf_exempt
@require_POST
def api_new_release_list(request):
    try:
        data = json.loads(request.body or '{}')

        filtered_queryset = ThemeNewDailyData.objects.select_related('product').all()

        category_values = [value.strip() for value in str(data.get('category', '')).split(',') if value.strip()]
        if category_values:
            filtered_queryset = filtered_queryset.filter(product__category__in=category_values)

        launch_date_start = str(data.get('launch_date_start', '')).strip()
        launch_date_end = str(data.get('launch_date_end', '')).strip()
        crawl_date_start = str(data.get('created_at_start', '')).strip()
        crawl_date_end = str(data.get('created_at_end', '')).strip()

        if launch_date_start:
            try:
                filtered_queryset = filtered_queryset.filter(
                    product__launch_date__gte=datetime.strptime(launch_date_start, '%Y-%m-%d').date()
                )
            except ValueError:
                pass
        if launch_date_end:
            try:
                filtered_queryset = filtered_queryset.filter(
                    product__launch_date__lte=datetime.strptime(launch_date_end, '%Y-%m-%d').date()
                )
            except ValueError:
                pass
        if crawl_date_start:
            try:
                filtered_queryset = filtered_queryset.filter(
                    crawl_date__gte=datetime.strptime(crawl_date_start, '%Y-%m-%d').date()
                )
            except ValueError:
                pass
        if crawl_date_end:
            try:
                filtered_queryset = filtered_queryset.filter(
                    crawl_date__lte=datetime.strptime(crawl_date_end, '%Y-%m-%d').date()
                )
            except ValueError:
                pass

        latest_record_subquery = (
            filtered_queryset.model.objects.filter(product_id=OuterRef('product_id'))
            .filter(pk__in=filtered_queryset.values('pk'))
            .order_by('-crawl_date', '-crawled_at', '-id')
            .values('id')[:1]
        )
        queryset = filtered_queryset.filter(id=Subquery(latest_record_subquery))

        sort_field = str(data.get('sort_field', 'score')).strip()
        sort_order = str(data.get('sort_order', 'desc')).strip().lower()
        sort_map = {
            'subject': 'product__subject',
            'score': 'score',
            'appear_count': 'appear_count',
            'launch_date': 'product__launch_date',
            'crawl_date': 'crawl_date',
            'category': 'product__category',
        }
        real_sort_field = sort_map.get(sort_field, 'score')
        if sort_order == 'desc':
            real_sort_field = f'-{real_sort_field}'
        queryset = queryset.order_by(real_sort_field, '-crawl_date', '-crawled_at', '-id')

        page = int(data.get('page', 1) or 1)
        page_size = int(data.get('page_size', 20) or 20)
        if page_size not in (20, 50, 100, 200):
            page_size = 20

        paginator = Paginator(queryset, page_size)
        try:
            current_page = paginator.page(page)
        except PageNotAnInteger:
            current_page = paginator.page(1)
        except EmptyPage:
            current_page = paginator.page(paginator.num_pages)

        current_asins = [item.product.asin for item in current_page.object_list]
        trend_rows = (
            ThemeNewDailyData.objects.filter(product__asin__in=current_asins)
            .order_by('product__asin', 'crawl_date')
            .values('product__asin', 'crawl_date', 'rank')
        )
        rank_trend_lookup = {}
        for row in trend_rows:
            asin = row['product__asin']
            rank_trend_lookup.setdefault(asin, []).append(
                {
                    'date': row['crawl_date'].strftime('%Y-%m-%d') if row['crawl_date'] else None,
                    'rank': row['rank'],
                }
            )
        for asin, trend_points in rank_trend_lookup.items():
            rank_trend_lookup[asin] = trend_points[-7:]

        product_rows = []
        for item in current_page.object_list:
            product_rows.append(
                {
                    'id': item.id,
                    'asin': item.product.asin,
                    'subject': item.product.subject or '',
                    'subject_translation': item.product.subject_translation or '',
                    'image_url': item.product.image_url or '',
                    'score': item.score,
                    'appear_count': item.appear_count,
                    'launch_date': item.product.launch_date.strftime('%Y-%m-%d') if item.product.launch_date else '',
                    'crawl_date': item.crawl_date.strftime('%Y-%m-%d') if item.crawl_date else '',
                    'category': item.product.category or '',
                    'rank_category': item.rank_category or '',
                    'rank': item.rank,
                    'rank_category2': item.rank_category2 or '',
                    'rank2': item.rank2,
                    'rank_category3': item.rank_category3 or '',
                    'rank3': item.rank3,
                    'rank_trend_7d': rank_trend_lookup.get(item.product.asin, []),
                }
            )

        now = timezone.now()
        first_day_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        stats = {
            'total_products': AmazonNewReleaseRank.objects.count(),
            'recent_subjects_7d': (
                AmazonNewReleaseRank.objects.filter(launch_date__gte=timezone.now().date() - timedelta(days=7))
                .exclude(subject__isnull=True)
                .exclude(subject='')
                .values('subject')
                .distinct()
                .count()
            ),
            'recent_products': AmazonNewReleaseRank.objects.filter(created_at__gte=first_day_of_month).count(),
        }

        return JsonResponse(
            {
                'success': True,
                'data': {
                    'products': product_rows,
                    'total': paginator.count,
                    'total_pages': paginator.num_pages,
                    'current_page': current_page.number,
                    'page_size': page_size,
                    'has_next': current_page.has_next(),
                    'has_previous': current_page.has_previous(),
                    'next_page': current_page.next_page_number() if current_page.has_next() else None,
                    'previous_page': current_page.previous_page_number() if current_page.has_previous() else None,
                    'stats': stats,
                },
            }
        )
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'message': '无效的JSON数据格式'}, status=400)
    except Exception as exc:
        return JsonResponse({'success': False, 'message': f'服务器内部错误: {exc}'}, status=500)





