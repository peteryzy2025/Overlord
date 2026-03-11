import os
import sys
import asyncio
import json
import logging
import traceback
from dataclasses import dataclass
from typing import Dict, List, Optional

# ====== Django 初始化 ======
# 说明：
# 1) 当前脚本在 amazon/view/ 目录下，需要将项目根目录加入 sys.path。
# 2) 必须先设置 DJANGO_SETTINGS_MODULE，再调用 django.setup()。
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
sys.path.insert(0, PROJECT_ROOT)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Overlord.settings")

import django

django.setup()

from django.db import transaction
from django.db.models.functions import Lower
from django.utils import timezone

from api.lingxing.Y_OpenApi import get_api_resp
from amazon.models import AmazonListing, LingXingAmazonShop
from theme.models import TrademarkInfo, TroTable
from theme.view.views_trend import analyze_theme_trend


# 接口每页条数（按领星 listing 接口约定）
PAGE_SIZE = 1000
# 仅中高风险写入中间词表；低风险只写主表，不写词关联
KEYWORD_WRITE_RISK_LEVELS = {"high", "medium"}
# 默认精简日志：主表写入 + 关键进度事件
LOG_ONLY_AMAZON_LISTING_STATUS = True
LOG_PROGRESS_EVENTS = {
    "sync.start",
    "sync.done",
    "shop.start",
    "shop.done",
    "shop.failed",
    "api.total.pages_computed",
    "api.total.empty_or_zero",
    "api.response",
    "api.data.empty",
    "page.start",
    "page.done",
    "page.fetch.failed",
    "page.empty.stop",
    "row.analyze.failed",
}

NAME_TYPE_MAPPING = {
    1: "系统白名单",
    2: "用户未指定",
    3: "观察名单",
    4: "亚马逊涉嫌侵权",
    5: "律师函",
    6: "权利人投诉",
    7: "违禁词",
    8: "商标侵权",
    9: "自定义白名单",
    10: "知名IP",
}
LOW_RISK_NAME_TYPES = {1, 9}
HIGH_RISK_NAME_TYPES = {4, 5, 6, 7, 10, 11}
TRADEMARK_CHECK_NAME_TYPES = {2, 3, 8}
MEDIUM_RISK_STATUS_CODES = {
    0, 401, 404, 600, 601, 602, 604, 605, 606, 610, 616, 618, 620, 622, 624, 625,
    630, 631, 632, 638, 640, 641, 642, 643, 644, 645, 646, 647, 648, 649, 650, 651,
    652, 653, 654, 655, 656, 657, 658, 659, 660, 661, 663, 664, 665, 666, 667, 668,
    672, 680, 681, 682, 686, 688, 689, 690, 692, 693, 694, 710, 711, 712, 713, 715,
    717, 718, 719,
}
RISK_RANK = {"low": 0, "medium": 1, "high": 2}
VALID_RISK_LEVELS = {"high", "medium", "low", "unknown"}


LOGGER = logging.getLogger("amazon.new_demo.sync")
if not LOGGER.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
    LOGGER.addHandler(handler)
LOGGER.setLevel(logging.INFO)
LOGGER.propagate = False


@dataclass
class ShopSyncStats:
    """
    单店铺同步统计信息。

    字段说明：
    - sid/shop_name: 当前店铺标识
    - fetched_count: 从领星接口获取的原始可用 listing 数
    - analyzed_count: 实际调用 analyze_theme_trend 的条数
    - risk_kept_count: 命中中/高风险的条数（用于写中间表）
    - listing_created/listing_updated: amazon_listing 新增/更新数量
    - tro_rel_count/trademark_rel_count: 两张中间表关联数量
    - skipped_count: amazon_listing 已存在且 title/is_active 均未变化而跳过的条数
    - error_count: 异常条数
    """

    sid: int
    shop_name: str
    fetched_count: int = 0
    analyzed_count: int = 0
    risk_kept_count: int = 0
    listing_created: int = 0
    listing_updated: int = 0
    tro_rel_count: int = 0
    trademark_rel_count: int = 0
    skipped_count: int = 0
    blocked_active_downgrade: int = 0
    error_count: int = 0


def _log_event(level: str, event: str, **payload) -> None:
    """
    统一日志输出格式：单行 JSON，便于检索和后续导入日志系统。
    """
    if LOG_ONLY_AMAZON_LISTING_STATUS:
        is_main_table_write = (event == "db.write" and payload.get("table") == "amazon_listing")
        if not is_main_table_write and event not in LOG_PROGRESS_EVENTS:
            return

    msg = json.dumps({"event": event, **payload}, ensure_ascii=False, default=str)
    if level == "error":
        LOGGER.error(msg)
    elif level == "warning":
        LOGGER.warning(msg)
    else:
        LOGGER.info(msg)


def _log_db_write_on_commit(**payload) -> None:
    """
    仅在事务真正提交后输出 db.write success 日志，避免“执行成功但未提交”误导。
    """
    transaction.on_commit(lambda: _log_event("info", "db.write", **payload))


def page(page_num: int) -> int:
    """
    将页码转换为领星接口所需 offset。

    参数：
    - page_num: 从 1 开始的页码

    返回：
    - offset（第 1 页 -> 0，第 2 页 -> 1000 ...）
    """
    offset = (page_num - 1) * PAGE_SIZE
    return offset


def _safe_str(value) -> str:
    """
    将任意输入安全转为去首尾空格字符串。

    作用：
    - 避免 None 导致异常
    - 统一字符串比较和入库前处理
    """
    return (value or "").strip()


def _dedup_words(words) -> List[str]:
    """
    对词列表做“按小写去重 + 保持原顺序”。

    参数：
    - words: 原始词列表（可能包含空值、大小写重复）

    返回：
    - 去重后词列表
    """
    seen = set()
    result = []
    for word in words or []:
        normalized = _safe_str(word).lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(_safe_str(word))
    return result


def _normalize_risk_level(value, default: str = "unknown") -> str:
    risk = _safe_str(value).lower()
    if risk in VALID_RISK_LEVELS:
        return risk
    return default


def _resolve_effective_is_active(current_is_active: Optional[bool], incoming_is_active: bool):
    """
    is_active 单向升级策略：
    - False -> True: 允许
    - True -> False: 拦截，保持 True
    """
    incoming_bool = bool(incoming_is_active)
    current_bool = bool(current_is_active)
    blocked = current_bool and (not incoming_bool)
    if blocked:
        return True, True
    return incoming_bool, False


def _norm_word(word: str) -> str:
    return _safe_str(word).lower()


def _ordered_unique(words) -> List[str]:
    seen = set()
    result = []
    for word in words or []:
        key = _norm_word(word)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(_safe_str(word))
    return result


def _to_int_or_none(value):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError, AttributeError):
        return None


def _max_risk_level(a: str, b: str) -> str:
    return a if RISK_RANK.get(a, 0) >= RISK_RANK.get(b, 0) else b


def _build_status_code_map(words) -> Dict[str, set]:
    lower_words = {_norm_word(word) for word in words or [] if _norm_word(word)}
    if not lower_words:
        return {}

    rows = (
        TrademarkInfo.objects
        .annotate(word_mark_lower=Lower("word_mark"))
        .filter(word_mark_lower__in=lower_words)
        .values_list("word_mark_lower", "status_code_id")
    )
    result = {}
    for word_lower, status_code in rows:
        code_int = _to_int_or_none(status_code)
        if code_int is None:
            continue
        result.setdefault(word_lower, set()).add(code_int)
    return result


def _is_medium_by_status_codes(status_codes) -> bool:
    return bool((status_codes or set()) & MEDIUM_RISK_STATUS_CODES)


def _build_listing_risk_data(listing: AmazonListing, status_code_map=None) -> Dict:
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
                "word": _safe_str(word),
                "sources": [],
                "infringement_types": set(),
                "risk_level": "low",
            }
        return norm, merged[norm]

    for tro in tro_objects:
        norm, item = ensure_item(tro.theme_name)
        if not item:
            continue

        if "tro_words" not in item["sources"]:
            item["sources"].append("tro_words")

        mapped_type = NAME_TYPE_MAPPING.get(tro.name_type)
        if mapped_type:
            item["infringement_types"].add(mapped_type)

        if tro.name_type in HIGH_RISK_NAME_TYPES:
            current_risk = "high"
        elif tro.name_type in LOW_RISK_NAME_TYPES:
            current_risk = "low"
        elif tro.name_type in TRADEMARK_CHECK_NAME_TYPES:
            current_risk = "medium" if _is_medium_by_status_codes(status_code_map.get(norm, set())) else "low"
        else:
            current_risk = "low"

        item["risk_level"] = _max_risk_level(item["risk_level"], current_risk)

    for tm in trademark_objects:
        norm, item = ensure_item(tm.word_mark)
        if not item:
            continue

        if "trademarks" not in item["sources"]:
            item["sources"].append("trademarks")

        current_risk = "medium" if _is_medium_by_status_codes(status_code_map.get(norm, set())) else "low"
        item["risk_level"] = _max_risk_level(item["risk_level"], current_risk)

    high_risk_words = []
    medium_risk_words = []
    low_risk_words = []
    word_sources = []

    for item in merged.values():
        word = item["word"]
        risk_level = item["risk_level"]
        if risk_level == "high":
            high_risk_words.append(word)
        elif risk_level == "medium":
            medium_risk_words.append(word)
        else:
            low_risk_words.append(word)

        word_sources.append(
            {
                "word": word,
                "risk_level": risk_level,
                "sources": item["sources"],
                "infringement_type": ", ".join(sorted(item["infringement_types"])) if item["infringement_types"] else "",
            }
        )

    high_risk_words = _ordered_unique(high_risk_words)
    medium_risk_words = _ordered_unique(medium_risk_words)
    low_risk_words = _ordered_unique(low_risk_words)

    if high_risk_words:
        overall_risk = "high"
    elif medium_risk_words:
        overall_risk = "medium"
    else:
        overall_risk = "low"

    word_sources.sort(key=lambda x: (-RISK_RANK.get(x["risk_level"], 0), x["word"].lower()))
    return {
        "risk_level": overall_risk,
        "high_risk_words": high_risk_words,
        "medium_risk_words": medium_risk_words,
        "low_risk_words": low_risk_words,
        "word_sources": word_sources,
    }


def _update_listing_risk_level_after_relations(listing: AmazonListing, analysis_failed: bool, row_ctx: Dict) -> str:
    if analysis_failed:
        final_risk_level = "unknown"
    else:
        risk_data = _build_listing_risk_data(listing)
        final_risk_level = _normalize_risk_level(risk_data.get("risk_level"), default="low")

    if listing.risk_level != final_risk_level:
        previous_risk = listing.risk_level
        listing.risk_level = final_risk_level
        listing.updated_at = timezone.now()
        listing.save(update_fields=["risk_level", "updated_at"])
        _log_db_write_on_commit(
            table="amazon_listing",
            action="update_risk_level",
            status="success",
            fields=["risk_level", "updated_at"],
            previous_risk_level=previous_risk,
            current_risk_level=final_risk_level,
            **row_ctx,
        )
    else:
        _log_event(
            "info",
            "db.write",
            table="amazon_listing",
            action="skip_risk_level",
            status="skipped",
            reason="risk_level_unchanged",
            current_risk_level=final_risk_level,
            **row_ctx,
        )
    return final_risk_level


def _to_bool_listing_active(item: Dict) -> bool:
    """
    按领星 listing 接口字段解析 is_active 入库值。

    规则：
    - status == 1 -> True
    - status == 0 -> False
    - 若 status 缺失，兼容读取 is_active（历史字段）
    - 其他异常值 -> False
    """
    status_value = item.get("status", None)
    if status_value is None:
        status_value = item.get("is_active", None)

    parsed = _to_int_or_none(status_value)
    if parsed == 1:
        return True
    if parsed == 0:
        return False
    return False


async def lingxing_api_info_getter(sid, page_offset=0):
    """
    调用领星 listing 接口，返回原始响应对象。

    参数：
    - sid: 领星店铺 sid
    - page_offset: 接口 offset（不是页码）

    返回：
    - 接口响应对象（通常包含 .data / .total）
    """
    try:
        resp = await get_api_resp(
            req_body={
                "sid": sid,
                "offset": page_offset,
            },
            api_path="/erp/sc/data/mws/listing",
            method="POST",
        )
        data_len = len(getattr(resp, "data", []) or [])
        total = getattr(resp, "total", None)
        api_code = getattr(resp, "code", None)
        api_msg = _safe_str(
            getattr(resp, "msg", None)
            or getattr(resp, "message", None)
            or getattr(resp, "error_msg", None)
        )
        _log_event(
            "info",
            "api.response",
            sid=sid,
            offset=page_offset,
            data_len=data_len,
            total=total,
            code=api_code,
            message=api_msg,
        )
        return resp
    except Exception as exc:
        _log_event(
            "error",
            "api.exception",
            sid=sid,
            offset=page_offset,
            error=str(exc),
            traceback=traceback.format_exc(),
        )
        raise


def get_total_page_num(sid, page_offset) -> int:
    """
    根据接口返回 total 计算总页数。

    参数：
    - sid: 领星店铺 sid
    - page_offset: 初始 offset（通常传 page(1)）

    返回：
    - 总页数，最小值为 1
    """
    resp = asyncio.run(lingxing_api_info_getter(sid, page_offset))
    total = getattr(resp, "total", 0) or 0
    if total <= 0:
        _log_event(
            "warning",
            "api.total.empty_or_zero",
            sid=sid,
            offset=page_offset,
            total=total,
            fallback_total_pages=1,
        )
        return 1
    total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
    _log_event(
        "info",
        "api.total.pages_computed",
        sid=sid,
        offset=page_offset,
        total=total,
        total_pages=total_pages,
    )
    return total_pages


def get_lingxing_api_listing_info(sid, page_offset) -> List[Dict]:
    """
    获取某一页 listing 的 data 列表。

    参数：
    - sid: 领星店铺 sid
    - page_offset: offset

    返回：
    - listing 原始字典列表；无数据时返回 []
    """
    resp = asyncio.run(lingxing_api_info_getter(sid, page_offset))
    data = getattr(resp, "data", []) or []
    if not data:
        _log_event(
            "warning",
            "api.data.empty",
            sid=sid,
            offset=page_offset,
            total=getattr(resp, "total", None),
            code=getattr(resp, "code", None),
            message=_safe_str(
                getattr(resp, "msg", None)
                or getattr(resp, "message", None)
                or getattr(resp, "error_msg", None)
            ),
        )
    return data


def process_lingxing_api_listing_info(sid, page_offset) -> List[Dict]:
    """
    处理领星原始 listing，抽取本流程需要的基础字段。

    参数：
    - sid: 领星店铺 sid
    - page_offset: offset

    返回：
    - 标准化后的 listing 列表，每条包含：
      asin/title/fulfillment_channel_type/is_active

    说明：
    - is_delete=1 的记录会直接跳过（表示商品已删除）。
    - is_delete=0 时，按 status 解析 is_active 写入 amazon_listing.is_active 字段。
    - 只要能 fetch 到且有 asin，就进入主表入库流程。
    """
    data = get_lingxing_api_listing_info(sid, page_offset)
    rows = []
    skipped_missing_asin = 0
    skipped_deleted = 0
    skipped_invalid_status = 0
    for item in data:
        is_delete = _to_int_or_none(item.get("is_delete"))
        if is_delete == 1:
            skipped_deleted += 1
            continue

        status_raw = item.get("status", item.get("is_active"))
        parsed_status = _to_int_or_none(status_raw)
        if parsed_status not in {0, 1}:
            skipped_invalid_status += 1
            continue

        asin = _safe_str(item.get("asin"))
        title = _safe_str(item.get("item_name"))
        if not asin:
            skipped_missing_asin += 1
            continue

        rows.append(
            {
                "asin": asin,
                "title": title,
                "fulfillment_channel_type": _safe_str(item.get("fulfillment_channel_type")),
                "is_active": (parsed_status == 1),
            }
        )
    _log_event(
        "info",
        "page.rows.normalized",
        sid=sid,
        offset=page_offset,
        raw_count=len(data),
        normalized_count=len(rows),
        skipped_missing_asin=skipped_missing_asin,
        skipped_deleted=skipped_deleted,
        skipped_invalid_status=skipped_invalid_status,
    )
    return rows


def _load_word_source_objects(tro_keywords: List[str], uspto_keywords: List[str]):
    """
    将命中的词文本映射为数据库对象，用于写中间表。

    参数：
    - tro_keywords: analyze_theme_trend 命中的 tro 词文本列表
    - uspto_keywords: analyze_theme_trend 命中的 uspto 词文本列表

    返回：
    - (tro_objects, trademark_objects)
      tro_objects: TroTable 对象列表（用于 amazon_listing_tro_words）
      trademark_objects: TrademarkInfo 对象列表（用于 amazon_listing_trademarks）
    """
    tro_objects = list(TroTable.objects.filter(theme_name__in=tro_keywords))
    trademark_objects = list(TrademarkInfo.objects.filter(word_mark__in=uspto_keywords))
    return tro_objects, trademark_objects


def _upsert_one_listing(shop: LingXingAmazonShop, full_row: Dict, stats: ShopSyncStats) -> str:
    """
    将“完整数据行”写入三张目标表。

    参数：
    - shop: 当前店铺对象
    - full_row: 已拼接完成的完整数据（含 title + 风险分析 + 词来源）
    - stats: 统计对象

    入库行为：
    1) 先按 (shop, asin) 查询 amazon_listing 是否已存在
    2) 若已存在且 title/is_active 都相同：跳过
    3) 若已存在且 title 相同但 is_active 不同：仅更新 is_active（仅允许 False -> True）
    4) 其余情况（新增或 title 变化）：写主表 + 更新两张中间表 + 计算并写 risk_level

    返回：
    - created / updated / skipped
    """
    row_ctx = {
        "sid": shop.sid,
        "asin": full_row["asin"],
        "incoming_theme_risk_level": full_row.get("theme_risk_level"),
    }

    listing = AmazonListing.objects.filter(
        lingxing_shop=shop,
        asin=full_row["asin"],
    ).first()
    incoming_is_active = bool(full_row["is_active"])
    effective_is_active = incoming_is_active
    blocked_downgrade = False
    if listing is not None:
        effective_is_active, blocked_downgrade = _resolve_effective_is_active(
            current_is_active=listing.is_active,
            incoming_is_active=incoming_is_active,
        )
        if blocked_downgrade:
            stats.blocked_active_downgrade += 1

    title_changed = False
    active_changed = False
    if listing is not None:
        title_changed = (listing.title != full_row["title"])
        active_changed = (bool(listing.is_active) != bool(effective_is_active))

    if listing is not None and (not title_changed) and (not active_changed):
        stats.skipped_count += 1
        skip_reason = "title_and_is_active_same"
        if blocked_downgrade:
            skip_reason = "is_active_true_to_false_blocked"
        _log_event(
            "info",
            "db.write",
            table="amazon_listing",
            action="skip",
            status="skipped",
            reason=skip_reason,
            current_title=listing.title,
            incoming_title=full_row["title"],
            current_is_active=listing.is_active,
            incoming_is_active=incoming_is_active,
            effective_is_active=effective_is_active,
            match_key="lingxing_shop+asin",
            **row_ctx,
        )
        _log_event(
            "info",
            "db.write",
            table="amazon_listing_tro_words",
            action="skip",
            status="skipped",
            reason="main_row_skipped",
            **row_ctx,
        )
        _log_event(
            "info",
            "db.write",
            table="amazon_listing_trademarks",
            action="skip",
            status="skipped",
            reason="main_row_skipped",
            **row_ctx,
        )
        return "skipped"

    if listing is not None and (not title_changed) and active_changed:
        try:
            previous_is_active = listing.is_active
            listing.is_active = effective_is_active
            listing.updated_at = timezone.now()
            listing.save(update_fields=["is_active", "updated_at"])
            _log_db_write_on_commit(
                table="amazon_listing",
                action="update",
                status="success",
                fields=["is_active", "updated_at"],
                previous_is_active=previous_is_active,
                incoming_is_active=incoming_is_active,
                current_is_active=effective_is_active,
                match_key="lingxing_shop+asin",
                **row_ctx,
            )
        except Exception as exc:
            _log_event(
                "error",
                "db.write",
                table="amazon_listing",
                action="update",
                status="failed",
                error=str(exc),
                traceback=traceback.format_exc(),
                **row_ctx,
            )
            raise

        stats.listing_updated += 1
        return "updated"

    # 新增或 title 变化：更新主表后重建词关联，并基于迁移后的规则更新 risk_level
    created = False
    if listing is None:
        try:
            listing = AmazonListing.objects.create(
                lingxing_shop=shop,
                asin=full_row["asin"],
                title=full_row["title"],
                is_active=effective_is_active,
            )
            _log_db_write_on_commit(
                table="amazon_listing",
                action="insert",
                status="success",
                **row_ctx,
            )
        except Exception as exc:
            _log_event(
                "error",
                "db.write",
                table="amazon_listing",
                action="insert",
                status="failed",
                error=str(exc),
                traceback=traceback.format_exc(),
                **row_ctx,
            )
            raise
        created = True
        stats.listing_created += 1
    else:
        try:
            previous_is_active = listing.is_active
            previous_title = listing.title
            listing.is_active = effective_is_active
            listing.title = full_row["title"]
            listing.updated_at = timezone.now()
            listing.save(update_fields=["is_active", "title", "updated_at"])
            _log_db_write_on_commit(
                table="amazon_listing",
                action="update",
                status="success",
                fields=["is_active", "title", "updated_at"],
                previous_is_active=previous_is_active,
                incoming_is_active=incoming_is_active,
                current_is_active=effective_is_active,
                previous_title=previous_title,
                current_title=full_row["title"],
                **row_ctx,
            )
        except Exception as exc:
            _log_event(
                "error",
                "db.write",
                table="amazon_listing",
                action="update",
                status="failed",
                error=str(exc),
                traceback=traceback.format_exc(),
                **row_ctx,
            )
            raise
        stats.listing_updated += 1

    tro_objects, trademark_objects = _load_word_source_objects(
        full_row["tro_keywords"],
        full_row["uspto_keywords"],
    )

    try:
        listing.tro_words.set(tro_objects)
        _log_event(
            "info",
            "db.write",
            table="amazon_listing_tro_words",
            action="insert_or_replace",
            status="success",
            relation_count=len(tro_objects),
            **row_ctx,
        )
    except Exception as exc:
        _log_event(
            "error",
            "db.write",
            table="amazon_listing_tro_words",
            action="insert_or_replace",
            status="failed",
            error=str(exc),
            traceback=traceback.format_exc(),
            **row_ctx,
        )
        raise

    try:
        listing.trademarks.set(trademark_objects)
        _log_event(
            "info",
            "db.write",
            table="amazon_listing_trademarks",
            action="insert_or_replace",
            status="success",
            relation_count=len(trademark_objects),
            **row_ctx,
        )
    except Exception as exc:
        _log_event(
            "error",
            "db.write",
            table="amazon_listing_trademarks",
            action="insert_or_replace",
            status="failed",
            error=str(exc),
            traceback=traceback.format_exc(),
            **row_ctx,
        )
        raise

    stats.tro_rel_count += len(tro_objects)
    stats.trademark_rel_count += len(trademark_objects)

    final_risk_level = _update_listing_risk_level_after_relations(
        listing=listing,
        analysis_failed=bool(full_row.get("analysis_failed")),
        row_ctx=row_ctx,
    )
    full_row["persisted_risk_level"] = final_risk_level
    return "created" if created else "updated"


def full_listing_info(sid, page_num=1, max_pages: Optional[int] = None) -> ShopSyncStats:
    """
    单店铺全流程同步。

    流程：
    1) 使用 page(page_num) 分页拉取领星 listing
    2) 对每条 title 调用 analyze_theme_trend
    3) 无论高/中/低风险都写主表 amazon_listing
    4) 新增或 title 变化时更新词关联，并按迁移规则重算 risk_level

    参数：
    - sid: 领星店铺 sid
    - page_num: 起始页码（默认 1）
    - max_pages: 最大处理页数，None 表示按总页数跑完

    返回：
    - ShopSyncStats 统计对象
    """
    shop = LingXingAmazonShop.objects.select_related("amazon_shop__ops").filter(sid=sid).first()
    if not shop:
        raise ValueError(f"店铺 sid={sid} 不存在")

    stats = ShopSyncStats(sid=shop.sid, shop_name=shop.name or "")
    current_page_num = max(1, int(page_num))
    total_page_num = get_total_page_num(sid, page(current_page_num))

    while current_page_num <= total_page_num:
        if max_pages is not None and current_page_num > max_pages:
            break

        page_offset = page(current_page_num)
        _log_event(
            "info",
            "page.start",
            sid=sid,
            page_num=current_page_num,
            offset=page_offset,
        )
        try:
            page_rows = process_lingxing_api_listing_info(sid, page_offset)
        except Exception as exc:
            _log_event(
                "error",
                "page.fetch.failed",
                sid=sid,
                page_num=current_page_num,
                offset=page_offset,
                error=str(exc),
                traceback=traceback.format_exc(),
            )
            stats.error_count += 1
            break

        if not page_rows:
            _log_event(
                "info",
                "page.empty.stop",
                sid=sid,
                page_num=current_page_num,
                offset=page_offset,
                reason="api_returned_empty_data",
            )
            break

        stats.fetched_count += len(page_rows)
        prepared_rows = []
        for row in page_rows:
            analysis = {}
            risk_level = "unknown"
            theme_risk_text = ""
            tro_keywords = []
            uspto_keywords = []
            analysis_failed = False

            # 分析失败不影响主表入库：失败时按 unknown 落库。
            try:
                _log_event(
                    "info",
                    "row.start",
                    sid=sid,
                    page_num=current_page_num,
                    offset=page_offset,
                    asin=row["asin"],
                    title=row["title"],
                    is_active=row["is_active"],
                )
                stats.analyzed_count += 1
                analysis = analyze_theme_trend(row["title"],mode=2)
                risk_level = _normalize_risk_level(analysis.get("theme_risk_level"), default="unknown")
                theme_risk_text = _safe_str(analysis.get("theme_risk_text"))

                if risk_level in KEYWORD_WRITE_RISK_LEVELS:
                    stats.risk_kept_count += 1
                    tro_keywords = _dedup_words(analysis.get("tro_keywords", []))
                    uspto_keywords = _dedup_words(analysis.get("uspto_keywords", []))
                _log_event(
                    "info",
                    "row.analyze.done",
                    sid=sid,
                    asin=row["asin"],
                    risk_level=risk_level,
                    tro_keyword_count=len(tro_keywords),
                    uspto_keyword_count=len(uspto_keywords),
                )
            except Exception:
                stats.error_count += 1
                analysis_failed = True
                risk_level = "unknown"
                _log_event(
                    "error",
                    "row.analyze.failed",
                    sid=sid,
                    asin=row.get("asin"),
                    title=row.get("title"),
                    error="analyze_theme_trend_exception",
                    traceback=traceback.format_exc(),
                )

            # 【关键构造完整数据点】
            # 这里把三部分数据拼成“完整数据行”：
            # A. 领星接口字段：asin/title/is_active/fulfillment_channel_type
            # B. 数据库店铺字段：sid/shop_name/amazon_shop_name/shop_owner
            # C. analyze_theme_trend 字段：risk_level + tro/uspto 命中词
            full_row = {
                "sid": shop.sid,
                "shop_name": _safe_str(shop.name),
                "amazon_shop_name": _safe_str(
                    shop.amazon_shop.shop_name if shop.amazon_shop else ""
                ),
                "shop_owner": _safe_str(
                    shop.amazon_shop.ops.first_name
                    if shop.amazon_shop and shop.amazon_shop.ops
                    else ""
                ),
                "asin": row["asin"],
                "title": row["title"],
                "fulfillment_channel_type": row["fulfillment_channel_type"],
                "is_active": row["is_active"],
                "theme_risk_level": risk_level,
                "theme_risk_text": theme_risk_text,
                "tro_keywords": tro_keywords,
                "uspto_keywords": uspto_keywords,
                "analysis_failed": analysis_failed,
            }
            prepared_rows.append(full_row)

        # 每页一个事务：本页失败只回滚本页，不影响其他页。
        try:
            with transaction.atomic():
                for full_row in prepared_rows:
                    action = _upsert_one_listing(shop, full_row, stats)
                    _log_event(
                        "info",
                        "row.db.done",
                        sid=sid,
                        asin=full_row["asin"],
                        action=action,
                        risk_level=full_row.get("persisted_risk_level", full_row.get("theme_risk_level")),
                    )
        except Exception:
            stats.error_count += 1
            _log_event(
                "error",
                "db.write",
                table="amazon_listing",
                action="transaction_rollback",
                status="failed",
                sid=sid,
                asin="*PAGE*",
                risk_level="unknown",
                reason="page_transaction_rollback",
                page_num=current_page_num,
                offset=page_offset,
                traceback=traceback.format_exc(),
            )

        _log_event(
            "info",
            "page.done",
            sid=sid,
            page_num=current_page_num,
            offset=page_offset,
            fetched_count=stats.fetched_count,
            analyzed_count=stats.analyzed_count,
            created_count=stats.listing_created,
            updated_count=stats.listing_updated,
            skipped_count=stats.skipped_count,
            blocked_active_downgrade=stats.blocked_active_downgrade,
            error_count=stats.error_count,
        )
        current_page_num += 1

    return stats


def sync_all_us_shops(
    max_shops: Optional[int] = None,
    max_pages_per_shop: Optional[int] = None,
) -> List[ShopSyncStats]:
    """
    批量同步所有 US 店铺。

    参数：
    - max_shops: 最多处理店铺数（用于调试）；None 表示全部
    - max_pages_per_shop: 每个店铺最多处理页数；None 表示按总页数

    返回：
    - 每个店铺对应的 ShopSyncStats 列表
    """
    shops = LingXingAmazonShop.objects.select_related("amazon_shop__ops").filter(name__contains="US")
    if max_shops is not None:
        shops = shops[: max(0, int(max_shops))]

    all_stats = []
    for shop in shops:
        try:
            _log_event(
                "info",
                "shop.start",
                sid=shop.sid,
                shop_name=shop.name,
            )
            stat = full_listing_info(shop.sid, page_num=1, max_pages=max_pages_per_shop)
            all_stats.append(stat)
            _log_event(
                "info",
                "shop.done",
                sid=stat.sid,
                shop_name=stat.shop_name,
                fetched=stat.fetched_count,
                analyzed=stat.analyzed_count,
                kept=stat.risk_kept_count,
                created=stat.listing_created,
                updated=stat.listing_updated,
                tro_rel=stat.tro_rel_count,
                trademark_rel=stat.trademark_rel_count,
                skipped=stat.skipped_count,
                blocked_active_downgrade=stat.blocked_active_downgrade,
                errors=stat.error_count,
            )
        except Exception as exc:
            _log_event(
                "error",
                "shop.failed",
                sid=shop.sid,
                shop_name=shop.name,
                error=str(exc),
                traceback=traceback.format_exc(),
            )

    return all_stats


if __name__ == "__main__":
    """
    脚本直接运行入口。
    """
    _log_event("info", "sync.start")
    stats = sync_all_us_shops()
    _log_event("info", "sync.done", synced_shops=len(stats))
