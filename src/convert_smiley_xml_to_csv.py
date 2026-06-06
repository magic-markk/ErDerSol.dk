import argparse
import csv
from datetime import datetime
from pathlib import Path
from xml.etree.ElementTree import iterparse


FIELD_MAP = {
    "navnelbnr": "navnelbnr",
    "cvrnr": "cvrnr",
    "pnr": "pnr",
    "region": "region",
    "brancheKode": "branche_kode",
    "branche": "branche",
    "virksomhedstype": "virksomhedstype",
    "navn1": "navn",
    "adresse1": "adresse",
    "postnr": "postnr",
    "By": "bynavn",
    "seneste_kontrol": "seneste_kontrol",
    "seneste_kontrol_dato": "seneste_kontrol_dato",
    "naestseneste_kontrol": "naestseneste_kontrol",
    "naestseneste_kontrol_dato": "naestseneste_kontrol_dato",
    "tredjeseneste_kontrol": "tredjeseneste_kontrol",
    "tredjeseneste_kontrol_dato": "tredjeseneste_kontrol_dato",
    "fjerdeseneste_kontrol": "fjerdeseneste_kontrol",
    "fjerdeseneste_kontrol_dato": "fjerdeseneste_kontrol_dato",
    "URL": "url",
    "reklame_beskyttelse": "reklame_beskyttelse",
    "Elite_Smiley": "elite_smiley",
    "Kaedenavn": "kaedenavn",
    "Geo_Lng": "geo_lng",
    "Geo_Lat": "geo_lat",
    "Pixibranche": "pixibranche",
}

COLUMNS = [
    "navnelbnr",
    "cvrnr",
    "pnr",
    "region",
    "branche_kode",
    "branche",
    "virksomhedstype",
    "navn",
    "adresse",
    "postnr",
    "bynavn",
    "seneste_kontrol",
    "seneste_kontrol_dato",
    "naestseneste_kontrol",
    "naestseneste_kontrol_dato",
    "tredjeseneste_kontrol",
    "tredjeseneste_kontrol_dato",
    "fjerdeseneste_kontrol",
    "fjerdeseneste_kontrol_dato",
    "url",
    "reklame_beskyttelse",
    "elite_smiley",
    "kaedenavn",
    "geo_lng",
    "geo_lat",
    "pixibranche",
]

DATE_COLUMNS = {
    "seneste_kontrol_dato",
    "naestseneste_kontrol_dato",
    "tredjeseneste_kontrol_dato",
    "fjerdeseneste_kontrol_dato",
}
BOOLEAN_COLUMNS = {"reklame_beskyttelse", "elite_smiley"}


def clean_text(value: str | None) -> str:
    if value is None:
        return ""

    return value.strip()


def convert_value(column: str, value: str | None) -> str:
    value = clean_text(value)
    if not value:
        return ""

    if column in DATE_COLUMNS:
        return datetime.strptime(value, "%d-%m-%Y %H:%M:%S").date().isoformat()

    if column in BOOLEAN_COLUMNS:
        return "true" if value == "1" else "false"

    return value


def row_to_record(row_element) -> dict[str, str]:
    record = {column: "" for column in COLUMNS}

    for child in row_element:
        column = FIELD_MAP.get(child.tag)
        if column is None:
            continue

        record[column] = convert_value(column, child.text)

    return record


def convert_xml_to_csv(xml_path: Path, csv_path: Path) -> int:
    row_count = 0

    with csv_path.open("w", encoding="utf-8-sig", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=COLUMNS)
        writer.writeheader()

        for _, element in iterparse(xml_path, events=("end",)):
            if element.tag != "row":
                continue

            writer.writerow(row_to_record(element))
            row_count += 1
            element.clear()

            if row_count % 10000 == 0:
                print(f"Converted {row_count} rows...")

    return row_count


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert Smiley.xml to Supabase-ready CSV.")
    parser.add_argument("--xml", default="Smiley.xml", type=Path)
    parser.add_argument("--csv", default="smiley.csv", type=Path)
    args = parser.parse_args()

    row_count = convert_xml_to_csv(args.xml, args.csv)
    print(f"Done. Wrote {row_count} rows to {args.csv}")


if __name__ == "__main__":
    main()
