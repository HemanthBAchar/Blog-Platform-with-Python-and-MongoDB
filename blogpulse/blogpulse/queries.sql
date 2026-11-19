-- =====================================================================
-- BlogPulse  |  queries.sql  |  analytical SQL on the user/role/plan data
-- Run after schema.sql and data.sql:  psql -d blogpulse -f queries.sql
-- "Today" in this dataset = the latest login (so results are repeatable).
-- =====================================================================

-- Q1. Role distribution (count and share of all users)
SELECT r.role_name,
       COUNT(*)                                             AS users,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1)   AS pct_of_users
FROM users u
JOIN roles r ON r.role_id = u.role_id
GROUP BY r.role_name
ORDER BY users DESC;

-- Q2. Sign-ups by month with running total (uses view v_monthly_signups)
SELECT month, signups, cumulative_users
FROM v_monthly_signups
ORDER BY month;

-- Q3. Monthly active users (MAU): distinct users who logged in each month
SELECT DATE_TRUNC('month', login_at)::date AS month,
       COUNT(DISTINCT user_id)             AS active_users,
       COUNT(*)                            AS logins
FROM user_logins
GROUP BY 1
ORDER BY 1;

-- Q4. Active users in the last 30 days of the dataset, by role
WITH ref AS (SELECT MAX(login_at) AS today FROM user_logins)
SELECT r.role_name,
       COUNT(DISTINCT l.user_id) AS active_last_30_days
FROM user_logins l
JOIN users u ON u.user_id = l.user_id
JOIN roles r ON r.role_id = u.role_id
CROSS JOIN ref
WHERE l.login_at > ref.today - INTERVAL '30 days'
GROUP BY r.role_name
ORDER BY active_last_30_days DESC;

-- Q5. Dormant accounts: active flag is TRUE but no login for 90+ days
--     (correlated subquery with NOT EXISTS)
SELECT u.user_id, u.username, r.role_name, u.signup_date
FROM users u
JOIN roles r ON r.role_id = u.role_id
WHERE u.is_active
  AND NOT EXISTS (
        SELECT 1 FROM user_logins l
        WHERE l.user_id = u.user_id
          AND l.login_at > (SELECT MAX(login_at) FROM user_logins) - INTERVAL '90 days')
ORDER BY u.signup_date
LIMIT 15;

-- Q6. Monthly recurring revenue (MRR) and subscribers per plan
SELECT p.plan_name,
       COUNT(*)                          AS active_subscribers,
       SUM(p.monthly_price)              AS mrr
FROM subscriptions s
JOIN plans p ON p.plan_id = s.plan_id
WHERE s.status = 'active'
GROUP BY p.plan_name, p.monthly_price
ORDER BY mrr DESC;

-- Q7. Countries with at least 10 users: user count and paid-plan share
SELECT c.country_name,
       COUNT(*)                                                    AS users,
       ROUND(100.0 * COUNT(*) FILTER (WHERE p.monthly_price > 0)
                   / COUNT(*), 1)                                  AS pct_on_paid_plan
FROM users u
JOIN countries c          ON c.country_code = u.country_code
LEFT JOIN subscriptions s ON s.user_id = u.user_id AND s.status = 'active'
LEFT JOIN plans p         ON p.plan_id = s.plan_id
GROUP BY c.country_name
HAVING COUNT(*) >= 10
ORDER BY users DESC;

-- Q8. Logins by hour of day and device (when do people read?)
SELECT EXTRACT(HOUR FROM login_at)::int AS hour_of_day,
       COUNT(*)                         AS logins,
       COUNT(*) FILTER (WHERE device = 'web')     AS web,
       COUNT(*) FILTER (WHERE device = 'android') AS android,
       COUNT(*) FILTER (WHERE device = 'ios')     AS ios
FROM user_logins
GROUP BY 1
ORDER BY 1;

-- Q9. Upgrade conversion: users who started on Free and later moved to a paid plan
WITH first_sub AS (
    SELECT DISTINCT ON (user_id) user_id, plan_id
    FROM subscriptions
    ORDER BY user_id, start_date
)
SELECT COUNT(*)                                                     AS started_free,
       COUNT(*) FILTER (WHERE EXISTS (
            SELECT 1 FROM subscriptions s
            JOIN plans p ON p.plan_id = s.plan_id
            WHERE s.user_id = f.user_id AND p.monthly_price > 0))   AS later_paid,
       ROUND(100.0 * COUNT(*) FILTER (WHERE EXISTS (
            SELECT 1 FROM subscriptions s
            JOIN plans p ON p.plan_id = s.plan_id
            WHERE s.user_id = f.user_id AND p.monthly_price > 0))
            / COUNT(*), 1)                                          AS conversion_pct
FROM first_sub f
WHERE f.plan_id = 1;

-- Q10. Most engaged users: login count above the average (subquery in HAVING)
SELECT o.username, o.role_name, o.current_plan, o.login_count, o.last_login
FROM v_user_overview o
WHERE o.login_count > (SELECT AVG(login_count) FROM v_user_overview)
ORDER BY o.login_count DESC
LIMIT 10;

-- Q11. Audit trail written by trigger trg_users_audit (excluding creations)
SELECT a.changed_at, u.username, a.action, a.old_value, a.new_value
FROM account_audit_log a
LEFT JOIN users u ON u.user_id = a.user_id
WHERE a.action <> 'ACCOUNT_CREATED'
ORDER BY a.log_id;

-- =====================================================================
-- TRIGGER DEMO  (wrapped in a transaction and rolled back, so the data
-- is left untouched)
-- =====================================================================
BEGIN;

-- 1) new account  -> trigger logs ACCOUNT_CREATED
INSERT INTO users (username, full_name, email, password_hash, role_id, country_code)
VALUES ('demo.user', 'Demo User', 'demo.user@example.com', REPEAT('0', 64), 4, 'IN');

-- 2) promote to author and deactivate -> trigger logs ROLE_CHANGED, ACCOUNT_DEACTIVATED
UPDATE users SET role_id = 3 WHERE username = 'demo.user';
UPDATE users SET is_active = FALSE WHERE username = 'demo.user';

-- 3) show what the trigger wrote
SELECT action, old_value, new_value
FROM account_audit_log
WHERE user_id = (SELECT user_id FROM users WHERE username = 'demo.user')
ORDER BY log_id;

-- 4) subscription trigger: a new active plan auto-closes the previous one
INSERT INTO subscriptions (user_id, plan_id, start_date, status)
SELECT user_id, 1, CURRENT_DATE - 30, 'active' FROM users WHERE username = 'demo.user';
INSERT INTO subscriptions (user_id, plan_id, start_date, status)
SELECT user_id, 2, CURRENT_DATE, 'active' FROM users WHERE username = 'demo.user';

SELECT plan_id, start_date, end_date, status
FROM subscriptions
WHERE user_id = (SELECT user_id FROM users WHERE username = 'demo.user')
ORDER BY start_date;

ROLLBACK;

-- =====================================================================
-- CONSTRAINT DEMO  (each statement is expected to FAIL - run one by one)
-- =====================================================================
-- duplicate e-mail (case-insensitive):
--   INSERT INTO users (username, full_name, email, password_hash, role_id, country_code)
--   VALUES ('dup', 'Dup', 'LIAM.REDDY@example.com', REPEAT('0',64), 4, 'IN');
-- unknown role:
--   INSERT INTO users (username, full_name, email, password_hash, role_id, country_code)
--   VALUES ('bad', 'Bad', 'bad@example.com', REPEAT('0',64), 99, 'IN');
-- second active subscription is closed by trigger, but an invalid status fails:
--   INSERT INTO subscriptions (user_id, plan_id, start_date, status) VALUES (1, 1, CURRENT_DATE, 'paused');
