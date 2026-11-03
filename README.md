# NORTHSTAR | Workforce & Corporate Performance Dashboard

A reproducible SQL-to-Excel-to-Power BI people-analytics portfolio project.
It models a fully synthetic, openly licensed workforce dataset into monthly
headcount, turnover, retention, tenure, absence-volume, and review measures.
The source contains no real employees.

> **Interpretation and privacy:** This is a generated training dataset, not a
> real employer's workforce. The data creator says attrition is generated from
> hire timing/tenure, not from department, pay, job level, or review results.
> Segment differences are descriptive, not causal findings. The pipeline
> publishes grouped aggregates only; raw data, names, email addresses, employee
> IDs, and birth dates are not exported or committed.

## Dataset and attribution

The project uses version 2 of
[Synthetic HR, Workforce and Attrition Database](https://www.kaggle.com/datasets/generaterealdata/synthetic-hr-workforce-attrition)
by GenerateRealData, licensed [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
Required attribution: **Synthetic HR, Workforce and Attrition, GenerateRealData**
with a link to [generaterealdata.com](https://www.generaterealdata.com).
The Kaggle page describes six tables covering 20,000 fictional current/former
employees, 40 departments, eight office locations, salaries, reviews, absences,
and attrition events. The upstream dataset is pinned to version 2 and is
downloaded to a temporary directory when the pipeline runs; raw rows are not
stored in this repository.

## Reproduce the results

Requires Python 3.10 or later and internet access to download the public dataset.
Alternatively, pass a previously downloaded version-2 Kaggle ZIP.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m workforce_dashboard.pipeline
python -m pytest -q
```

The download is automatically cleaned from the temporary directory after the
run. To use your own downloaded archive:

```powershell
python -m workforce_dashboard.pipeline --source-zip "C:\data\hr-workforce.zip"
```

The pipeline runs DuckDB SQL, validates source relationships and date logic,
computes aggregate tables, writes `results\metrics.json`, and creates the Excel
workbook `results\workforce_executive_dashboard.xlsx`. All `.csv` files in
`results\` contain grouped summaries only. The `.gitignore` excludes local raw
source files.

### Results snapshot

Metrics are calculated from the pinned public source, not invented resume
placeholders. See [`results/metrics.json`](results/metrics.json) for the full
run and [`results/`](results/) for report-ready aggregate tables.

| Metric | Measured result |
|---|---:|
| Source tables / rows | 6 / 155,186 |
| Employee records | 20,000 synthetic employees |
| Departments / office locations | 40 / 8 |
| Active headcount | 11,614 as of 2026-09-30 |
| Trailing-12-month turnover | 11.76% (1,324 exits / 11,255 average headcount) |
| 12-month cohort retention | 90.06%, weighted across eligible hire cohorts |
| Absence records / days through cutoff | 21,760 / 163,698 |
| SQL quality checks | 14/14 passed |
| Monthly dashboard period | 2015-01-01 through 2026-09-30 (141 months) |

**Descriptive segment result:** Product Design had the highest department
trailing-12-month turnover at **17.93% (29 exits)** versus **11.76%** company
wide. Marketing was the highest-turnover division at **12.84% (187 exits)**.
These are synthetic dataset comparisons, not evidence that department caused
attrition. The source generator explicitly does not use department, level, pay,
or performance to generate attrition. Do not compare the illustrative 1.2%
monthly target with an external benchmark.

## SQL model and metric definitions

[`sql/quality_checks.sql`](sql/quality_checks.sql) checks primary keys,
foreign-key relationships, termination/attrition consistency, and absence
durations. [`sql/transform.sql`](sql/transform.sql) produces:

- **Month-end headcount:** hired by snapshot date and not terminated by
  month-end.
- **Monthly turnover:** monthly exits divided by the average of starting and
  ending headcount.
- **Monthly retention:** opening-month employees still employed at month-end,
  divided by opening headcount; new hires are excluded.
- **Trailing-12-month turnover:** exits in the 12 complete months through the
  data cutoff divided by the average monthly average headcount.
- **12-month cohort retention:** employees employed beyond their first
  anniversary divided by cohort members observed for at least 12 months.
- **Tenure:** elapsed calendar days from hire to termination (or data cutoff)
  divided by 365.25.
- **Absence days:** absence periods are split across calendar months by
  overlapping days and are capped at the latest observed source date. Days per
  active employee is a volume proxy, **not** an official absenteeism percentage
  because scheduled working days are absent.

## Excel and Power BI

- The Excel workbook contains an executive summary with KPI cards and monthly
  trend charts, plus aggregate department, division, absence, review, exit, and
  retention sheets. Metric definitions and interpretation notes are included.
- [`powerbi/measures.dax`](powerbi/measures.dax) contains reusable DAX measures.
- [`powerbi/README.md`](powerbi/README.md) defines CSV imports, relationships,
  visuals, drill-downs, and report guardrails.
- [`powerbi/theme.json`](powerbi/theme.json) provides a consistent visual theme.

The repository includes Power BI-ready aggregate tables and DAX/report
specifications; it does not claim a published Power BI Service report.

## Repository map

- `src/workforce_dashboard/` — version-pinned download, safe ZIP handling, SQL
  execution, quality gates, aggregate exports, and Excel workbook generation.
- `sql/` — validation queries and workforce/department/time-series models.
- `powerbi/` — measures, theme, model relationships, and report blueprint.
- `tests/` — synthetic fixture tests for exact headcount, turnover, absence
  allocation, privacy-safe exports, and unsafe archive rejection.
- `results/` — aggregate-only benchmark outputs and Excel dashboard.

Project code is MIT-licensed. Source attribution and the CC BY 4.0 terms apply
to the source and derived result files; see the dataset links above.
