import json
from datetime import datetime

from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.db import connection
from django.db.models import Max, Min
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from theme.models import (
    AmazonNewReleaseRank,
    DailyRecommendedThemeV2,
    RecommendedThemeAsin,
    ThemeNewDailyData,
)
from theme.view.permissions import theme_access_required


NEW_RELEASE_SOURCE = DailyRecommendedThemeV2.Source.NEW_RELEASE
ABA_SOURCE = DailyRecommendedThemeV2.Source.ABA
ALLOWED_PERIOD_TYPES = {
    DailyRecommendedThemeV2.PeriodType.DAY,
    DailyRecommendedThemeV2.PeriodType.WEEK,
    DailyRecommendedThemeV2.PeriodType.MONTH,
}
ALLOWED_SOURCES = {
    DailyRecommendedThemeV2.Source.NOVELTY,
    DailyRecommendedThemeV2.Source.NEW_RELEASE,
    DailyRecommendedThemeV2.Source.ABA,
}
ALLOWED_PAGE_SIZES = {20, 50, 100, 200}


def _parse_date(value):
    value = str(value or "").strip()
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _date_to_str(value):
    return value.strftime("%Y-%m-%d") if value else ""


def _json_value(value):
    if isinstance(value, (dict, list)):
        return value
    return {}


def _split_filter_values(value):
    if isinstance(value, list):
        raw_values = value
    else:
        raw_values = str(value or "").split(",")
    return [str(item).strip() for item in raw_values if str(item).strip()]


def _positive_int(value, default):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _has_table_column(model, column_name):
    try:
        with connection.cursor() as cursor:
            columns = {
                column.name
                for column in connection.introspection.get_table_description(
                    cursor, model._meta.db_table
                )
            }
    except Exception:
        return False
    return column_name in columns


def _new_release_asin_count_for_snapshot(cluster_id, snapshot_date):
    if not cluster_id or not snapshot_date:
        return 0
    return AmazonNewReleaseRank.objects.filter(
        fingerprint__cluster_id=cluster_id,
        created_at__date=snapshot_date,
    ).count()


def _valid_source_values(value):
    return [
        source
        for source in _split_filter_values(value)
        if source in ALLOWED_SOURCES
    ]


def _new_release_daily_rank_lookup(snapshot_date, asins):
    if not snapshot_date or not asins:
        return {}
    rows = (
        ThemeNewDailyData.objects.filter(
            product__asin__in=asins,
            crawl_date=snapshot_date,
        )
        .values(
            "product__asin",
            "rank",
            "rank2",
            "rank3",
            "score",
            "appear_count",
            "crawl_date",
        )
    )
    return {row["product__asin"]: row for row in rows}


def _new_release_calculated_score(count, launch_date, rank, reference_date):
    try:
        count_value = int(count or 0)
    except (TypeError, ValueError):
        count_value = 0

    count_score = (
        5
        if count_value > 10
        else 4
        if count_value > 6
        else 3
        if count_value > 3
        else 2
        if count_value > 1
        else 1
    )

    if launch_date and reference_date:
        days_diff = (reference_date - launch_date).days
        time_score = (
            5
            if days_diff <= 1
            else 4
            if days_diff <= 3
            else 3
            if days_diff <= 7
            else 2
            if days_diff <= 15
            else 1
        )
    else:
        time_score = 1

    rank_score = 5 if rank not in (None, "") else 0
    return count_score + time_score + rank_score


def _new_release_effective_score(stored_score, daily_stats, launch_date, reference_date):
    if stored_score not in (None, 0):
        return stored_score

    raw_score = daily_stats.get("score")
    if raw_score not in (None, 0):
        return raw_score

    if not daily_stats:
        return stored_score

    return _new_release_calculated_score(
        daily_stats.get("appear_count") or 1,
        launch_date,
        daily_stats.get("rank"),
        reference_date,
    )


@theme_access_required
def recommended_theme_page(request):
    qs = DailyRecommendedThemeV2.objects.all()
    has_theme_category = _has_table_column(DailyRecommendedThemeV2, "category")

    date_range = qs.aggregate(
        min_snapshot_date=Min("snapshot_date"),
        max_snapshot_date=Max("snapshot_date"),
    )
    category_options = []
    if has_theme_category:
        category_options = list(
            qs.exclude(category__isnull=True)
            .exclude(category="")
            .values_list("category", flat=True)
            .distinct()
            .order_by("category")
        )

    context = {
        "page_title": "推荐主题",
        "active_nav": "theme_recommended",
        "active_page": "theme_recommended_page",
        "date_range": date_range,
        "category_options": category_options,
        "source_options": DailyRecommendedThemeV2.Source.choices,
    }
    return render(request, "recommended_theme.html", context)


@theme_access_required
@csrf_exempt
@require_POST
def api_recommended_theme_list(request):
    try:
        data = json.loads(request.body or "{}")

        period_type = str(data.get("period_type", "day") or "day").strip().lower()
        if period_type not in ALLOWED_PERIOD_TYPES:
            return JsonResponse(
                {"success": False, "message": "period_type 仅支持 day/week/month"},
                status=400,
            )

        qs = DailyRecommendedThemeV2.objects.filter(period_type=period_type)
        has_theme_category = _has_table_column(DailyRecommendedThemeV2, "category")

        source_values = _valid_source_values(data.get("source"))
        if source_values:
            qs = qs.filter(source__in=source_values)

        snapshot_date = _parse_date(data.get("snapshot_date"))
        if snapshot_date:
            qs = qs.filter(snapshot_date=snapshot_date)
        else:
            snapshot_date_start = _parse_date(data.get("snapshot_date_start"))
            snapshot_date_end = _parse_date(data.get("snapshot_date_end"))
            if snapshot_date_start:
                qs = qs.filter(snapshot_date__gte=snapshot_date_start)
            if snapshot_date_end:
                qs = qs.filter(snapshot_date__lte=snapshot_date_end)

        category_values = _split_filter_values(data.get("category"))
        if category_values and has_theme_category:
            qs = qs.filter(category__in=category_values)

        reason_values = _split_filter_values(data.get("reason_type"))
        if reason_values:
            qs = qs.filter(reason_type__in=reason_values)

        theme_search = str(data.get("theme_search", "") or "").strip()
        if theme_search:
            qs = qs.filter(theme__icontains=theme_search)

        sort_field = str(data.get("sort_field", "") or "").strip()
        sort_order = str(data.get("sort_order", "desc") or "desc").strip().lower()
        sort_map = {
            "snapshot_date": "snapshot_date",
            "window_start": "window_start",
            "window_end": "window_end",
            "source_date": "source_date",
            "reason_type": "reason_type",
            "theme": "theme",
            "source": "source",
            "asin_count": "asin_count",
            "metric_value": "metric_value",
            "created_at": "created_at",
        }
        if has_theme_category:
            sort_map["category"] = "category"
        if sort_field in sort_map:
            order_field = sort_map[sort_field]
            if sort_order == "desc":
                order_field = f"-{order_field}"
            qs = qs.order_by(order_field, "-snapshot_date", "-metric_value", "-created_at")
        else:
            qs = qs.order_by("-asin_count", "-snapshot_date", "-metric_value", "-created_at")

        page = _positive_int(data.get("page", 1), 1)
        page_size = _positive_int(data.get("page_size", 20), 20)
        if page_size not in ALLOWED_PAGE_SIZES:
            page_size = 20

        paginator = Paginator(qs, page_size)
        try:
            current_page = paginator.page(page)
        except PageNotAnInteger:
            current_page = paginator.page(1)
        except EmptyPage:
            current_page = paginator.page(paginator.num_pages)

        value_fields = [
            "id",
            "period_type",
            "snapshot_date",
            "window_start",
            "window_end",
            "source",
            "reason_type",
            "theme",
            "source_object_id",
            "source_date",
            "asin_count",
            "metric_value",
            "metrics",
        ]
        if has_theme_category:
            value_fields.append("category")

        reason_label_map = dict(DailyRecommendedThemeV2.ReasonType.choices)
        source_label_map = dict(DailyRecommendedThemeV2.Source.choices)
        theme_rows = []
        for item in current_page.object_list.values(*value_fields):
            theme_rows.append(
                {
                    "id": item["id"],
                    "period_type": item["period_type"],
                    "snapshot_date": _date_to_str(item["snapshot_date"]),
                    "window_start": _date_to_str(item["window_start"]),
                    "window_end": _date_to_str(item["window_end"]),
                    "source": item["source"],
                    "reason_type": item["reason_type"],
                    "reason_label": reason_label_map.get(
                        item["reason_type"], item["reason_type"]
                    ),
                    "source_label": source_label_map.get(
                        item["source"], item["source"]
                    ),
                    "theme": item["theme"] or "",
                    "category": item.get("category") or "",
                    "source_object_id": item["source_object_id"],
                    "source_date": _date_to_str(item["source_date"]),
                    "asin_count": item["asin_count"],
                    "metric_value": item["metric_value"],
                    "metrics": _json_value(item["metrics"]),
                }
            )

        stats_qs = DailyRecommendedThemeV2.objects.all()
        if source_values:
            stats_qs = stats_qs.filter(source__in=source_values)
        stats = {
            "total": stats_qs.count(),
            "period_total": paginator.count,
            "day_total": stats_qs.filter(period_type=DailyRecommendedThemeV2.PeriodType.DAY).count(),
            "week_total": stats_qs.filter(period_type=DailyRecommendedThemeV2.PeriodType.WEEK).count(),
            "month_total": stats_qs.filter(period_type=DailyRecommendedThemeV2.PeriodType.MONTH).count(),
        }

        return JsonResponse(
            {
                "success": True,
                "data": {
                    "themes": theme_rows,
                    "total": paginator.count,
                    "total_pages": paginator.num_pages,
                    "current_page": current_page.number,
                    "page_size": page_size,
                    "has_next": current_page.has_next(),
                    "has_previous": current_page.has_previous(),
                    "next_page": current_page.next_page_number()
                    if current_page.has_next()
                    else None,
                    "previous_page": current_page.previous_page_number()
                    if current_page.has_previous()
                    else None,
                    "stats": stats,
                },
            }
        )
    except json.JSONDecodeError:
        return JsonResponse(
            {"success": False, "message": "无效的JSON数据格式"}, status=400
        )
    except Exception as exc:
        return JsonResponse(
            {"success": False, "message": f"服务器内部错误: {exc}"}, status=500
        )


@theme_access_required
@csrf_exempt
@require_POST
def api_recommended_theme_asins(request):
    try:
        data = json.loads(request.body or "{}")
        recommended_theme_id = data.get("recommended_theme_id") or data.get("theme_id")
        if not recommended_theme_id:
            return JsonResponse(
                {"success": False, "message": "缺少 recommended_theme_id 参数"},
                status=400,
            )

        parent = DailyRecommendedThemeV2.objects.filter(id=recommended_theme_id).first()
        if not parent:
            return JsonResponse(
                {"success": False, "message": "推荐主题不存在"},
                status=404,
            )

        stored_asins = list(
            RecommendedThemeAsin.objects.filter(
                recommended_theme=parent,
            ).order_by("source_position")
        )
        if stored_asins:
            rank_lookup = {}
            if (
                parent.source == NEW_RELEASE_SOURCE
                and parent.period_type == DailyRecommendedThemeV2.PeriodType.DAY
            ):
                missing_rank_asins = [
                    sa.asin
                    for sa in stored_asins
                    if sa.asin and (sa.rank is None or sa.score in (None, 0))
                ]
                rank_lookup = _new_release_daily_rank_lookup(
                    parent.snapshot_date,
                    missing_rank_asins,
                )

            asin_rows = [
                {
                    "asin": sa.asin or "",
                    "title": sa.title or "",
                    "category": sa.category or "",
                    "launch_date": _date_to_str(sa.launch_date),
                    "rank": sa.rank
                    if sa.rank is not None
                    else rank_lookup.get(sa.asin, {}).get("rank"),
                    "score": _new_release_effective_score(
                        sa.score,
                        rank_lookup.get(sa.asin, {}),
                        sa.launch_date,
                        parent.snapshot_date,
                    ),
                    "source_position": sa.source_position,
                    "metrics": {
                        **(sa.metrics or {}),
                        **(
                            {
                                "crawl_date": _date_to_str(
                                    rank_lookup.get(sa.asin, {}).get("crawl_date")
                                ),
                                "raw_score": rank_lookup.get(sa.asin, {}).get("score"),
                                "appear_count": rank_lookup.get(sa.asin, {}).get("appear_count"),
                                "rank2": rank_lookup.get(sa.asin, {}).get("rank2"),
                                "rank3": rank_lookup.get(sa.asin, {}).get("rank3"),
                            }
                            if sa.asin in rank_lookup
                            else {}
                        ),
                    },
                }
                for sa in stored_asins
            ]
        elif (
            parent.source == NEW_RELEASE_SOURCE
            and parent.period_type == DailyRecommendedThemeV2.PeriodType.DAY
        ):
            product_rows = list(
                AmazonNewReleaseRank.objects.filter(
                    fingerprint__cluster_id=parent.source_object_id,
                    created_at__date=parent.snapshot_date,
                )
                .values("asin", "title", "category", "launch_date", "created_at")
                .order_by("-created_at", "asin")
            )
            asin_rows = [
                {
                    "asin": item["asin"] or "",
                    "title": item["title"] or "",
                    "category": item["category"] or "",
                    "launch_date": _date_to_str(item["launch_date"]),
                    "rank": None,
                    "score": None,
                    "source_position": index,
                    "metrics": {
                        "created_at": item["created_at"].isoformat()
                        if item.get("created_at")
                        else None
                    },
                }
                for index, item in enumerate(product_rows, start=1)
            ]
        elif parent.source == ABA_SOURCE:
            top_asins = _json_value(parent.metrics).get("top_asins") or []
            metric_json = _json_value(parent.metrics)
            asin_rows = [
                {
                    "asin": item.get("asin") or "",
                    "title": item.get("title") or "",
                    "category": parent.category or "",
                    "launch_date": "",
                    "rank": metric_json.get("search_frequency_rank"),
                    "score": None,
                    "source_position": index,
                    "metrics": item,
                }
                for index, item in enumerate(top_asins, start=1)
                if isinstance(item, dict)
            ]
        else:
            asin_rows = []

        return JsonResponse(
            {
                "success": True,
                "data": {
                    "asins": asin_rows,
                    "total": len(asin_rows),
                },
            }
        )

    except json.JSONDecodeError:
        return JsonResponse(
            {"success": False, "message": "无效的JSON数据格式"}, status=400
        )
    except Exception as exc:
        return JsonResponse(
            {"success": False, "message": f"服务器内部错误: {exc}"}, status=500
        )
