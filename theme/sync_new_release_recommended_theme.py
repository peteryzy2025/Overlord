"""
Sync NewRelease recommended theme snapshots.

Usage:
    python theme/sync_new_release_recommended_theme.py --dry-run
    python theme/sync_new_release_recommended_theme.py --period day --snapshot-date 2026-04-25
    python theme/sync_new_release_recommended_theme.py --period week --snapshot-date 2026-04-25 --limit 100
    python theme/sync_new_release_recommended_theme.py --period all --start-date 2026-04-20 --end-date 2026-04-25
    python theme/sync_new_release_recommended_theme.py --snapshot-date 2026-04-25 --period day --allow-empty
"""

import argparse
import os
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Overlord.settings")

import django

django.setup()

from django.db import connection, transaction
from django.db.models import Avg, Count
from django.utils import timezone

from theme.models import (
    AmazonNewReleaseRank,
    AmazonThemeCluster,
    DailyRecommendedThemeV2,
    RecommendedThemeAsin,
    ThemeNewDailyData,
)


NEW_RELEASE_SOURCE = DailyRecommendedThemeV2.Source.NEW_RELEASE
NEW_RELEASE_OBJECT_TYPE = DailyRecommendedThemeV2.SourceObjectType.NEW_RELEASE_CLUSTER
DAY_REASON = DailyRecommendedThemeV2.ReasonType.NEW_RELEASE_NEW_ASIN
WEEK_REASON = DailyRecommendedThemeV2.ReasonType.NEW_RELEASE_RANK_UP
RANK_UP_THRESHOLD = 0.30
VALID_PERIODS = {"day", "week"}


@dataclass
class RecommendedAsinPayload:
    asin: str
    title: str
    category: str
    launch_date: Any
    rank: int | None
    score: int | None
    source_position: int
    metrics: dict[str, Any]


@dataclass
class RecommendedThemePayload:
    period_type: str
    snapshot_date: Any
    window_start: Any
    window_end: Any
    reason_type: str
    theme: str
    category: str
    source_object_id: int
    source_date: Any
    asin_count: int
    metric_value: float | None
    metrics: dict[str, Any]
    asins: list[RecommendedAsinPayload]


def parse_args():
    parser = argparse.ArgumentParser(
        description="Sync NewRelease day/week recommended themes into snapshot tables."
    )
    parser.add_argument(
        "--snapshot-date",
        help="Snapshot date in YYYY-MM-DD. Defaults to today in Django timezone.",
    )
    parser.add_argument(
        "--start-date",
        help="Start snapshot date in YYYY-MM-DD for inclusive range rebuild.",
    )
    parser.add_argument(
        "--end-date",
        help="End snapshot date in YYYY-MM-DD for inclusive range rebuild.",
    )
    parser.add_argument(
        "--period",
        choices=["day", "week", "all"],
        default="all",
        help="Period to sync. Month is intentionally unsupported for NewRelease v1.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned rows without deleting or writing snapshots.",
    )
    parser.add_argument(
        "--allow-empty",
        action="store_true",
        help=(
            "Allow an empty rebuilt period to delete existing rows. "
            "By default empty periods are skipped to protect historical snapshots."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional max candidate themes per selected period, useful for debugging.",
    )
    return parser.parse_args()


def parse_snapshot_date(value):
    if not value:
        return timezone.now().date()
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise SystemExit("--snapshot-date must be in YYYY-MM-DD format") from exc


def parse_required_date(value, option_name):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise SystemExit(f"{option_name} must be in YYYY-MM-DD format") from exc


def selected_snapshot_dates(args):
    has_snapshot_date = bool(args.snapshot_date)
    has_start_date = bool(args.start_date)
    has_end_date = bool(args.end_date)
    has_range = has_start_date or has_end_date

    if has_snapshot_date and has_range:
        raise SystemExit(
            "Use either --snapshot-date or --start-date/--end-date, not both."
        )

    if has_range:
        if not has_start_date or not has_end_date:
            raise SystemExit("--start-date and --end-date must be provided together.")
        start_date = parse_required_date(args.start_date, "--start-date")
        end_date = parse_required_date(args.end_date, "--end-date")
        if start_date > end_date:
            raise SystemExit("--start-date must be earlier than or equal to --end-date.")

        days = (end_date - start_date).days
        return [start_date + timedelta(days=offset) for offset in range(days + 1)]

    return [parse_snapshot_date(args.snapshot_date)]


def selected_periods(period_arg):
    if period_arg == "all":
        return ["day", "week"]
    return [period_arg]


def required_columns(model):
    return {field.column for field in model._meta.concrete_fields}


def actual_columns(model):
    with connection.cursor() as cursor:
        return {
            column.name
            for column in connection.introspection.get_table_description(
                cursor, model._meta.db_table
            )
        }


def verify_target_schema():
    missing_by_table = {}
    for model in (DailyRecommendedThemeV2, RecommendedThemeAsin):
        missing = sorted(required_columns(model) - actual_columns(model))
        if missing:
            missing_by_table[model._meta.db_table] = missing

    if missing_by_table:
        details = "; ".join(
            f"{table}: missing {', '.join(columns)}"
            for table, columns in missing_by_table.items()
        )
        raise SystemExit(
            "Target recommendation tables do not match Django models. "
            f"Apply/fix migrations before writing snapshots. {details}"
        )


def normalize_category(value):
    return " ".join(str(value or "").split())


def most_common_category(rows):
    counter = Counter(
        category
        for category in (normalize_category(row.get("category")) for row in rows)
        if category
    )
    return counter.most_common(1)[0][0] if counter else ""


def round_int_or_none(value):
    if value is None:
        return None
    return int(round(float(value)))


def calculated_score(count, launch_date, rank, reference_date):
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

    if launch_date:
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


def effective_score(row, daily_stats, reference_date):
    stored_score = daily_stats.get("score")
    if stored_score not in (None, 0):
        return stored_score
    return calculated_score(
        daily_stats.get("appear_count") or 1,
        row.get("launch_date"),
        daily_stats.get("rank"),
        reference_date,
    )


def cluster_asin_rows(cluster_id, created_date=None):
    qs = AmazonNewReleaseRank.objects.filter(fingerprint__cluster_id=cluster_id)
    if created_date:
        qs = qs.filter(created_at__date=created_date)
    return list(
        qs
        .values("asin", "title", "category", "launch_date", "created_at")
        .order_by("-created_at", "asin")
    )


def daily_stats_by_asin(crawl_date, asins):
    if not asins:
        return {}
    rows = (
        ThemeNewDailyData.objects.filter(
            product__asin__in=asins,
            crawl_date=crawl_date,
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


def build_day_payloads(snapshot_date, limit=None):
    yesterday = snapshot_date - timedelta(days=1)

    clusters = AmazonThemeCluster.objects.filter(asin_change__gt=0).order_by(
        "-asin_change", "-updated_at", "id"
    )
    if limit:
        clusters = clusters[:limit]

    payloads: list[RecommendedThemePayload] = []
    for cluster in clusters:
        rows = cluster_asin_rows(cluster.id, yesterday)
        if not rows:
            continue
        stats_lookup = daily_stats_by_asin(
            yesterday,
            [row["asin"] for row in rows if row.get("asin")],
        )

        asins = [
            RecommendedAsinPayload(
                asin=row["asin"] or "",
                title=row["title"] or "",
                category=normalize_category(row.get("category")),
                launch_date=row["launch_date"],
                rank=stats_lookup.get(row["asin"], {}).get("rank"),
                score=effective_score(
                    row,
                    stats_lookup.get(row["asin"], {}),
                    yesterday,
                ),
                source_position=index,
                metrics={
                    "created_at": row["created_at"].isoformat()
                    if row.get("created_at")
                    else None,
                    "crawl_date": stats_lookup.get(row["asin"], {}).get("crawl_date").isoformat()
                    if stats_lookup.get(row["asin"], {}).get("crawl_date")
                    else None,
                    "raw_score": stats_lookup.get(row["asin"], {}).get("score"),
                    "appear_count": stats_lookup.get(row["asin"], {}).get("appear_count"),
                    "rank2": stats_lookup.get(row["asin"], {}).get("rank2"),
                    "rank3": stats_lookup.get(row["asin"], {}).get("rank3"),
                },
            )
            for index, row in enumerate(rows, start=1)
        ]
        payloads.append(
            RecommendedThemePayload(
                period_type=DailyRecommendedThemeV2.PeriodType.DAY,
                snapshot_date=snapshot_date,
                window_start=yesterday,
                window_end=yesterday,
                reason_type=DAY_REASON,
                theme=cluster.display_title or "",
                category=most_common_category(rows),
                source_object_id=cluster.id,
                source_date=snapshot_date,
                asin_count=len(asins),
                metric_value=float(cluster.asin_change or 0),
                metrics={
                    "asin_change": cluster.asin_change or 0,
                    "cluster_asin_count": cluster.asin_count or 0,
                    "new_asin_7d": cluster.new_asin_7d or 0,
                    "burst_score": cluster.burst_score or 0,
                    "asin_selection": "cluster_asins_created_on_snapshot_date",
                },
                asins=asins,
            )
        )
    return payloads


def rank_stats_by_cluster(start_date, end_date, cluster_ids):
    if not cluster_ids:
        return {}

    rows = (
        ThemeNewDailyData.objects.filter(
            product__fingerprint__cluster_id__in=cluster_ids,
            crawl_date__gte=start_date,
            crawl_date__lte=end_date,
            rank__isnull=False,
        )
        .values("product__fingerprint__cluster_id", "product__asin")
        .annotate(avg_rank=Avg("rank"), avg_score=Avg("score"), sample_count=Count("id"))
    )

    stats: dict[int, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in rows:
        cluster_id = row["product__fingerprint__cluster_id"]
        asin = row["product__asin"]
        if cluster_id is None or not asin:
            continue
        stats[cluster_id][asin] = {
            "avg_rank": float(row["avg_rank"]),
            "avg_score": float(row["avg_score"]) if row["avg_score"] is not None else None,
            "sample_count": row["sample_count"],
        }
    return stats


def product_lookup_for_asins(asins):
    if not asins:
        return {}
    rows = AmazonNewReleaseRank.objects.filter(asin__in=asins).values(
        "asin", "title", "category", "launch_date"
    )
    return {row["asin"]: row for row in rows}


def build_week_payloads(snapshot_date, limit=None):
    current_start = snapshot_date - timedelta(days=7)
    current_end = snapshot_date - timedelta(days=1)
    previous_start = snapshot_date - timedelta(days=14)
    previous_end = snapshot_date - timedelta(days=8)

    clusters = list(
        AmazonThemeCluster.objects.filter(
            created_at__date__gte=current_start,
            created_at__date__lte=current_end,
        ).order_by("-created_at", "id")
    )
    if limit:
        clusters = clusters[:limit]

    cluster_ids = [cluster.id for cluster in clusters]
    current_stats = rank_stats_by_cluster(current_start, current_end, cluster_ids)
    previous_stats = rank_stats_by_cluster(previous_start, previous_end, cluster_ids)

    all_asins = set()
    for cluster_id in cluster_ids:
        all_asins.update(current_stats.get(cluster_id, {}).keys())
    product_lookup = product_lookup_for_asins(all_asins)

    payloads: list[RecommendedThemePayload] = []
    for cluster in clusters:
        current_by_asin = current_stats.get(cluster.id, {})
        previous_by_asin = previous_stats.get(cluster.id, {})
        common_asins = sorted(set(current_by_asin) & set(previous_by_asin))
        if not common_asins:
            continue

        current_avg = sum(current_by_asin[asin]["avg_rank"] for asin in common_asins) / len(
            common_asins
        )
        previous_avg = sum(previous_by_asin[asin]["avg_rank"] for asin in common_asins) / len(
            common_asins
        )
        if previous_avg <= 0:
            continue

        improvement = (previous_avg - current_avg) / previous_avg
        if improvement < RANK_UP_THRESHOLD:
            continue

        ordered_asins = sorted(
            common_asins,
            key=lambda asin: (current_by_asin[asin]["avg_rank"], asin),
        )
        asin_payloads: list[RecommendedAsinPayload] = []
        for index, asin in enumerate(ordered_asins, start=1):
            product = product_lookup.get(asin, {})
            current = current_by_asin[asin]
            previous = previous_by_asin[asin]
            asin_improvement = (
                (previous["avg_rank"] - current["avg_rank"]) / previous["avg_rank"]
                if previous["avg_rank"] > 0
                else None
            )
            asin_payloads.append(
                RecommendedAsinPayload(
                    asin=asin,
                    title=product.get("title") or "",
                    category=normalize_category(product.get("category")),
                    launch_date=product.get("launch_date"),
                    rank=round_int_or_none(current["avg_rank"]),
                    score=round_int_or_none(current["avg_score"]),
                    source_position=index,
                    metrics={
                        "previous_avg_rank": round(previous["avg_rank"], 4),
                        "current_avg_rank": round(current["avg_rank"], 4),
                        "rank_improvement": round(asin_improvement, 4)
                        if asin_improvement is not None
                        else None,
                        "current_sample_count": current["sample_count"],
                        "previous_sample_count": previous["sample_count"],
                    },
                )
            )

        product_rows = [product_lookup.get(asin, {}) for asin in ordered_asins]
        payloads.append(
            RecommendedThemePayload(
                period_type=DailyRecommendedThemeV2.PeriodType.WEEK,
                snapshot_date=snapshot_date,
                window_start=current_start,
                window_end=current_end,
                reason_type=WEEK_REASON,
                theme=cluster.display_title or "",
                category=most_common_category(product_rows),
                source_object_id=cluster.id,
                source_date=snapshot_date,
                asin_count=len(asin_payloads),
                metric_value=round(improvement, 4),
                metrics={
                    "previous_window_start": previous_start.isoformat(),
                    "previous_window_end": previous_end.isoformat(),
                    "current_window_start": current_start.isoformat(),
                    "current_window_end": current_end.isoformat(),
                    "previous_avg_rank": round(previous_avg, 4),
                    "current_avg_rank": round(current_avg, 4),
                    "rank_improvement": round(improvement, 4),
                    "ranked_asin_count": len(asin_payloads),
                    "threshold": RANK_UP_THRESHOLD,
                },
                asins=asin_payloads,
            )
        )

    payloads.sort(key=lambda item: (item.metric_value or 0, item.asin_count), reverse=True)
    return payloads


def delete_existing(snapshot_date, periods):
    deleted, details = DailyRecommendedThemeV2.objects.filter(
        snapshot_date=snapshot_date,
        source=NEW_RELEASE_SOURCE,
        period_type__in=periods,
    ).delete()
    return deleted, details


def write_payloads(payloads):
    created_themes = 0
    created_asins = 0
    for payload in payloads:
        theme = DailyRecommendedThemeV2.objects.create(
            period_type=payload.period_type,
            snapshot_date=payload.snapshot_date,
            window_start=payload.window_start,
            window_end=payload.window_end,
            source=NEW_RELEASE_SOURCE,
            reason_type=payload.reason_type,
            theme=payload.theme,
            category=payload.category,
            source_object_type=NEW_RELEASE_OBJECT_TYPE,
            source_object_id=payload.source_object_id,
            source_metric_id=None,
            source_date=payload.source_date,
            asin_count=payload.asin_count,
            metric_value=payload.metric_value,
            metrics=payload.metrics,
        )
        created_themes += 1

        asin_objects = [
            RecommendedThemeAsin(
                recommended_theme=theme,
                asin=asin.asin,
                title=asin.title,
                category=asin.category,
                launch_date=asin.launch_date,
                rank=asin.rank,
                score=asin.score,
                source_position=asin.source_position,
                metrics=asin.metrics,
            )
            for asin in payload.asins
        ]
        if asin_objects:
            RecommendedThemeAsin.objects.bulk_create(asin_objects)
            created_asins += len(asin_objects)
    return created_themes, created_asins


def print_summary(period, payloads):
    asin_total = sum(len(payload.asins) for payload in payloads)
    print(f"[{period}] themes={len(payloads)} asins={asin_total}")
    for payload in payloads[:10]:
        print(
            "  "
            f"id={payload.source_object_id} "
            f"theme={payload.theme[:80]!r} "
            f"asin_count={payload.asin_count} "
            f"metric={payload.metric_value}"
        )
    if len(payloads) > 10:
        print(f"  ... {len(payloads) - 10} more")


def build_payloads_for_date(snapshot_date, periods, limit=None):
    payloads_by_period = {}
    if "day" in periods:
        print(f"building [day] payloads...", flush=True)
        payloads_by_period["day"] = build_day_payloads(snapshot_date, limit)
    if "week" in periods:
        print(f"building [week] payloads...", flush=True)
        payloads_by_period["week"] = build_week_payloads(snapshot_date, limit)
    return payloads_by_period


def sync_snapshot_date(
    snapshot_date,
    periods,
    limit=None,
    dry_run=False,
    allow_empty=False,
):
    print(
        f"snapshot_date={snapshot_date} dry_run={dry_run} allow_empty={allow_empty}"
    )
    payloads_by_period = build_payloads_for_date(snapshot_date, periods, limit)
    for period in periods:
        print_summary(period, payloads_by_period.get(period, []))

    if dry_run:
        print("Dry run only. No database rows were changed.")
        return {
            "deleted_count": 0,
            "deleted_details": {},
            "created_themes": 0,
            "created_asins": 0,
            "skipped_empty": 0,
        }

    total_deleted_count = 0
    total_deleted_details = defaultdict(int)
    total_created_themes = 0
    total_created_asins = 0
    skipped_empty = 0

    for period in periods:
        period_payloads = payloads_by_period.get(period, [])
        if not period_payloads and not allow_empty:
            skipped_empty += 1
            print(
                f"[{period}] rebuilt payload is empty; "
                "kept existing rows. Use --allow-empty to clear this period."
            )
            continue

        with transaction.atomic():
            deleted_count, deleted_details = delete_existing(snapshot_date, [period])
            created_themes, created_asins = write_payloads(period_payloads)

        total_deleted_count += deleted_count
        for key, value in deleted_details.items():
            total_deleted_details[key] += value
        total_created_themes += created_themes
        total_created_asins += created_asins

        print(f"[{period}] deleted={deleted_count} details={deleted_details}")
        print(f"[{period}] created_themes={created_themes} created_asins={created_asins}")

    print(
        f"deleted={total_deleted_count} details={dict(total_deleted_details)} "
        f"created_themes={total_created_themes} "
        f"created_asins={total_created_asins} "
        f"skipped_empty={skipped_empty}"
    )
    return {
        "deleted_count": total_deleted_count,
        "deleted_details": dict(total_deleted_details),
        "created_themes": total_created_themes,
        "created_asins": total_created_asins,
        "skipped_empty": skipped_empty,
    }


def main():
    args = parse_args()
    snapshot_dates = selected_snapshot_dates(args)
    periods = selected_periods(args.period)

    if not args.dry_run:
        verify_target_schema()

    totals = {
        "deleted_count": 0,
        "created_themes": 0,
        "created_asins": 0,
        "skipped_empty": 0,
    }

    for snapshot_date in snapshot_dates:
        result = sync_snapshot_date(
            snapshot_date,
            periods,
            limit=args.limit,
            dry_run=args.dry_run,
            allow_empty=args.allow_empty,
        )
        totals["deleted_count"] += result["deleted_count"]
        totals["created_themes"] += result["created_themes"]
        totals["created_asins"] += result["created_asins"]
        totals["skipped_empty"] += result["skipped_empty"]

    if len(snapshot_dates) > 1:
        print(
            "total "
            f"processed_dates={len(snapshot_dates)} "
            f"deleted={totals['deleted_count']} "
            f"created_themes={totals['created_themes']} "
            f"created_asins={totals['created_asins']} "
            f"skipped_empty={totals['skipped_empty']}"
        )


if __name__ == "__main__":
    main()
