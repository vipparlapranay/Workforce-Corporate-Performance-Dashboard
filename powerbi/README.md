# Power BI report build

The pipeline writes aggregate-only CSVs to `results\`. In Power BI Desktop, use
**Get data → Text/CSV** to import these files. Do not load the source archive or
the raw employee table into the report.

Rename the imported queries to match the DAX: `dim_month` → `DimMonth`,
`monthly_workforce` → `MonthlyWorkforce`, `department_monthly` →
`DepartmentMonthly`, `departments` → `Departments`, `absence_monthly` →
`AbsenceMonthly`, `department_absence_monthly` → `DepartmentAbsenceMonthly`,
`performance_monthly` → `PerformanceMonthly`, `department_performance` →
`DepartmentPerformance`, `department_scorecard` → `DepartmentScorecard`,
`division_scorecard` → `DivisionScorecard`, `attrition_reasons` →
`AttritionReasons`, `exit_tenure_bands` → `ExitTenureBands`, and
`retention_cohorts` → `RetentionCohorts`.

## Model relationships

Create one-to-many, single-direction relationships from `DimMonth[month_start]`
to `month_start` in:

- `MonthlyWorkforce`
- `DepartmentMonthly`
- `AbsenceMonthly`
- `DepartmentAbsenceMonthly`
- `PerformanceMonthly`

Create one-to-many relationships from `Departments[department_id]` to
`department_id` in:

- `DepartmentMonthly`
- `DepartmentAbsenceMonthly`
- `DepartmentPerformance`
- `DepartmentScorecard`

`AttritionReasons`, `ExitTenureBands`, and `RetentionCohorts` are separate
aggregate views. Retention cohorts use `cohort_month`; relate that field to a
second role-playing copy of `DimMonth` only if building a cohort timeline.

Apply the `Northstar Workforce` theme from `theme.json`. Sort
`DimMonth[month_label]` by `DimMonth[month_start]`.

## Measures

Copy the definitions in `measures.dax` into Power BI. Format rate measures as
percentages. The 1.2% monthly turnover threshold is an **illustrative user-set
target**, not a source-provided or industry benchmark.
Use `Turnover Target (Illustrative)` and `Turnover Target Gap` only on
month-grain visuals; they should not be compared to a selected multi-month
period's cumulative turnover measure.

## Executive report pages

### 1. Workforce overview

- KPI cards: month-end headcount, hires, exits, trailing-12-month turnover,
  opening-cohort retention, absence days per active employee.
- Line chart: month-end headcount and turnover; add the illustrative target
  as a constant line and keep the rate on a separate scale.
- Small multiples: headcount and exits by division.
- Slicers: month, division, department, location.

### 2. Attrition and retention

- Department/division turnover matrix with exit count, average headcount, and
  trailing-12-month turnover.
- Exit reason bar chart and tenure-at-exit distribution.
- Hire-cohort 12-month retention line chart.
- Add a visible note that these are synthetic, generated patterns, not causal
  findings. Do not frame a demographic or performance group as an attrition
  cause.

### 3. Attendance and performance

- Monthly absence-day trend and department/location drill-down.
- Review count, average rating, and goals-met trend.
- Absence days are a volume proxy: scheduled workdays are not present, so do not
  label this percentage an official absenteeism rate.

## Definitions and controls

- Month-end headcount counts employees hired by the snapshot date who have no
  termination date before or on that date.
- Monthly turnover is exits divided by the average of beginning- and
  end-of-month headcount.
- Monthly retention tracks the opening-month employee cohort only.
- Absence periods are allocated across calendar months by date overlap and
  capped at the latest observed source date.
- Group differences are descriptive. The dataset creator states attrition was
  generated from hire timing/tenure, not from department, pay, job level, or
  review results.
- Reports contain only grouped results; no employee name, email, birth date, or
  employee identifier is exported.
