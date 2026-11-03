CREATE OR REPLACE TEMP VIEW employees AS
SELECT
    try_cast(employee_id AS INTEGER) AS employee_id,
    try_cast(department_id AS INTEGER) AS department_id,
    job_title,
    try_cast(job_level AS INTEGER) AS job_level,
    try_cast(hire_date AS DATE) AS hire_date,
    try_cast(termination_date AS DATE) AS termination_date,
    employment_status
FROM raw_employees;

CREATE OR REPLACE TEMP VIEW departments AS
SELECT
    try_cast(department_id AS INTEGER) AS department_id,
    department_name,
    division,
    location
FROM raw_departments;

CREATE OR REPLACE TEMP VIEW attrition_events AS
SELECT
    try_cast(employee_id AS INTEGER) AS employee_id,
    try_cast(left_on AS DATE) AS left_on,
    reason,
    try_cast(voluntary AS BOOLEAN) AS voluntary
FROM raw_attrition_events;

CREATE OR REPLACE TEMP VIEW absences AS
SELECT
    try_cast(absence_id AS INTEGER) AS absence_id,
    try_cast(employee_id AS INTEGER) AS employee_id,
    try_cast(start_date AS DATE) AS start_date,
    try_cast(end_date AS DATE) AS end_date,
    try_cast(days AS INTEGER) AS days
FROM raw_absences;

CREATE OR REPLACE TEMP VIEW performance_reviews AS
SELECT
    try_cast(employee_id AS INTEGER) AS employee_id,
    try_cast(review_date AS DATE) AS review_date,
    try_cast(rating AS INTEGER) AS rating,
    try_cast(goals_met_pct AS DOUBLE) AS goals_met_pct,
    try_cast(promotion_recommended AS BOOLEAN) AS promotion_recommended
FROM raw_performance_reviews;

CREATE OR REPLACE TEMP VIEW data_cutoff AS
SELECT greatest(
    (SELECT max(hire_date) FROM employees),
    (SELECT max(termination_date) FROM employees),
    (SELECT max(try_cast(effective_from AS DATE)) FROM raw_salaries),
    (SELECT max(try_cast(review_date AS DATE)) FROM raw_performance_reviews),
    (SELECT max(start_date) FROM absences),
    (SELECT max(left_on) FROM attrition_events)
)::DATE AS as_of_date;

CREATE OR REPLACE TEMP VIEW month_calendar AS
SELECT
    generate_series::DATE AS month_start,
    least(
        last_day(generate_series)::DATE,
        (SELECT as_of_date FROM data_cutoff)
    ) AS month_end
FROM generate_series(
    date_trunc('month', (SELECT min(hire_date) FROM employees)),
    date_trunc('month', (SELECT as_of_date FROM data_cutoff)),
    INTERVAL '1 month'
);

CREATE OR REPLACE TEMP VIEW dim_month AS
SELECT
    month_start,
    month_end,
    year(month_start)::INTEGER AS calendar_year,
    month(month_start)::INTEGER AS month_number,
    strftime(month_start, '%b %Y') AS month_label
FROM month_calendar;

CREATE OR REPLACE TEMP VIEW monthly_workforce AS
WITH counts AS (
    SELECT
        m.month_start,
        m.month_end,
        count(*) FILTER (
            WHERE e.hire_date < m.month_start
              AND (e.termination_date IS NULL OR e.termination_date >= m.month_start)
        )::INTEGER AS starting_headcount,
        count(*) FILTER (
            WHERE e.hire_date <= m.month_end
              AND (e.termination_date IS NULL OR e.termination_date > m.month_end)
        )::INTEGER AS ending_headcount,
        count(*) FILTER (
            WHERE e.hire_date >= m.month_start AND e.hire_date <= m.month_end
        )::INTEGER AS hires,
        count(*) FILTER (
            WHERE e.termination_date >= m.month_start
              AND e.termination_date <= m.month_end
        )::INTEGER AS exits,
        count(*) FILTER (
            WHERE e.hire_date < m.month_start
              AND (e.termination_date IS NULL OR e.termination_date > m.month_end)
        )::INTEGER AS retained_from_opening_cohort
    FROM month_calendar m
    LEFT JOIN employees e
      ON e.hire_date <= m.month_end
     AND (e.termination_date IS NULL OR e.termination_date >= m.month_start)
    GROUP BY m.month_start, m.month_end
)
SELECT
    month_start,
    month_end,
    starting_headcount,
    ending_headcount,
    (starting_headcount + ending_headcount) / 2.0 AS average_headcount,
    hires,
    exits,
    retained_from_opening_cohort,
    exits / nullif((starting_headcount + ending_headcount) / 2.0, 0) AS monthly_turnover_rate,
    retained_from_opening_cohort / nullif(starting_headcount::DOUBLE, 0) AS monthly_retention_rate
FROM counts;

CREATE OR REPLACE TEMP VIEW department_monthly AS
WITH counts AS (
    SELECT
        m.month_start,
        m.month_end,
        d.department_id,
        d.department_name,
        d.division,
        d.location,
        count(*) FILTER (
            WHERE e.hire_date < m.month_start
              AND (e.termination_date IS NULL OR e.termination_date >= m.month_start)
        )::INTEGER AS starting_headcount,
        count(*) FILTER (
            WHERE e.hire_date <= m.month_end
              AND (e.termination_date IS NULL OR e.termination_date > m.month_end)
        )::INTEGER AS ending_headcount,
        count(*) FILTER (
            WHERE e.hire_date >= m.month_start AND e.hire_date <= m.month_end
        )::INTEGER AS hires,
        count(*) FILTER (
            WHERE e.termination_date >= m.month_start
              AND e.termination_date <= m.month_end
        )::INTEGER AS exits
    FROM month_calendar m
    CROSS JOIN departments d
    LEFT JOIN employees e
      ON e.department_id = d.department_id
     AND e.hire_date <= m.month_end
     AND (e.termination_date IS NULL OR e.termination_date >= m.month_start)
    GROUP BY
        m.month_start, m.month_end, d.department_id,
        d.department_name, d.division, d.location
)
SELECT
    month_start,
    month_end,
    department_id,
    department_name,
    division,
    location,
    starting_headcount,
    ending_headcount,
    (starting_headcount + ending_headcount) / 2.0 AS average_headcount,
    hires,
    exits,
    exits / nullif((starting_headcount + ending_headcount) / 2.0, 0) AS monthly_turnover_rate
FROM counts;

CREATE OR REPLACE TEMP VIEW absence_monthly AS
SELECT
    m.month_start,
    m.month_end,
    sum(date_diff(
        'day',
        greatest(a.start_date, m.month_start),
        least(a.end_date, m.month_end, (SELECT as_of_date FROM data_cutoff))
    ) + 1)::INTEGER AS absence_days,
    count(DISTINCT a.absence_id)::INTEGER AS absence_records
FROM month_calendar m
JOIN absences a
  ON a.start_date <= m.month_end
 AND a.end_date >= m.month_start
GROUP BY m.month_start, m.month_end;

CREATE OR REPLACE TEMP VIEW department_absence_monthly AS
SELECT
    m.month_start,
    m.month_end,
    d.department_id,
    d.department_name,
    d.division,
    d.location,
    coalesce(sum(date_diff(
        'day',
        greatest(a.start_date, m.month_start),
        least(a.end_date, m.month_end, (SELECT as_of_date FROM data_cutoff))
    ) + 1), 0)::INTEGER AS absence_days,
    count(DISTINCT a.absence_id)::INTEGER AS absence_records
FROM month_calendar m
CROSS JOIN departments d
LEFT JOIN employees e ON e.department_id = d.department_id
LEFT JOIN absences a
  ON a.employee_id = e.employee_id
 AND a.start_date <= m.month_end
 AND a.end_date >= m.month_start
GROUP BY
    m.month_start, m.month_end, d.department_id,
    d.department_name, d.division, d.location;

CREATE OR REPLACE TEMP VIEW department_scorecard AS
WITH cutoff AS (
    SELECT
        as_of_date,
        date_trunc('month', as_of_date - INTERVAL '11 months')::DATE AS period_start
    FROM data_cutoff
),
periods AS (
    SELECT
        d.department_id,
        d.department_name,
        d.division,
        d.location,
        count(e.employee_id) FILTER (
            WHERE e.hire_date <= c.as_of_date
              AND (e.termination_date IS NULL OR e.termination_date > c.as_of_date)
        )::INTEGER AS active_headcount,
        count(e.employee_id)::INTEGER AS employees_observed,
        count(e.employee_id) FILTER (WHERE e.termination_date IS NOT NULL)::INTEGER AS all_time_exits,
        count(e.employee_id) FILTER (
            WHERE e.termination_date >= c.period_start
              AND e.termination_date <= c.as_of_date
        )::INTEGER AS trailing_12m_exits
    FROM departments d
    CROSS JOIN cutoff c
    LEFT JOIN employees e ON e.department_id = d.department_id
    GROUP BY d.department_id, d.department_name, d.division, d.location
),
averages AS (
    SELECT
        department_id,
        avg(average_headcount) AS trailing_12m_average_headcount
    FROM department_monthly, cutoff
    WHERE month_start >= period_start
      AND month_start <= date_trunc('month', as_of_date)::DATE
    GROUP BY department_id
)
SELECT
    p.department_id,
    p.department_name,
    p.division,
    p.location,
    p.active_headcount,
    p.employees_observed,
    p.all_time_exits,
    p.trailing_12m_exits,
    coalesce(a.trailing_12m_average_headcount, 0) AS trailing_12m_average_headcount,
    p.trailing_12m_exits / nullif(a.trailing_12m_average_headcount, 0) AS trailing_12m_turnover_rate,
    p.all_time_exits / nullif(p.employees_observed::DOUBLE, 0) AS observed_cohort_exit_share
FROM periods p
LEFT JOIN averages a USING (department_id);

CREATE OR REPLACE TEMP VIEW division_scorecard AS
SELECT
    division,
    sum(active_headcount)::INTEGER AS active_headcount,
    sum(trailing_12m_exits)::INTEGER AS trailing_12m_exits,
    sum(trailing_12m_average_headcount) AS trailing_12m_average_headcount,
    sum(trailing_12m_exits) / nullif(sum(trailing_12m_average_headcount), 0) AS trailing_12m_turnover_rate,
    count(*)::INTEGER AS department_count
FROM department_scorecard
GROUP BY division;

CREATE OR REPLACE TEMP VIEW performance_monthly AS
SELECT
    m.month_start,
    m.month_end,
    count(r.employee_id)::INTEGER AS completed_reviews,
    avg(r.rating) AS average_rating,
    avg(r.goals_met_pct) AS average_goals_met_pct,
    avg(r.promotion_recommended::INTEGER) AS promotion_recommendation_rate
FROM month_calendar m
LEFT JOIN performance_reviews r
  ON r.review_date >= m.month_start
 AND r.review_date <= m.month_end
GROUP BY m.month_start, m.month_end;

CREATE OR REPLACE TEMP VIEW department_performance AS
WITH cutoff AS (
    SELECT
        as_of_date,
        date_trunc('month', as_of_date - INTERVAL '11 months')::DATE AS period_start
    FROM data_cutoff
)
SELECT
    d.department_id,
    d.department_name,
    d.division,
    d.location,
    count(r.employee_id)::INTEGER AS trailing_12m_reviews,
    avg(r.rating) AS trailing_12m_average_rating,
    avg(r.goals_met_pct) AS trailing_12m_average_goals_met_pct,
    avg(r.promotion_recommended::INTEGER) AS trailing_12m_promotion_recommendation_rate
FROM departments d
CROSS JOIN cutoff c
LEFT JOIN employees e ON e.department_id = d.department_id
LEFT JOIN performance_reviews r
  ON r.employee_id = e.employee_id
 AND r.review_date >= c.period_start
 AND r.review_date <= c.as_of_date
GROUP BY d.department_id, d.department_name, d.division, d.location;

CREATE OR REPLACE TEMP VIEW attrition_reasons AS
SELECT
    reason,
    voluntary,
    count(*)::INTEGER AS exits,
    count(*) / sum(count(*)) OVER ()::DOUBLE AS share_of_all_exits
FROM attrition_events
GROUP BY reason, voluntary;

CREATE OR REPLACE TEMP VIEW exit_tenure_bands AS
WITH exits AS (
    SELECT
        e.employee_id,
        date_diff('day', e.hire_date, e.termination_date) / 365.25 AS tenure_years
    FROM employees e
    WHERE e.termination_date IS NOT NULL
)
SELECT
    CASE
        WHEN tenure_years < 1 THEN 'Under 1 year'
        WHEN tenure_years < 2 THEN '1 to under 2 years'
        WHEN tenure_years < 5 THEN '2 to under 5 years'
        ELSE '5 years or more'
    END AS tenure_at_exit_band,
    count(*)::INTEGER AS exits,
    count(*) / sum(count(*)) OVER ()::DOUBLE AS share_of_all_exits
FROM exits
GROUP BY tenure_at_exit_band;

CREATE OR REPLACE TEMP VIEW retention_cohorts AS
WITH cutoff AS (
    SELECT as_of_date FROM data_cutoff
),
eligible AS (
    SELECT
        date_trunc('month', e.hire_date)::DATE AS cohort_month,
        e.employee_id,
        e.hire_date,
        e.termination_date,
        c.as_of_date
    FROM employees e
    CROSS JOIN cutoff c
    WHERE e.hire_date + INTERVAL '12 months' <= c.as_of_date
)
SELECT
    cohort_month,
    count(*)::INTEGER AS eligible_employees,
    count(*) FILTER (
        WHERE termination_date IS NULL OR termination_date > hire_date + INTERVAL '12 months'
    )::INTEGER AS retained_after_12_months,
    count(*) FILTER (
        WHERE termination_date IS NULL OR termination_date > hire_date + INTERVAL '12 months'
    ) / nullif(count(*)::DOUBLE, 0) AS retention_12m_rate
FROM eligible
GROUP BY cohort_month;
