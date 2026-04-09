"""Remove trailing empty columns from Referencias.csv (keep only first 6)."""
import csv
from pathlib import Path

CSV_PATH = Path(__file__).resolve().parents[1] / "output/2015/csv/Referencias.csv"

def main():
    rows = []
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        reader = csv.reader(f, delimiter=";")
        for row in reader:
            rows.append(row[:6])  # keep only article, description, doi, link, accessed, order

    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerows(rows)

    print(f"Atualizado: {CSV_PATH}")
    print(f"Colunas mantidas: 6 (article; description; doi; link; accessed; order)")

if __name__ == "__main__":
    main()
