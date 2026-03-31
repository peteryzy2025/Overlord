import argparse
import csv
import os
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import django
from django.db import transaction
from django.db.models import Count
from django.utils import timezone

# ====== Django 初始化路径（参考 amazon/sync_listing_risk_worker.py）======
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
APP_ROOT = os.path.dirname(CURRENT_DIR)
PROJECT_ROOT = os.path.dirname(APP_ROOT)


LOW_RISK_NAME_TYPES = {1, 9}
HIGH_RISK_NAME_TYPES = {4, 5, 6, 7, 10, 11}


def setup_django(settings_module: str) -> None:
    if PROJECT_ROOT not in sys.path:
        sys.path.insert(0, PROJECT_ROOT)

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", settings_module)
    django.setup()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="TroTable 去重脚本：支持 dry-run 预览和 apply 删除。"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="执行真实删除；默认仅 dry-run 预览，不修改数据。",
    )
    parser.add_argument(
        "--settings",
        default="Overlord.settings",
        help="Django settings 模块路径，默认 Overlord.settings",
    )
    parser.add_argument(
        "--question-word-file",
        default=None,
        help="question_word 文本文件输出路径，默认当前目录自动命名。",
    )
    parser.add_argument(
        "--preview-file",
        default=None,
        help="预览 CSV 输出路径，默认当前目录自动命名。",
    )
    parser.add_argument(
        "--theme",
        default=None,
        help="只处理指定 theme_name（精确匹配）。",
    )
    return parser.parse_args()


def _ts_key(dt: Optional[datetime]) -> float:
    if dt is None:
        return float("-inf")
    return dt.timestamp()


def pick_latest(records: Iterable[Dict]) -> Dict:
    return max(records, key=lambda x: (_ts_key(x.get("update_time")), x["id"]))


def default_output_paths() -> tuple[Path, Path]:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = Path.cwd()
    question_path = base / f"question_words_{stamp}.txt"
    preview_path = base / f"dedup_preview_{stamp}.csv"
    return question_path, preview_path


def write_question_words(path: Path, words: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for word in words:
            f.write(f"{word}\n")


def write_preview_csv(path: Path, preview_rows: List[Dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "theme_name",
        "group_size",
        "distinct_name_type_count",
        "has_low_risk",
        "keep_id",
        "keep_name_type",
        "keep_update_time",
        "delete_ids",
        "decision",
        "reason",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(preview_rows)


def format_dt(dt: Optional[datetime]) -> str:
    if dt is None:
        return ""
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def main() -> None:
    args = parse_args()
    setup_django(args.settings)

    from theme.models import TroTable

    now_question_path, now_preview_path = default_output_paths()
    question_file = Path(args.question_word_file) if args.question_word_file else now_question_path
    preview_file = Path(args.preview_file) if args.preview_file else now_preview_path

    dup_qs = TroTable.objects.values("theme_name").annotate(cnt=Count("id")).filter(cnt__gt=1)
    if args.theme:
        dup_qs = dup_qs.filter(theme_name=args.theme)

    duplicate_theme_names = list(dup_qs.values_list("theme_name", flat=True))
    if not duplicate_theme_names:
        print("未找到重复的 theme_name 记录，无需处理。")
        print(f"question_word 文件: {question_file}")
        print(f"预览文件: {preview_file}")
        write_question_words(question_file, [])
        write_preview_csv(preview_file, [])
        return

    rows = list(
        TroTable.objects.filter(theme_name__in=duplicate_theme_names).values(
            "id", "theme_name", "name_type", "update_time"
        )
    )

    grouped = defaultdict(list)
    for row in rows:
        grouped[row["theme_name"]].append(row)

    question_words: List[str] = []
    preview_rows: List[Dict] = []
    delete_ids: List[int] = []

    mixed_groups = 0
    same_type_groups = 0
    no_low_risk_groups = 0

    for theme_name in sorted(grouped.keys()):
        records = grouped[theme_name]
        distinct_name_types = {r.get("name_type") for r in records}
        has_low_risk = any((r.get("name_type") in LOW_RISK_NAME_TYPES) for r in records)

        keep_record = None
        group_delete_ids: List[int] = []
        decision = ""
        reason = ""

        if len(distinct_name_types) > 1:
            mixed_groups += 1
            low_risk_records = [r for r in records if r.get("name_type") in LOW_RISK_NAME_TYPES]
            if low_risk_records:
                keep_record = pick_latest(low_risk_records)
                group_delete_ids = [r["id"] for r in records if r["id"] != keep_record["id"]]
                decision = "mixed_types_keep_latest_low_risk"
                reason = "存在低风险类型，保留最新低风险记录"
            else:
                no_low_risk_groups += 1
                question_words.append(theme_name)
                decision = "question_word_no_low_risk"
                reason = "混合类型且无低风险，不执行删除"
        else:
            same_type_groups += 1
            keep_record = pick_latest(records)
            group_delete_ids = [r["id"] for r in records if r["id"] != keep_record["id"]]
            decision = "same_type_keep_latest"
            reason = "同类型重复，仅保留最新记录"

        delete_ids.extend(group_delete_ids)

        preview_rows.append(
            {
                "theme_name": theme_name,
                "group_size": len(records),
                "distinct_name_type_count": len(distinct_name_types),
                "has_low_risk": int(has_low_risk),
                "keep_id": keep_record["id"] if keep_record else "",
                "keep_name_type": keep_record["name_type"] if keep_record else "",
                "keep_update_time": format_dt(keep_record["update_time"]) if keep_record else "",
                "delete_ids": "|".join(str(i) for i in sorted(group_delete_ids)),
                "decision": decision,
                "reason": reason,
            }
        )

    unique_delete_ids = sorted(set(delete_ids))
    unique_question_words = sorted(set(question_words))

    write_question_words(question_file, unique_question_words)
    write_preview_csv(preview_file, preview_rows)

    print("TroTable 去重分析完成")
    print(f"执行模式: {'APPLY(真实删除)' if args.apply else 'DRY-RUN(仅预览)'}")
    if args.theme:
        print(f"限定主题词: {args.theme}")
    print(f"重复 theme_name 组数: {len(grouped)}")
    print(f"混合类型组数: {mixed_groups}")
    print(f"同类型组数: {same_type_groups}")
    print(f"question_word 组数: {no_low_risk_groups}")
    print(f"可删除记录数: {len(unique_delete_ids)}")
    print(f"question_word 数量: {len(unique_question_words)}")
    print(f"question_word 文件: {question_file}")
    print(f"预览文件: {preview_file}")

    if unique_question_words:
        sample = ", ".join(unique_question_words[:20])
        print(f"question_word 示例(最多20个): {sample}")

    if args.apply:
        if not unique_delete_ids:
            print("无需删除，任务结束。")
            return
        with transaction.atomic():
            deleted_count, _ = TroTable.objects.filter(id__in=unique_delete_ids).delete()
        print(f"实际删除行数: {deleted_count}")
    else:
        print("当前为 dry-run，未删除任何数据。")
        print("如需执行删除，请增加参数: --apply")


if __name__ == "__main__":
    main()
