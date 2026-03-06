"""
فريق كيريو تشان 🇦🇪 | @k2r_1
Session Tracking Server — يعمل على Railway مجاناً
"""

from flask import Flask, request, jsonify
from datetime import datetime, timedelta
import os, json, threading

app = Flask(__name__)

# ══════════════════════════════════════════════════════
#  CONFIG
# ══════════════════════════════════════════════════════
SESSION_SECRET = os.environ.get("SESSION_SECRET", "K2R_SECRET_CHANGE_ME")

# قاعدة بيانات بسيطة في الذاكرة
# (تُمسح عند إعادة تشغيل السيرفر — مناسب للاستخدام العادي)
sessions: dict = {}   # session_id → session_data
lock = threading.Lock()

HEARTBEAT_TIMEOUT = 90   # ثانية — إذا لم يُرسل heartbeat خلالها = غير نشط

# ══════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════
def is_active(session: dict) -> bool:
    """هل الجلسة نشطة؟ (heartbeat أُرسل خلال آخر 90 ثانية)"""
    if session.get("event") == "stop":
        return False
    last = session.get("last_seen")
    if not last:
        return False
    delta = datetime.utcnow() - datetime.fromisoformat(last)
    return delta.total_seconds() < HEARTBEAT_TIMEOUT

def check_secret(data: dict) -> bool:
    return data.get("secret") == SESSION_SECRET

def format_since(iso_time: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_time)
        delta = datetime.utcnow() - dt
        mins = int(delta.total_seconds() // 60)
        if mins < 1:   return "للتو"
        if mins < 60:  return f"منذ {mins} دقيقة"
        hours = mins // 60
        return f"منذ {hours} ساعة"
    except:
        return "—"

# ══════════════════════════════════════════════════════
#  ROUTES
# ══════════════════════════════════════════════════════

@app.route("/", methods=["GET"])
def home():
    with lock:
        active_count = sum(1 for s in sessions.values() if is_active(s))
    return jsonify({
        "status":        "online",
        "app":           "فريق كيريو تشان 🇦🇪 | @k2r_1",
        "active_users":  active_count,
        "total_sessions": len(sessions),
    })


@app.route("/api/sessions", methods=["POST"])
def handle_session():
    """استقبال أحداث الجلسة من البرنامج (start / heartbeat / stop)"""
    try:
        data = request.get_json(force=True)
        if not data or not check_secret(data):
            return jsonify({"error": "Unauthorized"}), 401

        session_id = data.get("session_id")
        event      = data.get("event", "heartbeat")
        if not session_id:
            return jsonify({"error": "Missing session_id"}), 400

        now = datetime.utcnow().isoformat()

        with lock:
            if session_id not in sessions:
                sessions[session_id] = {
                    "session_id":    session_id,
                    "user_id":       data.get("user_id", ""),
                    "username":      data.get("username", "مجهول"),
                    "discriminator": data.get("discriminator", "0"),
                    "game_path":     data.get("game_path", ""),
                    "started_at":    now,
                    "last_seen":     now,
                    "event":         event,
                }
            else:
                sessions[session_id]["last_seen"] = now
                sessions[session_id]["event"]     = event
                if data.get("game_path"):
                    sessions[session_id]["game_path"] = data["game_path"]

        return jsonify({"status": "ok", "event": event})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/sessions", methods=["GET"])
def list_sessions():
    """إرجاع قائمة المستخدمين النشطين — للوحة التحكم في البرنامج"""
    secret = request.args.get("secret")
    action = request.args.get("action", "list_active")

    if secret != SESSION_SECRET:
        return jsonify({"error": "Unauthorized"}), 401

    with lock:
        if action == "list_all":
            result = list(sessions.values())
        else:
            result = [s for s in sessions.values() if is_active(s)]

    users = []
    for s in result:
        name = s.get("username", "—")
        disc = s.get("discriminator", "0")
        users.append({
            "username":      name,
            "discriminator": disc,
            "display":       f"{name}#{disc}" if disc != "0" else name,
            "game_path":     s.get("game_path", "—"),
            "since":         format_since(s.get("started_at", "")),
            "last_seen":     s.get("last_seen", ""),
            "status":        "نشط" if is_active(s) else "غير نشط",
            "event":         s.get("event", ""),
        })

    # ترتيب: الأحدث أولاً
    users.sort(key=lambda x: x.get("last_seen", ""), reverse=True)

    return jsonify({
        "users":        users,
        "active_count": sum(1 for s in sessions.values() if is_active(s)),
        "total":        len(sessions),
        "timestamp":    datetime.utcnow().isoformat(),
    })


@app.route("/api/stats", methods=["GET"])
def stats():
    """إحصائيات عامة"""
    secret = request.args.get("secret")
    if secret != SESSION_SECRET:
        return jsonify({"error": "Unauthorized"}), 401

    with lock:
        active     = sum(1 for s in sessions.values() if is_active(s))
        total      = len(sessions)
        usernames  = list({s["username"] for s in sessions.values()})

    return jsonify({
        "active_now":      active,
        "total_sessions":  total,
        "unique_users":    len(usernames),
        "users_list":      usernames,
        "server_time":     datetime.utcnow().isoformat(),
    })


@app.route("/api/clear_old", methods=["POST"])
def clear_old():
    """حذف الجلسات القديمة (أكثر من 24 ساعة)"""
    data = request.get_json(force=True) or {}
    if not check_secret(data):
        return jsonify({"error": "Unauthorized"}), 401

    cutoff = datetime.utcnow() - timedelta(hours=24)
    removed = 0
    with lock:
        to_del = []
        for sid, s in sessions.items():
            try:
                if datetime.fromisoformat(s["last_seen"]) < cutoff:
                    to_del.append(sid)
            except:
                to_del.append(sid)
        for sid in to_del:
            del sessions[sid]
            removed += 1

    return jsonify({"removed": removed, "remaining": len(sessions)})


# ══════════════════════════════════════════════════════
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    print(f"🚀 k2r_1 Session Server running on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
