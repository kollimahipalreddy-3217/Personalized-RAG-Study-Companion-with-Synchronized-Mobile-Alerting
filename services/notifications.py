# ============================================================
#  notifications.py — Autonomous Study Reminder & Scheduling Engine
#  Personalized RAG Study Companion with Synchronized Mobile Alerting
#  Application Interface: StudyEdge AI
# ============================================================

import json
import threading
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler

import db
import alerts

# ─────────────────────────────────────────
#  Scheduler instance (module-level singleton)
# ─────────────────────────────────────────
scheduler = BackgroundScheduler(timezone="Asia/Kolkata")

# ─────────────────────────────────────────
#  In memory session state tracker
#  Tracks: break_started_at, last_question_at, session_start_at
#  per student_id
# ─────────────────────────────────────────
_state = {}  # { student_id: { ... } }

def update_state(student_id, **kwargs):
    sid = int(student_id)
    if sid not in _state:
        _state[sid] = {}
    _state[sid].update(kwargs)

def get_state(student_id, key, default=None):
    return _state.get(int(student_id), {}).get(key, default)


# ─────────────────────────────────────────
#  Core push helper
# ─────────────────────────────────────────
def _push(student_id, title, body, icon="/static/icon-192.png"):
    """Send push to student if they have a subscription and reminders are not paused."""
    try:
        # Check if student has paused reminders (Do Not Disturb)
        pause_info = db.is_reminders_paused(int(student_id))
        if pause_info.get("paused"):
            rem = pause_info.get("remaining_minutes")
            rem_str = "indefinitely" if rem == -1 else f"{rem}m left"
            print(f"[NOTIF] Reminders paused ({rem_str}) for student {student_id}. Suppressing notification: '{title}'")
            return

        sub = db.get_push_subscription(int(student_id))
        if sub:
            alerts.send_push_notification(sub, title, body, icon)
            db.log_notification(int(student_id), "push_alert", f"{title}: {body}")
            print(f"[NOTIF] Sent push alert to student {student_id}: '{title}'")
        else:
            print(f"[NOTIF] No push subscription found for student {student_id}")
    except Exception as e:
        print(f"[NOTIF] Push failed for student {student_id}: {e}")


def _push_all(title, body):
    """Send push to ALL subscribed students (e.g. daily digest)."""
    try:
        subs = db.get_all_push_subscriptions()
        for s in subs:
            _push(s['student_id'], title, body)
    except Exception as e:
        print(f"[NOTIF] push_all failed: {e}")


# ─────────────────────────────────────────
#  Smart Reminder Jobs (Pure Local JSON Storage)
# ─────────────────────────────────────────

def check_due_study_plans():
    """Remind students whose planned study session start time has arrived (within -45m to +1.5m)."""
    try:
        plans = db._load_json_file("study_plans.json", [])
        now = datetime.now()

        for plan in plans:
            if plan.get("status") == "pending" and not plan.get("notified"):
                start_str = str(plan.get("planned_start", ""))
                try:
                    p_dt = datetime.strptime(start_str, "%Y-%m-%d %H:%M:%S")
                except Exception:
                    try:
                        p_dt = datetime.fromisoformat(start_str.replace("Z", ""))
                    except Exception:
                        continue

                mins_diff = (p_dt - now).total_seconds() / 60.0
                if -45 <= mins_diff <= 1.5:
                    topic = plan.get("topic", "Scheduled Topic")
                    sid = plan.get("student_id", 1)
                    _push(
                        sid,
                        " Time to Study!",
                        f"Your planned session for '{topic}' is starting now! Tap to begin your focus sprint.",
                        "/static/icon-192.png"
                    )
                    db.mark_plan_notified(plan["id"])
                    print(f"[NOTIF] Dispatched study reminder for plan {plan['id']} ('{topic}')")
    except Exception as e:
        print(f"[NOTIF] check_due_study_plans error: {e}")


def check_planned_sessions_not_started():
    """Remind students who planned a session but haven't started it yet (10+ min late)."""
    try:
        plans = db._load_json_file("study_plans.json", [])
        now = datetime.now()
        ten_min_ago = now - timedelta(minutes=10)
        two_hours_ago = now - timedelta(hours=2)

        for plan in plans:
            if plan.get("status") == "pending":
                start_str = str(plan.get("planned_start", ""))
                try:
                    p_dt = datetime.strptime(start_str, "%Y-%m-%d %H:%M:%S")
                except Exception:
                    try:
                        p_dt = datetime.fromisoformat(start_str.replace("Z", ""))
                    except Exception:
                        continue

                if two_hours_ago <= p_dt <= ten_min_ago and not plan.get("notified"):
                    topic = plan.get("topic", "Scheduled Topic")
                    sid = plan.get("student_id", 1)
                    _push(
                        sid,
                        " Study Reminder",
                        f"You planned to study '{topic}' — ready to begin? Tap to start your session!",
                        "/static/icon-192.png"
                    )
                    db.mark_plan_notified(plan["id"])
    except Exception as e:
        print(f"[NOTIF] check_planned_sessions error: {e}")


def check_missed_sessions():
    """Notify students whose planned session start time passed 2+ hours ago and never started."""
    try:
        plans = db._load_json_file("study_plans.json", [])
        now = datetime.now()
        two_hours_ago = now - timedelta(hours=2)
        yesterday = now - timedelta(hours=24)

        for plan in plans:
            if plan.get("status") in ("pending", "notified"):
                start_str = str(plan.get("planned_start", ""))
                try:
                    p_dt = datetime.strptime(start_str, "%Y-%m-%d %H:%M:%S")
                except Exception:
                    continue

                if yesterday <= p_dt < two_hours_ago:
                    topic = plan.get("topic", "Scheduled Topic")
                    sid = plan.get("student_id", 1)
                    _push(
                        sid,
                        "Missed Study Session",
                        f"You missed your planned session for '{topic}'. Don't skip — even 15 min counts!",
                        "/static/icon-192.png"
                    )
                    db.update_plan_status(plan["id"], "missed")
    except Exception as e:
        print(f"[NOTIF] check_missed_sessions error: {e}")


def check_no_session_today():
    """Remind students who haven't started any session today."""
    try:
        now = datetime.now()
        hour = now.hour
        if not (9 <= hour <= 21):
            return

        today_prefix = now.strftime("%Y-%m-%d")
        sessions = db._load_json_file("sessions.json", [])
        active_today_sids = {s.get("student_id") for s in sessions if str(s.get("start_time", "")).startswith(today_prefix)}

        subs = db.get_all_push_subscriptions()
        for sub in subs:
            sid = sub.get("student_id")
            if sid and sid not in active_today_sids:
                if not db.was_notified_recently(sid, "no_session_today", hours=8):
                    _push(
                        sid,
                        "Daily Study Goal",
                        "You haven't started a study session today! Open StudyEdge AI to keep your momentum going.",
                        "/static/icon-192.png"
                    )
                    db.log_notification(sid, "no_session_today", "Daily study check")
    except Exception as e:
        print(f"[NOTIF] check_no_session_today error: {e}")


def check_study_streak():
    """Notify students who have a gap of 24h or 48h since last session."""
    try:
        now = datetime.now()
        sessions = db._load_json_file("sessions.json", [])
        subs = db.get_all_push_subscriptions()

        for sub in subs:
            sid = sub.get("student_id")
            student_sess = [s for s in sessions if s.get("student_id") == sid and s.get("end_time")]
            if not student_sess:
                continue

            last_s = max(student_sess, key=lambda x: str(x.get("end_time", "")))
            try:
                last_dt = datetime.strptime(str(last_s.get("end_time")), "%Y-%m-%d %H:%M:%S")
            except Exception:
                continue

            gap = now - last_dt
            topic = last_s.get("topic") or "your last topic"

            if timedelta(hours=23) <= gap <= timedelta(hours=25):
                _push(sid, " Don't Break Your Streak!",
                      f"It's been 24 hours since you studied '{topic}'. Jump back in — consistency is key!")
            elif timedelta(hours=47) <= gap <= timedelta(hours=49):
                _push(sid, "Study Reminder",
                      f"2 days since you touched '{topic}'! Even a quick 25-min Pomodoro will help.")
    except Exception as e:
        print(f"[NOTIF] check_study_streak error: {e}")


def check_slow_sessions():
    """Detect sessions where student hasn't asked a question in 15+ min (possibly stuck/distracted)."""
    try:
        now = datetime.now()
        for student_id, state in list(_state.items()):
            if not state.get('session_active'):
                continue
            last_q = state.get('last_question_at')
            session_start = state.get('session_start_at')
            if not session_start:
                continue
            elapsed_mins = (now - session_start).total_seconds() / 60
            if elapsed_mins < 20:
                continue
            mins_since = elapsed_mins if last_q is None else (now - last_q).total_seconds() / 60
            if mins_since >= 15 and not state.get('slow_notified'):
                _push(student_id, " Feeling Stuck?",
                      "You haven't asked the AI anything in 15 minutes. Try asking a question about your notes to stay engaged!")
                update_state(student_id, slow_notified=True)
            elif mins_since < 15:
                update_state(student_id, slow_notified=False)
    except Exception as e:
        print(f"[NOTIF] check_slow_sessions error: {e}")


def check_long_sessions():
    """Alert students who have been studying 90+ minutes without a long break."""
    try:
        now = datetime.now()
        for student_id, state in list(_state.items()):
            if not state.get('session_active'):
                continue
            session_start = state.get('session_start_at')
            if not session_start:
                continue
            elapsed_mins = (now - session_start).total_seconds() / 60
            if elapsed_mins >= 90 and not state.get('long_session_notified'):
                _push(student_id, " Take a Proper Break!",
                      f"You've been studying for {int(elapsed_mins)} minutes! Take a 15-minute break to recharge your mind.")
                update_state(student_id, long_session_notified=True)
    except Exception as e:
        print(f"[NOTIF] check_long_sessions error: {e}")


def check_break_not_returned():
    """Notify student if break started 7+ min ago and session not restarted."""
    try:
        now = datetime.now()
        for student_id, state in list(_state.items()):
            break_at = state.get('break_started_at')
            if not break_at:
                continue
            mins_on_break = (now - break_at).total_seconds() / 60
            break_type = state.get('break_type', 'short')
            warn_after = 7 if break_type == 'short' else 18
            if mins_on_break >= warn_after and not state.get('break_overrun_notified'):
                topic = state.get('current_topic', 'your study topic')
                _push(student_id, " Break is Over!",
                      f"Your break ended {int(mins_on_break - (5 if break_type == 'short' else 15))} min ago. Time to get back to '{topic}'!")
                update_state(student_id, break_overrun_notified=True)
    except Exception as e:
        print(f"[NOTIF] check_break_not_returned error: {e}")


# ─────────────────────────────────────────
#  Event Hooks (called from app.py)
# ─────────────────────────────────────────

def on_session_started(student_id, session_id, topic):
    update_state(student_id,
        session_active=True,
        session_id=session_id,
        current_topic=topic,
        session_start_at=datetime.now(),
        last_question_at=None,
        break_started_at=None,
        slow_notified=False,
        long_session_notified=False,
        break_overrun_notified=False,
        pomodoro_round=0
    )

def on_session_ended(student_id):
    update_state(student_id,
        session_active=False,
        break_started_at=None,
        session_start_at=None
    )

def on_question_asked(student_id):
    update_state(student_id,
        last_question_at=datetime.now(),
        slow_notified=False
    )

def on_break_started(student_id, break_type='short'):
    update_state(student_id,
        break_started_at=datetime.now(),
        break_type=break_type,
        break_overrun_notified=False
    )

def on_break_ended(student_id):
    update_state(student_id,
        break_started_at=None,
        break_overrun_notified=False
    )

def on_pomodoro_complete(student_id):
    current_round = get_state(student_id, 'pomodoro_round', 0) + 1
    update_state(student_id, pomodoro_round=current_round)
    break_type = 'long' if current_round % 4 == 0 else 'short'
    on_break_started(student_id, break_type)
    topic = get_state(student_id, 'current_topic', 'your topic')
    duration = 15 if break_type == 'long' else 5
    _push(student_id,
        f" Pomodoro {current_round} Complete!",
        f"Great work on '{topic}'! Take a {duration}-minute {'long' if break_type == 'long' else 'short'} break."
    )
    return break_type


# ─────────────────────────────────────────
#  Scheduler Startup
# ─────────────────────────────────────────

def start_scheduler():
    """Start the background notification scheduler."""
    if scheduler.running:
        return

    # Every 30 seconds: check for study sessions whose start time has arrived
    scheduler.add_job(check_due_study_plans, 'interval', seconds=30, id='due_study_plans')

    # Every 2 minutes: check for planned sessions not started (10+ min late catch-up)
    scheduler.add_job(check_planned_sessions_not_started, 'interval', minutes=2, id='planned_not_started')

    # Every 15 minutes: check for missed sessions
    scheduler.add_job(check_missed_sessions, 'interval', minutes=15, id='missed_sessions')

    # Real time session monitoring
    scheduler.add_job(check_slow_sessions, 'interval', minutes=2, id='slow_sessions')
    scheduler.add_job(check_long_sessions, 'interval', minutes=2, id='long_sessions')
    scheduler.add_job(check_break_not_returned, 'interval', minutes=1, id='break_overrun')

    # Daily checks
    scheduler.add_job(check_study_streak, 'cron', hour=9, minute=0, id='streak_check')
    scheduler.add_job(check_no_session_today, 'cron', hour=12, minute=0, id='no_session_noon')
    scheduler.add_job(check_no_session_today, 'cron', hour=19, minute=0, id='no_session_today')

    scheduler.start()
    print("[SCHEDULER] Smart notification scheduler started (Pure Local Storage).")
