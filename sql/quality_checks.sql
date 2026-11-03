SELECT 'departments_unique_id' AS test_name,
       count(*) AS failing_rows
FROM (
    SELECT department_id
    FROM raw_departments
    GROUP BY department_id
    HAVING department_id IS NULL OR count(*) > 1
)
UNION ALL
SELECT 'employees_unique_id', count(*)
FROM (
    SELECT employee_id
    FROM raw_employees
    GROUP BY employee_id
    HAVING employee_id IS NULL OR count(*) > 1
)
UNION ALL
SELECT 'employees_required_dates_and_department', count(*)
FROM raw_employees
WHERE department_id IS NULL
   OR try_cast(hire_date AS DATE) IS NULL
UNION ALL
SELECT 'employees_department_relationship', count(*)
FROM raw_employees e
LEFT JOIN raw_departments d ON e.department_id = d.department_id
WHERE d.department_id IS NULL
UNION ALL
SELECT 'termination_status_consistency', count(*)
FROM raw_employees
WHERE (employment_status = 'terminated') <> (termination_date IS NOT NULL)
UNION ALL
SELECT 'termination_after_hire', count(*)
FROM raw_employees
WHERE termination_date IS NOT NULL
  AND try_cast(termination_date AS DATE) < try_cast(hire_date AS DATE)
UNION ALL
SELECT 'salary_employee_relationship', count(*)
FROM raw_salaries s
LEFT JOIN raw_employees e ON s.employee_id = e.employee_id
WHERE e.employee_id IS NULL
UNION ALL
SELECT 'salary_positive', count(*)
FROM raw_salaries
WHERE try_cast(base_salary AS DOUBLE) IS NULL
   OR try_cast(base_salary AS DOUBLE) <= 0
UNION ALL
SELECT 'review_employee_relationship', count(*)
FROM raw_performance_reviews r
LEFT JOIN raw_employees e ON r.employee_id = e.employee_id
WHERE e.employee_id IS NULL
UNION ALL
SELECT 'absence_employee_relationship', count(*)
FROM raw_absences a
LEFT JOIN raw_employees e ON a.employee_id = e.employee_id
WHERE e.employee_id IS NULL
UNION ALL
SELECT 'absence_dates_and_duration', count(*)
FROM raw_absences
WHERE try_cast(start_date AS DATE) IS NULL
   OR try_cast(end_date AS DATE) < try_cast(start_date AS DATE)
   OR try_cast(days AS INTEGER) <> date_diff(
       'day', try_cast(start_date AS DATE), try_cast(end_date AS DATE)
   ) + 1
UNION ALL
SELECT 'attrition_employee_relationship', count(*)
FROM raw_attrition_events a
LEFT JOIN raw_employees e ON a.employee_id = e.employee_id
WHERE e.employee_id IS NULL
UNION ALL
SELECT 'attrition_date_matches_termination', count(*)
FROM raw_attrition_events a
JOIN raw_employees e ON a.employee_id = e.employee_id
WHERE try_cast(a.left_on AS DATE) <> try_cast(e.termination_date AS DATE)
UNION ALL
SELECT 'one_attrition_event_per_employee', count(*)
FROM (
    SELECT employee_id
    FROM raw_attrition_events
    GROUP BY employee_id
    HAVING count(*) > 1
)
