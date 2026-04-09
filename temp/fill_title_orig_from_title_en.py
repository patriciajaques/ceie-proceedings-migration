#!/usr/bin/env python3
"""
Script: for Artigos.csv rows with language=='en' and empty titleOrig,
copy titleEn to titleOrig.
"""
import csv
from pathlib import Path

CSV_PATH = Path(__file__).resolve().parents[1] / "output/2015/csv/Artigos.csv"


def main() -> None:
    with open(CSV_PATH, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter=";")
        rows = list(reader)
        fieldnames = reader.fieldnames

    updated = 0
    for row in rows:
        if row.get("language") == "en" and not (row.get("titleOrig") or "").strip():
            orig = (row.get("titleEn") or "").strip()
            if orig:
                row["titleOrig"] = orig
                updated += 1

    with open(CSV_PATH, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=";")
        writer.writeheader()
        writer.writerows(rows)

    print(f"Atualizados {updated} registro(s) em {CSV_PATH}")


if __name__ == "__main__":
    main()
