import hashlib
import json
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse


ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("NESTCARE_DB", ROOT / "nestcare.sqlite3"))
HOST = os.environ.get("NESTCARE_HOST", "127.0.0.1")
PORT = int(os.environ.get("NESTCARE_PORT", os.environ.get("PORT", "8000")))
SESSION_SECONDS = 60 * 60 * 24 * 7
MAX_BODY = 64 * 1024


def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.execute("PRAGMA busy_timeout = 10000")
    return db


@contextmanager
def database():
    db = connect()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def password_hash(password, salt=None):
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 310_000)
    return salt.hex() + ":" + digest.hex()


def verify_password(password, encoded):
    try:
        salt_hex, digest_hex = encoded.split(":", 1)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), 310_000)
        return secrets.compare_digest(actual.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def initialize():
    with database() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                phone TEXT NOT NULL DEFAULT '',
                role TEXT NOT NULL CHECK(role IN ('parent','provider','admin')),
                password_hash TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','pending','rejected')),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                expires_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS centers (
                id INTEGER PRIMARY KEY,
                provider_id INTEGER NOT NULL REFERENCES users(id),
                name TEXT NOT NULL,
                city TEXT NOT NULL,
                address TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                hours TEXT NOT NULL DEFAULT 'Daytime',
                capacity INTEGER NOT NULL DEFAULT 10 CHECK(capacity > 0),
                age_groups TEXT NOT NULL DEFAULT '["Toddler","Preschool"]',
                certifications TEXT NOT NULL DEFAULT '[]',
                plans TEXT NOT NULL DEFAULT '{}',
                caregivers TEXT NOT NULL DEFAULT '[]',
                verified INTEGER NOT NULL DEFAULT 0,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS bookings (
                id INTEGER PRIMARY KEY,
                center_id INTEGER NOT NULL REFERENCES centers(id),
                parent_id INTEGER NOT NULL REFERENCES users(id),
                child_name TEXT NOT NULL,
                child_age TEXT NOT NULL,
                date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                start_time TEXT NOT NULL DEFAULT '',
                end_time TEXT NOT NULL DEFAULT '',
                plan TEXT NOT NULL CHECK(plan IN ('hourly','daily','monthly')),
                notes TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending','confirmed','rejected','cancelled')),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS subscriptions (
                id INTEGER PRIMARY KEY,
                center_id INTEGER NOT NULL REFERENCES centers(id),
                parent_id INTEGER NOT NULL REFERENCES users(id),
                child_name TEXT NOT NULL,
                child_age TEXT NOT NULL,
                start_date TEXT NOT NULL,
                plan TEXT NOT NULL DEFAULT 'monthly',
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending','active','rejected','cancelled')),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                message TEXT NOT NULL,
                read INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS disputes (
                id INTEGER PRIMARY KEY,
                booking_id INTEGER NOT NULL REFERENCES bookings(id),
                reporter_id INTEGER NOT NULL REFERENCES users(id),
                message TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','resolved')),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS app_feedback (
                id INTEGER PRIMARY KEY,
                rating INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5),
                category TEXT NOT NULL CHECK(category IN ('search','booking','provider','accessibility','other')),
                message TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS booking_center_dates ON bookings(center_id, date, end_date, status);
            CREATE INDEX IF NOT EXISTS booking_parent ON bookings(parent_id, created_at);
            CREATE INDEX IF NOT EXISTS subscription_parent ON subscriptions(parent_id, created_at);
            """
        )
        if db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
            demo_data = os.environ.get("NESTCARE_DEMO_DATA", "true").strip().lower() in ("1", "true", "yes")
            if not demo_data:
                admin_email = os.environ.get("NESTCARE_ADMIN_EMAIL", "").strip().lower()
                admin_password = os.environ.get("NESTCARE_ADMIN_PASSWORD", "")
                if "@" not in admin_email or len(admin_password) < 16:
                    raise RuntimeError(
                        "Production setup requires NESTCARE_ADMIN_EMAIL and a NESTCARE_ADMIN_PASSWORD "
                        "with at least 16 characters."
                    )
                db.execute(
                    "INSERT INTO users(name,email,role,password_hash) VALUES(?,?,?,?)",
                    ("Platform Administrator", admin_email, "admin", password_hash(admin_password)),
                )
                return
            provider_id = db.execute(
                "INSERT INTO users(name,email,phone,role,password_hash) VALUES(?,?,?,?,?)",
                ("Aarav Sharma", "provider@nestcare.local", "+91 98765 43210", "provider",
                 password_hash("NestcareProvider123!")),
            ).lastrowid
            db.execute(
                "INSERT INTO users(name,email,role,password_hash) VALUES(?,?,?,?)",
                ("Nestcare Admin", "admin@nestcare.local", "admin", password_hash("NestcareAdmin123!")),
            )
            db.execute(
                """INSERT INTO centers
                (provider_id,name,city,address,description,hours,capacity,age_groups,
                 certifications,plans,caregivers,verified)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,1)""",
                (
                    provider_id, "Little Lanterns", "Bengaluru", "Indiranagar, Bengaluru",
                    "A calm, joyful space for little ones, with attentive caregivers and a garden to explore.",
                    "Open 24 hours", 18, json.dumps(["Infant", "Toddler", "Preschool"]),
                    json.dumps(["Child-safe premises", "Staff first-aid trained", "Fire safety certificate"]),
                    json.dumps({"hourly": 180, "daily": 950, "monthly": 14500}),
                    json.dumps([
                        {"name": "Meera Iyer", "role": "Lead caregiver", "experience": "8 years"},
                        {"name": "Nisha Rao", "role": "Infant care specialist", "experience": "6 years"},
                    ]),
                ),
            )
            db.execute(
                """INSERT INTO centers
                (provider_id,name,city,address,description,hours,capacity,age_groups,
                 certifications,plans,caregivers,verified)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,1)""",
                (
                    provider_id, "The Willow Nest", "Bengaluru", "Koramangala, Bengaluru",
                    "Small-group care with thoughtfully designed play rooms and flexible evening hours.",
                    "6:00 AM – 11:00 PM", 12, json.dumps(["Toddler", "Preschool"]),
                    json.dumps(["Verified caregiver identities", "First-aid trained staff"]),
                    json.dumps({"hourly": 150, "daily": 800, "monthly": 12000}),
                    json.dumps([
                        {"name": "Ananya Das", "role": "Centre director", "experience": "10 years"},
                        {"name": "Kavita Menon", "role": "Early-years educator", "experience": "5 years"},
                    ]),
                ),
            )


def clean_user(row):
    if not row:
        return None
    return {"id": row["id"], "name": row["name"], "email": row["email"],
            "phone": row["phone"], "role": row["role"], "status": row["status"]}


def notify(db, user_id, message):
    db.execute("INSERT INTO notifications(user_id,message) VALUES(?,?)", (user_id, message))


class APIError(Exception):
    def __init__(self, status, message):
        self.status = status
        self.message = message


class Handler(BaseHTTPRequestHandler):
    server_version = "Nestcare/1.0"

    def log_message(self, fmt, *args):
        print("%s - %s" % (self.address_string(), fmt % args))

    def send_json(self, status, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_error_json(self, status, message):
        self.send_json(status, {"error": message})

    def read_json(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise APIError(400, "Invalid request size.")
        if length <= 0 or length > MAX_BODY:
            raise APIError(413 if length > MAX_BODY else 400, "Request body is missing or too large.")
        try:
            value = json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise APIError(400, "Please send valid JSON.")
        if not isinstance(value, dict):
            raise APIError(400, "Request body must be an object.")
        return value

    def current_user(self, db):
        cookie = cookies.SimpleCookie(self.headers.get("Cookie", ""))
        morsel = cookie.get("nestcare_session")
        if not morsel:
            return None
        row = db.execute(
            """SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id
               WHERE s.token=? AND s.expires_at>?""", (morsel.value, int(time.time()))
        ).fetchone()
        return clean_user(row)

    def require_user(self, db, roles=None):
        user = self.current_user(db)
        if not user:
            raise APIError(401, "Please sign in to continue.")
        if user["status"] != "active":
            raise APIError(403, "Your account is awaiting administrator verification.")
        if roles and user["role"] not in roles:
            raise APIError(403, "You do not have permission to do that.")
        return user

    def set_cookie(self, token, max_age):
        secure = "; Secure" if (
            os.environ.get("NESTCARE_SECURE_COOKIES", "").strip().lower() in ("1", "true", "yes")
            or self.headers.get("X-Forwarded-Proto") == "https"
        ) else ""
        self.send_header(
            "Set-Cookie",
            f"nestcare_session={token}; HttpOnly; SameSite=Lax; Path=/; Max-Age={max_age}{secure}",
        )

    def do_GET(self):
        parsed = urlparse(self.path)
        if not parsed.path.startswith("/api/"):
            return self.serve_static(parsed.path)
        try:
            with database() as db:
                result, status = self.route_get(db, parsed.path, parse_qs(parsed.query))
            self.send_json(status, result)
        except APIError as exc:
            self.send_error_json(exc.status, exc.message)
        except sqlite3.Error:
            self.send_error_json(500, "The database could not complete the request.")

    def do_POST(self):
        if not self.path.startswith("/api/"):
            return self.send_error_json(404, "Not found.")
        try:
            body = self.read_json()
            with database() as db:
                result, status, cookie_action = self.route_post(db, urlparse(self.path).path, body)
            if cookie_action:
                token, max_age = cookie_action
                self.send_response(status)
                self.set_cookie(token, max_age)
                response = json.dumps(result, ensure_ascii=False).encode("utf-8")
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(response)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(response)
            else:
                self.send_json(status, result)
        except APIError as exc:
            self.send_error_json(exc.status, exc.message)
        except sqlite3.IntegrityError:
            self.send_error_json(409, "That record could not be saved because it conflicts with existing data.")
        except sqlite3.Error:
            self.send_error_json(500, "The database could not complete the request.")

    def do_PATCH(self):
        try:
            body = self.read_json()
            with database() as db:
                result = self.route_patch(db, urlparse(self.path).path, body)
            self.send_json(200, result)
        except APIError as exc:
            self.send_error_json(exc.status, exc.message)
        except sqlite3.Error:
            self.send_error_json(500, "The database could not complete the request.")

    def serve_static(self, request_path):
        path = unquote(request_path)
        if path in ("", "/"):
            path = "/index.html"
        requested = (ROOT / path.lstrip("/")).resolve()
        if ROOT not in requested.parents and requested != ROOT:
            self.send_error_json(403, "Forbidden.")
            return
        if not requested.is_file():
            self.send_error_json(404, "Not found.")
            return
        content_type = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "text/javascript; charset=utf-8",
            ".svg": "image/svg+xml",
            ".webm": "video/webm",
            ".vtt": "text/vtt; charset=utf-8",
        }.get(requested.suffix.lower(), "application/octet-stream")
        body = requested.read_bytes()
        status = 200
        range_header = self.headers.get("Range")
        if range_header:
            try:
                unit, bounds = range_header.strip().split("=", 1)
                if unit != "bytes" or "," in bounds:
                    raise ValueError
                first, last = bounds.split("-", 1)
                if first:
                    start = int(first)
                    end = min(int(last), len(body) - 1) if last else len(body) - 1
                else:
                    suffix_length = int(last)
                    if suffix_length <= 0:
                        raise ValueError
                    start = max(0, len(body) - suffix_length)
                    end = len(body) - 1
                if start < 0 or start >= len(body) or end < start:
                    raise ValueError
            except ValueError:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{len(body)}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            body = body[start:end + 1]
            status = 206
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Accept-Ranges", "bytes")
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{requested.stat().st_size}")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; media-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def route_get(self, db, path, query):
        if path == "/api/health":
            db.execute("SELECT 1").fetchone()
            return {"status": "ok"}, 200
        if path == "/api/me":
            return {"user": self.current_user(db)}, 200
        if path == "/api/availability":
            center_id = query.get("centerId", [""])[0]
            date = query.get("date", [""])[0]
            plan = query.get("plan", ["daily"])[0]
            if not center_id.isdigit() or not self.valid_date(date) or date < self.today() or plan not in ("hourly", "daily", "monthly"):
                raise APIError(400, "Choose a center, valid care date, and care plan.")
            start_time = query.get("startTime", [""])[0]
            end_time = query.get("endTime", [""])[0]
            if plan == "hourly" and (
                not self.valid_time(start_time) or not self.valid_time(end_time) or start_time >= end_time
            ):
                raise APIError(400, "Choose a valid hourly time range.")
            center = db.execute(
                """SELECT c.* FROM centers c JOIN users u ON u.id=c.provider_id
                   WHERE c.id=? AND c.active=1 AND c.verified=1 AND u.status='active'""",
                (int(center_id),),
            ).fetchone()
            if not center:
                raise APIError(404, "This center is not available.")
            bookings = db.execute(
                """SELECT COUNT(*) FROM bookings WHERE center_id=? AND status IN ('pending','confirmed')
                   AND date<=? AND end_date>=?
                   AND (plan!='hourly' OR ?='' OR start_time<? OR end_time>?)""",
                (center["id"], date, date, start_time, end_time, start_time),
            ).fetchone()[0]
            subscriptions = db.execute(
                "SELECT COUNT(*) FROM subscriptions WHERE center_id=? AND status='active' AND start_date<=?",
                (center["id"], date),
            ).fetchone()[0]
            remaining = max(0, center["capacity"] - bookings - subscriptions)
            return {"available": remaining > 0, "availableSlots": remaining, "capacity": center["capacity"]}, 200
        if path == "/api/centers":
            sql = """SELECT c.* FROM centers c JOIN users u ON u.id=c.provider_id
                     WHERE c.active=1 AND c.verified=1 AND u.status='active'"""
            args = []
            if query.get("city", [""])[0].strip():
                sql += " AND city LIKE ?"
                args.append("%" + query["city"][0].strip()[:80] + "%")
            if query.get("age", [""])[0] in ("Infant", "Toddler", "Preschool"):
                sql += " AND age_groups LIKE ?"
                args.append('%"' + query["age"][0] + '"%')
            if query.get("hours", [""])[0] == "24":
                sql += " AND hours LIKE '%24%'"
            rows = db.execute(sql + " ORDER BY name", args).fetchall()
            return {"centers": [self.center_json(row) for row in rows]}, 200
        if path.startswith("/api/centers/"):
            center_id = self.path_id(path, "/api/centers/")
            row = db.execute(
                """SELECT c.* FROM centers c JOIN users u ON u.id=c.provider_id
                   WHERE c.id=? AND c.active=1 AND c.verified=1 AND u.status='active'""",
                (center_id,),
            ).fetchone()
            if not row:
                raise APIError(404, "This center is not available.")
            return {"center": self.center_json(row)}, 200
        if path == "/api/bookings":
            user = self.require_user(db)
            if user["role"] == "provider":
                rows = db.execute(
                    """SELECT b.*,c.name AS center_name,c.provider_id,u.name AS parent_name
                       FROM bookings b JOIN centers c ON c.id=b.center_id
                       JOIN users u ON u.id=b.parent_id WHERE c.provider_id=?
                       ORDER BY b.created_at DESC""", (user["id"],)
                ).fetchall()
            elif user["role"] == "admin":
                rows = db.execute(
                    """SELECT b.*,c.name AS center_name,c.provider_id,u.name AS parent_name
                       FROM bookings b JOIN centers c ON c.id=b.center_id
                       JOIN users u ON u.id=b.parent_id ORDER BY b.created_at DESC"""
                ).fetchall()
            else:
                rows = db.execute(
                    """SELECT b.*,c.name AS center_name,u.name AS parent_name
                       FROM bookings b JOIN centers c ON c.id=b.center_id
                       JOIN users u ON u.id=b.parent_id WHERE b.parent_id=?
                       ORDER BY b.created_at DESC""", (user["id"],)
                ).fetchall()
            return {"bookings": [dict(row) for row in rows]}, 200
        if path == "/api/subscriptions":
            user = self.require_user(db)
            if user["role"] == "provider":
                rows = db.execute(
                    """SELECT s.*,c.name AS center_name,u.name AS parent_name,c.provider_id
                       FROM subscriptions s JOIN centers c ON c.id=s.center_id
                       JOIN users u ON u.id=s.parent_id WHERE c.provider_id=?
                       ORDER BY s.created_at DESC""", (user["id"],)
                ).fetchall()
            elif user["role"] == "admin":
                rows = db.execute(
                    """SELECT s.*,c.name AS center_name,u.name AS parent_name,c.provider_id
                       FROM subscriptions s JOIN centers c ON c.id=s.center_id
                       JOIN users u ON u.id=s.parent_id ORDER BY s.created_at DESC"""
                ).fetchall()
            else:
                rows = db.execute(
                    """SELECT s.*,c.name AS center_name,u.name AS parent_name
                       FROM subscriptions s JOIN centers c ON c.id=s.center_id
                       JOIN users u ON u.id=s.parent_id WHERE s.parent_id=?
                       ORDER BY s.created_at DESC""", (user["id"],)
                ).fetchall()
            return {"subscriptions": [dict(row) for row in rows]}, 200
        if path == "/api/notifications":
            user = self.require_user(db)
            rows = db.execute(
                "SELECT * FROM notifications WHERE user_id=? ORDER BY created_at DESC LIMIT 50",
                (user["id"],),
            ).fetchall()
            return {"notifications": [dict(row) for row in rows]}, 200
        if path == "/api/provider/center":
            user = self.require_user(db, ["provider"])
            row = db.execute("SELECT * FROM centers WHERE provider_id=? ORDER BY id LIMIT 1", (user["id"],)).fetchone()
            return {"center": self.center_json(row) if row else None}, 200
        if path == "/api/provider/analytics":
            user = self.require_user(db, ["provider"])
            center = db.execute("SELECT id,capacity FROM centers WHERE provider_id=? ORDER BY id LIMIT 1", (user["id"],)).fetchone()
            if not center:
                return {"centers": 0, "bookings": 0, "pending": 0, "utilization": 0}, 200
            counts = db.execute(
                "SELECT COUNT(*) AS total,SUM(status='pending') AS pending,SUM(status='confirmed') AS confirmed FROM bookings WHERE center_id=?",
                (center["id"],),
            ).fetchone()
            return {"centers": 1, "bookings": counts["total"], "pending": counts["pending"] or 0,
                    "utilization": min(100, round((counts["confirmed"] or 0) * 100 / center["capacity"]))}, 200
        if path == "/api/admin/overview":
            self.require_user(db, ["admin"])
            stats = {
                "parents": db.execute("SELECT COUNT(*) FROM users WHERE role='parent'").fetchone()[0],
                "providers": db.execute("SELECT COUNT(*) FROM users WHERE role='provider' AND status='active'").fetchone()[0],
                "pending": db.execute("SELECT COUNT(*) FROM users WHERE status='pending'").fetchone()[0]
                           + db.execute("SELECT COUNT(*) FROM centers WHERE verified=0").fetchone()[0],
                "bookings": db.execute("SELECT COUNT(*) FROM bookings").fetchone()[0],
            }
            users = db.execute("SELECT id,name,email,role,status,created_at FROM users WHERE role!='admin' ORDER BY created_at DESC").fetchall()
            centers = db.execute(
                """SELECT c.*,u.name AS provider_name FROM centers c JOIN users u ON u.id=c.provider_id
                   ORDER BY c.verified ASC,c.created_at DESC"""
            ).fetchall()
            disputes = db.execute(
                """SELECT d.*,b.child_name,b.date,c.name AS center_name,u.name AS reporter_name
                   FROM disputes d JOIN bookings b ON b.id=d.booking_id
                   JOIN centers c ON c.id=b.center_id JOIN users u ON u.id=d.reporter_id
                   ORDER BY d.status ASC,d.created_at DESC"""
            ).fetchall()
            feedback = db.execute(
                "SELECT id,rating,category,message,created_at FROM app_feedback ORDER BY created_at DESC LIMIT 100"
            ).fetchall()
            return {"stats": stats, "users": [dict(x) for x in users],
                    "centers": [self.center_json(x) | {"provider_name": x["provider_name"]} for x in centers],
                    "disputes": [dict(x) for x in disputes],
                    "feedback": [dict(x) for x in feedback]}, 200
        raise APIError(404, "Not found.")

    @staticmethod
    def center_json(row):
        return {
            "id": row["id"], "provider_id": row["provider_id"], "name": row["name"],
            "city": row["city"], "address": row["address"], "description": row["description"],
            "hours": row["hours"], "capacity": row["capacity"],
            "age_groups": json.loads(row["age_groups"]), "certifications": json.loads(row["certifications"]),
            "plans": json.loads(row["plans"]), "caregivers": json.loads(row["caregivers"]),
            "verified": bool(row["verified"]), "active": bool(row["active"]),
        }

    def route_post(self, db, path, body):
        if path == "/api/feedback":
            rating = self.number(body, "rating", 1, 5)
            category = self.text(body, "category", 20)
            message = body.get("message", "")
            if category not in ("search", "booking", "provider", "accessibility", "other"):
                raise APIError(400, "Choose a feedback topic.")
            if not isinstance(message, str) or not 10 <= len(message.strip()) <= 1200:
                raise APIError(400, "Feedback must be between 10 and 1,200 characters.")
            cursor = db.execute(
                "INSERT INTO app_feedback(rating,category,message) VALUES(?,?,?)",
                (rating, category, message.strip()),
            )
            return {"message": "Thank you for helping us improve Nestcare.", "feedbackId": cursor.lastrowid}, 201, None
        if path == "/api/register":
            name, email = self.text(body, "name", 100), self.text(body, "email", 254).lower()
            password = body.get("password", "")
            role = body.get("role", "parent")
            if role not in ("parent", "provider"):
                raise APIError(400, "Choose a parent or provider account.")
            if not name or "@" not in email or len(password) < 10:
                raise APIError(400, "Enter your name, a valid email, and a password of at least 10 characters.")
            if role == "provider" and not all(self.text(body, key, 100) for key in ("centerName", "city", "address")):
                raise APIError(400, "Provider registration requires a center name, city, and address.")
            if not isinstance(password, str) or not 10 <= len(password) <= 128:
                raise APIError(400, "Use a password between 10 and 128 characters.")
            status = "pending"
            cursor = db.execute(
                "INSERT INTO users(name,email,phone,role,password_hash,status) VALUES(?,?,?,?,?,?)",
                (name, email, self.text(body, "phone", 30), role, password_hash(password), status),
            )
            user_id = cursor.lastrowid
            if role == "provider":
                db.execute(
                    """INSERT INTO centers(provider_id,name,city,address,description,hours,capacity,age_groups,
                       certifications,plans,caregivers,verified) VALUES(?,?,?,?,?,?,?,?,?,?,?,0)""",
                    (user_id, self.text(body, "centerName", 120), self.text(body, "city", 100),
                     self.text(body, "address", 200), self.text(body, "description", 1000),
                     self.text(body, "hours", 80) or "Daytime", self.number(body, "capacity", 1, 1000, 12),
                     json.dumps(body.get("ageGroups", ["Toddler", "Preschool"])),
                     json.dumps(self.list_text(body.get("certifications", []), 10, 100)),
                     json.dumps({"hourly": 150, "daily": 800, "monthly": 12000}),
                     json.dumps([])),
                )
                admin_ids = db.execute("SELECT id FROM users WHERE role='admin'").fetchall()
                for admin in admin_ids:
                    notify(db, admin["id"], f"New childcare provider application: {self.text(body, 'centerName', 120)}.")
                return {"message": "Application received. An administrator will verify your center.",
                        "user": clean_user(db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone())}, 201, None
            token = secrets.token_urlsafe(32)
            db.execute("INSERT INTO sessions(token,user_id,expires_at) VALUES(?,?,?)",
                       (token, user_id, int(time.time()) + SESSION_SECONDS))
            for admin in db.execute("SELECT id FROM users WHERE role='admin'").fetchall():
                notify(db, admin["id"], f"New parent account application: {name}.")
            return {"message": "Account created. An administrator will verify it before you can request care.",
                    "user": clean_user(db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone())}, 201, (token, SESSION_SECONDS)

        if path == "/api/login":
            email = self.text(body, "email", 254).lower()
            row = db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
            password = body.get("password", "")
            if not row or not isinstance(password, str) or len(password) > 128 or not verify_password(password, row["password_hash"]):
                raise APIError(401, "Email or password is incorrect.")
            if row["status"] == "rejected":
                raise APIError(403, "This account is not approved. Please contact support.")
            token = secrets.token_urlsafe(32)
            db.execute("INSERT INTO sessions(token,user_id,expires_at) VALUES(?,?,?)",
                       (token, row["id"], int(time.time()) + SESSION_SECONDS))
            return {"user": clean_user(row)}, 200, (token, SESSION_SECONDS)

        if path == "/api/logout":
            cookie = cookies.SimpleCookie(self.headers.get("Cookie", ""))
            morsel = cookie.get("nestcare_session")
            if morsel:
                db.execute("DELETE FROM sessions WHERE token=?", (morsel.value,))
            return {"message": "Signed out."}, 200, ("", 0)

        if path == "/api/bookings":
            user = self.require_user(db, ["parent"])
            center_id = self.number(body, "centerId", 1, 2_000_000_000)
            center = db.execute("SELECT * FROM centers WHERE id=? AND verified=1 AND active=1", (center_id,)).fetchone()
            if not center:
                raise APIError(404, "This center is no longer available.")
            child_name = self.text(body, "childName", 100)
            age = self.text(body, "childAge", 20)
            plan = body.get("plan")
            date = self.text(body, "date", 10)
            if not child_name or age not in ("Infant", "Toddler", "Preschool") or plan not in ("hourly", "daily"):
                raise APIError(400, "Enter the child’s name and age group, and choose an hourly or daily booking.")
            if age not in json.loads(center["age_groups"]):
                raise APIError(400, "This center does not currently care for that age group.")
            if not self.valid_date(date) or date < self.today():
                raise APIError(400, "Choose a valid care date that is today or later.")
            start_time = self.text(body, "startTime", 5)
            end_time = self.text(body, "endTime", 5)
            if plan == "hourly":
                if not self.valid_time(start_time) or not self.valid_time(end_time) or start_time >= end_time:
                    raise APIError(400, "Choose a valid hourly time range.")
                end_date = date
            else:
                end_date = date
                start_time = ""
                end_time = ""
            db.execute("BEGIN IMMEDIATE")
            overlaps = db.execute(
                """SELECT COUNT(*) FROM bookings WHERE center_id=? AND status IN ('pending','confirmed')
                   AND date<=? AND end_date>=?
                   AND (plan!='hourly' OR ?='' OR start_time<? OR end_time>?)""",
                (center_id, end_date, date, start_time, end_time, start_time),
            ).fetchone()[0]
            active_subscriptions = db.execute(
                "SELECT COUNT(*) FROM subscriptions WHERE center_id=? AND status='active' AND start_date<=?",
                (center_id, date),
            ).fetchone()[0]
            if overlaps + active_subscriptions >= center["capacity"]:
                raise APIError(409, "This slot is full. Please choose another date or center.")
            cursor = db.execute(
                """INSERT INTO bookings(center_id,parent_id,child_name,child_age,date,end_date,start_time,
                   end_time,plan,notes) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (center_id, user["id"], child_name, age, date, end_date, start_time, end_time, plan,
                 self.text(body, "notes", 500)),
            )
            notify(db, center["provider_id"], f"New {plan} booking request for {child_name}.")
            return {"message": "Booking request sent. The center will confirm your request.",
                    "bookingId": cursor.lastrowid}, 201, None

        if path == "/api/subscriptions":
            user = self.require_user(db, ["parent"])
            center_id = self.number(body, "centerId", 1, 2_000_000_000)
            center = db.execute("SELECT * FROM centers WHERE id=? AND verified=1 AND active=1", (center_id,)).fetchone()
            age, child = self.text(body, "childAge", 20), self.text(body, "childName", 100)
            if not center or not child or age not in ("Infant", "Toddler", "Preschool"):
                raise APIError(400, "Choose an available center and enter the child’s details.")
            if age not in json.loads(center["age_groups"]):
                raise APIError(400, "This center does not currently care for that age group.")
            start_date = self.text(body, "startDate", 10)
            if not self.valid_date(start_date) or start_date < self.today():
                raise APIError(400, "Choose a valid start date that is today or later.")
            cursor = db.execute(
                "INSERT INTO subscriptions(center_id,parent_id,child_name,child_age,start_date) VALUES(?,?,?,?,?)",
                (center_id, user["id"], child, age, start_date),
            )
            notify(db, center["provider_id"], f"New monthly care request for {child}.")
            return {"message": "Monthly care request sent to the center.", "subscriptionId": cursor.lastrowid}, 201, None

        if path == "/api/notifications/read":
            user = self.require_user(db)
            db.execute("UPDATE notifications SET read=1 WHERE user_id=?", (user["id"],))
            return {"message": "Notifications marked as read."}, 200, None
        if path == "/api/disputes":
            user = self.require_user(db, ["parent"])
            booking_id = self.number(body, "bookingId", 1, 2_000_000_000)
            message = self.text(body, "message", 1000)
            booking = db.execute("SELECT * FROM bookings WHERE id=? AND parent_id=?", (booking_id, user["id"])).fetchone()
            if not booking:
                raise APIError(404, "Booking not found.")
            if not message:
                raise APIError(400, "Please describe your concern.")
            db.execute("INSERT INTO disputes(booking_id,reporter_id,message) VALUES(?,?,?)",
                       (booking_id, user["id"], message))
            for admin in db.execute("SELECT id FROM users WHERE role='admin'").fetchall():
                notify(db, admin["id"], f"A family reported a concern about booking #{booking_id}.")
            return {"message": "Your concern was sent to our admin team."}, 201, None
        raise APIError(404, "Not found.")

    def route_patch(self, db, path, body):
        user = self.require_user(db)
        if path.startswith("/api/bookings/"):
            booking_id = self.path_id(path, "/api/bookings/")
            status = body.get("status")
            if status not in ("confirmed", "rejected", "cancelled"):
                raise APIError(400, "Choose a valid booking status.")
            booking = db.execute(
                """SELECT b.*,c.provider_id,c.capacity FROM bookings b JOIN centers c ON c.id=b.center_id
                   WHERE b.id=?""", (booking_id,)
            ).fetchone()
            if not booking:
                raise APIError(404, "Booking not found.")
            if user["role"] == "parent":
                if booking["parent_id"] != user["id"] or status != "cancelled" or booking["status"] not in ("pending", "confirmed"):
                    raise APIError(403, "You can only cancel your own active booking requests.")
            elif user["role"] not in ("provider", "admin"):
                raise APIError(403, "You do not have permission to manage bookings.")
            if user["role"] == "provider" and booking["provider_id"] != user["id"]:
                raise APIError(403, "You can only manage bookings for your own center.")
            if user["role"] == "provider" and booking["status"] != "pending" and status != "cancelled":
                raise APIError(409, "Only pending bookings can be accepted or declined.")
            if status == "confirmed":
                db.execute("BEGIN IMMEDIATE")
                confirmed = db.execute(
                    """SELECT COUNT(*) FROM bookings WHERE center_id=? AND status='confirmed'
                       AND date<=? AND end_date>=?
                       AND (plan!='hourly' OR ?='' OR start_time<? OR end_time>?)""",
                    (booking["center_id"], booking["end_date"], booking["date"],
                     booking["start_time"], booking["end_time"], booking["start_time"]),
                ).fetchone()[0]
                if confirmed >= booking["capacity"]:
                    raise APIError(409, "Capacity is full. This booking cannot be confirmed.")
            db.execute("UPDATE bookings SET status=? WHERE id=?", (status, booking_id))
            notify(db, booking["parent_id"], f"Your booking request is {status}.")
            if user["role"] == "parent":
                notify(db, booking["provider_id"], f"A family cancelled a booking request for {booking['child_name']}.")
            return {"message": f"Booking {status}."}
        if path.startswith("/api/subscriptions/"):
            sub_id = self.path_id(path, "/api/subscriptions/")
            status = body.get("status")
            if status not in ("active", "rejected", "cancelled"):
                raise APIError(400, "Choose a valid subscription status.")
            sub = db.execute(
                """SELECT s.*,c.provider_id FROM subscriptions s JOIN centers c ON c.id=s.center_id WHERE s.id=?""",
                (sub_id,),
            ).fetchone()
            if not sub:
                raise APIError(404, "Subscription not found.")
            if user["role"] == "parent":
                if sub["parent_id"] != user["id"] or status != "cancelled" or sub["status"] not in ("pending", "active"):
                    raise APIError(403, "You can only cancel your own active monthly care requests.")
            elif user["role"] not in ("provider", "admin"):
                raise APIError(403, "You do not have permission to manage subscriptions.")
            if user["role"] == "provider" and sub["provider_id"] != user["id"]:
                raise APIError(403, "You can only manage subscriptions for your own center.")
            if user["role"] == "provider" and sub["status"] != "pending" and status != "cancelled":
                raise APIError(409, "Only pending monthly care requests can be accepted or declined.")
            if status == "active" and sub["status"] != "active":
                db.execute("BEGIN IMMEDIATE")
                occupied = db.execute(
                    """SELECT
                       (SELECT COUNT(*) FROM subscriptions WHERE center_id=? AND status='active'
                        AND start_date<=? AND id!=?)
                       +
                       (SELECT COUNT(*) FROM bookings WHERE center_id=? AND status='confirmed'
                        AND date<=? AND end_date>=?)""",
                    (sub["center_id"], sub["start_date"], sub_id,
                     sub["center_id"], sub["start_date"], sub["start_date"]),
                ).fetchone()[0]
                capacity = db.execute("SELECT capacity FROM centers WHERE id=?", (sub["center_id"],)).fetchone()[0]
                if occupied >= capacity:
                    raise APIError(409, "Capacity is full for that monthly care start date.")
            db.execute("UPDATE subscriptions SET status=? WHERE id=?", (status, sub_id))
            notify(db, sub["parent_id"], f"Your monthly care request is {status}.")
            return {"message": f"Monthly care request {status}."}
        if path == "/api/provider/center":
            if user["role"] != "provider":
                raise APIError(403, "Only providers can edit center details.")
            row = db.execute("SELECT * FROM centers WHERE provider_id=? ORDER BY id LIMIT 1", (user["id"],)).fetchone()
            if not row:
                raise APIError(404, "Center not found.")
            age_groups = body.get("ageGroups", json.loads(row["age_groups"]))
            if not isinstance(age_groups, list) or not age_groups or any(x not in ("Infant", "Toddler", "Preschool") for x in age_groups):
                raise APIError(400, "Select one or more valid age groups.")
            caregivers = body.get("caregivers", json.loads(row["caregivers"]))
            if not isinstance(caregivers, list) or any(
                not isinstance(item, dict) or not all(
                    isinstance(item.get(key), str) and item[key].strip() for key in ("name", "role", "experience")
                ) for item in caregivers
            ):
                raise APIError(400, "Enter a caregiver name, role, and experience for each profile.")
            caregivers = [
                {"name": item["name"].strip()[:100], "role": item["role"].strip()[:100],
                 "experience": item["experience"].strip()[:80]}
                for item in caregivers[:30]
            ]
            plans = body.get("plans", json.loads(row["plans"]))
            if not isinstance(plans, dict):
                raise APIError(400, "Enter valid pricing plans.")
            for key in ("hourly", "daily", "monthly"):
                value = plans.get(key)
                if not isinstance(value, int) or value < 0 or value > 10_000_000:
                    raise APIError(400, "Enter a non-negative whole-number price for each plan.")
            db.execute(
                """UPDATE centers SET description=?,hours=?,capacity=?,age_groups=?,certifications=?,plans=?,
                   caregivers=? WHERE id=?""",
                (self.text(body, "description", 1000), self.text(body, "hours", 80),
                 self.number(body, "capacity", 1, 1000), json.dumps(age_groups),
                 json.dumps(self.list_text(body.get("certifications", []), 10, 100)),
                 json.dumps(plans), json.dumps(caregivers), row["id"]),
            )
            return {"message": "Center details updated."}
        if user["role"] != "admin":
            raise APIError(403, "You do not have permission to do that.")
        if path.startswith("/api/admin/users/"):
            target_id = self.path_id(path, "/api/admin/users/")
            status = body.get("status")
            if status not in ("active", "rejected"):
                raise APIError(400, "Choose approve or reject for this account.")
            target = db.execute("SELECT * FROM users WHERE id=? AND role!='admin'", (target_id,)).fetchone()
            if not target:
                raise APIError(404, "Account not found.")
            db.execute("UPDATE users SET status=? WHERE id=?", (status, target_id))
            if status == "active":
                notify(db, target_id, "Your Nestcare account has been approved.")
            return {"message": f"Account {status}."}
        if path.startswith("/api/admin/centers/"):
            center_id = self.path_id(path, "/api/admin/centers/")
            approved = body.get("verified")
            if not isinstance(approved, bool):
                raise APIError(400, "Choose whether to approve this center.")
            center = db.execute("SELECT * FROM centers WHERE id=?", (center_id,)).fetchone()
            if not center:
                raise APIError(404, "Center not found.")
            db.execute("UPDATE centers SET verified=? WHERE id=?", (int(approved), center_id))
            status = "verified" if approved else "not approved"
            notify(db, center["provider_id"], f"Your center “{center['name']}” is {status}.")
            return {"message": f"Center {status}."}
        if path.startswith("/api/admin/disputes/"):
            dispute_id = self.path_id(path, "/api/admin/disputes/")
            status = body.get("status")
            if status not in ("open", "resolved"):
                raise APIError(400, "Choose open or resolved.")
            dispute = db.execute("SELECT * FROM disputes WHERE id=?", (dispute_id,)).fetchone()
            if not dispute:
                raise APIError(404, "Concern not found.")
            db.execute("UPDATE disputes SET status=? WHERE id=?", (status, dispute_id))
            notify(db, dispute["reporter_id"], f"Your reported concern is now {status}.")
            return {"message": f"Concern marked {status}."}
        raise APIError(404, "Not found.")

    @staticmethod
    def text(body, key, limit):
        value = body.get(key, "")
        return value.strip()[:limit] if isinstance(value, str) else ""

    @staticmethod
    def number(body, key, minimum, maximum, default=None):
        value = body.get(key, default)
        if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
            raise APIError(400, f"Enter a valid {key.replace('_', ' ')}.")
        return value

    @staticmethod
    def list_text(value, limit, item_limit):
        if not isinstance(value, list):
            return []
        return [item.strip()[:item_limit] for item in value[:limit] if isinstance(item, str) and item.strip()]

    @staticmethod
    def path_id(path, prefix):
        suffix = path[len(prefix):]
        if not suffix.isdigit():
            raise APIError(400, "Invalid record ID.")
        return int(suffix)

    @staticmethod
    def valid_time(value):
        if not isinstance(value, str) or len(value) != 5 or value[2] != ":":
            return False
        try:
            hour, minute = map(int, value.split(":"))
            return 0 <= hour <= 23 and 0 <= minute <= 59
        except ValueError:
            return False

    @staticmethod
    def valid_date(value):
        from datetime import date
        try:
            date.fromisoformat(value)
            return True
        except (ValueError, TypeError):
            return False

    @staticmethod
    def today():
        from datetime import date
        return date.today().isoformat()


def main():
    initialize()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Nestcare is ready at http://{HOST}:{PORT}")
    print("Demo admin: admin@nestcare.local / NestcareAdmin123!")
    print("Demo provider: provider@nestcare.local / NestcareProvider123!")
    print(f"Database: {DB_PATH}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Nestcare.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
