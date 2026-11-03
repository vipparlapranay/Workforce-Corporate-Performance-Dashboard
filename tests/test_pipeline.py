from __future__ import annotations

import csv
import json
import zipfile
from io import StringIO
from pathlib import Path
from xml.etree import ElementTree

import pytest

from workforce_dashboard.pipeline import run


FIXTURE_TABLES = {
    "departments.csv": (
        ["department_id", "department_name", "division", "location"],
        [[1, "=1+1", "Operations", "Sydney"]],
    ),
    "employees.csv": (
        [
            "employee_id",
            "first_name",
            "last_name",
            "email",
            "department_id",
            "job_title",
            "job_level",
            "hire_date",
            "termination_date",
            "employment_status",
            "gender",
            "date_of_birth",
            "work_mode",
        ],
        [
            [
                1,
                "Example",
                "One",
                "one@example.invalid",
                1,
                "Analyst",
                1,
                "2026-01-01",
                "2026-01-31",
                "terminated",
                "not_reported",
                "1990-01-01",
                "hybrid",
            ],
            [
                2,
                "Example",
                "Two",
                "two@example.invalid",
                1,
                "Analyst",
                1,
                "2026-01-10",
                "",
                "active",
                "not_reported",
                "1990-01-01",
                "remote",
            ],
            [
                3,
                "Example",
                "Three",
                "three@example.invalid",
                1,
                "Lead",
                2,
                "2026-02-01",
                "",
                "active",
                "not_reported",
                "1990-01-01",
                "office",
            ],
        ],
    ),
    "salaries.csv": (
        ["salary_id", "employee_id", "effective_from", "base_salary", "bonus_pct", "currency"],
        [
            [1, 1, "2026-01-01", 50000, 5, "AUD"],
            [2, 2, "2026-01-10", 51000, 5, "AUD"],
            [3, 3, "2026-02-28", 60000, 8, "AUD"],
        ],
    ),
    "performance_reviews.csv": (
        [
            "review_id",
            "employee_id",
            "review_date",
            "rating",
            "goals_met_pct",
            "promotion_recommended",
        ],
        [
            [1, 1, "2026-01-15", 3, 70, "false"],
            [2, 2, "2026-02-28", 4, 90, "true"],
            [3, 3, "2026-02-28", 4, 88, "true"],
        ],
    ),
    "absences.csv": (
        ["absence_id", "employee_id", "start_date", "end_date", "absence_type", "days"],
        [
            [1, 2, "2026-01-30", "2026-02-02", "vacation", 4],
            [2, 3, "2026-02-10", "2026-02-10", "sick", 1],
            [3, 3, "2026-02-28", "2026-03-02", "sick", 3],
        ],
    ),
    "attrition_events.csv": (
        [
            "attrition_id",
            "employee_id",
            "left_on",
            "reason",
            "voluntary",
            "exit_interview_score",
        ],
        [[1, 1, "2026-01-31", "better_offer", "true", 8]],
    ),
}


def _write_source_archive(path: Path) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for filename, (headers, rows) in FIXTURE_TABLES.items():
            stream = StringIO()
            writer = csv.writer(stream)
            writer.writerow(headers)
            writer.writerows(rows)
            archive.writestr(filename, stream.getvalue())


def test_pipeline_exports_accurate_aggregates_without_employee_identifiers(
    tmp_path: Path,
) -> None:
    archive_path = tmp_path / "source.zip"
    output_dir = tmp_path / "results"
    _write_source_archive(archive_path)

    metrics = run(output_dir=output_dir, source_zip=archive_path)

    assert metrics["employee_records"] == 3
    assert metrics["active_headcount"] == 2
    assert metrics["total_exits"] == 1
    assert metrics["absence_days_total"] == 6
    assert metrics["data_quality_tests_passed"] == metrics["data_quality_tests_total"]
    assert metrics["weighted_12m_retention_rate"] is None

    with (output_dir / "monthly_workforce.csv").open(
        encoding="utf-8-sig", newline=""
    ) as stream:
        monthly = list(csv.DictReader(stream))
    assert len(monthly) == 2
    assert monthly[0]["ending_headcount"] == "1"
    assert monthly[0]["exits"] == "1"
    assert monthly[1]["ending_headcount"] == "2"
    assert monthly[1]["retained_from_opening_cohort"] == "1"

    with (output_dir / "absence_monthly.csv").open(
        encoding="utf-8-sig", newline=""
    ) as stream:
        absences = list(csv.DictReader(stream))
    assert [row["absence_days"] for row in absences] == ["2", "4"]

    for path in output_dir.glob("*.csv"):
        with path.open(encoding="utf-8-sig", newline="") as stream:
            headers = next(csv.reader(stream))
        assert not {
            "employee_id",
            "first_name",
            "last_name",
            "email",
            "date_of_birth",
        }.intersection(headers)

    workbook = output_dir / "workforce_executive_dashboard.xlsx"
    assert workbook.is_file()
    with zipfile.ZipFile(workbook) as archive:
        assert archive.testzip() is None
        xml_files = [
            name
            for name in archive.namelist()
            if name.endswith(".xml")
        ]
        for name in xml_files:
            ElementTree.fromstring(archive.read(name))
        assert b"Example" not in archive.read("xl/sharedStrings.xml")
        for name in archive.namelist():
            if name.startswith("xl/worksheets/sheet") and name.endswith(".xml"):
                assert b"<f>" not in archive.read(name)
    assert json.loads((output_dir / "metrics.json").read_text())["employee_records"] == 3


def test_pipeline_rejects_an_unsafe_zip_path(tmp_path: Path) -> None:
    archive_path = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("../employees.csv", "employee_id\n1\n")

    with pytest.raises(ValueError, match="Unsafe path"):
        run(output_dir=tmp_path / "results", source_zip=archive_path)
