import argparse
import json
import os
import sys
from dataclasses import dataclass
from typing import Dict, List, Optional

import django
from django.db import transaction


project_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(project_path)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Overlord.settings")
django.setup()

from theme.models import TroTable  # noqa: E402


JSON_TO_DB_NAME_TYPE = {
    1: 1,
    4: 4,
    5: 5,
    7: 7,
    8: 8,
    9: 10,
    10: 11,
}


@dataclass
class JsonThemeRecord:
    normalized_theme_name: str
    raw_theme_name: str
    db_name_type: int


def normalize_theme_name(theme_name: str) -> str:
    return theme_name.strip().lower()


def map_json_name_type(value) -> Optional[int]:
    try:
        json_name_type = int(value)
    except (TypeError, ValueError):
        return None
    return JSON_TO_DB_NAME_TYPE.get(json_name_type)


def load_json_theme_records(json_file_path: str):
    with open(json_file_path, "r", encoding="utf-8") as f:
        payload = json.load(f)

    if not isinstance(payload, list):
        raise ValueError("JSON 顶层结构必须是数组")

    theme_map: Dict[str, JsonThemeRecord] = {}
    empty_theme_name_count = 0
    invalid_name_type_count = 0

    for item in payload:
        if not isinstance(item, dict):
            invalid_name_type_count += 1
            continue

        raw_theme_name = (item.get("themeName") or "").strip()
        if not raw_theme_name:
            empty_theme_name_count += 1
            continue

        mapped_name_type = map_json_name_type(item.get("nameType"))
        if mapped_name_type is None:
            invalid_name_type_count += 1
            continue

        key = normalize_theme_name(raw_theme_name)
        # 同名词如果在 JSON 重复出现，按最后一条覆盖。
        theme_map[key] = JsonThemeRecord(
            normalized_theme_name=key,
            raw_theme_name=raw_theme_name,
            db_name_type=mapped_name_type,
        )

    return theme_map, empty_theme_name_count, invalid_name_type_count


@transaction.atomic
def sync_theme_tro_table(theme_map: Dict[str, JsonThemeRecord]):
    db_rows = list(TroTable.objects.values("id", "theme_name", "name_type"))

    db_grouped: Dict[str, List[dict]] = {}
    for row in db_rows:
        theme_name = (row.get("theme_name") or "").strip()
        if not theme_name:
            continue
        key = normalize_theme_name(theme_name)
        db_grouped.setdefault(key, []).append(row)

    inserted_theme_count = 0
    updated_theme_count = 0
    updated_row_count = 0
    skipped_existing_theme_count = 0

    for key, json_record in theme_map.items():
        if key in db_grouped:
            rows = db_grouped[key]
            target_name_type = json_record.db_name_type

            row_ids_to_update = []
            for row in rows:
                db_name_type = row.get("name_type")
                if db_name_type != target_name_type:
                    row_ids_to_update.append(row["id"])

            if not row_ids_to_update:
                skipped_existing_theme_count += 1
                continue

            updated = TroTable.objects.filter(id__in=row_ids_to_update).update(
                name_type=target_name_type
            )
            updated_row_count += updated
            updated_theme_count += 1
        else:
            TroTable.objects.create(
                theme_name=json_record.raw_theme_name,
                name_type=json_record.db_name_type,
            )
            inserted_theme_count += 1

    return (
        inserted_theme_count,
        updated_theme_count,
        skipped_existing_theme_count,
        updated_row_count,
    )


def find_default_json_path() -> str:
    candidates = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "divi侵权词全量数据.json"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "divi侵权词库全量数据.json"),
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    raise FileNotFoundError("未找到 divi 侵权词 JSON 文件，请通过 --json-file 指定路径")


def main():
    parser = argparse.ArgumentParser(
        description="将 divi 侵权词 JSON 同步到 theme_tro_table（含 nameType 映射）"
    )
    parser.add_argument(
        "--json-file",
        default=None,
        help="JSON 文件路径，默认自动在当前目录查找 divi侵权词全量数据.json / divi侵权词库全量数据.json",
    )
    args = parser.parse_args()

    json_file_path = args.json_file or find_default_json_path()

    print(f"读取 JSON: {json_file_path}")
    theme_map, empty_theme_name_count, invalid_name_type_count = load_json_theme_records(
        json_file_path
    )
    print(f"JSON 唯一 theme_name 数量: {len(theme_map)}")
    print(f"跳过空 themeName: {empty_theme_name_count}")
    print(f"跳过无效/未映射 nameType: {invalid_name_type_count}")

    (
        inserted_theme_count,
        updated_theme_count,
        skipped_existing_theme_count,
        updated_row_count,
    ) = sync_theme_tro_table(theme_map)
    print("同步完成")
    print("结果统计:")
    print(f"插入了 {inserted_theme_count} 条")
    print(f"更新了 {updated_theme_count} 条")
    print(f"跳过（已存在）了 {skipped_existing_theme_count} 条")
    print(f"更新影响数据库行数: {updated_row_count}")


if __name__ == "__main__":
    main()
