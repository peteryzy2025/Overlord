from django.contrib.auth.decorators import login_required
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.db.models import (
    Avg,
    Count,
    F,
    Max,
    Min,
    OuterRef,
    Q,
    Subquery,
    Value,
    FloatField,
)
from django.db.models.functions import Coalesce
from django.db.models.expressions import RawSQL
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from datetime import datetime, timedelta
import json

from theme.models import (
    AmazonNewReleaseRank,
    AmazonThemeCluster,
    ThemeNewDailyData,
    ThemeSummary,
)
from theme.view.permissions import theme_access_required


@theme_access_required
def new_release_page(request):
    total_products = AmazonNewReleaseRank.objects.count()

    seven_days_ago = timezone.now().date() - timedelta(days=7)
    recent_subjects_7d = (  # 最近7天的主题数量有几条
        AmazonNewReleaseRank.objects.filter(launch_date__gte=seven_days_ago)
        .exclude(subject__isnull=True)
        .exclude(subject="")
        .values("subject")
        .distinct()
        .count()
    )

    now = timezone.now()
    first_day_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    recent_products = AmazonNewReleaseRank.objects.filter(
        created_at__gte=first_day_of_month
    ).count()  # 本月上架产品数量

    product_date_range = AmazonNewReleaseRank.objects.aggregate(
        min_launch_date=Min("launch_date"),
        max_launch_date=Max("launch_date"),
    )
    daily_date_range = ThemeNewDailyData.objects.aggregate(
        min_crawl_date=Min("crawl_date"),
        max_crawl_date=Max("crawl_date"),
    )

    category_options = list(
        AmazonNewReleaseRank.objects.exclude(category__isnull=True)
        .exclude(category="")
        .values_list("category", flat=True)
        .distinct()
        .order_by("category")
    )
    # ===============以下是针对ThemeSummary==========================================
    total_themes = ThemeSummary.objects.count()  # 聚合主题总条数
    recent_themes_7d = (  # 7天聚合主题数
        ThemeSummary.objects.filter(
            summary_subject__updated_at__gte=timezone.now() - timedelta(days=7)
        )
        .distinct()
        .count()
    )
    recent_themes_month = (  # 本月迄今为止聚合主题数
        ThemeSummary.objects.filter(summary_subject__updated_at__gte=first_day_of_month)
        .distinct()
        .count()
    )
    # ===============以下是针对 AmazonThemeCluster (三层架构) ==================
    total_clusters = AmazonThemeCluster.objects.count()
    recent_clusters_7d = AmazonThemeCluster.objects.filter(
        created_at__gte=now - timedelta(days=7)
    ).count()
    recent_clusters_month = AmazonThemeCluster.objects.filter(
        created_at__gte=first_day_of_month
    ).count()

    context = {
        "page_title": "亚马逊最新成交主题",
        "active_nav": "theme_new_release",
        "active_page": "theme_new_release_page",
        "stats": {  # 新品榜顶部卡
            "total_products": total_products,
            "recent_subjects_7d": recent_subjects_7d,
            "recent_products": recent_products,
        },
        "aggregation_stats": {  # 主题聚合顶部卡 (旧 ThemeSummary)
            "total_themes": total_themes,
            "recent_themes_7d": recent_themes_7d,
            "recent_themes_month": recent_themes_month,
        },
        "cluster_stats": {  # 主题聚合顶部卡 (新三层架构)
            "total_themes": total_clusters,
            "recent_themes_7d": recent_clusters_7d,
            "recent_themes_month": recent_clusters_month,
        },
        "date_range": {  # 时间筛选
            "min_launch_date": product_date_range["min_launch_date"],
            "max_launch_date": product_date_range["max_launch_date"],
            "min_crawl_date": daily_date_range["min_crawl_date"],
            "max_crawl_date": daily_date_range["max_crawl_date"],
        },
        "category_options": category_options,  # 品类筛选
    }
    return render(request, "new_release.html", context)


@theme_access_required
@csrf_exempt
@require_POST
def api_new_release_list(request):
    try:
        data = json.loads(request.body or "{}")

        filtered_queryset = ThemeNewDailyData.objects.select_related("product").all()

        category_values = [
            value.strip()
            for value in str(data.get("category", "")).split(",")
            if value.strip()
        ]
        if (
            category_values
        ):  # if前端传入category,则筛出category列含有category_values列表中的品类的数据行
            filtered_queryset = filtered_queryset.filter(
                product__category__in=category_values
            )

        launch_date_start = str(data.get("launch_date_start", "")).strip()
        launch_date_end = str(data.get("launch_date_end", "")).strip()
        crawl_date_start = str(data.get("created_at_start", "")).strip()
        crawl_date_end = str(data.get("created_at_end", "")).strip()

        if launch_date_start:
            try:
                filtered_queryset = filtered_queryset.filter(
                    product__launch_date__gte=datetime.strptime(
                        launch_date_start, "%Y-%m-%d"
                    ).date()
                )
            except ValueError:
                pass
        if launch_date_end:
            try:
                filtered_queryset = filtered_queryset.filter(
                    product__launch_date__lte=datetime.strptime(
                        launch_date_end, "%Y-%m-%d"
                    ).date()
                )
            except ValueError:
                pass
        if crawl_date_start:
            try:
                filtered_queryset = filtered_queryset.filter(
                    crawl_date__gte=datetime.strptime(
                        crawl_date_start, "%Y-%m-%d"
                    ).date()
                )
            except ValueError:
                pass
        if crawl_date_end:
            try:
                filtered_queryset = filtered_queryset.filter(
                    crawl_date__lte=datetime.strptime(crawl_date_end, "%Y-%m-%d").date()
                )
            except ValueError:
                pass

        latest_record_subquery = (
            filtered_queryset.model.objects.filter(product_id=OuterRef("product_id"))
            .filter(pk__in=filtered_queryset.values("pk"))
            .order_by("-crawl_date", "-crawled_at", "-id")
            .values("id")[:1]
        )
        queryset = filtered_queryset.filter(id=Subquery(latest_record_subquery))

        sort_field = str(data.get("sort_field", "score")).strip()
        sort_order = str(data.get("sort_order", "desc")).strip().lower()
        sort_map = {
            "subject": "product__subject",
            "score": "score",
            "appear_count": "appear_count",
            "launch_date": "product__launch_date",
            "crawl_date": "crawl_date",
            "category": "product__category",
        }
        real_sort_field = sort_map.get(sort_field, "score")
        if sort_order == "desc":
            real_sort_field = f"-{real_sort_field}"
        queryset = queryset.order_by(
            real_sort_field, "-crawl_date", "-crawled_at", "-id"
        )

        page = int(data.get("page", 1) or 1)
        page_size = int(data.get("page_size", 20) or 20)
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
            .order_by("product__asin", "crawl_date")
            .values("product__asin", "crawl_date", "rank")
        )
        rank_trend_lookup = {}
        for row in trend_rows:
            asin = row["product__asin"]
            rank_trend_lookup.setdefault(asin, []).append(
                {
                    "date": row["crawl_date"].strftime("%Y-%m-%d")
                    if row["crawl_date"]
                    else None,
                    "rank": row["rank"],
                }
            )
        for asin, trend_points in rank_trend_lookup.items():
            rank_trend_lookup[asin] = trend_points[-7:]

        product_rows = []
        for item in current_page.object_list:
            product_rows.append(
                {
                    "id": item.id,
                    "asin": item.product.asin,
                    "subject": item.product.subject or "",
                    "subject_translation": item.product.subject_translation or "",
                    "image_url": item.product.image_url or "",
                    "score": item.score,
                    "appear_count": item.appear_count,
                    "launch_date": item.product.launch_date.strftime("%Y-%m-%d")
                    if item.product.launch_date
                    else "",
                    "crawl_date": item.crawl_date.strftime("%Y-%m-%d")
                    if item.crawl_date
                    else "",
                    "category": item.product.category or "",
                    "rank_category": item.rank_category or "",
                    "rank": item.rank,
                    "rank_category2": item.rank_category2 or "",
                    "rank2": item.rank2,
                    "rank_category3": item.rank_category3 or "",
                    "rank3": item.rank3,
                    "rank_trend_7d": rank_trend_lookup.get(item.product.asin, []),
                }
            )

        now = timezone.now()
        first_day_of_month = now.replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )
        stats = {
            "total_products": AmazonNewReleaseRank.objects.count(),
            "recent_subjects_7d": (
                AmazonNewReleaseRank.objects.filter(
                    launch_date__gte=timezone.now().date() - timedelta(days=7)
                )
                .exclude(subject__isnull=True)
                .exclude(subject="")
                .values("subject")
                .distinct()
                .count()
            ),
            "recent_products": AmazonNewReleaseRank.objects.filter(
                created_at__gte=first_day_of_month
            ).count(),
        }

        return JsonResponse(
            {
                "success": True,
                "data": {
                    "products": product_rows,
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
def api_theme_aggregation_list(request):
    try:
        data = json.loads(request.body or "{}")

        start_date_str = str(data.get("start_date", "")).strip()
        end_date_str = str(data.get("end_date", "")).strip()

        date_filter = Q()
        if start_date_str:
            try:
                start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
                date_filter &= Q(summary_subject__updated_at__date__gte=start_date)
            except ValueError:
                pass
        if end_date_str:
            try:
                end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
                date_filter &= Q(summary_subject__updated_at__date__lte=end_date)
            except ValueError:
                pass

        # 新主题快速筛选
        new_theme_days = data.get("new_theme_days")
        new_theme_filter = Q()
        if new_theme_days:
            try:
                days = int(new_theme_days)
                if days > 0:
                    cutoff = timezone.now() - timedelta(days=days)
                    new_theme_filter = Q(created_time__gte=cutoff)
            except (ValueError, TypeError):
                pass

        qs = (
            ThemeSummary.objects.annotate(
                appear_count=Count("summary_subject", filter=date_filter, distinct=True)
            )
            .filter(appear_count__gt=0)
            .filter(new_theme_filter)
        )

        subject_search = str(data.get("subject_search", "")).strip()
        if subject_search:
            qs = qs.filter(
                Q(summary_subject__subject__icontains=subject_search)
                | Q(summary_subject__subject_translation__icontains=subject_search)
            ).distinct()

        today_date = timezone.now().date()
        today_str = today_date.isoformat()
        avg_days_sq = (
            AmazonNewReleaseRank.objects.filter(
                summary_subject_id=OuterRef("pk"), launch_date__isnull=False
            )
            .annotate(
                days_since_launch=RawSQL("(%s::date - launch_date)", (today_str,))
            )
            .values("summary_subject_id")
            .annotate(avg_d=Avg("days_since_launch"))
            .values("avg_d")[:1]
        )
        qs = qs.annotate(
            avg_launch_days_annotated=Coalesce(
                Subquery(avg_days_sq, output_field=FloatField()),
                Value(-1.0, output_field=FloatField()),
            )
        )

        sort_field = str(data.get("sort_field", "appear_count")).strip()
        sort_order = str(data.get("sort_order", "desc")).strip().lower()

        if sort_field == "summary_subject_title":
            order_field = "summary_subject_title"
            if sort_order == "desc":
                order_field = f"-{order_field}"
        elif sort_field == "avg_launch_days":
            order_field = "avg_launch_days_annotated"
            if sort_order == "desc":
                order_field = f"-{order_field}"
        else:
            order_field = "-appear_count" if sort_order == "desc" else "appear_count"

        qs = qs.order_by(order_field)

        page = int(data.get("page", 1) or 1)
        page_size = int(data.get("page_size", 20) or 20)
        if page_size not in (20, 50, 100, 200):
            page_size = 20

        paginator = Paginator(qs, page_size)
        try:
            current_page = paginator.page(page)
        except PageNotAnInteger:
            current_page = paginator.page(1)
        except EmptyPage:
            current_page = paginator.page(paginator.num_pages)

        theme_ids = [item.id for item in current_page.object_list]

        asin_theme_map = {}
        theme_fulfillment_counts = {
            tid: {"FBA": 0, "FBM": 0, "AMZ": 0, "unknown": 0, "total": 0}
            for tid in theme_ids
        }
        theme_category_counts = {tid: {} for tid in theme_ids}
        for rank in AmazonNewReleaseRank.objects.filter(
            summary_subject_id__in=theme_ids
        ).values(
            "asin", "summary_subject_id", "fulfillment", "launch_date", "category"
        ):
            asin_theme_map[rank["asin"]] = rank["summary_subject_id"]
            f = (rank["fulfillment"] or "").strip()
            tid = rank["summary_subject_id"]
            if tid in theme_fulfillment_counts:
                if f in ("FBA", "FBM", "AMZ"):
                    theme_fulfillment_counts[tid][f] += 1
                else:
                    theme_fulfillment_counts[tid]["unknown"] += 1
                theme_fulfillment_counts[tid]["total"] += 1
            category = (rank.get("category") or "").strip()
            # 标准化品类名称：去除多余空格，统一换行符
            if category:
                # 去除多余空格（包括连续的多个空格）
                category = " ".join(category.split())
                if category:
                    theme_category_counts[tid][category] = (
                        theme_category_counts[tid].get(category, 0) + 1
                    )

        theme_trend_lookup = {}
        if asin_theme_map:
            trend_data = (
                ThemeNewDailyData.objects.filter(
                    product__asin__in=list(asin_theme_map.keys())
                )
                .values("product__asin", "crawl_date", "rank")
                .order_by("product__asin", "crawl_date")
            )

            theme_date_ranks = {}
            for row in trend_data:
                theme_id = asin_theme_map.get(row["product__asin"])
                if theme_id is None or row["crawl_date"] is None or row["rank"] is None:
                    continue
                date_str = row["crawl_date"].strftime("%Y-%m-%d")
                theme_date_ranks.setdefault(theme_id, {}).setdefault(
                    date_str, []
                ).append(row["rank"])

            for tid, date_ranks in theme_date_ranks.items():
                trend_list = []
                for d in sorted(date_ranks.keys()):
                    ranks = date_ranks[d]
                    avg_rank = round(sum(ranks) / len(ranks), 1)
                    trend_list.append({"date": d, "rank": avg_rank})
                theme_trend_lookup[tid] = trend_list[-7:]

        theme_rows = []
        for item in current_page.object_list:
            counts = theme_fulfillment_counts.get(item.id, {})
            total = counts.get("total", 0)
            stats = {
                "FBA": {
                    "count": counts.get("FBA", 0),
                    "pct": round(counts.get("FBA", 0) / total * 100, 1) if total else 0,
                },
                "FBM": {
                    "count": counts.get("FBM", 0),
                    "pct": round(counts.get("FBM", 0) / total * 100, 1) if total else 0,
                },
                "AMZ": {
                    "count": counts.get("AMZ", 0),
                    "pct": round(counts.get("AMZ", 0) / total * 100, 1) if total else 0,
                },
                "unknown": {
                    "count": counts.get("unknown", 0),
                    "pct": round(counts.get("unknown", 0) / total * 100, 1)
                    if total
                    else 0,
                },
            }
            if total > 0:
                # 修正四舍五入误差，确保百分比之和等于 100
                diff = round(100 - sum(stats[k]["pct"] for k in stats), 1)
                largest = max(stats, key=lambda k: stats[k]["pct"])
                stats[largest]["pct"] = round(stats[largest]["pct"] + diff, 1)
            avg_days_val = item.avg_launch_days_annotated
            avg_days = (
                round(avg_days_val, 1) if avg_days_val and avg_days_val >= 0 else "-"
            )
            # =======================计算品类占比=========================================
            category_counts = theme_category_counts.get(item.id, {})
            category_total = sum(category_counts.values())
            category_stats = {}
            if category_total > 0:
                for cat, count in category_counts.items():
                    category_stats[cat] = {
                        "count": count,
                        "pct": round(count / category_total * 100, 1),
                    }
                # 修正四舍五入误差
                diff = round(100 - sum(s["pct"] for s in category_stats.values()), 1)
                if diff != 0 and category_stats:
                    largest = max(
                        category_stats, key=lambda k: category_stats[k]["pct"]
                    )
                    category_stats[largest]["pct"] = round(
                        category_stats[largest]["pct"] + diff, 1
                    )
            # =============================================================================
            theme_rows.append(
                {
                    "id": item.id,
                    "summary_subject_title": item.summary_subject_title,
                    "appear_count": item.appear_count,
                    "rank_trend_7d": theme_trend_lookup.get(item.id, []),
                    "fulfillment_stats": stats,
                    "avg_launch_days": avg_days,
                    "category_stats": category_stats,
                }
            )

        now = timezone.now()
        seven_days_ago_dt = now - timedelta(days=7)
        first_day_of_month = now.replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )

        stats = {
            "total_themes": ThemeSummary.objects.count(),
            "recent_themes_7d": ThemeSummary.objects.filter(
                summary_subject__updated_at__gte=seven_days_ago_dt
            )
            .distinct()
            .count(),
            "recent_themes_month": ThemeSummary.objects.filter(
                summary_subject__updated_at__gte=first_day_of_month
            )
            .distinct()
            .count(),
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
def api_theme_aggregation_asins(request):
    """返回指定聚合主题下的所有 ASIN 详细信息"""
    try:
        data = json.loads(request.body or "{}")
        theme_id = data.get("theme_id")

        if not theme_id:
            return JsonResponse(
                {"success": False, "message": "缺少 theme_id 参数"}, status=400
            )

        asins_qs = (
            AmazonNewReleaseRank.objects.filter(summary_subject_id=theme_id)
            .values(
                "asin",
                "title",
                "title_translation",
                "subject",
                "subject_translation",
                "category",
                "image_url",
                "launch_date",
                "fulfillment",
            )
            .order_by("-launch_date")
        )

        # 获取所有ASIN列表
        asin_list_raw = list(asins_qs)
        asin_values = [row["asin"] for row in asin_list_raw if row["asin"]]

        # 批量查询所有ASIN的历史排名数据
        rank_trend_lookup = {}
        if asin_values:
            trend_data = (
                ThemeNewDailyData.objects.filter(product__asin__in=asin_values)
                .values("product__asin", "crawl_date", "rank")
                .order_by("product__asin", "crawl_date")
            )
            for row in trend_data:
                asin = row["product__asin"]
                if asin not in rank_trend_lookup:
                    rank_trend_lookup[asin] = []
                rank_trend_lookup[asin].append(
                    {
                        "date": row["crawl_date"].strftime("%Y-%m-%d")
                        if row["crawl_date"]
                        else None,
                        "rank": row["rank"],
                    }
                )
            # 只保留最近7条数据
            for asin in rank_trend_lookup:
                rank_trend_lookup[asin] = rank_trend_lookup[asin][-7:]

        asin_list = []
        for row in asin_list_raw:
            asin = row["asin"] or ""
            asin_list.append(
                {
                    "asin": asin,
                    "title": row["title"] or "",
                    "title_translation": row["title_translation"] or "",
                    "subject": row["subject"] or "",
                    "subject_translation": row["subject_translation"] or "",
                    "category": row["category"] or "",
                    "image_url": row["image_url"] or "",
                    "launch_date": row["launch_date"].strftime("%Y-%m-%d")
                    if row["launch_date"]
                    else "",
                    "fulfillment": row["fulfillment"] or "",
                    "rank_trend_7d": rank_trend_lookup.get(asin, []),
                }
            )

        return JsonResponse(
            {
                "success": True,
                "data": {
                    "asins": asin_list,
                    "total": len(asin_list),
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


# =====================================================================
# 基于三层架构 (Cluster → Fingerprint → ASIN) 的主题聚合 API
# =====================================================================


@theme_access_required
@csrf_exempt
@require_POST
def api_cluster_aggregation_list(request):
    """
    基于 AmazonThemeCluster 的主题聚合列表 API。
    替代旧的 api_theme_aggregation_list (基于 ThemeSummary)。
    """
    try:
        data = json.loads(request.body or "{}")

        qs = AmazonThemeCluster.objects.all()

        subject_search = str(data.get("subject_search", "")).strip()
        if subject_search:
            qs = qs.filter(
                Q(display_title__icontains=subject_search)
                | Q(core_tags__icontains=subject_search)
            )

        new_theme_days = data.get("new_theme_days")
        if new_theme_days:
            try:
                days = int(new_theme_days)
                if days > 0:
                    cutoff = timezone.now() - timedelta(days=days)
                    qs = qs.filter(created_at__gte=cutoff)
            except (ValueError, TypeError):
                pass

        sort_field = str(data.get("sort_field", "asin_count")).strip()
        sort_order = str(data.get("sort_order", "desc")).strip().lower()

        sort_map = {
            "display_title": "display_title",
            "asin_count": "asin_count",
            "burst_score": "burst_score",
            "fingerprint_count": "fingerprint_count",
            "new_asin_7d": "new_asin_7d",
            "created_at": "created_at",
        }
        order_field = sort_map.get(sort_field, "asin_count")
        if sort_order == "desc":
            order_field = f"-{order_field}"
        qs = qs.order_by(order_field)

        page = int(data.get("page", 1) or 1)
        page_size = int(data.get("page_size", 20) or 20)
        if page_size not in (20, 50, 100, 200):
            page_size = 20

        paginator = Paginator(qs, page_size)
        try:
            current_page = paginator.page(page)
        except PageNotAnInteger:
            current_page = paginator.page(1)
        except EmptyPage:
            current_page = paginator.page(paginator.num_pages)

        cluster_ids = [c.id for c in current_page.object_list]

        asin_theme_map = {}
        cluster_fulfillment_counts = {
            cid: {"FBA": 0, "FBM": 0, "AMZ": 0, "unknown": 0, "total": 0}
            for cid in cluster_ids
        }
        cluster_category_counts = {cid: {} for cid in cluster_ids}
        for rank in AmazonNewReleaseRank.objects.filter(
            fingerprint__cluster_id__in=cluster_ids
        ).values(
            "asin", "fingerprint__cluster_id", "fulfillment", "launch_date", "category"
        ):
            asin_theme_map[rank["asin"]] = rank["fingerprint__cluster_id"]
            f = (rank["fulfillment"] or "").strip()
            cid = rank["fingerprint__cluster_id"]
            if cid in cluster_fulfillment_counts:
                if f in ("FBA", "FBM", "AMZ"):
                    cluster_fulfillment_counts[cid][f] += 1
                else:
                    cluster_fulfillment_counts[cid]["unknown"] += 1
                cluster_fulfillment_counts[cid]["total"] += 1
            category = (rank.get("category") or "").strip()
            if category:
                category = " ".join(category.split())
                if category and cid in cluster_category_counts:
                    cluster_category_counts[cid][category] = (
                        cluster_category_counts[cid].get(category, 0) + 1
                    )

        cluster_trend_lookup = {}
        if asin_theme_map:
            trend_data = (
                ThemeNewDailyData.objects.filter(
                    product__asin__in=list(asin_theme_map.keys())
                )
                .values("product__asin", "crawl_date", "rank")
                .order_by("product__asin", "crawl_date")
            )
            cluster_date_ranks = {}
            for row in trend_data:
                cluster_id = asin_theme_map.get(row["product__asin"])
                if (
                    cluster_id is None
                    or row["crawl_date"] is None
                    or row["rank"] is None
                ):
                    continue
                date_str = row["crawl_date"].strftime("%Y-%m-%d")
                cluster_date_ranks.setdefault(cluster_id, {}).setdefault(
                    date_str, []
                ).append(row["rank"])

            for cid, date_ranks in cluster_date_ranks.items():
                trend_list = []
                for d in sorted(date_ranks.keys()):
                    ranks = date_ranks[d]
                    avg_rank = round(sum(ranks) / len(ranks), 1)
                    trend_list.append({"date": d, "rank": avg_rank})
                cluster_trend_lookup[cid] = trend_list[-7:]

        theme_rows = []
        for item in current_page.object_list:
            counts = cluster_fulfillment_counts.get(item.id, {})
            total = counts.get("total", 0)
            fulfillment_stats = {
                "FBA": {
                    "count": counts.get("FBA", 0),
                    "pct": round(counts.get("FBA", 0) / total * 100, 1) if total else 0,
                },
                "FBM": {
                    "count": counts.get("FBM", 0),
                    "pct": round(counts.get("FBM", 0) / total * 100, 1) if total else 0,
                },
                "AMZ": {
                    "count": counts.get("AMZ", 0),
                    "pct": round(counts.get("AMZ", 0) / total * 100, 1) if total else 0,
                },
                "unknown": {
                    "count": counts.get("unknown", 0),
                    "pct": round(counts.get("unknown", 0) / total * 100, 1)
                    if total
                    else 0,
                },
            }
            if total > 0:
                diff = round(
                    100 - sum(fulfillment_stats[k]["pct"] for k in fulfillment_stats), 1
                )
                largest = max(
                    fulfillment_stats, key=lambda k: fulfillment_stats[k]["pct"]
                )
                fulfillment_stats[largest]["pct"] = round(
                    fulfillment_stats[largest]["pct"] + diff, 1
                )

            category_counts = cluster_category_counts.get(item.id, {})
            category_total = sum(category_counts.values())
            category_stats = {}
            if category_total > 0:
                for cat, count in category_counts.items():
                    category_stats[cat] = {
                        "count": count,
                        "pct": round(count / category_total * 100, 1),
                    }
                diff = round(100 - sum(s["pct"] for s in category_stats.values()), 1)
                if diff != 0 and category_stats:
                    largest = max(
                        category_stats, key=lambda k: category_stats[k]["pct"]
                    )
                    category_stats[largest]["pct"] = round(
                        category_stats[largest]["pct"] + diff, 1
                    )

            core_tags = item.core_tags if isinstance(item.core_tags, list) else []

            theme_rows.append(
                {
                    "id": item.id,
                    "summary_subject_title": item.display_title,
                    "core_tags": core_tags,
                    "fingerprint_count": item.fingerprint_count,
                    "asin_count": item.asin_count,
                    "burst_score": round(item.burst_score or 0, 4),
                    "new_asin_7d": item.new_asin_7d or 0,
                    "rank_trend_7d": cluster_trend_lookup.get(item.id, []),
                    "fulfillment_stats": fulfillment_stats,
                    "category_stats": category_stats,
                }
            )

        now = timezone.now()
        stats = {
            "total_themes": AmazonThemeCluster.objects.count(),
            "recent_themes_7d": AmazonThemeCluster.objects.filter(
                created_at__gte=now - timedelta(days=7)
            ).count(),
            "recent_themes_month": AmazonThemeCluster.objects.filter(
                created_at__gte=now.replace(
                    day=1, hour=0, minute=0, second=0, microsecond=0
                )
            ).count(),
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
def api_cluster_aggregation_asins(request):
    """返回指定 Cluster 下的所有 ASIN 详细信息 (通过 Fingerprint 层)"""
    try:
        data = json.loads(request.body or "{}")
        cluster_id = data.get("theme_id")

        if not cluster_id:
            return JsonResponse(
                {"success": False, "message": "缺少 theme_id 参数"}, status=400
            )

        asins_qs = (
            AmazonNewReleaseRank.objects.filter(fingerprint__cluster_id=cluster_id)
            .values(
                "asin",
                "title",
                "title_translation",
                "subject",
                "subject_translation",
                "category",
                "image_url",
                "launch_date",
                "fulfillment",
            )
            .order_by("-launch_date")
        )

        asin_list_raw = list(asins_qs)
        asin_values = [row["asin"] for row in asin_list_raw if row["asin"]]

        rank_trend_lookup = {}
        if asin_values:
            trend_data = (
                ThemeNewDailyData.objects.filter(product__asin__in=asin_values)
                .values("product__asin", "crawl_date", "rank")
                .order_by("product__asin", "crawl_date")
            )
            for row in trend_data:
                asin = row["product__asin"]
                if asin not in rank_trend_lookup:
                    rank_trend_lookup[asin] = []
                rank_trend_lookup[asin].append(
                    {
                        "date": row["crawl_date"].strftime("%Y-%m-%d")
                        if row["crawl_date"]
                        else None,
                        "rank": row["rank"],
                    }
                )
            for asin in rank_trend_lookup:
                rank_trend_lookup[asin] = rank_trend_lookup[asin][-7:]

        asin_list = []
        for row in asin_list_raw:
            asin = row["asin"] or ""
            asin_list.append(
                {
                    "asin": asin,
                    "title": row["title"] or "",
                    "title_translation": row["title_translation"] or "",
                    "subject": row["subject"] or "",
                    "subject_translation": row["subject_translation"] or "",
                    "category": row["category"] or "",
                    "image_url": row["image_url"] or "",
                    "launch_date": row["launch_date"].strftime("%Y-%m-%d")
                    if row["launch_date"]
                    else "",
                    "fulfillment": row["fulfillment"] or "",
                    "rank_trend_7d": rank_trend_lookup.get(asin, []),
                }
            )

        return JsonResponse(
            {
                "success": True,
                "data": {
                    "asins": asin_list,
                    "total": len(asin_list),
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
