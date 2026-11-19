# BlogPulse: Blog Platform with Python and MongoDB

**DBMS for Analytics (25MSDA1S04) · M.Sc. Data Science · Problem Statement 19 (Web application)**

BlogPulse stores **accounts, roles and subscriptions in PostgreSQL** (strict structure, money, audit trail) and **posts with embedded comments and tags in MongoDB** (flexible, read as a whole). Python ties them together: the DB-API (`psycopg2`) for SQL and PyMongo for posts.

## Repository layout

| File | Purpose |
|---|---|
| `schema.sql` | 7 tables in 3NF, PK/FK/CHECK/UNIQUE constraints, 2 triggers, 2 views |
| `data.sql` | Sample data (generated): 1,901 rows loaded by the script + 200+ audit rows made by the trigger |
| `queries.sql` | 11 analytical queries, trigger demo (rolled back) and constraint demo |
| `notebook.ipynb` | DB-API + PyMongo analysis, charts, SQL vs NoSQL comparison |
| `blogpulse_app.py` | Command-line app: user admin (SQL), posts/comments (MongoDB), reports, backup |
| `mongo/blogpulse.js` | mongosh script: indexes, CRUD, 5 aggregation pipelines |
| `mongo/posts.json` | 300 posts with 424 embedded comments |
| `scripts/generate_data.py` | Regenerates `data.sql` and `mongo/posts.json` (seeded, repeatable) |
| `docs/er_diagram.png` / `.mmd` | ER diagram |
| `charts/` | Chart images produced by the notebook |

## Data source
Synthetic data generated with Python (`scripts/generate_data.py`, seed 19). No real people: names are random combinations, e-mails use `example.com`, password hashes are SHA-256 of dummy text. Dates run from Jan 2024 to Dec 2025.

## Relational design (PostgreSQL)
`roles`, `countries`, `plans` (lookups) → `users` → `subscriptions`, `user_logins`, `account_audit_log`.

* **3NF:** role, country and plan details are stored once and referenced by key (e.g. `users.role_id`, not a role name repeated per user). Every non-key column depends on the key only.
* **Constraints:** unique e-mail (case-insensitive), unique username, role names restricted by `CHECK`, `end_date > start_date`, and a partial unique index allowing **only one active subscription per user**.
* **Trigger `trg_users_audit`:** logs account creation and every change of role, e-mail or active flag into `account_audit_log`.
* **Trigger `trg_close_previous_subscription`:** a new active subscription automatically closes the previous one.
* **Views:** `v_user_overview` (user + role + country + plan + login summary) and `v_monthly_signups` (monthly and cumulative sign-ups).

## MongoDB design
Collection `posts`: one document per post with `tags` (array) and `comments` (embedded array). `author_id` and `comments.user_id` refer to `users.user_id` in PostgreSQL. Optional fields (`cover_image`, `reading_time_min`, `series`) exist on some posts only, which is why a document model fits.
Indexes: unique `slug`, multikey `tags`, compound `(author_id, created_at)`, `created_at`, text index on `title`+`body`.

## How to run

### 1. PostgreSQL
```bash
createdb blogpulse
psql -d blogpulse -f schema.sql
psql -d blogpulse -f data.sql
psql -d blogpulse -f queries.sql
```

### 2. MongoDB
```bash
mongoimport --db blogpulse --collection posts --drop --jsonArray --file mongo/posts.json
mongosh --file mongo/blogpulse.js
```

### 3. Python
```bash
pip install -r requirements.txt
export PGUSER=postgres PGPASSWORD=yourpassword      # Windows: set PGUSER=...
jupyter notebook notebook.ipynb                      # run all cells

python blogpulse_app.py seed-mongo                   # alternative to mongoimport
python blogpulse_app.py users list --role author
python blogpulse_app.py users set-role <username> editor
python blogpulse_app.py users audit
python blogpulse_app.py posts search --tag python
python blogpulse_app.py report top-posts
python blogpulse_app.py backup
```
Environment variables: `PGHOST, PGPORT, PGUSER, PGPASSWORD, PGDATABASE, MONGO_URI, MONGO_DB`.

## Live demo checklist
1. `\dt` and `\d users` in psql (schema, constraints).
2. Run the trigger demo block at the end of `queries.sql`.
3. Run two analytical queries (e.g. Q3 monthly active users, Q6 revenue by plan).
4. Run the notebook and show the charts.
5. In mongosh: CRUD, `explain()` on a tag query, then pipelines A1 and A2.

## SQL vs NoSQL
| | PostgreSQL | MongoDB |
|---|---|---|
| Schema | Fixed, enforced | Flexible per document |
| Relations | JOINs on foreign keys | Embedded comments and tags |
| Integrity | ACID across tables, triggers | Per-document atomicity |
| Best for | Accounts, subscriptions, audit | Posts and comments |
| Our choice | Users, roles, plans, logins | Posts with comments and tags |
