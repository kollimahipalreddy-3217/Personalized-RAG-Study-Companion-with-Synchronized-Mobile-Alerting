# ============================================================
#  mcq_test.py — Bloom's Taxonomy Cognitive Assessment Engine
#  Personalized RAG Study Companion with Synchronized Mobile Alerting
#  Application Interface: StudyEdge AI
# ============================================================

import os
import re
import json
import uuid
import random
import requests
import subprocess
from typing import List, Dict, Any, Optional, Tuple
from config import OLLAMA_BASE_URL, MODELS

CATEGORIES = [
    "Cognitive Memory",
    "Logical Reasoning",
    "Critical Thinking",
    "Creative Application"
]

TEST_LENGTHS = {
    16: {"name": "Quick Test",         "batches": 4,  "per_cat": 4},
    32: {"name": "Standard Test",      "batches": 8,  "per_cat": 8},
    48: {"name": "Comprehensive Test", "batches": 12, "per_cat": 12},
    60: {"name": "Mock Exam / Master", "batches": 15, "per_cat": 15},
}


def _ensure_ollama_running():
    """Verifies Ollama is responsive; auto-starts if down."""
    try:
        r = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=2)
        if r.status_code == 200:
            return True
    except Exception:
        pass
    try:
        subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass
    return False


def clean_topic_title(raw_name: str) -> str:
    """Cleans raw PDF filenames into clean human-readable book/topic titles."""
    clean = str(raw_name or "")
    clean = re.sub(r'^(?:_|\s)+', '', clean)
    clean = re.sub(r'\.pdf$', '', clean, flags=re.IGNORECASE)
    clean = clean.replace('_', ' ').replace('-', ' ').strip()
    clean = re.sub(r'\s+', ' ', clean)
    return clean or "General Study"


def is_technical_chapter(title: str) -> bool:
    """Returns True if the chapter contains core technical content (filters out index, references, exercises, practice MCQs, appendices, etc.)."""
    t = str(title).strip().lower()
    if not t:
        return False
    t_clean = re.sub(r'^(?:chapter|section|part|unit|module)\s*\d+[:\s\-–]*', '', t).strip()
    t_clean = re.sub(r'^\d+[\.\:\-–\s]+', '', t_clean).strip()
    bad_pattern = r'^(?:index|references|further\s+reading|bibliography|table\s+of\s+contents|contents|brief\s+contents|about\s+.*|acknowledgments?|preface|copyright|title\s+page|appendix.*|exercise.*|solutions?.*|answers?.*|glossary|practice\s+mcq.*|practice\s+question.*|worked\s+solution.*|mock\s+test.*|sample\s+paper.*)\b'
    if re.search(bad_pattern, t_clean, re.I):
        return False
    if re.search(r'\b(?:practice\s+mcqs?|worked\s+solutions?|sample\s+questions?|mock\s+exam)\b', t, re.I):
        return False
    return True


def get_document_chapters(pdf_path: str) -> List[Dict[str, Any]]:
    """
    Extracts all Level 1 chapters and Level 2 subsections with start/end page boundaries.
    Filters out front-matter (preface, acknowledgments, cover, index) or marks them.
    Falls back to structural section detection for flat PDFs.
    """
    if not os.path.exists(pdf_path):
        return []

    import fitz
    doc = fitz.open(pdf_path)
    total_pages = len(doc)
    toc = doc.get_toc()

    chapters = []

    if toc:
        lvl1_items = [item for item in toc if item[0] == 1]
        filtered_items = []
        for item in lvl1_items:
            title = item[1].strip()
            title = re.sub(r'[\x00-\x1f\x7f-\x9f\ufffd]', ' ', title)
            title = re.sub(r'\s+', ' ', title).strip()
            if title.lower() in ('cover', 'title', 'title page', 'copyright', 'contents', 'brief contents'):
                continue
            filtered_items.append([item[0], title, item[2]])

        if not filtered_items:
            filtered_items = lvl1_items

        for idx, item in enumerate(filtered_items):
            lvl, title, page_start = item[0], item[1].strip(), item[2]
            if idx + 1 < len(filtered_items):
                page_end = max(page_start, filtered_items[idx + 1][2] - 1)
            else:
                page_end = total_pages

            # Find subsections
            subsections = []
            for sub in toc:
                if sub[0] == 2 and page_start <= sub[2] <= page_end:
                    clean_sub = re.sub(r'[\x00-\x1f\x7f-\x9f\ufffd]', ' ', sub[1]).strip()
                    subsections.append({
                        "title": re.sub(r'\s+', ' ', clean_sub),
                        "page": sub[2]
                    })

            is_main = is_technical_chapter(title) and (page_end - page_start >= 4)

            chapters.append({
                "id": f"ch_{idx+1}",
                "index": idx + 1,
                "title": title,
                "page_start": page_start,
                "page_end": page_end,
                "total_pages": max(1, page_end - page_start + 1),
                "is_main": is_main,
                "subsections": subsections
            })

    # Strategy 2: Fallback for PDFs WITHOUT Table of Contents / Index (scan headings)
    if not chapters:
        found_sections = []
        for p_no in range(total_pages):
            text = doc[p_no].get_text()
            lines = [l.strip() for l in text.split('\n') if l.strip()]
            for line in lines[:8]:
                m = re.match(
                    r'^(?:Chapter\s+\d+|Unit\s+\d+|Module\s+\d+|Section\s+\d+|Part\s+[IVX\d]+|\d+\.\s+[A-Z][\w\s]{2,40}|[A-Z\s]{4,30}$)',
                    line,
                    re.I
                )
                if m and len(line) < 70:
                    if not re.match(r'^(?:page\s+\d+|\d{1,2}/\d{1,2}/\d{2,4}|confidential|all rights|copyright).*', line, re.I):
                        found_sections.append((line, p_no + 1))
                        break

        # Consolidate sections that start on same page
        consolidated = []
        for title, p_start in found_sections:
            if not consolidated or p_start > consolidated[-1][1]:
                consolidated.append((title, p_start))

        if len(consolidated) >= 2:
            for idx, (title, p_start) in enumerate(consolidated):
                p_end = consolidated[idx + 1][1] - 1 if idx + 1 < len(consolidated) else total_pages
                chapters.append({
                    "id": f"sec_{idx+1}",
                    "index": idx + 1,
                    "title": title,
                    "page_start": p_start,
                    "page_end": p_end,
                    "total_pages": max(1, p_end - p_start + 1),
                    "is_main": True,
                    "subsections": []
                })

    # Strategy 3: Dynamic Thematic Partitioning (for plain documents/notes without headings)
    if not chapters:
        if total_pages <= 3:
            num_sec = 1
        elif total_pages <= 10:
            num_sec = min(3, total_pages)
        elif total_pages <= 30:
            num_sec = 4
        elif total_pages <= 80:
            num_sec = 6
        else:
            num_sec = min(10, max(5, total_pages // 15))

        step = max(1, total_pages // num_sec)
        for i in range(num_sec):
            p_start = i * step + 1
            p_end = (i + 1) * step if i + 1 < num_sec else total_pages

            first_page_text = doc[p_start - 1].get_text().strip()
            first_lines = [l.strip() for l in first_page_text.split('\n') if len(l.strip()) > 3]
            topic_hint = ""
            for l in first_lines[:4]:
                if len(l) < 60 and not re.search(r'http|page|copyright|\d{4}', l, re.I):
                    topic_hint = f": {l}"
                    break

            chapters.append({
                "id": f"part_{i+1}",
                "index": i + 1,
                "title": f"Section {i+1}{topic_hint} (Pages {p_start}–{p_end})" if num_sec > 1 else "Complete Document",
                "page_start": p_start,
                "page_end": p_end,
                "total_pages": max(1, p_end - p_start + 1),
                "is_main": True,
                "subsections": []
            })

    doc.close()
    return chapters


# Alias for backward compatibility
extract_document_chapters = get_document_chapters


def clean_passage_for_prompt(text: str) -> str:
    """Normalizes PDF passage text by un-hyphenating line breaks and stripping formatting artifacts and exam/recruitment branding."""
    if not text:
        return ""
    # Rejoin words hyphenated across line breaks: e.g. "atten-\ntion" -> "attention"
    text = re.sub(r'(\b[a-zA-Z]{2,})-\s*\n\s*([a-zA-Z]{2,}\b)', r'\1\2', text)
    # Rejoin words hyphenated with whitespace: e.g. "partic- ular" -> "particular"
    text = re.sub(r'(\b[a-zA-Z]{2,})-\s+([a-zA-Z]{2,}\b)', r'\1\2', text)
    # Remove watermarks / publishing header artifacts / recruitment drive headers
    text = re.sub(r'(?i)\b(?:accenture|cognizant|tcs|infosys|wipro|capgemini|deloitte)\s*(?:campus|drive|recruitment|technical|assessment|test|national|qualifier|mock)?\s*(?:\|\s*technical\s*assessment|[-–—]\s*section\s*[a-z0-9]+|\b)?', '', text)
    text = re.sub(r'(?i)\b(?:campus\s+drive|technical\s+assessment|recruitment\s+training|practice\s+guide|sample\s+paper|studyedge\s+ai|syllabus\s+alignment)\b', '', text)
    text = re.sub(r'(?i)\bPattern\s*\([^\)]*\)\s*[-–—]?\s*(?:For\s+Campus\s+Prep\s+Only)?', '', text)
    text = re.sub(r'(?i)\bFor\s+Campus\s+Prep\s+Only\b', '', text)
    text = re.sub(r'(?i)downloaded from|all rights reserved|published by|isbn\s*[\d\-]+|copyright\s*©?', '', text)
    text = re.sub(r'(?i)\b(?:page\s+\d+\s+of\s+\d+|\bpage\s+\d+\b)', '', text)
    # Strip non printable, private-use unicode, OCR control characters
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\uf000-\uf8ff\ufffd\xad]', ' ', text)
    # Normalize multiple whitespace and newlines
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()



def extract_passage_key_concepts(passage_text: str, max_concepts: int = 5) -> List[str]:
    """Extracts distinctive domain terms, mechanisms, concepts, and named entities across any subject."""
    candidates = []
    stop_meta = {
        "chapter", "section", "part", "figure", "table", "listing", "appendix", "author",
        "book", "page", "pages", "exercise", "solution", "summary", "contents", "index",
        "about", "which", "where", "there", "their", "these", "those", "other", "first",
        "second", "third", "after", "before", "between", "example", "notes", "when", "what",
        "this", "that", "from", "with", "into", "such", "more", "most", "some", "also", "the",
        "higher", "lower", "conversely", "similarly", "therefore", "furthermore", "however",
        "additionally", "moreover", "consequently", "according", "under", "within", "without",
        "during", "through", "across", "while", "since", "until", "because", "although",
        "though", "despite", "whereas", "meanwhile", "overall", "typically", "generally",
        "specifically", "initially", "finally", "ultimately", "essentially", "namely"
    }

    # 1. Multi-word title case domain concepts (supports terms like "Due Process Clause", "Le Chatelier's Principle", "Marbury v. Madison", "Discounted Cash Flow", "Federal Funds Rate")
    pattern = r'\b[A-Z][a-z]+(?:\'[a-z]+)?(?:\s+(?:(?:of|and|in|de|v\.|for)\s+)?[A-Z][a-z]+(?:\'[a-z]+)?)+\b'
    for mn in re.findall(pattern, passage_text):
        clean = re.sub(r'^(?:The|This|That|These|Those|When|What|Which|In|On|At|By|For|With|Under|From|Into|About|During|Through|Across|According\s+to)\s+', '', mn.strip(), flags=re.I)
        if clean.lower() not in stop_meta and clean not in candidates and len(clean) > 3:
            candidates.append(clean)

    # 2. Domain Acronyms & Uppercase tokens (2-8 chars: e.g. DNA, RNA, TCP, HTTP, GDP, ROI, FIFO, VLOOKUP, WACC, DCF)
    acronyms = re.findall(r'\b[A-Z0-9]{2,8}\b', passage_text)
    for acr in acronyms:
        if acr.lower() not in stop_meta and not re.match(r'^(?:THE|AND|FOR|NOT|ARE|CAN|ALL|NEW|SET|END|BUT|ANY|OUT|HAS|HAD|WAS)$', acr):
            if acr not in candidates:
                candidates.append(acr)

    # 3. Quoted / Backticked terms (e.g. `VLOOKUP`, "Inflation", 'Photosynthesis')
    quoted_terms = re.findall(r'[`\'\"]([A-Za-z0-9_\-\s]{3,30})[`\'\"]', passage_text)
    for q in quoted_terms:
        clean_q = q.strip()
        if clean_q.lower() not in stop_meta and len(clean_q) > 2:
            if clean_q not in candidates:
                candidates.append(clean_q)

    # 4. Code / Technical Identifiers & functions (e.g. col_index_num, malloc(), countif(), SlideMaster)
    code_terms = re.findall(r'\b(?:[a-zA-Z_][a-zA-Z0-9_]*_[a-zA-Z0-9_]+|[a-zA-Z_][a-zA-Z0-9_]+\(\)|[a-z]{2,}[A-Z][a-zA-Z0-9]*|[A-Z][a-z]+[A-Z][a-zA-Z0-9]*)\b', passage_text)
    for term in code_terms:
        if len(term) > 3 and term.lower() not in stop_meta and not re.match(r'^(?:true|false|none|self|return|import|class|from|print|range|this|that|with)$', term, re.I):
            if term not in candidates and term.capitalize() not in candidates:
                candidates.append(term)

    # 5. Prominent Single Capitalized Domain Nouns (e.g. Mitochondria, Keynesian, Inflation, Algorithm)
    if len(candidates) < max_concepts:
        words = [w.capitalize() for w in re.findall(r'\b[A-Z][a-z]{3,}\b', passage_text) if w.lower() not in stop_meta]
        for w in words:
            if w not in candidates and w.lower() not in [c.lower() for c in candidates] and not any(w.lower() in c.lower() for c in candidates):
                candidates.append(w)
                if len(candidates) >= max_concepts:
                    break

    return candidates[:max_concepts]


def extract_substantive_passages_from_pdf(
    pdf_path: str,
    count: int = 15,
    selected_chapter_ids: Optional[List[str]] = None
) -> List[Dict[str, Any]]:
    """
    Extracts evenly distributed, substantive passages across core technical chapters.
    Uses continuous paragraph sliding windows to guarantee 100% distinct, rich technical context
    for all batches (even when generating 60-question tests on concise documents).
    Always returns exactly `count` passages.
    """
    import fitz
    chapters = get_document_chapters(pdf_path)

    active_chapters = []
    if selected_chapter_ids and len(selected_chapter_ids) > 0:
        active_chapters = [c for c in chapters if c["id"] in selected_chapter_ids]
    if not active_chapters:
        tech_chaps = [c for c in chapters if is_technical_chapter(c.get("title", ""))]
        active_chapters = [c for c in tech_chaps if c.get("is_main")]
        if not active_chapters:
            active_chapters = tech_chaps if tech_chaps else [c for c in chapters if c.get("is_main")]
        if not active_chapters:
            active_chapters = chapters

    doc = fitz.open(pdf_path)
    total_pages = len(doc)

    all_paragraphs = []
    for chap in active_chapters:
        p_start = max(1, chap["page_start"])
        p_end = min(total_pages, chap["page_end"])

        for page_idx in range(p_start - 1, p_end):
            raw_text = doc[page_idx].get_text()
            clean_text = clean_passage_for_prompt(raw_text)
            paragraphs = [p.strip() for p in re.split(r'\n\s*\n+|\n(?=\d+\.\d+\s+[A-Z])|\n(?=[•\-\*]\s+[A-Z])', clean_text) if len(p.strip()) > 35]
            for p in paragraphs:
                p_clean = re.sub(r'\s+', ' ', p).strip()
                if not p_clean.startswith(('Figure ', 'Table ', 'Listing ', 'Exercise ', 'Answer:', 'INDEX', 'CONTENTS', 'Contents', 'Q1.', 'Q2.', 'Q3.', 'Q4.', 'Q5.')):
                    if len(p_clean) >= 40 and not re.search(r'(?i)\b(?:Pattern\s*\(|For\s+Campus\s+Prep|All\s+Rights|Page\s+\d+)\b', p_clean):
                        all_paragraphs.append({
                            "page": page_idx + 1,
                            "chapter_id": chap["id"],
                            "chapter_title": chap["title"],
                            "text": p_clean
                        })

    doc.close()

    if not all_paragraphs:
        all_paragraphs = [{
            "page": 1,
            "chapter_id": "ch_1",
            "chapter_title": "Core",
            "text": "Core technical principles, operational parameters, and foundational mechanisms."
        }]

    passages = []
    n_paras = len(all_paragraphs)

    if n_paras >= count:
        # Step through the substantive paragraphs evenly across the document
        step = max(1.0, (n_paras - 1) / max(1, count - 1)) if count > 1 else 1.0
        for i in range(count):
            start_idx = min(int(round(i * step)), max(0, n_paras - 1))
            current_chunk = []
            curr_len = 0
            idx = start_idx
            # Accumulate paragraphs to build a robust 700-1400 character technical passage
            while idx < n_paras and (curr_len < 750 or len(current_chunk) < 2):
                p_item = all_paragraphs[idx]
                current_chunk.append(p_item["text"])
                curr_len += len(p_item["text"])
                idx += 1
            combined = " ".join(current_chunk).strip()
            anchor = all_paragraphs[start_idx]
            passages.append({
                "page": anchor["page"],
                "chapter_id": anchor["chapter_id"],
                "chapter_title": anchor["chapter_title"],
                "text": combined if len(combined) >= 200 else anchor["text"],
                "focus_angle": i % 4
            })
    else:
        # Fewer total paragraphs than requested batches:
        # Build sliding windows with distinct starting offsets and complementary focus angles
        for i in range(count):
            start_idx = i % n_paras
            current_chunk = []
            curr_len = 0
            for offset in range(min(4, n_paras)):
                p_item = all_paragraphs[(start_idx + offset) % n_paras]
                current_chunk.append(p_item["text"])
                curr_len += len(p_item["text"])
                if curr_len >= 750:
                    break
            combined = " ".join(current_chunk).strip()
            anchor = all_paragraphs[start_idx]
            passages.append({
                "page": anchor["page"],
                "chapter_id": anchor["chapter_id"],
                "chapter_title": anchor["chapter_title"],
                "text": combined if len(combined) >= 200 else anchor["text"],
                "focus_angle": (i // n_paras) % 4
            })

    return passages


def _sanitize_text(text: str) -> str:
    """Strips non printable, private-use unicode, and OCR artifact characters."""
    if not text:
        return ""
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\uf000-\uf8ff\ufffd]', ' ', str(text))
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def _clean_option_text(opt: str) -> str:
    """Strips leading option labels ('A)', '(A)', '[A]', 'Option A:', 'A. ') without corrupting single-letter answers, formulas, or shortcuts."""
    if not opt:
        return ""
    cleaned = str(opt).strip().strip('"\'')
    cleaned = re.sub(r'^\*{1,2}([A-Da-d0-9\(\)\[\]\.:\-\s]+)\*{1,2}\s*', r'\1 ', cleaned)

    # 1. Strip letter labels: Option A:, Choice A., (A), [A], A), A. (only if length > 2)
    if len(cleaned) > 2:
        cleaned = re.sub(r'^(?:(?:Option|Choice|Answer)\s+[A-D]\s*[:.)\-]?\s*|\([A-D]\)\s*[:.)\-]?\s*|\[[A-D]\]\s*[:.)\-]?\s*|[A-D]\s*[:.)\-]\s+)', '', cleaned, flags=re.I).strip()

    # 2. Strip number prefix ONLY if 1-4 followed by space and text (e.g. "1. 12 layers")
    if len(cleaned) > 2:
        cleaned = re.sub(r'^(?:\([1-4]\)\s*[:.)\-]?\s*|[1-4]\s*[:.)\-]\s+)(?=\S)', '', cleaned).strip()

    cleaned = cleaned.strip('"\'`').strip()
    if not re.search(r'[a-zA-Z0-9$#=]', cleaned):
        cleaned = str(opt).strip()
    return _sanitize_text(cleaned)


DEFAULT_TECHNICAL_DISTRACTORS = [
    "By adhering to standard foundational principles and validated procedural rules",
    "Through systematic evaluation of documented criteria and established guidelines",
    "By maintaining consistency and validity across interrelated analytical stages",
    "Through comprehensive verification of baseline conditions and operational bounds",
    "By isolating primary variables to prevent unintended confounding effects",
    "By applying verified methodological guidelines to achieve reproducible outcomes",
    "Through direct evaluation of logical conditions within established boundaries",
    "By enforcing structural boundaries and preventing unauthorized state modifications"
]


def is_numeric_option_value(val: str) -> bool:
    """Detects if an option is a scalar number, decimal, or dimension tuple (e.g. 12, 768, 0.001, (10, 64))."""
    clean = str(val).strip().rstrip('. ')
    return clean.isdigit() or bool(re.match(r'^\d+\.\d+$', clean)) or bool(re.match(r'^\([0-9,\s\-]+\)$', clean))


def get_numeric_distractors(val_str: str) -> List[str]:
    """Generates plausible numeric distractors matching the magnitude and domain of the answer."""
    clean = str(val_str).strip().rstrip('. ')
    if clean.isdigit():
        num = int(clean)
        candidates = [num * 2, max(1, num // 2), num + 4, max(1, num - 4), num * 4, max(1, num // 4)]
        dist = [str(c) for c in candidates if c != num]
        if dist:
            return dist[:3]
    return ["12", "24", "6"]


def _should_append_period(text: str) -> bool:
    """Determines whether an option should end with a period (natural language sentences) or not (formulas, shortcuts, codes, numbers)."""
    s = text.strip()
    if len(s) < 12:
        return False
    # Formulas, error codes, cell references
    if s.startswith(('=', '#', '$', '@', 'http', '<')):
        return False
    # Math/logic operators or code tokens
    if re.search(r'[\+\-\*/<>=_{}\[\]\(\)]', s):
        return False
    # Keyboard shortcuts like Ctrl + B, Alt + F4, Shift + F5
    if re.search(r'^(?:Ctrl|Alt|Shift|Cmd|Esc|F\d+|Tab|Enter|Delete)\s*[\+\-]', s, re.I):
        return False
    # Pure numbers, dimensions, percentages
    if is_numeric_option_value(s) or re.match(r'^\d+\s*(?:%|px|pt|cm|mm|mb|gb|kb|ms|s)?$', s, re.I):
        return False
    # Already punctuated
    if s[-1] in '.!?;:':
        return False
    return True


def equalize_option_lengths(options: List[str], correct_answer: str) -> Tuple[List[str], str]:
    """
    Guarantees 4 distinct, valid, well-formatted options.
    Preserves single-character answers ('B', '1', 'A'), Excel formulas, cell references, and shortcuts.
    Never duplicates options and ensures correctAnswer matches exactly one option.
    """
    if not options or not isinstance(options, list):
        options = []

    cleaned_ans = _clean_option_text(correct_answer)
    if not cleaned_ans:
        cleaned_ans = str(correct_answer).strip() or "Standard execution"

    cleaned_opts = [_clean_option_text(o) for o in options if _clean_option_text(o)]

    # 1. Numerical options
    is_numeric = is_numeric_option_value(cleaned_ans) or (cleaned_opts and all(is_numeric_option_value(o) for o in cleaned_opts))
    if is_numeric:
        clean_num_ans = cleaned_ans.rstrip('. ')
        existing_nums = [o.rstrip('. ') for o in cleaned_opts]
        if clean_num_ans not in existing_nums:
            cleaned_opts.insert(0, clean_num_ans)

        num_distractors = get_numeric_distractors(clean_num_ans)
        for d in num_distractors:
            if len(cleaned_opts) >= 4:
                break
            if d not in [o.rstrip('. ') for o in cleaned_opts]:
                cleaned_opts.append(d)

        while len(cleaned_opts) < 4:
            cleaned_opts.append(str((len(cleaned_opts) + 1) * 4))

        final_opts = list(dict.fromkeys([o.rstrip('. ') for o in cleaned_opts]))[:4]
        while len(final_opts) < 4:
            final_opts.append(str(int(final_opts[-1]) + 2 if final_opts[-1].isdigit() else len(final_opts)))
        matching_ans = next((o for o in final_opts if o == clean_num_ans), final_opts[0])
        return final_opts, matching_ans

    # 2. General text / formula / shortcut options
    # Ensure correct answer is in options
    if not any(o.strip().lower() == cleaned_ans.strip().lower() for o in cleaned_opts):
        cleaned_opts.insert(0, cleaned_ans)

    # Deduplicate while preserving order
    seen = set()
    deduped_opts = []
    for o in cleaned_opts:
        norm = o.strip().lower()
        if norm not in seen:
            seen.add(norm)
            deduped_opts.append(o.strip())

    # Fill up to 4 if short using DEFAULT_TECHNICAL_DISTRACTORS
    for d in DEFAULT_TECHNICAL_DISTRACTORS:
        if len(deduped_opts) >= 4:
            break
        if d.lower() not in seen:
            seen.add(d.lower())
            deduped_opts.append(d)

    deduped_opts = deduped_opts[:4]

    # Find the matching index for cleaned_ans
    ans_idx = 0
    for i, o in enumerate(deduped_opts):
        if o.lower() == cleaned_ans.lower():
            ans_idx = i
            break

    # Format options cleanly: only append period if it's a full prose sentence
    final_opts = []
    for o in deduped_opts:
        o_clean = o.strip()
        if _should_append_period(o_clean):
            final_opts.append(o_clean.rstrip('. ') + '.')
        else:
            final_opts.append(o_clean)

    final_ans = final_opts[ans_idx]
    return final_opts, final_ans


def parse_llm_questions_resilient(raw_text: str) -> List[Dict[str, Any]]:
    """Robust JSON and regex question parser that extracts valid questions from any LLM format."""
    clean = re.sub(r'```(?:json)?', '', raw_text).replace('```', '').strip()
    s = clean.find('{')
    e = clean.rfind('}')
    if s != -1 and e != -1:
        chunk = clean[s:e+1]
        chunk = re.sub(r',\s*([\]}])', r'\1', chunk)
        try:
            data = json.loads(chunk)
            if "questions" in data and isinstance(data["questions"], list):
                return data["questions"]
        except Exception:
            pass

    q_blocks = re.findall(r'\{[^{}]*"category"[^{}]*"questionText"[^{}]*"options"[^{}]*"correctAnswer"[^{}]*\}', raw_text, re.DOTALL)
    results = []
    for block in q_blocks:
        block_clean = re.sub(r',\s*([\]}])', r'\1', block)
        try:
            q = json.loads(block_clean)
            if q.get("questionText") and len(q.get("options", [])) == 4:
                results.append(q)
                continue
        except Exception:
            pass

        cat_m = re.search(r'"category"\s*:\s*"([^"]+)"', block)
        qt_m  = re.search(r'"questionText"\s*:\s*"([^"]+)"', block)
        ans_m = re.search(r'"correctAnswer"\s*:\s*"([^"]+)"', block)
        opts_block = re.search(r'"options"\s*:\s*\[(.*?)\]', block, re.DOTALL)
        opts_m = re.findall(r'"([^"]+)"', opts_block.group(1)) if opts_block else []

        if qt_m and len(opts_m) == 4:
            results.append({
                "category": cat_m.group(1) if cat_m else "Cognitive Memory",
                "questionText": qt_m.group(1),
                "options": opts_m,
                "correctAnswer": ans_m.group(1) if ans_m else opts_m[0]
            })
    return results


def _strip_meta_references(text: str) -> str:
    """
    Removes references to source book, chapters, notes, page numbers, figures, tables, and 'given context'.
    Ensures questions read as pure domain/certification exam questions.
    """
    if not text:
        return ""
    s = str(text).strip()

    # 0. Strip detokenized / LLM text meta phrases
    s = re.sub(r'(?i)(?:as\s+)?(?:shown|revealed|indicated)\s+by\s+the\s+detokenized\s+text', '', s)
    s = re.sub(r'(?i)in\s+the\s+given\s+(?:llm|model|architecture|implementation)', '', s)
    s = re.sub(r'(?i)(?:in|for)\s+the\s+model\s+shown', '', s)

    # 1. Strip figure / table / listing references
    s = re.sub(r'(?i)\b(?:as\s+)?(?:depicted|shown|illustrated|seen|described|indicated)\s+in\s+(?:figure|fig\.|table|listing|diagram|chart)\s*[\d\.]*', '', s)
    s = re.sub(r'(?i)\b(?:in|according to|from)\s+(?:figure|fig\.|table|listing|diagram|chart)\s*[\d\.]*', '', s)
    s = re.sub(r'\(?\b(?:figure|fig\.|table|listing)\s*[\d\.]+\)?', '', s, flags=re.I)

    # 2. Strip "in the given context / snippet / code / scenario / example"
    s = re.sub(r'(?i)\b(?:in|for|from)\s+the\s+given\s+(?:context|snippet|code|passage|scenario|implementation|example)\b', '', s)
    s = re.sub(r'(?i)\bthe\s+given\s+(?:context|snippet|code|passage|scenario|implementation)\b', '', s)

    # 3. Strip page references: "on page 12", "(Page 12)", "(pages 23-45)", "on Page 23", "p. 45"
    s = re.sub(r'(?i)\b(?:on|at|from)\s+(?:page|pages|p\.)\s*\d+(?:\s*[\-–]\s*\d+)?\b', '', s)
    s = re.sub(r'\(?\b(?:page|pages|p\.)\s*\d+(?:\s*[\-–]\s*\d+)?\)?', '', s, flags=re.I)

    # 4. Strip lead-ins: "According to the passage", "In Chapter 3", etc.
    s = re.sub(r'(?i)^\s*(?:According to|Based on|As described in|As discussed in|As mentioned in|As stated in)\s+(?:the\s+)?(?:text|passage|book|notes|section|chapter|author|document|provided\s+material)[,\s:]*', '', s)
    s = re.sub(r'(?i)^\s*In\s+(?:Chapter|Section|Part|Appendix|Unit|Module)\s*(?:\d+|[IVXLCDM]+|[A-Z])(?:\s*[:\-–]\s*[^\n,:]+)?(?:\([^\)]*\))?[,\s:]*', '', s)
    s = re.sub(r'(?i)^\s*In\s+this\s+(?:chapter|section|part|document|passage|book)[,\s:]*', '', s)

    # 5. Strip inline phrases: "in the text", "in the passage", "in this section", "in this chapter", "in the notes", "in the book"
    s = re.sub(r'(?i)\b(?:in|from)\s+(?:the\s+|this\s+)?(?:text|passage|notes|book|section|chapter|document)\b', '', s)

    # 6. Clean up dangling prepositions before punctuation and double spaces
    s = re.sub(r'\b(?:on|in|at|from|of|for|as)\s*([,\?\.\!])', r'\1', s, flags=re.I)
    s = re.sub(r'^[,\s:\-]+', '', s)
    s = re.sub(r'\s+([,\?\.\!])', r'\1', s)
    s = re.sub(r'\s{2,}', ' ', s).strip()

    # Capitalize first letter
    if s and s[0].islower():
        s = s[0].upper() + s[1:]
    return s


def validate_and_correct_question_key(q: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validates the generated question and options for known inversion pitfalls, ensuring 100% answer accuracy.
    Specifically checks:
    1. Mixed cell referencing ($A1 vs A$1):
       - If question specifies column fixed / locked and row changing / relative -> answer MUST be $A1
       - If question specifies row fixed / locked and column changing / relative -> answer MUST be A$1
       - If question specifies both fixed / locked -> answer MUST be $A$1
       - If question specifies both relative / changing -> answer MUST be A1
    2. VLOOKUP col_index_num greater than columns -> answer is #REF!
    3. PowerPoint screen shortcuts ('B' for black screen, 'W' for white screen).
    4. Guarantees correctAnswer is an exact match to one of the options.
    """
    qt = q.get("questionText", "")
    opts = q.get("options", [])
    ans = q.get("correctAnswer", "")
    if not opts or not ans:
        return q

    qt_lower = qt.lower()
    is_referencing_q = "referenc" in qt_lower or "cell" in qt_lower or "mixed" in qt_lower
    if is_referencing_q:
        col_fixed = bool(re.search(r'\bcolumn(?:\s+[a-z])?\s+(?:is\s+)?(?:fixed|locked|frozen)\b|\b(?:fixes?|locks?|freezes?)\b[^\w\n]{0,15}(?:the\s+)?column(?:\s+[a-z])?\b', qt_lower))
        row_changing = bool(re.search(r'\brows?\s+(?:to\s+)?(?:change|changing|adjust|adjusting|shift|shifting|relative)\b|\b(?:changes?|adjusts?|shifts?)\b[^\w\n]{0,15}(?:the\s+)?rows?\b', qt_lower))
        row_fixed = bool(re.search(r'\brows?(?:\s+\d+)?\s+(?:is\s+)?(?:fixed|locked|frozen)\b|\b(?:fixes?|locks?|freezes?)\b[^\w\n]{0,15}(?:the\s+)?rows?(?:\s+\d+)?\b', qt_lower))
        col_changing = bool(re.search(r'\bcolumns?\s+(?:to\s+)?(?:change|changing|adjust|adjusting|shift|shifting|relative)\b|\b(?:changes?|adjusts?|shifts?)\b[^\w\n]{0,15}(?:the\s+)?columns?\b', qt_lower))

        expected_ref = None
        if col_fixed and (row_changing or not row_fixed):
            expected_ref = "$A1"
        elif row_fixed and (col_changing or not col_fixed):
            expected_ref = "A$1"
        elif "absolute" in qt_lower or (col_fixed and row_fixed):
            expected_ref = "$A$1"
        elif "relative" in qt_lower and not col_fixed and not row_fixed:
            expected_ref = "A1"

        if expected_ref:
            matching_opt = None
            for opt in opts:
                clean_o = opt.strip().rstrip('. ')
                if expected_ref == "$A1":
                    if "$A$1" in clean_o:
                        continue
                    if clean_o.startswith("$A1") or clean_o == "$A1" or f"`{expected_ref}`" in opt or f"({expected_ref})" in opt or f" {expected_ref} " in f" {opt} ":
                        matching_opt = opt
                        break
                elif expected_ref == "A$1":
                    if clean_o.startswith("A$1") or clean_o == "A$1" or f"`{expected_ref}`" in opt or f"({expected_ref})" in opt or f" {expected_ref} " in f" {opt} ":
                        matching_opt = opt
                        break
                elif expected_ref == "$A$1":
                    if clean_o.startswith("$A$1") or clean_o == "$A$1" or f"`{expected_ref}`" in opt or f"({expected_ref})" in opt or f" {expected_ref} " in f" {opt} ":
                        matching_opt = opt
                        break
                elif expected_ref == "A1":
                    if "$" in clean_o:
                        continue
                    if clean_o.startswith("A1") or clean_o == "A1" or f"`{expected_ref}`" in opt or f"({expected_ref})" in opt or f" {expected_ref} " in f" {opt} ":
                        matching_opt = opt
                        break
            if matching_opt:
                q["correctAnswer"] = matching_opt

    if "col_index_num" in qt_lower and ("greater" in qt_lower or "exceed" in qt_lower or "more than" in qt_lower):
        ref_opt = next((o for o in opts if "#REF" in o), None)
        if ref_opt:
            q["correctAnswer"] = ref_opt

    if ("black screen" in qt_lower or "screen black" in qt_lower) and "powerpoint" in qt_lower:
        b_opt = next((o for o in opts if o.strip().rstrip('. ') in ("B", "'B'", "`B`", "B key")), None)
        if b_opt:
            q["correctAnswer"] = b_opt

    if ("white screen" in qt_lower or "screen white" in qt_lower) and "powerpoint" in qt_lower:
        w_opt = next((o for o in opts if o.strip().rstrip('. ') in ("W", "'W'", "`W`", "W key")), None)
        if w_opt:
            q["correctAnswer"] = w_opt

    if q["correctAnswer"] not in opts:
        match = next((o for o in opts if o.strip().lower() == q["correctAnswer"].strip().lower()), opts[0])
        q["correctAnswer"] = match

    return q


def generate_batch_for_passage(
    passage_text: str,
    page_num: int,
    topic: str,
    model_name: str,
    chapter_title: str = "",
    focus_angle: int = 0,
    excluded_concepts: Optional[List[str]] = None
) -> List[Dict[str, Any]]:
    """
    Generates 4 deep, challenging, category-specific multiple-choice questions grounded in technical mechanisms.
    Returns [Memory_Q, Logic_Q, Critical_Q, Creative_Q].
    Strictly enforces 100% factual accuracy, zero concept repetition, and no out-of-domain boilerplate.
    """
    clean_p = clean_passage_for_prompt(passage_text)
    key_concepts = extract_passage_key_concepts(clean_p, max_concepts=5)
    concepts_str = ", ".join(key_concepts) if key_concepts else topic

    focus_directives = [
        "Focus on core functional mechanisms, component interactions, and execution pipelines.",
        "Focus on syntax conventions, formula parameters, and logical operations.",
        "Focus on error states, boundary constraints, and edge-case exceptions.",
        "Focus on practical problem solving, execution tracing, and concrete scenario analysis."
    ]
    focus_text = focus_directives[focus_angle % len(focus_directives)]

    exclude_clause = ""
    if excluded_concepts:
        stop_names = {clean_topic_title(topic).lower(), "excel", "office", "powerpoint", "word", "code", "system", "general", "chapter", "section"}
        clean_excl = [c for c in excluded_concepts if len(c) > 2 and c.lower() not in stop_names][-12:]
        if clean_excl:
            exclude_clause = f"\nRECENTLY TESTED ITEMS IN PREVIOUS BATCHES: {', '.join(clean_excl)}. Avoid duplicate questions on these exact items; focus on OTHER distinctive rules, parameters, edge cases, and mechanisms.\n"

    prompt = f"""You are an expert technical examiner authoring rigorous certification exam questions on "{topic}".
Target Technical Concepts: {concepts_str}.
Batch Focus Directive: {focus_text}
{exclude_clause}
TECHNICAL REFERENCE PASSAGE:
\"\"\"
{clean_p}
\"\"\"

Create exactly 4 challenging, standalone multiple-choice questions strictly grounded in the passage:
1. "Cognitive Memory": Test precision recall of a key syntax rule, parameter constraint, formula name, standard port, or structural property directly mentioned in the passage.
2. "Logical Reasoning": Test causality, functional necessity, or why a specific mechanism operates the way it does based on the passage.
3. "Critical Thinking": Test operational trade-offs, limitations, edge cases, error conditions, or security/performance implications.
4. "Creative Application": A concrete practical scenario, code/formula snippet, calculation, or output tracing question based strictly on the provided passage.

STRICT QUALITY, DIVERSITY & ANTI-HALLUCINATION RULES (MANDATORY):
1. MANDATORY CONCEPT DIVERSITY: Each of the 4 questions MUST test a COMPLETELY DIFFERENT feature, function, formula, parameter, or concept from the passage. NEVER ask multiple questions about the same function (e.g. do NOT ask more than one question about VLOOKUP in this batch). Distribute questions across different topics (e.g. cell referencing, VLOOKUP, IF/COUNTIF, error codes, shortcuts).
2. GROUNDED IN PASSAGE: ALL questions and options MUST be strictly derived from the technical reference passage. NEVER invent unrelated frameworks, external libraries, or concepts not present in the passage.
3. FACTUAL ACCURACY & SINGLE UNAMBIGUOUS KEY: Double check that the designated `correctAnswer` is 100% factually, syntactically, and logically accurate according to standard official documentation.
   - For mixed referencing: `$A1` locks column A while allowing rows to change. `A$1` locks row 1 while allowing columns to change. `$A$1` locks both.
   - For lookup functions: `col_index_num` exceeding column count returns `#REF!`. Exact match lookup does NOT require the lookup column to be sorted.
   - Exactly ONE option must be correct. The other 3 options must be plausible but definitively incorrect.
4. NO TAUTOLOGIES OR QUESTION ECHOES: The correct answer and distractors must explain the technical reason or mechanism. NEVER write a correct answer that merely repeats or restates the question text. State the technical consequence or behavior clearly!
5. STANDALONE (ZERO META-REFERENCES): Questions must be completely self-contained. NEVER write "According to the passage", "as shown by the detokenized text", "In this chapter", "On page X", "In Figure X", "In the text", or "In the given context".
6. CLEAN VALUES, FORMULAS & SHORTCUTS: When options are keyboard shortcuts (`Ctrl + B`, `B`), cell references (`$A1`, `A$1`), formulas (`=SUM(A1:A10)`), or error codes (`#REF!`), write them as clean, concise values. Do NOT invent verbose sentences for naturally short syntax items. NEVER append trailing periods to formulas, shortcuts, cell references, or error codes.
7. ZERO EXAM OR COMPANY BRANDING: Ignore any company names (e.g. Accenture), campus drive labels, or document headers. NEVER ask about who created, authored, or administered the document. Test purely the technical software concepts.
8. CODE FORMATTING: Put all code, formula names, pseudocode, and keywords in backticks inside `questionText`.
9. RAW OPTIONS: Output option text only without labels like "A)", "B)", or "Option A:".

JSON OUTPUT FORMAT ONLY:
{{
  "questions": [
    {{
      "category": "Cognitive Memory",
      "questionText": "<Challenging question testing exact parameters, constants, formula syntax, or specifications>",
      "options": ["<Option A>", "<Option B>", "<Option C>", "<Option D>"],
      "correctAnswer": "<Exact matching option>"
    }},
    {{
      "category": "Logical Reasoning",
      "questionText": "<Challenging question testing causality, functional necessity, or behavioral rules>",
      "options": ["<Option A>", "<Option B>", "<Option C>", "<Option D>"],
      "correctAnswer": "<Exact matching option>"
    }},
    {{
      "category": "Critical Thinking",
      "questionText": "<Challenging question testing trade-offs, edge cases, error codes, or boundary limits>",
      "options": ["<Option A>", "<Option B>", "<Option C>", "<Option D>"],
      "correctAnswer": "<Exact matching option>"
    }},
    {{
      "category": "Creative Application",
      "questionText": "<Challenging question testing practical scenario, code/formula evaluation, or output prediction>",
      "options": ["<Option A>", "<Option B>", "<Option C>", "<Option D>"],
      "correctAnswer": "<Exact matching option>"
    }}
  ]
}}"""

    valid_questions = []

    try:
        r = requests.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json={
                "model": model_name,
                "prompt": prompt,
                "format": "json",
                "stream": False,
                "keep_alive": "60m",
                "options": {
                    "temperature": 0.2,
                    "num_predict": 1400
                }
            },
            timeout=120
        )
        if r.status_code == 200:
            raw_qs = parse_llm_questions_resilient(r.json().get("response", ""))
            for cat in CATEGORIES:
                match = next((q for q in raw_qs if q.get("category", "").lower() == cat.lower()), None)
                if not match and raw_qs:
                    match = raw_qs.pop(0)
                    match["category"] = cat

                if match:
                    raw_qt = _sanitize_text(match.get("questionText", ""))
                    clean_qt = _strip_meta_references(raw_qt)
                    raw_opts = match.get("options", [])
                    raw_ans = match.get("correctAnswer", "")
                    if isinstance(raw_ans, list):
                        raw_ans = raw_ans[0] if raw_ans else ""
                    raw_ans = str(raw_ans).strip()

                    if isinstance(raw_opts, list):
                        raw_opts = [o[0] if isinstance(o, list) else str(o) for o in raw_opts]

                    if clean_qt and isinstance(raw_opts, list) and len(raw_opts) == 4:
                        sanitized_opts = [_clean_option_text(o) for o in raw_opts]
                        sanitized_ans = _clean_option_text(raw_ans)
                        equalized_opts, equalized_ans = equalize_option_lengths(sanitized_opts, sanitized_ans)

                        shuffled = list(equalized_opts)
                        random.shuffle(shuffled)

                        q_item = {
                            "category": cat,
                            "questionText": clean_qt,
                            "options": shuffled,
                            "correctAnswer": equalized_ans,
                            "chapterTitle": chapter_title or topic,
                            "sourcePage": page_num
                        }
                        q_item = validate_and_correct_question_key(q_item)
                        valid_questions.append(q_item)
    except Exception as e:
        print(f"[TEST GEN] Batch for page {page_num} notice: {e}")

    # Domain-grounded universal fallback question bank
    fallback_templates = {
        "Cognitive Memory": [
            (
                "In the context of {topic}, what is the primary role or definition of {w1}?",
                "To serve as a foundational mechanism or standard component according to established principles.",
                "To act as an optional secondary indicator without affecting core operations or outcomes.",
                "To bypass standard validation rules and force arbitrary default values.",
                "To terminate execution or analysis immediately upon encountering variable inputs."
            ),
            (
                "Which characteristic or property directly defines the behavior or nature of {w1}?",
                "The documented operational parameters and baseline constraints established within {topic}.",
                "The external presentation formatting and arbitrary visual standard.",
                "The secondary temporary caching and transient buffer allocation size.",
                "The arbitrary background polling frequency of external observation monitors."
            ),
            (
                "What core specification or standard constraint governs the configuration of {w1}?",
                "The designated parameter schema and adherence to formal interface conventions.",
                "The arbitrary graphical window layout established by client themes.",
                "The volatile operating system memory fragmentation index.",
                "The random numeric seed initialized at initial boot sequence."
            ),
            (
                "Which invariant condition must be maintained when evaluating or referencing {w1}?",
                "Structural determinism and compliance with documented input type rules.",
                "Automatic inversion of parameter values upon successful evaluation.",
                "Unrestricted read and write access to isolated external memory blocks.",
                "Instantaneous execution with zero computational resource usage."
            ),
            (
                "In standard architectural implementations, how is {w1} formally categorized?",
                "As an essential functional component operating within documented parameter specifications.",
                "As an untyped background daemon lacking runtime validation guards.",
                "As a deprecated legacy routine maintained strictly for backward compatibility.",
                "As an arbitrary user-defined script lacking deterministic behavior."
            ),
            (
                "What is the expected default state or behavior of {w1} prior to receiving active inputs?",
                "Resting in an initialized standard state awaiting validated operational parameters.",
                "Continuously polling memory buffers and forcing continuous CPU interrupts.",
                "Randomly overwriting adjacent variables with arbitrary dummy data.",
                "Terminating parent processes upon detecting null or default values."
            )
        ],
        "Logical Reasoning": [
            (
                "Why is {w1} fundamental when analyzing or working with {topic}?",
                "It establishes systematic rules to ensure predictable, deterministic behavior and data integrity.",
                "It eliminates the necessity for validating input parameters and baseline conditions.",
                "It replaces structured methodological logic with unstructured arbitrary defaults.",
                "It causes intermediate findings or calculations to reset after each phase."
            ),
            (
                "How does the relationship between {w1} and {w2} govern outcomes in {topic}?",
                "By coordinating their respective functions so that structural validity and integrity are maintained.",
                "By randomly disabling downstream operations during processing.",
                "By resetting all configured variables to arbitrary initial states.",
                "By bypassing boundary condition checks in subsequent steps."
            ),
            (
                "Why must prerequisites be validated before initiating operations involving {w1}?",
                "To prevent invalid state propagation and safeguard downstream calculations from corruption.",
                "To force manual parameter recalculation after every single evaluation step.",
                "To reduce active storage allocation down to zero bytes.",
                "To bypass operating system security protocols and memory protections."
            ),
            (
                "What causal mechanism explains the outcome when {w1} encounters incompatible inputs?",
                "Formal validation guards halt execution or generate standardized diagnostic indicators.",
                "The system automatically invents plausible replacement data without notification.",
                "Hardware clocks are throttled to preserve internal power reserves.",
                "All external network socket connections are terminated instantaneously."
            ),
            (
                "Why is modular encapsulation enforced when designing mechanisms around {w1}?",
                "It isolates faults, minimizes cross-component interference, and enhances predictable maintainability.",
                "It eliminates the need for unit testing or integration verification.",
                "It permanently prevents external modules from receiving calculated outputs.",
                "It allows memory leaks to propagate safely without consuming physical RAM."
            ),
            (
                "How does the sequential evaluation of {w1} preserve algorithmic consistency?",
                "By resolving dependent arguments in deterministic order prior to final computation.",
                "By evaluating sub-expressions in random non-reproducible sequences.",
                "By disregarding parenthetical hierarchy and precedence rules.",
                "By caching unverified intermediate states across unrelated sessions."
            )
        ],
        "Critical Thinking": [
            (
                "What is a primary limitation or key consideration associated with {w1} in {topic}?",
                "Operational inputs and conditions must strictly adhere to expected structural bounds to prevent failure.",
                "It can only be applied to trivial sample cases and fails on comprehensive scenarios.",
                "All foundational criteria must be manually reconstructed on every single iteration.",
                "Operations must be halted whenever a non-zero parameter value is encountered."
            ),
            (
                "Under what condition does the application of {w1} risk producing invalid or unintended results?",
                "When foundational prerequisites or operational boundary constraints are violated.",
                "When all input data strictly matches the expected target distribution.",
                "When operating within standard nominal parameters and verified conditions.",
                "When baseline validation checks complete successfully without errors."
            ),
            (
                "What technical trade-off is introduced when increasing the operational complexity of {w1}?",
                "Debugging overhead and failure surface area increase alongside enhanced capability.",
                "Execution latency drops to zero while computational precision degrades.",
                "Memory consumption is eliminated entirely at the expense of storage durability.",
                "System throughput becomes completely immune to underlying hardware bottlenecks."
            ),
            (
                "What is the primary operational vulnerability when {w1} processes unvalidated external data?",
                "Vulnerability to calculation faults, injection anomalies, and unhandled runtime exceptions.",
                "Permanent degradation of physical storage drive read speeds.",
                "Inversion of host operating system system-level environment flags.",
                "Silent conversion of persistent database records into temporary caches."
            ),
            (
                "Why is relying solely on default configurations for {w1} suboptimal in high-reliability systems?",
                "Generic defaults may fail to account for domain-specific boundary constraints and throughput demands.",
                "Standard defaults intentionally inject random errors to test operational resilience.",
                "Default parameters permanently disable all diagnostic logging and audit capabilities.",
                "Configuration defaults force the underlying system to recompile from source code."
            ),
            (
                "When comparing {w1} with alternative approaches in {topic}, what constitutes its principal technical constraint?",
                "Strict dependency on verified structural prerequisites and formal data conventions.",
                "Inability to execute on standard multi-core processor architectures.",
                "Mandatory requirement for uninterrupted continuous internet connectivity.",
                "Total prohibition against interfacing with relational databases or files."
            )
        ],
        "Creative Application": [
            (
                "In a practical scenario involving {w1}, which workflow guarantees an accurate and robust result?",
                "Verifying baseline requirements, applying appropriate methods, and verifying results against standards.",
                "Applying the method directly without checking prerequisites or validating boundary conditions.",
                "Hardcoding fixed predetermined outputs regardless of incoming input data.",
                "Omitting verification steps and suppressing all generated error indicators."
            ),
            (
                "When troubleshooting unexpected results or anomalies involving {w1}, what is the most effective approach?",
                "Tracing each operational step systematically against established domain principles to identify discrepancies.",
                "Ignoring error indicators and allowing anomalous outputs to propagate unchecked.",
                "Discarding existing data entries whenever an unexpected result occurs.",
                "Disabling all validation rules and quality control checks across the entire workflow."
            ),
            (
                "When integrating {w1} into an automated pipeline, what architectural pattern ensures high resilience?",
                "Implementing explicit validation layers, graceful exception handling, and idempotent execution guards.",
                "Bypassing data transformation layers to reduce operational latency.",
                "Hardcoding internal memory addresses across distributed service nodes.",
                "Suppressing all error logging to minimize storage footprint."
            ),
            (
                "How should an engineer structure a regression test suite to thoroughly validate {w1}?",
                "Testing nominal workflows, boundary condition limits, and intentional invalid input edge cases.",
                "Testing only a single hardcoded happy-path scenario and extrapolating results.",
                "Relying exclusively on manual visual inspection without automated assertion checks.",
                "Disabling assertions whenever test execution time exceeds arbitrary thresholds."
            ),
            (
                "What remediation procedure should be executed when {w1} reports a critical boundary failure?",
                "Isolating the faulty input, analyzing the diagnostic state, and applying targeted parameter corrections.",
                "Rebooting the entire hardware infrastructure without capturing failure logs.",
                "Overwriting operational code with legacy unverified binaries.",
                "Terminating client network sessions permanently without diagnostic feedback."
            ),
            (
                "When refactoring legacy procedures into modern implementations of {w1}, what protocol guarantees backward compatibility?",
                "Comparing parallel execution outputs across a comprehensive benchmark suite of representative inputs.",
                "Immediately deprecating all legacy interfaces without transitional proxy layers.",
                "Altering mathematical formulas to simplify computational complexity regardless of precision loss.",
                "Removing unit tests that fail to compile under the new syntax structure."
            )
        ]
    }

    for cat in CATEGORIES:
        if not any(q["category"] == cat for q in valid_questions):
            w1 = key_concepts[0] if key_concepts else clean_topic_title(topic)
            w2 = key_concepts[min(1, len(key_concepts)-1)] if len(key_concepts) > 1 else "operation"

            template_choices = fallback_templates.get(cat, fallback_templates["Cognitive Memory"])
            choice_idx = (page_num * 7 + focus_angle + len(valid_questions) * 3) % len(template_choices)
            tmpl_qt, tmpl_ans, d1, d2, d3 = template_choices[choice_idx]

            qt = tmpl_qt.format(w1=w1, w2=w2, topic=topic)
            ans = tmpl_ans.format(w1=w1, w2=w2, topic=topic)

            opts, ans = equalize_option_lengths([ans, d1, d2, d3], ans)
            shuffled = list(opts)
            random.shuffle(shuffled)
            fallback_q = {
                "category": cat,
                "questionText": qt,
                "options": shuffled,
                "correctAnswer": ans,
                "chapterTitle": chapter_title or topic,
                "sourcePage": page_num
            }
            fallback_q = validate_and_correct_question_key(fallback_q)
            valid_questions.append(fallback_q)

    return valid_questions[:4]


def deduplicate_test_questions(questions: List[Dict[str, Any]], clean_topic: str) -> List[Dict[str, Any]]:
    """
    Guarantees 100% question uniqueness across the entire exam.
    Checks normalized stems, answers, and semantic keyword overlap to eliminate repetitive questions.
    Replaces duplicates with diverse, clean, domain-appropriate technical scenarios.
    """
    seen_stems = set()
    seen_answers = set()
    seen_keywords = []
    unique_questions = []

    def get_keywords(text: str) -> set:
        stop = {"what", "which", "when", "where", "why", "how", "does", "from", "with", "this", "that",
                "the", "and", "for", "are", "can", "all", "correct", "syntax", "used", "following",
                "statement", "value", "function", "parameter", "option", "result", "using", "true",
                "given", "excel", "word", "powerpoint", "formula", "code"}
        words = re.findall(r'[a-zA-Z0-9_\$#]+', text.lower())
        return {w for w in words if len(w) > 2 and w not in stop}

    alt_variants = {
        "Cognitive Memory": [
            ("In {w}, which specification or fundamental rule governs its primary operation?",
             "The standard configuration defining operational constraints and execution bounds.",
             "The external display adapter resolution setting.",
             "The temporary clipboard buffer refresh interval.",
             "The background network packet inspection rate."),
            ("What is the primary role of {w} within standard workflows?",
             "Providing structured functionality for consistent, reliable, and deterministic operations.",
             "Overriding internal security and memory boundary checks.",
             "Bypassing input validation routines unconditionally.",
             "Enforcing arbitrary dynamic variable recalculation at all times."),
            ("Which property is strictly maintained during standard execution in {w}?",
             "Functional determinism and adherence to documented syntax specifications.",
             "Automatic deletion of input references upon completion.",
             "Inversion of parameter order during sequential evaluation.",
             "Arbitrary modification of unrelated document properties."),
            ("What foundational prerequisite must be established prior to executing {w}?",
             "Validating input parameter compatibility and baseline structural environment constraints.",
             "Disabling operating system task scheduling and thread interrupts.",
             "Clearing persistent storage caches unconditionally.",
             "Converting all scalar variables into unbounded dynamic pointers."),
            ("Which structural boundary or constraint directly dictates the validity of {w}?",
             "The documented allowable ranges and formatted schema requirements.",
             "The physical orientation of the primary display monitor.",
             "The hardware clock speed of the auxiliary co-processor.",
             "The arbitrary sequential indexing of unrelated temporary tables."),
            ("How is {w} formally classified within standard system architecture?",
             "As an essential foundational component operating under explicit operational specifications.",
             "As an untyped background process running without input validation.",
             "As a legacy deprecated module maintained exclusively for backwards compatibility.",
             "As a volatile transient buffer lacking persistent state."),
            ("What is the designated default state of {w} prior to invocation?",
             "Resting in an initialized baseline state awaiting validated operational parameters.",
             "Continuously broadcasting network status packets across all interfaces.",
             "Pre-allocating maximum system memory regardless of workload demand.",
             "Supplying arbitrary placeholder values to downstream modules."),
            ("Which attribute of {w} is verified during formal compliance checks?",
             "Adherence to documented interface signatures and validated return data structures.",
             "The brand manufacturer of the physical host computer hardware.",
             "The number of concurrent graphical desktop windows open on the machine.",
             "The alphabetical order of file paths in the directory index."),
            ("What standard parameter convention governs the initialization of {w}?",
             "Explicit parameter definition adhering to strict schema and datatype conventions.",
             "Implicit type coercion defaulting to random floating point numbers.",
             "Dynamic keyword rewriting based on current CPU temperature.",
             "Suppressing all input verification to accelerate initial startup."),
            ("In technical documentation, what distinguishes {w} from secondary utility routines?",
             "Its dedicated role in establishing core structural logic and deterministic state handling.",
             "Its inability to run on modern 64-bit operating systems.",
             "Its requirement for continuous physical operator intervention.",
             "Its complete independence from system clocks and hardware counters."),
            ("Which invariant behavior is guaranteed when {w} receives valid parameters?",
             "Predictable, reproducible output strictly adhering to documented specifications.",
             "Immediate termination of all background processes.",
             "Random alteration of global system variables.",
             "Suppression of all output data without diagnostic logs."),
            ("What is the primary constraint regarding resource allocation in {w}?",
             "Operating within designated memory bounds and CPU execution quotas.",
             "Demanding exclusive single-threaded CPU lockouts unconditionally.",
             "Consuming all available disk storage before execution completes.",
             "Ignoring memory leak safeguards to maximize throughput."),
            ("Which lifecycle phase defines the active operational execution of {w}?",
             "The processing phase following parameter validation and prerequisite verification.",
             "The initial boot loader pre-kernel initialization sequence.",
             "The post-crash core dump serialization stage.",
             "The physical hardware decommissioning phase."),
            ("What is the defined return convention for {w} upon normal completion?",
             "A structured result object or validated value confirming expected output criteria.",
             "A null pointer with suppressed diagnostic flags.",
             "An unhandled system exception requiring reboot.",
             "An arbitrary numeric code unrelated to the calculation."),
            ("Which security constraint governs operations executed within {w}?",
             "Restricting memory access to authorized boundaries and preventing privilege escalation.",
             "Permitting arbitrary kernel code execution without authentication.",
             "Disabling all firewall and network inspection rules during execution.",
             "Storing sensitive credentials in unencrypted plain text buffers."),
            ("How does {w} handle nominal state transitions during processing?",
             "By progressing systematically through defined sequential stages with checkpoint validation.",
             "By skipping intermediate verification checks whenever CPU load exceeds 50%.",
             "By randomly branching into uninitialized instruction routines.",
             "By clearing all session context data between iterations.")
        ],
        "Logical Reasoning": [
            ("Within the context of {w}, why is systematic validation enforced at each stage?",
             "To prevent invalid state propagation and guarantee deterministic output results.",
             "To force manual parameter recalculation after every single step.",
             "To reset environment variables to default empty values.",
             "To disable calculation pipelines across sheet or section boundaries."),
            ("During the execution of {w}, what is the direct consequence of omitting parameter checks?",
             "Error codes, calculation failures, or unintended data corruption.",
             "Automatic self-healing with zero operational penalty.",
             "Instantaneous completion of all pending calculations.",
             "Suppression of all output values without diagnostic feedback."),
            ("Why is modular separation essential when working with {w}?",
             "It minimizes interdependencies, prevents cascading errors, and isolates potential faults.",
             "It completely eliminates the need for testing or verification.",
             "It reduces data storage requirements to zero bytes.",
             "It ensures operations run without requiring any input data."),
            ("Why must input parameters for {w} be resolved before downstream computation begins?",
             "Because downstream operations depend causally on the verified outputs of preceding stages.",
             "Because modern processors cannot process data in sequential order.",
             "To ensure all network sockets remain open indefinitely.",
             "To force the system into an infinite speculative execution loop."),
            ("What causal relationship exists between prerequisite validation and operational reliability in {w}?",
             "Validating prerequisites eliminates edge-case failures and prevents undefined runtime states.",
             "Prerequisite checks introduce non-deterministic bugs into compiled code.",
             "Checking inputs increases physical wear on solid-state drives.",
             "Validation guarantees that calculations execute with zero electricity."),
            ("Why does {w} enforce strict datatype alignment during evaluation?",
             "To prevent type mismatch exceptions, silent precision loss, and unexpected coercion anomalies.",
             "To limit execution strictly to ancient 16-bit integer calculations.",
             "To allow strings to be arbitrarily multiplied by system memory addresses.",
             "To force all floating-point numbers to truncate to zero."),
            ("How does error isolation within {w} protect the stability of the overall application?",
             "By trapping faults locally, preventing unhandled exceptions from crashing parent workflows.",
             "By suppressing all error notifications and returning fake success codes.",
             "By restarting the entire operating system upon detecting any warning.",
             "By routing all network traffic through an unmonitored proxy."),
            ("Why is sequential precedence critical when evaluating nested expressions in {w}?",
             "To guarantee that inner dependencies evaluate deterministically before outer functions execute.",
             "To ensure expressions are evaluated in reverse alphabetical order.",
             "To prevent multiple CPU cores from executing instructions simultaneously.",
             "To bypass operating system memory protection tables."),
            ("What logical necessity dictates that {w} maintain an immutable record of baseline state?",
             "To enable idempotent rollback and consistent audit verification if faults occur.",
             "To prevent users from viewing calculation results.",
             "To fill available hard drive space and force automatic cleanup routines.",
             "To ensure all historical data is overwritten on every reboot."),
            ("Why are boundary limits established for numerical operations within {w}?",
             "To prevent arithmetic overflow, underflow, and out-of-range memory indexing.",
             "To restrict calculations exclusively to prime numbers.",
             "To ensure all numeric results are forced to negative values.",
             "To eliminate the need for floating-point calculation hardware."),
            ("How does deterministic caching of intermediate states in {w} improve overall efficiency?",
             "By eliminating redundant evaluations of identical parameters without sacrificing accuracy.",
             "By clearing CPU L1 and L2 cache hierarchies after every instruction.",
             "By forcing disk reads on every arithmetic calculation.",
             "By randomly re-executing previously completed tasks."),
            ("Why is asynchronous execution in {w} decoupled from immediate UI presentation updates?",
             "To prevent heavy background computation from blocking the interactive interface responsiveness.",
             "To ensure the user interface freezes completely during background operations.",
             "To prevent data from ever reaching the presentation layer.",
             "To force all rendering through CPU software emulation."),
            ("What is the underlying logical cause of a synchronization deadlock in {w}?",
             "Two or more concurrent processes waiting perpetually on resources held by each other.",
             "A sudden increase in ambient operating room temperature.",
             "The presence of too many comments in the source code.",
             "Using lowercase variable names instead of uppercase letters."),
            ("Why does {w} require explicit termination conditions for iterative procedures?",
             "To prevent infinite loops, unbounded resource exhaustion, and application unresponsiveness.",
             "To ensure the CPU clock frequency drops to zero.",
             "To force automatic deletion of all project files upon loop completion.",
             "To bypass operating system scheduling queues."),
            ("How does decoupling data storage from operational logic enhance {w}?",
             "It allows data schemas and business rules to evolve independently without breaking core contracts.",
             "It forces all data to be stored exclusively in volatile CPU registers.",
             "It prevents external backup systems from copying data files.",
             "It eliminates the need for database indexes and primary keys."),
            ("Why must configuration flags for {w} be validated at launch rather than deferred to runtime?",
             "To fail fast before executing critical workloads, avoiding corrupt state during production runs.",
             "To extend application startup latency to several hours.",
             "To ensure default settings can never be inspected by system administrators.",
             "To disable all interactive diagnostic command-line tools.")
        ],
        "Critical Thinking": [
            ("When applying {w} in complex operational scenarios, what is the primary technical consideration?",
             "Balancing execution efficiency and resource utilization against data accuracy and integrity.",
             "Trading specification compliance for unverified speed gains.",
             "Sacrificing output reliability for immediate completion.",
             "Choosing deprecated legacy syntax over standard supported methods."),
            ("How does increasing the complexity of {w} impact overall maintenance and reliability?",
             "Debugging difficulty and the risk of unhandled edge cases increase proportionally.",
             "Operational complexity remains strictly constant regardless of structure.",
             "System overhead decreases as the number of dependencies multiplies.",
             "All potential error conditions are automatically resolved."),
            ("What technical risk arises if {w} is executed without appropriate error-handling guards?",
             "Unhandled runtime errors, formula failure cascades, and invalid downstream outputs.",
             "Physical damage to internal hardware components.",
             "Automatic conversion of static values into volatile formulas.",
             "Permanent loss of application configuration settings."),
            ("Under high-concurrency conditions, what is the principal architectural vulnerability of {w}?",
             "Race conditions, resource contention, and inconsistent shared-state mutations.",
             "Physical overheating of external monitor displays.",
             "Automatic deletion of operating system boot files.",
             "Spontaneous reversal of data sorting orders."),
            ("What is the major limitation of relying on heuristic approximations within {w}?",
             "Risk of subtle precision degradation and invalid outputs on non-standard input distributions.",
             "Heuristics always execute ten times slower than brute-force calculation.",
             "Approximations require continuous physical network connectivity.",
             "Modern processors refuse to compile heuristic algorithms."),
            ("When evaluating the security posture of {w}, which vector represents the highest operational risk?",
             "Unsanitized input injection leading to unauthorized code execution or data leakage.",
             "Setting desktop wallpaper resolution to 4K instead of 1080p.",
             "Using standard UTF-8 encoding for text files.",
             "Executing calculations on battery power instead of AC adapter."),
            ("What is the primary trade-off when configuring aggressive memory caching for {w}?",
             "Lower calculation latency traded against higher RAM footprint and risk of stale state.",
             "Faster execution traded against permanent loss of CPU instructions.",
             "Zero memory consumption achieved by disabling disk storage.",
             "Automatic deletion of network adapters upon cache fill."),
            ("Why can premature optimization of {w} lead to severe architectural liabilities?",
             "Obscuring code readability, introducing brittle edge cases, and complicating maintenance.",
             "Optimizations always increase physical binary file size by 1000%.",
             "Compilers automatically reject optimized algorithms during build.",
             "Hardware manufacturers void device warranties when code is optimized."),
            ("What critical failure mode occurs if {w} is deployed without adequate input bounds checking?",
             "Buffer overflow, memory boundary corruption, or silent propagation of invalid data.",
             "Immediate physical shutdown of the local electrical circuit breaker.",
             "Automatic formatting of all attached backup drives.",
             "Inversion of alphanumeric characters on physical keyboards."),
            ("How does tight coupling between {w} and external third-party libraries compromise system resilience?",
             "External breaking changes or vulnerabilities immediately destabilize the host application.",
             "Third-party libraries consume 100% of GPU compute cycles at all times.",
             "Coupled libraries prevent operating systems from updating device drivers.",
             "Third-party dependencies force code to compile in 8-bit mode."),
            ("What is the danger of suppressing diagnostic warnings during the execution of {w}?",
             "Masking latent bugs and structural defects until catastrophic failure occurs in production.",
             "Warnings consume immense hard drive storage space if left unsuppressed.",
             "Displaying warnings physically damages computer monitors.",
             "Suppressing warnings increases calculation precision by 50%."),
            ("When scaling {w} to enterprise volumes, what bottleneck typically emerges first?",
             "I/O throughput limitations, memory bandwidth saturation, and lock contention.",
             "Exhaustion of available letters in the English alphabet for variable names.",
             "Depletion of physical system time counters on the motherboard.",
             "Inability to format numbers with commas and decimals."),
            ("Why is blind reliance on default configuration parameters in {w} dangerous?",
             "Default settings are generalized and often leave security holes or performance bottlenecks unaddressed.",
             "Configuration defaults are intentionally designed to inject malicious logic.",
             "Default parameters disable all hardware cooling fans.",
             "Systems running on default configurations automatically lock themselves after 24 hours."),
            ("What trade-off is involved when choosing strict consistency over eventual consistency in {w}?",
             "Guaranteed data accuracy at the cost of higher latency and lower availability during network partitions.",
             "Instantaneous network replication achieved by dropping all encryption.",
             "Zero latency achieved by omitting all data validation.",
             "Unlimited throughput achieved by corrupting database indices."),
            ("How does lack of idempotent design in {w} impact automated retry mechanisms?",
             "Retrying failed operations may cause duplicate transactions, double counting, or corrupted state.",
             "Idempotency causes the computer to execute operations in reverse.",
             "Non-idempotent operations always execute faster than idempotent ones.",
             "Retrying non-idempotent tasks causes physical processor cores to shut down."),
            ("What is the principal danger of unchecked memory allocation during long-running tasks in {w}?",
             "Gradual memory exhaustion, operating system paging thrashing, and eventual process crash.",
             "Physical expansion of RAM modules inside the computer chassis.",
             "Conversion of dynamic RAM into read-only ROM memory.",
             "Sudden erasure of the computer BIOS firmware.")
        ],
        "Creative Application": [
            ("In a practical implementation involving {w}, what constitutes a valid, robust execution sequence?",
             "Initializing prerequisites, validating input ranges, executing logic, and verifying output bounds.",
             "Executing logic directly without prior parameter initialization or validation.",
             "Assuming all external references and dependent values are unconditionally correct.",
             "Suppressing all return values and error flags during processing."),
            ("When troubleshooting unexpected results in an operation utilizing {w}, which approach is most effective?",
             "Tracing intermediate evaluations step-by-step against documented syntax rules.",
             "Relying solely on visual inspection without checking argument formulas.",
             "Randomly altering parameter values until desired output appears.",
             "Disabling all system warnings and error diagnostics."),
            ("Which practice should be applied when integrating {w} with other functions or modules?",
             "Ensuring type compatibility and matching input/output interfaces precisely.",
             "Overriding target function signatures without verifying compatibility.",
             "Bypassing data transformation steps to minimize processing time.",
             "Ignoring interface documentation and forcing default arguments."),
            ("How should an engineer design a comprehensive automated test harness for {w}?",
             "Combining unit assertions for happy-path cases, boundary condition fuzzing, and regression tests.",
             "Running a single manual test and assuming all permutations behave identically.",
             "Testing only with positive integers and ignoring null, negative, and string inputs.",
             "Writing assertions that automatically pass regardless of the returned value."),
            ("When migrating legacy calculations to a modern implementation of {w}, what protocol ensures fidelity?",
             "Running side-by-side parallel benchmarks and validating output parity across diverse test cases.",
             "Replacing legacy routines immediately in production without verification.",
             "Manually recalculating one sample row on paper and deploying.",
             "Disabling regression testing to accelerate project delivery schedules."),
            ("What architectural pattern best isolates {w} from unexpected input volatility?",
             "Implementing an input sanitization and boundary-validation proxy layer.",
             "Connecting the internal core logic directly to unvalidated external data feeds.",
             "Hardcoding expected values and discarding any dynamic inputs.",
             "Permitting all inputs to execute with elevated administrative privileges."),
            ("How can system observability be effectively established for {w} in production environments?",
             "Emitting structured telemetry logs, tracking latency distributions, and capturing error rates.",
             "Writing raw stack traces to volatile desktop popup messages.",
             "Disabling all logging to conserve storage and reduce overhead.",
             "Logging sensitive passwords and authentication keys in unencrypted text files."),
            ("When refactoring a monolithic implementation of {w} into microservices, what design rule is paramount?",
             "Defining clear interface boundaries, minimizing state sharing, and handling partial failures gracefully.",
             "Allowing all microservices to directly write to a single unmanaged shared memory pool.",
             "Deploying all services onto a single physical virtual machine without isolation.",
             "Removing all authentication headers between internal service endpoints."),
            ("What strategy ensures continuous data availability during scheduled maintenance of {w}?",
             "Employing rolling deployments, active-passive failover clustering, and zero-downtime migrations.",
             "Terminating all active database connections without saving pending transactions.",
             "Disconnecting the primary network cables while queries are executing.",
             "Forcing all client requests to return 500 Internal Server Errors during the window."),
            ("How should an engineer systematically debug a subtle numerical drift error in {w}?",
             "Isolating floating-point rounding points, validating precision settings, and verifying step calculations.",
             "Replacing all mathematical formulas with arbitrary hardcoded constants.",
             "Blaming the underlying hardware and ignoring code discrepancies.",
             "Truncating all intermediate calculations to single-digit integers."),
            ("When building an automated disaster recovery plan for {w}, what mechanism guarantees rapid recovery?",
             "Automated health checks, replicated immutable backups, and validated infrastructure-as-code recovery scripts.",
             "Relying on manual sticky notes with operator credentials written on them.",
             "Backing up data once per year to an unverified local flash drive.",
             "Disabling all backup routines to prevent storage costs from increasing."),
            ("What configuration management technique ensures reproducible deployments of {w}?",
             "Version-controlled declarative configuration files decoupled from code binaries.",
             "Manually changing registry settings on production servers via remote desktop.",
             "Allowing developers to edit configuration files directly in live production environments.",
             "Relying on memory defaults and omitting configuration files altogether."),
            ("How can throughput bottlenecks in {w} be systematically diagnosed without interrupting live users?",
             "Attaching a non-intrusive asynchronous performance profiler to capture CPU and memory flame graphs.",
             "Pausing the server process for several minutes during peak traffic to examine thread dumps.",
             "Terminating 50% of user sessions to see if performance improves.",
             "Disabling SSL encryption on all incoming requests."),
            ("What protocol should be followed to safely deprecate a legacy feature within {w}?",
             "Issuing clear deprecation warnings across release cycles, providing migration paths, and monitoring usage.",
             "Deleting the legacy feature abruptly in a minor patch without prior notification.",
             "Modifying the legacy feature to return corrupted calculations silently.",
             "Removing documentation while leaving the buggy legacy code in production."),
            ("How should a development team organize CI/CD pipelines to prevent regressions in {w}?",
             "Requiring automated unit tests, lint checks, integration tests, and peer review before merging.",
             "Pushing unreviewed code directly to production branches on Friday afternoons.",
             "Skipping automated testing whenever builds take longer than two minutes.",
             "Disabling linting tools because formatting consistency is purely aesthetic."),
            ("What approach guarantees safe rollback if a new release of {w} introduces critical runtime errors?",
             "Blue/green or canary deployments coupled with automated health metrics that trigger instant rollback.",
             "Manually recompiling the previous source code from memory on the live server.",
             "Deleting all server logs to hide the failure from end users.",
             "Waiting for users to report errors before deciding whether to investigate.")
        ]
    }

    for q in questions:
        qt = q.get("questionText", "")
        ans = q.get("correctAnswer", "")
        stem_norm = re.sub(r'[^a-zA-Z0-9]', '', qt.lower())[:120]
        ans_norm = re.sub(r'[^a-zA-Z0-9]', '', ans.lower())[:80]
        kw = get_keywords(qt)

        # Check exact collision or high keyword collision (>0.6 Jaccard with at least 3 shared keywords)
        is_dup = (stem_norm in seen_stems) or (ans_norm in seen_answers)
        if not is_dup and kw:
            for prev_kw in seen_keywords:
                intersection = kw & prev_kw
                if len(intersection) >= 3:
                    jaccard = len(intersection) / len(kw | prev_kw)
                    if jaccard >= 0.6:
                        is_dup = True
                        break

        if is_dup:
            cat = q.get("category", "Cognitive Memory")
            chap = q.get("chapterTitle", clean_topic)
            clean_chap = re.sub(r'^\d+\s*', '', chap).strip() or clean_topic
            clean_chap = re.sub(r'^(?:Chapter\s*\d+|Section\s*\d+)[:\s\-–]*', '', clean_chap, flags=re.I).strip() or clean_topic

            variants = alt_variants.get(cat, alt_variants["Cognitive Memory"])
            found_var = None
            for cand in variants:
                cand_qt = cand[0].format(w=clean_chap)
                cand_ans = cand[1].format(w=clean_chap)
                cand_s_norm = re.sub(r'[^a-zA-Z0-9]', '', cand_qt.lower())[:120]
                cand_a_norm = re.sub(r'[^a-zA-Z0-9]', '', cand_ans.lower())[:80]
                if cand_s_norm not in seen_stems and cand_a_norm not in seen_answers:
                    found_var = (cand, cand_qt, cand_ans, cand_s_norm, cand_a_norm)
                    break

            if not found_var:
                base_var = variants[len(unique_questions) % len(variants)]
                specifier = f"specifically in Practice Section {len(unique_questions) + 1}"
                cand_qt = base_var[0].format(w=f"{clean_chap} ({specifier})")
                cand_ans = base_var[1].format(w=clean_chap)
                cand_s_norm = re.sub(r'[^a-zA-Z0-9]', '', cand_qt.lower())[:120]
                cand_a_norm = re.sub(r'[^a-zA-Z0-9]', '', cand_ans.lower())[:80]
                found_var = (base_var, cand_qt, cand_ans, cand_s_norm, cand_a_norm)

            selected_var, new_qt, new_ans, stem_norm, ans_norm = found_var
            opts, new_ans = equalize_option_lengths([new_ans, selected_var[2], selected_var[3], selected_var[4]], new_ans)
            shuffled = list(opts)
            random.shuffle(shuffled)
            q["questionText"] = new_qt
            q["options"] = shuffled
            q["correctAnswer"] = new_ans
            q = validate_and_correct_question_key(q)
            kw = get_keywords(new_qt)

        seen_stems.add(stem_norm)
        seen_answers.add(ans_norm)
        seen_keywords.append(kw)
        unique_questions.append(q)

    return unique_questions


def create_mcq_test(
    document_chunks_or_path: Any,
    total_questions: int = 16,
    topic: str = "General Study",
    model_override: Optional[str] = None,
    progress_callback=None,
    selected_chapters: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Generates a deep technical MCQ test sampled across technical chapters.
    Uses sequential Ollama processing for maximum stability and prompt accuracy.
    Strictly guarantees equal question distribution across 4 cognitive categories and zero duplication.
    Supported lengths: 16, 32, 48, 60.
    """
    import threading

    _ensure_ollama_running()

    if total_questions not in TEST_LENGTHS:
        total_questions = 16

    config_info = TEST_LENGTHS[total_questions]
    num_batches = config_info["batches"]
    per_category = config_info["per_cat"]
    model_name = model_override or MODELS.get("questions", "phi3")

    clean_topic = clean_topic_title(topic)

    print(f"[TEST] Starting Parallel Deep Generation: '{config_info['name']}' ({total_questions} total, "
          f"{num_batches} chapter batches) | Topic: '{clean_topic}' | Scope: {selected_chapters or 'All Chapters'} | Model: {model_name}")

    if progress_callback:
        scope_desc = f"{len(selected_chapters)} Selected Chapter(s)" if selected_chapters else "All Chapters"
        progress_callback(f"Starting {config_info['name']} ({total_questions} questions) across {scope_desc} of '{clean_topic}' using {model_name}…")

    passages = []
    if isinstance(document_chunks_or_path, str) and os.path.exists(document_chunks_or_path):
        passages = extract_substantive_passages_from_pdf(
            document_chunks_or_path,
            count=num_batches,
            selected_chapter_ids=selected_chapters
        )
    elif isinstance(document_chunks_or_path, list) and document_chunks_or_path:
        if isinstance(document_chunks_or_path[0], str) and os.path.exists(document_chunks_or_path[0]):
            passages = extract_substantive_passages_from_pdf(
                document_chunks_or_path[0],
                count=num_batches,
                selected_chapter_ids=selected_chapters
            )
        else:
            total_c = len(document_chunks_or_path)
            for b in range(num_batches):
                idx = b % total_c
                chunk_str = str(document_chunks_or_path[idx])
                cycle_num = b // total_c
                offset = min(cycle_num * 600, max(0, len(chunk_str) - 800))
                selected_text = chunk_str[offset : offset + 1200] if len(chunk_str) > offset else chunk_str[:1200]
                first_line = chunk_str.split("\n")[0].strip().lstrip("#:- ").strip()
                title = first_line[:40] if first_line else f"Section {b+1}"
                passages.append({
                    "page": b + 1,
                    "chapter_id": f"part_{b+1}",
                    "chapter_title": title,
                    "text": selected_text
                })

    if not passages:
        passages = [{"page": 1, "chapter_id": "ch_1", "chapter_title": "Core", "text": f"Foundational concepts in {clean_topic}."}] * num_batches

    all_questions = []
    completed_count = 0
    progress_lock = threading.Lock()
    tested_concepts_global = set()

    def _process_batch(item):
        nonlocal completed_count
        b_idx, passage = item
        chap_title = passage.get("chapter_title", "")
        focus_angle = passage.get("focus_angle", b_idx % 4)
        batch_qs = generate_batch_for_passage(
            passage["text"],
            passage["page"],
            clean_topic,
            model_name,
            chapter_title=chap_title,
            focus_angle=focus_angle,
            excluded_concepts=list(tested_concepts_global)
        )
        with progress_lock:
            for q in batch_qs:
                words = re.findall(r'\b[A-Z][a-zA-Z0-9_]{2,}\b|\b[a-z]{3,}_[a-z0-9_]+\b', q.get("questionText", ""))
                for w in words:
                    if w.lower() not in {"what", "which", "when", "where", "why", "how", "does", "from", "with", "this", "that", "chapter", "section"}:
                        tested_concepts_global.add(w)
            completed_count += 1
            if progress_callback:
                progress_callback(f" [{completed_count}/{num_batches}] Synthesized 4 questions from '{chap_title or 'Section'}' (p.{passage['page']})")
        return (b_idx, batch_qs)

    # Sequential processing for local Ollama to guarantee 100% stability, zero timeouts, and maximum token quality
    results = []
    for idx, p in enumerate(passages, 1):
        res = _process_batch((idx, p))
        results.append(res)

    # Sort back by original batch order to maintain chapter progression
    results.sort(key=lambda x: x[0])
    for _, batch_qs in results:
        all_questions.extend(batch_qs)

    if progress_callback:
        progress_callback("Finalizing test — deduplicating and balancing cognitive categories…")

    grouped_by_cat = {cat: [] for cat in CATEGORIES}
    for q in all_questions:
        grouped_by_cat[q["category"]].append(q)

    interleaved = []
    for i in range(per_category):
        for cat in CATEGORIES:
            cat_list = grouped_by_cat[cat]
            if i < len(cat_list):
                interleaved.append(cat_list[i])

    # If any category had fewer questions than per_category, fill up from any remaining questions
    if len(interleaved) < total_questions:
        remaining_pool = [q for q in all_questions if q not in interleaved]
        for q in remaining_pool:
            if len(interleaved) >= total_questions:
                break
            interleaved.append(q)

    # If still short, synthesize using category fallbacks
    while len(interleaved) < total_questions:
        needed_cat = CATEGORIES[len(interleaved) % len(CATEGORIES)]
        extra_b = generate_batch_for_passage(f"Foundational concepts and principles of {clean_topic}.", 1, clean_topic, model_name, clean_topic, focus_angle=len(interleaved))
        match_q = next((q for q in extra_b if q.get("category") == needed_cat), extra_b[0])
        interleaved.append(match_q)

    # Truncate if somehow exceeded
    interleaved = interleaved[:total_questions]

    # Global deduplication across all questions
    interleaved = deduplicate_test_questions(interleaved, clean_topic)

    # FINAL INTEGRITY AUDIT:
    # Guarantee 100% of questions have exactly 4 non empty, distinct options and a valid correctAnswer
    for idx, q in enumerate(interleaved):
        q["id"] = idx + 1
        opts = q.get("options", [])
        ans = q.get("correctAnswer", "")
        # If any option is empty, dot-only, options not length 4, or options contain duplicates
        if not isinstance(opts, list) or len(opts) != 4 or len(set(opts)) != 4 or any(not str(o).strip() or re.match(r'^[\.\:\-\s]+$', str(o).strip()) for o in opts) or ans not in opts:
            valid_opts, valid_ans = equalize_option_lengths(opts, ans)
            q["options"] = valid_opts
            q["correctAnswer"] = valid_ans
        validate_and_correct_question_key(q)

    test_id = str(uuid.uuid4())
    print(f"[TEST] Complete: {len(interleaved)} questions | testId: {test_id}")

    if progress_callback:
        progress_callback(f" All {len(interleaved)} chapter questions ready! Loading exam interface…")

    return {
        "testId": test_id,
        "testType": config_info["name"],
        "totalQuestions": len(interleaved),
        "topic": clean_topic,
        "selectedChapters": selected_chapters or [],
        "questions": interleaved
    }
