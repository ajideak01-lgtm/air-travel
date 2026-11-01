from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from werkzeug.utils import secure_filename
from pathlib import Path
from datetime import datetime
import os, uuid, urllib.request, urllib.error, json, sqlite3
from werkzeug.security import generate_password_hash, check_password_hash

ROOT = Path(__file__).resolve().parent
UPLOADS = ROOT / "static" / "uploads"
UPLOADS.mkdir(parents=True, exist_ok=True)
ALLOWED = {"png", "jpg", "jpeg", "gif", "webp"}

app = Flask(__name__)
app.secret_key = os.environ.get("AIRTRAVEL_SECRET", "change-this-secret-before-deployment")
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024
DB_PATH = ROOT / "airtravel_users.db"

def init_db():
    with sqlite3.connect(DB_PATH) as db:
        db.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, created_at TEXT NOT NULL)")

init_db()

# Local prototype storage. Replace with a database and real-time service for production.
messages = [
    {"id": "welcome", "name": "Air Travel Crew", "role": "System", "text": "Welcome aboard! Keep conversations respectful and aviation-focused.", "image": None, "time": "Just now"}
]
flights = [
    {"callsign":"AFR702","from":"Paris (CDG)","to":"Lagos (LOS)","altitude":"FL360","speed":"452 kt","status":"En route","lat":6.4,"lon":2.2},
    {"callsign":"BAW75","from":"London (LHR)","to":"Abuja (ABV)","altitude":"FL340","speed":"438 kt","status":"En route","lat":8.1,"lon":4.0},
    {"callsign":"KQA532","from":"Nairobi (NBO)","to":"Lagos (LOS)","altitude":"FL380","speed":"467 kt","status":"En route","lat":5.2,"lon":9.1},
    {"callsign":"DHL8XX","from":"Accra (ACC)","to":"Abuja (ABV)","altitude":"FL320","speed":"421 kt","status":"Approach","lat":8.9,"lon":1.8},
]

def is_owner():
    return bool(session.get("owner"))

@app.get("/")
def home():
    return render_template("index.html", owner=is_owner(), username=session.get("username"), signed_in=bool(session.get("user_id")))

@app.get("/api/messages")
def get_messages():
    return jsonify(messages[-80:])

@app.post("/api/messages")
def post_message():
    if not session.get("user_id"):
        return jsonify(error="Please sign in or create an account before posting."), 401
    name = (session.get("username") or "Member").strip()[:28]
    text = (request.form.get("text") or "").strip()[:600]
    image_url = None
    image = request.files.get("image")
    if image and image.filename:
        ext = image.filename.rsplit(".", 1)[-1].lower() if "." in image.filename else ""
        if ext not in ALLOWED:
            return jsonify(error="Please upload a PNG, JPG, GIF or WEBP image."), 400
        filename = secure_filename(f"{uuid.uuid4().hex}.{ext}")
        image.save(UPLOADS / filename)
        image_url = f"/static/uploads/{filename}"
    if not text and not image_url:
        return jsonify(error="Write a message or attach a picture."), 400
    item = {"id":uuid.uuid4().hex, "name":name, "role":"Pilot / Member", "text":text, "image":image_url, "time":datetime.now().strftime("%H:%M")}
    messages.append(item)
    return jsonify(item)

@app.get("/api/flights")
def get_flights():
    # Public ADS-B data near Lagos, Nigeria. Provider availability/rate limits may vary.
    # This is for awareness/education, not navigation or operational decisions.
    try:
        req = urllib.request.Request(
            "https://api.adsb.lol/v2/lat/6.5244/lon/3.3792/dist/250",
            headers={"User-Agent": "AirTravelDemo/1.0 (educational flight map)"})
        with urllib.request.urlopen(req, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
        live = []
        for ac in (payload.get("aircraft") or [])[:120]:
            lat, lon = ac.get("lat"), ac.get("lon")
            if lat is None or lon is None:
                continue
            alt = ac.get("alt_baro", "—")
            if isinstance(alt, (int, float)):
                alt = f"{round(alt):,} ft"
            speed = ac.get("gs", "—")
            if isinstance(speed, (int, float)):
                speed = f"{round(speed)} kt"
            live.append({"callsign": (ac.get("flight") or ac.get("hex") or "Unknown").strip(),
                         "from": ac.get("r") or "Unknown aircraft", "to": "Route not provided",
                         "altitude": str(alt), "speed": str(speed), "status": "Live ADS-B",
                         "lat": lat, "lon": lon, "hex": ac.get("hex", "")})
        return jsonify({"demo": False, "provider": "adsb.lol", "flights": live,
                        "updated": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")})
    except Exception:
        return jsonify({"demo": True, "provider": None, "flights": flights,
                        "notice": "Live ADS-B data is temporarily unavailable. Showing clearly labelled sample aircraft."})

@app.post("/api/ai")
def ai_assistant():
    data = request.get_json(silent=True) or {}
    raw_prompt = str(data.get("prompt", "")).strip()[:1200]
    if not raw_prompt:
        return jsonify(answer="Type a question first and I’ll help.", mode="Air Travel AI")
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if api_key:
        try:
            body = json.dumps({"model": os.environ.get("OPENAI_MODEL", "gpt-4.1-mini"),
                "messages": [{"role":"system","content":"You are Air Travel AI, a friendly aviation education assistant. Explain aviation topics clearly and accurately. Never act as an air traffic controller or provide operational flight instructions. For safety-critical decisions, refer users to certified aviation sources and trained professionals."},
                             {"role":"user","content":raw_prompt}], "max_tokens":600}).encode()
            req = urllib.request.Request("https://api.openai.com/v1/chat/completions", data=body,
                headers={"Authorization":"Bearer " + api_key,"Content-Type":"application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=25) as response:
                result = json.loads(response.read().decode())
            answer = result["choices"][0]["message"]["content"].strip()
            return jsonify(answer=answer, mode="Connected AI")
        except Exception as exc:
            # Do not silently hide a broken API configuration; provide useful guidance.
            return jsonify(answer="The AI service could not connect. Check that your OPENAI_API_KEY is valid, that billing/API access is enabled, and that this computer has internet access. The built-in helper is still available below.\n\n" + demo_ai_answer(raw_prompt), mode="AI connection needs setup")
    return jsonify(answer=demo_ai_answer(raw_prompt), mode="Built-in AI helper · API key not set")

def demo_ai_answer(raw_prompt):
    prompt = raw_prompt.lower()
    if any(k in prompt for k in ["ads-b", "adsb"]):
        return "ADS-B means Automatic Dependent Surveillance–Broadcast. An aircraft determines its position using navigation systems and broadcasts information such as position, altitude, speed and identity. Ground stations or satellites may receive those broadcasts. Coverage and data quality vary."
    if "flight level" in prompt or "flight levels" in prompt:
        return "A flight level is a pressure-altitude level expressed in hundreds of feet, using a standard pressure setting. For example, FL350 means 35,000 feet on that standard setting. Actual level selection and separation follow the applicable aviation rules and ATC instructions."
    if any(k in prompt for k in ["track", "flight tracking", "aircraft", "plane"]):
        return "Flight tracking websites combine reports from sources such as ADS-B receivers and other aviation data feeds to estimate aircraft positions. Coverage may be incomplete or delayed. Air Travel's map tries a public ADS-B feed near Lagos; when that feed is unavailable, the app labels the fallback as sample data."
    if any(k in prompt for k in ["weather", "turbulence"]):
        return "Turbulence is irregular air movement that can cause a bumpy ride. It can be associated with storms, terrain, jet streams or other atmospheric conditions. For actual flight planning or safety decisions, crews use official aviation weather products and approved procedures."
    if any(k in prompt for k in ["airport", "runway"]):
        return "An airport is a facility for aircraft arrivals, departures and ground operations. A runway is a defined surface used for takeoff and landing. Runway selection and use depend on factors such as wind, conditions, aircraft performance and ATC instructions."
    if any(k in prompt for k in ["hello", "hi", "hey"]):
        return "Hello! ✈️ I’m Air Travel AI. You can ask me about ADS-B, flight levels, airports, aircraft, aviation terminology or how to use this app."
    if any(k in prompt for k in ["sign in", "login", "account", "register"]):
        return "To join the Air Travel community, open Sign in / Join in the top menu. Create an account with a username, email address and password, then sign in to post messages and pictures."
    return "I’m Air Travel’s built-in aviation helper. I can explain topics such as ADS-B, flight levels, airport operations and flight tracking. For this question I may need a connected AI API key to give a more detailed answer. To enable full AI, configure OPENAI_API_KEY in your environment before starting the app. Never use this demo assistant for operational flight decisions."

@app.post("/auth/signup")
def signup():
    username = (request.form.get("username") or "").strip()[:28]
    email = (request.form.get("email") or "").strip().lower()[:254]
    password = request.form.get("password") or ""
    if len(username) < 3 or "@" not in email or len(password) < 8:
        return redirect(url_for("home", auth_error="invalid_signup") + "#auth")
    try:
        with sqlite3.connect(DB_PATH) as db:
            cur = db.execute("INSERT INTO users(username,email,password_hash,created_at) VALUES(?,?,?,?)", (username,email,generate_password_hash(password),datetime.utcnow().isoformat()))
            session.clear(); session["user_id"] = cur.lastrowid; session["username"] = username
        return redirect(url_for("home", auth_success="joined") + "#community")
    except sqlite3.IntegrityError:
        return redirect(url_for("home", auth_error="exists") + "#auth")

@app.post("/auth/login")
def login():
    identity = (request.form.get("identity") or "").strip().lower()
    password = request.form.get("password") or ""
    with sqlite3.connect(DB_PATH) as db:
        db.row_factory = sqlite3.Row
        user = db.execute("SELECT * FROM users WHERE lower(username)=? OR email=?", (identity, identity)).fetchone()
    if not user or not check_password_hash(user["password_hash"], password):
        return redirect(url_for("home", auth_error="login") + "#auth")
    session.clear(); session["user_id"] = user["id"]; session["username"] = user["username"]
    return redirect(url_for("home", auth_success="welcome") + "#community")

@app.post("/auth/logout")
def auth_logout():
    session.clear()
    return redirect(url_for("home", auth_success="logout") + "#auth")

@app.post("/owner/login")
def owner_login():
    password = request.form.get("password", "")
    expected = os.environ.get("AIRTRAVEL_OWNER_PASSWORD", "change-this-password")
    if password and password == expected:
        session["owner"] = True
        return redirect(url_for("home"))
    return redirect(url_for("home") + "?owner_error=1")

@app.post("/owner/logout")
def owner_logout():
    session.pop("owner", None)
    return redirect(url_for("home"))

@app.get("/api/owner/stats")
def owner_stats():
    if not is_owner():
        return jsonify(error="Owner access required."), 403
    return jsonify(members="Demo mode", messages=len(messages), uploads=len(list(UPLOADS.glob("*"))), flights=len(flights))

if __name__ == "__main__":
    if os.environ.get("AIRTRAVEL_OPEN_BROWSER", "1") == "1":
        import webbrowser, threading
        url = "http://127.0.0.1:5000"
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), debug=False)
