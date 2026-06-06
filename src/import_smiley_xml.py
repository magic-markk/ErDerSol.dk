import argparse
import os
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from xml.etree.ElementTree import iterparse

import requests


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

INTEGER_FIELDS = {
    "navnelbnr",
    "cvrnr",
    "pnr",
    "seneste_kontrol",
    "naestseneste_kontrol",
    "tredjeseneste_kontrol",
    "fjerdeseneste_kontrol",
}
DATE_FIELDS = {
    "seneste_kontrol_dato",
    "naestseneste_kontrol_dato",
    "tredjeseneste_kontrol_dato",
    "fjerdeseneste_kontrol_dato",
}
BOOLEAN_FIELDS = {"reklame_beskyttelse", "elite_smiley"}
DECIMAL_FIELDS = {"geo_lng", "geo_lat"}


def clean_text(value: str | None) -> str | None:
    if value is None:
        return None

    value = value.strip()
    return value or None


def parse_date(value: str | None) -> str | None:
    value = clean_text(value)
    if value is None:
        return None

    return datetime.strptime(value, "%d-%m-%Y %H:%M:%S").date().isoformat()


def parse_decimal(value: str | None) -> str | None:
    value = clean_text(value)
    if value is None:
        return None

    try:
        return str(Decimal(value))
    except InvalidOperation as error:
        raise ValueError(f"Invalid decimal value: {value}") from error


def convert_value(column: str, value: str | None) -> Any:
    value = clean_text(value)

    if value is None:
        return None
    if column in INTEGER_FIELDS:
        return int(value)
    if column in DATE_FIELDS:
        return parse_date(value)
    if column in BOOLEAN_FIELDS:
        return value == "1"
    if column in DECIMAL_FIELDS:
        return parse_decimal(value)

    return value


def row_to_record(row_element: Any) -> dict[str, Any]:
    record: dict[str, Any] = {}

    for child in row_element:
        column = FIELD_MAP.get(child.tag)
        if column is None:
            continue

        record[column] = convert_value(column, child.text)

    return record


def upsert_batch(
    session: requests.Session,
    supabase_url: str,
    service_role_key: str,
    table_name: str,
    batch: list[dict[str, Any]],
) -> None:
    endpoint = f"{supabase_url.rstrip('/')}/rest/v1/{table_name}"
    response = session.post(
        endpoint,
        params={"on_conflict": "navnelbnr"},
        headers={
            "apikey": service_role_key,
            "Authorization": f"Bearer {service_role_key}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates,return=minimal",
        },
        json=batch,
        timeout=60,
    )

    if response.status_code not in {200, 201, 204}:
        raise RuntimeError(
            f"Supabase upload failed with {response.status_code}: {response.text}"
        )


def import_xml(
    xml_path: Path,
    supabase_url: str,
    service_role_key: str,
    table_name: str,
    batch_size: int,
) -> int:
    batch: list[dict[str, Any]] = []
    imported_count = 0

    with requests.Session() as session:
        for _, element in iterparse(xml_path, events=("end",)):
            if element.tag != "row":
                continue

            record = row_to_record(element)
            if "navnelbnr" not in record or record["navnelbnr"] is None:
                element.clear()
                continue

            batch.append(record)
            element.clear()

            if len(batch) >= batch_size:
                upsert_batch(
                    session,
                    supabase_url,
                    service_role_key,
                    table_name,
                    batch,
                )
                imported_count += len(batch)
                print(f"Imported {imported_count} rows...")
                batch.clear()

        if batch:
            upsert_batch(
                session,
                supabase_url,
                service_role_key,
                table_name,
                batch,
            )
            imported_count += len(batch)

    return imported_count


def main() -> None:
    parser = argparse.ArgumentParser(description="Import Smiley.xml into Supabase.")
    parser.add_argument(
        "--xml",
        default="Smiley.xml",
        type=Path,
        help="Path to Smiley.xml",
    )
    parser.add_argument("--table", default="smiley", help="Supabase table name")
    parser.add_argument("--batch-size", default=500, type=int)
    args = parser.parse_args()

    supabase_url = os.environ.get("SUPABASE_URL")
    service_role_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

    if not supabase_url or not service_role_key:
        raise SystemExit(
            "Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY before running import."
        )

    imported_count = import_xml(
        xml_path=args.xml,
        supabase_url=supabase_url,
        service_role_key=service_role_key,
        table_name=args.table,
        batch_size=args.batch_size,
    )
    print(f"Done. Imported/upserted {imported_count} rows.")


if __name__ == "__main__":
    main()
