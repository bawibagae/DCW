import os
import json
import re
from werkzeug.exceptions import HTTPException
import sqlite3
import secrets
import hashlib
import hmac
import datetime
import urllib.parse
from functools import wraps

from flask import Flask, request, jsonify, g, send_from_directory


# Input validation (integrated)
"""Strict shared server input validation. All prices are line totals in KRW."""
def body(request):
    value = request.get_json(silent=True)
    if not isinstance(value, dict):
        raise ValueError('JSON 객체가 필요합니다.')
    return value


def text(value, label, limit=100, strip=True):
    if not isinstance(value, str):
        raise ValueError(f'{label}: 문자열이 필요합니다.')
    value = value.strip() if strip else value
    if not value or len(value) > limit:
        raise ValueError(f'{label}: 1~{limit}자여야 합니다.')
    return value


def integer(value, label, minimum=0, maximum=1_000_000_000):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f'{label}: {minimum}~{maximum} 사이 정수가 필요합니다.')
    return value


def objects(value, label, limit):
    if not isinstance(value, list) or not 1 <= len(value) <= limit or not all(isinstance(x, dict) for x in value):
        raise ValueError(f'{label}: 1~{limit}개 객체 배열이 필요합니다.')
    return value


def validate_settlement(data, conn, owner):
    bank = text(data.get('bank'), '은행', 50)
    account = text(data.get('account'), '계좌번호', 40)
    if not account.replace('-', '').replace(' ', '').isdigit():
        raise ValueError('계좌번호에는 숫자, 공백, 하이픈만 입력하세요.')
    participants = objects(data.get('participants'), '참여자', 100)
    receipts = objects(data.get('receipts'), '영수증', 50)
    seen = set()
    for p in participants:
        p['name'] = text(p.get('name'), '참여자 이름', 150)
        integer(p.get('amount'), '참여자 금액', 1)
        if p['name'] in seen:
            raise ValueError('참여자 표시 이름을 구분해 주세요.')
        seen.add(p['name'])
        uid = p.get('user_id')
        if uid is not None:
            integer(uid, 'user_id', 1)
            if uid != owner and not conn.execute('SELECT 1 FROM friends WHERE user_id=? AND friend_id=?',(owner,uid)).fetchone():
                raise ValueError('등록된 친구만 연결할 수 있습니다.')
    for r in receipts:
        integer(r.get('total_amount'), '영수증 총액', 1)
        for item in objects(r.get('items'), '품목', 200):
            item['item'] = text(item.get('item'), '품목명', 150)
            integer(item.get('qty'), '수량', 1, 10000)
            integer(item.get('price'), '품목 합계 금액', 0)
        if sum(x['price'] for x in r['items']) != r['total_amount']:
            raise ValueError('품목 금액 합계와 영수증 총액이 다릅니다. 수정 후 제출하세요.')
    total = sum(r['total_amount'] for r in receipts)
    integer(total, '정산 총액', 1)
    if total != sum(p['amount'] for p in participants):
        raise ValueError('참여자 청구액 합계와 영수증 총액이 다릅니다.')
    return bank, account, participants, receipts

# Server-only OCR (integrated)
"""Server-only OCR. Recognition is a draft requiring user confirmation."""
import io
import re
from PIL import Image


def parse_text(content):
    items, totals = [], []
    for line in content.splitlines():
        line = line.strip()
        if any(k in line for k in ('결제금액','총결제','받을금액','합계','총액','TOTAL','Total')):
            nums = re.findall(r'\d[\d,]*', line)
            if nums:
                rank = 2 if any(k in line for k in ('결제금액','총결제','받을금액')) else 1
                totals.append((rank, int(nums[-1].replace(',',''))))
            continue
        if any(k in line.lower() for k in ('사업자','주소','승인','카드','현금','부가세','tel','vat','pos','일시','할인')):
            continue
        match = re.fullmatch(r'(.+?)\s+(\d+)\s+([\d,]+)원?', line)
        if match:
            name, qty, price = match.groups()
            qty = int(qty)
        else:
            match = re.fullmatch(r'(.+?)\s+([\d,]+)원?', line)
            if not match:
                continue
            name, price = match.groups()
            qty = 1  # Never infer quantity from digits in the item name.
        price = int(price.replace(',',''))
        if 1 <= qty <= 10000 and 0 <= price <= 1_000_000_000 and re.search(r'[가-힣A-Za-z]',name):
            items.append({'item':name,'qty':qty,'price':price})
    total = sorted(totals, key=lambda t:t[0])[-1][1] if totals else sum(i['price'] for i in items)
    return {'items':items, 'total':total, 'review_required':True,
            'warning':'품목 금액은 단가가 아닌 해당 줄의 합계입니다. 할인·누락·수량을 반드시 수정/확인하세요.'}


def recognize(raw):
    if not raw or len(raw) > 10 * 1024 * 1024:
        raise ValueError('이미지는 10MB 이하여야 합니다.')
    try:
        with Image.open(io.BytesIO(raw)) as im:
            if im.format not in ('PNG','JPEG','WEBP') or im.width * im.height > 25_000_000:
                raise ValueError('지원 이미지: JPG/PNG/WEBP, 최대 2500만 화소')
            im.verify()
    except Exception as exc:
        raise ValueError('유효한 JPG/PNG/WEBP 이미지를 선택해 주세요.') from exc
    from google.cloud import vision
    response = vision.ImageAnnotatorClient().document_text_detection(image=vision.Image(content=raw), timeout=45)
    if response.error.message:
        raise RuntimeError(response.error.message)
    return parse_text(response.full_text_annotation.text)


APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.getenv("DB_PATH", os.path.join(APP_DIR, "dutchpay.db"))
API_BASE_URL = os.getenv("API_BASE_URL", os.getenv("RENDER_EXTERNAL_URL", "https://dcw-6vyo.onrender.com")).rstrip("/")
WEB_URL = os.getenv("WEB_URL", API_BASE_URL + "/")
WEBHOOK_SECRET = os.getenv("DUTCHPAY_WEBHOOK_SECRET", "")
PORT = int(os.getenv("PORT", "5000"))

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 12 * 1024 * 1024
SESSION_DAYS = int(os.getenv('SESSION_DAYS', '7'))

@app.errorhandler(ValueError)
def invalid_input(error):
    return jsonify(error=str(error)), 400

@app.errorhandler(HTTPException)
def http_error(error):
    return jsonify(error=error.description), error.code

@app.errorhandler(sqlite3.IntegrityError)
def db_conflict(error):
    db().rollback()
    return jsonify(error='데이터 충돌입니다. 입력을 확인해 주세요.'), 409

@app.errorhandler(sqlite3.OperationalError)
def db_unavailable(error):
    db().rollback()
    app.logger.exception('Database operation failed')
    return jsonify(error='DB를 사용할 수 없습니다. 잠시 후 다시 시도해 주세요.'), 503



@app.after_request
def add_cors_headers(response):
    origin = request.headers.get('Origin', '')
    allowed = {API_BASE_URL, urllib.parse.urlsplit(WEB_URL).scheme + '://' + urllib.parse.urlsplit(WEB_URL).netloc}
    allowed.update(x.strip() for x in os.getenv('CORS_ORIGINS', 'https://bawibagae.github.io').split(',') if x.strip())
    if origin in allowed:
        response.headers['Access-Control-Allow-Origin'] = origin
        response.headers['Vary'] = 'Origin'
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['X-Content-Type-Options'] = 'nosniff' 
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-DutchPay-Secret"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response


@app.route("/", methods=["GET"])
def web_index():
    return send_from_directory(APP_DIR, "index.html")


def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH, timeout=30)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_error=None):
    conn = g.pop("db", None)
    if conn:
        conn.close()


def init_db():
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
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
    conn.execute('PRAGMA journal_mode=WAL')
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS payment_events (
      transaction_id TEXT PRIMARY KEY, participant_id INTEGER NOT NULL,
      settlement_id INTEGER NOT NULL, amount INTEGER NOT NULL, created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS settlement_requests (
      owner_id INTEGER NOT NULL, request_id TEXT NOT NULL, settlement_id INTEGER NOT NULL,
      PRIMARY KEY(owner_id, request_id)
    );
    """)
    # Preserve historical transactions without changing existing participant rows.
    conn.execute("""INSERT OR IGNORE INTO payment_events
      SELECT transaction_id,id,settlement_id,amount,COALESCE(paid_at,'')
      FROM settlement_participants WHERE transaction_id IS NOT NULL AND transaction_id != ''""")
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
        WHERE s.token = ? AND julianday(s.created_at) > julianday(?)
    """, (token, (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=SESSION_DAYS)).isoformat())).fetchone()
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
    data = body(request)
    name = text(data.get('name'), '이름', 80)
    email = text(data.get('email'), '이메일', 254).lower()
    password = text(data.get('password'), '비밀번호', 256, strip=False)
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
        raise ValueError('올바른 이메일을 입력해 주세요.')

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
    data = body(request)
    email = text(data.get('email'), '이메일', 254).lower()
    password = text(data.get('password'), '비밀번호', 256, strip=False)

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
    data = body(request)
    value = str(data.get("email_or_name", "")).strip()
    if not value:
        return jsonify({"error": "친구의 이메일 또는 이름을 입력해 주세요."}), 400

    matches = db().execute("SELECT * FROM users WHERE email = ? COLLATE NOCASE", (value,)).fetchall()
    if not matches:
        matches = db().execute("SELECT * FROM users WHERE name = ? COLLATE NOCASE LIMIT 2", (value,)).fetchall()
    if len(matches) > 1:
        raise ValueError('동명이인이 있습니다. 이메일로 추가해 주세요.')
    friend = matches[0] if matches else None

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
    data = body(request)
    bank, account, participants, receipts = validate_settlement(data, db(), g.current_user['id'])
    request_id = text(data.get('request_id'), 'request_id', 100)
    conn = db()
    conn.execute('BEGIN IMMEDIATE')
    existing = conn.execute('SELECT settlement_id FROM settlement_requests WHERE owner_id=? AND request_id=?',
                            (g.current_user['id'], request_id)).fetchone()
    if existing:
        payload = settlement_json(existing['settlement_id'], g.current_user['id'])
        conn.rollback()
        return jsonify(payload), 200

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

    conn.execute('INSERT INTO settlement_requests VALUES(?,?,?)',
                 (g.current_user['id'], request_id, settlement_id))
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
    payload = settlement_json(row['id'])
    if payload is None:
        return jsonify(error='참여자 정보가 없는 이전 정산입니다.'), 404
    return jsonify({
        'bank': payload['bank'], 'account': payload['account'],
        'owner_name': payload['owner_name'], 'total_amount': payload['total_amount'],
        'participants': [{k: p[k] for k in ('id','name','amount','status','paid_at')} for p in payload['participants']]
    })


@app.route("/api/payments/webhook", methods=["POST"])
def payment_webhook():
    # This endpoint is for a trusted bank adapter, not for browser clients.
    if len(WEBHOOK_SECRET) < 32:
        return jsonify(error='입금 연동 비밀키가 설정되지 않았습니다.'), 503
    signature = request.headers.get('X-DutchPay-Secret', '')
    if not hmac.compare_digest(signature.encode(), WEBHOOK_SECRET.encode()):
        return jsonify(error='invalid webhook secret'), 401
    data = body(request)
    sid = integer(data.get('settlement_id'), 'settlement_id', 1)
    pid = integer(data.get('participant_id'), 'participant_id', 1)
    amount = integer(data.get('amount'), 'amount', 1)
    tx = text(data.get('transaction_id'), 'transaction_id', 200)
    conn = db()
    conn.execute('BEGIN IMMEDIATE')
    old = conn.execute('SELECT * FROM payment_events WHERE transaction_id=?', (tx,)).fetchone()
    if old:
        conn.rollback()
        if (old['participant_id'],old['settlement_id'],old['amount']) != (pid,sid,amount):
            return jsonify(error='거래 ID가 다른 입금 정보에 이미 사용되었습니다.'), 409
        return jsonify(ok=True, duplicate=True)
    p = conn.execute('SELECT * FROM settlement_participants WHERE id=? AND settlement_id=?', (pid,sid)).fetchone()
    if not p or p['amount'] != amount or p['status'] != 'pending':
        conn.rollback()
        return jsonify(error='참여자, 금액 또는 상태 불일치: 수동 확인이 필요합니다.', matched=False), 409
    stamp = now()
    conn.execute('INSERT INTO payment_events VALUES(?,?,?,?,?)', (tx,pid,sid,amount,stamp))
    conn.execute("UPDATE settlement_participants SET status='paid',paid_at=?,transaction_id=? WHERE id=? AND status='pending'", (stamp,tx,pid))
    owner = conn.execute('SELECT owner_id FROM settlements WHERE id=?',(sid,)).fetchone()
    conn.execute('INSERT INTO notifications(user_id,kind,title,message,settlement_id,created_at) VALUES(?,?,?,?,?,?)',
      (owner['owner_id'],'payment_received','입금이 확인되었습니다',f"{p['name']}님이 {amount:,}원을 입금했습니다.",sid,stamp))
    conn.commit()
    return jsonify(ok=True, matched=True, participant_id=pid)


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


@app.route('/api/ocr', methods=['POST'])
@login_required
def ocr():
    uploaded = request.files.get('image')
    if uploaded is None:
        raise ValueError('image 파일을 보내 주세요.')
    try:
        return jsonify(recognize(uploaded.read()))
    except ValueError:
        raise
    except Exception:
        app.logger.exception('OCR service failed')
        return jsonify(error='OCR 서비스 오류: 서버 인증키, Vision API 활성화 및 할당량을 확인해 주세요.'), 503

# Also initialize under gunicorn; CREATE IF NOT EXISTS preserves old records.
init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=False)
