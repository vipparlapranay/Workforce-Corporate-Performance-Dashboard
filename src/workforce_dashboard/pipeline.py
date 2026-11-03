from __future__ import annotations

import argparse
import csv
import json
import shutil
import tempfile
import urllib.request
import zipfile
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path, PurePosixPath
from typing import Any

import duckdb

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_REF = "generaterealdata/synthetic-hr-workforce-attrition"
SOURCE_VERSION = 2
SOURCE_URL = (
    "https://www.kaggle.com/datasets/generaterealdata/"
    "synthetic-hr-workforce-attrition"
)
SOURCE_CREDIT = (
    "Synthetic HR, Workforce and Attrition, GenerateRealData "
    "(CC BY 4.0); https://www.generaterealdata.com"
)
SOURCE_DOWNLOAD_URL = (
    "https://www.kaggle.com/api/v1/datasets/download/"
    f"{SOURCE_REF}?datasetVersionNumber={SOURCE_VERSION}"
)
TABLES = {
    "departments.csv": "raw_departments",
    "employees.csv": "raw_employees",
    "salaries.csv": "raw_salaries",
    "performance_reviews.csv": "raw_performance_reviews",
    "absences.csv": "raw_absences",
    "attrition_events.csv": "raw_attrition_events",
}
EXPORTS = {
    "dim_month.csv": (
        "SELECT * FROM dim_month ORDER BY month_start"
    ),
    "departments.csv": (
        "SELECT * FROM departments ORDER BY division, department_name"
    ),
    "monthly_workforce.csv": (
        "SELECT * FROM monthly_workforce ORDER BY month_start"
    ),
    "department_monthly.csv": (
        "SELECT * FROM department_monthly "
        "ORDER BY month_start, division, department_name"
    ),
    "department_scorecard.csv": (
        "SELECT * FROM department_scorecard ORDER BY trailing_12m_turnover_rate DESC"
    ),
    "division_scorecard.csv": (
        "SELECT * FROM division_scorecard ORDER BY trailing_12m_turnover_rate DESC"
    ),
    "absence_monthly.csv": (
        "SELECT * FROM absence_monthly ORDER BY month_start"
    ),
    "department_absence_monthly.csv": (
        "SELECT * FROM department_absence_monthly "
        "ORDER BY month_start, division, department_name"
    ),
    "performance_monthly.csv": (
        "SELECT * FROM performance_monthly ORDER BY month_start"
    ),
    "department_performance.csv": (
        "SELECT * FROM department_performance ORDER BY trailing_12m_average_rating DESC"
    ),
    "attrition_reasons.csv": (
        "SELECT * FROM attrition_reasons ORDER BY exits DESC"
    ),
    "exit_tenure_bands.csv": (
        "SELECT * FROM exit_tenure_bands ORDER BY tenure_at_exit_band"
    ),
    "retention_cohorts.csv": (
        "SELECT * FROM retention_cohorts ORDER BY cohort_month"
    ),
}
EXPECTED_TABLES = set(TABLES)
MAX_ARCHIVE_BYTES = 30_000_000
MAX_UNCOMPRESSED_BYTES = 50_000_000
MAX_TABLE_BYTES = 25_000_000


def _download_source(destination: Path) -> None:
    request = urllib.request.Request(
        SOURCE_DOWNLOAD_URL,
        headers={"User-Agent": "workforce-performance-dashboard/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            total = 0
            with destination.open("wb") as output:
                while block := response.read(1024 * 1024):
                    total += len(block)
                    if total > MAX_ARCHIVE_BYTES:
                        raise ValueError(
                            "The source archive exceeded the configured 30 MB limit."
                        )
                    output.write(block)
    except (OSError, TimeoutError) as error:
        raise RuntimeError(
            "Could not download the public Kaggle dataset. Check network access "
            "or pass a previously downloaded version-2 archive with --source-zip."
        ) from error
    if not zipfile.is_zipfile(destination):
        raise ValueError("The Kaggle download is not a valid ZIP archive.")


def _extract_source_tables(archive_path: Path, destination: Path) -> None:
    if archive_path.stat().st_size > MAX_ARCHIVE_BYTES:
        raise ValueError("The supplied source archive exceeds the 30 MB limit.")

    extracted: set[str] = set()
    uncompressed = 0
    try:
        with zipfile.ZipFile(archive_path) as archive:
            for entry in archive.infolist():
                path = PurePosixPath(entry.filename)
                if path.is_absolute() or ".." in path.parts:
                    raise ValueError("Unsafe path in source ZIP archive.")
                if entry.is_dir() or path.name not in EXPECTED_TABLES:
                    continue
                if len(path.parts) != 1:
                    raise ValueError("Source table CSVs must be at the ZIP root.")
                if path.name in extracted:
                    raise ValueError(f"Duplicate CSV in source ZIP: {path.name}.")
                if entry.file_size > MAX_TABLE_BYTES:
                    raise ValueError(f"Source table is too large: {path.name}.")
                uncompressed += entry.file_size
                if uncompressed > MAX_UNCOMPRESSED_BYTES:
                    raise ValueError("Uncompressed source tables exceed 50 MB.")
                with archive.open(entry) as source, (
                    destination / path.name
                ).open("wb") as output:
                    shutil.copyfileobj(source, output)
                extracted.add(path.name)
    except zipfile.BadZipFile as error:
        raise ValueError("The supplied source archive is not a valid ZIP.") from error

    missing = EXPECTED_TABLES - extracted
    if missing:
        raise ValueError(
            "The source archive is missing required tables: "
            + ", ".join(sorted(missing))
        )


def _sql_path(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/").replace("'", "''")


def _register_source_tables(
    connection: duckdb.DuckDBPyConnection,
    extracted_dir: Path,
) -> None:
    for filename, view_name in TABLES.items():
        path = _sql_path(extracted_dir / filename)
        connection.execute(
            f"""
            CREATE OR REPLACE TEMP VIEW {view_name} AS
            SELECT * FROM read_csv_auto(
                '{path}',
                header = true,
                sample_size = -1,
                null_padding = true
            )
            """
        )


def _run_quality_checks(
    connection: duckdb.DuckDBPyConnection,
) -> tuple[int, int]:
    sql = (PROJECT_ROOT / "sql" / "quality_checks.sql").read_text(
        encoding="utf-8"
    )
    checks = connection.execute(sql).fetchall()
    failing = [(name, count) for name, count in checks if count]
    if failing:
        detail = ", ".join(f"{name}: {count}" for name, count in failing)
        raise ValueError(f"Source data failed quality checks: {detail}")
    return len(checks), len(checks) - len(failing)


def _execute_models(connection: duckdb.DuckDBPyConnection) -> None:
    sql = (PROJECT_ROOT / "sql" / "transform.sql").read_text(
        encoding="utf-8"
    )
    connection.execute(sql)


def _json_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if hasattr(value, "item"):
        return value.item()
    return value


def _query_rows(
    connection: duckdb.DuckDBPyConnection, query: str
) -> tuple[list[str], list[dict[str, Any]]]:
    cursor = connection.execute(query)
    headers = [column[0] for column in cursor.description]
    rows = [
        {key: _json_value(value) for key, value in zip(headers, row, strict=True)}
        for row in cursor.fetchall()
    ]
    return headers, rows


def _write_exports(
    connection: duckdb.DuckDBPyConnection, output_dir: Path
) -> dict[str, list[dict[str, Any]]]:
    outputs: dict[str, list[dict[str, Any]]] = {}
    forbidden_columns = {
        "first_name",
        "last_name",
        "email",
        "employee_id",
        "date_of_birth",
    }
    for filename, query in EXPORTS.items():
        headers, rows = _query_rows(connection, query)
        unexpected = forbidden_columns.intersection(
            column.lower() for column in headers
        )
        if unexpected:
            raise ValueError(
                f"Refusing to export employee-level identifiers: {sorted(unexpected)}"
            )
        with (output_dir / filename).open(
            "w", encoding="utf-8-sig", newline=""
        ) as stream:
            writer = csv.DictWriter(stream, fieldnames=headers)
            writer.writeheader()
            writer.writerows(rows)
        outputs[filename.removesuffix(".csv")] = rows
    return outputs


def _build_workbook(
    path: Path,
    outputs: dict[str, list[dict[str, Any]]],
    metrics: dict[str, Any],
) -> None:
    import xlsxwriter

    workbook = xlsxwriter.Workbook(
        path,
        {"strings_to_formulas": False, "strings_to_urls": False},
    )
    workbook.set_properties(
        {
            "title": "Workforce and Corporate Performance",
            "subject": "Synthetic workforce metrics and data definitions",
            "author": "Workforce Analytics Portfolio",
            "comments": f"Source attribution: {SOURCE_CREDIT}.",
        }
    )
    navy = "#142D4E"
    teal = "#00A6A6"
    light = "#EAF1F8"
    title_format = workbook.add_format(
        {"bold": True, "font_size": 20, "font_color": "white", "bg_color": navy}
    )
    subtitle_format = workbook.add_format(
        {"font_color": "#43566B", "text_wrap": True, "valign": "top"}
    )
    header_format = workbook.add_format(
        {
            "bold": True,
            "font_color": "white",
            "bg_color": navy,
            "text_wrap": True,
            "border": 0,
        }
    )
    percent_format = workbook.add_format({"num_format": "0.0%"})
    date_format = workbook.add_format({"num_format": "yyyy-mm-dd"})
    kpi_percent_format = workbook.add_format(
        {
            "bold": True,
            "font_size": 18,
            "font_color": teal,
            "bg_color": light,
            "border": 1,
            "num_format": "0.0%",
        }
    )
    kpi_label_format = workbook.add_format(
        {"bold": True, "font_color": navy, "bg_color": light, "border": 1}
    )
    kpi_value_format = workbook.add_format(
        {
            "bold": True,
            "font_size": 18,
            "font_color": teal,
            "bg_color": light,
            "border": 1,
            "num_format": "#,##0.0",
        }
    )

    summary = workbook.add_worksheet("Executive Summary")
    summary.hide_gridlines(2)
    summary.set_column("A:A", 31)
    summary.set_column("B:B", 19)
    summary.set_column("C:C", 4)
    summary.set_column("D:D", 31)
    summary.set_column("E:E", 19)
    summary.merge_range("A1:E1", "WORKFORCE | EXECUTIVE SCORECARD", title_format)
    summary.merge_range(
        "A2:E3",
        (
            f"Synthetic training dataset | As of {metrics['as_of_date']} | "
            "All measures are descriptive; no employee-level data is included."
        ),
        subtitle_format,
    )
    kpis = [
        ("Employees in source", metrics["employee_records"]),
        ("Active headcount", metrics["active_headcount"]),
        ("Trailing 12-month turnover", metrics["trailing_12m_turnover_rate"]),
        ("Trailing 12-month exits", metrics["trailing_12m_exits"]),
        ("12-month cohort retention", metrics["weighted_12m_retention_rate"]),
        ("Absence days in source", metrics["absence_days_total"]),
    ]
    for index, (label, value) in enumerate(kpis):
        row = 5 + (index // 2) * 3
        col = (index % 2) * 3
        summary.merge_range(row, col, row, col + 1, label, kpi_label_format)
        summary.merge_range(
            row + 1,
            col,
            row + 1,
            col + 1,
            value,
            (
                kpi_percent_format
                if "turnover" in label.lower() or "retention" in label.lower()
                else kpi_value_format
            ),
        )
    summary.merge_range(
        "A16:E18",
        (
            "Interpretation guardrail: generated data is not evidence about a real "
            "employer or workforce. Turnover patterns are intentionally generated "
            "from tenure, so observed group differences are descriptive, not causal. "
            "The turnover target is an illustrative planning threshold, not an "
            "industry benchmark."
        ),
        subtitle_format,
    )
    summary.merge_range(
        "A20:E21",
        f"Source: {SOURCE_CREDIT}. {SOURCE_URL}",
        subtitle_format,
    )

    sheet_specs = [
        ("Monthly Workforce", "monthly_workforce"),
        ("Department Trends", "department_monthly"),
        ("Department Scorecard", "department_scorecard"),
        ("Division Scorecard", "division_scorecard"),
        ("Absence Trends", "absence_monthly"),
        ("Department Absence", "department_absence_monthly"),
        ("Performance Trends", "performance_monthly"),
        ("Department Performance", "department_performance"),
        ("Exit Reasons", "attrition_reasons"),
        ("Exit Tenure", "exit_tenure_bands"),
        ("Cohort Retention", "retention_cohorts"),
    ]
    worksheets: dict[str, Any] = {}
    for sheet_name, key in sheet_specs:
        rows = outputs[key]
        worksheet = workbook.add_worksheet(sheet_name)
        worksheets[key] = worksheet
        worksheet.freeze_panes(1, 0)
        worksheet.hide_gridlines(2)
        if rows:
            headers = list(rows[0])
            worksheet.write_row(0, 0, headers, header_format)
            for column_index, header in enumerate(headers):
                worksheet.set_column(
                    column_index,
                    column_index,
                    20,
                    percent_format
                    if "rate" in header.lower() or "share" in header.lower()
                    else None,
                )
            for row_index, row in enumerate(rows, start=1):
                for column_index, header in enumerate(headers):
                    value = row[header]
                    if (
                        isinstance(value, str)
                        and header.lower().endswith(
                            ("date", "month_start", "month_end", "cohort_month")
                        )
                    ):
                        worksheet.write_datetime(
                            row_index,
                            column_index,
                            datetime.fromisoformat(value),
                            date_format,
                        )
                    else:
                        worksheet.write(row_index, column_index, value)
            worksheet.autofilter(0, 0, len(rows), len(headers) - 1)

    monthly_sheet = worksheets["monthly_workforce"]
    monthly_rows = outputs["monthly_workforce"]
    monthly_headers = list(monthly_rows[0])
    index = {name: position for position, name in enumerate(monthly_headers)}
    chart = workbook.add_chart({"type": "line"})
    category_range = [
        "Monthly Workforce",
        1,
        index["month_start"],
        len(monthly_rows),
        index["month_start"],
    ]
    for column, title in (
        ("ending_headcount", "Month-end headcount"),
        ("monthly_turnover_rate", "Monthly turnover"),
    ):
        chart.add_series(
            {
                "name": title,
                "categories": category_range,
                "values": [
                    "Monthly Workforce",
                    1,
                    index[column],
                    len(monthly_rows),
                    index[column],
                ],
                "y2_axis": column == "monthly_turnover_rate",
            }
        )
    chart.set_title({"name": "Headcount and monthly turnover"})
    chart.set_x_axis({"name": "Month", "date_axis": True, "num_format": "mmm yy"})
    chart.set_y_axis({"name": "Headcount", "major_gridlines": {"visible": True}})
    chart.set_y2_axis({"name": "Turnover", "num_format": "0.0%"})
    chart.set_legend({"position": "bottom"})
    chart.set_size({"width": 900, "height": 390})
    summary.insert_chart("A23", chart)

    absence_rows = outputs["absence_monthly"]
    if absence_rows:
        absence_headers = list(absence_rows[0])
        absence_index = {name: pos for pos, name in enumerate(absence_headers)}
        absence_chart = workbook.add_chart({"type": "column"})
        absence_chart.add_series(
            {
                "name": "Absence days",
                "categories": [
                    "Absence Trends",
                    1,
                    absence_index["month_start"],
                    len(absence_rows),
                    absence_index["month_start"],
                ],
                "values": [
                    "Absence Trends",
                    1,
                    absence_index["absence_days"],
                    len(absence_rows),
                    absence_index["absence_days"],
                ],
                "fill": {"color": teal},
            }
        )
        absence_chart.set_title({"name": "Absence days by month"})
        absence_chart.set_x_axis({"name": "Month", "date_axis": True})
        absence_chart.set_y_axis({"name": "Days"})
        absence_chart.set_legend({"none": True})
        absence_chart.set_size({"width": 900, "height": 320})
        summary.insert_chart("A44", absence_chart)

    definitions = workbook.add_worksheet("Metric Definitions")
    definitions.hide_gridlines(2)
    definitions.set_column("A:A", 31)
    definitions.set_column("B:B", 104)
    definitions.write_row(0, 0, ["Metric", "Definition and caveat"], header_format)
    definitions_data = [
        (
            "Month-end headcount",
            "Employees hired by month-end whose termination date is after month-end, or is blank.",
        ),
        (
            "Monthly turnover",
            "Exits in month divided by the average of beginning- and end-of-month headcount.",
        ),
        (
            "Monthly retention",
            "Share of the opening-month employee cohort still active at month-end; new hires are excluded.",
        ),
        (
            "Trailing 12-month turnover",
            "Exits in the 12 complete months through the dataset cutoff divided by the average monthly average headcount.",
        ),
        (
            "12-month cohort retention",
            "Employees still active beyond their first anniversary divided by cohort members with a full 12-month observation window.",
        ),
        (
            "Absence days",
            "Calendar days of absence allocated to each month by date overlap and capped at the dataset cutoff. This is not a percentage of scheduled work days.",
        ),
        (
            "Absence days per active employee",
            "Absence days divided by average active headcount. A volume indicator, not an official absenteeism rate.",
        ),
        (
            "Target",
            "Illustrative monthly turnover threshold configured in the Power BI guide; not an external benchmark.",
        ),
        (
            "Driver analysis",
            "Descriptive associations in generated data only. The source explicitly says attrition depends on tenure, not pay, performance, level or department.",
        ),
    ]
    for row_index, row in enumerate(definitions_data, start=1):
        definitions.write_row(row_index, 0, row, subtitle_format)
        definitions.set_row(row_index, 34)

    workbook.close()


def _build_metrics(
    connection: duckdb.DuckDBPyConnection,
    outputs: dict[str, list[dict[str, Any]]],
    quality_total: int,
    quality_passed: int,
) -> dict[str, Any]:
    source_counts = {
        view_name.removeprefix("raw_"): connection.execute(
            f"SELECT count(*) FROM {view_name}"
        ).fetchone()[0]
        for view_name in TABLES.values()
    }
    summary = connection.execute(
        """
        SELECT
            (SELECT count(*) FROM employees) AS employee_records,
            (SELECT count(*) FROM employees
             WHERE termination_date IS NULL OR termination_date > as_of_date)
                AS active_headcount,
            (SELECT count(*) FROM employees
             WHERE termination_date IS NOT NULL) AS total_exits,
            (SELECT count(*) FROM departments) AS department_count,
            (SELECT count(DISTINCT location) FROM departments) AS office_count,
            (SELECT count(*) FROM absences) AS absence_records,
            (SELECT coalesce(sum(absence_days), 0) FROM absence_monthly)
                AS absence_days_total,
            (SELECT as_of_date FROM data_cutoff) AS as_of_date
        FROM data_cutoff
        """
    ).fetchone()
    (
        employee_records,
        active_headcount,
        total_exits,
        department_count,
        office_count,
        absence_records,
        absence_days_total,
        as_of_date,
    ) = summary
    trailing = connection.execute(
        """
        SELECT
            sum(exits) AS exits,
            avg(average_headcount) AS average_headcount,
            sum(exits) / nullif(avg(average_headcount), 0) AS turnover_rate
        FROM monthly_workforce, data_cutoff
        WHERE month_start >= date_trunc(
            'month', as_of_date - INTERVAL '11 months'
        )::DATE
          AND month_start <= date_trunc('month', as_of_date)::DATE
        """
    ).fetchone()
    retention = connection.execute(
        """
        SELECT
            sum(retained_after_12_months) / nullif(sum(eligible_employees), 0)
        FROM retention_cohorts
        """
    ).fetchone()[0]
    monthly = outputs["monthly_workforce"]
    last_month = monthly[-1]
    division_leader = outputs["division_scorecard"][0]
    department_leader = outputs["department_scorecard"][0]
    exit_reason_leader = outputs["attrition_reasons"][0]
    exit_tenure_leader = max(
        outputs["exit_tenure_bands"],
        key=lambda row: row["exits"],
    )
    return {
        "dataset": "Synthetic HR, Workforce and Attrition Database",
        "source_url": SOURCE_URL,
        "source_version": SOURCE_VERSION,
        "source_license": "CC BY 4.0",
        "source_credit": SOURCE_CREDIT,
        "synthetic_data": True,
        "contains_real_employee_data": False,
        "as_of_date": _json_value(as_of_date),
        "date_range": {
            "first_month": outputs["monthly_workforce"][0]["month_start"],
            "last_month": last_month["month_start"],
        },
        "source_row_counts": source_counts,
        "total_source_rows": sum(source_counts.values()),
        "employee_records": int(employee_records),
        "active_headcount": int(active_headcount),
        "total_exits": int(total_exits),
        "observed_cohort_exit_share": (
            round(total_exits / employee_records, 6) if employee_records else None
        ),
        "department_count": int(department_count),
        "office_count": int(office_count),
        "absence_records": int(absence_records),
        "absence_days_total": int(absence_days_total),
        "trailing_12m_exits": int(trailing[0]),
        "trailing_12m_average_headcount": round(float(trailing[1]), 2),
        "trailing_12m_turnover_rate": round(float(trailing[2]), 6),
        "weighted_12m_retention_rate": (
            round(float(retention), 6) if retention is not None else None
        ),
        "latest_month_turnover_rate": last_month["monthly_turnover_rate"],
        "latest_month_end_headcount": last_month["ending_headcount"],
        "highest_turnover_division_trailing_12m": {
            "division": division_leader["division"],
            "turnover_rate": division_leader["trailing_12m_turnover_rate"],
            "exits": division_leader["trailing_12m_exits"],
        },
        "highest_turnover_department_trailing_12m": {
            "department": department_leader["department_name"],
            "division": department_leader["division"],
            "turnover_rate": department_leader["trailing_12m_turnover_rate"],
            "exits": department_leader["trailing_12m_exits"],
        },
        "most_common_exit_reason": {
            "reason": exit_reason_leader["reason"],
            "exits": exit_reason_leader["exits"],
            "share_of_exits": exit_reason_leader["share_of_all_exits"],
        },
        "largest_exit_tenure_band": {
            "band": exit_tenure_leader["tenure_at_exit_band"],
            "exits": exit_tenure_leader["exits"],
            "share_of_exits": exit_tenure_leader["share_of_all_exits"],
        },
        "data_quality_tests_total": quality_total,
        "data_quality_tests_passed": quality_passed,
        "export_row_counts": {
            filename: len(rows)
            for filename, rows in outputs.items()
        },
        "privacy": (
            "Only aggregate tables are exported. Names, email addresses, dates of "
            "birth and employee identifiers are excluded from report files."
        ),
        "interpretation_caveat": (
            "The source is fully synthetic. Its creator states attrition depends "
            "on hire timing/tenure, not performance, pay, level or department. "
            "Segment differences are descriptive generator behavior, not causal "
            "evidence or findings about a real employer."
        ),
    }


def run(
    output_dir: Path | None = None,
    source_zip: Path | None = None,
) -> dict[str, Any]:
    results_dir = output_dir or PROJECT_ROOT / "results"
    results_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="workforce-dashboard-") as workdir:
        temporary = Path(workdir)
        archive_path = source_zip
        if archive_path is None:
            archive_path = temporary / "workforce-source.zip"
            _download_source(archive_path)
        if not archive_path.is_file():
            raise FileNotFoundError(f"Source archive not found: {archive_path}")
        extracted = temporary / "tables"
        extracted.mkdir()
        _extract_source_tables(archive_path, extracted)

        connection = duckdb.connect(":memory:")
        try:
            _register_source_tables(connection, extracted)
            quality_total, quality_passed = _run_quality_checks(connection)
            _execute_models(connection)
            outputs = _write_exports(connection, results_dir)
            metrics = _build_metrics(
                connection, outputs, quality_total, quality_passed
            )
            _build_workbook(
                results_dir / "workforce_executive_dashboard.xlsx",
                outputs,
                metrics,
            )
            metrics["artifacts"] = sorted(
                [*EXPORTS.keys(), "workforce_executive_dashboard.xlsx"]
            )
            (results_dir / "metrics.json").write_text(
                json.dumps(metrics, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            return metrics
        finally:
            connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Build aggregate workforce metrics and an Excel executive dashboard "
            "from the licensed synthetic source."
        )
    )
    parser.add_argument("--source-zip", type=Path)
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "results")
    args = parser.parse_args()
    print(json.dumps(run(args.output_dir, args.source_zip), indent=2))


if __name__ == "__main__":
    main()
