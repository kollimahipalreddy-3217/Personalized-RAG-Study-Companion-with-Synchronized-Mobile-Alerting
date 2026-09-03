# ============================================================
#  pdf_indexer.py — Document Extraction & Dense Vector Ingestion Engine
#  Personalized RAG Study Companion with Synchronized Mobile Alerting
#  Application Interface: StudyEdge AI
# ============================================================

import re
import os
import threading

_INDEXING_STATUS = {}   # in memory progress tracker: {doc_name: "indexing"|"ready"|"error"}
_STATUS_LOCK = threading.Lock()


# ─────────────────────────────────────────────────────
#  Passage quality scorer
# ─────────────────────────────────────────────────────

def _score_passage(text: str, is_technical: bool) -> float:
    """
    Computes a 0.0-1.0 quality score for a passage.
    Higher = more substantive, concept-rich, complete sentences.
    """
    score = 0.0
    if not text or len(text) < 150:
        return 0.0

    # 1. Length score (0-0.30): reward passages up to ~1800 chars
    length_score = min(len(text) / 1800.0, 1.0) * 0.30
    score += length_score

    # 2. Technical concept density (0-0.35)
    tech_patterns = [
        r'\b(?:torch|nn|numpy|np|pandas|pd|sklearn|transformers)\b',
        r'\b(?:tensor|embedding|attention|transformer|softmax|layer|weight|gradient|loss)\b',
        r'\b(?:training|inference|forward|backward|optimizer|learning rate|batch|epoch)\b',
        r'\b(?:tokeniz|vocabulary|encoding|decoding|masking|head|ffn|mlp|gpt|bert|llm)\b',
        r'\b(?:self\.\w+|nn\.\w+|torch\.\w+)\b',
        r'def\s+\w+\(|class\s+\w+[\(:]',
        r'\b(?:matrix|vector|dimension|shape|sequence|context window|parameter)\b',
        r'\b(?:pretraining|fine.tuning|lora|peft|rlhf|instruction|alignment)\b',
    ]
    hits = 0
    for pat in tech_patterns:
        matches = re.findall(pat, text, re.IGNORECASE)
        hits += len(matches)
    concept_density = min(hits / 12.0, 1.0) * 0.35
    score += concept_density

    # 3. Sentence completeness (0-0.20): rewards prose over bullet fragments
    sentences = re.findall(r'[A-Z][^.!?]{20,}[.!?]', text)
    completeness = min(len(sentences) / 6.0, 1.0) * 0.20
    score += completeness

    # 4. Code presence bonus (0-0.10)
    code_lines = re.findall(r'(?:def |class |import |from |return |for |if |while |    [\w])', text)
    code_bonus = min(len(code_lines) / 5.0, 1.0) * 0.10
    score += code_bonus

    # 5. Boilerplate penalty
    junk_hits = len(re.findall(
        r'(?:downloaded from|all rights reserved|isbn\s*[\d\-]+|page\s+\d+|'
        r'copyright\s*©?|exercise\s+\d+|listing\s+\d+\.\d+|figure\s+\d+\.\d+)',
        text, re.IGNORECASE
    ))
    score -= min(junk_hits * 0.05, 0.20)

    # 6. Non technical chapters get a hard cap
    if not is_technical:
        score = min(score, 0.30)

    return max(0.0, min(score, 1.0))


def _count_concepts(text: str) -> int:
    """Counts distinct technical concepts in a passage."""
    patterns = [
        r'\b(?:torch|nn|numpy|sklearn|transformers)\b',
        r'\b(?:tensor|embedding|attention|softmax|gradient|loss|weight)\b',
        r'\b(?:training|inference|forward|backward|optimizer)\b',
        r'\b(?:tokeniz|vocabulary|encoding|decoding|masking|gpt|bert|llm)\b',
        r'\b(?:pretraining|fine.tuning|lora|peft|rlhf|instruction|alignment)\b',
        r'\b(?:matrix|vector|sequence|context.window|parameter)\b',
    ]
    found = set()
    for pat in patterns:
        for m in re.findall(pat, text, re.IGNORECASE):
            found.add(m.lower())
    return len(found)


# ─────────────────────────────────────────────────────
#  Main indexing function
# ─────────────────────────────────────────────────────

def index_pdf_to_db(pdf_path: str, doc_name: str, force: bool = False) -> int:
    """
    Pre-indexes ALL pages of a PDF into the database.
    - Extracts every substantive passage from all core technical chapters
    - Scores each passage for quality/richness
    - Stores chapters + passages in MySQL
    - Runs fully in-process (caller should invoke in a background thread)
    Returns the number of passages indexed.
    """
    with _STATUS_LOCK:
        if _INDEXING_STATUS.get(doc_name) == "indexing" and not force:
            print("[INDEXER] Already indexing '{}', skipping duplicate call.".format(doc_name))
            return 0
        _INDEXING_STATUS[doc_name] = "indexing"

    try:
        import fitz  # PyMuPDF
        import db
        from mcq_test import (
            get_document_chapters,
            is_technical_chapter,
            clean_passage_for_prompt,
        )

        print("[INDEXER] Starting full pre-index of '{}' ({})".format(doc_name, pdf_path))

        if not os.path.exists(pdf_path):
            print("[INDEXER] ERROR: File not found: {}".format(pdf_path))
            with _STATUS_LOCK:
                _INDEXING_STATUS[doc_name] = "error"
            return 0

        # Step 1: Extract all chapters
        chapters = get_document_chapters(pdf_path)
        if not chapters:
            print("[INDEXER] No chapters found in '{}'".format(doc_name))
            with _STATUS_LOCK:
                _INDEXING_STATUS[doc_name] = "error"
            return 0

        # Save chapters to DB
        db.save_document_chapters(doc_name, chapters)
        print("[INDEXER] Saved {} chapters for '{}'".format(len(chapters), doc_name))

        # Step 2: Open PDF and scan ALL pages in ALL chapters
        doc_fitz = fitz.open(pdf_path)
        total_pages_in_pdf = len(doc_fitz)

        passages_to_save = []

        for chap in chapters:
            is_tech = is_technical_chapter(chap.get("title", ""))
            p_start = max(1, chap["page_start"])
            p_end   = min(total_pages_in_pdf, chap["page_end"])

            for page_idx in range(p_start - 1, p_end):
                raw_text = doc_fitz[page_idx].get_text()
                clean_text = clean_passage_for_prompt(raw_text)

                # Skip blank/very short pages
                if len(clean_text.strip()) < 120:
                    continue

                quality = _score_passage(clean_text, is_tech)
                concepts = _count_concepts(clean_text)

                passages_to_save.append({
                    "chapter_id":    chap["id"],
                    "chapter_title": chap["title"],
                    "page_num":      page_idx + 1,
                    "text_content":  clean_text[:2000],
                    "quality_score": quality,
                    "concept_count": concepts,
                    "is_technical":  is_tech,
                })

        doc_fitz.close()

        # Step 3: Bulk save all passages to DB
        count = db.save_document_passages(doc_name, passages_to_save)

        with _STATUS_LOCK:
            _INDEXING_STATUS[doc_name] = "ready"

        print("[INDEXER] Done: {} passages indexed for '{}' (across {} chapters, {} pages)".format(
            count, doc_name, len(chapters), total_pages_in_pdf))
        return count

    except Exception as e:
        print("[INDEXER] ERROR indexing '{}': {}".format(doc_name, e))
        import traceback
        traceback.print_exc()
        with _STATUS_LOCK:
            _INDEXING_STATUS[doc_name] = "error"
        return 0


def get_in_memory_status(doc_name: str) -> str:
    """Returns current in memory indexing status: 'indexing', 'ready', 'error', or 'unknown'."""
    with _STATUS_LOCK:
        return _INDEXING_STATUS.get(doc_name, "unknown")


def index_pdf_background(pdf_path: str, doc_name: str):
    """Starts PDF indexing in a daemon background thread. Returns immediately."""
    t = threading.Thread(
        target=index_pdf_to_db,
        args=(pdf_path, doc_name),
        daemon=True
    )
    t.start()
    print("[INDEXER] Background indexing started for '{}'".format(doc_name))


def ensure_indexed(pdf_path: str, doc_name: str) -> bool:
    """
    Checks if a document is already indexed in the DB.
    If not, starts background indexing.
    Returns True if already indexed, False if indexing just started.
    """
    import db
    status = db.get_indexing_status(doc_name)
    if status["passages_indexed"] > 0:
        return True
    # Not indexed — kick off background indexing
    index_pdf_background(pdf_path, doc_name)
    return False
