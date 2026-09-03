# ============================================================
#  config.py — Central System Configuration
#  Personalized RAG Study Companion with Synchronized Mobile Alerting
# ============================================================

# ------------------------------------------------------------
# Local Persistence Layer Settings
# All application state is stored locally on disk via JSON tables.
# ------------------------------------------------------------
STORAGE_DIR_NAME = "storage"

# ------------------------------------------------------------
# Edge AI Inference Configuration (Ollama)
# Directs local HTTP requests to the active inference server.
# ------------------------------------------------------------
OLLAMA_BASE_URL = "http://localhost:11434"

# ------------------------------------------------------------
# Dynamic Task to Model Routing Configuration
# Maps specialized cognitive tasks to optimal local LLM architectures.
#
# Model Architecture Profiles:
#   gemma3:4b  - Optimized for instructional Q&A, conceptual tutoring
#   phi3       - High speed inference for concise responses and summaries
#   mistral    - Balanced reasoning for curriculum synthesis and analytics
#   llama3     - Deep contextual reasoning and comprehensive breakdowns
# ------------------------------------------------------------

MODELS = {
    # Task: Contextual Question Answering from Local Notes (RAG)
    "qa"         : "mistral",

    # Task: Topic and Session Summarization
    "summary"    : "mistral",

    # Task: Socratic Inquiries & Reflection Prompts
    "questions"  : "mistral",

    # Task: Weak Area & Knowledge Point Diagnostic Analysis
    "analytics"  : "mistral",

    # Task: Autonomous Curriculum Formulation & Interactive Milestones
    "curriculum" : "mistral",
    "interactive_plan": "mistral",

    # Fallback Model Identifier
    "fallback"   : "mistral",
}

# ----------------------------
import os
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ----------------------------
# ChromaDB Storage Path
# ----------------------------
CHROMA_PATH = os.path.join(BASE_DIR, "vectordb")

# ----------------------------
# PDF Uploads Folder & Size Limits
# ----------------------------
UPLOAD_FOLDER       = os.path.join(BASE_DIR, "uploads")
MAX_UPLOAD_SIZE_MB  = 100
MAX_CONTENT_LENGTH  = 100 * 1024 * 1024  # 100 MB max request body payload

# ----------------------------
# RAG Settings
# ----------------------------
CHUNK_SIZE    = 500   # words per chunk
CHUNK_OVERLAP = 50    # overlapping words between chunks
TOP_K_RESULTS = 4     # number of chunks retrieved per query

# ----------------------------
# Pomodoro Timer Settings
# ----------------------------
POMODORO_MINUTES    = 25
SHORT_BREAK_MINUTES = 5
LONG_BREAK_MINUTES  = 15   # every 4th round
LONG_BREAK_EVERY    = 4    # rounds before a long break

# ----------------------------
# Weak Area Detection
# ----------------------------
WEAK_AREA_THRESHOLD = 5    # alert after 5+ queries on same topic

# ----------------------------
# Smart Notification Thresholds
# ----------------------------
SLOW_SESSION_MINS   = 15   # notify if no question asked in 15 min
LONG_SESSION_MINS   = 90   # notify if studying 90+ min no break
STREAK_WARN_HOURS   = 24   # notify if no session in 24h
STREAK_CRITICAL_HRS = 48   # critical nudge after 48h gap

# ----------------------------
# Flask Server Settings
# ----------------------------
HOST  = "0.0.0.0"
PORT  = 5000
DEBUG = True

