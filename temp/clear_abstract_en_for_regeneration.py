#!/usr/bin/env python3
"""
Clear abstractEn in articles_metadata_apos_do_field_completion.json so the next
migration run re-runs field completion for English abstract (extraction-first).

Usage:
  conda run -n llms python temp/clear_abstract_en_for_regeneration.py --year 2012
  conda run -n llms python temp/clear_abstract_en_for_regeneration.py --year 2012 --seq 11
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
from datetime import datetime


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", required=True, help="Proceedings year, e.g. 2012")
    parser.add_argument(
        "--seq",
        type=int,
        default=None,
        help="Only clear abstractEn for this seq; omit to clear all articles",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print actions without writing",
    )
    args = parser.parse_args()

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(
        root,
        "output",
        str(args.year),
        "logs",
        "articles_metadata_apos_do_field_completion.json",
    )
    if not os.path.isfile(path):
        raise SystemExit(f"File not found: {path}")

    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise SystemExit("Expected JSON array")

    backup = path + ".bak." + datetime.now().strftime("%Y%m%d%H%M%S")
    if not args.dry_run:
        shutil.copy2(path, backup)
        print(f"Backup: {backup}")

    n = 0
    for item in data:
        if not isinstance(item, dict):
            continue
        if args.seq is not None and int(item.get("seq") or 0) != args.seq:
            continue
        prev = str(item.get("abstractEn", "") or "")[:100]
        item["abstractEn"] = ""
        n += 1
        print(
            f"  Cleared abstractEn seq={item.get('seq')} "
            f"idJEMS={item.get('idJEMS')} preview_was={prev!r}"
        )

    if args.dry_run:
        print(f"(dry-run) Would clear {n} record(s)")
        return

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"Cleared abstractEn on {n} record(s). Re-run migration to regenerate.")


if __name__ == "__main__":
    main()
