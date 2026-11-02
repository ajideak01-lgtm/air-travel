import os
import re
import sqlite3
import secrets
import hmac
import urllib.parse
from datetime import datetime, timedelta, timezone
from functools import wraps
from contextlib import contextmanager
from pathlib import Path

from flask import Flask, abort, flash, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
import requests

BASE_DIR = Path(__file__).resolve().parent


def load_local_env():
    """Read a local .env file without requiring extra packages; real env vars win."""
    env_file = BASE_DIR / ".env"
    if not env_file.is_file():
        return
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


load_local_env()
DB_PATH = Path(os.getenv("DATABASE_PATH", str(BASE_DIR / "airtravel.db")))

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.getenv("SECRET_KEY", "LOCAL-ONLY-change-this-before-public-launch"),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.getenv("COOKIE_SECURE", "0") == "1",
)

OWNER_EMAIL = os.getenv("OWNER_EMAIL", "owner@airtravel.local").strip().lower()
OWNER_PASSWORD = os.getenv("OWNER_PASSWORD", "AirTravelOwner2026!")
CO_OWNER_EMAIL = os.getenv("CO_OWNER_EMAIL", "coowner@airtravel.local").strip().lower()
CO_OWNER_PASSWORD = os.getenv("CO_OWNER_PASSWORD", "AirTravelCoOwner2026!")


@contextmanager
def db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=15)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def init_db():
    with db() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'guest',
            must_change_password INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        con.execute("""CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user TEXT NOT NULL,
            body TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        con.execute("""CREATE TABLE IF NOT EXISTS ads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            sponsor TEXT NOT NULL,
            description TEXT NOT NULL,
            link TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        con.execute("""CREATE TABLE IF NOT EXISTS notices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            body TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        con.execute("""CREATE TABLE IF NOT EXISTS diary_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            note TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )""")
        con.execute("""CREATE TABLE IF NOT EXISTS support_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            topic TEXT NOT NULL,
            message TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'new',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )""")
        # Add columns when upgrading an earlier AIR TRAVEL SQLite database.
        columns = {row[1] for row in con.execute("PRAGMA table_info(users)")}
        if "password_hash" not in columns:
            con.execute("ALTER TABLE users ADD COLUMN password_hash TEXT")
            if "password" in columns:
                con.execute("UPDATE users SET password_hash=password WHERE password_hash IS NULL")
        if "role" not in columns:
            con.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'guest'")
        if "must_change_password" not in columns:
            con.execute("ALTER TABLE users ADD COLUMN must_change_password INTEGER NOT NULL DEFAULT 0")
        if "created_at" not in columns:
            con.execute("ALTER TABLE users ADD COLUMN created_at TEXT NOT NULL DEFAULT ''")
        con.execute("UPDATE users SET created_at=CURRENT_TIMESTAMP WHERE created_at='' OR created_at IS NULL")
        msg_columns = {row[1] for row in con.execute("PRAGMA table_info(messages)")}
        if "created_at" not in msg_columns:
            con.execute("ALTER TABLE messages ADD COLUMN created_at TEXT NOT NULL DEFAULT ''")
            if "created" in msg_columns:
                con.execute("UPDATE messages SET created_at=created WHERE created_at='' OR created_at IS NULL")
        con.execute("UPDATE messages SET created_at=CURRENT_TIMESTAMP WHERE created_at='' OR created_at IS NULL")

        # Membership columns are added safely when an older review database is upgraded.
        user_columns = {row[1] for row in con.execute("PRAGMA table_info(users)")}
        if "premium_trial_used" not in user_columns:
            con.execute("ALTER TABLE users ADD COLUMN premium_trial_used INTEGER NOT NULL DEFAULT 0")
        if "premium_started_at" not in user_columns:
            con.execute("ALTER TABLE users ADD COLUMN premium_started_at TEXT")
        if "premium_expires_at" not in user_columns:
            con.execute("ALTER TABLE users ADD COLUMN premium_expires_at TEXT")
        con.execute("""CREATE TABLE IF NOT EXISTS trip_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            destination TEXT NOT NULL,
            days INTEGER NOT NULL,
            budget REAL NOT NULL DEFAULT 0,
            interests TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )""")
        con.execute("""CREATE TABLE IF NOT EXISTS group_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            channel TEXT NOT NULL,
            body TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )""")
        con.execute("""CREATE TABLE IF NOT EXISTS passport_stamps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            country TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, country),
            FOREIGN KEY(user_id) REFERENCES users(id)
        )""")
        con.execute("""CREATE TABLE IF NOT EXISTS movie_rooms (
            code TEXT PRIMARY KEY,
            host_user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            media_url TEXT NOT NULL,
            playback_state TEXT NOT NULL DEFAULT 'paused',
            position REAL NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(host_user_id) REFERENCES users(id)
        )""")

        # Seed owner accounts only when the email is not already registered.
        seed_account(con, "AKINOLA AJIDE", OWNER_EMAIL, OWNER_PASSWORD, "owner")
        seed_account(con, "JAYDINE", CO_OWNER_EMAIL, CO_OWNER_PASSWORD, "co_owner")


def seed_account(con, name, email, password, role):
    if not email or not password:
        return
    existing = con.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
    if not existing:
        con.execute(
            "INSERT INTO users(name,email,password_hash,role,must_change_password) VALUES(?,?,?,?,1)",
            (name, email, generate_password_hash(password), role),
        )
    else:
        # Promote the configured ownership accounts without overwriting an existing password.
        con.execute("UPDATE users SET role=?, name=? WHERE email=?", (role, name, email))


# Initialise on import too, so the database exists under both `python app.py` and WSGI hosts.
init_db()


def logged_in(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login", next=request.path))
        if session.get("must_change_password") and request.endpoint not in {"change_password", "logout", "static"}:
            return redirect(url_for("change_password"))
        return view(*args, **kwargs)
    return wrapper


def staff_required(view):
    @wraps(view)
    @logged_in
    def wrapper(*args, **kwargs):
        if session.get("role") not in {"owner", "co_owner", "admin"}:
            abort(403)
        return view(*args, **kwargs)
    return wrapper


def owner_required(view):
    @wraps(view)
    @logged_in
    def wrapper(*args, **kwargs):
        if session.get("role") != "owner":
            abort(403)
        return view(*args, **kwargs)
    return wrapper


def safe_local_redirect(target):
    """Return only same-site absolute paths; reject protocol-relative or external URLs."""
    target = (target or "").strip()
    parsed = urllib.parse.urlparse(target)
    if target.startswith("/") and not target.startswith("//") and not parsed.netloc and parsed.scheme == "":
        return target
    return None


def membership_for_user(user_id):
    with db() as con:
        user = con.execute("SELECT premium_trial_used,premium_started_at,premium_expires_at FROM users WHERE id=?", (user_id,)).fetchone()
    if not user:
        return {"active": False, "used": False, "expires_at": None, "days_left": 0}
    expires = None
    active = False
    days_left = 0
    if user["premium_expires_at"]:
        try:
            expires = datetime.fromisoformat(user["premium_expires_at"].replace("Z", "+00:00"))
            active = expires > datetime.now(timezone.utc)
            if active:
                days_left = max(1, (expires - datetime.now(timezone.utc)).days + 1)
        except ValueError:
            active = False
    return {"active": active, "used": bool(user["premium_trial_used"]),
            "expires_at": user["premium_expires_at"], "days_left": days_left}


def premium_required(view):
    @wraps(view)
    @logged_in
    def wrapper(*args, **kwargs):
        membership = membership_for_user(session["user_id"])
        if not membership["active"]:
            if request.path.startswith("/api/"):
                return jsonify(error="This feature is part of AIR TRAVEL Premium. Start the free 3-day trial to unlock it."), 403
            flash("Start your free 3-day Premium trial to open the VIP Lounge.", "error")
            return redirect(url_for("premium"))
        return view(*args, **kwargs)
    return wrapper


@app.before_request
def protect_post_requests():
    token = session.get("_csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf_token"] = token
    if request.method == "POST":
        supplied = request.form.get("csrf_token") or request.headers.get("X-CSRFToken", "")
        if not hmac.compare_digest(str(token), str(supplied)):
            abort(400)


@app.context_processor
def inject_shared_data():
    with db() as con:
        live_ads = con.execute("SELECT id,title,sponsor,description,link FROM ads WHERE active=1 ORDER BY id DESC LIMIT 2").fetchall()
        latest_notices = con.execute("SELECT title,body,created_at FROM notices ORDER BY id DESC LIMIT 3").fetchall()
    premium_membership = membership_for_user(session["user_id"]) if session.get("user_id") else {"active": False, "used": False, "expires_at": None, "days_left": 0}
    return {"live_ads": live_ads, "latest_notices": latest_notices, "csrf_token": session.get("_csrf_token", ""),
            "premium_membership": premium_membership}


@app.get("/")
def home():
    return render_template("index.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()[:80]
        email = request.form.get("email", "").strip().lower()[:160]
        password = request.form.get("password", "")
        if not name or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email) or len(password) < 8:
            flash("Enter your name, a valid email address and a password of at least 8 characters.", "error")
        else:
            try:
                with db() as con:
                    con.execute("INSERT INTO users(name,email,password_hash,role) VALUES(?,?,?,'guest')",
                                (name, email, generate_password_hash(password)))
                flash("Guest account created. You can now sign in.", "success")
                return redirect(url_for("login"))
            except sqlite3.IntegrityError:
                flash("That email already has an account.", "error")
    return render_template("auth.html", mode="register")


@app.route("/login", methods=["GET", "POST"])
def login():
    next_path = safe_local_redirect(request.values.get("next", ""))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        with db() as con:
            user = con.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session.update(user_id=user["id"], user=user["name"], email=user["email"],
                           role=user["role"], must_change_password=bool(user["must_change_password"]))
            if next_path:
                session["post_login_next"] = next_path
            if session["must_change_password"]:
                return redirect(url_for("change_password"))
            return redirect(next_path or url_for("admin" if user["role"] in {"owner", "co_owner", "admin"} else "hub"))
        flash("Email or password is incorrect.", "error")
    return render_template("auth.html", mode="login", next_path=next_path or "")


@app.get("/owner-login")
def owner_login():
    # Dedicated shortcut; it uses the same secure login form and does not expose guest registration.
    return redirect(url_for("login", account="owner"))


@app.route("/change-password", methods=["GET", "POST"])
@logged_in
def change_password():
    if request.method == "POST":
        old = request.form.get("old_password", "")
        new = request.form.get("new_password", "")
        confirm = request.form.get("confirm_password", "")
        with db() as con:
            user = con.execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()
            if not user or not check_password_hash(user["password_hash"], old):
                flash("Your current password is not correct.", "error")
            elif len(new) < 12:
                flash("Choose a new password with at least 12 characters.", "error")
            elif new != confirm:
                flash("The new passwords do not match.", "error")
            else:
                con.execute("UPDATE users SET password_hash=?,must_change_password=0 WHERE id=?",
                            (generate_password_hash(new), session["user_id"]))
                session["must_change_password"] = False
                flash("Password updated successfully.", "success")
                next_path = safe_local_redirect(session.pop("post_login_next", ""))
                return redirect(next_path or url_for("admin" if session.get("role") in {"owner", "co_owner", "admin"} else "hub"))
    return render_template("change_password.html")


@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


@app.get("/hub")
@logged_in
def hub():
    with db() as con:
        diary = con.execute("SELECT title,note,created_at FROM diary_entries WHERE user_id=? ORDER BY id DESC LIMIT 12",
                            (session["user_id"],)).fetchall()
    return render_template("hub.html", diary=diary)


@app.get("/explore")
def explore():
    return render_template("explore.html")


@app.get("/travel-tools")
def travel_tools():
    return render_template("travel_tools.html")


@app.get("/quiz")
def quiz():
    return render_template("quiz.html")


@app.get("/tv")
def travel_tv():
    return render_template("tv.html")


@app.get("/cinema")
def cinema():
    return render_template("movie_night.html")


@app.get("/world")
def air_travel_world():
    return render_template("world.html")


@app.get("/community")
@logged_in
def community():
    return render_template("community.html")


@app.get("/radio")
def radio():
    return render_template("radio.html")


@app.get("/premium")
def premium():
    membership = membership_for_user(session["user_id"]) if session.get("user_id") else {"active": False, "used": False, "expires_at": None, "days_left": 0}
    return render_template("premium.html", membership=membership)


@app.post("/premium/start")
@logged_in
def start_premium_trial():
    with db() as con:
        user = con.execute("SELECT premium_trial_used,premium_expires_at FROM users WHERE id=?", (session["user_id"],)).fetchone()
        if user and user["premium_expires_at"]:
            try:
                expiry = datetime.fromisoformat(user["premium_expires_at"].replace("Z", "+00:00"))
                if expiry > datetime.now(timezone.utc):
                    flash("Your Premium trial is already active.", "success")
                    return redirect(url_for("premium_lounge"))
            except ValueError:
                pass
        if not user or user["premium_trial_used"]:
            flash("The free 3-day Premium trial can only be activated once per account.", "error")
        else:
            now = datetime.now(timezone.utc)
            start = now.isoformat(timespec="seconds").replace("+00:00", "Z")
            expiry = (now + timedelta(days=3)).isoformat(timespec="seconds").replace("+00:00", "Z")
            con.execute("UPDATE users SET premium_trial_used=1,premium_started_at=?,premium_expires_at=? WHERE id=?",
                        (start, expiry, session["user_id"]))
            flash("Your free 3-day AIR TRAVEL Premium trial is active. It will not auto-renew or charge you.", "success")
            return redirect(url_for("premium_lounge"))
    return redirect(url_for("premium"))


@app.get("/premium/lounge")
@premium_required
def premium_lounge():
    with db() as con:
        trips = con.execute("SELECT title,destination,days,budget,interests,created_at FROM trip_plans WHERE user_id=? ORDER BY id DESC LIMIT 8", (session["user_id"],)).fetchall()
        stamps = con.execute("SELECT country,created_at FROM passport_stamps WHERE user_id=? ORDER BY id DESC", (session["user_id"],)).fetchall()
    return render_template("premium_lounge.html", trips=trips, stamps=stamps)


@app.route("/support", methods=["GET", "POST"])
def support():
    if request.method == "POST":
        name = request.form.get("name", "").strip()[:80]
        email = request.form.get("email", "").strip().lower()[:160]
        topic = request.form.get("topic", "General question").strip()[:80]
        message = request.form.get("message", "").strip()[:1500]
        if not name or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email) or len(message) < 10:
            flash("Please enter your name, a valid email address and a message of at least 10 characters.", "error")
        else:
            with db() as con:
                con.execute("INSERT INTO support_requests(user_id,name,email,topic,message) VALUES(?,?,?,?,?)",
                            (session.get("user_id"), name, email, topic, message))
            flash("Your support request has been saved for the AIR TRAVEL team.", "success")
            return redirect(url_for("support"))
    return render_template("support.html")


@app.get("/api/diary")
@logged_in
def get_diary():
    with db() as con:
        rows = con.execute("SELECT id,title,note,created_at FROM diary_entries WHERE user_id=? ORDER BY id DESC LIMIT 30",
                           (session["user_id"],)).fetchall()
    return jsonify([dict(row) for row in rows])


@app.post("/api/diary")
@logged_in
def save_diary():
    data = request.get_json(silent=True) or {}
    title = str(data.get("title", "")).strip()[:80]
    note = str(data.get("note", "")).strip()[:1500]
    if not title or not note:
        return jsonify(error="Add both a title and a note."), 400
    with db() as con:
        con.execute("INSERT INTO diary_entries(user_id,title,note) VALUES(?,?,?)",
                    (session["user_id"], title, note))
    return jsonify(ok=True)


@app.get("/api/trips")
@logged_in
@premium_required
def get_trip_plans():
    with db() as con:
        rows = con.execute("SELECT id,title,destination,days,budget,interests,created_at FROM trip_plans WHERE user_id=? ORDER BY id DESC LIMIT 20", (session["user_id"],)).fetchall()
    return jsonify([dict(row) for row in rows])


@app.post("/api/trips")
@logged_in
@premium_required
def save_trip_plan():
    data = request.get_json(silent=True) or {}
    title = str(data.get("title", "")).strip()[:80]
    destination = str(data.get("destination", "")).strip()[:100]
    interests = str(data.get("interests", "")).strip()[:300]
    try:
        days = int(data.get("days", 0))
        budget = float(data.get("budget", 0) or 0)
    except (TypeError, ValueError):
        return jsonify(error="Enter a valid trip duration and budget."), 400
    if not title or not destination or not 1 <= days <= 60 or not 0 <= budget <= 1_000_000_000_000:
        return jsonify(error="Add a title, destination, 1–60 days and a valid non-negative budget."), 400
    with db() as con:
        con.execute("INSERT INTO trip_plans(user_id,title,destination,days,budget,interests) VALUES(?,?,?,?,?,?)",
                    (session["user_id"], title, destination, days, budget, interests))
    return jsonify(ok=True, message="Trip saved to your Premium itinerary vault.")


@app.get("/api/passport")
@logged_in
@premium_required
def get_passport_stamps():
    with db() as con:
        rows = con.execute("SELECT country,created_at FROM passport_stamps WHERE user_id=? ORDER BY id", (session["user_id"],)).fetchall()
    return jsonify([dict(row) for row in rows])


@app.post("/api/passport")
@logged_in
@premium_required
def add_passport_stamp():
    data = request.get_json(silent=True) or {}
    country = str(data.get("country", "")).strip()[:80]
    allowed = {"Nigeria", "Ghana", "Kenya", "South Africa", "United Kingdom", "France", "United Arab Emirates", "Japan", "Canada", "Brazil"}
    if country not in allowed:
        return jsonify(error="Choose a destination from the available digital passport list."), 400
    with db() as con:
        try:
            con.execute("INSERT INTO passport_stamps(user_id,country) VALUES(?,?)", (session["user_id"], country))
        except sqlite3.IntegrityError:
            return jsonify(error="You already collected this digital stamp."), 409
    return jsonify(ok=True, country=country)


@app.get("/api/groups/messages")
@logged_in
def get_group_messages():
    channel = request.args.get("channel", "travel-lovers")
    allowed = {"aviation-learners", "travel-lovers", "pilot-community"}
    if channel not in allowed:
        return jsonify(error="Unknown community group."), 400
    with db() as con:
        rows = con.execute("SELECT group_messages.body,group_messages.created_at,users.name AS user FROM group_messages JOIN users ON users.id=group_messages.user_id WHERE channel=? ORDER BY group_messages.id DESC LIMIT 50", (channel,)).fetchall()
    return jsonify([dict(row) for row in reversed(rows)])


@app.post("/api/groups/messages")
@logged_in
def post_group_message():
    data = request.get_json(silent=True) or {}
    channel = str(data.get("channel", "travel-lovers"))
    body = str(data.get("body", "")).strip()
    allowed = {"aviation-learners", "travel-lovers", "pilot-community"}
    if channel not in allowed:
        return jsonify(error="Unknown community group."), 400
    if not body or len(body) > 500:
        return jsonify(error="Messages must contain 1–500 characters."), 400
    with db() as con:
        con.execute("INSERT INTO group_messages(user_id,channel,body) VALUES(?,?,?)", (session["user_id"], channel, body))
    return jsonify(ok=True)


@app.get("/admin")
@staff_required
def admin():
    with db() as con:
        total_users = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        total_messages = con.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        members = con.execute("SELECT name,email,role,created_at FROM users ORDER BY id DESC LIMIT 40").fetchall()
        ads = con.execute("SELECT * FROM ads ORDER BY id DESC LIMIT 20").fetchall()
        support_requests = con.execute("SELECT * FROM support_requests ORDER BY id DESC LIMIT 30").fetchall()
    return render_template("admin.html", total_users=total_users,
                           total_messages=total_messages, members=members, ads=ads,
                           support_requests=support_requests)


@app.post("/admin/create-admin")
@owner_required
def create_admin():
    name = request.form.get("name", "").strip()[:80]
    email = request.form.get("email", "").strip().lower()[:160]
    password = request.form.get("password", "")
    if not name or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email) or len(password) < 12:
        flash("Enter an administrator name, valid email and temporary password of at least 12 characters.", "error")
    else:
        try:
            with db() as con:
                con.execute("INSERT INTO users(name,email,password_hash,role,must_change_password) VALUES(?,?,?,'admin',1)",
                            (name, email, generate_password_hash(password)))
            flash("Administrator account created. They must change the temporary password at first sign-in.", "success")
        except sqlite3.IntegrityError:
            flash("That email already has an account.", "error")
    return redirect(url_for("admin"))


@app.post("/admin/notice")
@staff_required
def add_notice():
    title = request.form.get("title", "").strip()[:100]
    body = request.form.get("body", "").strip()[:1000]
    if title and body:
        with db() as con:
            con.execute("INSERT INTO notices(title,body) VALUES(?,?)", (title, body))
        flash("Community notice published.", "success")
    else:
        flash("Add both a notice title and message.", "error")
    return redirect(url_for("admin"))


@app.post("/admin/ad")
@owner_required
def add_ad():
    title = request.form.get("title", "").strip()[:100]
    sponsor = request.form.get("sponsor", "").strip()[:80]
    description = request.form.get("description", "").strip()[:300]
    link = request.form.get("link", "").strip()[:500]
    if not (title and sponsor and description and link.startswith(("https://", "http://"))):
        flash("Enter the advert details and a valid http(s) link.", "error")
    else:
        with db() as con:
            con.execute("INSERT INTO ads(title,sponsor,description,link) VALUES(?,?,?,?)",
                        (title, sponsor, description, link))
        flash("Advert added to the website. This is a manually managed advert, not an ad network.", "success")
    return redirect(url_for("admin"))


@app.post("/admin/ad/<int:ad_id>/toggle")
@owner_required
def toggle_ad(ad_id):
    with db() as con:
        con.execute("UPDATE ads SET active=CASE active WHEN 1 THEN 0 ELSE 1 END WHERE id=?", (ad_id,))
    flash("Advert status updated.", "success")
    return redirect(url_for("admin"))


@app.get("/api/messages")
def get_messages():
    with db() as con:
        rows = con.execute("SELECT user,body,created_at FROM messages ORDER BY id DESC LIMIT 60").fetchall()
    return jsonify([dict(row) for row in reversed(rows)])


@app.post("/api/messages")
@logged_in
def post_message():
    data = request.get_json(silent=True) or {}
    body = str(data.get("body", "")).strip()
    if not body or len(body) > 500:
        return jsonify(error="Messages must contain 1–500 characters."), 400
    with db() as con:
        con.execute("INSERT INTO messages(user,body) VALUES(?,?)", (session["user"], body))
    return jsonify(ok=True)


@app.get("/api/flights")
def flights():
    """Return demo data unless a compatible provider endpoint is configured."""
    api_url, api_key = os.getenv("FLIGHT_API_URL"), os.getenv("FLIGHT_API_KEY")
    if api_url and api_key:
        try:
            response = requests.get(api_url, headers={"Authorization": f"Bearer {api_key}"}, timeout=10)
            response.raise_for_status()
            payload = response.json()
            items = payload.get("flights", []) if isinstance(payload, dict) else payload
            clean = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                lat, lon = item.get("lat"), item.get("lon")
                try:
                    lat, lon = float(lat), float(lon)
                except (TypeError, ValueError):
                    continue
                if -90 <= lat <= 90 and -180 <= lon <= 180:
                    clean.append({"callsign": item.get("callsign") or item.get("icao24") or "Aircraft",
                                  "lat": lat, "lon": lon, "status": item.get("status") or "Reported position"})
            return jsonify(source="configured provider", demo=False, flights=clean)
        except (requests.RequestException, ValueError):
            return jsonify(error="The configured flight provider could not be reached.", demo=False), 502
    return jsonify(source="sample records", demo=True, flights=[
        {"callsign": "SAMPLE-01", "lat": 9.0765, "lon": 7.3986, "status": "DEMO — not a real aircraft"},
        {"callsign": "SAMPLE-02", "lat": 6.5244, "lon": 3.3792, "status": "DEMO — not a real aircraft"},
    ])


def local_assistant_reply(prompt):
    """Helpful built-in assistant. It works without an API key or internet access."""
    q = prompt.lower()
    if any(word in q for word in ("hello", "hi ", "hey", "good morning", "good evening")):
        return "Hello and welcome aboard! ✈️ I'm the AIR TRAVEL assistant. Ask me about airport codes, travel preparation, baggage, aviation terms, route planning or using this website."
    if (any(word in q for word in ("airport code", "what is los", "what is abv", "what is phc", "what is kan", "lagos airport", "abuja airport", "port harcourt airport", "kano airport"))
            or re.search(r"\b(?:LOS|ABV|PHC|KAN)\b", prompt, re.IGNORECASE)):
        return "Some Nigerian airport codes: LOS is Murtala Muhammed International Airport in Lagos; ABV is Nnamdi Azikiwe International Airport in Abuja; PHC is Port Harcourt International Airport; KAN is Mallam Aminu Kano International Airport. Confirm airport details with your airline before travelling."
    if any(word in q for word in ("check in", "check-in", "boarding pass", "boarding")):
        return "For a typical trip, check your airline's check-in opening and closing times, use the airline's official website or app, keep your booking reference and identification ready, and confirm your boarding gate on airport screens. Exact rules and timings vary by airline and airport."
    if any(word in q for word in ("baggage", "luggage", "suitcase", "carry-on", "hand luggage")):
        return "Baggage allowances differ by airline, route, fare and ticket type. Check the baggage section of your booking before packing. Keep travel documents, essential medication and valuables in your permitted cabin bag, and do not pack prohibited items."
    if any(word in q for word in ("passport", "visa", "immigration", "travel document")):
        return "Passport validity and visa requirements depend on your nationality and destination. Check the destination government's official immigration website and your airline before paying for a ticket. Some destinations require additional validity, permits or supporting documents."
    if any(word in q for word in ("turbulence", "bumpy", "shaking")):
        return "Turbulence is a change in airflow that can make an aircraft move unevenly. It is common. Follow the crew's instructions and keep your seat belt fastened whenever seated, even when the seat-belt sign is off."
    if any(word in q for word in ("pilot", "become a pilot", "pilot career", "flying career")):
        return "Pilot training requirements depend on the country and licence you want. A typical path includes meeting medical standards, approved ground school, flight training, examinations and flight-hour requirements. Check your national civil aviation authority and approved flight schools for current rules."
    if any(word in q for word in ("flight attendant", "cabin crew")):
        return "Cabin crew roles commonly involve passenger safety, emergency procedures, service and teamwork. Airlines set their own education, language, medical and recruitment requirements, so use the airline's official careers page for current vacancies and criteria."
    if any(word in q for word in ("budget", "cost", "save money", "cheap flight", "fare")):
        return "To plan a travel budget, add the fare, baggage, airport transport, accommodation, meals, local transport, visa or document fees and an emergency buffer. Compare the full trip cost, not only the advertised ticket price. AIR TRAVEL's Travel Tools page has a budget calculator."
    if any(word in q for word in ("route", "destination", "where should", "explore")):
        return "You can explore destination ideas on the Explore page and compare simple route ideas on the home page. The route planner is not a live schedule search, so confirm actual routes and departure times with airlines."
    if any(word in q for word in ("air travel", "website", "account", "login", "log in", "sign in", "register")):
        return "Welcome to AIR TRAVEL! Guests can register and sign in. The Pilot Hub contains the community chat, this assistant and your private travel diary. The Owner access link is separate from guest registration. Contact the team through Support if you have an account problem."
    if any(word in q for word in ("currency", "exchange rate", "convert", "dollar", "naira", "pound", "euro")):
        return "Exchange rates change throughout the day and can differ by bank or provider. Use the currency calculator on Travel Tools with a rate from your bank or a trusted current source; this built-in assistant does not claim to provide live rates."
    if any(word in q for word in ("safety", "safe", "security")):
        return "For safer travel, use official airline and airport information, protect your booking reference and personal documents, keep valuables secure, and follow airport staff and crew instructions. AIR TRAVEL is a community information platform, not an official aviation authority."
    if any(word in q for word in ("thank", "thanks")):
        return "You're welcome! Have a smooth journey and welcome to the AIR TRAVEL community. ✈️"
    return "I can help with airport codes, check-in, baggage, passports and visas, turbulence, pilot careers, cabin crew, travel budgets, currency calculations and using AIR TRAVEL. Try asking one of those questions, or include your destination and what you need to know. For current flight, visa or safety instructions, always verify with the airline or relevant official authority."


@app.post("/api/assistant")
@logged_in
def assistant():
    prompt = str((request.get_json(silent=True) or {}).get("message", "")).strip()
    if not prompt or len(prompt) > 1000:
        return jsonify(error="Enter a question of up to 1,000 characters."), 400

    # Optional generative AI: add OPENAI_API_KEY on the server. Never place keys in browser code.
    openai_key = os.getenv("OPENAI_API_KEY", "").strip()
    if openai_key:
        try:
            response = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {openai_key}", "Content-Type": "application/json"},
                json={"model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                      "messages": [
                          {"role": "system", "content": "You are AIR TRAVEL's friendly travel and aviation education assistant. Give concise general information. Never present sample flight data, visa rules, airline policies, live schedules or operational aviation instructions as verified. Direct users to official airlines and authorities for current requirements. Do not provide instructions for controlling aircraft or accessing aviation communications."},
                          {"role": "user", "content": prompt}
                      ], "temperature": 0.4}, timeout=25)
            response.raise_for_status()
            result = response.json()
            reply = result.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
            if reply:
                return jsonify(reply=reply, mode="connected AI")
        except (requests.RequestException, ValueError, KeyError, IndexError):
            # Gracefully fall back to local answers if provider setup or connectivity fails.
            pass
    return jsonify(reply=local_assistant_reply(prompt), mode="built-in assistant")


def valid_movie_media_url(value):
    """Accept only direct MP4/WebM media URLs, never arbitrary streaming pages."""
    value = (value or "").strip()
    if len(value) > 1000:
        return None
    if value.startswith("/static/media/") and ".." not in value and value.lower().split("?", 1)[0].endswith((".mp4", ".webm")):
        local_file = BASE_DIR / value.lstrip("/")
        return value if local_file.is_file() else None
    try:
        parsed = urllib.parse.urlparse(value)
    except ValueError:
        return None
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        return None
    if not parsed.path.lower().endswith((".mp4", ".webm")):
        return None
    return value


def get_movie_room_payload(con, code):
    room = con.execute("""SELECT r.code,r.title,r.media_url,r.playback_state,r.position,r.updated_at,
                                r.created_at,r.host_user_id,u.name AS host_name
                         FROM movie_rooms r JOIN users u ON u.id=r.host_user_id WHERE r.code=?""", (code,)).fetchone()
    if not room:
        return None
    data = dict(room)
    position = float(data["position"] or 0)
    if data["playback_state"] == "playing":
        try:
            updated = datetime.fromisoformat(data["updated_at"].replace("Z", "+00:00"))
            position += max(0, (datetime.now(timezone.utc) - updated).total_seconds())
        except (ValueError, TypeError):
            pass
    data["position"] = round(max(0, position), 2)
    return data


@app.post("/api/movie-night/create")
@logged_in
def create_movie_room():
    payload = request.get_json(silent=True) or {}
    title = str(payload.get("title", "")).strip()[:100]
    media_url = valid_movie_media_url(str(payload.get("media_url", "")))
    if not title or not media_url:
        return jsonify(error="Add a movie title and a direct HTTPS MP4/WebM link (or a file in this site's /static/media/ folder). Only use video content you own or are authorised to show."), 400
    code = None
    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    with db() as con:
        for _ in range(8):
            candidate = "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(6))
            try:
                con.execute("INSERT INTO movie_rooms(code,host_user_id,title,media_url,playback_state,position,updated_at,created_at) VALUES(?,?,?,?,?,?,?,?)",
                            (candidate, session["user_id"], title, media_url, "paused", 0, now, now))
                code = candidate
                break
            except sqlite3.IntegrityError:
                continue
    if not code:
        return jsonify(error="A room could not be created. Please try again."), 500
    return jsonify(ok=True, code=code, url=url_for("cinema", _external=False) + "?room=" + code)


@app.post("/api/movie-night/join")
@logged_in
def join_movie_room():
    payload = request.get_json(silent=True) or {}
    code = re.sub(r"[^A-Z0-9]", "", str(payload.get("code", "")).upper())[:6]
    if len(code) != 6:
        return jsonify(error="Enter the six-character room code."), 400
    with db() as con:
        room = get_movie_room_payload(con, code)
    if not room:
        return jsonify(error="That Movie Night room was not found. Check the code with the host."), 404
    return jsonify(ok=True, url=url_for("cinema", _external=False) + "?room=" + code)


@app.get("/api/movie-night/<code>")
@logged_in
def movie_room_state(code):
    code = re.sub(r"[^A-Z0-9]", "", code.upper())[:6]
    with db() as con:
        room = get_movie_room_payload(con, code)
    if not room:
        return jsonify(error="Movie Night room not found."), 404
    room["is_host"] = room["host_user_id"] == session["user_id"]
    return jsonify(room)


@app.post("/api/movie-night/<code>/control")
@logged_in
def movie_room_control(code):
    code = re.sub(r"[^A-Z0-9]", "", code.upper())[:6]
    payload = request.get_json(silent=True) or {}
    action = str(payload.get("action", ""))
    try:
        position = float(payload.get("position", 0))
    except (TypeError, ValueError):
        return jsonify(error="Invalid playback position."), 400
    if action not in {"play", "pause"} or not 0 <= position <= 60 * 60 * 12:
        return jsonify(error="Invalid playback update."), 400
    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    with db() as con:
        room = con.execute("SELECT host_user_id FROM movie_rooms WHERE code=?", (code,)).fetchone()
        if not room:
            return jsonify(error="Movie Night room not found."), 404
        if room["host_user_id"] != session["user_id"]:
            return jsonify(error="Only the room host can control playback."), 403
        state = "playing" if action == "play" else "paused"
        con.execute("UPDATE movie_rooms SET playback_state=?,position=?,updated_at=? WHERE code=?",
                    (state, position, now, code))
    return jsonify(ok=True)


@app.post("/api/movie-night/<code>/end")
@logged_in
def end_movie_room(code):
    code = re.sub(r"[^A-Z0-9]", "", code.upper())[:6]
    with db() as con:
        room = con.execute("SELECT host_user_id FROM movie_rooms WHERE code=?", (code,)).fetchone()
        if not room:
            return jsonify(error="Movie Night room not found."), 404
        if room["host_user_id"] != session["user_id"] and session.get("role") != "owner":
            return jsonify(error="Only the host or site owner can end this room."), 403
        con.execute("DELETE FROM movie_rooms WHERE code=?", (code,))
    return jsonify(ok=True)


@app.errorhandler(400)
def bad_request(_error):
    return render_template("error.html", code=400, message="The request could not be accepted. Refresh the page and try again."), 400


@app.errorhandler(403)
def forbidden(_error):
    return render_template("error.html", code=403, message="You do not have permission to open this page."), 403


@app.errorhandler(404)
def not_found(_error):
    return render_template("error.html", code=404, message="That page could not be found."), 404


if __name__ == "__main__":
    # Local Windows-friendly development server. Use a proper HTTPS host before public launch.
    app.run(host="127.0.0.1", port=int(os.getenv("PORT", "5000")), debug=False)
