# ============================================================
#  app.py — Personalized RAG Study Companion Backend
#  Application Name: StudyEdge AI
# ============================================================

import os, sys, re, json, threading, time, uuid, requests as rq
from datetime import datetime
from flask import Flask, request, jsonify, render_template, session, send_from_directory
from flask_socketio import SocketIO, emit
from werkzeug.utils import secure_filename

# Ensure root, core, services, and config are in sys.path
_ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
for _p in [_ROOT_DIR, os.path.join(_ROOT_DIR, "core"), os.path.join(_ROOT_DIR, "services"), os.path.join(_ROOT_DIR, "config")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from services import db
from core import rag_engine, reports, mcq_test, cross_module_agent, pdf_indexer
from services import notifications
from services.alerts import send_push_notification, VAPID_PUBLIC_KEY
from config import (HOST, PORT, DEBUG, UPLOAD_FOLDER, MAX_CONTENT_LENGTH,
                    WEAK_AREA_THRESHOLD, POMODORO_MINUTES,
                    SHORT_BREAK_MINUTES, LONG_BREAK_MINUTES, OLLAMA_BASE_URL, MODELS)

# ─────────────────────────────────────────
#  Load VAPID public key from vapid_config.json
# ─────────────────────────────────────────
_VAPID_PUBLIC_KEY = ""
try:
    if os.path.exists('vapid_config.json'):
        with open('vapid_config.json') as f:
            _VAPID_PUBLIC_KEY = json.load(f).get('VAPID_PUBLIC_KEY', '')
except Exception:
    pass

# ─────────────────────────────────────────
#  App Initialization
# ─────────────────────────────────────────
app = Flask(__name__)
app.secret_key = "studyedge_secret_2024"
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH
socketio = SocketIO(app, cors_allowed_origins="*")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

@app.errorhandler(413)
def request_entity_too_large(error):
    return jsonify({"error": "File size exceeds the 100MB limit. Please upload a PDF under 100MB."}), 413

# Per session Pomodoro state
active_timers = {}
_test_jobs = {}


# ─────────────────────────────────────────
#  Ollama Model Auto Discovery & Health
# ─────────────────────────────────────────
_model_status = {}

def check_and_warm_models():
    """Ensure Ollama daemon is running and discover installed models."""
    global _model_status
    rag_engine.ensure_ollama_running()
    installed = rag_engine.get_available_models()
    print(f"[OLLAMA] Server active. Installed models: {installed}")
    
    # Mark installed models as ready
    for key, model_name in MODELS.items():
        base = model_name.split(":")[0]
        if any(base in m for m in installed) or len(installed) > 0:
            _model_status[model_name] = 'ready'
        else:
            _model_status[model_name] = 'ready'


# ─────────────────────────────────────────
#  Routes: Serve Pages
# ─────────────────────────────────────────
@app.route("/")
@app.route("/login", methods=["GET"])
def login_page():
    return render_template("login.html")


@app.route("/current-user", methods=["GET"])
def get_current_user():
    student_id = session.get("student_id") or request.args.get("student_id") or 1
    student = db.get_student_by_id(int(student_id))
    if student:
        return jsonify({"success": True, "student": student, "student_id": int(student_id), "name": student.get("name")})
    return jsonify({"success": True, "student_id": int(student_id), "name": "Student"})


@app.route("/dashboard")
def dashboard():
    return render_template("dashboard.html")


@app.route("/mobile")
def mobile_companion():
    return render_template("mobile.html")


@app.route("/download/StudyEdge.apk")
def download_studyedge_apk():
    response = send_from_directory("static/downloads", "StudyEdge.apk", as_attachment=True, mimetype="application/vnd.android.package-archive")
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response




# ─────────────────────────────────────────
#  Route: Service Worker (must be at root scope)
# ─────────────────────────────────────────
@app.route("/sw.js")
def service_worker():
    return send_from_directory("static", "sw.js",
                               mimetype="application/javascript")


# ─────────────────────────────────────────
#  Route: Startup / Model Status
# ─────────────────────────────────────────
@app.route("/startup-status")
def startup_status():
    rag_engine.ensure_ollama_running()
    installed = rag_engine.get_available_models()
    all_configured = list(set(MODELS.values()))
    ready_list = installed if installed else all_configured
    
    return jsonify({
        "ready": ready_list,
        "warming": [],
        "failed": [],
        "all_ready": True,
        "installed": installed,
        "vapid_public_key": _VAPID_PUBLIC_KEY
    })


# ─────────────────────────────────────────
#  Route: Login
# ─────────────────────────────────────────
@app.route("/login", methods=["POST"])
def login():
    data = request.get_json() or {}
    name = data.get("name", "").strip() or data.get("username", "").strip()
    if not name:
        return jsonify({"error": "Name is required"}), 400
    student = db.get_student_by_name(name)
    if not student:
        student_id = db.create_student(name)
    else:
        student_id = student["id"]
    session["student_id"]   = student_id
    session["student_name"] = name
    return jsonify({"success": True, "student_id": student_id, "name": name,
                    "vapid_public_key": _VAPID_PUBLIC_KEY})


# ─────────────────────────────────────────
#  Route: Subscribe to Push (Web Push VAPID)
# ─────────────────────────────────────────
@app.route("/subscribe", methods=["POST"])
def subscribe():
    data         = request.get_json()
    student_id   = data.get("student_id")
    subscription = data.get("subscription")
    if not student_id or not subscription:
        return jsonify({"error": "Missing fields"}), 400
    db.save_push_subscription(student_id, json.dumps(subscription))
    return jsonify({"success": True, "message": "Push subscription saved."})


# ─────────────────────────────────────────
#  Route: VAPID Public Key
# ─────────────────────────────────────────
@app.route("/vapid-public-key")
def vapid_public_key():
    return jsonify({"public_key": _VAPID_PUBLIC_KEY})


# ─────────────────────────────────────────
#  Routes: Study Session
# ─────────────────────────────────────────
@app.route("/session/start", methods=["POST"])
def start_session():
    data       = request.get_json() or {}
    student_id = data.get("student_id") or 1
    topic      = data.get("topic", "General")
    plan_id    = data.get("plan_id")  # optional: link to a plan

    session_id = db.start_session(student_id, topic, plan_id)

    # Mark linked plan as active
    if plan_id:
        db.update_plan_status(plan_id, 'active')

    # Notify the smart engine
    notifications.on_session_started(student_id, session_id, topic)

    # Real time multi-device sync broadcast
    socketio.emit("session_started", {
        "session_id": session_id,
        "student_id": int(student_id),
        "topic": topic,
        "plan_id": plan_id
    })

    return jsonify({"success": True, "session_id": session_id})


@app.route("/session/end", methods=["POST"])
def end_session():
    data       = request.get_json() or {}
    session_id = data.get("session_id")
    student_id = data.get("student_id") or 1

    if session_id:
        db.end_session(session_id)
    if student_id:
        db.end_all_active_sessions_for_student(student_id)
        notifications.on_session_ended(int(student_id))

    # Stop and clear all active timers for this session or student
    for sid in list(active_timers.keys()):
        tdata = active_timers.get(sid, {})
        if str(sid) == str(session_id) or str(tdata.get("student_id")) == str(student_id):
            tdata["running"] = False
            active_timers.pop(sid, None)

    # Real time multi-device sync broadcast
    socketio.emit("session_ended", {
        "session_id": session_id,
        "student_id": int(student_id)
    })

    return jsonify({"success": True})


@app.route("/session/active", methods=["GET"])
def get_active_session():
    student_id = request.args.get("student_id") or 1
    student_id = int(student_id)

    # 1. Check if an active timer is running in active_timers
    for sess_id, timer_data in list(active_timers.items()):
        if timer_data.get("student_id") == student_id and timer_data.get("running"):
            return jsonify({
                "has_active": True,
                "session_id": sess_id,
                "topic": timer_data.get("topic", "Focus Session"),
                "seconds_left": timer_data.get("seconds_left", 1500),
                "total_secs": timer_data.get("total_secs", 1500),
                "is_break": timer_data.get("is_break", False),
                "break_type": timer_data.get("break_type", "short"),
                "round": notifications._state.get(student_id, {}).get('pomodoro_round', 1),
                "running": True,
                "milestones": timer_data.get("milestones", [])
            })

    # 2. Check if an active session was started in database and has not ended
    active_sess = db.get_active_session_for_student(student_id)
    if active_sess and not active_sess.get("end_time"):
        sess_id = active_sess.get("id")
        timer_data = active_timers.get(str(sess_id)) or active_timers.get(sess_id) or {}
        return jsonify({
            "has_active": True,
            "session_id": sess_id,
            "topic": active_sess.get("topic", "Focus Session"),
            "seconds_left": timer_data.get("seconds_left", 1500),
            "total_secs": timer_data.get("total_secs", 1500),
            "is_break": timer_data.get("is_break", False),
            "break_type": timer_data.get("break_type", "short"),
            "round": notifications._state.get(student_id, {}).get('pomodoro_round', 1),
            "running": timer_data.get("running", False),
            "milestones": timer_data.get("milestones") or active_sess.get("milestones", [])
        })

    # If no active session exists in DB or active timers, return False
    return jsonify({"has_active": False})


CURRICULUM_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "curriculum")
os.makedirs(CURRICULUM_DIR, exist_ok=True)
_curriculum_generating_lock = threading.Lock()
_curriculum_generating_sessions = set()


@app.route("/session/preview-plan", methods=["POST"])
def preview_study_plan():
    data = request.get_json() or {}
    topic = data.get("topic", "Focus Study").strip()
    doc_name = data.get("doc_name")
    student_id = data.get("student_id") or 1
    if doc_name and str(doc_name).startswith("saved_session:"):
        saved_id = doc_name.split(":")[1]
        cur_file = os.path.join(CURRICULUM_DIR, f"curriculum_{saved_id}.json")
        if os.path.exists(cur_file):
            try:
                with open(cur_file, "r", encoding="utf-8") as f:
                    cdata = json.load(f)
                overview = cdata.get("overview") or f"A comprehensive 4-stage study curriculum on {topic} based on your saved notes."
                return jsonify({
                    "success": True,
                    "summary": overview,
                    "source": f"Saved Notes (Session #{saved_id})",
                    "total_mins": cdata.get("total_suggested_mins", 75)
                })
            except Exception:
                pass
    elif doc_name and (str(doc_name).startswith("my_note:") or str(doc_name).startswith("user_note:")):
        nid = str(doc_name).split(":")[1]
        user_notes = db.get_user_notes(int(student_id))
        target_note = next((n for n in user_notes if str(n.get("id")) == nid), None)
        if target_note:
            ntitle = target_note.get("title", topic)
            return jsonify({
                "success": True,
                "topic": topic,
                "summary": f"Personalized 4-stage study sprint formulated directly from your note '{ntitle}'. Covers key concepts, definitions, and active recall drills.",
                "source": f"Personal Note: {ntitle}",
                "total_mins": 75,
                "stages": [
                    "Stage 1: Core Definitions & Formula Intuition (20m)",
                    "Stage 2: Notes Synthesis & Mechanism Breakdown (25m)",
                    "Stage 3: Active Recall & Note Application Drills (15m)",
                    "Stage 4: Notes Verification & Mastery Quiz (15m)"
                ]
            })
    preview = rag_engine.generate_plan_preview(topic, doc_name=doc_name, student_id=int(student_id))
    return jsonify({"success": True, **preview})


@app.route("/session/curriculum/generate", methods=["POST"])
def generate_curriculum_route():
    data = request.get_json() or {}
    topic = data.get("topic", "Focus Study")
    student_id = data.get("student_id") or 1
    session_id = data.get("session_id")
    doc_name = data.get("doc_name")
    custom_focus = data.get("custom_focus")

    # Guard: If session was already ended, terminate immediately
    if session_id:
        sess = db.get_session_by_id(int(session_id))
        if not sess or sess.get("end_time"):
            print(f"[CURRICULUM] Session {session_id} is inactive or already ended. Aborting generation.")
            return jsonify({"success": False, "message": "Session is inactive or already ended."})

        # Check if curriculum for this session already exists on disk
        cur_file = os.path.join(CURRICULUM_DIR, f"curriculum_{session_id}.json")
        if os.path.exists(cur_file):
            try:
                with open(cur_file, "r", encoding="utf-8") as f:
                    cached_curriculum = json.load(f)
                socketio.emit("curriculum_ready", {
                    "session_id": int(session_id),
                    "student_id": int(student_id),
                    "topic": topic,
                    "curriculum": cached_curriculum
                })
                return jsonify({"success": True, "curriculum": cached_curriculum})
            except Exception:
                pass

        # If another concurrent request is currently generating this session, wait for it
        wait_start = time.time()
        while str(session_id) in _curriculum_generating_sessions:
            if time.time() - wait_start > 35:
                break
            time.sleep(0.5)
            if os.path.exists(cur_file):
                try:
                    with open(cur_file, "r", encoding="utf-8") as f:
                        cached_curriculum = json.load(f)
                    socketio.emit("curriculum_ready", {
                        "session_id": int(session_id),
                        "student_id": int(student_id),
                        "topic": topic,
                        "curriculum": cached_curriculum
                    })
                    return jsonify({"success": True, "curriculum": cached_curriculum})
                except Exception:
                    pass

    with _curriculum_generating_lock:
        if session_id:
            _curriculum_generating_sessions.add(str(session_id))

    try:
        if doc_name and str(doc_name).startswith("saved_session:"):
            saved_id = doc_name.split(":")[1]
            cur_file = os.path.join(CURRICULUM_DIR, f"curriculum_{saved_id}.json")
            if os.path.exists(cur_file):
                try:
                    with open(cur_file, "r", encoding="utf-8") as f:
                        curriculum = json.load(f)
                    curriculum["session_id"] = session_id
                    if session_id:
                        new_file = os.path.join(CURRICULUM_DIR, f"curriculum_{session_id}.json")
                        with open(new_file, "w", encoding="utf-8") as f:
                            json.dump(curriculum, f, indent=2, ensure_ascii=False)
                        socketio.emit("curriculum_ready", {
                            "session_id": int(session_id),
                            "student_id": int(student_id),
                            "topic": topic,
                            "curriculum": curriculum
                        })
                    return jsonify({"success": True, "curriculum": curriculum})
                except Exception:
                    pass

        curriculum = rag_engine.generate_study_curriculum(
            topic,
            student_id=int(student_id),
            doc_name=doc_name,
            custom_focus=custom_focus
        )

        # Reverify session activity after AI generation completes
        if session_id:
            sess = db.get_session_by_id(int(session_id))
            if not sess or sess.get("end_time"):
                print(f"[CURRICULUM] Session {session_id} was terminated during formulation. Discarding output.")
                return jsonify({"success": False, "message": "Session was terminated during formulation."})

            cur_file = os.path.join(CURRICULUM_DIR, f"curriculum_{session_id}.json")
            try:
                with open(cur_file, "w", encoding="utf-8") as f:
                    json.dump(curriculum, f, indent=2, ensure_ascii=False)
            except Exception as e:
                print(f"[CURRICULUM SAVE ERROR]: {e}")

            # Automatically extract and sync canonical sprint milestones from curriculum stages
            rounds = curriculum.get("rounds") or []
            if rounds:
                canon_milestones = []
                for r in rounds:
                    r_num = r.get("round_number", 1)
                    r_title = r.get("title", f"Stage {r_num}")
                    r_obj = r.get("objective") or r.get("focus") or f"Master concepts for Stage {r_num}"
                    canon_milestones.append({
                        "title": f"Stage {r_num}: {r_title}",
                        "goal": r_obj,
                        "tip": "Study the guide notes and complete the stage practice drill.",
                        "done": False
                    })
                db.save_session_milestones(int(session_id), canon_milestones)
                if int(session_id) in active_timers:
                    active_timers[int(session_id)]["milestones"] = canon_milestones
                socketio.emit("milestones_updated", {
                    "session_id": int(session_id),
                    "milestones": canon_milestones
                })
                print(f"[MILESTONES] Synced {len(canon_milestones)} canonical milestones for session {session_id} ('{topic}')")

            # Broadcast curriculum_ready so desktop Output Studio renders immediately
            socketio.emit("curriculum_ready", {
                "session_id": int(session_id),
                "student_id": int(student_id),
                "topic": topic,
                "curriculum": curriculum
            })
            print(f"[CURRICULUM] Broadcasted curriculum_ready for session {session_id} ('{topic}')")

        return jsonify({"success": True, "curriculum": curriculum})
    finally:
        with _curriculum_generating_lock:
            if session_id:
                _curriculum_generating_sessions.discard(str(session_id))


@app.route("/session/curriculum", methods=["GET"])
def get_curriculum_route():
    session_id = request.args.get("session_id")
    if not session_id:
        student_id = request.args.get("student_id", 1)
        active = db.get_active_session_for_student(int(student_id))
        if active:
            session_id = active.get("id")
        else:
            return jsonify({"has_curriculum": False})

    cur_file = os.path.join(CURRICULUM_DIR, f"curriculum_{session_id}.json")
    if os.path.exists(cur_file):
        try:
            with open(cur_file, "r", encoding="utf-8") as f:
                curriculum = json.load(f)
            return jsonify({"has_curriculum": True, "curriculum": curriculum, "session_id": session_id})
        except Exception:
            pass

    return jsonify({"has_curriculum": False})


@app.route("/session/curriculum/expand", methods=["POST"])
def expand_curriculum_route():
    data = request.get_json() or {}
    session_id = data.get("session_id")
    topic = data.get("topic", "General")
    round_idx = int(data.get("round_idx", 0))
    expand_type = data.get("expand_type", "more_drills")  # more_drills | more_checkpoints | deeper_notes | replan_round
    student_id = int(data.get("student_id", 1))

    cur_file = os.path.join(CURRICULUM_DIR, f"curriculum_{session_id}.json")
    if not os.path.exists(cur_file):
        return jsonify({"error": "Curriculum not found"}), 404

    with open(cur_file, "r", encoding="utf-8") as f:
        curriculum = json.load(f)

    rounds = curriculum.get("rounds", [])
    if round_idx >= len(rounds):
        return jsonify({"error": "Invalid round index"}), 400

    r = rounds[round_idx]
    r_title = r.get("title", topic)
    doc_name = curriculum.get("doc_name")

    if expand_type == "more_drills":
        new_drills = rag_engine.generate_more_drills(topic, r_title, student_id=student_id, session_id=session_id, doc_name=doc_name)
        existing = r.get("practice_drills", [])
        existing.extend(new_drills)
        r["practice_drills"] = existing

    elif expand_type == "more_checkpoints":
        new_checkpoints = rag_engine.generate_more_checkpoints(topic, r_title, student_id=student_id)
        existing = r.get("active_checkpoints", [])
        existing.extend(new_checkpoints)
        r["active_checkpoints"] = existing

    elif expand_type == "deeper_notes":
        extra_notes = rag_engine.generate_deeper_notes(topic, r_title, student_id=student_id, session_id=session_id, doc_name=doc_name)
        r["study_content_markdown"] = (r.get("study_content_markdown", "") + "\n\n" + extra_notes).strip()

    elif expand_type == "replan_round":
        fresh_round = rag_engine.replan_single_round(topic, r.get("round_number", round_idx + 1), student_id=student_id)
        rounds[round_idx] = fresh_round

    with open(cur_file, "w", encoding="utf-8") as f:
        json.dump(curriculum, f, indent=2, ensure_ascii=False)

    return jsonify({"success": True, "curriculum": curriculum, "round": rounds[round_idx]})


@app.route("/session/saved-list", methods=["GET"])
def list_saved_sessions():
    """Lists all saved study sessions with their metadata."""
    saved = []
    if os.path.exists(CURRICULUM_DIR):
        for fname in os.listdir(CURRICULUM_DIR):
            if fname.startswith("curriculum_") and fname.endswith(".json"):
                sid_str = fname.replace("curriculum_", "").replace(".json", "")
                fpath = os.path.join(CURRICULUM_DIR, fname)
                try:
                    mtime = os.path.getmtime(fpath)
                    created_dt = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
                    with open(fpath, "r", encoding="utf-8") as f:
                        cdata = json.load(f)
                    saved.append({
                        "session_id": sid_str,
                        "topic": cdata.get("topic", "Study Session"),
                        "overview": cdata.get("overview", ""),
                        "rounds_count": len(cdata.get("rounds", [])),
                        "total_suggested_mins": cdata.get("total_suggested_mins", 75),
                        "source_type": cdata.get("source_type", "Notes + Web"),
                        "created_at": created_dt,
                        "saved_state": cdata.get("saved_state")
                    })
                except Exception:
                    pass
    saved.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return jsonify({"success": True, "sessions": saved})


@app.route("/session/saved/<session_id>", methods=["DELETE"])
def delete_saved_session(session_id):
    """Deletes only the saved curriculum session details without touching any tests, scores, or reports."""
    cur_file = os.path.join(CURRICULUM_DIR, f"curriculum_{session_id}.json")
    if os.path.exists(cur_file):
        try:
            os.remove(cur_file)
            return jsonify({"success": True, "message": "Saved session details deleted. All test results and reports remain preserved."})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    return jsonify({"success": True, "message": "Session already removed."})


@app.route("/session/load", methods=["POST"])
def load_saved_session():
    """Resumes or re-learns any saved or ended study session with choice of 'continue' or 'restart'."""
    data = request.get_json() or {}
    session_id = data.get("session_id")
    student_id = int(data.get("student_id") or 1)
    mode = data.get("mode", "continue") # "continue" | "restart"

    if not session_id:
        return jsonify({"error": "Missing session_id"}), 400

    cur_file = os.path.join(CURRICULUM_DIR, f"curriculum_{session_id}.json")
    if not os.path.exists(cur_file):
        return jsonify({"error": "Curriculum file not found"}), 404

    with open(cur_file, "r", encoding="utf-8") as f:
        curriculum = json.load(f)

    topic = curriculum.get("topic", "Study Session")
    saved_state = curriculum.get("saved_state") or {}
    rounds = curriculum.get("rounds", [])

    # Determine target round and remaining seconds
    if mode == "continue" and saved_state:
        target_round_idx = min(saved_state.get("round_idx", 0), max(0, len(rounds) - 1))
        target_round = rounds[target_round_idx] if rounds else {}
        dur_mins = target_round.get("suggested_duration_mins", 25)
        target_secs = saved_state.get("seconds_left", dur_mins * 60)
        round_num = target_round_idx + 1
    else:
        target_round_idx = 0
        target_round = rounds[0] if rounds else {}
        dur_mins = target_round.get("suggested_duration_mins", 25) if rounds else 25
        target_secs = dur_mins * 60
        round_num = 1
    
    # Check if session exists in db or register fresh active session
    new_sess_id = int(session_id)
    try:
        sess = db.get_session(int(session_id))
        if not sess or sess.get("ended_at"):
            new_sess_id = db.create_session(student_id=student_id, topic=topic)
            new_file = os.path.join(CURRICULUM_DIR, f"curriculum_{new_sess_id}.json")
            with open(new_file, "w", encoding="utf-8") as f:
                json.dump(curriculum, f, indent=2, ensure_ascii=False)
    except Exception as ex:
        print(f"[SESSION LOAD DB NOTE]: {ex}")

    t_entry = {
        "seconds_left": target_secs,
        "total_secs": dur_mins * 60,
        "running": False,
        "is_break": False,
        "break_type": None,
        "round": round_num,
        "topic": topic,
        "student_id": student_id,
        "milestones": []
    }
    active_timers[str(new_sess_id)] = t_entry
    active_timers[int(new_sess_id)] = t_entry

    # Extract & save milestones
    try:
        milestones = [
            {
                "title": f"Stage {r.get('round_number', i+1)}: {r.get('title', 'Milestone')}",
                "goal": r.get("objective", f"Complete Stage {i+1}"),
                "tip": f"Duration: {r.get('suggested_duration_mins', 25)}m ({r.get('mode', 'Tutor')})",
                "done": (mode == "continue" and i < target_round_idx)
            }
            for i, r in enumerate(rounds)
        ]
        db.save_session_milestones(new_sess_id, milestones)
        t_entry["milestones"] = milestones
    except Exception:
        pass

    mins = target_secs // 60
    sec = target_secs % 60
    time_str = f"{mins:02d}:{sec:02d}"

    # Broadcast session_started
    socketio.emit("session_started", {
        "session_id": new_sess_id,
        "student_id": student_id,
        "topic": topic,
        "seconds_left": target_secs,
        "total_secs": dur_mins * 60,
        "time_str": time_str,
        "round": round_num
    })

    return jsonify({
        "success": True,
        "session_id": new_sess_id,
        "topic": topic,
        "curriculum": curriculum,
        "round_idx": target_round_idx,
        "seconds_left": target_secs,
        "time_str": time_str,
        "mode": mode
    })


@app.route("/session/pause-save", methods=["POST"])
def pause_save_session():
    """Pauses and saves active study session for later resumption."""
    data = request.get_json() or {}
    session_id = data.get("session_id")
    student_id = int(data.get("student_id") or 1)
    round_idx = data.get("round_idx", 0)

    if session_id:
        _, timer = _find_timer(session_id)
        if timer:
            timer["running"] = False
        cur_file = os.path.join(CURRICULUM_DIR, f"curriculum_{session_id}.json")
        if os.path.exists(cur_file):
            try:
                with open(cur_file, "r", encoding="utf-8") as f:
                    cdata = json.load(f)
                cdata["saved_state"] = {
                    "round_idx": round_idx,
                    "seconds_left": timer.get("seconds_left", 1200) if timer else 1200,
                    "saved_at": datetime.now().isoformat()
                }
                with open(cur_file, "w", encoding="utf-8") as f:
                    json.dump(cdata, f, indent=2, ensure_ascii=False)
            except Exception:
                pass

    return jsonify({"success": True, "message": "Study session paused and saved for later."})


@app.route("/session/curriculum/ask-doubt", methods=["POST"])
def ask_curriculum_doubt():
    """Answers a student's question/doubt about the active session notes or topic."""
    data = request.get_json() or {}
    topic = data.get("topic") or "General Study"
    question = data.get("question") or ""
    round_notes = data.get("round_notes") or ""
    session_id = data.get("session_id")
    student_id = int(data.get("student_id") or 1)

    if not question.strip():
        return jsonify({"error": "Question is required"}), 400

    doc_name = None
    if session_id:
        cur_file = os.path.join(CURRICULUM_DIR, f"curriculum_{session_id}.json")
        if os.path.exists(cur_file):
            try:
                with open(cur_file, "r", encoding="utf-8") as f:
                    cdata = json.load(f)
                doc_name = cdata.get("doc_name")
            except Exception:
                pass

    res = rag_engine.ask_study_doubt(topic, question, round_notes=round_notes, doc_name=doc_name, student_id=student_id)
    return jsonify(res)


@app.route("/session/curriculum/generate-exam", methods=["POST"])
def generate_curriculum_exam():
    """Generates an accurate, full-length test (16, 32, 48, or 60 questions) from all notes and concepts covered in the specified session."""
    from mcq_test import create_mcq_test
    data = request.get_json() or {}
    session_id = data.get("session_id")
    try:
        num_questions = int(data.get("num_questions", 16))
    except (ValueError, TypeError):
        num_questions = 16
    if num_questions not in [16, 32, 48, 60]:
        num_questions = 16

    timer_mode = data.get("timer_mode", "timed")
    try:
        time_limit_minutes = int(data.get("time_limit_minutes", 0))
    except (ValueError, TypeError):
        time_limit_minutes = 0

    if not time_limit_minutes:
        time_limit_minutes = {16: 15, 32: 30, 48: 45, 60: 60}.get(num_questions, 20)

    client_sid = data.get("socket_id", "")

    cur_file = os.path.join(CURRICULUM_DIR, f"curriculum_{session_id}.json")
    if not os.path.exists(cur_file):
        return jsonify({"error": "Session details not found"}), 404

    with open(cur_file, "r", encoding="utf-8") as f:
        curriculum = json.load(f)

    topic = curriculum.get("topic", "Session Mastery Exam")
    rounds = curriculum.get("rounds", [])

    # Assemble granular substantive syllabus chunks from all rounds
    full_context_chunks = []
    if curriculum.get("overview"):
        full_context_chunks.append(f"Overview & Core Strategy of {topic}:\n{curriculum.get('overview')}")

    for r in rounds:
        r_num = r.get("round_number", "")
        r_title = r.get("title", "")
        notes = r.get("study_content_markdown", "")

        # Split notes by headings or double newlines into granular substantive passages
        paras = [p.strip() for p in re.split(r'\n\s*#{1,4}\s+|\n\n+', notes) if len(p.strip()) > 60]
        if paras:
            for p in paras:
                full_context_chunks.append(f"Stage {r_num} ({r_title}):\n{p}")
        elif notes:
            full_context_chunks.append(f"Stage {r_num} ({r_title}):\n{notes}")

        drills = r.get("practice_drills", [])
        if drills:
            d_text = "\n".join([f"Q: {d.get('question')} | Key concept & explanation: {d.get('explanation')}" for d in drills if isinstance(d, dict)])
            full_context_chunks.append(f"Stage {r_num} ({r_title}) Practice Drills & Applied Logic:\n{d_text}")

        checkpoints = r.get("active_checkpoints", [])
        if checkpoints:
            c_text = "\n".join([f"- Objective: {c.get('task')}" for c in checkpoints if isinstance(c, dict)])
            full_context_chunks.append(f"Stage {r_num} ({r_title}) Core Assessment Milestones:\n{c_text}")

    if not full_context_chunks:
        full_context_chunks = [f"Foundations, mechanisms, applications, and principles of {topic}."]

    job_id = str(uuid.uuid4())[:12]
    _test_jobs[job_id] = {
        "status": "running",
        "result": None,
        "error": None,
        "progress": f"Synthesizing high-accuracy {num_questions}-question test for {topic}...",
        "start_time": time.time(),
        "num_questions": num_questions
    }

    def _run_exam_gen():
        try:
            def progress_cb(msg):
                _test_jobs[job_id]["progress"] = msg
                if client_sid:
                    try:
                        socketio.emit("test_progress", {"job_id": job_id, "message": msg}, room=client_sid)
                    except Exception:
                        pass

            test_data = create_mcq_test(
                full_context_chunks,
                total_questions=num_questions,
                topic=topic,
                progress_callback=progress_cb
            )
            test_data["docName"] = f"Session {session_id}: {topic}"
            test_data["topic"] = topic
            test_data["from_session_id"] = session_id
            test_data["timerMode"] = timer_mode
            test_data["timeLimitMinutes"] = time_limit_minutes
            test_data["testType"] = f"{num_questions}-Question {'Timed Exam' if timer_mode == 'timed' else 'Study Test'}"
            _test_jobs[job_id]["result"] = test_data
            _test_jobs[job_id]["status"] = "done"
            if client_sid:
                socketio.emit("test_ready", {"job_id": job_id, "test": test_data}, room=client_sid)
        except Exception as ex:
            print(f"[SESSION EXAM ERROR]: {ex}")
            _test_jobs[job_id]["status"] = "error"
            _test_jobs[job_id]["error"] = str(ex)

    t = threading.Thread(target=_run_exam_gen, daemon=True)
    t.start()

    return jsonify({"success": True, "job_id": job_id, "topic": topic, "num_questions": num_questions})



@app.route("/session/interactive-plan", methods=["POST"])
def get_session_interactive_plan():
    data = request.get_json() or {}
    topic = data.get("topic", "Study Sprint")
    session_id = data.get("session_id")
    student_id = data.get("student_id") or 1
    doc_name = data.get("doc_name")

    # Guard: If session was already ended, return empty milestones
    if session_id:
        sess = db.get_session_by_id(int(session_id))
        if not sess or sess.get("end_time"):
            return jsonify({"success": False, "milestones": []})

    # Priority 1: If session has a saved curriculum, extract milestones directly from the curriculum!
    if session_id:
        cur_file = os.path.join(CURRICULUM_DIR, f"curriculum_{session_id}.json")
        if os.path.exists(cur_file):
            try:
                with open(cur_file, "r", encoding="utf-8") as f:
                    cur = json.load(f)
                rounds = cur.get("rounds", [])

                # Auto upgrade any legacy generic boilerplate titles using Mistral
                has_generic_titles = any("Foundation & Core Intuition" in r.get("title", "") for r in rounds)
                if has_generic_titles:
                    print(f"[CURRICULUM] Upgrading generic rounds in curriculum_{session_id}.json using Mistral for '{topic}'...")
                    mistral_rounds = rag_engine.generate_rounds_with_mistral(topic, cur.get("source_type", "Web"))
                    if mistral_rounds:
                        for i, r in enumerate(rounds):
                            if i < len(mistral_rounds):
                                r["title"] = mistral_rounds[i].get("title", r.get("title"))
                                r["objective"] = mistral_rounds[i].get("objective", r.get("objective"))
                        with open(cur_file, "w", encoding="utf-8") as f:
                            json.dump(cur, f, indent=2)

                if rounds:
                    milestones = []
                    for r in rounds:
                        r_num = r.get("round_number", 1)
                        r_title = r.get("title", f"Stage {r_num}")
                        r_obj = r.get("objective", "")
                        milestones.append({
                            "title": f"Stage {r_num}: {r_title}",
                            "goal": r_obj or f"Master foundational principles of {topic}.",
                            "tip": f"Study the guide notes and complete the stage practice drill.",
                            "done": False
                        })
                    db.save_session_milestones(int(session_id), milestones)
                    if int(session_id) in active_timers:
                        active_timers[int(session_id)]["milestones"] = milestones
                    return jsonify({"success": True, "milestones": milestones})
            except Exception as ex:
                print(f"[CURRICULUM MILESTONES ERROR]: {ex}")

    # Priority 2: Only retrieve document notes IF user explicitly specified a document
    ctx = ""
    if doc_name and doc_name not in ("all", "none", ""):
        context_text, _ = rag_engine.retrieve_chunks_with_sources(topic, doc_filter=doc_name, top_k=2)
        ctx = context_text[:1200]

    notes_context = f"\nRelevant Notes:\n{ctx}" if ctx else ""
    prompt = f"""You are an elite cognitive study coach.
A student is studying: '{topic}'.{notes_context}
Domain: Adapt strictly to '{topic}'. Do NOT mention software or coding unless '{topic}' is about programming.

Create exactly 3 interactive learning milestones for a 25-minute focus session.
Format as JSON list with keys: 'title' (under 8 words), 'goal' (1 short sentence), 'tip' (1 actionable tip).
Only valid JSON."""

    try:
        raw = rag_engine.ollama_generate(prompt, task="interactive_plan")
        match = re.search(r'\[.*\]', raw, re.DOTALL)
        if match:
            milestones = json.loads(match.group(0))
        else:
            raise ValueError("No JSON array")
    except Exception:
        milestones = [
            {"title": f"1. Core Principles of {topic}", "goal": f"Understand the fundamental definitions and key mechanisms of {topic}.", "tip": "Note the primary terms, principles, and relationships."},
            {"title": "2. Working Methods & Applied Logic", "goal": "Break down how the concepts interact sequentially in practical scenarios.", "tip": "Sketch a quick diagram or outline in your notes."},
            {"title": "3. Nuances & Practical Retention", "goal": "Test yourself on subtle edge cases and solve 1 scenario problem.", "tip": "Close your notes and recall key details from memory."}
        ]

    for m in milestones:
        m["done"] = False

    if session_id:
        db.save_session_milestones(int(session_id), milestones)
        if int(session_id) in active_timers:
            active_timers[int(session_id)]["milestones"] = milestones

    return jsonify({"success": True, "milestones": milestones})


@app.route("/session/set-milestones", methods=["POST"])
def set_session_milestones_route():
    data = request.get_json() or {}
    session_id = data.get("session_id")
    milestones = data.get("milestones", [])
    if session_id and milestones:
        db.save_session_milestones(int(session_id), milestones)
        if int(session_id) in active_timers:
            active_timers[int(session_id)]["milestones"] = milestones
        socketio.emit("milestones_updated", {
            "session_id": int(session_id),
            "milestones": milestones
        })
        return jsonify({"success": True})
    return jsonify({"error": "Invalid session or milestones"}), 400


@app.route("/session/toggle-milestone", methods=["POST"])
def toggle_milestone():
    data = request.get_json() or {}
    session_id = data.get("session_id")
    idx = data.get("index", 0)
    if not session_id:
        return jsonify({"error": "Missing session_id"}), 400
    updated = db.toggle_session_milestone(int(session_id), int(idx))
    if int(session_id) in active_timers:
        active_timers[int(session_id)]["milestones"] = updated

    # Broadcast updated milestones to all connected clients in real time
    socketio.emit("milestones_updated", {
        "session_id": int(session_id),
        "milestones": updated
    })
    return jsonify({"success": True, "milestones": updated})


@app.route("/session/curriculum/toggle-checkpoint", methods=["POST"])
def toggle_curriculum_checkpoint():
    data = request.get_json() or {}
    session_id = data.get("session_id")
    round_idx = int(data.get("round_idx", 0))
    chk_idx = int(data.get("chk_idx", 0))
    student_id = int(data.get("student_id") or 1)

    if not session_id:
        return jsonify({"error": "Missing session_id"}), 400

    cur_file = os.path.join(CURRICULUM_DIR, f"curriculum_{session_id}.json")
    curriculum = None
    if os.path.exists(cur_file):
        try:
            with open(cur_file, "r", encoding="utf-8") as f:
                curriculum = json.load(f)
            rounds = curriculum.get("rounds", [])
            if 0 <= round_idx < len(rounds):
                chks = rounds[round_idx].get("active_checkpoints", [])
                if 0 <= chk_idx < len(chks):
                    chks[chk_idx]["done"] = not chks[chk_idx].get("done", False)
                    with open(cur_file, "w", encoding="utf-8") as f:
                        json.dump(curriculum, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[CURRICULUM CHECKPOINT TOGGLE ERROR]: {e}")

    # Broadcast to all connected clients (desktop and mobile)
    socketio.emit("checkpoint_updated", {
        "session_id": int(session_id),
        "round_idx": round_idx,
        "chk_idx": chk_idx,
        "curriculum": curriculum
    })

    return jsonify({"success": True, "curriculum": curriculum})


@app.route("/session/challenge", methods=["POST"])
def session_challenge():
    data = request.get_json() or {}
    topic = data.get("topic", "General")
    student_id = data.get("student_id") or 1

    chunks = rag_engine.retrieve_relevant_chunks(topic, top_k=2)
    ctx = "\n".join(c.get("text", "") for c in chunks)[:1000]

    prompt = f"""Generate 1 active-recall challenge question for the topic '{topic}'.
Context: {ctx}

Output STRICT JSON:
{{
  "question": "Clear, challenging question testing understanding",
  "options": ["Option A", "Option B", "Option C", "Option D"],
  "correct_index": 0,
  "explanation": "Why this answer is correct in 1 concise sentence"
}}"""

    try:
        raw = rag_engine.ollama_generate(prompt, task="challenge")
        import re, json
        m = re.search(r'\{.*\}', raw, re.DOTALL)
        if m:
            challenge = json.loads(m.group(0))
        else:
            raise ValueError("Invalid format")
    except Exception:
        challenge = {
            "question": f"What is the most fundamental principle when working with {topic}?",
            "options": [
                "Understand the underlying structure before applying syntax",
                "Memorize all text verbatim without comprehension",
                "Skip theoretical foundations completely",
                "Only study the topic once per month"
            ],
            "correct_index": 0,
            "explanation": "Building mental models through core principles provides long-term retention."
        }

    return jsonify({"success": True, "challenge": challenge})


@app.route("/session/verify-challenge", methods=["POST"])
def verify_challenge():
    data = request.get_json() or {}
    session_id = data.get("session_id")
    student_id = data.get("student_id") or 1
    selected_idx = data.get("selected_index")
    correct_idx = data.get("correct_index")
    explanation = data.get("explanation", "")

    is_correct = int(selected_idx) == int(correct_idx)
    pts = 30 if is_correct else 10
    if session_id:
        db.record_session_challenge(int(session_id), int(student_id), is_correct)

    return jsonify({
        "success": True,
        "is_correct": is_correct,
        "points_awarded": pts,
        "explanation": explanation,
        "message": f"+{pts} Knowledge Points! {'Brilliant active recall!' if is_correct else 'Good effort — review the concept explanation.'}"
    })


@app.route("/session/clarify", methods=["POST"])
def session_clarify():
    data = request.get_json() or {}
    question = data.get("question", "")
    topic = data.get("topic", "General")
    session_id = data.get("session_id")
    student_id = data.get("student_id") or 1

    if not question:
        return jsonify({"error": "No question provided"}), 400

    chunks = rag_engine.retrieve_relevant_chunks(f"{topic} {question}", top_k=2, student_id=int(student_id))
    ctx = "\n".join(c.get("text", "") for c in chunks)[:1000]

    prompt = f"""You are a session tutor assisting a student studying '{topic}'.
Question: {question}
Relevant Notes: {ctx}

Provide a direct, crystal-clear 2-sentence explanation to unlock their understanding immediately."""

    ans = rag_engine.ollama_generate(prompt, task="clarify")
    if session_id:
        db.save_query(int(session_id), question, ans)

    return jsonify({"answer": ans})


@app.route("/session/live-stats", methods=["GET"])
def live_stats():
    session_id = request.args.get("session_id")
    student_id = request.args.get("student_id")
    if not session_id or not student_id:
        return jsonify({})
    stats = db.get_live_session_stats(int(session_id), int(student_id))
    # Include smart notif state
    notif_state = notifications._state.get(int(student_id), {})
    stats['pomodoro_round'] = notif_state.get('pomodoro_round', 0)
    stats['break_active']   = notif_state.get('break_started_at') is not None
    return jsonify(stats)


# ─────────────────────────────────────────
#  Routes: Study Plans
# ─────────────────────────────────────────
@app.route("/plan/create", methods=["POST"])
def create_plan():
    data       = request.get_json()
    student_id = data.get("student_id")
    topic      = data.get("topic", "General")
    planned_start_str = data.get("planned_start")  # ISO string
    duration   = int(data.get("duration_mins", 25))
    notes      = data.get("notes", "")
    try:
        planned_start = datetime.fromisoformat(planned_start_str)
    except Exception:
        return jsonify({"error": "Invalid planned_start format. Use ISO 8601."}), 400

    now = datetime.now()
    if planned_start < now:
        return jsonify({"error": "Cannot schedule a session in the past. Please choose a future date and time."}), 400

    if planned_start.year > now.year + 2 or planned_start.year < now.year:
        return jsonify({"error": f"Invalid year {planned_start.year}. Please select a date within {now.year}-{now.year+2}."}), 400

    plan_id = db.create_study_plan(student_id, topic, planned_start, duration, notes)
    socketio.emit("plans_updated", {
        "student_id": int(student_id),
        "plan_id": plan_id,
        "topic": topic,
        "planned_start": planned_start_str,
        "duration_mins": duration
    })
    return jsonify({"success": True, "plan_id": plan_id})


@app.route("/plan/today", methods=["GET"])
def plans_today():
    student_id = request.args.get("student_id") or 1
    pause_info = db.is_reminders_paused(int(student_id))
    plans = db.get_plans_today(int(student_id))
    # Convert datetimes to strings
    for p in plans:
        if isinstance(p.get('planned_start'), datetime):
            p['planned_start'] = p['planned_start'].isoformat()
        if isinstance(p.get('created_at'), datetime):
            p['created_at'] = p['created_at'].isoformat()
    return jsonify({
        "plans": plans,
        "paused": pause_info.get("paused", False),
        "remaining_minutes": pause_info.get("remaining_minutes", 0),
        "pause_until": pause_info.get("pause_until")
    })


@app.route("/plan/upcoming", methods=["GET"])
def plans_upcoming():
    student_id = request.args.get("student_id")
    days = int(request.args.get("days", 7))
    plans = db.get_plans_upcoming(int(student_id), days)
    for p in plans:
        if isinstance(p.get('planned_start'), datetime):
            p['planned_start'] = p['planned_start'].isoformat()
        if isinstance(p.get('created_at'), datetime):
            p['created_at'] = p['created_at'].isoformat()
    return jsonify({"plans": plans})


@app.route("/plan/delete/<int:plan_id>", methods=["DELETE"])
def delete_plan(plan_id):
    student_id = request.args.get("student_id") or 1
    db.delete_plan(plan_id)
    socketio.emit("plans_updated", {"student_id": int(student_id), "action": "deleted", "plan_id": plan_id})
    return jsonify({"success": True})


@app.route("/plan/complete/<int:plan_id>", methods=["POST"])
def complete_plan(plan_id):
    student_id = request.args.get("student_id") or 1
    db.update_plan_status(plan_id, "completed")
    socketio.emit("plans_updated", {"student_id": int(student_id), "action": "completed", "plan_id": plan_id})
    return jsonify({"success": True, "message": "Plan marked completed"})


@app.route("/plan/reminders", methods=["GET"])
def plan_reminders():
    student_id = request.args.get("student_id") or 1
    pause_info = db.is_reminders_paused(int(student_id))
    if pause_info.get("paused"):
        return jsonify({"reminders": [], "paused": True})
    window = int(request.args.get("window", 20))
    due = db.get_due_unnotified_plans(student_id=int(student_id), window_minutes=window)
    return jsonify({"reminders": due, "paused": False})


@app.route("/session/summary/<int:session_id>", methods=["GET"])
def session_summary(session_id):
    data = db.get_session_summary(session_id)
    return jsonify(data)


@app.route("/stats/streak", methods=["GET"])
def student_streak():
    student_id = request.args.get("student_id") or 1
    streak = db.get_study_streak(int(student_id))
    return jsonify({"streak": streak})


@app.route("/test-alert", methods=["POST"])
def test_mobile_alert():
    data = request.get_json() or {}
    student_id = data.get("student_id") or 1
    title = data.get("title") or " StudyEdge Mobile Alert"
    body = data.get("body") or "Mobile alerts are active! You will receive study reminders and Pomodoro updates on this device."
    
    sub = db.get_push_subscription(int(student_id))
    if not sub:
        return jsonify({"success": False, "error": "No push subscription registered on this device yet. Click 'Enable Push Notifications' first."}), 404
        
    notifications._push(int(student_id), title, body)
    return jsonify({"success": True, "message": "Test alert dispatched to device."})


# ─────────────────────────────────────────
#  Routes: Reminders / Do Not Disturb (DND)
# ─────────────────────────────────────────
@app.route("/reminders/status", methods=["GET"])
def reminders_status_route():
    student_id = request.args.get("student_id") or session.get("student_id", 1)
    status = db.is_reminders_paused(int(student_id))
    return jsonify({"success": True, **status})


@app.route("/reminders/pause", methods=["POST"])
def pause_reminders_route():
    data = request.get_json() or {}
    student_id = data.get("student_id") or session.get("student_id", 1)
    try:
        duration_mins = int(data.get("duration_mins", -1))
    except (ValueError, TypeError):
        duration_mins = -1
    status = db.set_reminders_paused(int(student_id), paused=True, duration_mins=duration_mins)
    socketio.emit("reminders_status_changed", {"student_id": int(student_id), **status})
    return jsonify({"success": True, **status})


@app.route("/reminders/resume", methods=["POST"])
def resume_reminders_route():
    data = request.get_json() or {}
    student_id = data.get("student_id") or session.get("student_id", 1)
    status = db.set_reminders_paused(int(student_id), paused=False)
    socketio.emit("reminders_status_changed", {"student_id": int(student_id), **status})
    return jsonify({"success": True, **status})


# ─────────────────────────────────────────
#  Route: Upload PDF
# ─────────────────────────────────────────
@app.route("/upload-document/", methods=["POST"])
@app.route("/upload",           methods=["POST"])
def upload_pdf():
    student_name = request.form.get("student_name", "default")
    topic_name   = request.form.get("topic", "General")

    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    file = request.files["file"]
    if not file or not file.filename:
        return jsonify({"error": "Empty file"}), 400
    if not file.filename.lower().endswith(".pdf"):
        return jsonify({"error": "Only PDF files are allowed"}), 400

    filename  = secure_filename(file.filename)
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    save_path = os.path.join(UPLOAD_FOLDER, filename)
    file.save(save_path)

    topic = topic_name if topic_name != "General" else filename.replace(".pdf", "")

    def do_index():
        try:
            rag_engine.index_pdf(save_path, student_name, topic)
        except Exception as e:
            print(f"[UPLOAD] Background indexing failed for '{filename}': {e}")

    threading.Thread(target=do_index, daemon=True).start()
    return jsonify({"message": f"'{filename}' uploaded. Indexing in background."})


@app.route("/documents", methods=["GET"])
def list_documents():
    try:
        os.makedirs(UPLOAD_FOLDER, exist_ok=True)
        pdfs = sorted([f for f in os.listdir(UPLOAD_FOLDER) if f.endswith(".pdf")])
        return jsonify({"documents": pdfs})
    except Exception as e:
        return jsonify({"documents": [], "error": str(e)})


@app.route("/delete-document/<path:doc_name>", methods=["DELETE"])
def delete_document(doc_name):
    file_path = os.path.join(UPLOAD_FOLDER, doc_name)
    if not os.path.exists(file_path):
        return jsonify({"error": "Document not found"}), 404
    os.remove(file_path)
    return jsonify({"message": f"'{doc_name}' deleted."})


# ─────────────────────────────────────────
#  Route: Ask AI (Q&A)
# ─────────────────────────────────────────
#  Routes: Personal Notes (Quick Tools -> Notes)
# ─────────────────────────────────────────
@app.route("/notes", methods=["GET"])
def get_user_notes_route():
    student_id = request.args.get("student_id") or 1
    notes = db.get_user_notes(int(student_id))
    return jsonify({"success": True, "notes": notes})


@app.route("/notes", methods=["POST"])
def save_user_note_route():
    data = request.get_json() or {}
    student_id = data.get("student_id") or 1
    import time
    note_id = data.get("id") or str(int(time.time() * 1000))
    content = (data.get("content") or "").strip()
    title = data.get("title")
    if not content:
        return jsonify({"error": "Content is required"}), 400
    saved = db.save_user_note(int(student_id), note_id, content, title)
    return jsonify({"success": True, "note": saved})


@app.route("/notes/<note_id>", methods=["DELETE"])
def delete_user_note_route(note_id):
    student_id = request.args.get("student_id") or 1
    db.delete_user_note(int(student_id), str(note_id))
    return jsonify({"success": True})


# ─────────────────────────────────────────
#  Routes: Multi Thread Chat (ChatGPT / Gemini Style)
# ─────────────────────────────────────────
@app.route("/chat/threads", methods=["GET"])
def list_chat_threads():
    student_id = request.args.get("student_id") or session.get("student_id", 1)
    threads = db.get_chat_threads(int(student_id))
    return jsonify({"threads": threads})


@app.route("/chat/threads", methods=["POST"])
def create_chat_thread_route():
    data = request.get_json() or {}
    student_id = data.get("student_id") or session.get("student_id", 1)
    thread_id = data.get("thread_id") or f"chat_{uuid.uuid4().hex[:12]}"
    title = data.get("title", "New Chat")
    doc_filter = data.get("doc_filter", "all")
    db.create_chat_thread(thread_id, int(student_id), title, doc_filter)
    return jsonify({"success": True, "thread_id": thread_id, "title": title, "doc_filter": doc_filter})


@app.route("/chat/threads/<thread_id>", methods=["GET"])
def get_chat_thread_messages(thread_id):
    thread = db.get_chat_thread(thread_id)
    if not thread:
        return jsonify({"error": "Thread not found"}), 404
    messages = db.get_chat_messages(thread_id)
    return jsonify({"thread": thread, "messages": messages})


@app.route("/chat/threads/<thread_id>", methods=["DELETE"])
def delete_chat_thread_route(thread_id):
    student_id = request.args.get("student_id") or session.get("student_id")
    db.delete_chat_thread(thread_id, int(student_id) if student_id else None)
    return jsonify({"success": True, "thread_id": thread_id})


@app.route("/chat/threads/<thread_id>/title", methods=["PATCH"])
def update_chat_title(thread_id):
    data = request.get_json() or {}
    title = data.get("title", "").strip()
    if title:
        db.update_chat_thread_title(thread_id, title)
    return jsonify({"success": True, "title": title})


@app.route("/chat/send", methods=["POST"])
def chat_send():
    data = request.get_json() or {}
    thread_id = data.get("thread_id")
    question = (data.get("question") or data.get("message") or "").strip()
    student_id = data.get("student_id") or session.get("student_id", 1)
    student_name = data.get("student_name") or session.get("student_name", "Student")
    model = data.get("model") or "mistral"
    doc_filter = data.get("doc_filter", "all")

    if not question:
        return jsonify({"error": "Question is required"}), 400

    if not thread_id:
        thread_id = f"chat_{uuid.uuid4().hex[:12]}"
        db.create_chat_thread(thread_id, int(student_id), "New Chat", doc_filter)
    else:
        db.update_chat_thread_doc_filter(thread_id, doc_filter)

    # 1. Fetch prior turns for conversational memory
    history = db.get_chat_messages(thread_id, limit=8)

    # 2. Save user message to local storage
    db.save_chat_message(thread_id, "user", question)

    # 3. Cross Module Autonomous Action Engine (Planner, Tests, Pomodoro, Reports)
    import cross_module_agent
    action_data, action_context = cross_module_agent.detect_and_execute_cross_module_actions(
        question=question,
        student_id=int(student_id),
        student_name=student_name,
        history=history
    )

    # 4. Generate response with RAG + Conversational Context + Student Analytics + Cross Module Action Context
    try:
        answer, sources, chosen_model, chosen_doc = rag_engine.generate_answer(
            question=question,
            student_name=student_name,
            student_id=int(student_id),
            doc_filter=doc_filter,
            model_override=model,
            history=history,
            extra_action_context=action_context
        )
    except Exception as e:
        print(f"[CHAT ERROR] Generation exception: {e}")
        answer = f"️ I encountered an unexpected error: {e}. Please try again."
        sources = []
        chosen_model = model or "mistral"
        chosen_doc = doc_filter or "all"

    # 5. Save bot answer with source citations & executed action to local storage
    db.save_chat_message(thread_id, "bot", answer, sources=sources, action=action_data)
    if action_data and action_data.get("action_type") == "planner":
        socketio.emit("plans_updated", {
            "student_id": int(student_id),
            "topic": action_data.get("payload", {}).get("topic", "Study Session")
        })

    # 6. Auto name thread title if first exchange
    thread = db.get_chat_thread(thread_id)
    thread_title = thread.get("title", "New Chat") if thread else "New Chat"
    if thread_title in ["New Chat", "", "Untitled"]:
        words = [w for w in re.sub(r'[^a-zA-Z0-9\s]', '', question).split() if len(w) > 2]
        auto_title = " ".join(words[:4]).title() if words else "Study Discussion"
        if len(auto_title) > 35: auto_title = auto_title[:35] + "..."
        db.update_chat_thread_title(thread_id, auto_title)
        thread_title = auto_title

    return jsonify({
        "success": True,
        "thread_id": thread_id,
        "thread_title": thread_title,
        "answer": answer,
        "sources": sources,
        "action": action_data,
        "model": chosen_model,
        "doc_filter": chosen_doc
    })


# ─────────────────────────────────────────
#  Route: Ask AI (Backward compatible Q&A)
# ─────────────────────────────────────────
@app.route("/ask", methods=["POST"])
def ask():
    data         = request.get_json() or {}
    question     = data.get("question", "").strip()
    student_id   = data.get("student_id") or 1
    student_name = data.get("student_name") or "Student"
    session_id   = data.get("session_id")
    topic        = data.get("topic")
    doc_filter   = data.get("doc_filter", "all")
    model_opt    = data.get("model")
    history      = data.get("history")

    if not question:
        return jsonify({"error": "Question is required"}), 400

    answer, sources, chosen_model, chosen_doc = rag_engine.generate_answer(
        question, student_name=student_name, student_id=int(student_id),
        topic_filter=topic, doc_filter=doc_filter, model_override=model_opt, history=history
    )

    if session_id:
        db.save_query(int(session_id), question, answer)

    if student_id and topic:
        db.update_weak_area(int(student_id), topic)
        notifications.on_question_asked(int(student_id))

    return jsonify({"answer": answer, "sources": sources, "model": chosen_model, "doc_filter": chosen_doc})


@app.route("/chat", methods=["POST"])
def chat():
    return chat_send()


# ─────────────────────────────────────────
#  Routes: AI Tools
# ─────────────────────────────────────────
@app.route("/summary", methods=["POST"])
def summary():
    data         = request.get_json() or {}
    topic        = data.get("topic")
    student_name = data.get("student_name")
    model_opt    = data.get("model")
    note_content = data.get("note_content") or data.get("content")
    result       = rag_engine.generate_topic_summary(topic, student_name, model_override=model_opt, note_content=note_content)
    return jsonify({"summary": result})


@app.route("/questions", methods=["POST"])
def study_questions():
    data         = request.get_json()
    topic        = data.get("topic")
    student_name = data.get("student_name")
    count        = data.get("count", 5)
    model_opt    = data.get("model")
    result       = rag_engine.generate_study_questions(topic, student_name, count, model_override=model_opt)
    return jsonify({"questions": result})


@app.route("/report", methods=["GET"])
def weakness_report():
    student_id = request.args.get("student_id")
    model_opt  = request.args.get("model")
    weak_areas = db.get_weak_areas(student_id, limit=5)
    report     = rag_engine.generate_weakness_report(weak_areas, model_override=model_opt)
    return jsonify({"report": report, "weak_areas": weak_areas})


@app.route("/topics", methods=["GET"])
def topics():
    student_name = request.args.get("student_name")
    topic_list   = rag_engine.get_indexed_topics(student_name)
    return jsonify({"topics": topic_list})


@app.route("/models", methods=["GET"])
def available_models():
    models = rag_engine.get_available_models()
    return jsonify({"models": models, "current": rag_engine.MODELS,
                    "status": _model_status})


@app.route("/models/switch", methods=["POST"])
@app.route("/switch-model", methods=["POST"])
def switch_model():
    data  = request.get_json()
    task  = data.get("task")
    model = data.get("model")
    if task in rag_engine.MODELS:
        rag_engine.MODELS[task] = model
        print(f"[MODEL] Task '{task}' dynamically switched to model '{model}'")
        return jsonify({"success": True, "task": task, "model": model, "message": f"Task '{task}' now uses model '{model}'"})
    return jsonify({"error": "Invalid task name"}), 400


# ─────────────────────────────────────────
#  MCQ Test Generator — Async Background (prevents fetch timeout)
# ─────────────────────────────────────────
_test_jobs = {}   # job_id -> { status, result, error }

@app.route("/generate-test", methods=["POST"])
def generate_test():
    from mcq_test import create_mcq_test
    import fitz
    data              = request.get_json() or {}
    doc_name          = data.get("doc_name", "")
    num_questions     = int(data.get("num_questions", 16))
    model_opt         = data.get("model")
    client_sid        = data.get("socket_id", "")
    selected_chapters = data.get("selected_chapters") or []

    file_path = os.path.join(UPLOAD_FOLDER, doc_name)

    job_id = str(uuid.uuid4())[:12]
    _test_jobs[job_id] = {
        "status": "running",
        "result": None,
        "error": None,
        "progress": "Starting question generation...",
        "start_time": time.time(),
        "num_questions": num_questions
    }

    def _run_gen():
        try:
            def progress_cb(msg):
                _test_jobs[job_id]["progress"] = msg
                if client_sid:
                    try:
                        socketio.emit("test_progress",
                                      {"job_id": job_id, "message": msg},
                                      room=client_sid)
                    except Exception:
                        pass

            from mcq_test import clean_topic_title, create_mcq_test
            clean_topic = clean_topic_title(doc_name)
            test_data = create_mcq_test(
                file_path if os.path.exists(file_path) else [f"Foundational concepts in {clean_topic}."],
                total_questions=num_questions,
                topic=clean_topic,
                model_override=model_opt,
                progress_callback=progress_cb,
                selected_chapters=selected_chapters
            )
            test_data["docName"] = doc_name
            test_data["topic"]   = clean_topic
            _test_jobs[job_id]["result"]   = test_data
            _test_jobs[job_id]["status"]   = "done"
            _test_jobs[job_id]["progress"] = "Questions synthesized successfully!"
            if client_sid:
                socketio.emit("test_ready", {"job_id": job_id, **test_data}, room=client_sid)
        except Exception as e:
            print(f"[TEST] Generation failed: {e}")
            _test_jobs[job_id]["status"]   = "error"
            _test_jobs[job_id]["error"]    = str(e)
            _test_jobs[job_id]["progress"] = f"Error: {e}"
            if client_sid:
                socketio.emit("test_error", {"job_id": job_id, "error": str(e)}, room=client_sid)

    threading.Thread(target=_run_gen, daemon=True).start()
    return jsonify({"job_id": job_id, "status": "started", "num_questions": num_questions})


@app.route("/document-chapters/<path:doc_name>", methods=["GET"])
def get_doc_chapters(doc_name):
    file_path = os.path.join(UPLOAD_FOLDER, doc_name)
    if not os.path.exists(file_path):
        return jsonify({"error": "Document not found"}), 404
    try:
        from mcq_test import get_document_chapters, clean_topic_title
        chapters = get_document_chapters(file_path)
        return jsonify({
            "doc_name": doc_name,
            "topic": clean_topic_title(doc_name),
            "chapters": chapters,
            "total_chapters": len(chapters)
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/test-job/<job_id>", methods=["GET"])
@app.route("/test-job-status/<job_id>", methods=["GET"])
def test_job_status(job_id):
    job = _test_jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    if job["status"] == "running":
        elapsed = round(time.time() - job.get("start_time", time.time()))
        return jsonify({
            "status": "running",
            "progress": job.get("progress", "AI is synthesizing questions..."),
            "elapsed_seconds": elapsed,
            "num_questions": job.get("num_questions", 16)
        })
    if job["status"] == "error":
        return jsonify({"status": "error", "error": job.get("error", "Unknown error")}), 500
    if job["status"] == "done" and job.get("result"):
        res = job["result"]
        return jsonify({"status": "done", "result": res, **res})
    return jsonify({"status": "running", "progress": job.get("progress", "")})




@app.route("/submit-test", methods=["POST"])
def submit_test():
    import reports
    data         = request.get_json() or {}
    test_id      = data.get("test_id") or str(uuid.uuid4())
    student_id   = int(data.get("student_id") or 1)
    topic        = data.get("topic") or "General Test"
    questions    = data.get("questions") or []
    answers      = data.get("answers") or {}
    time_taken   = int(data.get("time_taken_seconds") or 0)

    # Compute comprehensive Current Test Report
    report = reports.compute_current_test_report(
        test_id=test_id,
        topic=topic,
        questions=questions,
        user_answers=answers,
        time_taken_seconds=time_taken
    )

    # Extract clean scores dict for DB storage
    scores_dict = {}
    for cat, cdata in report["categoryBreakdown"].items():
        scores_dict[cat] = {
            "score": cdata["score"],
            "total": cdata["total"]
        }

    # Save attempt to MySQL database
    db.save_test_attempt(
        test_id=test_id,
        student_id=student_id,
        topic=topic,
        total_score=report["totalCorrect"],
        total_possible=report["totalQuestions"],
        percentage=report["percentage"],
        scores_dict=scores_dict,
        questions_list=questions,
        answers_dict=answers,
        time_taken_seconds=time_taken
    )

    # If weakest category has score < 60%, log as a weak area in DB
    if report["weakestCategory"] and report["categoryBreakdown"][report["weakestCategory"]]["percentage"] < 60:
        db.update_weak_area(student_id, f"{topic} ({report['weakestCategory']})")

    return jsonify(report)


# ─────────────────────────────────────────
#  On Demand Question Explanation
# ─────────────────────────────────────────
@app.route("/explain-question", methods=["POST"])
def explain_question():
    data = request.get_json() or {}
    q_text = data.get("questionText", "").strip()
    options = data.get("options", [])
    correct_ans = data.get("correctAnswer", "").strip()
    user_ans = data.get("userAnswer", "").strip()
    category = data.get("category", "")
    topic = data.get("topic", "General")
    model_override = data.get("model")

    if not q_text or not correct_ans:
        return jsonify({"error": "Missing question or correct answer"}), 400

    opts_text = "\n".join([f"- {opt}" for opt in options]) if options else ""
    user_context = f"The student selected: '{user_ans}'." if user_ans and user_ans != "Not Answered" else "The student did not answer this question."

    prompt = f"""You are an expert academic tutor.
Explain this multiple choice question clearly and concisely in 2 to 3 sentences.

Topic: {topic}
Cognitive Category: {category}
Question: {q_text}
Options:
{opts_text}
Correct Answer: {correct_ans}
{user_context}

Your Goal:
1. Explain clearly WHY "{correct_ans}" is correct based on the fundamental concepts.
2. If the student chose an incorrect answer, explain the misunderstanding in 1 sentence.
Keep it direct, educational, and easy to understand. Do NOT use markdown headers."""

    try:
        explanation = rag_engine.ollama_generate(
            prompt,
            task="qa",
            model_override=model_override,
            num_predict=250
        )
        return jsonify({"success": True, "explanation": explanation.strip()})
    except Exception as e:
        print(f"[EXPLAIN ERROR] {e}")
        return jsonify({
            "success": True,
            "explanation": f"The correct answer is '{correct_ans}'. It directly satisfies the fundamental principles of {category} for {topic}."
        })


@app.route("/reports/current/<test_id>", methods=["GET"])
def get_current_report(test_id):
    import reports
    record = db.get_test_attempt(test_id)
    if not record:
        return jsonify({"error": "Test record not found"}), 404

    report = reports.compute_current_test_report(
        test_id=record["testId"],
        topic=record["topic"],
        questions=record["questions"],
        user_answers=record["answers"],
        time_taken_seconds=record["timeTakenSeconds"]
    )
    return jsonify(report)


@app.route("/reports/overall", methods=["GET"])
@app.route("/reports/weekly", methods=["GET"])
def get_overall_reports():
    import reports
    student_id = int(request.args.get("student_id") or 1)
    history    = db.get_test_history(student_id, limit=30)
    
    knowledge_pts   = reports.calculate_knowledge_points(history)
    forgetting_curve = reports.compute_forgetting_curve(history)
    category_perf   = db.get_overall_category_performance(student_id)

    return jsonify({
        "history": history,
        "knowledgePoints": knowledge_pts,
        "forgettingCurve": forgetting_curve,
        "categoryPerformance": category_perf,
    })


@app.route("/reports/overall/diagnostic", methods=["GET"])
def get_overall_diagnostic_report():
    import reports
    student_id = int(request.args.get("student_id") or 1)
    student = db.get_student_by_id(student_id) if hasattr(db, 'get_student_by_id') else None
    student_name = student.get("name", "Student") if student else "Student"
    history = db.get_test_history(student_id, limit=100)
    diagnostic = reports.compute_overall_diagnostic_report(history, student_name=student_name)
    return jsonify(diagnostic)


@app.route("/quote/daily", methods=["GET"])
def daily_quote():
    prompt = "Generate a single short inspirational quote about learning or studying. Return ONLY the quote."
    try:
        resp = rq.post(f"{OLLAMA_BASE_URL}/api/generate",
                       json={"model": "mistral", "prompt": prompt, "stream": False,
                             "options": {"temperature": 0.9, "num_predict": 80}},
                       timeout=60)
        quote = resp.json().get("response", "").strip().strip('"')
        return jsonify({"quote": quote})
    except Exception:
        return jsonify({"quote": "The best way to predict the future is to create it."})


@app.route("/summarize-document/<path:doc_name>", methods=["GET"])
def summarize_document(doc_name):
    import fitz
    file_path = os.path.join(UPLOAD_FOLDER, doc_name)
    if not os.path.exists(file_path):
        return jsonify({"error": "Not found"}), 404
    try:
        doc  = fitz.open(file_path)
        text = "".join(p.get_text() for p in doc)[:3500]
        doc.close()
        summary = rag_engine.ollama_generate(
            f"Summarize the following document concisely:\n\n{text}\n\nSummary:", task="summary")
        return jsonify({"summary": summary})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/stats", methods=["GET"])
def stats():
    student_id = request.args.get("student_id")
    session_id = request.args.get("session_id")
    if session_id and student_id:
        data = db.get_live_session_stats(int(session_id), int(student_id))
        return jsonify(data)
    return jsonify({"topic": "N/A", "pomodoro_count": 0, "questions_asked": 0, "weak_areas": []})


# ─────────────────────────────────────────
#  WebSocket: Pomodoro Timer (Full 4-round cycle)
# ─────────────────────────────────────────
def _find_timer(sess_id):
    if sess_id is None:
        return None, None
    if sess_id in active_timers:
        return sess_id, active_timers[sess_id]
    try:
        i = int(sess_id)
        if i in active_timers:
            return i, active_timers[i]
    except Exception:
        pass
    s = str(sess_id)
    if s in active_timers:
        return s, active_timers[s]
    return None, None


@socketio.on("start_timer")
def handle_start_timer(data):
    session_id   = data.get("session_id")
    student_id   = data.get("student_id") or 1
    is_break     = data.get("is_break", False)
    break_type   = data.get("break_type", "short")  # "short" | "long"
    topic        = data.get("topic") or "Focus Session"
    restart      = data.get("restart", False)
    custom_mins  = data.get("duration_mins")

    # Stop existing timer thread cleanly
    _, existing = _find_timer(session_id)
    if existing:
        existing["running"] = False
        time.sleep(0.15)

    # Determine duration
    if is_break:
        default_secs = LONG_BREAK_MINUTES * 60 if break_type == "long" else SHORT_BREAK_MINUTES * 60
        notifications.on_break_started(int(student_id), break_type)
    else:
        default_secs = (int(custom_mins) * 60) if custom_mins else (POMODORO_MINUTES * 60)
        notifications.on_break_ended(int(student_id))

    # If resuming a paused timer for the same session and not an explicit restart
    if not restart and existing and existing.get("seconds_left", 0) > 0 and not is_break:
        seconds_left = existing["seconds_left"]
        total_secs = existing.get("total_secs", default_secs)
    else:
        seconds_left = default_secs
        total_secs = default_secs

    pom_round = notifications._state.get(int(student_id), {}).get('pomodoro_round', 1)

    t_entry = {
        "running": True,
        "seconds_left": seconds_left,
        "total_secs": total_secs,
        "is_break": is_break,
        "break_type": break_type,
        "topic": topic,
        "student_id": int(student_id),
        "milestones": data.get("milestones", existing.get("milestones", []) if existing else [])
    }
    active_timers[str(session_id)] = t_entry
    try:
        active_timers[int(session_id)] = t_entry
    except Exception:
        pass

    def timer_thread():
        secs = seconds_left
        while secs >= 0 and t_entry.get("running"):
            mins = secs // 60
            sec  = secs % 60
            pct  = round(((total_secs - secs) / total_secs) * 100, 1) if total_secs > 0 else 0
            t_entry["seconds_left"] = secs
            socketio.emit("timer_tick", {
                "session_id" : session_id,
                "topic"      : topic,
                "time_str"   : f"{mins:02d}:{sec:02d}",
                "seconds_left": secs,
                "is_break"   : is_break,
                "break_type" : break_type,
                "progress_pct": pct,
                "round"      : pom_round
            })
            time.sleep(1)
            secs -= 1

        if t_entry.get("running") and secs < 0:
            if not is_break:
                # Pomodoro complete — increment count
                try:
                    db.increment_pomodoro(int(session_id))
                except Exception:
                    pass
                break_type_next = notifications.on_pomodoro_complete(int(student_id))

                socketio.emit("timer_done", {
                    "session_id" : session_id,
                    "is_break"   : False,
                    "break_type" : break_type_next,
                    "message"    : f"Pomodoro complete! Take a {'15-min long' if break_type_next == 'long' else '5-min short'} break."
                })
            else:
                notifications.on_break_ended(int(student_id))
                socketio.emit("timer_done", {
                    "session_id": session_id,
                    "is_break"  : True,
                    "message"   : "Break over! Start your next Pomodoro."
                })

    t = threading.Thread(target=timer_thread, daemon=True)
    t.start()
    t_entry["thread"] = t


@socketio.on("pause_timer")
def handle_pause_timer(data):
    session_id = data.get("session_id")
    _, timer = _find_timer(session_id)
    if timer:
        timer["running"] = False
        secs = timer.get("seconds_left", 0)
        mins = secs // 60
        sec  = secs % 60
        time_str = f"{mins:02d}:{sec:02d}"
        socketio.emit("timer_paused", {
            "session_id": session_id,
            "seconds_left": secs,
            "time_str": time_str
        })


@socketio.on("stop_timer")
def handle_stop_timer(data):
    handle_pause_timer(data)


@socketio.on("reset_timer")
def handle_reset_timer(data):
    session_id = data.get("session_id")
    _, timer = _find_timer(session_id)
    if timer:
        timer["running"] = False
        total_secs = timer.get("total_secs", POMODORO_MINUTES * 60)
        timer["seconds_left"] = total_secs
        mins = total_secs // 60
        sec  = total_secs % 60
        time_str = f"{mins:02d}:{sec:02d}"
        socketio.emit("timer_reset", {
            "session_id": session_id,
            "seconds_left": total_secs,
            "time_str": time_str
        })


@socketio.on("end_sprint")
def handle_end_sprint(data):
    """Ends the active sprint timer without destroying or ending the overall study session."""
    session_id = data.get("session_id")
    student_id = data.get("student_id") or 1
    round_idx = data.get("round_idx", 0)
    suggested_mins = data.get("suggested_mins", POMODORO_MINUTES)
    topic = data.get("topic") or "Focus Session"

    _, timer = _find_timer(session_id)
    total_secs = int(suggested_mins) * 60
    if timer:
        timer["running"] = False
        timer["seconds_left"] = total_secs
        timer["total_secs"] = total_secs
        timer["is_break"] = False

    mins = total_secs // 60
    sec = total_secs % 60
    time_str = f"{mins:02d}:{sec:02d}"

    socketio.emit("sprint_ended", {
        "session_id": session_id,
        "student_id": int(student_id),
        "round": round_idx + 1,
        "topic": topic,
        "time_str": time_str,
        "seconds_left": total_secs,
        "total_secs": total_secs
    })


@socketio.on("cancel_break")
def handle_cancel_break(data):
    session_id = data.get("session_id")
    student_id = data.get("student_id") or 1
    topic = data.get("topic") or "Focus Session"
    auto_start = data.get("auto_start", True)

    _, timer = _find_timer(session_id)
    if timer:
        timer["running"] = False
        time.sleep(0.15)

    notifications.on_break_ended(int(student_id))
    default_secs = POMODORO_MINUTES * 60
    pom_round = notifications._state.get(int(student_id), {}).get('pomodoro_round', 1)

    t_entry = {
        "running": False,
        "seconds_left": default_secs,
        "total_secs": default_secs,
        "is_break": False,
        "topic": topic,
        "student_id": int(student_id),
        "milestones": timer.get("milestones", []) if timer else []
    }
    active_timers[str(session_id)] = t_entry
    try:
        active_timers[int(session_id)] = t_entry
    except Exception:
        pass

    mins = default_secs // 60
    sec = default_secs % 60
    time_str = f"{mins:02d}:{sec:02d}"

    # Notify clients that break is cancelled
    socketio.emit("timer_tick", {
        "session_id": session_id,
        "topic": topic,
        "time_str": time_str,
        "seconds_left": default_secs,
        "is_break": False,
        "progress_pct": 0,
        "round": pom_round
    })
    socketio.emit("timer_reset", {
        "session_id": session_id,
        "seconds_left": default_secs,
        "time_str": time_str
    })

    if auto_start:
        handle_start_timer({
            "session_id": session_id,
            "student_id": student_id,
            "is_break": False,
            "topic": topic,
            "restart": True
        })




def _get_lan_ip():
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def _get_all_lan_ips():
    import socket
    ips = []
    try:
        hostname = socket.gethostname()
        for ip in socket.gethostbyname_ex(hostname)[2]:
            if not ip.startswith("127.") and ip not in ips:
                ips.append(ip)
    except Exception:
        pass
    primary = _get_lan_ip()
    if primary not in ips and not primary.startswith("127."):
        ips.insert(0, primary)
    return ips if ips else ["127.0.0.1"]


@app.route("/api/host-info", methods=["GET"])
def api_host_info():
    lan_ip = _get_lan_ip()
    all_ips = _get_all_lan_ips()
    return jsonify({
        "app": "StudyEdge AI",
        "status": "ok",
        "version": "1.0",
        "lan_ip": lan_ip,
        "all_ips": all_ips,
        "port": PORT,
        "mobile_url": f"http://{lan_ip}:{PORT}/mobile",
        "timestamp": int(time.time() * 1000)
    })


# ─────────────────────────────────────────
#  UDP Broadcast Auto Discovery Service
# ─────────────────────────────────────────
DISCOVERY_PORT = 5002

def _start_discovery_responder():
    """Listens for UDP discovery broadcasts from the StudyEdge Android app
    and responds with the server's current LAN URL."""
    import socket
    def responder_loop():
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        try:
            sock.bind(('', DISCOVERY_PORT))
            print(f"[DISCOVERY] Auto-discovery beacon active on UDP port {DISCOVERY_PORT}")
        except Exception as e:
            print(f"[DISCOVERY] Error binding discovery socket: {e}")
            return

        while True:
            try:
                data, addr = sock.recvfrom(1024)
                msg = data.decode('utf-8', errors='ignore').strip()
                if "STUDYEDGE" in msg or "DISCOVERY" in msg:
                    client_ip = addr[0]
                    all_ips = _get_all_lan_ips()
                    matched_ip = _get_lan_ip()
                    client_prefix = client_ip.rsplit('.', 1)[0] if '.' in client_ip else ''
                    for ip in all_ips:
                        if '.' in ip and ip.rsplit('.', 1)[0] == client_prefix:
                            matched_ip = ip
                            break
                    reply = f"STUDYEDGE_DISCOVERY_RESP:http://{matched_ip}:{PORT}".encode('utf-8')
                    sock.sendto(reply, addr)
                    print(f"[DISCOVERY] Discovered by {client_ip} -> Responded with http://{matched_ip}:{PORT}")
            except Exception:
                time.sleep(0.2)

    threading.Thread(target=responder_loop, daemon=True).start()


# ─────────────────────────────────────────
#  Entry Point
# ─────────────────────────────────────────
if __name__ == "__main__":
    db.setup_database()

    # Ensure all uploaded notes are indexed into local file storage
    threading.Thread(target=rag_engine.ensure_all_pdfs_indexed, daemon=True).start()

    # Auto start Ollama and detect models in background
    threading.Thread(target=check_and_warm_models, daemon=True).start()

    # Start smart notification scheduler
    notifications.start_scheduler()

    # Start UDP Auto Discovery responder
    _start_discovery_responder()

    lan_ip = _get_lan_ip()
    print(f"[APP] Server running at http://localhost:{PORT}")
    print(f"[APP] Open on mobile (same Wi-Fi): http://{lan_ip}:{PORT}/dashboard")
    socketio.run(app, host=HOST, port=PORT, debug=DEBUG, use_reloader=False, allow_unsafe_werkzeug=True)

