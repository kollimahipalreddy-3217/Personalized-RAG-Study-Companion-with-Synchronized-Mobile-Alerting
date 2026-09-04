# ============================================================
# rag_engine.py — Multi Model Dynamic Router & Local Context Retrieval Engine
# Personalized RAG Study Companion with Synchronized Mobile Alerting
# Application Interface: StudyEdge AI
# ============================================================

from bs4 import BeautifulSoup
from urllib.parse import unquote, parse_qs, urlparse

import os
import re
import math
import json
import time
from datetime import datetime, timedelta
import requests
import fitz # PyMuPDF
from config import (OLLAMA_BASE_URL, MODELS, CHUNK_SIZE, CHUNK_OVERLAP,
                    TOP_K_RESULTS, UPLOAD_FOLDER)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STORAGE_DIR = os.path.join(BASE_DIR, "data", "storage")
KNOWLEDGE_FILE = os.path.join(STORAGE_DIR, "knowledge_chunks.json")
CURRICULUM_DIR = os.path.join(BASE_DIR, "data", "curriculum")
os.makedirs(CURRICULUM_DIR, exist_ok=True)


def _ensure_storage():
    os.makedirs(STORAGE_DIR, exist_ok=True)


def _load_knowledge_chunks() -> list:
    _ensure_storage()
    if not os.path.exists(KNOWLEDGE_FILE):
        return []
    try:
        with open(KNOWLEDGE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[RAG STORAGE READ ERROR]: {e}")
        return []


def _save_knowledge_chunks(chunks: list):
    _ensure_storage()
    temp_file = KNOWLEDGE_FILE + ".tmp"
    try:
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(chunks, f, indent=2, ensure_ascii=False)
        os.replace(temp_file, KNOWLEDGE_FILE)
    except Exception as e:
        print(f"[RAG STORAGE WRITE ERROR]: {e}")
        if os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except Exception:
                pass


# ─────────────────────────────────────────
# Ollama Server Check
# ─────────────────────────────────────────
def ensure_ollama_running():
    """Checks if Ollama is responding on localhost."""
    try:
        r = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=2)
        return r.status_code == 200
    except Exception:
        return False


def get_available_models():
    """Returns list of installed Ollama models."""
    try:
        r = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=3)
        if r.status_code == 200:
            return [m["name"] for m in r.json().get("models", [])]
        return []
    except Exception:
        return []


# ─────────────────────────────────────────
# Smart Dynamic Model Routing (ChatGPT / Gemini Architecture)
# ─────────────────────────────────────────
def select_optimal_model(question: str, preferred_model: str = None) -> str:
    """
    Dynamically routes the prompt to the most suitable installed Ollama model
    based on task type, complexity, and performance requirements:
    - Coding / programming / algorithms -> mistral
    - Academic explanation / curriculum tutoring -> gemma3:4b (or mistral)
    - Quick conversational / temporal / calendar / greetings -> phi3 (or mistral)
    - Deep reasoning / multi-step logic -> llama3
    """
    if preferred_model and preferred_model != "auto":
        return preferred_model

    q = (question or "").lower()

    # 1. Coding & Programming Tasks -> Mistral
    code_keywords = [
        "code", "python", "javascript", "function", "algorithm", "loop", "array",
        "sql", "regex", "class", "debug", "compile", "syntax", "git", "api", "html", "css"
    ]
    if any(k in q for k in code_keywords):
        return "mistral"

    # 2. Deep Analytical / Multi-step Reasoning -> Llama 3
    deep_reasoning = [
        "compare and contrast", "critique", "in-depth analysis", "philosophical",
        "synthesize", "trade-offs", "architectural", "derive"
    ]
    if any(k in q for k in deep_reasoning):
        return "llama3"

    # 3. Quick Chat, Greetings & Temporal Queries -> Phi-3 / Mistral (Ultra-fast)
    if is_temporal_query(question) or _is_conversational_greeting(question) or len(q.split()) <= 4:
        return "phi3"

    # 4. Academic Explanations & Curriculum Study -> Gemma 3 4B
    return "gemma3:4b"


# ─────────────────────────────────────────
# Smart Dynamic Document Scope / Mode Router
# ─────────────────────────────────────────
def select_optimal_doc_filter(question: str, preferred_filter: str = "auto") -> str:
    """
    Dynamically routes the document/RAG scope based on question intent:
    - If user explicitly chose a specific filter (e.g. 'none', 'all', or 'file.pdf'), honor it.
    - If 'auto':
      * Temporal, clock, calendar, greetings, or test reports -> 'none' (General Knowledge / Real time)
      * Query with strong topical match in uploaded notes -> specific PDF or 'all'
      * General science, world knowledge, or general coding -> 'none'
    """
    if preferred_filter and preferred_filter not in ("auto", "dynamic", "", None):
        return preferred_filter

    # 1. Temporal, clock, calendar, greetings -> none
    if is_temporal_query(question) or _is_conversational_greeting(question):
        return "none"

    # 2. Student performance reports -> none
    if _is_student_performance_query(question):
        return "none"

    # 3. Check for genuine matches against uploaded study notes
    chunks = _load_knowledge_chunks()
    if not chunks:
        return "none"

    raw_tokens = _tokenize(question)
    query_tokens = _filter_query_tokens(raw_tokens)
    if not query_tokens:
        return "none"

    # Ignore generic instructions from determining document matches
    generic_words = {
        'write', 'code', 'function', 'program', 'example', 'simple', 'explain',
        'what', 'how', 'create', 'give', 'show', 'tell', 'make', 'use', 'find'
    }
    content_tokens = [t for t in query_tokens if t not in generic_words]
    if not content_tokens:
        return "none"

    doc_scores = {}
    q_lower = question.strip().lower()

    for c in chunks:
        doc = c.get("doc_name")
        text = c.get("text", "")
        text_lower = text.lower()
        text_tokens = _tokenize(text)
        if not text_tokens:
            continue

        text_token_set = set(text_tokens)
        matched = [t for t in content_tokens if t in text_token_set]
        if not matched:
            continue

        coverage = len(matched) / max(1, len(content_tokens))
        has_phrase = len(q_lower) > 6 and q_lower in text_lower

        if not has_phrase:
            if len(content_tokens) >= 2 and (len(matched) < 2 or coverage < 0.38):
                continue
            elif len(content_tokens) == 1 and len(matched) < 1:
                continue

        score = (8.0 if has_phrase else 0.0) + (coverage * 6.0)
        for t in matched:
            if len(t) > 2:
                score += min(3.0, text_tokens.count(t) * 0.8)

        if score >= 4.5:
            doc_scores[doc] = max(doc_scores.get(doc, 0.0), score)

    if not doc_scores:
        return "none"

    sorted_docs = sorted(doc_scores.items(), key=lambda x: x[1], reverse=True)
    best_doc, best_score = sorted_docs[0]

    # If a specific document is clearly the primary source, target that document
    if (len(sorted_docs) == 1 or best_score >= 1.4 * sorted_docs[1][1]) and best_score >= 6.0:
        return best_doc

    return "all"


# ─────────────────────────────────────────
# Ollama Generation Helper
# ─────────────────────────────────────────
def ollama_generate(prompt: str, task: str = "qa", model_override: str = None, num_predict: int = 900) -> str:
    """Invokes local Ollama model with smart dynamic fallback."""
    if model_override == "auto" or not model_override:
        preferred_model = MODELS.get(task, "mistral")
    else:
        preferred_model = model_override

    payload = {
        "model": preferred_model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.3,
            "top_p": 0.9,
            "num_predict": num_predict
        }
    }

    try:
        response = requests.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json=payload,
            timeout=90
        )
        if response.status_code == 200:
            res_text = response.json().get("response", "").strip()
            if res_text:
                return res_text
        raise RuntimeError(f"Ollama returned HTTP {response.status_code}: {response.text[:100]}")
    except Exception as e:
        available = get_available_models()
        fallback = None
        for cand in ["mistral", "phi3", "llama3", "gemma3:4b"]:
            if any(cand in a for a in available) and cand not in (preferred_model or ""):
                fallback = cand
                break
        if not fallback and available:
            fallback = available[0]
        if not fallback:
            fallback = "mistral" if preferred_model != "mistral" else "phi3"

        try:
            payload["model"] = fallback
            payload["options"]["num_predict"] = min(payload["options"]["num_predict"], 400)
            r = requests.post(f"{OLLAMA_BASE_URL}/api/generate", json=payload, timeout=60)
            if r.status_code == 200:
                return r.json().get("response", "").strip()
        except Exception:
            pass
        return f"Error: Model generation failed or timed out ({e}). Make sure Ollama is running."


# ─────────────────────────────────────────
# Local PDF Text Extraction & Chunking
# ─────────────────────────────────────────
def clean_topic_title(filename: str) -> str:
    name = re.sub(r'\.pdf$', '', filename, flags=re.I)
    name = re.sub(r'[_]+', ' ', name)
    return name.strip()


def split_into_chunks(text: str, chunk_size: int = 220, overlap: int = 40) -> list:
    words = text.split()
    chunks = []
    start = 0
    while start < len(words):
        chunk = " ".join(words[start : start + chunk_size])
        if len(chunk.strip()) > 30:
            chunks.append(chunk)
        start += chunk_size - overlap
    return chunks


def index_pdf(pdf_path: str, student_name: str = "global", topic_name: str = "General") -> int:
    """Extracts text page-by-page and stores indexed chunks in local JSON storage."""
    import hashlib
    filename = os.path.basename(pdf_path)
    clean_topic = clean_topic_title(filename)
    print(f"[RAG LOCAL] Indexing PDF: {filename} -> '{clean_topic}'")

    if not os.path.exists(pdf_path):
        return 0

    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        print(f"[RAG LOCAL] Failed to open PDF {filename}: {e}")
        return 0

    all_chunks = _load_knowledge_chunks()
    # Remove older chunks for this document
    all_chunks = [c for c in all_chunks if c.get("doc_name") != filename]

    new_chunks = []
    for page_idx, page in enumerate(doc, 1):
        page_text = page.get_text()
        if not page_text.strip():
            continue
        p_chunks = split_into_chunks(page_text, chunk_size=200, overlap=35)
        for c_idx, chunk_text in enumerate(p_chunks):
            chunk_id = hashlib.md5(f"{filename}_{page_idx}_{c_idx}_{chunk_text[:50]}".encode()).hexdigest()
            new_chunks.append({
                "id": chunk_id,
                "doc_name": filename,
                "topic": clean_topic,
                "page": page_idx,
                "chunk_index": c_idx,
                "text": chunk_text
            })
    doc.close()

    all_chunks.extend(new_chunks)
    _save_knowledge_chunks(all_chunks)
    print(f"[RAG LOCAL] Successfully indexed {len(new_chunks)} chunks for '{filename}' into local storage.")
    return len(new_chunks)


def ensure_all_pdfs_indexed():
    """Scans UPLOAD_FOLDER and ensures all PDFs are indexed in local storage."""
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    pdfs = [f for f in os.listdir(UPLOAD_FOLDER) if f.lower().endswith(".pdf")]
    chunks = _load_knowledge_chunks()
    indexed_docs = set(c.get("doc_name") for c in chunks)

    for pdf in pdfs:
        if pdf not in indexed_docs:
            pdf_path = os.path.join(UPLOAD_FOLDER, pdf)
            index_pdf(pdf_path, topic_name=clean_topic_title(pdf))


# Common stopwords to prevent irrelevant chunks matching conversational or general queries
COMMON_STOPWORDS = {
    'a', 'about', 'above', 'after', 'again', 'against', 'all', 'am', 'an', 'and', 'any', 'are', 'aren',
    'as', 'at', 'be', 'because', 'been', 'before', 'being', 'below', 'between', 'both', 'but', 'by',
    'can', 'could', 'did', 'didn', 'do', 'does', 'doesn', 'doing', 'don', 'down', 'during', 'each',
    'few', 'for', 'from', 'further', 'had', 'hadn', 'has', 'hasn', 'have', 'haven', 'having', 'he',
    'her', 'here', 'hers', 'herself', 'him', 'himself', 'his', 'how', 'i', 'if', 'in', 'into', 'is',
    'isn', 'it', 'its', 'itself', 'just', 'll', 'm', 'me', 'might', 'more', 'most', 'must', 'my',
    'myself', 'no', 'nor', 'not', 'now', 'o', 'of', 'off', 'on', 'once', 'only', 'or', 'other', 'our',
    'ours', 'ourselves', 'out', 'over', 'own', 're', 's', 'same', 'she', 'should', 'so', 'some', 'such',
    't', 'than', 'that', 'the', 'their', 'theirs', 'them', 'themselves', 'then', 'there', 'these',
    'they', 'this', 'those', 'through', 'to', 'too', 'under', 'until', 'up', 've', 'very', 'was',
    'wasn', 'we', 'were', 'weren', 'what', 'whats', 'whatever', 'when', 'where', 'which', 'while',
    'who', 'whom', 'why', 'will', 'with', 'won', 'would', 'y', 'you', 'your', 'yours', 'yourself',
    'tell', 'give', 'today', 'tomorrow', 'yesterday', 'time', 'date', 'day', 'clock', 'hour', 'minute', 'second',
    'please', 'can', 'could', 'would', 'show', 'check', 'get'
}


def _tokenize(text: str) -> list:
    return re.findall(r'[a-zA-Z0-9_#]+', text.lower())


def _filter_query_tokens(tokens: list) -> list:
    return [t for t in tokens if t not in COMMON_STOPWORDS and len(t) > 1]


def is_temporal_query(query: str) -> bool:
    """Detects if query is purely asking for current time, date, day of week, or calendar info."""
    q = query.strip().lower()
    # If the user is asking about news, affairs, events, weather, stock, or topical info, it is NOT a clock query!
    if any(k in q for k in ["news", "affair", "affairs", "headline", "headlines", "event", "events", "happening", "happenings", "update", "updates", "weather", "market", "topic", "study", "exam", "test"]):
        return False
    time_patterns = [
        r'\b(?:what(?:\'?s| is)?|hat(?:\'?s| is)?|tell me|current|check|get)\s+(?:the\s+)?(?:time|date|day of the week|day today|clock)\b',
        r'^(?:what(?:\'?s| is)?\s+)?(?:today(?:\'?s)?|tomorrow(?:\'?s)?|yesterday(?:\'?s)?)\s+(?:date|day|time)$',
        r'^(?:what(?:\'?s| is)?\s+)?(?:date|time|day)\s+(?:today|tomorrow|yesterday)$',
        r'^(?:today|tomorrow|yesterday)$',
        r'\bwhats the date\b',
        r'\bwhat is tomorrow\b',
        r'\bwhat is the date\b',
        r'\bwhat is the time\b',
        r'\bwhats the time\b',
        r'\bwhat time is it\b',
        r'\bwhat day is today\b',
        r'\bwhat day is it\b',
        r'\bwhat day is tomorrow\b',
        r'\bwhich year is (?:this|it)\b',
        r'\bcurrent date and time\b',
        r'\bdate today\b',
        r'\btime now\b'
    ]
    return any(re.search(p, q) for p in time_patterns)


def is_news_or_current_affairs_query(query: str) -> bool:
    """Detects if the query is asking for current affairs, live news, recent headlines, or world events."""
    q = query.strip().lower()
    triggers = [
        "current affair", "current affairs", "today's news", "todays news", "today news",
        "latest news", "breaking news", "news today", "headlines", "top headlines",
        "recent events", "latest events", "what happened today", "what is happening today",
        "current events", "news in", "current affairs in"
    ]
    if any(t in q for t in triggers):
        return True
    if re.search(r'\b(news|headlines|current affairs)\b', q):
        return True
    return False


def clean_news_query(query: str) -> str:
    """Normalizes typos and extracts clean keyword for news feed searching."""
    q = query.lower()
    q = re.sub(r'\bfeeld\b', 'field', q)
    q = re.sub(r'\bartifical\b', 'artificial', q)
    q = re.sub(r'\binteligence\b', 'intelligence', q)

    clean = re.sub(r'^(what\s+are\s+)?(give\s+me\s+)?(tell\s+me\s+about\s+)?(check\s+for\s+)?(today\'?s?\s+)?(todays\s+)?(current\s+affairs\s+)?(news\s+)?(in\s+)?', '', q.strip(), flags=re.I)
    clean = re.sub(r'\b(current\s+affairs|latest\s+news|today\'?s?\s+news|news|field|feeld|today|from\s+the\s+internet|from\s+internet|internet)\b', '', clean, flags=re.I).strip()

    if 'ai' in q.split() or 'artificial intelligence' in q:
        return 'Artificial Intelligence AI technology'
    if clean and len(clean) > 2:
        return f'{clean} latest news'
    return ''


def fetch_live_news(query: str, max_items: int = 8) -> tuple:
    """
    Fetches verified live real-time news headlines via Google News RSS.
    Returns (context_text, sources_list) or (None, []) if offline or unreachable.
    """
    import urllib.request, urllib.parse, xml.etree.ElementTree as ET
    try:
        topic_term = clean_news_query(query)
        if topic_term:
            q_enc = urllib.parse.quote(topic_term)
            url = f"https://news.google.com/rss/search?q={q_enc}&hl=en-IN&gl=IN&ceid=IN:en"
        else:
            url = "https://news.google.com/rss?hl=en-IN&gl=IN&ceid=IN:en"

        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"})
        with urllib.request.urlopen(req, timeout=4.5) as resp:
            content = resp.read()
            root = ET.fromstring(content)
            items = root.findall('.//item')
            results = []
            context_lines = []
            for item in items[:max_items]:
                title = item.find('title').text if item.find('title') is not None else ''
                pubDate = item.find('pubDate').text if item.find('pubDate') is not None else ''
                link = item.find('link').text if item.find('link') is not None else ''
                source = item.find('source').text if item.find('source') is not None else ''
                if title:
                    results.append({
                        'doc_name': title,
                        'url': link,
                        'snippet': f'{pubDate} - Source: {source or "Verified News Feed"}',
                        'type': 'live_news'
                    })
                    context_lines.append(f"- **{title}** (Source: {source or 'News'}, Published: {pubDate})")
            if context_lines:
                print(f"[LIVE NEWS] Retrieved {len(context_lines)} live headlines for '{topic_term or 'top stories'}'")
                return "\n".join(context_lines), results
            return None, []
    except Exception as e:
        print(f"[LIVE NEWS OFFLINE / TIMEOUT]: {e}")
        return None, []


def retrieve_chunks_with_sources(query: str, doc_filter: str = "all", top_k: int = 4) -> tuple:
    """
    Searches local knowledge chunks using BM25 / term matching with zero database dependency.
    Returns (context_text, sources_list).
    """
    if doc_filter == "none":
        return "", []

    # If it's a pure temporal or clock query, do not search PDF course notes!
    if is_temporal_query(query):
        return "", []

    chunks = _load_knowledge_chunks()
    if not chunks:
        ensure_all_pdfs_indexed()
        chunks = _load_knowledge_chunks()

    if not chunks:
        return "", []

    # Filter by specific document if selected
    if doc_filter and doc_filter != "all" and doc_filter != "General":
        candidate_chunks = [c for c in chunks if c.get("doc_name") == doc_filter]
    else:
        candidate_chunks = chunks

    if not candidate_chunks:
        return "", []

    raw_query_tokens = _tokenize(query)
    # Stopword-filtered tokens for meaningful topical matching
    query_tokens = _filter_query_tokens(raw_query_tokens)
    if not query_tokens:
        return "", []

    # Compute BM25 scores
    scores = []
    for c in candidate_chunks:
        text = c.get("text", "")
        text_tokens = _tokenize(text)
        if not text_tokens:
            continue

        score = 0.0
        # Exact phrase bonus (only if meaningful words in query)
        if len(query.strip()) > 5 and query.strip().lower() in text.lower():
            score += 8.0

        # Term match of meaningful topical tokens
        text_token_set = set(text_tokens)
        matched_tokens = [t for t in query_tokens if t in text_token_set]
        match_count = len(matched_tokens)
        coverage = match_count / max(1, len(query_tokens))

        # Enforce genuine topical relevance:
        # If query has 3+ tokens, require at least 2 distinct matching tokens AND coverage >= 0.30 (or exact phrase match)
        has_phrase = len(query.strip()) > 5 and query.strip().lower() in text.lower()
        if not has_phrase:
            if len(query_tokens) >= 3 and (match_count < 2 or coverage < 0.28):
                continue
            elif len(query_tokens) < 3 and match_count == 0:
                continue

        if has_phrase:
            score += 8.0

        score += coverage * 6.0

        # Specific keyword occurrences
        for t in matched_tokens:
            if len(t) > 2:
                score += min(3.0, text_tokens.count(t) * 0.8)

        # Higher threshold ensuring genuine topical relevance
        if score > 3.0:
            scores.append((score, c))

    scores.sort(key=lambda x: x[0], reverse=True)
    top_candidates = [c for _, c in scores[:top_k]]

    if not top_candidates:
        return "", []

    context_parts = []
    sources = []
    seen_sources = set()

    for c in top_candidates:
        doc_name = c.get("doc_name", "Study Document")
        page = c.get("page", 1)
        text = c.get("text", "")

        src_key = f"{doc_name}:{page}"
        if src_key not in seen_sources:
            seen_sources.add(src_key)
            sources.append({
                "type": "local",
                "doc_name": doc_name,
                "page": page,
                "snippet": text[:200] + "..." if len(text) > 200 else text
            })
        context_parts.append(f"[{doc_name} - Page {page}]:\n{text}")

    context_text = "\n\n".join(context_parts)
    return context_text, sources


def retrieve_relevant_chunks(query: str, top_k: int = 4, student_id: int = 1) -> list:
    ctx, sources = retrieve_chunks_with_sources(query, doc_filter="all", top_k=top_k)
    if ctx:
        return [{"text": ctx, "sources": sources}]
    return []



SPAM_SEARCH_DOMAINS = {
    "todaysdatenow.com", "whatistodaydate.com", "datetoday.net", "datetoolshub.com",
    "todaydateandtime.com", "inspiritlive.com", "calendardate.com", "time.is"
}


# ─────────────────────────────────────────
# Live Web Search Engine (DuckDuckGo HTML + DDG Lite)
# ─────────────────────────────────────────
def web_search(query: str, max_results: int = 4) -> tuple:
    """
    Robust live web search using DuckDuckGo HTML parser.
    Extracts authoritative snippets, page titles, and decoded direct URLs.
    Returns (context_text, sources_list).
    """
    if not query or len(query.strip()) < 2:
        return "", []

    # Clean query of non-search noise
    clean_q = re.sub(r'^(please\s+)?(can\s+you\s+)?(give\s+me\s+)?(tell\s+me\s+about\s+)?(i\s+want\s+to\s+know\s+)?', '', query.strip(), flags=re.I)
    clean_q = re.sub(r'[^\w\s\+\-\.]', ' ', clean_q).strip()
    if not clean_q:
        clean_q = query.strip()

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9"
    }

    results = []
    context_parts = []

    # Method 1: DuckDuckGo HTML
    try:
        resp = requests.post(
            "https://html.duckduckgo.com/html/",
            data={"q": clean_q},
            headers=headers,
            timeout=4.5
        )
        if resp.status_code == 200 and len(resp.text) > 1000:
            soup = BeautifulSoup(resp.text, "html.parser")
            for r in soup.select(".result"):
                t_el = r.select_one(".result__title .result__a")
                s_el = r.select_one(".result__snippet")
                if not t_el or not s_el:
                    continue

                title = t_el.get_text(strip=True)
                snippet = s_el.get_text(strip=True)
                raw_href = t_el.get("href", "")

                # Decode DDG redirect URL to direct destination URL
                final_url = raw_href
                if "uddg=" in raw_href:
                    try:
                        parsed = parse_qs(urlparse(raw_href).query)
                        if "uddg" in parsed:
                            final_url = parsed["uddg"][0]
                    except Exception:
                        pass

                # Filter out low-value utility/SEO spam sites
                domain = urlparse(final_url).netloc.lower()
                if any(bad in domain for bad in SPAM_SEARCH_DOMAINS):
                    continue

                if snippet and len(snippet) > 25:
                    results.append({
                        "type": "web",
                        "doc_name": title,
                        "url": final_url,
                        "snippet": snippet,
                        "page": "Web"
                    })
                    context_parts.append(f"[{title}] ({final_url}):\n{snippet}")

                if len(results) >= max_results:
                    break
    except Exception as e:
        print(f"[WEB SEARCH DDG HTML ERROR]: {e}")

    # Method 2: Fallback to DuckDuckGo Lite if HTML gave 0 results
    if not results:
        try:
            resp_lite = requests.post(
                "https://lite.duckduckgo.com/lite/",
                data={"q": clean_q},
                headers=headers,
                timeout=4.0
            )
            if resp_lite.status_code == 200:
                soup_lite = BeautifulSoup(resp_lite.text, "html.parser")
                titles = soup_lite.select(".result-link")
                snippets = soup_lite.select(".result-snippet")
                for t_el, s_el in zip(titles[:max_results], snippets[:max_results]):
                    title = t_el.get_text(strip=True)
                    snippet = s_el.get_text(strip=True)
                    link = t_el.find("a")
                    href = link.get("href", "") if link else ""
                    if snippet and len(snippet) > 20:
                        results.append({
                            "type": "web",
                            "doc_name": title,
                            "url": href,
                            "snippet": snippet,
                            "page": "Web"
                        })
                        context_parts.append(f"[{title}]:\n{snippet}")
        except Exception as e:
            print(f"[WEB SEARCH DDG LITE ERROR]: {e}")

    print(f"[WEB SEARCH] Retrieved {len(results)} live results for query: '{clean_q}'")
    context_text = "\n\n".join(context_parts)
    return context_text, results


# ─────────────────────────────────────────
# Synergistic Dual-Retrieval: Local RAG + Live Web Search Working Together
# ─────────────────────────────────────────
def _is_student_performance_query(query: str, history: list = None) -> bool:
    q = query.lower()
    triggers = [
        "my test", "my report", "my score", "my performance", "tests attempted",
        "tests i attempted", "tests that i", "my weak areas", "how did i do",
        "how am i doing", "my progress", "my stats", "my knowledge points",
        "overall report of my tests", "report of the tests", "tests that i generated",
        "how many tests", "overall report", "my results", "my analytics",
        "tests i took", "tests taken", "my marks", "test reports", "tests here and attempted",
        "the tests that i generated here"
    ]
    if any(t in q for t in triggers):
        return True
    if history and isinstance(history, list):
        for h in history[-3:]:
            hc = (h.get("content") or "").lower()
            if any(k in hc for k in ["test", "report", "score", "performance", "attempt"]):
                if any(k in q for k in ["report", "scores", "how did i", "overall", "attempts", "here and attempted", "that i generated", "tests"]):
                    return True
    return False


def _is_conversational_greeting(query: str) -> bool:
    """
    Detects conversational greetings, pleasantries, check-ins, or introductions
    so the bot responds naturally like ChatGPT/Gemini without doing redundant web searches
    or lecturing the user on what a greeting means.
    """
    clean = re.sub(r'[^a-zA-Z\s]', ' ', query.strip().lower())
    clean = " ".join(clean.split())
    words = clean.split()
    if not words:
        return False

    common_phrases = {
        "hi", "hii", "hiii", "hello", "hey", "heyy", "namaste", "hola",
        "good morning", "good afternoon", "good evening", "good day", "good night", "howdy", "sup",
        "yo", "whats up", "what is up", "what s up", "what are you doing", "how are you", "how are you doing",
        "how are you doing today", "how are you today", "how has your day been", "how was your day",
        "how are things", "how is it going", "hows it going", "how are u", "how r u", "how do you do",
        "who are you", "what is your name", "whats your name", "tell me about yourself",
        "what can you do", "how can you help", "thank you", "thanks", "thank u", "thx",
        "thank you so much", "thanks a lot", "bye", "goodbye", "see you", "see ya", "take care", "nice to meet you"
    }

    # 1. Exact match on raw clean text
    if clean in common_phrases:
        return True

    # 2. Check after stripping bot name references (e.g. 'studyedge', 'studyedge ai', 'ai', 'bot')
    bot_stripped = re.sub(r'\b(studyedge\s*ai|studyedge|study\s*edge|ai|bot|assistant)\b', '', clean, flags=re.I).strip()
    bot_stripped = " ".join(bot_stripped.split())
    if bot_stripped in common_phrases or (bot_stripped and bot_stripped in {"hi", "hii", "hiii", "hello", "hey", "heyy"}):
        return True

    # 3. Check leading greeting word with rest
    b_words = (bot_stripped or clean).split()
    greetings_lead = {"hi", "hii", "hiii", "hello", "hey", "heyy"}
    if b_words and b_words[0] in greetings_lead:
        rest = " ".join(b_words[1:])
        if not rest or rest in common_phrases:
            return True

    patterns = [
        r'^(hi|hey|hello|yo)\b.*(how are you|hows it going|how are you doing|whats up|what s up|what is up)',
        r'^how (are you|are u|r u|is it going|have you been|has your day been|was your day)',
        r'^(who|what) are you\b',
        r'^what (is|are) your (name|purpose|capabilities)',
        r'^(thank you|thanks)\b',
        r'^(good morning|good afternoon|good evening|good night)\b'
    ]
    for p in patterns:
        if re.search(p, clean) or (bot_stripped and re.search(p, bot_stripped)):
            return True

    return False


def generate_answer(question: str, student_name: str = "Student", student_id: int = 1,
                    topic_filter: str = None, doc_filter: str = "all",
                    model_override: str = None, history: list = None,
                    extra_action_context: str = "") -> tuple:
    """
    Synergistic Dual-Retrieval + Personal Student Analytics Engine:
    1. Detects if student is asking about their own test reports, scores, or performance.
       If so, retrieves their actual test attempts, scores, and cognitive breakdown from local storage!
    2. Local RAG: Retrieves syllabus, specific course notes, exact questions, and curriculum definitions.
    3. Web Search: Retrieves up-to-date documentation, comprehensive explanations, and complete code.
    4. Synthesizes all sources seamlessly with zero boilerplate.
    """
    # Real time temporal anchor & calendar offsets from system clock
    now = datetime.now()
    tomorrow = now + timedelta(days=1)
    yesterday = now - timedelta(days=1)
    real_time_info = (
        f"- Today's Date: {now.strftime('%A, %B %d, %Y')}\n"
        f"- Current Time: {now.strftime('%I:%M %p')}\n"
        f"- Day of the Week: {now.strftime('%A')}\n"
        f"- Tomorrow's Date: {tomorrow.strftime('%A, %B %d, %Y')}\n"
        f"- Yesterday's Date: {yesterday.strftime('%A, %B %d, %Y')}\n"
        f"- Current Year: {now.year}\n"
        f"- Local Timezone: India Standard Time (IST, UTC+5:30)\n"
        f"- Environment Access: Live System Clock & Verified Web Active"
    )

    # ── Multi-Turn Conversation History ──
    history_text = ""
    if history and isinstance(history, list):
        recent = history[-8:]
        lines = []
        for msg in recent:
            role = "Student" if msg.get("sender") in ("user", "human") or msg.get("role") == "user" else "StudyEdge AI"
            content = (msg.get("content") or "").strip()
            if content:
                short = content[:350] + "..." if len(content) > 350 else content
                lines.append(f"{role}: {short}")
        if lines:
            history_text = "Prior Conversation History:\n" + "\n".join(lines) + "\n\n"

    # ── 1. Check for Student Personal Performance / Test Report Queries ──
    perf_context = ""
    perf_sources = []
    tot_correct = 0
    tot_possible = 0

    if student_id and _is_student_performance_query(question, history):
        try:
            import db, reports
            tests = db.get_test_history(student_id, limit=30)
            if tests:
                cat_perf = db.get_overall_category_performance(student_id)
                pts = reports.calculate_knowledge_points(tests)
                curve = reports.compute_forgetting_curve(tests)

                tot_correct = sum(t.get("totalScore", 0) for t in tests)
                tot_possible = sum(t.get("totalPossible", 0) for t in tests)
                overall_pct = round((tot_correct / tot_possible) * 100, 1) if tot_possible else 0

                lines = [
                    f"===  REAL TEST PERFORMANCE & HISTORY FOR {student_name.upper()} ===",
                    f"Total Tests Attempted: {len(tests)}",
                    f"Total Score Across All Tests: {tot_correct} / {tot_possible} ({overall_pct}%)",
                    f"Knowledge Points Earned: {pts.get('points')} Points (Tier: {pts.get('tier')})",
                    f"Estimated Memory Retention: {curve.get('retentionPercent')}%",
                    "\nCognitive Category Performance:",
                ]
                for cat, cdata in cat_perf.items():
                    lines.append(f"- {cat}: {cdata['score']}/{cdata['total']} ({cdata['percentage']}%)")

                lines.append("\nDetailed List of All Attempted Tests:")
                for idx, t in enumerate(tests, 1):
                    lines.append(f"{idx}. Date: {t.get('createdAt')} | Topic: '{t.get('topic')}' | Score: {t.get('totalScore')}/{t.get('totalPossible')} ({t.get('percentage')}%) | Time: {t.get('timeTakenSeconds', 0)}s")

                perf_context = "\n".join(lines)
                perf_sources.append({
                    "type": "local",
                    "doc_name": f"Student Test History ({len(tests)} Tests Attempted)",
                    "page": "Dashboard Analytics",
                    "snippet": f"Overall: {overall_pct}% ({tot_correct}/{tot_possible}), {pts.get('points')} Knowledge Points ({pts.get('tier')} Tier)"
                })
                print(f"[STUDENT REPORT] Injected personal test performance for student {student_id} ({len(tests)} tests)")
        except Exception as e:
            print(f"[PERFORMANCE CONTEXT ERROR]: {e}")

    is_greeting = _is_conversational_greeting(question)
    is_temporal = is_temporal_query(question)
    is_news = is_news_or_current_affairs_query(question)

    # ── 1c. Live News & Current Affairs (Google News RSS + Verified Feed) ──
    if is_news:
        news_context, news_sources = fetch_live_news(question)
        if news_context:
            prompt = f"""You are StudyEdge AI, an advanced AI tutor and companion with live verified internet access.
Current Date: {now.strftime('%A, %B %d, %Y')} ({now.strftime('%I:%M %p')} IST)

VERIFIED REAL-TIME LIVE NEWS FEED:
=================================================
{news_context}
=================================================

{history_text}Student Request: {question}

RESPONSE INSTRUCTIONS:
1. Provide a comprehensive, in-depth breakdown of these real live news stories.
2. For each major headline, provide a clear, detailed 2-3 sentence explanation detailing:
   - What happened & key context
   - Real-world impact & future implications
   - Verified publisher citation & publication timestamp
3. Group stories into clear markdown sections:
   - 🤖 AI & Emerging Technology
   - 🌐 National & Global Affairs
   - 💼 Economy, Policy & Industry
4. Base your answer strictly on the real news feed provided above. Do not invent details.
5. Deliver a rich, well-organized, and engaging report.

StudyEdge AI:"""
            bot_text = ollama_generate(prompt, task="qa", model_override=model_override, num_predict=650)
            return bot_text, news_sources, model_override or "mistral", "web"
        else:
            offline_msg = (
                f"⚠️ **Offline Mode — Internet Connection Required**\n\n"
                f"I am currently operating in **Local Offline Mode** without active internet access. "
                f"Live breaking news feeds and real-time current affairs require an internet connection.\n\n"
                f"💡 **What you can do offline:**\n"
                f"- Ask about academic concepts, computer science, mathematics, reasoning, or exam syllabus using local offline AI models.\n"
                f"- Study your uploaded PDF textbooks and study notes.\n"
                f"- Practice MCQ tests and track your forgetting curve.\n\n"
                f"*To view live real-time current affairs, please connect your device to the internet and ask again.*"
            )
            offline_sources = [{
                "type": "offline_notice",
                "doc_name": "Offline Mode (Internet Required for Live News)",
                "url": "",
                "snippet": "Internet is offline or unreachable. Live news feeds require an active internet connection.",
                "page": "Offline"
            }]
            return offline_msg, offline_sources, model_override or "mistral", "web"

    # ── 1b. Dynamic Scope / Document Selection (ChatGPT / Gemini Automatic Routing) ──
    chosen_doc_filter = select_optimal_doc_filter(question, preferred_filter=doc_filter)

    # ── 2. Local Notes RAG Retrieval (Skipped for greetings, temporal, personal test queries, or general mode) ──
    local_context = ""
    local_sources = []
    if chosen_doc_filter != "none" and not perf_context and not is_greeting and not is_temporal:
        local_context, local_sources = retrieve_chunks_with_sources(question, doc_filter=chosen_doc_filter, top_k=4)

    # ── 3. Live Web Search (Skipped for greetings, temporal, or personal test queries) ──
    web_context = ""
    web_sources = []
    if not perf_context and not is_greeting and not is_temporal:
        web_query = question
        if len(question.split()) <= 4 and local_sources:
            best_doc = local_sources[0].get("doc_name", "")
            clean_hint = re.sub(r'[\._\-]+', ' ', best_doc).replace('pdf', '').strip()
            tokens = [w for w in clean_hint.split() if len(w) > 3 and w.lower() not in ('section', 'part', 'chapter', 'notes', 'and', 'with')]
            if tokens:
                web_query = f"{question} {' '.join(tokens[:2])}"
        web_context, web_sources = web_search(web_query, max_results=4)

    # ── 4. Combine Contexts ──
    context_blocks = []
    if extra_action_context:
        context_blocks.append(extra_action_context)
    if perf_context:
        context_blocks.append(perf_context)
    if local_context:
        context_blocks.append("===  FROM YOUR UPLOADED STUDY NOTES ===\n" + local_context)
    if web_context:
        context_blocks.append("===  FROM LIVE VERIFIED WEB KNOWLEDGE ===\n" + web_context)

    combined_context = "\n\n".join(context_blocks)
    all_sources = [] if is_greeting else (perf_sources + local_sources + web_sources)
    if chosen_doc_filter == "web" and not web_sources and not is_greeting:
        all_sources.append({
            "type": "web_offline",
            "doc_name": "Offline Mode: Web Search Unreachable",
            "url": "",
            "snippet": "Live internet search timed out or is offline. Response synthesized autonomously with local neural knowledge.",
            "page": "Offline"
        })

    # ── 5. Multi-Turn Conversation History ──
    # History text already extracted at top of function

    # Real time temporal anchor & calendar offsets from system clock
    now = datetime.now()
    tomorrow = now + timedelta(days=1)
    yesterday = now - timedelta(days=1)
    real_time_info = (
        f"- Today's Date: {now.strftime('%A, %B %d, %Y')}\n"
        f"- Current Time: {now.strftime('%I:%M %p')}\n"
        f"- Day of the Week: {now.strftime('%A')}\n"
        f"- Tomorrow's Date: {tomorrow.strftime('%A, %B %d, %Y')}\n"
        f"- Yesterday's Date: {yesterday.strftime('%A, %B %d, %Y')}\n"
        f"- Current Year: {now.year}\n"
        f"- Local Timezone: India Standard Time (IST, UTC+5:30)\n"
        f"- Environment Access: Live System Clock & Verified Web Active"
    )

    # ── 6. Prompting ──
    if is_temporal:
        prompt = f"""You are StudyEdge AI, an advanced, highly intelligent AI tutor and universal assistant like ChatGPT and Gemini.
You have direct, real time system and internet access.

REAL-TIME SYSTEM CLOCK & CALENDAR:
{real_time_info}

{history_text}Student: {question}

RESPONSE INSTRUCTIONS:
1. Answer the student's question directly, precisely, and conversationally using the REAL-TIME SYSTEM CLOCK & CALENDAR provided above.
2. If asked about today, tomorrow, yesterday, time, day, or year, state the exact date or time directly.
3. NEVER say "I don't have access to real time information" or "I cannot provide real time updates".
4. NEVER direct the student to external websites (like todaydateandtime.com, time.is, or datetoday.net) to check the time or date.
5. Keep your tone warm, concise, and helpful.

StudyEdge AI:"""
    elif perf_context:
        prompt = f"""You are StudyEdge AI, an advanced AI tutor and personal academic advisor for {student_name}.
You have direct real time system and internet access.
Current Date: {now.strftime('%A, %B %d, %Y')}

The student is asking about their test reports, performance metrics, and history on this platform.

{history_text}STUDENT'S ACTUAL TEST ATTEMPT RECORDS:
---
{perf_context}
---

Student Question: {question}

RESPONSE INSTRUCTIONS:
1. Provide a comprehensive, clear, and encouraging overall performance report based directly on the student's actual test data above.
2. Structure your report clearly:
   -  Overall Performance Summary (Total tests, overall score {tot_correct}/{tot_possible}, Knowledge Points & Tier)
   -  Cognitive Category Breakdown (Highlight their strongest areas and areas needing improvement)
   -  Key Highlighted Tests (Mention top scores like 100% and 98.3%, and recent tests)
   -  Actionable Improvement Advice (Focused tips for their lower scoring categories)
3. Do NOT lecture on general software testing concepts. Speak directly to {student_name} about their actual results.

StudyEdge AI:"""
    elif extra_action_context:
        prompt = f"""You are StudyEdge AI, an advanced AI companion and academic advisor for {student_name} like ChatGPT and Gemini.
You have direct real time system and internet access.
Current Date & Time: {now.strftime('%A, %B %d, %Y, %I:%M %p')}

{history_text}{extra_action_context}

---
REFERENCE KNOWLEDGE:
{combined_context}
---

Student Request: {question}

RESPONSE INSTRUCTIONS:
1. Warmly and clearly confirm that you have officially scheduled this study plan inside the app (in their Study Planner) for the requested time.
2. Provide a concise, high-yield study session roadmap (Core Concepts, Applied Logic, Practice Drills, Knowledge Check).
3. Do NOT tell the student to install external third-party apps or make the plan themselves. The plan is already active in their Study Planner tab!
4. Encourage them and invite them to launch the session using the interactive card below or from the Study Planner tab.

StudyEdge AI:"""
    elif is_greeting:
        prompt = f"""You are StudyEdge AI, a helpful, brilliant, and friendly AI assistant and tutor like ChatGPT and Gemini.
Current Time & Date: {now.strftime('%A, %B %d, %Y, %I:%M %p')}

{history_text}User: {question}

RESPONSE GUIDELINES:
1. Respond warmly, naturally, and conversationally just like ChatGPT or Gemini (e.g. "Hello! I'm doing well, thank you! How are you? What can I help you with today?").
2. Answer any check-in question directly and casually (e.g. if asked "how are you doing", say you're doing great and ready to help).
3. NEVER write an essay, grammar lesson, or breakdown analyzing what the greeting means.
4. NEVER cite external websites or ESL forums for a simple greeting.
5. Keep your response brief, friendly, and under 2-3 sentences.

StudyEdge AI:"""
    elif combined_context:
        prompt = f"""You are StudyEdge AI, an advanced, highly versatile AI assistant and expert tutor like ChatGPT and Gemini.
You have direct real time system and internet access.
Current Date & Time: {now.strftime('%A, %B %d, %Y, %I:%M %p')}

Answer the student's question accurately, thoroughly, with comprehensive explanatory depth.

{history_text}REFERENCE KNOWLEDGE (Study Notes & Live Web Search working together):
---
{combined_context}
---

Current Student Question: {question}

SYNERGISTIC RESPONSE GUIDELINES:
1. Provide a rich, thorough, and in-depth educational response:
   - Ground your answer in syllabus definitions, terminology, and course focus if present.
   - Use live web knowledge to enrich the answer with deep explanations, practical real-world context, edge cases, and complete examples.
2. Structure your explanation clearly using markdown headers, bullet points, bold key terms, and numbered steps.
3. If code or programming is needed, write clean, complete, working code in markdown code fences with the language tag (e.g. ```python) and include explanatory comments.
4. Provide complete conceptual depth — do not give shallow or overly brief answers.
5. Provide accurate, verified answers — never make up information. If a question asks about a fictional claim or future unverified event, clarify factually.

StudyEdge AI:"""
    else:
        prompt = f"""You are StudyEdge AI, an advanced, highly versatile AI assistant and expert tutor like ChatGPT and Gemini.
You have direct real time system and internet access.
Current Date & Time: {now.strftime('%A, %B %d, %Y, %I:%M %p')}

Answer the student's question accurately, comprehensively, and with rich explanatory detail for any kind of task (programming, writing, calculations, reasoning, general knowledge, or curriculum study).

{history_text}Current Student Question: {question}

RESPONSE GUIDELINES:
1. Provide an in-depth, clear, and comprehensive answer with thorough explanations and concrete examples.
2. If code or programming is requested, write complete, syntactically correct code blocks in markdown fences (e.g. ```python) with step-by-step walkthroughs.
3. Format with clean markdown headers, bold key terms, and bullet points.
4. Avoid shallow or truncated replies; give the student a complete, thorough understanding.
5. Fact Verification: If the user asks about a fictional concept or unverified claim, state clearly that it is fictional or unverified.

StudyEdge AI:"""

    tokens = 120 if (is_greeting or is_temporal) else 700
    chosen_model = select_optimal_model(question, preferred_model=model_override)
    answer = ollama_generate(prompt, task="qa", model_override=chosen_model, num_predict=tokens)
    return answer, all_sources, chosen_model, chosen_doc_filter


# ─────────────────────────────────────────
def generate_topic_summary(topic_name: str, student_name: str, model_override: str = None, note_content: str = None) -> str:
    if note_content and len(note_content.strip()) > 20:
        context = note_content.strip()[:3500]
        prompt = f"""Provide a clear, high-yield audio study summary of the following notes titled "{topic_name}":
1. Key Summary (2-3 concise sentences explaining the core takeaway)
2. Essential Concepts and Bullet Points
3. Practical Application & Review Takeaways

Study Notes:
{context}

Summary:"""
        return ollama_generate(prompt, task="summary", model_override=model_override, num_predict=650)

    context, _ = retrieve_chunks_with_sources(topic_name, doc_filter="all", top_k=4)
    if context:
        prompt = f"""Summarize the following study notes on the topic "{topic_name}":
1. Comprehensive Overview (3-4 sentences explaining core significance)
2. Key Concepts & Definitions (5 structured bullet points)
3. Practical Takeaways & Application Notes

Study Notes:
{context}

Summary:"""
    else:
        prompt = f"""Provide a comprehensive study summary on the topic "{topic_name}":
1. Topic Overview (3-4 sentences)
2. 5 Essential Principles / Concepts
3. Practical Application & Examples

Summary:"""

    return ollama_generate(prompt, task="summary", model_override=model_override, num_predict=750)


def generate_study_questions(topic_name: str, student_name: str, count: int = 5, model_override: str = None) -> list:
    context, _ = retrieve_chunks_with_sources(topic_name, doc_filter="all", top_k=3)
    prompt = f"""Generate {count} challenging study review questions on "{topic_name}".
Context from notes:
{context[:1000] if context else 'General academic topic'}

Return each question on a numbered line."""
    resp = ollama_generate(prompt, task="questions", model_override=model_override, num_predict=500)
    lines = [l.strip() for l in resp.split("\n") if re.match(r'^\d+[\.\)]', l.strip())]
    return lines[:count] if lines else [resp]


def generate_weakness_report(weak_areas: list, model_override: str = None) -> str:
    if not weak_areas:
        return "No weak areas detected yet. Keep taking practice tests!"
    topics = ", ".join([w.get("topic", "") for w in weak_areas])
    prompt = f"""As an academic advisor, generate a personalized diagnostic analysis and targeted improvement roadmap for a student struggling in these areas: {topics}.
Structure with:
1. Diagnosis & Root Causes
2. Targeted Study Recommendations
3. Practical 3-Day Action Plan"""
    return ollama_generate(prompt, task="analytics", model_override=model_override, num_predict=700)


def get_indexed_topics(student_name: str = None) -> list:
    chunks = _load_knowledge_chunks()
    topics = sorted(list(set(c.get("topic") or c.get("doc_name") for c in chunks)))
    return topics


# ─────────────────────────────────────────
# AI Tutor & Tester: Autonomous Curriculum Generator (Dual RAG + Web Search)
# ─────────────────────────────────────────
# AI Tutor & Tester: Autonomous Curriculum Generator (Dual RAG + Web Search)
# ─────────────────────────────────────────
def generate_plan_preview(topic: str, doc_name: str = None, student_id: int = 1) -> dict:
    """
    Generates a crisp 1-2 sentence preview summary of what a 4-stage sprint on 'topic' will cover,
    adapting strictly to the domain (English, Science, Humanities, Business, or Tech).
    """
    source_label = f"Document: {doc_name}" if doc_name else "Academic Knowledge & Web Grounding"
    
    # Fast prompt to generate a domain-accurate 1-sentence summary
    prompt = f"""You are a master academic curriculum advisor.
A student is about to start a 4-stage study sprint on: '{topic}'.
Write a clear, inspiring ONE-SENTENCE summary (under 28 words) stating what this study session will cover from foundation to mastery.
Domain Rule: Adapt strictly to '{topic}'. Do NOT mention software or coding unless '{topic}' is explicitly about computer programming.
Return ONLY that single sentence."""
    
    summary = ""
    try:
        raw = ollama_generate(prompt, task="qa", model_override="phi3:latest", num_predict=80)
        clean = raw.strip().replace('"', '').replace('\n', ' ')
        if len(clean) > 20 and not clean.lower().startswith("here"):
            summary = clean
    except Exception:
        pass

    if not summary:
        summary = f"A comprehensive 4-stage mastery curriculum on {topic}, guiding you from core definitions and mental models to practical application and exam-level active retrieval."

    return {
        "topic": topic,
        "doc_name": doc_name or "",
        "source": source_label,
        "summary": summary,
        "stages": [
            "Stage 1: Foundation & Core Intuition (20m)",
            "Stage 2: Mechanism & Applied Logic (25m)",
            "Stage 3: Active Recall & Problem Solving (15m)",
            "Stage 4: Mastery Verification Exam (15m)"
        ]
    }


def clean_topic_title(raw_name: str) -> str:
    """Cleans raw PDF filenames into clean human-readable book/topic titles."""
    clean = str(raw_name or "")
    clean = re.sub(r'^(?:_|\s)+', '', clean)
    clean = re.sub(r'\.pdf$', '', clean, flags=re.IGNORECASE)
    clean = clean.replace('_', ' ').replace('-', ' ').strip()
    clean = re.sub(r'\s+', ' ', clean)
    return clean or "General Study"


def _generate_grounded_drill(topic: str, round_title: str, passage: str, round_num: int) -> dict:
    """Synthesizes a practice drill question strictly grounded in the passage text, without generic meta-study tips."""
    clean_topic = clean_topic_title(topic)
    
    if passage and len(passage.strip()) > 60:
        prompt = f"""Based strictly on this study excerpt from '{clean_topic}' ({round_title}):
\"\"\"{passage[:800]}\"\"\"

Generate 1 multiple-choice practice question testing a specific conceptual definition, mechanism, or technical relationship from the text above.
Rules:
- Strictly test the factual content of the text above.
- Do NOT generate questions about study habits, memorization strategies, or test-taking advice.
- Return ONLY valid JSON with this format:
{{
  "question": "Clear, specific question about the content",
  "options": ["Correct answer", "Plausible alternative 1", "Plausible alternative 2", "Plausible alternative 3"],
  "correct_index": 0,
  "explanation": "Clear explanation grounded in the text."
}}"""
        try:
            res = ollama_generate(prompt, task="questions", model_override="phi3:latest", num_predict=220)
            clean = re.sub(r'```(?:json)?', '', res).strip()
            s = clean.find('{')
            e = clean.rfind('}')
            if s != -1 and e != -1:
                q_obj = json.loads(clean[s:e+1])
                if "question" in q_obj and isinstance(q_obj.get("options"), list) and len(q_obj["options"]) == 4:
                    return q_obj
        except Exception as ex:
            print(f"[GROUNDED DRILL LLM NOTE]: {ex}")

        # Smart fallback from passage: extract first informative sentence
        sentences = [s.strip() for s in re.split(r'[.!?]\s+', passage) if len(s.strip()) > 35 and not s.strip().startswith(('http', '[', 'xv', 'About', 'Page'))]
        if sentences:
            core_fact = sentences[0]
            if len(core_fact) > 130:
                core_fact = core_fact[:127] + "..."
            return {
                "question": f"In the study of {clean_topic} ({round_title}), which of the following is a primary principle or component established in this section?",
                "options": [
                    f"{core_fact}.",
                    f"Prioritizing surface-level syntax over fundamental structural mechanics in {clean_topic}.",
                    f"Treating all operational parameters as static constants regardless of context in {clean_topic}.",
                    f"Bypassing baseline data transformations without verifying input consistency."
                ],
                "correct_index": 0,
                "explanation": f"The core text establishes: '{core_fact}' as a primary concept in {clean_topic}."
            }

    # Subject-specific grounded fallback (NO generic meta-study tips)
    stage_themes = {
        1: (f"What is the foundational definition and core purpose of {clean_topic}?",
            f"It provides the foundational framework and baseline rules to model and analyze systems accurately.",
            f"It operates without structured rules or deterministic relationships.",
            f"It applies only to non-reproducible edge cases.",
            f"It replaces conceptual understanding with arbitrary assumptions."),
        2: (f"In practical application of {clean_topic}, how do the primary mechanisms interact?",
            f"Inputs and baseline parameters are processed sequentially through verified operational stages.",
            f"Output states are generated spontaneously without following initial conditions.",
            f"Operational parameters remain completely independent of contextual constraints.",
            f"Intermediate stages are skipped without state verification."),
        3: (f"When evaluating an edge case or advanced scenario in {clean_topic}, what is critical to verify?",
            f"Boundary conditions and input parameter constraints to maintain system validity.",
            f"Discarding boundary limits to force a default outcome.",
            f"Assuming edge cases can never alter expected results.",
            f"Ignoring contextual constraints during state transitions."),
        4: (f"Which of the following demonstrates complete mastery of {clean_topic}?",
            f"Accurately tracing end-to-end logic, resolving edge cases, and validating results against core principles.",
            f"Memorizing isolated terminology without understanding underlying mechanisms.",
            f"Applying arbitrary rules when encountering unfamiliar scenarios.",
            f"Disregarding boundary constraints during practical execution.")
    }
    q, c_opt, d1, d2, d3 = stage_themes.get(round_num, stage_themes[1])
    return {
        "question": q,
        "options": [c_opt, d1, d2, d3],
        "correct_index": 0,
        "explanation": f"In {clean_topic}, understanding core principles and verified operational mechanisms is essential for accurate problem solving."
    }


def generate_rounds_with_mistral(topic: str, source_type: str = "Academic Knowledge", local_text: str = "", custom_focus: str = None) -> list:
    """
    Invokes Mistral to autonomously generate a high-accuracy, topic-specific 4-stage study plan.
    Strictly forbids generic meta-study boilerplate and adapts directly to the topic and context.
    """
    clean_topic = clean_topic_title(topic)
    focus_instruction = f" Special student focus: {custom_focus}." if custom_focus else ""
    
    prompt = f"""You are an elite academic curriculum architect.
A student wants to study and master: '{clean_topic}'.{focus_instruction}
Knowledge Context ({source_type}):
{local_text[:900] if local_text else clean_topic}

Design a customized 4-round Pomodoro study plan for high academic accuracy.
Every single round MUST have a concrete, topic-specific title and an actionable learning objective tailored strictly to '{clean_topic}'.
Rule: Do NOT use generic meta-study titles like 'Foundation & Core Intuition' or 'Mechanism & Applied Logic'.
Rule: Do NOT use generic phrases like 'understand definitions of {clean_topic}'.

Output ONLY a JSON array with 4 objects:
[
  {{"round_number": 1, "title": "<Specific Topic Title 1>", "mode": "Tutor", "suggested_duration_mins": 25, "objective": "<Concrete Learning Objective 1>"}},
  {{"round_number": 2, "title": "<Specific Topic Title 2>", "mode": "Tutor", "suggested_duration_mins": 25, "objective": "<Concrete Learning Objective 2>"}},
  {{"round_number": 3, "title": "<Specific Practice/Recall Title 3>", "mode": "Tester", "suggested_duration_mins": 25, "objective": "<Concrete Learning Objective 3>"}},
  {{"round_number": 4, "title": "<Specific Mastery Exam Title 4>", "mode": "Tester", "suggested_duration_mins": 25, "objective": "<Concrete Learning Objective 4>"}}
]"""

    try:
        raw = ollama_generate(prompt, task="curriculum", model_override="mistral", num_predict=450)
        match = re.search(r'\[.*\]', raw, re.DOTALL)
        if match:
            parsed = json.loads(match.group(0))
            if isinstance(parsed, list) and len(parsed) >= 3:
                print(f"[CURRICULUM] Mistral successfully generated {len(parsed)} customized rounds for '{clean_topic}'!")
                return parsed
    except Exception as e:
        print(f"[CURRICULUM MISTRAL ERROR]: {e}")

    # Fallback retry with Mistral using a fast direct instruction
    try:
        fast_prompt = f"Output a JSON list with 4 Pomodoro stages for studying '{clean_topic}'. Each with keys: round_number (1-4), title (specific topic concept), mode ('Tutor' or 'Tester'), suggested_duration_mins (25, 25, 25, 25), objective (actionable goal for {clean_topic}). JSON only."
        raw2 = ollama_generate(fast_prompt, task="curriculum", model_override="mistral", num_predict=350)
        match2 = re.search(r'\[.*\]', raw2, re.DOTALL)
        if match2:
            parsed2 = json.loads(match2.group(0))
            if isinstance(parsed2, list) and len(parsed2) >= 3:
                return parsed2
    except Exception:
        pass

    return [
        {"round_number": 1, "title": f"Core Foundations of {clean_topic}", "mode": "Tutor", "suggested_duration_mins": 25, "objective": f"Master foundational principles, definitions, and core mental models of {clean_topic}."},
        {"round_number": 2, "title": f"Applied Mechanisms & Analysis of {clean_topic}", "mode": "Tutor", "suggested_duration_mins": 25, "objective": f"Analyze working methods, step-by-step logic, and practical applications of {clean_topic}."},
        {"round_number": 3, "title": f"Active Recall & Problem Solving on {clean_topic}", "mode": "Tester", "suggested_duration_mins": 25, "objective": f"Test yourself on edge-case scenarios, problem solving, and key formulas from memory."},
        {"round_number": 4, "title": f"Diagnostic Mastery Verification on {clean_topic}", "mode": "Tester", "suggested_duration_mins": 25, "objective": f"Comprehensive diagnostic verification to solidify retention and eliminate blind spots in {clean_topic}."}
    ]


def generate_study_curriculum(topic: str, student_id: int = 1, doc_name: str = None, custom_focus: str = None) -> dict:
    """
    Generates a structured multi-Pomodoro study curriculum with dynamic time allocation,
    rich study guide notes (Tutor mode), and active scenario drills (Tester mode).
    If local PDF notes are insufficient, seamlessly retrieves web knowledge via DuckDuckGo.
    Uses Mistral for high accuracy and topic-specific depth.
    """
    clean_topic = clean_topic_title(topic)
    print(f"[CURRICULUM] Synthesizing study curriculum for '{clean_topic}' (doc: {doc_name}, focus: {custom_focus})...")

    local_text = ""
    sources = []
    source_type = "Academic Curriculum"

    # Check if clean_topic explicitly matches any local document name
    matched_doc = None
    if not doc_name:
        all_chunks = _load_knowledge_chunks()
        doc_names_set = set(c.get("doc_name") for c in all_chunks if c.get("doc_name"))
        topic_clean_lower = clean_topic.lower()
        for dn in doc_names_set:
            c_dn = clean_topic_title(dn).lower()
            if len(topic_clean_lower) >= 5 and (topic_clean_lower in c_dn or c_dn in topic_clean_lower):
                matched_doc = dn
                break

    # 1. If personal note requested from Quick Tools -> Notes
    if doc_name and (str(doc_name).startswith("my_note:") or str(doc_name).startswith("user_note:")):
        nid = str(doc_name).split(":")[1]
        try:
            import db
            all_user_notes = db.get_user_notes(student_id)
            target_note = next((n for n in all_user_notes if str(n.get("id")) == str(nid)), None)
            if target_note:
                ntitle = target_note.get("title", clean_topic)
                ncontent = target_note.get("content", "")
                local_text = f"=== STUDENT'S PERSONAL STUDY NOTES: {ntitle} ===\n{ncontent}"
                sources = [f"Personal Note: {ntitle}"]
                source_type = f"Personal Note: {ntitle}"
                print(f"[CURRICULUM] Grounding curriculum directly on user note: '{ntitle}' ({len(ncontent)} chars)")
        except Exception as e:
            print(f"[NOTE GROUNDING ERROR]: {e}")

    # If explicit document requested (or exact match to document title), retrieve from that document
    elif doc_name:
        context_text, src_list = retrieve_chunks_with_sources(clean_topic, doc_filter=doc_name, top_k=6)
        local_text = context_text
        sources = [clean_topic_title(doc_name)]
        source_type = f"Document: {clean_topic_title(doc_name)}"
    elif matched_doc:
        print(f"[CURRICULUM] Topic '{clean_topic}' matched local document '{matched_doc}'")
        context_text, src_list = retrieve_chunks_with_sources(clean_topic, doc_filter=matched_doc, top_k=6)
        local_text = context_text
        sources = [clean_topic_title(matched_doc)]
        source_type = f"Document: {clean_topic_title(matched_doc)}"
    else:
        # 2. Open Topic: Live Web Research (DuckDuckGo) + Academic Curriculum
        search_query = f"{clean_topic} {custom_focus or ''} comprehensive guide core concepts principles tutorial".strip()
        print(f"[CURRICULUM] Searching web knowledge for open topic: '{search_query}'...")
        web_text, web_sources = web_search(search_query, max_results=4)
        if web_text and len(web_text.strip()) > 100:
            local_text = web_text
            sources = [ws.get("doc_name", "Web") for ws in web_sources]
            source_type = "Live Web Research"
        else:
            local_text = ""
            sources = ["Authoritative Academic Knowledge"]
            source_type = "Academic Curriculum"

    # Autonomously generate 4 custom rounds using Mistral
    llm_rounds = generate_rounds_with_mistral(clean_topic, source_type, local_text, custom_focus)

    # Slice text into 4 distinct semantic passages for the 4 stages
    text_len = len(local_text)
    step = max(1, text_len // 4)
    slice_1 = local_text[0 : step].strip()
    slice_2 = local_text[step : step * 2].strip()
    slice_3 = local_text[step * 2 : step * 3].strip()
    slice_4 = local_text[step * 3 :].strip()

    def _format_stage_notes(round_num: int, title: str, excerpt: str) -> str:
        clean_snip = re.sub(r'https?://\S+', '', excerpt)
        clean_snip = re.sub(r'\[.*?\](?::|\s*)', '', clean_snip)
        clean_snip = re.sub(r'\(.*?\)(?::|\s*)', '', clean_snip)
        clean_snip = re.sub(r'#+\s*$', '', clean_snip).strip()
        # Add space between lowercase and uppercase words if concatenated (e.g. toEnglish -> to English)
        clean_snip = re.sub(r'([a-z])([A-Z])', r'\1 \2', clean_snip)
        clean_snip = re.sub(r'\s+', ' ', clean_snip).strip()[:650]
        clean_snip = clean_snip.rstrip('#-:;,.').strip()

        if clean_snip and len(clean_snip) > 80:
            return (
                f"###  Stage {round_num}: {title} — {clean_topic}\n\n"
                f"{clean_snip}\n\n"
                f"#### Core Objectives for this Stage:\n"
                f"1. **Conceptual Grounding**: Connect each primary definition in **{clean_topic}** to verified fundamentals.\n"
                f"2. **Operational Clarity**: Follow the sequential transformations and working methods described in the text.\n"
                f"3. **Practical Retention**: Test comprehension of subtle nuances and boundary conditions before advancing."
            )
        else:
            stage_outlines = {
                1: (f"Master the primary definitions, foundational principles, and core mental models of **{clean_topic}**.\n\n"
                    f"#### 1. Foundational Definition & Scope\n"
                    f"- Establish baseline rules, primary conventions, and key terminology in **{clean_topic}**.\n"
                    f"- Understand how central concepts build logically upon initial premises.\n\n"
                    f"#### 2. Intuitive Mental Model\n"
                    f"- Examine practical everyday applications of **{clean_topic}** to ground abstract principles.\n"
                    f"- Move beyond surface memorization by analyzing why specific rules and conventions exist."),
                2: (f"Explore working methods, applied logic, and step-by-step mechanisms in **{clean_topic}**.\n\n"
                    f"#### Analytical Process\n"
                    f"1. **Baseline Assessment**: Verify initial conditions and premises.\n"
                    f"2. **Applied Reasoning**: Work through primary relationships, transformations, or rhetorical rules step-by-step.\n"
                    f"3. **Synthesis**: Verify outcomes against foundational principles.\n\n"
                    f"#### Edge Cases & Nuance\n"
                    f"- Identify nuanced exceptions or boundary conditions where standard rules require careful adjustments."),
                3: (f"Test yourself from memory without referencing notes. Active retrieval produces maximum long-term retention.\n\n"
                    f"#### Retrieval Exercise\n"
                    f"- Explain the core mechanism of **{clean_topic}** in your own words in 60 seconds.\n"
                    f"- Solve the active scenario drill below without checking reference material."),
                4: (f"High-yield diagnostic review to solidify permanent mastery of **{clean_topic}**.\n\n"
                    f"#### Capstone Mastery Verification\n"
                    f"- Synthesize end-to-end knowledge and verify practical problem-solving capability.\n"
                    f"- Review diagnostic feedback to eliminate remaining cognitive blind spots.")
            }
            body = stage_outlines.get(round_num, stage_outlines[1])
            return (
                f"###  Stage {round_num}: {title} — {clean_topic}\n\n"
                f"{body}"
            )

    t1 = llm_rounds[0].get("title") if llm_rounds and len(llm_rounds) > 0 else "Foundation & Core Intuition"
    t2 = llm_rounds[1].get("title") if llm_rounds and len(llm_rounds) > 1 else "Mechanism & Applied Logic"
    t3 = llm_rounds[2].get("title") if llm_rounds and len(llm_rounds) > 2 else "Active Recall & Problem Solving"
    t4 = llm_rounds[3].get("title") if llm_rounds and len(llm_rounds) > 3 else "Mastery Verification Exam"

    drill_1 = _generate_grounded_drill(clean_topic, t1, slice_1, 1)
    drill_2 = _generate_grounded_drill(clean_topic, t2, slice_2, 2)
    drill_3 = _generate_grounded_drill(clean_topic, t3, slice_3, 3)
    drill_4 = _generate_grounded_drill(clean_topic, t4, slice_4, 4)

    curriculum = {
        "topic": clean_topic,
        "doc_name": doc_name or "",
        "custom_focus": custom_focus or "",
        "source_type": source_type,
        "overview": f"A comprehensive 4-stage mastery curriculum on {clean_topic}{' focusing on ' + custom_focus if custom_focus else ''}, taking you from fundamental intuition to practical application and exam-level active retrieval.",
        "total_suggested_mins": 75,
        "rounds": [
            {
                "round_number": 1,
                "title": t1,
                "mode": (llm_rounds[0].get("mode") if llm_rounds and len(llm_rounds) > 0 else "Tutor"),
                "suggested_duration_mins": 25,
                "objective": (llm_rounds[0].get("objective") if llm_rounds and len(llm_rounds) > 0 else f"Understand primary definitions and intuitive mental models of {clean_topic}."),
                "study_content_markdown": _format_stage_notes(1, t1, slice_1),
                "active_checkpoints": [
                    {"task": f"Define the core principle of {clean_topic} in your own words", "done": False},
                    {"task": "Identify the 3 most important terms, rules, or concepts", "done": False}
                ],
                "practice_drills": [drill_1]
            },
            {
                "round_number": 2,
                "title": t2,
                "mode": (llm_rounds[1].get("mode") if llm_rounds and len(llm_rounds) > 1 else "Tutor"),
                "suggested_duration_mins": 25,
                "objective": (llm_rounds[1].get("objective") if llm_rounds and len(llm_rounds) > 1 else f"Master working methods, step-by-step logic, and practical applications of {clean_topic}."),
                "study_content_markdown": _format_stage_notes(2, t2, slice_2),
                "active_checkpoints": [
                    {"task": "Analyze a concrete practical example from start to finish", "done": False},
                    {"task": "Identify 2 nuanced edge cases or exceptions in this topic", "done": False}
                ],
                "practice_drills": [drill_2]
            },
            {
                "round_number": 3,
                "title": t3,
                "mode": (llm_rounds[2].get("mode") if llm_rounds and len(llm_rounds) > 2 else "Tester"),
                "suggested_duration_mins": 25,
                "objective": (llm_rounds[2].get("objective") if llm_rounds and len(llm_rounds) > 2 else f"Test yourself from memory without referencing notes."),
                "study_content_markdown": (
                    f"###  Stage 3: Active Retrieval Drill (Closed-Book) — {clean_topic}\n\n"
                    f"**Instruction**: Close your notes! Testing yourself through active recall builds strong neural retention.\n\n"
                    f"Try explaining the core concepts of **{clean_topic}** out loud or writing a 60-second summary before answering the drill below."
                ),
                "active_checkpoints": [
                    {"task": f"Explain the core mechanism of {clean_topic} in your own words in 60 seconds", "done": False},
                    {"task": "Solve the active recall question on the first attempt", "done": False}
                ],
                "practice_drills": [drill_3]
            },
            {
                "round_number": 4,
                "title": t4,
                "mode": (llm_rounds[3].get("mode") if llm_rounds and len(llm_rounds) > 3 else "Tester"),
                "suggested_duration_mins": 25,
                "objective": (llm_rounds[3].get("objective") if llm_rounds and len(llm_rounds) > 3 else f"High-yield diagnostic test to solidify long-term retention of {clean_topic}."),
                "study_content_markdown": (
                    f"###  Stage 4: Final Mastery Verification — {clean_topic}\n\n"
                    f"Congratulations on reaching the final round! This sprint locks {clean_topic} into permanent memory.\n\n"
                    f"Answer the capstone question below and review the diagnostic feedback to verify mastery."
                ),
                "active_checkpoints": [
                    {"task": "Answer the final capstone question", "done": False},
                    {"task": "Review diagnostic feedback and log Knowledge Points", "done": False}
                ],
                "practice_drills": [drill_4]
            }
        ]
    }
    return curriculum


def generate_more_drills(topic: str, round_title: str, student_id: int = 1, session_id: int = None, doc_name: str = None) -> list:
    """Generates 3 additional high-yield practice drills strictly grounded in document/session context."""
    clean_topic = clean_topic_title(topic)
    
    passage_ctx = ""
    if session_id:
        cur_file = os.path.join(CURRICULUM_DIR, f"curriculum_{session_id}.json")
        if os.path.exists(cur_file):
            try:
                with open(cur_file, "r", encoding="utf-8") as f:
                    cdata = json.load(f)
                doc_name = doc_name or cdata.get("doc_name")
                for r in cdata.get("rounds", []):
                    if round_title.lower() in r.get("title", "").lower():
                        passage_ctx = r.get("study_content_markdown", "")
                        break
            except Exception:
                pass

    if not passage_ctx and doc_name:
        text, _ = retrieve_chunks_with_sources(round_title, doc_filter=doc_name, top_k=3)
        passage_ctx = text[:1500]

    prompt = f"""Generate 3 multiple-choice practice drills (MCQs) for the study topic: '{clean_topic}' - Stage: '{round_title}'.
Context from study notes/book:
\"\"\"{passage_ctx[:1000] if passage_ctx else clean_topic}\"\"\"

Rules:
- Adapt questions strictly to the subject of '{clean_topic}'.
- Every question must test a specific conceptual definition, mechanism, or scenario from the context above.
- Do NOT mention software or coding unless '{clean_topic}' is explicitly about programming.
- Do NOT generate questions about study habits, memorization strategies, or meta-learning tips.
- Output strictly valid JSON with this format:
[
  {{
    "question": "Clear, specific question about {clean_topic}",
    "options": ["Option A", "Option B", "Option C", "Option D"],
    "correct_index": 0,
    "explanation": "Clear explanation grounded in {clean_topic}."
  }}
]
Do not include markdown codeblocks or extra text. Only the JSON array."""

    res = ollama_generate(prompt, task="questions", model_override="phi3:latest", num_predict=450)
    try:
        clean = re.sub(r'```json\s*', '', res)
        clean = re.sub(r'```\s*', '', clean).strip()
        data = json.loads(clean)
        if isinstance(data, list) and len(data) > 0:
            return data[:3]
    except Exception as e:
        print(f"[DRILLS GEN NOTE]: {e}")

    # Grounded fallback drills (NO generic meta-study tips)
    p_len = len(passage_ctx)
    d1 = _generate_grounded_drill(clean_topic, round_title, passage_ctx[:max(1, p_len // 3)], 1)
    d2 = _generate_grounded_drill(clean_topic, round_title, passage_ctx[max(1, p_len // 3): max(1, 2 * p_len // 3)], 2)
    d3 = _generate_grounded_drill(clean_topic, round_title, passage_ctx[max(1, 2 * p_len // 3):], 3)
    return [d1, d2, d3]


def ask_study_doubt(topic: str, question: str, round_notes: str = "", doc_name: str = None, student_id: int = 1) -> dict:
    """Answers a student's doubt about a study session, grounded in session notes and document context."""
    clean_topic = clean_topic_title(topic)
    ctx = round_notes[:1500] if round_notes else ""
    if not ctx and doc_name:
        text, _ = retrieve_chunks_with_sources(question, doc_filter=doc_name, top_k=2)
        ctx = text[:1500]
    
    prompt = f"""You are an elite AI Study Coach & Subject Matter Expert.
A student studying '{clean_topic}' has a doubt or question:
Student Question: "{question}"

Study Context:
{ctx or 'No specific notes provided; use authoritative subject knowledge.'}

Provide a clear, pedagogical, intuitive explanation that directly resolves their doubt.
Structure:
1. **Core Intuition / Direct Answer**: A concise, clear explanation.
2. ️ **Mechanism / Step-by-Step Breakdown**: How it works practically or conceptually.
3. **Takeaway / Example**: A concrete example or memorable rule of thumb.
Adapt tone to the topic's domain. Keep it under 250 words."""

    answer = ollama_generate(prompt, task="qa", model_override="phi3:latest", num_predict=350)
    if not answer or len(answer.strip()) < 20:
        answer = f"In **{clean_topic}**, {question.strip().rstrip('?')} can be understood by examining the underlying principle. When applying this concept, always start from the baseline definitions and trace how inputs transform into outputs step-by-step."
    
    return {
        "success": True,
        "topic": clean_topic,
        "question": question,
        "explanation_markdown": answer
    }


def generate_more_checkpoints(topic: str, round_title: str, student_id: int = 1) -> list:
    """Generates 2 additional actionable learning checkpoints for the round."""
    prompt = f"""Generate 2 concise, actionable learning checkpoints (tasks) for a student studying '{topic}' ({round_title}).
Output strictly valid JSON array of strings:
["Actionable task 1", "Actionable task 2"]"""
    res = ollama_generate(prompt, task="qa", model_override="phi3:latest", num_predict=200)
    try:
        clean = re.sub(r'```json\s*', '', res)
        clean = re.sub(r'```\s*', '', clean).strip()
        tasks = json.loads(clean)
        if isinstance(tasks, list) and len(tasks) > 0:
            return [{"task": str(t), "done": False} for t in tasks[:2]]
    except Exception as e:
        print(f"[CHECKPOINTS GEN NOTE]: {e}")

    return [
        {"task": f"Trace an end-to-end example illustrating {round_title} in {topic}", "done": False},
        {"task": f"Formulate and explain one edge-case scenario for {topic}", "done": False}
    ]


def generate_deeper_notes(topic: str, round_title: str, student_id: int = 1, session_id: int = None, doc_name: str = None) -> str:
    """Generates an in-depth expansion tailored to the topic's domain (English, Sciences, Humanities, Business, or Tech)."""
    clean_topic = clean_topic_title(topic)
    
    passage_ctx = ""
    if session_id:
        cur_file = os.path.join(CURRICULUM_DIR, f"curriculum_{session_id}.json")
        if os.path.exists(cur_file):
            try:
                with open(cur_file, "r", encoding="utf-8") as f:
                    cdata = json.load(f)
                doc_name = doc_name or cdata.get("doc_name")
                for r in cdata.get("rounds", []):
                    if round_title.lower() in r.get("title", "").lower():
                        passage_ctx = r.get("study_content_markdown", "")
                        break
            except Exception:
                pass

    if not passage_ctx and doc_name:
        text, _ = retrieve_chunks_with_sources(round_title, doc_filter=doc_name, top_k=3)
        passage_ctx = text[:1500]

    ctx_prompt = f"\nStudy Context / Excerpt:\n\"\"\"{passage_ctx[:1200]}\"\"\"\n" if passage_ctx else ""

    prompt = f"""You are an expert professor and master educator teaching '{clean_topic}'.
Write a comprehensive, in-depth lesson expansion for the study stage: '{round_title}'.
{ctx_prompt}
CRITICAL INSTRUCTIONS:
- Adapt your explanation strictly to the domain and subject matter of '{clean_topic}' (e.g. English literature/grammar, science, history, business, mathematics, or technology).
- Do NOT assume computer science, software engineering, or write programming code UNLESS '{clean_topic}' is explicitly about coding or software development!
- Use clear, professional, engaging academic prose with rich examples and practical applications.

Include:
1. Deep-Dive Concepts & Real-World Application / Case Example
2. Common Misconceptions & Frequent Mistakes to Avoid
3. Key Takeaway & Golden Rule for Lifelong Retention

Format with clean Markdown (use ## and ### headings, bullet points, and bold terms). Do NOT print raw isolated # characters."""
    res = ollama_generate(prompt, task="qa", model_override="phi3:latest", num_predict=600)
    if res and len(res.strip()) > 100:
        return res.strip()

    return f"""###  In-Depth Deep Dive: {round_title}

#### Applied Principles & Meaning in Context
True mastery of **{topic}** requires connecting foundational definitions to real-world contexts, practical applications, and analytical thinking.

#### Common Misconceptions & Pitfalls to Avoid
- **Superficial Memorization**: Memorizing terms or rules without understanding their contextual meaning or practical usage.
- **Overlooking Nuances & Exceptions**: Assuming one rigid rule applies universally without examining edge cases or boundary conditions.

#### Golden Rule for Retention
> Always test your understanding by explaining core concepts in your own words with concrete examples before moving to advanced material."""


def replan_single_round(topic: str, round_number: int, student_id: int = 1) -> dict:
    """Re-synthesizes a fresh round with new notes, checkpoints, and drills."""
    drills = generate_more_drills(topic, f"Stage {round_number}", student_id)
    checkpoints = generate_more_checkpoints(topic, f"Stage {round_number}", student_id)
    notes = generate_deeper_notes(topic, f"Stage {round_number}", student_id)

    titles = [
        "Foundation & Core Intuition",
        "Mechanism & Applied Logic",
        "Active Recall & Problem Solving",
        "Mastery Verification Exam"
    ]
    title = titles[round_number - 1] if 1 <= round_number <= 4 else f"Stage {round_number} Mastery"
    mode = "Tutor" if round_number <= 2 else "Tester"

    return {
        "round_number": round_number,
        "title": title,
        "mode": mode,
        "suggested_duration_mins": 25,
        "objective": f"Master the core operational principles and applied techniques of {topic}.",
        "study_content_markdown": notes,
        "active_checkpoints": checkpoints,
        "practice_drills": drills
    }


