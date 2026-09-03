# ============================================================
#  db.py — Thread-Safe Local JSON Persistence Engine
#  Personalized RAG Study Companion with Synchronized Mobile Alerting
#  Application Interface: StudyEdge AI
# ============================================================

import os
import json
import threading
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STORAGE_DIR = os.path.join(BASE_DIR, "data", "storage")
_LOCK = threading.RLock()


def _ensure_storage_dir():
    os.makedirs(STORAGE_DIR, exist_ok=True)


def _load_json_file(filename: str, default: list = None) -> list:
    """Reads a JSON file from local disk storage safely."""
    _ensure_storage_dir()
    filepath = os.path.join(STORAGE_DIR, filename)
    if not os.path.exists(filepath):
        return default if default is not None else []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, (list, dict)) else (default if default is not None else [])
    except Exception as e:
        print(f"[STORAGE READ ERROR] {filename}: {e}")
        return default if default is not None else []


def _save_json_file(filename: str, data: list):
    """Atomically writes JSON data to local disk storage."""
    _ensure_storage_dir()
    filepath = os.path.join(STORAGE_DIR, filename)
    temp_path = filepath + ".tmp"
    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(temp_path, filepath)
    except Exception as e:
        print(f"[STORAGE WRITE ERROR] {filename}: {e}")
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass


def _next_id(records: list) -> int:
    """Calculates auto-incrementing integer ID for local records."""
    if not records:
        return 1
    max_id = 0
    for r in records:
        val = r.get("id")
        if isinstance(val, int) and val > max_id:
            max_id = val
    return max_id + 1


# ─────────────────────────────────────────
#  Initialize Local Storage
# ─────────────────────────────────────────
def setup_database():
    """Initializes local storage directory and default JSON structures."""
    with _LOCK:
        _ensure_storage_dir()
        tables = [
            "students.json",
            "sessions.json",
            "queries.json",
            "weak_areas.json",
            "push_subscriptions.json",
            "study_plans.json",
            "notification_log.json",
            "test_attempts.json",
            "chat_threads.json",
            "chat_messages.json",
            "notification_settings.json"
        ]
        for tbl in tables:
            fp = os.path.join(STORAGE_DIR, tbl)
            if not os.path.exists(fp):
                _save_json_file(tbl, {} if tbl == "notification_settings.json" else [])
        print(f"[STORAGE] Local System File Storage active at: {STORAGE_DIR}")


# ─────────────────────────────────────────
#  Student Operations
# ─────────────────────────────────────────
def create_student(name: str, email: str = None) -> int:
    with _LOCK:
        students = _load_json_file("students.json", [])
        clean_name = str(name).strip() if name else "Student"
        for s in students:
            if s.get("name", "").lower() == clean_name.lower():
                return s["id"]

        new_id = _next_id(students)
        record = {
            "id": new_id,
            "name": clean_name,
            "email": email or f"{clean_name.lower()}@studyedge.local",
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        students.append(record)
        _save_json_file("students.json", students)
        return new_id


def get_student_by_id(student_id: int) -> dict:
    with _LOCK:
        students = _load_json_file("students.json", [])
        for s in students:
            if s.get("id") == int(student_id):
                return dict(s)
        return None


def get_student_by_name(name: str) -> dict:
    with _LOCK:
        students = _load_json_file("students.json", [])
        clean_name = str(name).strip().lower() if name else ""
        for s in students:
            if s.get("name", "").lower() == clean_name:
                return dict(s)
        return None


# ─────────────────────────────────────────
#  Session Operations
# ─────────────────────────────────────────
def start_session(student_id: int, topic: str, plan_id: int = None) -> int:
    with _LOCK:
        sessions = _load_json_file("sessions.json", [])
        plans = _load_json_file("study_plans.json", [])
        new_id = _next_id(sessions)
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # Automatically close any previous unended sessions for this student
        for s in sessions:
            if s.get("student_id") == int(student_id) and not s.get("end_time"):
                s["end_time"] = now_str
                old_pid = s.get("plan_id")
                if old_pid:
                    for p in plans:
                        if p.get("id") == int(old_pid) and p.get("status") == "active":
                            p["status"] = "completed"
                            p["completed_at"] = now_str

        # If a specific plan is being started, mark it active
        if plan_id:
            for p in plans:
                if p.get("id") == int(plan_id):
                    p["status"] = "active"

        record = {
            "id": new_id,
            "student_id": int(student_id),
            "topic": topic or "General",
            "plan_id": int(plan_id) if plan_id else None,
            "start_time": now_str,
            "end_time": None,
            "pomodoro_count": 0
        }
        sessions.append(record)
        _save_json_file("sessions.json", sessions)
        _save_json_file("study_plans.json", plans)
        return new_id


def end_session(session_id: int):
    with _LOCK:
        sessions = _load_json_file("sessions.json", [])
        plans = _load_json_file("study_plans.json", [])
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        plan_id = None
        for s in sessions:
            if s.get("id") == int(session_id):
                s["end_time"] = now_str
                plan_id = s.get("plan_id")
                break

        # Complete associated plan or any lingering active plan for this session
        if plan_id:
            for p in plans:
                if p.get("id") == int(plan_id) and p.get("status") == "active":
                    p["status"] = "completed"
                    p["completed_at"] = now_str
        _save_json_file("sessions.json", sessions)
        _save_json_file("study_plans.json", plans)


def end_all_active_sessions_for_student(student_id: int):
    """Guarantees all open sessions for this student are cleanly closed."""
    with _LOCK:
        sessions = _load_json_file("sessions.json", [])
        plans = _load_json_file("study_plans.json", [])
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for s in sessions:
            if s.get("student_id") == int(student_id) and not s.get("end_time"):
                s["end_time"] = now_str
                pid = s.get("plan_id")
                if pid:
                    for p in plans:
                        if p.get("id") == int(pid) and p.get("status") == "active":
                            p["status"] = "completed"
                            p["completed_at"] = now_str

        # Mark all active plans for this student as completed
        for p in plans:
            if p.get("student_id") == int(student_id) and p.get("status") == "active":
                p["status"] = "completed"
                p["completed_at"] = now_str

        _save_json_file("sessions.json", sessions)
        _save_json_file("study_plans.json", plans)


def increment_pomodoro(session_id: int):
    with _LOCK:
        sessions = _load_json_file("sessions.json", [])
        for s in sessions:
            if s.get("id") == int(session_id):
                s["pomodoro_count"] = s.get("pomodoro_count", 0) + 1
                break
        _save_json_file("sessions.json", sessions)


def get_session_by_id(session_id: int) -> dict:
    """Returns the session record for the given ID, or None if not found."""
    if not session_id:
        return None
    with _LOCK:
        sessions = _load_json_file("sessions.json", [])
        for s in sessions:
            if s.get("id") == int(session_id):
                return dict(s)
        return None


def get_active_session_for_student(student_id: int) -> dict:
    """Finds latest session for the student that has not ended and was started recently."""
    with _LOCK:
        sessions = _load_json_file("sessions.json", [])
        now = datetime.now()
        active = []
        for s in sessions:
            if s.get("student_id") == int(student_id) and not s.get("end_time"):
                # Ignore and close sessions older than 8 hours
                st_str = s.get("start_time", "")
                try:
                    st_dt = datetime.strptime(st_str, "%Y-%m-%d %H:%M:%S")
                    if (now - st_dt).total_seconds() > 8 * 3600:
                        s["end_time"] = now.strftime("%Y-%m-%d %H:%M:%S")
                        continue
                except Exception:
                    pass
                active.append(s)
        if active:
            active.sort(key=lambda x: x.get("start_time", ""), reverse=True)
            return dict(active[0])
        return None


def save_session_milestones(session_id: int, milestones: list):
    with _LOCK:
        sessions = _load_json_file("sessions.json", [])
        for s in sessions:
            if s.get("id") == int(session_id):
                s["milestones"] = milestones
                break
        _save_json_file("sessions.json", sessions)


def get_session_milestones(session_id: int) -> list:
    with _LOCK:
        sessions = _load_json_file("sessions.json", [])
        for s in sessions:
            if s.get("id") == int(session_id):
                return list(s.get("milestones", []))
        return []



def toggle_session_milestone(session_id: int, milestone_idx: int) -> list:
    with _LOCK:
        sessions = _load_json_file("sessions.json", [])
        updated = []
        for s in sessions:
            if s.get("id") == int(session_id):
                ms = s.get("milestones", [])
                if 0 <= milestone_idx < len(ms):
                    ms[milestone_idx]["done"] = not ms[milestone_idx].get("done", False)
                updated = ms
                break
        _save_json_file("sessions.json", sessions)
        return updated


def record_session_challenge(session_id: int, student_id: int, is_correct: bool) -> int:
    with _LOCK:
        pts = 30 if is_correct else 10
        sessions = _load_json_file("sessions.json", [])
        for s in sessions:
            if s.get("id") == int(session_id):
                s["challenges_completed"] = s.get("challenges_completed", 0) + 1
                if is_correct:
                    s["challenges_correct"] = s.get("challenges_correct", 0) + 1
                break
        _save_json_file("sessions.json", sessions)
        return pts



# ─────────────────────────────────────────
#  Query (Q&A) Operations
# ─────────────────────────────────────────
def save_query(session_id: int, question: str, answer: str) -> int:
    with _LOCK:
        queries = _load_json_file("queries.json", [])
        new_id = _next_id(queries)
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        record = {
            "id": new_id,
            "session_id": int(session_id),
            "question": question,
            "answer": answer,
            "timestamp": now_str
        }
        queries.append(record)
        _save_json_file("queries.json", queries)
        return new_id


def get_session_queries(session_id: int) -> list:
    with _LOCK:
        queries = _load_json_file("queries.json", [])
        filtered = [q for q in queries if q.get("session_id") == int(session_id)]
        filtered.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return filtered


# ─────────────────────────────────────────
#  Weak Area Operations
# ─────────────────────────────────────────
def update_weak_area(student_id: int, topic: str):
    with _LOCK:
        weak_areas = _load_json_file("weak_areas.json", [])
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        clean_topic = str(topic).strip()
        found = False
        for w in weak_areas:
            if w.get("student_id") == int(student_id) and w.get("topic", "").lower() == clean_topic.lower():
                w["query_count"] = w.get("query_count", 0) + 1
                w["last_updated"] = now_str
                found = True
                break
        if not found:
            weak_areas.append({
                "id": _next_id(weak_areas),
                "student_id": int(student_id),
                "topic": clean_topic,
                "query_count": 1,
                "last_updated": now_str
            })
        _save_json_file("weak_areas.json", weak_areas)


def get_weak_areas(student_id: int, limit: int = 5) -> list:
    with _LOCK:
        weak_areas = _load_json_file("weak_areas.json", [])
        student_w = [w for w in weak_areas if w.get("student_id") == int(student_id)]
        student_w.sort(key=lambda x: x.get("query_count", 0), reverse=True)
        return student_w[:limit]


# ─────────────────────────────────────────
#  Push Subscription Operations
# ─────────────────────────────────────────
def save_push_subscription(student_id: int, subscription_json: str):
    with _LOCK:
        subs = _load_json_file("push_subscriptions.json", [])
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        subs = [s for s in subs if s.get("student_id") != int(student_id)]
        subs.append({
            "id": _next_id(subs),
            "student_id": int(student_id),
            "subscription": subscription_json,
            "created_at": now_str
        })
        _save_json_file("push_subscriptions.json", subs)


def get_push_subscription(student_id: int) -> str:
    with _LOCK:
        subs = _load_json_file("push_subscriptions.json", [])
        for s in subs:
            if s.get("student_id") == int(student_id):
                return s.get("subscription")
        return None


def get_all_push_subscriptions() -> list:
    with _LOCK:
        subs = _load_json_file("push_subscriptions.json", [])
        seen = set()
        result = []
        for s in subs:
            sid = s.get("student_id")
            if sid and sid not in seen:
                seen.add(sid)
                result.append({"student_id": sid})
        return result


# ─────────────────────────────────────────
#  Study Plans CRUD
# ─────────────────────────────────────────
def create_study_plan(student_id: int, topic: str, planned_start, duration_mins: int = 25, notes: str = "") -> int:
    with _LOCK:
        plans = _load_json_file("study_plans.json", [])
        new_id = _next_id(plans)
        start_val = planned_start.strftime("%Y-%m-%d %H:%M:%S") if hasattr(planned_start, "strftime") else str(planned_start)
        record = {
            "id": new_id,
            "student_id": int(student_id),
            "topic": topic,
            "planned_start": start_val,
            "planned_duration_mins": duration_mins,
            "notes": notes,
            "status": "pending",
            "notified": False,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        plans.append(record)
        _save_json_file("study_plans.json", plans)
        return new_id


def get_plans_today(student_id: int) -> list:
    with _LOCK:
        plans = _load_json_file("study_plans.json", [])
        today_date = datetime.now().strftime("%Y-%m-%d")
        result = [p for p in plans if p.get("student_id") == int(student_id) and str(p.get("planned_start", ""))[:10] == today_date]
        result.sort(key=lambda x: x.get("planned_start", ""))
        return result


def get_plans_upcoming(student_id: int, days: int = 7) -> list:
    with _LOCK:
        plans = _load_json_file("study_plans.json", [])
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        future_str = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        result = [
            p for p in plans
            if p.get("student_id") == int(student_id) and now_str <= str(p.get("planned_start", "")) <= future_str
        ]
        result.sort(key=lambda x: x.get("planned_start", ""))
        return result


def update_plan_status(plan_id: int, status: str):
    with _LOCK:
        plans = _load_json_file("study_plans.json", [])
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for p in plans:
            if p.get("id") == int(plan_id):
                p["status"] = status
                if status == "completed":
                    p["completed_at"] = now_str
                break
        _save_json_file("study_plans.json", plans)


def mark_plan_notified(plan_id: int):
    with _LOCK:
        plans = _load_json_file("study_plans.json", [])
        for p in plans:
            if p.get("id") == int(plan_id):
                p["notified"] = True
                break
        _save_json_file("study_plans.json", plans)


def get_plan_by_id(plan_id: int) -> dict:
    with _LOCK:
        plans = _load_json_file("study_plans.json", [])
        for p in plans:
            if p.get("id") == int(plan_id):
                return dict(p)
        return None


def get_active_plan_for_topic(student_id: int, topic: str) -> dict:
    """Find a pending plan for today that matches topic (fuzzy)."""
    with _LOCK:
        plans = _load_json_file("study_plans.json", [])
        today = datetime.now().strftime("%Y-%m-%d")
        topic_lower = topic.lower()
        for p in plans:
            if (p.get("student_id") == int(student_id)
                    and p.get("status") == "pending"
                    and str(p.get("planned_start", ""))[:10] == today):
                plan_topic = p.get("topic", "").lower()
                if any(w in plan_topic for w in topic_lower.split() if len(w) > 3):
                    return dict(p)
        return None


def delete_plan(plan_id: int):
    with _LOCK:
        plans = _load_json_file("study_plans.json", [])
        plans = [p for p in plans if p.get("id") != int(plan_id)]
        _save_json_file("study_plans.json", plans)


def get_due_unnotified_plans(student_id: int = None, window_minutes: int = 15) -> list:
    with _LOCK:
        plans = _load_json_file("study_plans.json", [])
        students = {s["id"]: s.get("name", "Student") for s in _load_json_file("students.json", [])}
        now = datetime.now()
        due = []
        for p in plans:
            if p.get("status") == "pending" and not p.get("notified"):
                if student_id and p.get("student_id") != int(student_id):
                    continue
                start_str = str(p.get("planned_start", ""))
                try:
                    p_dt = datetime.strptime(start_str, "%Y-%m-%d %H:%M:%S")
                except Exception:
                    try:
                        p_dt = datetime.fromisoformat(start_str.replace("Z", ""))
                    except Exception:
                        continue

                mins_diff = (p_dt - now).total_seconds() / 60.0
                # Trigger for plans that have arrived (-45 mins to +1 min) or upcoming within window
                if -45 <= mins_diff <= window_minutes:
                    item = dict(p)
                    item["mins_until"] = max(0, int(mins_diff))
                    item["is_due_now"] = (mins_diff <= 1.0)
                    item["student_name"] = students.get(p.get("student_id"), "Student")
                    due.append(item)
        return due


def get_study_streak(student_id: int) -> int:
    """Calculate consecutive days with at least one completed session."""
    with _LOCK:
        sessions = _load_json_file("sessions.json", [])
        student_sess = [s for s in sessions if s.get("student_id") == int(student_id) and s.get("end_time")]
        if not student_sess:
            return 0
        dates = set()
        for s in student_sess:
            try:
                d = str(s.get("start_time", ""))[:10]
                if d:
                    dates.add(d)
            except Exception:
                pass
        streak = 0
        check = datetime.now().date()
        while True:
            if check.strftime("%Y-%m-%d") in dates:
                streak += 1
                check = check - timedelta(days=1)
            else:
                break
        return streak


def get_session_summary(session_id: int) -> dict:
    """Full summary of a completed session."""
    with _LOCK:
        sessions = _load_json_file("sessions.json", [])
        queries = _load_json_file("queries.json", [])
        for s in sessions:
            if s.get("id") == int(session_id):
                start_str = str(s.get("start_time", ""))
                end_str = str(s.get("end_time", ""))
                duration_mins = 0
                if start_str and end_str:
                    try:
                        start_dt = datetime.strptime(start_str, "%Y-%m-%d %H:%M:%S")
                        end_dt   = datetime.strptime(end_str,   "%Y-%m-%d %H:%M:%S")
                        duration_mins = max(0, int((end_dt - start_dt).total_seconds() / 60))
                    except Exception:
                        pass
                q_count = sum(1 for q in queries if q.get("session_id") == int(session_id))
                pomodoros = s.get("pomodoro_count", 0)
                return {
                    "session_id": session_id,
                    "topic": s.get("topic", "General"),
                    "start_time": start_str,
                    "end_time": end_str,
                    "duration_mins": duration_mins,
                    "pomodoro_count": pomodoros,
                    "questions_asked": q_count,
                    "focus_score": round(min(100, (pomodoros * 25 + q_count * 5)), 0)
                }
        return {}


# ─────────────────────────────────────────
#  Notification Log Operations
# ─────────────────────────────────────────
def log_notification(student_id: int, notif_type: str, message: str):
    with _LOCK:
        logs = _load_json_file("notification_log.json", [])
        logs.append({
            "id": _next_id(logs),
            "student_id": int(student_id),
            "type": notif_type,
            "message": message,
            "sent_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })
        _save_json_file("notification_log.json", logs)


def was_notified_recently(student_id: int, notif_type: str, hours: int = 2) -> bool:
    with _LOCK:
        logs = _load_json_file("notification_log.json", [])
        cutoff_str = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
        for l in logs:
            if l.get("student_id") == int(student_id) and l.get("type") == notif_type:
                if str(l.get("sent_at", "")) >= cutoff_str:
                    return True
        return False


def is_reminders_paused(student_id: int = 1) -> dict:
    """Returns {'paused': bool, 'pause_until': str, 'remaining_minutes': int, 'duration_mins': int}."""
    with _LOCK:
        settings = _load_json_file("notification_settings.json", {})
        s_key = str(student_id) if student_id else "1"
        # Query specific student, with fallback to global or default profile "1"
        student_setting = settings.get(s_key) or settings.get("global") or settings.get("1") or {}
        if not student_setting.get("paused"):
            return {"paused": False, "pause_until": None, "remaining_minutes": 0, "duration_mins": 0}

        pause_until = student_setting.get("pause_until")
        duration_mins = student_setting.get("duration_mins", -1)
        if not pause_until:
            # Indefinite pause until explicitly resumed
            return {"paused": True, "pause_until": None, "remaining_minutes": -1, "duration_mins": duration_mins}

        try:
            until_dt = datetime.fromisoformat(pause_until)
            now = datetime.now()
            if now < until_dt:
                rem = max(1, int((until_dt - now).total_seconds() / 60))
                return {"paused": True, "pause_until": pause_until, "remaining_minutes": rem, "duration_mins": duration_mins}
            else:
                # Auto-expired
                student_setting["paused"] = False
                student_setting["pause_until"] = None
                settings[s_key] = student_setting
                if "global" in settings:
                    settings["global"]["paused"] = False
                if "1" in settings:
                    settings["1"]["paused"] = False
                _save_json_file("notification_settings.json", settings)
                return {"paused": False, "pause_until": None, "remaining_minutes": 0, "duration_mins": 0}
        except Exception:
            return {"paused": False, "pause_until": None, "remaining_minutes": 0, "duration_mins": 0}


def set_reminders_paused(student_id: int = 1, paused: bool = True, duration_mins: int = -1) -> dict:
    """
    Sets reminders pause status for a student and global app setting.
    duration_mins = -1 means indefinite (until resumed manually).
    duration_mins > 0 means pause for that number of minutes.
    """
    with _LOCK:
        settings = _load_json_file("notification_settings.json", {})
        s_key = str(student_id) if student_id else "1"
        if paused:
            pause_until = None
            if duration_mins > 0:
                until_dt = datetime.now() + timedelta(minutes=duration_mins)
                pause_until = until_dt.isoformat()
            setting_data = {
                "paused": True,
                "paused_at": datetime.now().isoformat(),
                "pause_until": pause_until,
                "duration_mins": duration_mins
            }
            settings[s_key] = setting_data
            settings["global"] = setting_data
            settings["1"] = setting_data
        else:
            setting_data = {
                "paused": False,
                "resumed_at": datetime.now().isoformat(),
                "pause_until": None,
                "duration_mins": 0
            }
            settings[s_key] = setting_data
            settings["global"] = setting_data
            settings["1"] = setting_data
        _save_json_file("notification_settings.json", settings)
    return is_reminders_paused(student_id)


# ─────────────────────────────────────────
#  Live Session Monitoring Stats
# ─────────────────────────────────────────
def get_live_session_stats(session_id: int, student_id: int) -> dict:
    with _LOCK:
        sessions = _load_json_file("sessions.json", [])
        target_session = None
        for s in sessions:
            if s.get("id") == int(session_id):
                target_session = s
                break

        queries = _load_json_file("queries.json", [])
        q_count = sum(1 for q in queries if q.get("session_id") == int(session_id))
        weak = get_weak_areas(student_id, limit=3)

        if not target_session:
            return {}

        now = datetime.now()
        start = target_session.get("start_time")
        elapsed_mins = 0
        if start:
            try:
                start_dt = datetime.fromisoformat(str(start)) if isinstance(start, str) else start
                elapsed_mins = int((now - start_dt).total_seconds() / 60)
            except Exception:
                elapsed_mins = 0

        pomodoros = target_session.get("pomodoro_count", 0)
        focus_score = round((q_count / max(pomodoros, 1)) * 10, 1)
        pace = "Good" if elapsed_mins > 0 and q_count >= 1 else "Getting Started"

        return {
            "session_id": session_id,
            "topic": target_session.get("topic", "General"),
            "elapsed_mins": elapsed_mins,
            "pomodoro_count": pomodoros,
            "query_count": q_count,
            "focus_score": focus_score,
            "pace": pace,
            "weak_areas": weak,
        }


# ─────────────────────────────────────────
#  Test Attempts Operations
# ─────────────────────────────────────────
def save_test_attempt(
    test_id: str,
    student_id: int,
    topic: str,
    total_score: int,
    total_possible: int,
    percentage: float,
    scores_dict: dict,
    questions_list: list,
    answers_dict: dict,
    time_taken_seconds: int = 0
):
    with _LOCK:
        attempts = _load_json_file("test_attempts.json", [])
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        existing = None
        for a in attempts:
            if a.get("test_id") == test_id:
                existing = a
                break

        if existing:
            existing["total_score"] = total_score
            existing["total_possible"] = total_possible
            existing["percentage"] = percentage
            existing["scores_json"] = json.dumps(scores_dict)
            existing["questions_json"] = json.dumps(questions_list)
            existing["answers_json"] = json.dumps(answers_dict)
            existing["time_taken_seconds"] = time_taken_seconds
            _save_json_file("test_attempts.json", attempts)
            return existing.get("id", 1)
        else:
            new_id = _next_id(attempts)
            record = {
                "id": new_id,
                "test_id": test_id,
                "student_id": int(student_id),
                "topic": topic,
                "total_score": total_score,
                "total_possible": total_possible,
                "percentage": percentage,
                "scores_json": json.dumps(scores_dict),
                "questions_json": json.dumps(questions_list),
                "answers_json": json.dumps(answers_dict),
                "time_taken_seconds": time_taken_seconds,
                "created_at": now_str
            }
            attempts.append(record)
            _save_json_file("test_attempts.json", attempts)
            return new_id


def get_test_history(student_id: int, limit: int = 25) -> list:
    with _LOCK:
        attempts = _load_json_file("test_attempts.json", [])
        student_att = [a for a in attempts if a.get("student_id") == int(student_id)]
        student_att.sort(key=lambda x: x.get("id", 0), reverse=True)

        history = []
        for r in student_att[:limit]:
            try:
                scores = json.loads(r.get("scores_json") or "{}")
            except Exception:
                scores = {}
            created_str = str(r.get("created_at") or "")
            ts = int(datetime.now().timestamp() * 1000)
            if created_str:
                try:
                    ts = int(datetime.strptime(created_str, "%Y-%m-%d %H:%M:%S").timestamp() * 1000)
                except Exception:
                    pass

            history.append({
                "testId": r.get("test_id"),
                "topic": r.get("topic") or "General Test",
                "totalScore": r.get("total_score", 0),
                "totalPossible": r.get("total_possible", 0),
                "percentage": r.get("percentage", 0.0),
                "scores": scores,
                "timeTakenSeconds": r.get("time_taken_seconds", 0),
                "createdAt": created_str,
                "timestamp": ts
            })
        return history


def get_test_attempt(test_id: str) -> dict:
    with _LOCK:
        attempts = _load_json_file("test_attempts.json", [])
        for r in attempts:
            if r.get("test_id") == test_id:
                return {
                    "testId": r["test_id"],
                    "studentId": r["student_id"],
                    "topic": r.get("topic"),
                    "totalScore": r.get("total_score", 0),
                    "totalPossible": r.get("total_possible", 0),
                    "percentage": r.get("percentage", 0.0),
                    "scores": json.loads(r.get("scores_json") or "{}"),
                    "questions": json.loads(r.get("questions_json") or "[]"),
                    "answers": json.loads(r.get("answers_json") or "{}"),
                    "timeTakenSeconds": r.get("time_taken_seconds", 0),
                    "createdAt": str(r.get("created_at"))
                }
        return None


def get_overall_category_performance(student_id: int) -> dict:
    history = get_test_history(student_id, limit=50)
    totals = {
        "Cognitive Memory":     {"score": 0, "total": 0},
        "Logical Reasoning":    {"score": 0, "total": 0},
        "Critical Thinking":    {"score": 0, "total": 0},
        "Creative Application": {"score": 0, "total": 0},
    }

    for test in history:
        scores = test.get("scores", {})
        for cat in totals:
            if cat in scores:
                totals[cat]["score"] += scores[cat].get("score", 0)
                totals[cat]["total"] += scores[cat].get("total", 0)

    results = {}
    for cat, data in totals.items():
        score = data["score"]
        total = data["total"]
        pct = round((score / total) * 100, 1) if total > 0 else 0.0
        results[cat] = {
            "score": score,
            "total": total,
            "percentage": pct
        }
    return results


# ─────────────────────────────────────────
#  Chat Threads & Message Operations (ChatGPT/Gemini Style)
# ─────────────────────────────────────────
def create_chat_thread(thread_id: str, student_id: int, title: str = "New Chat", doc_filter: str = "all") -> bool:
    with _LOCK:
        threads = _load_json_file("chat_threads.json", [])
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        existing = None
        for t in threads:
            if t.get("id") == thread_id:
                existing = t
                break

        if existing:
            existing["title"] = title
            existing["doc_filter"] = doc_filter
            existing["updated_at"] = now_str
        else:
            threads.append({
                "id": thread_id,
                "student_id": int(student_id),
                "title": title,
                "doc_filter": doc_filter,
                "created_at": now_str,
                "updated_at": now_str
            })
        _save_json_file("chat_threads.json", threads)
        return True


def get_chat_threads(student_id: int) -> list:
    with _LOCK:
        threads = _load_json_file("chat_threads.json", [])
        user_threads = [t for t in threads if t.get("student_id") == int(student_id)]
        user_threads.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
        return [
            {
                "id": t["id"],
                "studentId": t["student_id"],
                "title": t.get("title", "New Chat"),
                "docFilter": t.get("doc_filter", "all"),
                "createdAt": str(t.get("created_at")),
                "updatedAt": str(t.get("updated_at")),
            }
            for t in user_threads
        ]


def get_chat_thread(thread_id: str) -> dict:
    with _LOCK:
        threads = _load_json_file("chat_threads.json", [])
        for t in threads:
            if t.get("id") == thread_id:
                return {
                    "id": t["id"],
                    "studentId": t["student_id"],
                    "title": t.get("title", "New Chat"),
                    "docFilter": t.get("doc_filter", "all"),
                    "createdAt": str(t.get("created_at")),
                    "updatedAt": str(t.get("updated_at")),
                }
        return None


def update_chat_thread_title(thread_id: str, title: str) -> bool:
    with _LOCK:
        threads = _load_json_file("chat_threads.json", [])
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for t in threads:
            if t.get("id") == thread_id:
                t["title"] = title
                t["updated_at"] = now_str
                _save_json_file("chat_threads.json", threads)
                return True
        return False


def update_chat_thread_doc_filter(thread_id: str, doc_filter: str) -> bool:
    with _LOCK:
        threads = _load_json_file("chat_threads.json", [])
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for t in threads:
            if t.get("id") == thread_id:
                t["doc_filter"] = doc_filter
                t["updated_at"] = now_str
                _save_json_file("chat_threads.json", threads)
                return True
        return False


def delete_chat_thread(thread_id: str, student_id: int = None) -> bool:
    with _LOCK:
        threads = _load_json_file("chat_threads.json", [])
        if student_id:
            threads = [t for t in threads if not (t.get("id") == thread_id and t.get("student_id") == int(student_id))]
        else:
            threads = [t for t in threads if t.get("id") != thread_id]
        _save_json_file("chat_threads.json", threads)

        # Also delete messages in this thread
        messages = _load_json_file("chat_messages.json", [])
        messages = [m for m in messages if m.get("thread_id") != thread_id]
        _save_json_file("chat_messages.json", messages)
        return True


def save_chat_message(thread_id: str, sender: str, content: str, sources: list = None, action: dict = None) -> int:
    with _LOCK:
        messages = _load_json_file("chat_messages.json", [])
        new_id = _next_id(messages)
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        record = {
            "id": new_id,
            "thread_id": thread_id,
            "sender": sender,
            "content": content,
            "sources": sources or [],
            "action": action,
            "created_at": now_str
        }
        messages.append(record)
        _save_json_file("chat_messages.json", messages)

        # Touch the thread's updated_at
        threads = _load_json_file("chat_threads.json", [])
        for t in threads:
            if t.get("id") == thread_id:
                t["updated_at"] = now_str
                break
        _save_json_file("chat_threads.json", threads)
        return new_id


def get_chat_messages(thread_id: str, limit: int = 100) -> list:
    with _LOCK:
        messages = _load_json_file("chat_messages.json", [])
        thread_msgs = [m for m in messages if m.get("thread_id") == thread_id]
        thread_msgs.sort(key=lambda x: x.get("id", 0))
        result = []
        for m in thread_msgs[-limit:]:
            result.append({
                "id": m.get("id"),
                "threadId": m.get("thread_id"),
                "sender": m.get("sender"),
                "content": m.get("content"),
                "sources": m.get("sources") or [],
                "action": m.get("action"),
                "createdAt": str(m.get("created_at"))
            })
        return result


# ─────────────────────────────────────────────────────────────
#  User Personal Notes (Quick Tools -> Notes)
# ─────────────────────────────────────────────────────────────
def get_user_notes(student_id: int) -> list:
    """Retrieves all personal notes created by the student."""
    with _LOCK:
        notes = _load_json_file("user_notes.json", [])
        student_notes = [n for n in notes if n.get("student_id") == int(student_id)]
        student_notes.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
        return student_notes


def save_user_note(student_id: int, note_id: str, content: str, title: str = None) -> dict:
    """Creates or updates a personal study note."""
    with _LOCK:
        notes = _load_json_file("user_notes.json", [])
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if not title:
            lines = [l.strip() for l in content.split("\n") if l.strip()]
            title = lines[0][:60] if lines else "Untitled Note"

        found = False
        result = None
        for n in notes:
            if str(n.get("id")) == str(note_id) and n.get("student_id") == int(student_id):
                n["content"] = content
                n["title"] = title
                n["updated_at"] = now_str
                found = True
                result = n
                break

        if not found:
            result = {
                "id": str(note_id),
                "student_id": int(student_id),
                "title": title,
                "content": content,
                "created_at": now_str,
                "updated_at": now_str
            }
            notes.insert(0, result)

        _save_json_file("user_notes.json", notes)
        return result


def delete_user_note(student_id: int, note_id: str):
    """Deletes a personal study note."""
    with _LOCK:
        notes = _load_json_file("user_notes.json", [])
        notes = [n for n in notes if not (str(n.get("id")) == str(note_id) and n.get("student_id") == int(student_id))]
        _save_json_file("user_notes.json", notes)

