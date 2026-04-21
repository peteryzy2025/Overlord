import json
from datetime import datetime, timedelta

from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.db.models import Count, Q
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from theme.models import (
    AmazonThemeClusterNovelty,
    AmazonThemeNovelty,
    ThemeDailyData,
    ThemeFingerprintNovelty,
    ThemeNoveltySummary,
)
from theme.view.permissions import theme_access_required


@theme_access_required
@csrf_exempt
@require_POST
def api_novelty_aggregation_list(request):
    try:
        data = json.loads(request.body or "{}")
        print(data)
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
            ThemeNoveltySummary.objects.annotate(
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

        sort_field = str(data.get("sort_field", "appear_count")).strip()
        sort_order = str(data.get("sort_order", "desc")).strip().lower()

        page = int(data.get("page", 1) or 1)
        page_size = int(data.get("page_size", 20) or 20)
        if page_size not in (20, 50, 100, 200):
            page_size = 20

        python_sort_fields = {"avg_launch_days", "avg_score"}

        if sort_field in python_sort_fields:
            all_items = list(qs)
            all_theme_ids = [item.id for item in all_items]

            all_asin_theme_map = {}
            all_launch_stats = {
                tid: {"total_days": 0, "count": 0} for tid in all_theme_ids
            }
            all_score_stats = {
                tid: {"total_score": 0, "count": 0} for tid in all_theme_ids
            }
            asins_with_launch_date = set()
            for novelty in AmazonThemeNovelty.objects.filter(
                theme_novelty_summary_id__in=all_theme_ids
            ).values("asin", "theme_novelty_summary_id", "launch_date"):
                all_asin_theme_map[novelty["asin"]] = novelty[
                    "theme_novelty_summary_id"
                ]
                tid = novelty["theme_novelty_summary_id"]
                launch_date = novelty.get("launch_date", "")
                if launch_date and isinstance(launch_date, datetime):
                    launch_date = launch_date.date()
                if launch_date:
                    asins_with_launch_date.add(novelty["asin"])
                    if tid in all_launch_stats:
                        days = (timezone.now().date() - launch_date).days
                        all_launch_stats[tid]["total_days"] += days
                        all_launch_stats[tid]["count"] += 1

            if all_asin_theme_map:
                score_filter = Q(
                    product__asin__in=list(
                        k
                        for k in all_asin_theme_map.keys()
                        if k in asins_with_launch_date
                    )
                )
                if start_date_str:
                    try:
                        score_start = datetime.strptime(
                            start_date_str, "%Y-%m-%d"
                        ).date()
                        score_filter &= Q(crawled_at__date__gte=score_start)
                    except ValueError:
                        pass
                if end_date_str:
                    try:
                        score_end = datetime.strptime(end_date_str, "%Y-%m-%d").date()
                        score_filter &= Q(crawled_at__date__lte=score_end)
                    except ValueError:
                        pass
                score_rows = ThemeDailyData.objects.filter(score_filter).values_list(
                    "product__asin", "score"
                )
                for asin_val, score_val in score_rows:
                    tid = all_asin_theme_map.get(asin_val)
                    if (
                        tid is not None
                        and tid in all_score_stats
                        and score_val is not None
                    ):
                        all_score_stats[tid]["total_score"] += score_val
                        all_score_stats[tid]["count"] += 1

            computed = []
            for item in all_items:
                ls = all_launch_stats.get(item.id, {"total_days": 0, "count": 0})
                avg_days = (
                    round(ls["total_days"] / ls["count"], 1) if ls["count"] > 0 else -1
                )
                ss = all_score_stats.get(item.id, {"total_score": 0, "count": 0})
                avg_score_val = (
                    round(ss["total_score"] / ss["count"], 1) if ss["count"] > 0 else -1
                )
                computed.append(
                    {
                        "item": item,
                        "avg_launch_days": avg_days,
                        "avg_score": avg_score_val,
                    }
                )

            reverse = sort_order == "desc"
            if sort_field == "avg_launch_days":
                computed.sort(key=lambda x: x["avg_launch_days"], reverse=reverse)
            else:
                computed.sort(key=lambda x: x["avg_score"], reverse=reverse)

            total_count = len(computed)
            total_pages = (
                (total_count + page_size - 1) // page_size if total_count > 0 else 1
            )
            if page > total_pages:
                page = total_pages
            if page < 1:
                page = 1
            start_idx = (page - 1) * page_size
            end_idx = start_idx + page_size
            page_computed = computed[start_idx:end_idx]

            page_theme_ids = [c["item"].id for c in page_computed]

            asin_theme_map = {}
            for novelty in AmazonThemeNovelty.objects.filter(
                theme_novelty_summary_id__in=page_theme_ids
            ).values("asin", "theme_novelty_summary_id"):
                asin_theme_map[novelty["asin"]] = novelty["theme_novelty_summary_id"]

            theme_trend_lookup = {}
            if asin_theme_map:
                trend_data = (
                    ThemeDailyData.objects.filter(
                        product__asin__in=list(asin_theme_map.keys())
                    )
                    .values("product__asin", "crawl_date", "rank")
                    .order_by("product__asin", "crawl_date")
                )
                theme_date_ranks = {}
                for row in trend_data:
                    theme_id = asin_theme_map.get(row["product__asin"])
                    if (
                        theme_id is None
                        or row["crawl_date"] is None
                        or row["rank"] is None
                    ):
                        continue
                    date_str = row["crawl_date"].strftime("%Y-%m-%d")
                    theme_date_ranks.setdefault(theme_id, {}).setdefault(
                        date_str, []
                    ).append(row["rank"])
                for tid, date_ranks in theme_date_ranks.items():
                    trend_list = []
                    for d in sorted(date_ranks.keys()):
                        ranks = date_ranks[d]
                        trend_list.append(
                            {"date": d, "rank": round(sum(ranks) / len(ranks), 1)}
                        )
                    theme_trend_lookup[tid] = trend_list[-7:]

            theme_rows = []
            for c in page_computed:
                item = c["item"]
                avg_days = c["avg_launch_days"]
                avg_score_val = c["avg_score"]
                theme_rows.append(
                    {
                        "id": item.id,
                        "summary_subject_title": item.summary_subject_title,
                        "appear_count": item.appear_count,
                        "rank_trend_7d": theme_trend_lookup.get(item.id, []),
                        "avg_launch_days": avg_days if avg_days >= 0 else "-",
                        "avg_score": avg_score_val if avg_score_val >= 0 else "-",
                    }
                )

            now = timezone.now()
            stats = {
                "total_themes": ThemeNoveltySummary.objects.count(),
                "recent_themes_7d": ThemeNoveltySummary.objects.filter(
                    summary_subject__updated_at__gte=now - timedelta(days=7)
                )
                .distinct()
                .count(),
                "recent_themes_month": ThemeNoveltySummary.objects.filter(
                    summary_subject__updated_at__gte=now.replace(
                        day=1, hour=0, minute=0, second=0, microsecond=0
                    )
                )
                .distinct()
                .count(),
            }

            return JsonResponse(
                {
                    "success": True,
                    "data": {
                        "themes": theme_rows,
                        "total": total_count,
                        "total_pages": total_pages,
                        "current_page": page,
                        "page_size": page_size,
                        "has_next": page < total_pages,
                        "has_previous": page > 1,
                        "next_page": page + 1 if page < total_pages else None,
                        "previous_page": page - 1 if page > 1 else None,
                        "stats": stats,
                    },
                }
            )
        else:
            if sort_field == "summary_subject_title":
                order_field = "summary_subject_title"
                if sort_order == "desc":
                    order_field = f"-{order_field}"
            else:
                order_field = (
                    "-appear_count" if sort_order == "desc" else "appear_count"
                )

            qs = qs.order_by(order_field)

            paginator = Paginator(qs, page_size)
            try:
                current_page = paginator.page(page)
            except PageNotAnInteger:
                current_page = paginator.page(1)
            except EmptyPage:
                current_page = paginator.page(paginator.num_pages)

            theme_ids = [item.id for item in current_page.object_list]

            asin_theme_map = {}
            asins_with_launch_date = set()
            theme_launch_stats = {
                tid: {"total_days": 0, "count": 0} for tid in theme_ids
            }
            for novelty in AmazonThemeNovelty.objects.filter(
                theme_novelty_summary_id__in=theme_ids
            ).values("asin", "theme_novelty_summary_id", "launch_date"):
                asin_theme_map[novelty["asin"]] = novelty["theme_novelty_summary_id"]
                tid = novelty["theme_novelty_summary_id"]
                launch_date = novelty.get("launch_date", "")
                if launch_date and isinstance(launch_date, datetime):
                    launch_date = launch_date.date()
                if launch_date:
                    asins_with_launch_date.add(novelty["asin"])
                    if tid in theme_launch_stats:
                        days = (timezone.now().date() - launch_date).days
                        theme_launch_stats[tid]["total_days"] += days
                        theme_launch_stats[tid]["count"] += 1

            theme_trend_lookup = {}
            theme_score_stats = {
                tid: {"total_score": 0, "count": 0} for tid in theme_ids
            }
            if asin_theme_map:
                trend_data = (
                    ThemeDailyData.objects.filter(
                        product__asin__in=list(asin_theme_map.keys())
                    )
                    .values("product__asin", "crawl_date", "rank")
                    .order_by("product__asin", "crawl_date")
                )
                theme_date_ranks = {}
                for row in trend_data:
                    theme_id = asin_theme_map.get(row["product__asin"])
                    if (
                        theme_id is None
                        or row["crawl_date"] is None
                        or row["rank"] is None
                    ):
                        continue
                    date_str = row["crawl_date"].strftime("%Y-%m-%d")
                    theme_date_ranks.setdefault(theme_id, {}).setdefault(
                        date_str, []
                    ).append(row["rank"])
                for tid, date_ranks in theme_date_ranks.items():
                    trend_list = []
                    for d in sorted(date_ranks.keys()):
                        ranks = date_ranks[d]
                        trend_list.append(
                            {"date": d, "rank": round(sum(ranks) / len(ranks), 1)}
                        )
                    theme_trend_lookup[tid] = trend_list[-7:]

                score_filter = Q(
                    product__asin__in=list(
                        k for k in asin_theme_map.keys() if k in asins_with_launch_date
                    )
                )
                if start_date_str:
                    try:
                        score_start = datetime.strptime(
                            start_date_str, "%Y-%m-%d"
                        ).date()
                        score_filter &= Q(crawled_at__date__gte=score_start)
                    except ValueError:
                        pass
                if end_date_str:
                    try:
                        score_end = datetime.strptime(end_date_str, "%Y-%m-%d").date()
                        score_filter &= Q(crawled_at__date__lte=score_end)
                    except ValueError:
                        pass
                score_rows = ThemeDailyData.objects.filter(score_filter).values_list(
                    "product__asin", "score"
                )
                for asin_val, score_val in score_rows:
                    tid = asin_theme_map.get(asin_val)
                    if (
                        tid is not None
                        and tid in theme_score_stats
                        and score_val is not None
                    ):
                        theme_score_stats[tid]["total_score"] += score_val
                        theme_score_stats[tid]["count"] += 1

            theme_rows = []
            for item in current_page.object_list:
                launch_stat = theme_launch_stats.get(
                    item.id, {"total_days": 0, "count": 0}
                )
                if launch_stat["count"] > 0:
                    avg_days = round(
                        launch_stat["total_days"] / launch_stat["count"], 1
                    )
                else:
                    avg_days = "-"
                score_stat = theme_score_stats.get(
                    item.id, {"total_score": 0, "count": 0}
                )
                if score_stat["count"] > 0:
                    avg_score = round(
                        score_stat["total_score"] / score_stat["count"], 1
                    )
                else:
                    avg_score = "-"
                theme_rows.append(
                    {
                        "id": item.id,
                        "summary_subject_title": item.summary_subject_title,
                        "appear_count": item.appear_count,
                        "rank_trend_7d": theme_trend_lookup.get(item.id, []),
                        "avg_launch_days": avg_days,
                        "avg_score": avg_score,
                    }
                )

            now = timezone.now()
            stats = {
                "total_themes": ThemeNoveltySummary.objects.count(),
                "recent_themes_7d": ThemeNoveltySummary.objects.filter(
                    summary_subject__updated_at__gte=now - timedelta(days=7)
                )
                .distinct()
                .count(),
                "recent_themes_month": ThemeNoveltySummary.objects.filter(
                    summary_subject__updated_at__gte=now.replace(
                        day=1, hour=0, minute=0, second=0, microsecond=0
                    )
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
def api_novelty_aggregation_asins(request):
    try:
        data = json.loads(request.body or "{}")
        theme_id = data.get("theme_id")

        if not theme_id:
            return JsonResponse(
                {"success": False, "message": "缺少 theme_id 参数"}, status=400
            )

        asins_qs = (
            AmazonThemeNovelty.objects.filter(theme_novelty_summary_id=theme_id)
            .values(
                "asin",
                "title",
                "title_translation",
                "subject",
                "subject_translation",
                "image_url",
                "launch_date",
            )
            .order_by("-launch_date")
        )

        asin_list_raw = list(asins_qs)
        asin_values = [row["asin"] for row in asin_list_raw if row["asin"]]

        rank_trend_lookup = {}
        if asin_values:
            trend_data = (
                ThemeDailyData.objects.filter(product__asin__in=asin_values)
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
                    "image_url": row["image_url"] or "",
                    "launch_date": row["launch_date"].strftime("%Y-%m-%d")
                    if row["launch_date"]
                    else "",
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
# 基于三层架构 (Cluster → Fingerprint → ASIN) 的新奇特主题聚合 API
# =====================================================================


@theme_access_required
@csrf_exempt
@require_POST
def api_novelty_cluster_aggregation_list(request):
    """
    基于 AmazonThemeClusterNovelty 的主题聚合列表 API。
    """
    try:
        data = json.loads(request.body or "{}")

        qs = AmazonThemeClusterNovelty.objects.all()

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
                    cutoff = timezone.now().date() - timedelta(days=days)
                    cluster_ids_with_recent_asin = (
                        AmazonThemeNovelty.objects.filter(
                            fingerprint__cluster_id__isnull=False,
                            launch_date__gte=cutoff,
                        )
                        .values_list("fingerprint__cluster_id", flat=True)
                        .distinct()
                    )
                    qs = qs.filter(id__in=cluster_ids_with_recent_asin)
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

        asin_cluster_map = {}
        cluster_trend_lookup = {}
        for rank in AmazonThemeNovelty.objects.filter(
            fingerprint__cluster_id__in=cluster_ids
        ).values("asin", "fingerprint__cluster_id"):
            cid = rank["fingerprint__cluster_id"]
            if rank["asin"]:
                asin_cluster_map[rank["asin"]] = cid

        if asin_cluster_map:
            trend_data = (
                ThemeDailyData.objects.filter(
                    product__asin__in=list(asin_cluster_map.keys())
                )
                .values("product__asin", "crawl_date", "rank")
                .order_by("product__asin", "crawl_date")
            )
            cluster_date_ranks = {}
            for row in trend_data:
                cluster_id = asin_cluster_map.get(row["product__asin"])
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
                }
            )

        now = timezone.now()
        stats = {
            "total_themes": AmazonThemeClusterNovelty.objects.count(),
            "recent_themes_7d": AmazonThemeClusterNovelty.objects.filter(
                created_at__gte=now - timedelta(days=7)
            ).count(),
            "recent_themes_month": AmazonThemeClusterNovelty.objects.filter(
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
def api_novelty_cluster_aggregation_asins(request):
    """返回指定 Cluster 下的所有 ASIN 详细信息 (通过 Fingerprint 层)"""
    try:
        data = json.loads(request.body or "{}")
        cluster_id = data.get("theme_id")

        if not cluster_id:
            return JsonResponse(
                {"success": False, "message": "缺少 theme_id 参数"}, status=400
            )

        asins_qs = (
            AmazonThemeNovelty.objects.filter(fingerprint__cluster_id=cluster_id)
            .values(
                "asin",
                "title",
                "title_translation",
                "subject",
                "subject_translation",
                "image_url",
                "launch_date",
            )
            .order_by("-launch_date")
        )

        asin_list_raw = list(asins_qs)
        asin_values = [row["asin"] for row in asin_list_raw if row["asin"]]

        rank_trend_lookup = {}
        if asin_values:
            trend_data = (
                ThemeDailyData.objects.filter(product__asin__in=asin_values)
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
                    "image_url": row["image_url"] or "",
                    "launch_date": row["launch_date"].strftime("%Y-%m-%d")
                    if row["launch_date"]
                    else "",
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
