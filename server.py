import os
import sqlite3
import secrets
import hashlib
import hmac
import datetime
import urllib.parse
from functools import wraps

from flask import Flask, request, jsonify, g, send_from_directory

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.getenv("DB_PATH", os.path.join(APP_DIR, "dutchpay.db"))
API_BASE_URL = os.getenv("API_BASE_URL", "http://192.168.1.16:5000").rstrip("/")
WEB_URL = os.getenv("WEB_URL", API_BASE_URL + "/")
WEBHOOK_SECRET = os.getenv("DUTCHPAY_WEBHOOK_SECRET", "change-this-secret")
PORT = int(os.getenv("PORT", "5000"))

app = Flask(__name__)


@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-DutchPay-Secret"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response


@app.route("/", methods=["GET"])
def web_index():
    return send_from_directory(APP_DIR, "index.html")


def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_error=None):
    conn = g.pop("db", None)
    if conn:
        conn.close()


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT NOT NULL UNIQUE COLLATE NOCASE,
        password_hash TEXT NOT NULL,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS sessions (
        token TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS friends (
        user_id INTEGER NOT NULL,
        friend_id INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        PRIMARY KEY(user_id, friend_id),
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY(friend_id) REFERENCES users(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS settlements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        owner_id INTEGER NOT NULL,
        public_token TEXT NOT NULL UNIQUE,
        bank TEXT NOT NULL,
        account TEXT NOT NULL,
        total_amount INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(owner_id) REFERENCES users(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS settlement_participants (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        settlement_id INTEGER NOT NULL,
        user_id INTEGER,
        name TEXT NOT NULL,
        amount INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        paid_at TEXT,
        transaction_id TEXT,
        FOREIGN KEY(settlement_id) REFERENCES settlements(id) ON DELETE CASCADE,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE SET NULL
    );

    CREATE TABLE IF NOT EXISTS receipts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        settlement_id INTEGER NOT NULL,
        receipt_index INTEGER NOT NULL,
        total_amount INTEGER NOT NULL,
        items_json TEXT NOT NULL,
        FOREIGN KEY(settlement_id) REFERENCES settlements(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        kind TEXT NOT NULL,
        title TEXT NOT NULL,
        message TEXT NOT NULL,
        settlement_id INTEGER,
        read INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );
    """)
    conn.commit()
    conn.close()


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def hash_password(password, salt=None):
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 210_000)
    return salt.hex() + ":" + digest.hex()


def verify_password(password, stored):
    try:
        salt_hex, digest_hex = stored.split(":", 1)
        candidate = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), 210_000
        ).hex()
        return hmac.compare_digest(candidate, digest_hex)
    except Exception:
        return False


def current_user():
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    token = auth[7:].strip()
    row = db().execute("""
        SELECT u.* FROM users u
        JOIN sessions s ON s.user_id = u.id
        WHERE s.token = ?
    """, (token,)).fetchone()
    return row


def login_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        user = current_user()
        if not user:
            return jsonify({"error": "로그인이 필요합니다."}), 401
        g.current_user = user
        return fn(*args, **kwargs)
    return wrapped


def public_settlement(token):
    row = db().execute("""
        SELECT s.*, u.name AS owner_name
        FROM settlements s JOIN users u ON u.id = s.owner_id
        WHERE s.public_token = ?
    """, (token,)).fetchone()
    return row


def settlement_json(settlement_id, owner_id=None):
    params = [settlement_id]
    sql = """
    SELECT sp.id, sp.user_id, sp.name, sp.amount, sp.status,
           sp.paid_at, sp.transaction_id, s.owner_id, s.bank, s.account,
           s.total_amount, s.public_token, s.created_at
    FROM settlement_participants sp
    JOIN settlements s ON s.id = sp.settlement_id
    WHERE sp.settlement_id = ?
    """
    if owner_id is not None:
        sql += " AND s.owner_id = ?"
        params.append(owner_id)

    rows = db().execute(sql, params).fetchall()
    if not rows:
        return None

    head = rows[0]
    receipts = db().execute("""
        SELECT receipt_index, total_amount, items_json
        FROM receipts WHERE settlement_id = ?
        ORDER BY receipt_index
    """, (settlement_id,)).fetchall()

    import json
    return {
        "id": settlement_id,
        "owner_id": head["owner_id"],
        "owner_name": db().execute("SELECT name FROM users WHERE id=?", (head["owner_id"],)).fetchone()["name"],
        "bank": head["bank"],
        "account": head["account"],
        "total_amount": head["total_amount"],
        "public_token": head["public_token"],
        "share_url": WEB_URL + "?token=" + head["public_token"] + "&api=" + urllib.parse.quote(API_BASE_URL, safe=""),
        "created_at": head["created_at"],
        "participants": [
            {
                "id": r["id"],
                "user_id": r["user_id"],
                "name": r["name"],
                "amount": r["amount"],
                "status": r["status"],
                "paid_at": r["paid_at"],
                "transaction_id": r["transaction_id"],
            } for r in rows
        ],
        "receipts": [
            {
                "index": r["receipt_index"],
                "total_amount": r["total_amount"],
                "items": json.loads(r["items_json"]),
            } for r in receipts
        ],
    }


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"ok": True})


@app.route("/api/auth/register", methods=["POST"])
def register():
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))

    if not name or not email or not password:
        return jsonify({"error": "이름, 이메일, 비밀번호를 입력해 주세요."}), 400
    if len(password) < 6:
        return jsonify({"error": "비밀번호는 6자 이상이어야 합니다."}), 400

    try:
        conn = db()
        cur = conn.execute(
            "INSERT INTO users(name,email,password_hash,created_at) VALUES(?,?,?,?)",
            (name, email, hash_password(password), now()),
        )
        conn.commit()
        user_id = cur.lastrowid
    except sqlite3.IntegrityError:
        return jsonify({"error": "이미 가입된 이메일입니다."}), 409

    return jsonify({"id": user_id, "name": name, "email": email}), 201


@app.route("/api/auth/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))

    user = db().execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    if not user or not verify_password(password, user["password_hash"]):
        return jsonify({"error": "이메일 또는 비밀번호가 일치하지 않습니다."}), 401

    token = secrets.token_urlsafe(32)
    db().execute("INSERT INTO sessions(token,user_id,created_at) VALUES(?,?,?)",
                 (token, user["id"], now()))
    db().commit()
    return jsonify({
        "token": token,
        "user": {"id": user["id"], "name": user["name"], "email": user["email"]},
    })


@app.route("/api/auth/logout", methods=["POST"])
@login_required
def logout():
    auth = request.headers.get("Authorization", "")
    token = auth[7:].strip()
    db().execute("DELETE FROM sessions WHERE token = ?", (token,))
    db().commit()
    return jsonify({"ok": True})


@app.route("/api/me", methods=["GET"])
@login_required
def me():
    u = g.current_user
    return jsonify({"id": u["id"], "name": u["name"], "email": u["email"]})


@app.route("/api/friends", methods=["GET"])
@login_required
def friends_list():
    rows = db().execute("""
        SELECT u.id, u.name, u.email
        FROM friends f JOIN users u ON u.id = f.friend_id
        WHERE f.user_id = ?
        ORDER BY u.name COLLATE NOCASE
    """, (g.current_user["id"],)).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/friends/add", methods=["POST"])
@login_required
def friends_add():
    data = request.get_json(silent=True) or {}
    value = str(data.get("email_or_name", "")).strip()
    if not value:
        return jsonify({"error": "친구의 이메일 또는 이름을 입력해 주세요."}), 400

    friend = db().execute("""
        SELECT * FROM users
        WHERE email = ? COLLATE NOCASE OR name = ? COLLATE NOCASE
        LIMIT 1
    """, (value, value)).fetchone()

    if not friend:
        return jsonify({"error": "가입된 사용자를 찾을 수 없습니다."}), 404
    if friend["id"] == g.current_user["id"]:
        return jsonify({"error": "본인은 친구로 추가할 수 없습니다."}), 400

    conn = db()
    conn.execute("INSERT OR IGNORE INTO friends(user_id,friend_id,created_at) VALUES(?,?,?)",
                 (g.current_user["id"], friend["id"], now()))
    conn.execute("INSERT OR IGNORE INTO friends(user_id,friend_id,created_at) VALUES(?,?,?)",
                 (friend["id"], g.current_user["id"], now()))
    conn.commit()
    return jsonify({"id": friend["id"], "name": friend["name"], "email": friend["email"]}), 201


@app.route("/api/settlements", methods=["POST"])
@login_required
def create_settlement():
    import json
    data = request.get_json(silent=True) or {}
    bank = str(data.get("bank", "")).strip()
    account = str(data.get("account", "")).strip()
    participants = data.get("participants") or []
    receipts = data.get("receipts") or []

    if not bank or not account:
        return jsonify({"error": "입금 계좌 정보가 필요합니다."}), 400
    if not participants:
        return jsonify({"error": "참여자가 필요합니다."}), 400
    if not receipts:
        return jsonify({"error": "영수증이 필요합니다."}), 400

    public_token = secrets.token_urlsafe(18)
    total_amount = sum(int(r.get("total_amount", 0)) for r in receipts)

    conn = db()
    cur = conn.execute("""
        INSERT INTO settlements(owner_id,public_token,bank,account,total_amount,created_at)
        VALUES(?,?,?,?,?,?)
    """, (g.current_user["id"], public_token, bank, account, total_amount, now()))
    settlement_id = cur.lastrowid

    for receipt_index, receipt in enumerate(receipts, 1):
        conn.execute("""
            INSERT INTO receipts(settlement_id,receipt_index,total_amount,items_json)
            VALUES(?,?,?,?)
        """, (
            settlement_id,
            receipt_index,
            int(receipt.get("total_amount", 0)),
            json.dumps(receipt.get("items", []), ensure_ascii=False),
        ))

    for p in participants:
        name = str(p.get("name", "")).strip()
        amount = int(p.get("amount", 0))
        user_id = p.get("user_id")
        if name and amount > 0:
            conn.execute("""
                INSERT INTO settlement_participants
                (settlement_id,user_id,name,amount,status)
                VALUES(?,?,?,?, 'pending')
            """, (settlement_id, user_id, name, amount))

            if user_id:
                conn.execute("""
                    INSERT INTO notifications(user_id,kind,title,message,settlement_id,created_at)
                    VALUES(?,?,?,?,?,?)
                """, (
                    user_id, "settlement_request", "새 정산 요청",
                    f"{g.current_user['name']}님이 {amount:,}원 정산을 요청했습니다.",
                    settlement_id, now()
                ))

    conn.commit()
    payload = settlement_json(settlement_id, g.current_user["id"])
    payload["share_url"] = WEB_URL + "?token=" + public_token + "&api=" + urllib.parse.quote(API_BASE_URL, safe="")
    return jsonify(payload), 201


@app.route("/api/settlements/<int:settlement_id>", methods=["GET"])
@login_required
def settlement_owner_view(settlement_id):
    payload = settlement_json(settlement_id, g.current_user["id"])
    if payload is None:
        return jsonify({"error": "정산 내역을 찾을 수 없습니다."}), 404
    return jsonify(payload)


@app.route("/api/public/settlements/<token>", methods=["GET"])
def public_settlement_view(token):
    row = public_settlement(token)
    if not row:
        return jsonify({"error": "정산 링크가 유효하지 않습니다."}), 404
    payload = settlement_json(row["id"])
    return jsonify(payload)


@app.route("/api/payments/webhook", methods=["POST"])
def payment_webhook():
    signature = request.headers.get("X-DutchPay-Secret", "")
    if not hmac.compare_digest(signature, WEBHOOK_SECRET):
        return jsonify({"error": "invalid webhook secret"}), 401

    data = request.get_json(silent=True) or {}
    settlement_id = data.get("settlement_id")
    amount = int(data.get("amount", 0) or 0)
    sender_user_id = data.get("sender_user_id")
    sender_name = str(data.get("sender_name", "")).strip()
    transaction_id = str(data.get("transaction_id", "")).strip()

    if not settlement_id or not amount or not transaction_id:
        return jsonify({"error": "settlement_id, amount, transaction_id가 필요합니다."}), 400

    conn = db()

    # 중복 거래 방지
    exists = conn.execute(
        "SELECT id FROM settlement_participants WHERE transaction_id = ?",
        (transaction_id,)
    ).fetchone()
    if exists:
        return jsonify({"ok": True, "duplicate": True})

    participant = None
    if sender_user_id:
        participant = conn.execute("""
            SELECT * FROM settlement_participants
            WHERE settlement_id=? AND user_id=? AND status='pending' AND amount=?
            LIMIT 1
        """, (settlement_id, sender_user_id, amount)).fetchone()

    if not participant and sender_name:
        participant = conn.execute("""
            SELECT * FROM settlement_participants
            WHERE settlement_id=? AND name=? AND status='pending' AND amount=?
            LIMIT 1
        """, (settlement_id, sender_name, amount)).fetchone()

    if not participant:
        participant = conn.execute("""
            SELECT * FROM settlement_participants
            WHERE settlement_id=? AND status='pending' AND amount=?
            ORDER BY id LIMIT 1
        """, (settlement_id, amount)).fetchone()

    if not participant:
        return jsonify({
            "ok": False,
            "matched": False,
            "message": "금액과 참여자를 매칭하지 못했습니다."
        }), 200

    paid_time = now()
    conn.execute("""
        UPDATE settlement_participants
        SET status='paid', paid_at=?, transaction_id=?
        WHERE id=?
    """, (paid_time, transaction_id, participant["id"]))

    settlement = conn.execute(
        "SELECT owner_id FROM settlements WHERE id=?", (settlement_id,)
    ).fetchone()

    conn.execute("""
        INSERT INTO notifications(user_id,kind,title,message,settlement_id,created_at)
        VALUES(?,?,?,?,?,?)
    """, (
        settlement["owner_id"], "payment_received", "입금이 확인되었습니다",
        f"{participant['name']}님이 {participant['amount']:,}원을 입금했습니다.",
        settlement_id, paid_time
    ))

    conn.commit()
    return jsonify({"ok": True, "matched": True, "participant_id": participant["id"]})


@app.route("/api/settlements", methods=["GET"])
@login_required
def settlements_list():
    rows = db().execute("""
        SELECT s.id, s.total_amount, s.created_at, s.public_token,
               COUNT(sp.id) AS participant_count,
               SUM(CASE WHEN sp.status='paid' THEN 1 ELSE 0 END) AS paid_count
        FROM settlements s
        LEFT JOIN settlement_participants sp ON sp.settlement_id = s.id
        WHERE s.owner_id = ?
        GROUP BY s.id
        ORDER BY s.id DESC
        LIMIT 50
    """, (g.current_user["id"],)).fetchall()

    result = []
    for r in rows:
        participants = db().execute("""
            SELECT name, amount, status, paid_at
            FROM settlement_participants
            WHERE settlement_id=?
            ORDER BY id
        """, (r["id"],)).fetchall()
        result.append({
            "id": r["id"],
            "date": r["created_at"][:10],
            "total": r["total_amount"],
            "count": db().execute(
                "SELECT COUNT(*) FROM receipts WHERE settlement_id=?", (r["id"],)
            ).fetchone()[0],
            "members": [p["name"] for p in participants],
            "paid_count": r["paid_count"] or 0,
            "participant_count": r["participant_count"] or 0,
            "participants": [dict(p) for p in participants],
            "share_url": WEB_URL + "?token=" + r["public_token"] + "&api=" +
                         urllib.parse.quote(API_BASE_URL, safe=""),
        })
    return jsonify(result)


@app.route("/api/notifications", methods=["GET"])
@login_required
def notifications():
    rows = db().execute("""
        SELECT id,kind,title,message,settlement_id,read,created_at
        FROM notifications WHERE user_id=?
        ORDER BY id DESC LIMIT 50
    """, (g.current_user["id"],)).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/notifications/<int:notification_id>/read", methods=["POST"])
@login_required
def notification_read(notification_id):
    db().execute("""
        UPDATE notifications SET read=1
        WHERE id=? AND user_id=?
    """, (notification_id, g.current_user["id"]))
    db().commit()
    return jsonify({"ok": True})


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=PORT, debug=False)
