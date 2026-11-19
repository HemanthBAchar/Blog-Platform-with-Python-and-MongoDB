#!/usr/bin/env python3
"""
BlogPulse command-line application
===================================
Users, roles and subscriptions  -> PostgreSQL  (Python DB-API via psycopg2)
Posts, embedded comments, tags  -> MongoDB     (PyMongo)

Examples
    python blogpulse_app.py seed-mongo
    python blogpulse_app.py users list --role author
    python blogpulse_app.py users add --username demo --name "Demo User" \
           --email demo@example.com --role reader --country IN
    python blogpulse_app.py users set-role demo author
    python blogpulse_app.py users audit
    python blogpulse_app.py posts create --author demo --title "Hello" --tags python,sql --body "..."
    python blogpulse_app.py posts comment hello --user liam.reddy --text "Nice!"
    python blogpulse_app.py posts search --tag python
    python blogpulse_app.py report top-posts
    python blogpulse_app.py backup

Connection settings come from environment variables (defaults in brackets):
    PGHOST [localhost] PGPORT [5432] PGUSER [postgres] PGPASSWORD [] PGDATABASE [blogpulse]
    MONGO_URI [mongodb://localhost:27017]  MONGO_DB [blogpulse]
"""
import argparse
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import psycopg2                      # PostgreSQL DB-API driver
from pymongo import MongoClient, ASCENDING, DESCENDING
from pymongo.errors import PyMongoError, DuplicateKeyError
from bson import json_util

ROOT = Path(__file__).resolve().parent


# ----------------------------------------------------------------- connections
def pg_connect():
    return psycopg2.connect(
        host=os.getenv("PGHOST", "localhost"),
        port=os.getenv("PGPORT", "5432"),
        user=os.getenv("PGUSER", "postgres"),
        password=os.getenv("PGPASSWORD", ""),
        dbname=os.getenv("PGDATABASE", "blogpulse"),
    )


def mongo_db():
    client = MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017"),
                         serverSelectionTimeoutMS=4000)
    return client[os.getenv("MONGO_DB", "blogpulse")]


def table(rows, headers):
    """Tiny text-table printer."""
    rows = [[("" if v is None else str(v)) for v in r] for r in rows]
    widths = [max(len(h), *(len(r[i]) for r in rows)) if rows else len(h)
              for i, h in enumerate(headers)]
    line = "  ".join(h.ljust(w) for h, w in zip(headers, widths))
    print(line)
    print("  ".join("-" * w for w in widths))
    for r in rows:
        print("  ".join(v.ljust(w) for v, w in zip(r, widths)))
    print(f"({len(rows)} rows)")


def slugify(title):
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")


# ----------------------------------------------------------------- SQL helpers
def find_user(cur, username):
    """Return (user_id, full_name, role_name, is_active) or exit with a message."""
    cur.execute(
        "SELECT u.user_id, u.full_name, r.role_name, u.is_active "
        "FROM users u JOIN roles r ON r.role_id = u.role_id WHERE u.username = %s",
        (username,))
    row = cur.fetchone()
    if row is None:
        sys.exit(f"No such user: {username}")
    return row


# ----------------------------------------------------------------- users (SQL)
def users_list(args):
    sql = ("SELECT user_id, username, role_name, country_name, current_plan, "
           "login_count, is_active FROM v_user_overview")
    params = []
    if args.role:
        sql += " WHERE role_name = %s"
        params.append(args.role)
    sql += " ORDER BY user_id LIMIT %s"
    params.append(args.limit)
    with pg_connect() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        table(cur.fetchall(), ["id", "username", "role", "country", "plan", "logins", "active"])


def users_add(args):
    with pg_connect() as conn, conn.cursor() as cur:        # 'with conn' = one transaction
        cur.execute("SELECT role_id FROM roles WHERE role_name = %s", (args.role,))
        role = cur.fetchone()
        if role is None:
            sys.exit(f"Unknown role {args.role!r}")
        cur.execute(
            "INSERT INTO users (username, full_name, email, password_hash, role_id, country_code) "
            "VALUES (%s, %s, %s, REPEAT('0', 64), %s, %s) RETURNING user_id",
            (args.username, args.name, args.email, role[0], args.country.upper()))
        print("Created user_id", cur.fetchone()[0], "(audit row written by trigger)")


def users_set_role(args):
    with pg_connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT role_id FROM roles WHERE role_name = %s", (args.role,))
        role = cur.fetchone()
        if role is None:
            sys.exit(f"Unknown role {args.role!r}")
        cur.execute("UPDATE users SET role_id = %s WHERE username = %s", (role[0], args.username))
        print("Updated" if cur.rowcount else "No such user", args.username)


def users_deactivate(args):
    with pg_connect() as conn, conn.cursor() as cur:
        cur.execute("UPDATE users SET is_active = FALSE WHERE username = %s", (args.username,))
        print("Deactivated" if cur.rowcount else "No such user", args.username)


def users_audit(args):
    with pg_connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT a.changed_at, u.username, a.action, a.old_value, a.new_value "
            "FROM account_audit_log a LEFT JOIN users u ON u.user_id = a.user_id "
            "WHERE a.action <> 'ACCOUNT_CREATED' ORDER BY a.log_id DESC LIMIT %s", (args.limit,))
        table(cur.fetchall(), ["changed_at", "user", "action", "old", "new"])


# ----------------------------------------------------------------- posts (MongoDB)
def posts_create(args):
    with pg_connect() as conn, conn.cursor() as cur:         # validate author in SQL
        user_id, full_name, role, active = find_user(cur, args.author)
    if role not in ("admin", "editor", "author") or not active:
        sys.exit(f"{args.author} is not an active author/editor/admin")
    doc = {
        "title": args.title, "slug": slugify(args.title),
        "author_id": user_id, "author_name": full_name,
        "category": args.category,
        "tags": [t.strip().lower() for t in args.tags.split(",") if t.strip()],
        "body": args.body, "status": args.status,
        "views": 0, "likes": 0,
        "created_at": datetime.now(timezone.utc), "comments": [],
    }
    res = mongo_db().posts.insert_one(doc)
    print("Inserted post", res.inserted_id, "slug =", doc["slug"])


def posts_show(args):
    doc = mongo_db().posts.find_one({"slug": args.slug})
    print(json_util.dumps(doc, indent=2) if doc else "Not found")


def posts_comment(args):
    with pg_connect() as conn, conn.cursor() as cur:
        user_id, full_name, _, active = find_user(cur, args.user)
    if not active:
        sys.exit("Deactivated users cannot comment")
    posts = mongo_db().posts
    post = posts.find_one({"slug": args.slug}, {"comments": 1})
    if post is None:
        sys.exit("Post not found")
    next_id = len(post.get("comments", [])) + 1
    posts.update_one({"slug": args.slug}, {"$push": {"comments": {
        "comment_id": next_id, "user_id": user_id, "user_name": full_name,
        "text": args.text, "likes": 0, "created_at": datetime.now(timezone.utc)}}})
    print(f"Comment {next_id} added to {args.slug}")


def posts_update(args):
    changes = {}
    if args.status:
        changes["status"] = args.status
    if args.title:
        changes["title"] = args.title
    if not changes:
        sys.exit("Nothing to update (use --status and/or --title)")
    changes["updated_at"] = datetime.now(timezone.utc)
    res = mongo_db().posts.update_one({"slug": args.slug}, {"$set": changes})
    print("Matched", res.matched_count, "modified", res.modified_count)


def posts_delete(args):
    res = mongo_db().posts.delete_one({"slug": args.slug})
    print("Deleted", res.deleted_count)


def posts_search(args):
    query = {}
    if args.tag:
        query["tags"] = args.tag.lower()
    if args.text:
        query["$text"] = {"$search": args.text}
    if not query:
        sys.exit("Use --tag and/or --text")
    cursor = mongo_db().posts.find(query, {"title": 1, "author_name": 1, "views": 1, "tags": 1, "_id": 0}
                                   ).sort("views", DESCENDING).limit(args.limit)
    table([(d["title"], d["author_name"], d["views"], ",".join(d["tags"])) for d in cursor],
          ["title", "author", "views", "tags"])


# ----------------------------------------------------------------- aggregation reports
PIPELINES = {
    "top-posts": [
        {"$match": {"status": "published"}},
        {"$addFields": {"comment_count": {"$size": "$comments"}}},
        {"$addFields": {"engagement": {"$add": ["$views", {"$multiply": ["$likes", 5]},
                                                {"$multiply": ["$comment_count", 10]}]}}},
        {"$sort": {"engagement": -1}}, {"$limit": 10},
        {"$project": {"_id": 0, "title": 1, "author_name": 1, "views": 1, "likes": 1,
                      "comment_count": 1, "engagement": 1}},
    ],
    "popular-tags": [
        {"$match": {"status": "published"}},
        {"$unwind": "$tags"},
        {"$group": {"_id": "$tags", "posts": {"$sum": 1}, "avg_views": {"$avg": "$views"},
                    "total_comments": {"$sum": {"$size": "$comments"}}}},
        {"$sort": {"posts": -1, "_id": 1}}, {"$limit": 10},
        {"$project": {"_id": 0, "tag": "$_id", "posts": 1,
                      "avg_views": {"$round": ["$avg_views", 0]}, "total_comments": 1}},
    ],
    "comments-per-author": [
        {"$match": {"status": "published"}},
        {"$group": {"_id": {"id": "$author_id", "name": "$author_name"}, "posts": {"$sum": 1},
                    "comments": {"$sum": {"$size": "$comments"}}, "views": {"$sum": "$views"}}},
        {"$addFields": {"comments_per_post": {"$round": [{"$divide": ["$comments", "$posts"]}, 2]}}},
        {"$sort": {"comments": -1}}, {"$limit": 10},
        {"$project": {"_id": 0, "author_id": "$_id.id", "author": "$_id.name", "posts": 1,
                      "comments": 1, "comments_per_post": 1, "views": 1}},
    ],
}


def report(args):
    rows = list(mongo_db().posts.aggregate(PIPELINES[args.name]))
    if not rows:
        print("(no results)")
        return
    headers = list(rows[0].keys())
    table([[r.get(h) for h in headers] for r in rows], headers)


# ----------------------------------------------------------------- admin
def seed_mongo(args):
    """Load mongo/posts.json and create the indexes (drops the old collection)."""
    db = mongo_db()
    docs = json_util.loads((ROOT / "mongo" / "posts.json").read_text(encoding="utf-8"))
    db.posts.drop()
    db.posts.insert_many(docs)
    db.posts.create_index([("slug", ASCENDING)], unique=True, name="ux_slug")
    db.posts.create_index([("tags", ASCENDING)], name="ix_tags")
    db.posts.create_index([("author_id", ASCENDING), ("created_at", DESCENDING)], name="ix_author_date")
    db.posts.create_index([("created_at", DESCENDING)], name="ix_created")
    db.posts.create_index([("title", "text"), ("body", "text")], name="tx_title_body")
    print(f"Loaded {len(docs)} posts and created {len(db.posts.index_information())} indexes")


def backup(args):
    """Backup PostgreSQL (pg_dump) and MongoDB posts (JSON export)."""
    out = Path(args.dir)
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    sql_file = out / f"blogpulse_pg_{stamp}.sql"
    env = dict(os.environ, PGPASSWORD=os.getenv("PGPASSWORD", ""))
    subprocess.run(["pg_dump", "-h", os.getenv("PGHOST", "localhost"),
                    "-p", os.getenv("PGPORT", "5432"), "-U", os.getenv("PGUSER", "postgres"),
                    "-f", str(sql_file), os.getenv("PGDATABASE", "blogpulse")],
                   check=True, env=env)
    print("PostgreSQL backup ->", sql_file)

    json_file = out / f"blogpulse_posts_{stamp}.json"
    docs = list(mongo_db().posts.find({}))
    json_file.write_text(json_util.dumps(docs), encoding="utf-8")
    print(f"MongoDB backup    -> {json_file} ({len(docs)} posts)")


# ----------------------------------------------------------------- CLI wiring
def build_parser():
    p = argparse.ArgumentParser(description="BlogPulse: PostgreSQL users + MongoDB posts")
    sub = p.add_subparsers(dest="group", required=True)

    sub.add_parser("seed-mongo", help="load mongo/posts.json and create indexes").set_defaults(fn=seed_mongo)
    b = sub.add_parser("backup", help="back up PostgreSQL and MongoDB")
    b.add_argument("--dir", default="backups")
    b.set_defaults(fn=backup)

    u = sub.add_parser("users", help="user administration (SQL)").add_subparsers(dest="cmd", required=True)
    x = u.add_parser("list");        x.add_argument("--role"); x.add_argument("--limit", type=int, default=20); x.set_defaults(fn=users_list)
    x = u.add_parser("add")
    x.add_argument("--username", required=True); x.add_argument("--name", required=True)
    x.add_argument("--email", required=True); x.add_argument("--role", default="reader")
    x.add_argument("--country", default="IN"); x.set_defaults(fn=users_add)
    x = u.add_parser("set-role");    x.add_argument("username"); x.add_argument("role"); x.set_defaults(fn=users_set_role)
    x = u.add_parser("deactivate");  x.add_argument("username"); x.set_defaults(fn=users_deactivate)
    x = u.add_parser("audit");       x.add_argument("--limit", type=int, default=20); x.set_defaults(fn=users_audit)

    po = sub.add_parser("posts", help="posts and comments (MongoDB)").add_subparsers(dest="cmd", required=True)
    x = po.add_parser("create")
    x.add_argument("--author", required=True, help="username of the author"); x.add_argument("--title", required=True)
    x.add_argument("--tags", default=""); x.add_argument("--body", default="")
    x.add_argument("--category", default="Tutorial"); x.add_argument("--status", default="published", choices=["draft", "published"])
    x.set_defaults(fn=posts_create)
    x = po.add_parser("show");    x.add_argument("slug"); x.set_defaults(fn=posts_show)
    x = po.add_parser("comment"); x.add_argument("slug"); x.add_argument("--user", required=True); x.add_argument("--text", required=True); x.set_defaults(fn=posts_comment)
    x = po.add_parser("update");  x.add_argument("slug"); x.add_argument("--status", choices=["draft", "published"]); x.add_argument("--title"); x.set_defaults(fn=posts_update)
    x = po.add_parser("delete");  x.add_argument("slug"); x.set_defaults(fn=posts_delete)
    x = po.add_parser("search");  x.add_argument("--tag"); x.add_argument("--text"); x.add_argument("--limit", type=int, default=10); x.set_defaults(fn=posts_search)

    r = sub.add_parser("report", help="MongoDB aggregation reports")
    r.add_argument("name", choices=sorted(PIPELINES))
    r.set_defaults(fn=report)
    return p


if __name__ == "__main__":
    args = build_parser().parse_args()
    try:
        args.fn(args)
    except psycopg2.Error as e:                      # e.g. duplicate e-mail, bad country code
        sys.exit(f"PostgreSQL error: {str(e).strip().splitlines()[0]}")
    except DuplicateKeyError:                        # unique index on slug
        sys.exit("MongoDB error: a post with that slug already exists")
    except PyMongoError as e:
        sys.exit(f"MongoDB error: {e}")
