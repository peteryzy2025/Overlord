"""
Sync Novelty recommended theme snapshots.

Usage:
    python theme/sync_novelty_recommended_theme.py --dry-run
    python theme/sync_novelty_recommended_theme.py --period day --snapshot-date 2026-04-25
    python theme/sync_novelty_recommended_theme.py --period all --snapshot-date 2026-04-25 --limit 100
    python theme/sync_novelty_recommended_theme.py --period all --start-date 2026-04-20 --end-date 2026-04-25
    python theme/sync_novelty_recommended_theme.py --snapshot-date 2026-04-25 --period day --allow-empty
"""

import argparse
import os
import sys
from collections import defaultdict
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
from django.utils import timezone

from theme.models import (
    DailyRecommendedThemeV2,
    RecommendedThemeAsin,
    ThemeDailyData,
)


NOVELTY_SOURCE = DailyRecommendedThemeV2.Source.NOVELTY
NOVELTY_OBJECT_TYPE = DailyRecommendedThemeV2.SourceObjectType.NOVELTY_CLUSTER
NOVELTY_REASON = DailyRecommendedThemeV2.ReasonType.NOVELTY_SCORE
SCORE_THRESHOLD = 5
PERIOD_WINDOWS = {
    DailyRecommendedThemeV2.PeriodType.DAY: 1,
    DailyRecommendedThemeV2.PeriodType.WEEK: 7,
    DailyRecommendedThemeV2.PeriodType.MONTH: 30,
}


@dataclass
class RecommendedAsinPayload:
    asin: str
    title: str
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
    theme: str
    source_object_id: int
    source_date: Any
    asin_count: int
    metric_value: float | None
    metrics: dict[str, Any]
    asins: list[RecommendedAsinPayload]


def parse_args():
    parser = argparse.ArgumentParser(
        description="Sync Novelty day/week/month recommended themes into snapshot tables."
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
        choices=["day", "week", "month", "all"],
        default="all",
        help="Period to sync.",
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
        help="Optional max recommended themes per selected period, useful for debugging.",
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
        return ["day", "week", "month"]
    return [period_arg]


def window_for_period(snapshot_date, period_type):
    days = PERIOD_WINDOWS[period_type]
    return snapshot_date - timedelta(days=days), snapshot_date - timedelta(days=1)


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


def better_hit(candidate, current):
    if current is None:
        return True
    candidate_score = candidate.get("score") or 0
    current_score = current.get("score") or 0
    if candidate_score != current_score:
        return candidate_score > current_score
    return (candidate.get("crawl_date") or datetime.min.date()) > (
        current.get("crawl_date") or datetime.min.date()
    )


def launch_age_days(row):
    crawl_date = row.get("crawl_date")
    launch_date = row.get("product__launch_date")
    if not crawl_date or not launch_date:
        return None
    return (crawl_date - launch_date).days


def build_payloads(period_type, snapshot_date, limit=None):
    window_start, window_end = window_for_period(snapshot_date, period_type)
    max_age_days = PERIOD_WINDOWS[period_type]
    launch_date_start = window_start - timedelta(days=max_age_days)
    rows = (
        ThemeDailyData.objects.filter(
            score__gte=SCORE_THRESHOLD,
            crawl_date__gte=window_start,
            crawl_date__lte=window_end,
            product__launch_date__isnull=False,
            product__launch_date__gte=launch_date_start,
            product__launch_date__lte=window_end,
            product__fingerprint__cluster_id__isnull=False,
        )
        .values(
            "product__asin",
            "product__title",
            "product__launch_date",
            "product__fingerprint__cluster_id",
            "product__fingerprint__cluster__display_title",
            "product__fingerprint__cluster__asin_count",
            "product__fingerprint__cluster__new_asin_7d",
            "product__fingerprint__cluster__burst_score",
            "crawl_date",
            "rank",
            "score",
            "appear_count",
        )
        .order_by("-score", "-crawl_date", "product__asin")
    )

    best_by_cluster_asin: dict[tuple[int, str], dict[str, Any]] = {}
    for row in rows.iterator(chunk_size=5000):
        cluster_id = row["product__fingerprint__cluster_id"]
        asin = row["product__asin"]
        if not cluster_id or not asin:
            continue
        age_days = launch_age_days(row)
        if age_days is None or age_days < 0 or age_days > max_age_days:
            continue
        row["launch_age_days"] = age_days
        key = (cluster_id, asin)
        if better_hit(row, best_by_cluster_asin.get(key)):
            best_by_cluster_asin[key] = row

    grouped: dict[int, list[dict[str, Any]]] = {}
    for (cluster_id, _asin), row in best_by_cluster_asin.items():
        grouped.setdefault(cluster_id, []).append(row)

    payloads: list[RecommendedThemePayload] = []
    for cluster_id, cluster_rows in grouped.items():
        ordered_rows = sorted(
            cluster_rows,
            key=lambda item: (
                -(item.get("score") or 0),
                item.get("rank") is None,
                item.get("rank") or 0,
                item.get("product__asin") or "",
            ),
        )
        best_row = ordered_rows[0]
        max_score = best_row.get("score") or 0
        source_date = best_row.get("crawl_date") or snapshot_date
        title = best_row.get("product__fingerprint__cluster__display_title") or ""

        asin_payloads = [
            RecommendedAsinPayload(
                asin=row["product__asin"] or "",
                title=row["product__title"] or "",
                launch_date=row["product__launch_date"],
                rank=row["rank"],
                score=row["score"],
                source_position=index,
                metrics={
                    "crawl_date": row["crawl_date"].isoformat()
                    if row.get("crawl_date")
                    else None,
                    "launch_age_days": row.get("launch_age_days"),
                    "appear_count": row.get("appear_count") or 0,
                },
            )
            for index, row in enumerate(ordered_rows, start=1)
        ]

        payloads.append(
            RecommendedThemePayload(
                period_type=period_type,
                snapshot_date=snapshot_date,
                window_start=window_start,
                window_end=window_end,
                theme=title,
                source_object_id=cluster_id,
                source_date=source_date,
                asin_count=len(asin_payloads),
                metric_value=float(max_score),
                metrics={
                    "score_threshold": SCORE_THRESHOLD,
                    "max_score": max_score,
                    "matched_asin_count": len(asin_payloads),
                    "cluster_asin_count": best_row.get(
                        "product__fingerprint__cluster__asin_count"
                    )
                    or 0,
                    "cluster_new_asin_7d": best_row.get(
                        "product__fingerprint__cluster__new_asin_7d"
                    )
                    or 0,
                    "cluster_burst_score": best_row.get(
                        "product__fingerprint__cluster__burst_score"
                    )
                    or 0,
                    "asin_selection": "score_gte_threshold_and_launch_age_in_period",
                    "launch_age_max_days": max_age_days,
                    "launch_date_prefilter_start": launch_date_start.isoformat(),
                    "launch_date_prefilter_end": window_end.isoformat(),
                    "crawl_date_window_start": window_start.isoformat(),
                    "crawl_date_window_end": window_end.isoformat(),
                    "time_rule": "theme_daily_data.crawl_date - theme_amazon_novelty.launch_date",
                },
                asins=asin_payloads,
            )
        )

    payloads.sort(key=lambda item: (item.metric_value or 0, item.asin_count), reverse=True)
    if limit:
        payloads = payloads[:limit]
    return payloads


def delete_existing(snapshot_date, periods):
    deleted, details = DailyRecommendedThemeV2.objects.filter(
        snapshot_date=snapshot_date,
        source=NOVELTY_SOURCE,
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
            source=NOVELTY_SOURCE,
            reason_type=NOVELTY_REASON,
            theme=payload.theme,
            category="",
            source_object_type=NOVELTY_OBJECT_TYPE,
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
                category="",
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
            f"max_score={payload.metric_value}"
        )
    if len(payloads) > 10:
        print(f"  ... {len(payloads) - 10} more")


def build_payloads_for_date(snapshot_date, periods, limit=None):
    payloads_by_period = {}
    for period in periods:
        print(f"building [{period}] payloads...", flush=True)
        payloads_by_period[period] = build_payloads(period, snapshot_date, limit)
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
        print_summary(period, payloads_by_period[period])

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
