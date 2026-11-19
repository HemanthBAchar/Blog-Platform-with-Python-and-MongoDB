#!/usr/bin/env python3
"""
generate_data.py - builds the synthetic BlogPulse dataset (seeded, repeatable).

Outputs
  data.sql          INSERT statements for the PostgreSQL tables
  mongo/posts.json  blog posts with embedded comments and tags (MongoDB)

Both outputs share the same user_ids, so SQL users and Mongo posts can be
joined in Python.  No real people: names are random combinations and all
e-mails use the reserved example.com domain.

Run from the project root:   python scripts/generate_data.py
"""
import hashlib
import json
import math
import random
from datetime import date, datetime, timedelta
from pathlib import Path

SEED = 19
random.seed(SEED)
ROOT = Path(__file__).resolve().parent.parent
START, END = date(2024, 1, 1), date(2025, 12, 31)

# ------------------------------------------------------------------ lookups
ROLES = [
    (1, "admin",  "Full access: manage users, roles and all content", True),
    (2, "editor", "Edits and publishes any post, moderates comments", True),
    (3, "author", "Writes and publishes own posts", True),
    (4, "reader", "Reads posts and writes comments", False),
]
COUNTRIES = [
    ("IN", "India", "Asia"), ("US", "United States", "North America"),
    ("GB", "United Kingdom", "Europe"), ("DE", "Germany", "Europe"),
    ("AU", "Australia", "Oceania"), ("CA", "Canada", "North America"),
    ("SG", "Singapore", "Asia"), ("AE", "United Arab Emirates", "Asia"),
    ("FR", "France", "Europe"), ("BR", "Brazil", "South America"),
]
COUNTRY_W = [38, 18, 9, 6, 5, 6, 6, 5, 4, 3]
PLANS = [(1, "Free", 0.00, 5), (2, "Pro", 9.00, 50), (3, "Team", 29.00, 500)]
PLAN_W = [60, 30, 10]

FIRST = ["Aarav", "Diya", "Rohan", "Ananya", "Vikram", "Meera", "Arjun", "Isha",
         "Karthik", "Priya", "Sanjay", "Neha", "Rahul", "Kavya", "Aditya",
         "Sneha", "Emma", "Liam", "Olivia", "Noah", "Sophia", "James", "Mia",
         "Lucas", "Chloe", "Ethan", "Hannah", "Oscar", "Lena", "Mateus",
         "Camila", "Yusuf", "Fatima", "Wei", "Mei", "Hiro", "Zara", "Omar"]
LAST = ["Sharma", "Iyer", "Reddy", "Nair", "Patel", "Gupta", "Menon", "Das",
        "Khan", "Singh", "Smith", "Brown", "Taylor", "Wilson", "Clarke",
        "Muller", "Schmidt", "Dubois", "Silva", "Costa", "Tan", "Lim",
        "Hassan", "Ali", "Fernandes", "Rao", "Kapoor", "Joshi", "Bose"]

TAGS = ["python", "sql", "mongodb", "data-science", "machine-learning",
        "statistics", "visualization", "pandas", "career", "tutorial",
        "productivity", "cloud", "devops", "nlp", "deep-learning",
        "databases", "analytics", "beginners", "writing", "tools",
        "open-source", "web-dev", "flask", "indexing", "case-study"]
TAG_W = [14, 12, 9, 10, 8, 5, 6, 7, 4, 9, 3, 4, 3, 4, 5, 6, 8, 7, 2, 3, 2, 4, 3, 4, 3]
CATEGORIES = ["Tutorial", "Guide", "Case Study", "Opinion", "News", "Review"]
CATEGORY_W = [34, 22, 14, 12, 10, 8]
COMMENTS = [
    "Great explanation, this finally made it click for me.",
    "Could you share the dataset used in the example?",
    "I ran into an error on step 3, any tips?",
    "Bookmarked for my next project.",
    "Nice write-up! Would love a follow-up on performance.",
    "Thanks, the diagrams were really helpful.",
    "I disagree with the second point, but good discussion.",
    "Works perfectly on my setup.",
    "Is there a faster approach for very large tables?",
    "Clear and concise. Sharing with my class.",
    "This saved me hours of debugging.",
    "Please cover indexing in the next post.",
    "Typo in the third code block, otherwise excellent.",
    "How does this compare with the alternative approach?",
    "Super useful for my assignment, thank you!",
]
TITLE_T = [
    "Getting started with {t}", "{n} common {t} mistakes to avoid",
    "A practical guide to {t}", "Why {t} matters for analytics",
    "{t} in the real world: lessons learned", "Hands-on {t}: a worked example",
    "From zero to confident in {t}", "Tips and tricks for {t}",
    "{t} vs the alternatives: what to pick",
]
DISPLAY = {"sql": "SQL", "nlp": "NLP", "mongodb": "MongoDB", "devops": "DevOps",
           "case-study": "Case Studies", "web-dev": "Web Development", "tools": "Developer Tools",
           "writing": "Technical Writing", "career": "Career Growth", "beginners": "Beginner Projects", "tutorial": "Tutorials",
           "open-source": "Open Source Projects", "opinion": "Opinion Pieces"}
SERIES = ["Data Foundations", "Python for Analysts", "Database Deep Dive"]


def sha(s):
    return hashlib.sha256(s.encode()).hexdigest()


def q(s):
    """SQL string literal."""
    return "'" + str(s).replace("'", "''") + "'"


def rand_date(a, b):
    return a + timedelta(days=random.randint(0, (b - a).days))


def poisson(lam):
    L, k, p = math.exp(-lam), 0, 1.0
    while p > L:
        k += 1
        p *= random.random()
    return k - 1


# ------------------------------------------------------------------ users
N_USERS = 200
role_pool = [1] * 3 + [2] * 10 + [3] * 40 + [4] * (N_USERS - 53)
random.shuffle(role_pool)
role_pool[:3] = [1, 1, 1]                     # make sure the first three are admins
role_pool = role_pool[:3] + [r for r in role_pool[3:] if r != 1][: N_USERS - 3]
while len(role_pool) < N_USERS:
    role_pool.append(4)

users, used_usernames = [], set()
for uid in range(1, N_USERS + 1):
    fn, ln = random.choice(FIRST), random.choice(LAST)
    uname = f"{fn}.{ln}".lower()
    if uname in used_usernames:
        uname = f"{uname}{uid}"
    used_usernames.add(uname)
    # sign-ups grow over time (squaring the random number skews to later dates)
    span = (END - START).days
    signup = START + timedelta(days=int(span * (random.random() ** 0.8)))
    if uid <= 3:
        signup = START + timedelta(days=uid * 2)
    users.append({
        "user_id": uid, "username": uname, "full_name": f"{fn} {ln}",
        "email": f"{uname}@example.com", "password_hash": sha(f"demo-{uid}-{SEED}"),
        "role_id": role_pool[uid - 1],
        "country_code": random.choices([c[0] for c in COUNTRIES], COUNTRY_W)[0],
        "signup_date": signup,
        "is_active": random.random() > 0.07,
    })
by_id = {u["user_id"]: u for u in users}

# ------------------------------------------------------------------ subscriptions
subs = []
for u in users:
    plan = random.choices([1, 2, 3], PLAN_W)[0]
    start = u["signup_date"]
    if u["role_id"] == 4 and random.random() < 0.15:
        plan = 1
    # ~22 % of users upgrade later: Free (expired) -> Pro/Team (active)
    if plan == 1 and random.random() < 0.22 and (END - start).days > 40:
        up = start + timedelta(days=random.randint(20, max(21, (END - start).days - 5)))
        subs.append((u["user_id"], 1, start, up, "expired"))
        subs.append((u["user_id"], random.choice([2, 2, 3]), up, None, "active"))
    elif not u["is_active"] and plan > 1 and (END - start).days > 40:
        end = start + timedelta(days=random.randint(20, (END - start).days - 1))
        subs.append((u["user_id"], plan, start, end, "cancelled"))
    else:
        subs.append((u["user_id"], plan, start, None, "active"))
# load order matters for the BEFORE INSERT trigger: older rows first
subs.sort(key=lambda s: (s[0], s[2]))

# ------------------------------------------------------------------ logins
logins = []
mean_logins = {1: 26, 2: 20, 3: 14, 4: 5}
hour_w = [1, 1, 1, 1, 1, 2, 3, 5, 7, 8, 8, 7, 6, 6, 7, 7, 7, 8, 9, 10, 10, 8, 5, 3]
for u in users:
    if random.random() < 0.08:                  # registered but never logged in
        continue
    n = max(1, poisson(mean_logins[u["role_id"]]))
    first, last = u["signup_date"], END
    if random.random() < 0.25 or not u["is_active"]:   # churned: stops early
        last = min(END, first + timedelta(days=random.randint(15, 240)))
    for _ in range(n):
        d = rand_date(first, last)
        ts = datetime(d.year, d.month, d.day, random.choices(range(24), hour_w)[0],
                      random.randint(0, 59), random.randint(0, 59))
        logins.append((u["user_id"], ts, random.choices(["web", "android", "ios"], [55, 30, 15])[0]))
logins.sort(key=lambda r: r[1])

# ------------------------------------------------------------------ role changes shown by the trigger
# a few promotions / deactivations executed at the end of data.sql
promo_readers = [u["user_id"] for u in users if u["role_id"] == 4 and u["is_active"]][:4]
promo_authors = [u["user_id"] for u in users if u["role_id"] == 3 and u["is_active"]][:2]
deact = [u["user_id"] for u in users if u["role_id"] == 4 and u["is_active"]][4:6]


# ------------------------------------------------------------------ write data.sql
def multi(table, cols, rows, size=100):
    out = []
    for i in range(0, len(rows), size):
        chunk = rows[i:i + size]
        out.append(f"INSERT INTO {table} ({', '.join(cols)}) VALUES\n  " +
                   ",\n  ".join("(" + ", ".join(r) + ")" for r in chunk) + ";\n")
    return "\n".join(out)


lines = [
    "-- =====================================================================",
    "-- BlogPulse  |  data.sql  |  synthetic sample data (generated)",
    f"-- Generated by scripts/generate_data.py (seed {SEED}). Run AFTER schema.sql.",
    "-- Data source: randomly generated with Python; no real people. Emails use",
    "-- the reserved example.com domain; password_hash values are SHA-256 of dummy text.",
    "-- =====================================================================",
    "BEGIN;",
    "",
    multi("roles", ["role_id", "role_name", "description", "can_publish"],
          [[str(r[0]), q(r[1]), q(r[2]), "TRUE" if r[3] else "FALSE"] for r in ROLES]),
    multi("countries", ["country_code", "country_name", "region"],
          [[q(c[0]), q(c[1]), q(c[2])] for c in COUNTRIES]),
    multi("plans", ["plan_id", "plan_name", "monthly_price", "max_posts_per_month"],
          [[str(p[0]), q(p[1]), f"{p[2]:.2f}", str(p[3])] for p in PLANS]),
    "-- users (the trigger trg_users_audit writes one ACCOUNT_CREATED row per user)",
    multi("users", ["user_id", "username", "full_name", "email", "password_hash",
                    "role_id", "country_code", "signup_date", "is_active"],
          [[str(u["user_id"]), q(u["username"]), q(u["full_name"]), q(u["email"]),
            q(u["password_hash"]), str(u["role_id"]), q(u["country_code"]),
            q(u["signup_date"]), "TRUE" if u["is_active"] else "FALSE"] for u in users]),
    multi("subscriptions", ["user_id", "plan_id", "start_date", "end_date", "status"],
          [[str(s[0]), str(s[1]), q(s[2]), q(s[3]) if s[3] else "NULL", q(s[4])] for s in subs]),
    multi("user_logins", ["user_id", "login_at", "device"],
          [[str(l[0]), q(l[1].strftime("%Y-%m-%d %H:%M:%S")), q(l[2])] for l in logins], size=200),
    "-- keep the identity sequence ahead of the explicitly inserted user_ids",
    "SELECT setval(pg_get_serial_sequence('users','user_id'), (SELECT MAX(user_id) FROM users));",
    "",
    "-- A few UPDATEs so the audit trigger has role changes / deactivations to show",
    "UPDATE users SET role_id = 3 WHERE user_id IN (" + ", ".join(map(str, promo_readers)) + ");   -- reader -> author",
    "UPDATE users SET role_id = 2 WHERE user_id IN (" + ", ".join(map(str, promo_authors)) + ");   -- author -> editor",
    "UPDATE users SET is_active = FALSE WHERE user_id IN (" + ", ".join(map(str, deact)) + ");     -- deactivated",
    "",
    "COMMIT;",
    "",
    "ANALYZE;",
]
(ROOT / "data.sql").write_text("\n".join(lines) + "\n", encoding="utf-8")

# ------------------------------------------------------------------ MongoDB posts
# authors are the users that were author/editor/admin at sign-up
writers = [u for u in users if u["role_id"] in (1, 2, 3)]
w_weights = [random.paretovariate(1.4) for _ in writers]   # a few prolific authors
N_POSTS = 300
posts, slugs = [], set()
for i in range(N_POSTS):
    a = random.choices(writers, w_weights)[0]
    tags = []
    while len(tags) < random.choice([2, 3, 3, 4]):
        t = random.choices(TAGS, TAG_W)[0]
        if t not in tags:
            tags.append(t)
    main = DISPLAY.get(tags[0], tags[0].replace("-", " ").title())
    title = random.choice(TITLE_T).format(t=main, n=random.choice([3, 5, 7, 10]))
    slug = title.lower().replace(" ", "-").replace(":", "").replace(",", "")
    if slug in slugs:
        slug = f"{slug}-{i}"
    slugs.add(slug)
    created = datetime.combine(rand_date(max(a["signup_date"], START), END),
                               datetime.min.time()) + timedelta(
        hours=random.randint(6, 22), minutes=random.randint(0, 59))
    published = random.random() > 0.10
    age_days = max(1, (datetime.combine(END, datetime.min.time()) - created).days)
    views = int(random.lognormvariate(5.2, 1.0) * (1 + age_days / 250)) if published else 0
    likes = int(views * random.uniform(0.01, 0.06))
    doc = {
        "title": title, "slug": slug,
        "author_id": a["user_id"], "author_name": a["full_name"],
        "category": random.choices(CATEGORIES, CATEGORY_W)[0],
        "tags": tags,
        "body": f"A practical look at {', '.join(tags[:2])} with examples, common pitfalls and next steps.",
        "status": "published" if published else "draft",
        "views": views, "likes": likes,
        "created_at": {"$date": created.strftime("%Y-%m-%dT%H:%M:%SZ")},
        "comments": [],
    }
    # optional fields: schema varies between documents (why a document model fits)
    if random.random() < 0.30:
        doc["cover_image"] = f"/img/covers/{slug[:30]}.jpg"
    if random.random() < 0.60:
        doc["reading_time_min"] = random.randint(3, 15)
    if random.random() < 0.10:
        doc["series"] = {"name": random.choice(SERIES), "part": random.randint(1, 5)}
    if published:
        n_c = min(12, poisson(0.8 + views / 450))
        for c in range(n_c):
            cdate = created + timedelta(hours=random.randint(1, 24 * 40))
            if cdate.date() > END:
                cdate = datetime.combine(END, datetime.min.time()) + timedelta(hours=random.randint(1, 23))
            eligible = [u for u in users if u["signup_date"] <= cdate.date()]
            cu = random.choice(eligible)
            doc["comments"].append({
                "comment_id": c + 1, "user_id": cu["user_id"], "user_name": cu["full_name"],
                "text": random.choice(COMMENTS), "likes": poisson(1.2),
                "created_at": {"$date": cdate.strftime("%Y-%m-%dT%H:%M:%SZ")},
            })
        doc["comments"].sort(key=lambda x: x["created_at"]["$date"])
    posts.append(doc)

(ROOT / "mongo").mkdir(exist_ok=True)
with open(ROOT / "mongo" / "posts.json", "w", encoding="utf-8") as f:
    f.write("[\n" + ",\n".join(json.dumps(p, ensure_ascii=False) for p in posts) + "\n]\n")

n_comments = sum(len(p["comments"]) for p in posts)
sql_rows = len(ROLES) + len(COUNTRIES) + len(PLANS) + len(users) + len(subs) + len(logins)
print(f"users={len(users)} subscriptions={len(subs)} logins={len(logins)} "
      f"(SQL rows loaded by data.sql, excl. trigger-made audit rows: {sql_rows})")
print(f"posts={len(posts)} embedded comments={n_comments}")
