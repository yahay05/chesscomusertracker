import json
import time
import threading
import requests
import sqlite3
from datetime import datetime, timezone
from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_socketio import SocketIO, emit
import requests.exceptions
import os
from dotenv import load_dotenv

load_dotenv()  # load environment variables from .env file

admin_username = os.getenv("ADMIN_USERNAME", "admin")
admin_password = os.getenv("ADMIN_PASSWORD", "password123")

print(admin_username)
print(admin_password)

# === Flask setup ===
app = Flask(__name__)
app.secret_key = "supersecret"
socketio = SocketIO(app, cors_allowed_origins="*")

last_status_cache = {}
DB_FILE = "app.db"
CHESS_API = "https://www.chess.com/service/presence/watch/users?ids="

def init_db():
    # Initialize last_status_cache on startup
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    # Users table (for login)
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password TEXT
    )''')

    # Create tracked_users table if it doesn't exist
    c.execute('''CREATE TABLE IF NOT EXISTS tracked_users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT UNIQUE,
        chess_id TEXT,
        username TEXT,
        firstName TEXT,
        avatarUrl TEXT,
        bestRating INTEGER,
        bestRatingType TEXT,
        chessTitle TEXT,
        countryName TEXT,
        joinDate TEXT,
        lastLoginDate TEXT,
        topPuzzleRushScore INTEGER,
        topPuzzleRushScoreType TEXT,
        isStreamer BOOLEAN,
        isTopBlogger BOOLEAN,
        membershipLevel INTEGER,
        membershipName TEXT,
        membershipCode TEXT,
        flairPng TEXT,
        onlineStatus TEXT,
        last_active TEXT,
        updated_at TEXT,
        uuid TEXT,
        status TEXT,
        last_status TEXT,
        api_url TEXT
    )''')
    
        
    conn.commit()
    
    c.execute("SELECT uuid, last_status FROM tracked_users WHERE uuid IS NOT NULL")
    for uuid, last_status in c.fetchall():
        if last_status:
            last_status_cache[uuid] = last_status
        
        
    # Seed login user
    c.execute(
        "INSERT OR IGNORE INTO users (username, password) VALUES (?, ?)",
        (admin_username, admin_password)
    )
    conn.commit()
    conn.close()

def humanize_time_difference(iso_time_str):
    """Convert ISO timestamp into human-readable 'X minutes/hours/days ago'."""
    try:
        ts = datetime.fromisoformat(iso_time_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        delta = now - ts

        seconds = int(delta.total_seconds())
        minutes = seconds // 60
        hours = minutes // 60
        days = hours // 24

        if seconds < 60:
            return f"{seconds} seconds ago"
        elif minutes < 60:
            return f"{minutes} minutes ago"
        elif hours < 24:
            return f"{hours} hours ago"
        else:
            return f"{days} days ago"
    except Exception as e:
        print(f"Error parsing time {iso_time_str}: {e}")
        return "unknown time"

def get_user_data_from_username(username):
    """Fetch full Chess.com user data from username."""
    url = f"https://www.chess.com/callback/user/popup/{username}"
    try:
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            return r.json()
        else:
            print(f"Lookup failed for {username}: {r.status_code}")
            return None
    except Exception as e:
        print(f"Error during lookup for {username}: {e}")
        return None
    
    
def fetch_chess_data():
    """Background thread that reconnects every 5s to check user presence without spamming."""
    while True:
        try:
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            c.execute("SELECT uuid, id, username, last_status, api_url FROM tracked_users WHERE uuid IS NOT NULL")
            rows = c.fetchall()
            conn.close()

            if not rows:
                print("⏳ No users to track. Waiting...")
                time.sleep(5)
                continue

            for uuid, db_id, username, last_status, api_url in rows:
                url = f"{CHESS_API}{uuid}"
                try:
                    with requests.get(url, stream=True, timeout=30) as response:
                        response.raise_for_status()

                        for line in response.iter_lines(decode_unicode=True):
                            if not line or not line.strip():
                                continue

                            if line.startswith("data:"):
                                try:
                                    data = json.loads(line[len("data:"):].strip())
                                    status = data.get("status")
                                    last_active = data.get("statusAt")

                                    # Get previous status (from memory or DB)
                                    prev_status = last_status_cache.get(uuid, last_status or "unknown")
                                    
                                    
                                    # Only act if it TRULY changed
                                    if status and status != prev_status:
                                        last_status_cache[uuid] = status
                                        print(f"🔄 {username} status changed: {prev_status} → {status}")

                                        # update DB with new status
                                        db_conn = sqlite3.connect(DB_FILE)
                                        db_c = db_conn.cursor()
                                        db_c.execute("""
                                            UPDATE tracked_users
                                            SET onlineStatus=?, last_active=?, updated_at=?, status=?, last_status=?
                                            WHERE uuid=?
                                        """, (
                                            status,
                                            last_active,
                                            datetime.now(timezone.utc).isoformat(),
                                            status,
                                            status,
                                            uuid
                                        ))
                                        db_conn.commit()
                                        db_conn.close()
                                        
                                        print(status)
                                        socketio.emit(
                                            "update",
                                            {
                                                "user_id": db_id,
                                                "status": status or "unknown",
                                                "last_active": humanize_time_difference(last_active) if last_active else "unknown",
                                                "uuid": uuid
                                            }
                                        )


                                        # call external API
                                        if api_url:
                                            try:
                                                if status == "online":
                                                    msg = f"✅ {username} is ONLINE now"
                                                elif status == "offline":
                                                    readable = humanize_time_difference(last_active) if last_active else "unknown"
                                                    msg = f"❌ {username} went OFFLINE (last seen {readable})"
                                                else:
                                                    msg = f"ℹ️ {username} status: {status}"

                                                r = requests.post(api_url,
                                                    data=msg.encode(encoding='utf-8'), timeout=2)
                                                print(f"📡 API triggered: {r.status_code} {msg}")
                                            except Exception as e:
                                                print(f"⚠️ API error for {username}: {e}")

                                except json.JSONDecodeError:
                                    print("⚠️ JSON parse error:", line)

                                # break after first event (force reconnect after 1 event)
                                break

                except Exception as e:
                    print(f"❌ Error for {username}: {e}")

            # wait before looping through users again
            time.sleep(5)

        except Exception as e:
            print(f"❌ Unexpected error: {e}")
            time.sleep(5)


# === Routes ===
@app.route("/")
def home():
    if "user" in session:
        return redirect(url_for("dashboard"))
    return render_template("home.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        if not username or not password:
            flash("Please provide both username and password")
            return render_template("login.html")
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE username=? AND password=?", (username, password))
        user = c.fetchone()
        conn.close()
        if user:
            session["user"] = username
            return redirect(url_for("dashboard"))
        else:
            flash("Invalid credentials")
    return render_template("login.html")

@app.route("/dashboard")
def dashboard():
    print(admin_password,"admin-password" )
    if "user" not in session:
        return redirect(url_for("home"))
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""SELECT 
        id, user_id, chess_id, username, firstName, avatarUrl, bestRating, bestRatingType, 
        chessTitle, countryName, joinDate, lastLoginDate, topPuzzleRushScore, topPuzzleRushScoreType,
        isStreamer, isTopBlogger, membershipLevel, membershipName, membershipCode, flairPng,
        onlineStatus, last_active, updated_at, uuid, status, api_url
    FROM tracked_users ORDER BY username""")
    users = c.fetchall()
    conn.close()
    processed_users = []
    for user in users:
        user_dict = {
            'id': user[0],
            'user_id': user[1],
            'chess_id': user[2],
            'username': user[3],
            'firstName': user[4],
            'avatarUrl': user[5],
            'bestRating': user[6],
            'bestRatingType': user[7],
            'chessTitle': user[8],
            'countryName': user[9],
            'joinDate': user[10],
            'lastLoginDate': user[11],
            'topPuzzleRushScore': user[12],
            'topPuzzleRushScoreType': user[13],
            'isStreamer': user[14],
            'isTopBlogger': user[15],
            'membershipLevel': user[16],
            'membershipName': user[17],
            'membershipCode': user[18],
            'flairPng': user[19],
            'onlineStatus': user[20] or 'unknown',
            'last_active': humanize_time_difference(user[21]) if user[21] else 'unknown',
            'updated_at': user[22],
            'uuid': user[23],
            'status':user[20] or user[24] or 'unknown',
            'api_url': user[25]
        }
        processed_users.append(user_dict)
    return render_template("dashboard.html", users=processed_users)

@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect(url_for("home"))

@app.route("/add_user", methods=["POST"])
def add_user():
    if "user" not in session:
        return redirect(url_for("home"))
    username_input = request.form.get("username", "").strip()
    if not username_input:
        flash("Please enter a username")
        return redirect(url_for("dashboard"))
    data = get_user_data_from_username(username_input)
    if data and data.get("userId"):
        try:
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            c.execute("SELECT id FROM tracked_users WHERE user_id=?", (str(data.get("userId")),))
            if c.fetchone():
                flash(f"User {username_input} is already being tracked")
                conn.close()
                return redirect(url_for("dashboard"))
            membership = data.get("membership", {})
            flair = data.get("flair", {})
            flair_images = flair.get("images", {}) if flair else {}
            c.execute("""
                INSERT INTO tracked_users (
                    user_id, chess_id, username, firstName, avatarUrl, bestRating, bestRatingType, chessTitle,
                    countryName, joinDate, lastLoginDate, topPuzzleRushScore, topPuzzleRushScoreType,
                    isStreamer, isTopBlogger, membershipLevel, membershipName, membershipCode, flairPng,
                    onlineStatus, uuid, status, updated_at, last_status, api_url
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                str(data.get("userId")),
                str(data.get("userId")),
                username_input,
                data.get("firstName"),
                data.get("avatarUrl"),
                data.get("bestRating"),
                data.get("bestRatingType"),
                data.get("chessTitle"),
                data.get("countryName"),
                data.get("joinDate"),
                data.get("lastLoginDate"),
                data.get("topPuzzleRushScore"),
                data.get("topPuzzleRushScoreType"),
                int(data.get("isStreamer", False)),
                int(data.get("isTopBlogger", False)),
                membership.get("level"),
                membership.get("name"),
                membership.get("code"),
                flair_images.get("png"),
                data.get("onlineStatus", "unknown"),
                data.get("uuid"),
                data.get("onlineStatus", "unknown"),
                datetime.now(timezone.utc).isoformat(),
                data.get("onlineStatus", "unknown"),
                None
            ))
            conn.commit()
            conn.close()
            flash(f"Successfully added {username_input} to tracking")
        except Exception as e:
            flash(f"Error adding user: {str(e)}")
            print(f"Database error: {e}")
    else:
        flash(f"Could not find Chess.com user: {username_input}")
    return redirect(url_for("dashboard"))

@app.route("/update_api_url", methods=["POST"])
def update_api_url():
    if "user" not in session:
        return redirect(url_for("home"))
    user_id = request.form.get("user_id")
    api_url = request.form.get("api_url")
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("UPDATE tracked_users SET api_url = ? WHERE id = ?", (api_url, user_id))
        conn.commit()
        conn.close()
        flash("API URL updated successfully")
    except Exception as e:
        flash(f"Error updating API URL: {str(e)}")
    return redirect(url_for("dashboard"))

@app.route("/remove_user/<int:user_id>", methods=["POST"])
def remove_user(user_id):
    if "user" not in session:
        return redirect(url_for("home"))
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("DELETE FROM tracked_users WHERE id=?", (user_id,))
        conn.commit()
        conn.close()
        flash("User removed successfully")
    except Exception as e:
        flash(f"Error removing user: {str(e)}")
    return redirect(url_for("dashboard"))

# === Startup ===
if __name__ == "__main__":
    init_db()
    thread = threading.Thread(target=fetch_chess_data, daemon=True)
    thread.start()
    socketio.start_background_task(fetch_chess_data)
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)

