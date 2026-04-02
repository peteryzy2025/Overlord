# import os
# import sys
# import asyncio
# import json
# import logging
# import traceback
# from dataclasses import dataclass
# from typing import Dict, List, Optional
# from decimal import Decimal, InvalidOperation
#
# # ====== Django 初始化 ======
# # 说明：
# # 1) 当前脚本在 amazon/view/ 目录下，需要将项目根目录加入 sys.path。
# # 2) 必须先设置 DJANGO_SETTINGS_MODULE，再调用 django.setup()。
# CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
# PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
# sys.path.insert(0, PROJECT_ROOT)
#
# os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Overlord.settings")
#
# import django
#
# django.setup()
#
# import argparse
#
# from django.db import transaction
# from django.utils import timezone
#
# from api.lingxing.Y_OpenApi import get_api_resp
# from amazon.models import AmazonListingLegacy, LingXingAmazonShop
#
#
# PAGE_SIZE = 1000
# DEFAULT_RISK_LEVEL = "unknown"
#
# LOGGER = logging.getLogger("amazon.listing_ingest.sync")
# if not LOGGER.handlers:
#     handler = logging.StreamHandler()
#     handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
#     LOGGER.addHandler(handler)
# LOGGER.setLevel(logging.INFO)
# LOGGER.propagate = False
#
#
# @dataclass
# class ShopIngestStats:
#     sid: int
#     shop_name: str
#     fetched_count: int = 0
#     normalized_count: int = 0
#     skipped_missing_asin: int = 0
#     skipped_deleted: int = 0
#     skipped_invalid_status: int = 0
#     listing_created: int = 0
#     listing_updated: int = 0
#     listing_skipped: int = 0
#     blocked_active_downgrade: int = 0
#     error_count: int = 0
#
#
# def _log(level: str, event: str, **payload) -> None:
#     message = json.dumps({"event": event, **payload}, ensure_ascii=False, default=str)
#     if level == "error":
#         LOGGER.error(message)
#     elif level == "warning":
#         LOGGER.warning(message)
#     else:
#         LOGGER.info(message)
#
#
# def _safe_str(value) -> str:
#     return (value or "").strip()
#
#
# def _to_int_or_none(value):
#     try:
#         return int(str(value).strip())
#     except (TypeError, ValueError, AttributeError):
#         return None
#
#
# def _to_decimal_or_none(value):
#     """将值转换为 Decimal，失败返回 None"""
#     from decimal import Decimal, InvalidOperation
#     try:
#         return Decimal(str(value).strip())
#     except (TypeError, ValueError, AttributeError, InvalidOperation):
#         return None
#
#
# def _extract_data_field(item: Dict, field_name: str):
#     """从嵌套的 data 对象中提取字段"""
#     data = item.get("data") or {}
#     return data.get(field_name)
#
#
# def _to_bool_listing_active(item: Dict) -> bool:
#     status_value = item.get("status", None)
#     if status_value is None:
#         status_value = item.get("is_active", None)
#     parsed = _to_int_or_none(status_value)
#     return parsed == 1
#
#
# def _resolve_effective_is_active(current_is_active: Optional[bool], incoming_is_active: bool):
#     """
#     is_active 单向升级策略：
#     - False -> True: 允许
#     - True -> False: 拦截，保持 True
#     """
#     incoming_bool = bool(incoming_is_active)
#     current_bool = bool(current_is_active)
#     blocked = current_bool and (not incoming_bool)
#     if blocked:
#         return True, True
#     return incoming_bool, False
#
#
# def page(page_num: int) -> int:
#     return (page_num - 1) * PAGE_SIZE
#
#
# async def lingxing_api_info_getter(sid, page_offset=0):
#     try:
#         resp = await get_api_resp(
#             req_body={
#                 "sid": sid,
#                 "offset": page_offset,
#             },
#             api_path="/erp/sc/data/mws/listing",
#             method="POST",
#         )
#         _log(
#             "info",
#             "api.response",
#             sid=sid,
#             offset=page_offset,
#             data_len=len(getattr(resp, "data", []) or []),
#             total=getattr(resp, "total", None),
#             code=getattr(resp, "code", None),
#         )
#         return resp
#     except Exception as exc:
#         _log(
#             "error",
#             "api.exception",
#             sid=sid,
#             offset=page_offset,
#             error=str(exc),
#             traceback=traceback.format_exc(),
#         )
#         raise
#
#
# def get_total_page_num(sid, page_offset) -> int:
#     resp = asyncio.run(lingxing_api_info_getter(sid, page_offset))
#     total = getattr(resp, "total", 0) or 0
#     if total <= 0:
#         _log("warning", "api.total.empty_or_zero", sid=sid, offset=page_offset, total=total, total_pages=1)
#         return 1
#     total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
#     _log("info", "api.total.pages_computed", sid=sid, offset=page_offset, total=total, total_pages=total_pages)
#     return total_pages
#
#
# def get_lingxing_api_listing_info(sid, page_offset) -> List[Dict]:
#     resp = asyncio.run(lingxing_api_info_getter(sid, page_offset))
#     return getattr(resp, "data", []) or []
#
#
# def process_lingxing_api_listing_info(sid, page_offset):
#     data = get_lingxing_api_listing_info(sid, page_offset)
#     rows = []
#     counters = {
#         "raw_count": len(data),
#         "normalized_count": 0,
#         "skipped_missing_asin": 0,
#         "skipped_deleted": 0,
#         "skipped_invalid_status": 0,
#     }
#
#     for item in data:
#         is_delete = _to_int_or_none(item.get("is_delete"))
#         if is_delete == 1:
#             counters["skipped_deleted"] += 1
#             continue
#
#         status_raw = item.get("status", item.get("is_active"))
#         parsed_status = _to_int_or_none(status_raw)
#         if parsed_status not in {0, 1}:
#             counters["skipped_invalid_status"] += 1
#             continue
#
#         asin = _safe_str(item.get("asin"))
#         if not asin:
#             counters["skipped_missing_asin"] += 1
#             continue
#
#         # 提取销量和销售额字段（从 data 嵌套对象中）
#         volume_1d = _to_int_or_none(_extract_data_field(item, "yesterday_volume"))
#         volume_7d = _to_int_or_none(_extract_data_field(item, "total_volume"))
#         volume_14d = _to_int_or_none(_extract_data_field(item, "fourteen_volume"))
#         volume_30d = _to_int_or_none(_extract_data_field(item, "thirty_volume"))
#
#         amount_1d = _to_decimal_or_none(_extract_data_field(item, "yesterday_amount"))
#         amount_7d = _to_decimal_or_none(_extract_data_field(item, "seven_amount"))
#         amount_14d = _to_decimal_or_none(_extract_data_field(item, "fourteen_amount"))
#         amount_30d = _to_decimal_or_none(_extract_data_field(item, "thirty_amount"))
#
#         avg_volume_7d = _to_int_or_none(_extract_data_field(item, "average_seven_volume"))
#         avg_volume_14d = _to_int_or_none(_extract_data_field(item, "average_fourteen_volume"))
#         avg_volume_30d = _to_int_or_none(_extract_data_field(item, "average_thirty_volume"))
#
#         # 提取排名所属类别（列表）
#         seller_category_raw = item.get("seller_category_new")
#         seller_category_new = seller_category_raw if isinstance(seller_category_raw, list) else []
#
#         rows.append(
#             {
#                 "asin": asin,
#                 "title": _safe_str(item.get("item_name")),
#                 "fulfillment_channel_type": _safe_str(item.get("fulfillment_channel_type")),
#                 "is_active": (parsed_status == 1),
#                 # 新增字段
#                 "small_image_url": _safe_str(item.get("small_image_url")),
#                 "seller_sku": _safe_str(item.get("seller_sku")),
#                 "seller_rank": _to_int_or_none(item.get("seller_rank")),
#                 "seller_category_new": seller_category_new,
#                 # 销量字段
#                 "volume_1d": volume_1d,
#                 "volume_7d": volume_7d,
#                 "volume_14d": volume_14d,
#                 "volume_30d": volume_30d,
#                 # 销售额字段
#                 "amount_1d": amount_1d,
#                 "amount_7d": amount_7d,
#                 "amount_14d": amount_14d,
#                 "amount_30d": amount_30d,
#                 # 日均销量字段
#                 "avg_volume_7d": avg_volume_7d,
#                 "avg_volume_14d": avg_volume_14d,
#                 "avg_volume_30d": avg_volume_30d,
#             }
#         )
#
#     counters["normalized_count"] = len(rows)
#     _log(
#         "info",
#         "page.rows.normalized",
#         sid=sid,
#         offset=page_offset,
#         **counters,
#     )
#     return rows, counters
#
#
# def _upsert_one_base_listing(shop: LingXingAmazonShop, row: Dict, stats: ShopIngestStats) -> str:
#     listing = AmazonListingLegacy.objects.filter(lingxing_shop=shop, asin=row["asin"]).first()
#     incoming_title = row["title"]
#     incoming_active = bool(row["is_active"])
#
#     if listing is None:
#         AmazonListingLegacy.objects.create(
#             lingxing_shop=shop,
#             asin=row["asin"],
#             title=incoming_title,
#             is_active=incoming_active,
#             risk_level=DEFAULT_RISK_LEVEL,
#             # 新增字段
#             small_image_url=row.get("small_image_url") or None,
#             seller_sku=row.get("seller_sku") or None,
#             seller_rank=row.get("seller_rank"),
#             seller_category_new=row.get("seller_category_new") or [],
#             # 销量字段
#             volume_1d=row.get("volume_1d"),
#             volume_7d=row.get("volume_7d"),
#             volume_14d=row.get("volume_14d"),
#             volume_30d=row.get("volume_30d"),
#             # 销售额字段
#             amount_1d=row.get("amount_1d"),
#             amount_7d=row.get("amount_7d"),
#             amount_14d=row.get("amount_14d"),
#             amount_30d=row.get("amount_30d"),
#             # 日均销量字段
#             avg_volume_7d=row.get("avg_volume_7d"),
#             avg_volume_14d=row.get("avg_volume_14d"),
#             avg_volume_30d=row.get("avg_volume_30d"),
#         )
#         stats.listing_created += 1
#         return "created"
#
#     effective_active, blocked_downgrade = _resolve_effective_is_active(
#         current_is_active=listing.is_active,
#         incoming_is_active=incoming_active,
#     )
#     if blocked_downgrade:
#         stats.blocked_active_downgrade += 1
#
#     old_title = _safe_str(listing.title)
#     title_changed = old_title != incoming_title
#     active_changed = bool(listing.is_active) != bool(effective_active)
#
#     # 注意：15个新字段（销量、销售额等）每次都全量更新，不判断是否变化
#     # 只有 title 变化才用于触发风险检测（清空关联词、重置 risk_level）
#     if not title_changed and not active_changed:
#         # 即使没有基础字段变化，也更新动态数据字段（销量、销售额等）
#         listing.updated_at = timezone.now()
#         listing.small_image_url = row.get("small_image_url") or None
#         listing.seller_sku = row.get("seller_sku") or None
#         listing.seller_rank = row.get("seller_rank")
#         listing.seller_category_new = row.get("seller_category_new") or []
#         listing.volume_1d = row.get("volume_1d")
#         listing.volume_7d = row.get("volume_7d")
#         listing.volume_14d = row.get("volume_14d")
#         listing.volume_30d = row.get("volume_30d")
#         listing.amount_1d = row.get("amount_1d")
#         listing.amount_7d = row.get("amount_7d")
#         listing.amount_14d = row.get("amount_14d")
#         listing.amount_30d = row.get("amount_30d")
#         listing.avg_volume_7d = row.get("avg_volume_7d")
#         listing.avg_volume_14d = row.get("avg_volume_14d")
#         listing.avg_volume_30d = row.get("avg_volume_30d")
#         listing.save(update_fields=[
#             "updated_at",
#             "small_image_url", "seller_sku", "seller_rank", "seller_category_new",
#             "volume_1d", "volume_7d", "volume_14d", "volume_30d",
#             "amount_1d", "amount_7d", "amount_14d", "amount_30d",
#             "avg_volume_7d", "avg_volume_14d", "avg_volume_30d",
#         ])
#         stats.listing_updated += 1
#         return "updated"
#
#     # title 或 is_active 有变化的情况
#     listing.title = incoming_title
#     listing.is_active = effective_active
#     listing.updated_at = timezone.now()
#     update_fields = ["title", "is_active", "updated_at"]
#
#     # 只有 title 变化时才重置风险等级（触发风险检测）
#     if title_changed:
#         listing.risk_level = DEFAULT_RISK_LEVEL
#         update_fields.append("risk_level")
#
#     # 同时更新所有新字段
#     listing.small_image_url = row.get("small_image_url") or None
#     listing.seller_sku = row.get("seller_sku") or None
#     listing.seller_rank = row.get("seller_rank")
#     listing.seller_category_new = row.get("seller_category_new") or []
#     listing.volume_1d = row.get("volume_1d")
#     listing.volume_7d = row.get("volume_7d")
#     listing.volume_14d = row.get("volume_14d")
#     listing.volume_30d = row.get("volume_30d")
#     listing.amount_1d = row.get("amount_1d")
#     listing.amount_7d = row.get("amount_7d")
#     listing.amount_14d = row.get("amount_14d")
#     listing.amount_30d = row.get("amount_30d")
#     listing.avg_volume_7d = row.get("avg_volume_7d")
#     listing.avg_volume_14d = row.get("avg_volume_14d")
#     listing.avg_volume_30d = row.get("avg_volume_30d")
#     update_fields.extend([
#         "small_image_url", "seller_sku", "seller_rank", "seller_category_new",
#         "volume_1d", "volume_7d", "volume_14d", "volume_30d",
#         "amount_1d", "amount_7d", "amount_14d", "amount_30d",
#         "avg_volume_7d", "avg_volume_14d", "avg_volume_30d",
#     ])
#
#     listing.save(update_fields=update_fields)
#
#     # 标题变化后先清空历史词关联，避免旧词关联污染。
#     if title_changed:
#         listing.tro_words.clear()
#         listing.trademarks.clear()
#
#     stats.listing_updated += 1
#     return "updated"
#
#
# def ingest_shop_base_data(sid, page_num=1, max_pages: Optional[int] = None) -> ShopIngestStats:
#     shop = LingXingAmazonShop.objects.select_related("amazon_shop__ops").filter(sid=sid).first()
#     if not shop:
#         raise ValueError(f"店铺 sid={sid} 不存在")
#
#     stats = ShopIngestStats(sid=shop.sid, shop_name=shop.name or "")
#     current_page_num = max(1, int(page_num))
#     total_page_num = get_total_page_num(sid, page(current_page_num))
#
#     while current_page_num <= total_page_num:
#         if max_pages is not None and current_page_num > max_pages:
#             break
#
#         page_offset = page(current_page_num)
#         _log("info", "page.start", sid=sid, page_num=current_page_num, offset=page_offset)
#         try:
#             page_rows, counters = process_lingxing_api_listing_info(sid, page_offset)
#         except Exception as exc:
#             stats.error_count += 1
#             _log(
#                 "error",
#                 "page.fetch.failed",
#                 sid=sid,
#                 page_num=current_page_num,
#                 offset=page_offset,
#                 error=str(exc),
#                 traceback=traceback.format_exc(),
#             )
#             break
#
#         stats.fetched_count += counters["raw_count"]
#         stats.normalized_count += counters["normalized_count"]
#         stats.skipped_missing_asin += counters["skipped_missing_asin"]
#         stats.skipped_deleted += counters["skipped_deleted"]
#         stats.skipped_invalid_status += counters["skipped_invalid_status"]
#
#         if not page_rows:
#             _log(
#                 "info",
#                 "page.empty.stop",
#                 sid=sid,
#                 page_num=current_page_num,
#                 offset=page_offset,
#             )
#             current_page_num += 1
#             continue
#
#         try:
#             with transaction.atomic():
#                 for row in page_rows:
#                     _upsert_one_base_listing(shop, row, stats)
#         except Exception:
#             stats.error_count += 1
#             _log(
#                 "error",
#                 "db.write.rollback",
#                 sid=sid,
#                 page_num=current_page_num,
#                 offset=page_offset,
#                 traceback=traceback.format_exc(),
#             )
#
#         _log(
#             "info",
#             "page.done",
#             sid=sid,
#             page_num=current_page_num,
#             offset=page_offset,
#             fetched_count=stats.fetched_count,
#             normalized_count=stats.normalized_count,
#             created_count=stats.listing_created,
#             updated_count=stats.listing_updated,
#             skipped_count=stats.listing_skipped,
#             blocked_active_downgrade=stats.blocked_active_downgrade,
#             skipped_deleted=stats.skipped_deleted,
#             skipped_invalid_status=stats.skipped_invalid_status,
#             errors=stats.error_count,
#         )
#         current_page_num += 1
#
#     return stats
#
#
# def ingest_all_us_shops(max_shops: Optional[int] = None, max_pages_per_shop: Optional[int] = None) -> List[ShopIngestStats]:
#     shops = LingXingAmazonShop.objects.select_related("amazon_shop__ops").filter(name__contains="US")
#     if max_shops is not None:
#         shops = shops[:max(0, int(max_shops))]
#
#     all_stats = []
#     for shop in shops:
#         try:
#             _log("info", "shop.start", sid=shop.sid, shop_name=shop.name)
#             stat = ingest_shop_base_data(shop.sid, page_num=1, max_pages=max_pages_per_shop)
#             all_stats.append(stat)
#             _log(
#                 "info",
#                 "shop.done",
#                 sid=stat.sid,
#                 shop_name=stat.shop_name,
#                 fetched=stat.fetched_count,
#                 normalized=stat.normalized_count,
#                 created=stat.listing_created,
#                 updated=stat.listing_updated,
#                 skipped=stat.listing_skipped,
#                 blocked_active_downgrade=stat.blocked_active_downgrade,
#                 skipped_deleted=stat.skipped_deleted,
#                 skipped_invalid_status=stat.skipped_invalid_status,
#                 errors=stat.error_count,
#             )
#         except Exception as exc:
#             _log(
#                 "error",
#                 "shop.failed",
#                 sid=shop.sid,
#                 shop_name=shop.name,
#                 error=str(exc),
#                 traceback=traceback.format_exc(),
#             )
#     return all_stats
#
#
# def _parse_args():
#     parser = argparse.ArgumentParser(description="Amazon Listing 基础入库脚本（不做侵权分析）")
#     parser.add_argument("--sid", type=int, default=None, help="仅处理单店铺 sid")
#     parser.add_argument("--max-shops", type=int, default=None, help="最多处理店铺数")
#     parser.add_argument("--max-pages", type=int, default=None, help="每店铺最多处理页数")
#     parser.add_argument("--start-page", type=int, default=1, help="单店铺模式起始页")
#     return parser.parse_args()
#
#
# if __name__ == "__main__":
#     args = _parse_args()
#     _log("info", "ingest.start", sid=args.sid, max_shops=args.max_shops, max_pages=args.max_pages)
#     if args.sid:
#         result = ingest_shop_base_data(args.sid, page_num=args.start_page, max_pages=args.max_pages)
#         _log(
#             "info",
#             "ingest.done",
#             sid=result.sid,
#             created=result.listing_created,
#             updated=result.listing_updated,
#             blocked_active_downgrade=result.blocked_active_downgrade,
#         )
#     else:
#         results = ingest_all_us_shops(max_shops=args.max_shops, max_pages_per_shop=args.max_pages)
#         _log("info", "ingest.done", synced_shops=len(results))
