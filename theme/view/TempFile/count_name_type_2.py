import argparse
import re
from pathlib import Path


PATTERN = re.compile(r'"nameType"\s*:\s*2(?!\d)')


def count_name_type_2(file_path: Path, chunk_size: int = 4 * 1024 * 1024, overlap: int = 8192) -> int:
    total = 0
    tail = ""

    with file_path.open("r", encoding="utf-8", errors="ignore") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                total += len(PATTERN.findall(tail))
                break

            data = tail + chunk
            if len(data) <= overlap:
                tail = data
                continue

            scan_part = data[:-overlap]
            total += len(PATTERN.findall(scan_part))
            tail = data[-overlap:]

    return total


def main() -> None:
    parser = argparse.ArgumentParser(
        description='Count occurrences of "nameType": 2 in a large JSON file without loading it fully into memory.'
    )
    parser.add_argument(
        "file",
        nargs="?",
        default="divi侵权词库全量数据.json",
        help="Path to JSON file (default: divi侵权词库全量数据.json)",
    )
    args = parser.parse_args()

    file_path = Path(args.file)
    if not file_path.exists():
        raise SystemExit(f"File not found: {file_path}")

    count = count_name_type_2(file_path)
    print(count)


if __name__ == "__main__":
    main()
