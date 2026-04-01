import os
import sys
import asyncio
import json
import logging
import traceback
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

# ====== Django 初始化 ======
# 说明：
# 1) 当前脚本在 amazon/sync/ 目录下，需要向上两级到项目根目录。
# 2) 必须先设置 DJANGO_SETTINGS_MODULE，再调用 django.setup()。
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(CURRENT_DIR))  # amazon/sync/ -> amazon/ -> 项目根目录
sys.path.insert(0, PROJECT_ROOT)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Overlord.settings")

import django

django.setup()

import argparse
from collections import defaultdict

from django.db import transaction, close_old_connections
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils import timezone

from amazon.models import AmazonListing
from theme.models import TrademarkInfo, TroTable
from theme.view.views_trend import batch_analyze_theme_trend


DEFAULT_RISK_LEVEL = "unknown"
VALID_RISK_LEVELS = {"high", "medium", "low", "unknown"}
KEYWORD_WRITE_RISK_LEVELS = {"high", "medium"}

LOGGER = logging.getLogger("amazon.listing_risk_worker.sync")
if not LOGGER.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
    LOGGER.addHandler(handler)
LOGGER.setLevel(logging.INFO)
LOGGER.propagate = False


@dataclass
class RiskWorkerStats:
    total_sids: int = 0
    committed_sids: int = 0
    total_listings: int = 0
    total_titles: int = 0
    analyzed_titles: int = 0
    listings_updated: int = 0
    error_count: int = 0
    high_count: int = 0
    medium_count: int = 0
    low_count: int = 0
    unknown_count: int = 0


@dataclass
class SidRiskStats:
    sid: int
    target_listings: int = 0
    unique_titles: int = 0
    analyzed_titles: int = 0
    listings_updated: int = 0
    error_count: int = 0
    high_count: int = 0
    medium_count: int = 0
    low_count: int = 0
    unknown_count: int = 0
    committed: bool = False


def _log(level: str, event: str, **payload) -> None:
    message = json.dumps({"event": event, **payload}, ensure_ascii=False, default=str)
    if level == "error":
        LOGGER.error(message)
    elif level == "warning":
        LOGGER.warning(message)
    else:
        LOGGER.info(message)


def _safe_str(value) -> str:
    return (value or "").strip()


def _normalize_risk_level(value, default=DEFAULT_RISK_LEVEL) -> str:
    risk = _safe_str(value).lower()
    if risk in VALID_RISK_LEVELS:
        return risk
    return default


def _dedup_words(words) -> List[str]:
    seen = set()
    result = []
    for word in words or []:
        text = _safe_str(word)
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def _chunked(items: List[str], size: int):
    for idx in range(0, len(items), size):
        yield items[idx: idx + size]


def _get_target_queryset(sid: Optional[int], include_known: bool, only_active: bool):
    queryset = AmazonListing.objects.select_related("lingxing_shop").filter(
        lingxing_shop__name__icontains="US",
    ).exclude(
        title__isnull=True,
    ).exclude(
        title__exact="",
    )

    if sid:
        queryset = queryset.filter(lingxing_shop__sid=sid)
    if only_active:
        queryset = queryset.filter(is_active=True)
    if not include_known:
        queryset = queryset.filter(Q(risk_level=DEFAULT_RISK_LEVEL) | Q(risk_level__isnull=True) | Q(risk_level=""))
    return queryset.order_by("id")


def _get_target_sid_list(sid: Optional[int], include_known: bool, only_active: bool) -> List[int]:
    queryset = _get_target_queryset(sid=sid, include_known=include_known, only_active=only_active)
    sid_values = (
        queryset
        .values_list("lingxing_shop__sid", flat=True)
        .distinct()
        .order_by("lingxing_shop__sid")
    )
    return [int(item) for item in sid_values if item is not None]


def _build_title_map_from_listings(listings: List[AmazonListing]) -> Dict[str, List[AmazonListing]]:
    title_map = defaultdict(list)
    for listing in listings:
        title = _safe_str(listing.title)
        if not title:
            continue
        title_map[title].append(listing)
    return dict(title_map)


def _batch_analyze_titles(
    unique_titles: List[str],
    title_batch_size: int,
    sid: int,
) -> Tuple[Dict[str, Dict], set, int, int]:
    analysis_map = {}
    failed_titles = set()
    analyzed_titles = 0
    error_count = 0
    for idx, chunk in enumerate(_chunked(unique_titles, title_batch_size), start=1):
        try:
            batch_result = batch_analyze_theme_trend(chunk)
            analysis_map.update(batch_result)
            analyzed_titles += len(chunk)
            _log(
                "info",
                "risk.batch.done",
                sid=sid,
                batch_index=idx,
                batch_size=len(chunk),
                analyzed_titles=analyzed_titles,
            )
        except Exception as exc:
            error_count += 1
            failed_titles.update(chunk)
            _log(
                "error",
                "risk.batch.failed",
                sid=sid,
                batch_index=idx,
                batch_size=len(chunk),
                error=str(exc),
                traceback=traceback.format_exc(),
            )
    return analysis_map, failed_titles, analyzed_titles, error_count


def _build_word_object_maps(analysis_map: Dict[str, Dict]):
    tro_words = set()
    tm_words = set()
    for result in analysis_map.values():
        risk_level = _normalize_risk_level(result.get("theme_risk_level"))
        if risk_level not in KEYWORD_WRITE_RISK_LEVELS:
            continue
        for word in _dedup_words(result.get("tro_keywords", [])):
            tro_words.add(word.lower())
        for word in _dedup_words(result.get("uspto_keywords", [])):
            tm_words.add(word.lower())

    tro_map = {}
    if tro_words:
        rows = (
            TroTable.objects
            .annotate(theme_name_lower=Lower("theme_name"))
            .filter(theme_name_lower__in=tro_words)
        )
        for item in rows:
            key = _safe_str(item.theme_name).lower()
            if key and key not in tro_map:
                tro_map[key] = item

    tm_map = {}
    if tm_words:
        rows = (
            TrademarkInfo.objects
            .annotate(word_mark_lower=Lower("word_mark"))
            .filter(word_mark_lower__in=tm_words)
        )
        for item in rows:
            key = _safe_str(item.word_mark).lower()
            if key and key not in tm_map:
                tm_map[key] = item

    return tro_map, tm_map


def _sync_listing_risk(
    title_map: Dict[str, List[AmazonListing]],
    analysis_map: Dict[str, Dict],
    tro_map: Dict,
    tm_map: Dict,
) -> Dict[str, int]:
    updated_count = 0
    high_count = 0
    medium_count = 0
    low_count = 0
    unknown_count = 0
    now_time = timezone.now()

    listing_updates = []
    listing_ids = []
    tro_rel_rows = []
    tm_rel_rows = []

    tro_through = AmazonListing.tro_words.through
    tm_through = AmazonListing.trademarks.through
    tro_source_fk, tro_target_fk = _resolve_through_fk_names(tro_through)
    tm_source_fk, tm_target_fk = _resolve_through_fk_names(tm_through)

    for title, listings in title_map.items():
        result = analysis_map.get(title) or {}
        risk_level = _normalize_risk_level(result.get("theme_risk_level"))

        tro_keywords = [word.lower() for word in _dedup_words(result.get("tro_keywords", []))]
        uspto_keywords = [word.lower() for word in _dedup_words(result.get("uspto_keywords", []))]

        if risk_level in KEYWORD_WRITE_RISK_LEVELS:
            tro_objects = [tro_map[w] for w in tro_keywords if w in tro_map]
            tm_objects = [tm_map[w] for w in uspto_keywords if w in tm_map]
        else:
            tro_objects = []
            tm_objects = []

        for listing in listings:
            listing.risk_level = risk_level
            listing.updated_at = now_time
            listing_updates.append(listing)
            listing_ids.append(listing.id)

            for tro_obj in tro_objects:
                tro_rel_rows.append(
                    tro_through(
                        **{
                            f"{tro_source_fk}_id": listing.id,
                            f"{tro_target_fk}_id": tro_obj.pk,
                        }
                    )
                )

            for tm_obj in tm_objects:
                tm_rel_rows.append(
                    tm_through(
                        **{
                            f"{tm_source_fk}_id": listing.id,
                            f"{tm_target_fk}_id": tm_obj.pk,
                        }
                    )
                )

            updated_count += 1

            if risk_level == "high":
                high_count += 1
            elif risk_level == "medium":
                medium_count += 1
            elif risk_level == "low":
                low_count += 1
            else:
                unknown_count += 1

    if listing_updates:
        AmazonListing.objects.bulk_update(
            listing_updates,
            fields=["risk_level", "updated_at"],
            batch_size=2000,
        )

    if listing_ids:
        tro_through.objects.filter(**{f"{tro_source_fk}_id__in": listing_ids}).delete()
        tm_through.objects.filter(**{f"{tm_source_fk}_id__in": listing_ids}).delete()

        if tro_rel_rows:
            tro_through.objects.bulk_create(tro_rel_rows, batch_size=5000)
        if tm_rel_rows:
            tm_through.objects.bulk_create(tm_rel_rows, batch_size=5000)

    return {
        "updated_count": updated_count,
        "high_count": high_count,
        "medium_count": medium_count,
        "low_count": low_count,
        "unknown_count": unknown_count,
    }


def _resolve_through_fk_names(through_model):
    source_fk = None
    target_fk = None
    for field in through_model._meta.fields:
        if not getattr(field, "many_to_one", False):
            continue
        related_model = field.remote_field.model
        if related_model == AmazonListing:
            source_fk = field.name
        else:
            target_fk = field.name
    if not source_fk or not target_fk:
        raise RuntimeError(f"无法识别 through model 字段: {through_model.__name__}")
    return source_fk, target_fk


def _process_one_sid(
    current_sid: int,
    include_known: bool,
    only_active: bool,
    title_batch_size: int,
    max_titles: Optional[int] = None,
) -> SidRiskStats:
    close_old_connections()
    sid_stats = SidRiskStats(sid=current_sid)
    try:
        sid_queryset = _get_target_queryset(
            sid=current_sid,
            include_known=include_known,
            only_active=only_active,
        )
        sid_listings = list(sid_queryset.iterator(chunk_size=2000))
        if not sid_listings:
            return sid_stats

        sid_stats.target_listings = len(sid_listings)
        title_map = _build_title_map_from_listings(sid_listings)
        unique_titles = list(title_map.keys())
        if max_titles is not None:
            unique_titles = unique_titles[:max(0, int(max_titles))]
            title_map = {title: title_map[title] for title in unique_titles}
        sid_stats.unique_titles = len(unique_titles)

        if sid_stats.unique_titles <= 0:
            return sid_stats

        _log(
            "info",
            "risk.sid.start",
            sid=current_sid,
            target_listings=sid_stats.target_listings,
            unique_titles=sid_stats.unique_titles,
        )

        analysis_map, failed_titles, analyzed_titles, batch_errors = _batch_analyze_titles(
            unique_titles=unique_titles,
            title_batch_size=title_batch_size,
            sid=current_sid,
        )
        sid_stats.analyzed_titles = analyzed_titles
        sid_stats.error_count += batch_errors

        ready_title_map = {title: title_map[title] for title in unique_titles if title in analysis_map}
        if failed_titles:
            _log(
                "warning",
                "risk.sid.partial_failed",
                sid=current_sid,
                failed_title_count=len(failed_titles),
            )
        if not ready_title_map:
            _log("warning", "risk.sid.no_analyzed_titles", sid=current_sid)
            return sid_stats

        sid_analysis_map = {title: analysis_map[title] for title in ready_title_map.keys()}
        tro_map, tm_map = _build_word_object_maps(sid_analysis_map)

        with transaction.atomic():
            sync_stats = _sync_listing_risk(
                title_map=ready_title_map,
                analysis_map=sid_analysis_map,
                tro_map=tro_map,
                tm_map=tm_map,
            )

        sid_stats.listings_updated = sync_stats["updated_count"]
        sid_stats.high_count = sync_stats["high_count"]
        sid_stats.medium_count = sync_stats["medium_count"]
        sid_stats.low_count = sync_stats["low_count"]
        sid_stats.unknown_count = sync_stats["unknown_count"]
        sid_stats.committed = True
        _log(
            "info",
            "risk.sid.done",
            sid=current_sid,
            committed_listings=sid_stats.listings_updated,
            committed_titles=len(ready_title_map),
        )
        return sid_stats
    except Exception as exc:
        sid_stats.error_count += 1
        _log(
            "error",
            "risk.sid.failed",
            sid=current_sid,
            error=str(exc),
            traceback=traceback.format_exc(),
        )
        return sid_stats
    finally:
        close_old_connections()


def run_risk_worker(
    sid: Optional[int] = None,
    include_known: bool = False,
    only_active: bool = True,
    title_batch_size: int = 800,
    max_titles: Optional[int] = None,
    workers: int = 4,
) -> RiskWorkerStats:
    stats = RiskWorkerStats()
    sid_list = _get_target_sid_list(sid=sid, include_known=include_known, only_active=only_active)
    if not sid_list:
        _log("info", "risk.no_target_listings", sid=sid, include_known=include_known, only_active=only_active)
        return stats

    stats.total_sids = len(sid_list)
    remaining_titles = None if max_titles is None else max(0, int(max_titles))

    _log(
        "info",
        "risk.start",
        sid=sid,
        total_sids=stats.total_sids,
        title_batch_size=title_batch_size,
        workers=max(1, int(workers)),
        include_known=include_known,
        only_active=only_active,
        rerun_rule="title_changed_should_be_marked_unknown_in_ingest",
    )

    worker_count = max(1, int(workers))
    if remaining_titles is not None and worker_count > 1:
        _log("warning", "risk.parallel.disabled_for_max_titles", reason="max_titles_requires_ordered_sequential")
        worker_count = 1

    if worker_count <= 1 or len(sid_list) <= 1:
        for current_sid in sid_list:
            if remaining_titles is not None and remaining_titles <= 0:
                break
            sid_stats = _process_one_sid(
                current_sid=current_sid,
                include_known=include_known,
                only_active=only_active,
                title_batch_size=title_batch_size,
                max_titles=remaining_titles,
            )
            _merge_stats(stats, sid_stats)
            if remaining_titles is not None:
                remaining_titles -= sid_stats.unique_titles
    else:
        max_workers = min(worker_count, len(sid_list))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_map = {
                executor.submit(
                    _process_one_sid,
                    current_sid,
                    include_known,
                    only_active,
                    title_batch_size,
                    None,
                ): current_sid
                for current_sid in sid_list
            }
            for future in as_completed(future_map):
                sid_stats = future.result()
                _merge_stats(stats, sid_stats)

    _log(
        "info",
        "risk.done",
        sid=sid,
        total_sids=stats.total_sids,
        committed_sids=stats.committed_sids,
        total_listings=stats.total_listings,
        total_titles=stats.total_titles,
        analyzed_titles=stats.analyzed_titles,
        listings_updated=stats.listings_updated,
        high=stats.high_count,
        medium=stats.medium_count,
        low=stats.low_count,
        unknown=stats.unknown_count,
        errors=stats.error_count,
    )
    return stats


def _merge_stats(global_stats: RiskWorkerStats, sid_stats: SidRiskStats) -> None:
    global_stats.total_listings += sid_stats.target_listings
    global_stats.total_titles += sid_stats.unique_titles
    global_stats.analyzed_titles += sid_stats.analyzed_titles
    global_stats.listings_updated += sid_stats.listings_updated
    global_stats.error_count += sid_stats.error_count
    global_stats.high_count += sid_stats.high_count
    global_stats.medium_count += sid_stats.medium_count
    global_stats.low_count += sid_stats.low_count
    global_stats.unknown_count += sid_stats.unknown_count
    if sid_stats.committed:
        global_stats.committed_sids += 1


def _parse_args():
    parser = argparse.ArgumentParser(description="Amazon Listing 侵权风险批量分析脚本")
    parser.add_argument("--sid", type=int, default=None, help="仅处理单店铺 sid")
    parser.add_argument("--include-known", action="store_true", help="包含已存在风险等级数据")
    parser.add_argument("--include-inactive", action="store_true", help="包含非在售 listing")
    parser.add_argument("--title-batch-size", type=int, default=800, help="每批分析标题数")
    parser.add_argument("--max-titles", type=int, default=None, help="最多分析标题数量（调试用）")
    parser.add_argument("--workers", type=int, default=4, help="按 sid 并发 worker 数")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    run_risk_worker(
        sid=args.sid,
        include_known=args.include_known,
        only_active=not args.include_inactive,
        title_batch_size=max(1, int(args.title_batch_size)),
        max_titles=args.max_titles,
        workers=max(1, int(args.workers)),
    )
