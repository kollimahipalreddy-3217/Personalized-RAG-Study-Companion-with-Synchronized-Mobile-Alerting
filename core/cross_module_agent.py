# ============================================================
#  cross_module_agent.py — Cross Module Autonomous Reasoning Engine
#  Personalized RAG Study Companion with Synchronized Mobile Alerting
#  Application Interface: StudyEdge AI
# ============================================================

import re
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
import db
import reports

def get_student_weak_topic(student_id: int) -> str:
    """Finds the most critical weak topic for the student."""
    cat_perf = db.get_overall_category_performance(student_id)
    if cat_perf:
        # Find lowest category
        lowest_cat = min(cat_perf.items(), key=lambda x: x[1].get("percentage", 100))
        cat_name, cdata = lowest_cat
        if cdata.get("percentage", 100) < 65:
            return f"{cat_name} (Accuracy: {cdata.get('percentage')}%)"
            
    weak_areas = db.get_weak_areas(student_id)
    for w in weak_areas:
        t = (w.get("topic") or "").strip()
        if len(t) > 2 and not t.startswith(""):
            return t
    return "Core Concept Review"


def parse_schedule_time(text: str) -> Tuple[str, str]:
    """Parses natural language date/time (including 9.30pm, 9:30pm, today, tonight, tomorrow) into datetime string and display string."""
    now = datetime.now()
    t_lower = text.lower()
    
    # Determine day: today, tonight, tomorrow, or weekday
    target_date = now.date()
    is_today = "today" in t_lower or "tonight" in t_lower
    is_tomorrow = "tomorrow" in t_lower
    
    if is_tomorrow:
        target_date = now.date() + timedelta(days=1)
    elif not is_today:
        weekdays = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        for idx, day in enumerate(weekdays):
            if day in t_lower:
                days_ahead = (idx - now.weekday()) % 7 or 7
                target_date = now.date() + timedelta(days=days_ahead)
                break

    # Parse time: 9.30pm, 9:30pm, 9:30 pm, 9.30 pm, 9pm, 9 am, 21:30
    target_hr = 10
    target_min = 0
    time_found = False

    time_match = re.search(r'\b(\d{1,2})(?:[\.:](\d{2}))?\s*(am|pm)\b', t_lower)
    if time_match:
        time_found = True
        target_hr = int(time_match.group(1))
        target_min = int(time_match.group(2)) if time_match.group(2) else 0
        meridiem = time_match.group(3)
        if meridiem == "pm" and target_hr < 12:
            target_hr += 12
        elif meridiem == "am" and target_hr == 12:
            target_hr = 0
    else:
        h24 = re.search(r'\b([01]?\d|2[0-3])[:.]([0-5]\d)\b', t_lower)
        if h24:
            time_found = True
            target_hr = int(h24.group(1))
            target_min = int(h24.group(2))
        elif "tonight" in t_lower:
            time_found = True
            target_hr = 20
            target_min = 0

    target_dt = datetime.combine(target_date, datetime.min.time()).replace(hour=target_hr, minute=target_min)
    
    # If target is in past and user didn't explicitly say "today", push to tomorrow
    if target_dt < now and not is_today and not time_found:
        target_dt += timedelta(days=1)

    display_day = "Today" if target_dt.date() == now.date() else ("Tomorrow" if target_dt.date() == (now + timedelta(days=1)).date() else target_dt.strftime("%A, %b %d"))
    time_str = target_dt.strftime("%I:%M %p").lstrip("0")
    display_str = f"{display_day} at {time_str}"
        
    return target_dt.strftime("%Y-%m-%d %H:%M:%S"), display_str


def detect_and_execute_cross_module_actions(
    question: str,
    student_id: int = 1,
    student_name: str = "Student",
    history: list = None
) -> Tuple[Optional[Dict[str, Any]], str]:
    """
    Analyzes student message for cross-feature tasks and executes them.
    Returns (action_metadata_dict, system_context_to_inject).
    """
    q_lower = question.lower()
    history_str = " ".join((m.get("content") or "").lower() for m in (history or [])[-4:])
    
    # ─────────────────────────────────────────────────────────────
    # 1. ACTION: Schedule / Add Study Plan (Planner Module)
    # ─────────────────────────────────────────────────────────────
    planner_triggers = [
        r'\b(?:make|create|schedule|set|add|build)\s+(?:a\s+)?(?:session\s+)?(?:study\s+)?plan\b',
        r'\b(?:make|create|schedule|set|start)\s+(?:a\s+)?session\b',
        r'\bplan\s+(?:a\s+)?(?:study\s+)?(?:session|python|code|exam|test|revision)?\b',
        r'\bremind\s+me\s+to\s+study\b',
        r'\bschedule\s+revision\b',
        r'\bstudy\s+[a-zA-Z0-9\+\#\s]+\s+at\s+\d',
        r'\bin\s+the\s+app\b'
    ]
    is_planner_request = any(re.search(t, q_lower) for t in planner_triggers)
    if not is_planner_request and "plan" in q_lower and ("today" in q_lower or "tonight" in q_lower or "pm" in q_lower or "am" in q_lower):
        is_planner_request = True
    if not is_planner_request and ("in the app" in q_lower or "by myself" in q_lower) and "plan" in history_str:
        is_planner_request = True

    if is_planner_request:
        # Extract topic
        topic = "Python Programming & Core Syntax" if ("python" in q_lower or "python" in history_str) else "Focused Study Session"
        if "weak" in q_lower:
            topic = f"Revision: {get_student_weak_topic(student_id)}"
        elif "python" in q_lower or "python" in history_str:
            topic = "Python Programming & Core Syntax"
        elif "english" in q_lower or "english" in history_str:
            topic = "English Grammar & Writing Mastery"
        elif "excel" in q_lower or "vlookup" in q_lower:
            topic = "Excel Formulas & Common Applications"
        elif "llm" in q_lower or "transformer" in q_lower:
            topic = "Large Language Models & Deep Learning"
        else:
            m = re.search(r'(?:study|on|for|about|learn|master)\s+([a-zA-Z0-9\+\#\s\-]+?)(?:\s+(?:at|today|tomorrow|tonight|in|with|\d)|\Z)', question, re.I)
            if m and len(m.group(1).strip()) > 1:
                topic = m.group(1).strip().title()

        duration = 30
        dur_match = re.search(r'(\d+)\s*(?:min|minute)', q_lower)
        if dur_match:
            duration = int(dur_match.group(1))

        # Check question for time or fallback to history
        time_text = question
        if not re.search(r'\b(?:\d{1,2}(?:[\.:]\d{2})?\s*(?:am|pm)|\d{1,2}:\d{2}|tonight|today|tomorrow)\b', q_lower):
            if re.search(r'\b(?:\d{1,2}(?:[\.:]\d{2})?\s*(?:am|pm)|\d{1,2}:\d{2}|tonight|today|tomorrow)\b', history_str):
                time_text = history_str

        planned_start, display_time = parse_schedule_time(time_text)
        
        try:
            plan_id = db.create_study_plan(
                student_id=student_id,
                topic=topic,
                planned_start=planned_start,
                duration_mins=duration,
                notes=f"Auto-scheduled by StudyEdge AI Copilot for {student_name}"
            )
            action_data = {
                "action_type": "planner",
                "action_name": "Study Plan Created",
                "target_view": "planner",
                "title": f" Study Plan: {topic}",
                "description": f"Scheduled for {display_time} ({duration} mins)",
                "button_label": "View in Study Planner ",
                "payload": {"plan_id": plan_id, "topic": topic, "planned_start": planned_start}
            }
            context_injection = f"""=== CROSS-MODULE ACTION EXECUTED: STUDY PLANNER ===
Status: Success! The study session has been formally created in the student's Study Planner database.
Plan ID: {plan_id}
Topic: '{topic}'
Scheduled Time: {display_time} ({planned_start})
Duration: {duration} minutes

INSTRUCTION: Warmly confirm to {student_name} that you have officially scheduled this study plan inside the app for {display_time}.
Mention that a reminder is booked, and they can click the interactive card below or open the 'Study Planner' tab anytime to start the session."""
            return action_data, context_injection
        except Exception as e:
            print(f"[ACTION ERROR - PLANNER]: {e}")

    # ─────────────────────────────────────────────────────────────
    # 2. ACTION: Launch MCQ Test / Practice Quiz (Test Module)
    # ─────────────────────────────────────────────────────────────
    test_triggers = [
        r'\btest\s+me\b', r'\bgenerate\s+(a\s+)?test\b', r'\btake\s+(a\s+)?test\b',
        r'\bquiz\s+me\b', r'\bpractice\s+test\b', r'\bstart\s+(a\s+)?test\b',
        r'\bcreate\s+(a\s+)?test\b'
    ]
    if any(re.search(t, q_lower) for t in test_triggers):
        num_q = 16
        for n in [60, 48, 32, 16]:
            if str(n) in q_lower:
                num_q = n
                break

        test_topic = "General Knowledge Practice"
        if "weak" in q_lower:
            test_topic = f"Weak Area Quiz: {get_student_weak_topic(student_id)}"
        else:
            try:
                from config import UPLOAD_FOLDER
                if os.path.exists(UPLOAD_FOLDER):
                    available_docs = [f for f in os.listdir(UPLOAD_FOLDER) if f.lower().endswith(".pdf")]
                    for d in available_docs:
                        d_stem = d.replace(".pdf", "").replace("_", " ").lower()
                        if any(term in q_lower for term in d_stem.split() if len(term) > 3):
                            test_topic = d
                            break
                    if test_topic == "General Knowledge Practice" and available_docs:
                        test_topic = available_docs[0]
            except Exception:
                pass

        action_data = {
            "action_type": "test",
            "action_name": "Practice Test Prepared",
            "target_view": "test",
            "title": f" Ready: {test_topic.replace('.pdf', '').replace('_', ' ')}",
            "description": f"{num_q} Questions Balanced Across 4 Cognitive Categories",
            "button_label": "Launch Practice Exam Now ",
            "payload": {"doc_name": test_topic, "num_questions": num_q}
        }
        context_injection = f"""=== CROSS-MODULE ACTION EXECUTED: TEST GENERATOR ===
Status: Ready! Practice exam configured.
Document/Topic: '{test_topic}'
Questions: {num_q}
Cognitive Categories: Memory, Logic, Critical Thinking, Application

INSTRUCTION: Let the student know their practice test has been configured and is ready to launch immediately via the button below."""
        return action_data, context_injection

    # ─────────────────────────────────────────────────────────────
    # 3. ACTION: Start Pomodoro Focus Session (Focus / Home Module)
    # ─────────────────────────────────────────────────────────────
    pomodoro_triggers = [
        r'\bstart\s+(a\s+)?(pomodoro|focus|study)\s*(session|timer)?\b',
        r'\bbegin\s+(a\s+)?(pomodoro|session|study)\b',
        r'\blet\'?s\s+study\b', r'\bstudy\s+mode\b'
    ]
    if any(re.search(t, q_lower) for t in pomodoro_triggers):
        topic = "Focused Study"
        m = re.search(r'(?:on|for)\s+([a-zA-Z0-9\s\-]+)', question, re.I)
        if m and len(m.group(1).strip()) > 2:
            topic = m.group(1).strip().title()

        action_data = {
            "action_type": "pomodoro",
            "action_name": "Focus Session Ready",
            "target_view": "home",
            "title": f"️ Study Session: {topic}",
            "description": f"Ready to begin a 25-minute study sprint on '{topic}'",
            "button_label": "Enter Focus Room ",
            "payload": {"topic": topic}
        }
        context_injection = f"""=== CROSS-MODULE RECOMMENDATION: FOCUS POMODORO ===
Topic: '{topic}'
Focus Duration: 25 minutes + 5 minute break

INSTRUCTION: Encourage the student to enter the Focus Room to begin studying '{topic}' whenever they are ready."""
        return action_data, context_injection

    # ─────────────────────────────────────────────────────────────
    # 4. ACTION: View Deep Historical Test Report (Reports Module)
    # ─────────────────────────────────────────────────────────────
    report_triggers = [
        r'\bopen\s+(my\s+)?report\b', r'\bshow\s+(my\s+)?last\s+test\b',
        r'\bdiagnostic\s+report\b', r'\bview\s+(my\s+)?test\s+report\b'
    ]
    if any(re.search(t, q_lower) for t in report_triggers):
        history_tests = db.get_test_history(student_id, limit=5)
        if history_tests:
            latest = history_tests[0]
            action_data = {
                "action_type": "report",
                "action_name": "Diagnostic Report",
                "target_view": "reports",
                "title": f" Report: {latest.get('topic')}",
                "description": f"Score: {latest.get('totalScore')}/{latest.get('totalPossible')} ({latest.get('percentage')}%) | {latest.get('createdAt')}",
                "button_label": "Open Full Diagnostic Report ",
                "payload": {"test_id": latest.get("testId")}
            }
            context_injection = f"""=== CROSS-MODULE ACTION EXECUTED: REPORTS & ANALYTICS ===
Test ID: {latest.get('testId')}
Topic: '{latest.get('topic')}'
Score: {latest.get('totalScore')}/{latest.get('totalPossible')} ({latest.get('percentage')}%)

INSTRUCTION: Direct the student to their diagnostic report card to review question-by-question explanations."""
            return action_data, context_injection

    return None, ""
