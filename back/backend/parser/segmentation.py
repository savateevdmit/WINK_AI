#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Hardened screenplay parser — DOCX numbering-aware edition.

Key features:
- Robust DOCX paragraph extraction that reconstructs Word numbering shown on screen
  (reads word/numbering.xml and computes numbering labels per paragraph).
- Highlight-aware (w:shd) detection: highlighted paragraphs won't be mis-detected as cast headers.
- Attempts to preserve/restore numeric scene numbers (number, number_suffix).
- Otherwise uses the improved heuristics for slug/cast/dialogue/action as before.
"""
from __future__ import annotations
import os
import re
import unicodedata
import importlib
import collections
import zipfile
import xml.etree.ElementTree as ET
from typing import List, Dict, Any, Optional, Tuple, Union, Iterable, DefaultDict

# -------------------------
# Config
# -------------------------
VERBOSE = False
SPLIT_ACTION_BLOCKS_INTO_SENTENCES = False
MAX_SCENE_CHARS_BEFORE_FORCED_SPLIT = 3000
MIN_LINES_FOR_VERTICAL_CAST = 2
MAX_VERTICAL_CAST_LINES = 12
MAX_LINE_LEN_FOR_NAME = 120
MAX_NUMBERING_LEVELS = 12

# -------------------------
# lazy imports
# -------------------------
_fitz = None
_pdfplumber = None
PdfReader = None
Document = None
Image = None
_easyocr = None

def _lazy_imports():
    global _fitz, _pdfplumber, PdfReader, Document, Image, _easyocr
    try:
        _fitz = importlib.import_module("fitz")  # PyMuPDF
    except Exception:
        _fitz = None
    try:
        _pdfplumber = importlib.import_module("pdfplumber")
    except Exception:
        _pdfplumber = None
    try:
        spec = importlib.util.find_spec("pypdf")
        if spec:
            pypdf = importlib.import_module("pypdf")
            PdfReader = getattr(pypdf, "PdfReader", None)
        else:
            spec2 = importlib.util.find_spec("PyPDF2")
            if spec2:
                py_pdf2 = importlib.import_module("PyPDF2")
                PdfReader = getattr(py_pdf2, "PdfReader", None)
    except Exception:
        PdfReader = None
    try:
        docx = importlib.import_module("docx")
        Document = getattr(docx, "Document", None)
    except Exception:
        Document = None
    try:
        from PIL import Image as _PILImage
        Image = _PILImage
    except Exception:
        Image = None

def _get_easyocr_reader():
    global _easyocr
    if _easyocr is not None:
        return _easyocr
    try:
        easyocr = importlib.import_module("easyocr")
    except Exception as e:
        raise RuntimeError(
            "EasyOCR is not installed. Install with:\n"
            "  pip install easyocr\n"
            "And ensure torch (CPU) is available, e.g.:\n"
            "  pip install torch --index-url https://download.pytorch.org/whl/cpu\n"
        ) from e
    _easyocr = easyocr.Reader(["ru", "en"], gpu=False, verbose=False)
    return _easyocr

# -------------------------
# normalization + regexes
# -------------------------
SOFT_HYPHEN_RE = re.compile("\u00AD")
WHITESPACES = ["\u00A0", "\u202F", "\u2007"]
DASH_TRANSLATE = {ord("–"):"-", ord("—"):"-", ord("−"):"-", ord("-"):"-"}

def normalize_text(s: str) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s)
    s = SOFT_HYPHEN_RE.sub("", s)
    for ws in WHITESPACES:
        s = s.replace(ws, " ")
    s = s.translate(DASH_TRANSLATE)
    s = re.sub(r"[ \t]+", " ", s)
    return s.strip()

DASH = r"[–—-]"
DASH_ALL = r"[.\-–—-]"
IE_TOK = r"(?:INT|EXT|ИНТ|ЭКСТ|НАТ|EXTERIOR|INTERIOR)(?:\s*/\s*(?:INT|EXT|ИНТ|ЭКСТ|НАТ))*"
TOD = r"(?:ДЕНЬ|НОЧЬ|ВЕЧЕР|УТРО|СУМЕРКИ|ПОЛДЕНЬ|MORNING|NIGHT|DAY|EVENING)"
SCN_NUM = rf"[0-9]+(?:{DASH_ALL}[0-9A-Za-zА-Яа-я]+)*"
TAIL_FLAGS = rf"(?:\s*{DASH}\s*(?:ДОСЪЕМ|ПЕРЕСЪЕМ|ПЕРЕНЕСЕНА.*|ДООЗВУЧКА).*)?"

SLUG_RE = re.compile(
    rf"""
    ^\s*
    (?P<num>{SCN_NUM})?
    \s*
    (?:(?P<num_suffix>-[A-Za-zА-Яа-я0-9]+)\.?)?
    \s*
    (?:\((?P<paren>[^)]{{0,80}})\)\.?\s*)?
    (?P<ie>{IE_TOK})\b\.?(?=\s|$)
    \s*
    (?P<rest>.*?)
    \s*
    (?P<removed>\(УДАЛЕНА\))?
    \s*$
    """,
    re.IGNORECASE | re.VERBOSE
)

REST_TIME_RE = re.compile(
    rf"""
    ^
    (?P<loc>.*?)
    (?:\s*(?:{DASH}|\.)\s*(?P<tod>{TOD})\.?)?
    (?:\s*\.?\s*(?:СД\s*)?(?P<shoot_day>\d+)\.?)?
    (?:\s*\.?\s*(?P<timecode>\d{{1,2}}:\d{{2}}))?
    {TAIL_FLAGS}?
    \s*$
    """,
    re.IGNORECASE | re.VERBOSE
)

CHAR_CUE_HARD_RE = re.compile(r"^[A-ZА-ЯЁ0-9\s\-\.'()]+$", re.UNICODE)
SENT_SPLIT = re.compile(r'(?<=[\.\?\!…])\s+(?=[А-ЯЁA-Z])')
COMMON_LOWER_START = re.compile(r'^(?:и|а|но|как|когда|если|под|от|из|это|то|он|она|они|в|во|на|к|с|отходит)\b', re.IGNORECASE)
UPPER_COMMA_CONT_RE = re.compile(r'^[«"(\[]?[А-ЯЁ][а-яё]+,\s')
TIME_PREFIX_RE = re.compile(r'^\(\s*\d{1,2}:\d{2}\s*\)\s*|^\d{1,2}:\d{2}\s*')
DASH_END_RE = re.compile(rf"{DASH}\s*$")
SLUG_HEAD_RE = re.compile(rf"^\s*(?:{SCN_NUM})(?:\s*\([^)]+\)\.)?\s*$", re.IGNORECASE)
IE_LINE_RE = re.compile(rf"^\s*{IE_TOK}\b", re.IGNORECASE)

# helpers for columns/pagination
PAGE_NUM_RE = re.compile(r'^\s*страница\s*\d+\s*$', re.IGNORECASE)
FOOTER_HEADER_CLEAN_RE = re.compile(r'^(?:page|страница|серия|episode)\b.*$', re.IGNORECASE)

# cast heuristics
CAST_HEADER_LINE_REJECT_CHARS = re.compile(r"[0-9;:!?]")
CAST_TOKEN_RE = re.compile(r"^[A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё\.\- ]*$")

def looks_like_name(tok: str) -> bool:
    tok = (tok or "").strip()
    if not tok:
        return False
    if tok.upper() == tok and re.search(r'[A-ZА-ЯЁ]', tok):
        return True
    if re.match(r'^[A-ZА-ЯЁ][a-zа-яё\-]+(?:\s+[A-ZА-ЯЁ][a-zа-яё\-]+)?$', tok):
        return True
    return False

def _is_cast_header_line(line: str, highlight: bool = False) -> Optional[List[str]]:
    if highlight:
        return None
    s = line.strip()
    if not s:
        return None
    if CAST_HEADER_LINE_REJECT_CHARS.search(s):
        return None
    s_clean_for_check = s.replace(".", "")
    parts = [p.strip() for p in s_clean_for_check.split(",") if p.strip()]
    if len(parts) < 3:
        return None
    name_like = sum(1 for p in parts if looks_like_name(p))
    if name_like < max(2, (len(parts) + 1)//2):
        return None
    cleaned: List[str] = []
    for p in parts:
        if len(p) > 40:
            return None
        if not CAST_TOKEN_RE.match(p):
            return None
        t = "-".join(x.capitalize() for x in p.split("-"))
        cleaned.append(t)
    return cleaned

CAST_HEADER_PREFIX_RE = re.compile(
    r"""
    ^\s*
    (?P<header>
      (?:[A-Za-zА-Яа-яЁё\.\-]+(?:\s+[A-Za-zА-Яа-яЁё\.\-]+)?)    
      (?:\s*,\s*
         (?:[A-Za-zА-Яа-яЁё\.\-]+(?:\s+[A-Za-zА-Яа-яЁё\.\-]+)?)
      ){2,}                                                 
    )
    \s+
    (?P<rest>.+)
    $
    """,
    re.VERBOSE,
)

def _extract_cast_header_and_action(text: str) -> Tuple[List[str], str]:
    m = CAST_HEADER_PREFIX_RE.match(text)
    if not m:
        return [], text
    header = m.group("header").strip()
    rest = m.group("rest").strip()
    items = [x.strip() for x in header.split(",") if x.strip()]
    if len(items) < 3:
        return [], text
    name_like = sum(1 for it in items if looks_like_name(it))
    if name_like < max(2, (len(items) + 1)//2):
        return [], text
    filtered = []
    for it in items:
        if len(it) > 40:
            return [], text
        if not re.search(r"[A-Za-zА-Яа-яЁё]", it):
            return [], text
        filtered.append("-".join(x.capitalize() for x in it.split("-")))
    if len(filtered) < 3:
        return [], text
    if "\n" in header:
        return [], text
    return filtered, rest

# -------------------------
# DOCX numbering-aware extraction
# -------------------------
W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

def _safe_find(elem: ET.Element, path: str) -> Optional[ET.Element]:
    return elem.find(path)

def _safe_findall(elem: ET.Element, path: str) -> List[ET.Element]:
    return elem.findall(path)

def _parse_numbering_xml(numbering_xml: str) -> Dict[str, Any]:
    """
    Parse numbering.xml and return:
      - numid_to_abstract: { numId -> abstractNumId }
      - abstract_levels: { abstractNumId -> { ilvl (int) -> { 'lvlText': str or None, 'numFmt': str or None, 'start': int } } }
    """
    root = ET.fromstring(numbering_xml)
    numid_to_abstract: Dict[str, str] = {}
    abstract_levels: Dict[str, Dict[int, Dict[str, Any]]] = {}

    # map numId -> abstractNumId
    for num in root.findall(f".//{W_NS}num"):
        nid = num.get(f"{{http://schemas.openxmlformats.org/wordprocessingml/2006/main}}numId")
        if not nid:
            # try child w:numId/@w:val
            nid_node = num.find(f"{W_NS}numId")
            nid = nid_node.get(f"{{http://schemas.openxmlformats.org/wordprocessingml/2006/main}}val") if nid_node is not None else None
        abs_elem = num.find(f"{W_NS}abstractNumId")
        abs_id = abs_elem.get(f"{{http://schemas.openxmlformats.org/wordprocessingml/2006/main}}val") if abs_elem is not None else None
        if nid and abs_id:
            numid_to_abstract[nid] = abs_id

    # parse abstractNum levels
    for abs_node in root.findall(f".//{W_NS}abstractNum"):
        abs_id = abs_node.get(f"{{http://schemas.openxmlformats.org/wordprocessingml/2006/main}}abstractNumId")
        if not abs_id:
            # try attribute with different name
            abs_id = abs_node.get("abstractNumId")
        if not abs_id:
            continue
        levels = {}
        for lvl in abs_node.findall(f"{W_NS}lvl"):
            ilvl_raw = lvl.get(f"{{http://schemas.openxmlformats.org/wordprocessingml/2006/main}}ilvl")
            try:
                ilvl = int(ilvl_raw) if ilvl_raw is not None else 0
            except Exception:
                ilvl = 0
            lvlText = None
            numFmt = None
            start = 1
            lt = lvl.find(f"{W_NS}lvlText")
            if lt is not None:
                lvlText = lt.get(f"{{http://schemas.openxmlformats.org/wordprocessingml/2006/main}}val") or lt.get("val")
            nf = lvl.find(f"{W_NS}numFmt")
            if nf is not None:
                numFmt = nf.get(f"{{http://schemas.openxmlformats.org/wordprocessingml/2006/main}}val") or nf.get("val")
            st = lvl.find(f"{W_NS}start")
            if st is not None:
                try:
                    start = int(st.get(f"{{http://schemas.openxmlformats.org/wordprocessingml/2006/main}}val") or st.get("val") or "1")
                except Exception:
                    start = 1
            levels[ilvl] = {"lvlText": lvlText, "numFmt": numFmt, "start": start}
        abstract_levels[abs_id] = levels

    return {"numid_to_abstract": numid_to_abstract, "abstract_levels": abstract_levels}

def _compute_number_label_for_para(numid_to_abstract: Dict[str,str], abstract_levels: Dict[str, Dict[int, Dict[str,Any]]], numId: str, ilvl: int, counters_by_num: DefaultDict[str, List[int]]) -> str:
    """
    Update counters_by_num[numId] per ilvl and return label string.
    """
    # ensure counters list long enough
    arr = counters_by_num[numId]
    if len(arr) < MAX_NUMBERING_LEVELS:
        # extend
        arr.extend([0] * (MAX_NUMBERING_LEVELS - len(arr)))
    # increment this level, reset deeper
    arr[ilvl] += 1
    for k in range(ilvl+1, MAX_NUMBERING_LEVELS):
        arr[k] = 0
    # determine template
    abstract = numid_to_abstract.get(numId)
    tpl = None
    if abstract:
        levels = abstract_levels.get(abstract, {})
        lvl_info = levels.get(ilvl)
        if lvl_info:
            tpl = lvl_info.get("lvlText")
    # If template exists, replace %1, %2 etc.
    if tpl:
        def repl(m):
            idx = int(m.group(1)) - 1
            val = arr[idx] if 0 <= idx < len(arr) else 0
            return str(val)
        label = re.sub(r"%(\d+)", repl, tpl)
        # make sure label ends with space
        label = label.strip()
        if not label.endswith((".", ":", "-", "—")):
            label = label + " "
        else:
            label = label + " "
        return label
    # fallback: join levels up to ilvl with '.'
    parts = [str(arr[k]) for k in range(0, ilvl+1) if arr[k] > 0]
    if not parts:
        return ""
    label = ".".join(parts) + ". "
    return label

def extract_docx_lines(path: str) -> List[Dict[str, Union[str, bool]]]:
    """
    Return a list of dicts: {"text": ..., "highlight": True|False}
    Reconstructs numbering labels from numbering.xml when present.
    """
    _lazy_imports()
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    # Read document.xml
    with zipfile.ZipFile(path) as zf:
        if 'word/document.xml' not in zf.namelist():
            raise RuntimeError("Invalid docx: missing word/document.xml")
        doc_xml = zf.read('word/document.xml').decode('utf-8')
        numbering_xml = None
        if 'word/numbering.xml' in zf.namelist():
            numbering_xml = zf.read('word/numbering.xml').decode('utf-8')
    # parse numbering if available
    numid_to_abstract = {}
    abstract_levels = {}
    if numbering_xml:
        try:
            parsed = _parse_numbering_xml(numbering_xml)
            numid_to_abstract = parsed.get("numid_to_abstract", {})
            abstract_levels = parsed.get("abstract_levels", {})
        except Exception:
            numid_to_abstract = {}
            abstract_levels = {}
    # Build paragraph XML list
    root = ET.fromstring(doc_xml)
    # Find all w:p elements in order
    paras = root.findall(f".//{W_NS}p")
    out: List[Dict[str, Union[str, bool]]] = []
    # counters per numId to compute numbering sequences
    counters_by_num: DefaultDict[str, List[int]] = collections.defaultdict(lambda: [0]*MAX_NUMBERING_LEVELS)

    for p in paras:
        # Gather all text nodes inside <w:p>
        texts = []
        for t in p.findall(f".//{W_NS}t"):
            if t.text:
                texts.append(t.text)
        para_text = "".join(texts).replace("\r", " ").strip()
        # detect highlight (shading) inside runs in this paragraph
        highlight = False
        # If any w:shd with w:fill attribute is present in this <w:p>, flag highlight
        if re.search(r'<w:shd[^>]*w:fill="[^"]+"', ET.tostring(p, encoding='unicode'), flags=re.IGNORECASE):
            # ensure fill isn't empty
            if re.search(r'<w:shd[^>]*w:fill="([^"]+)"', ET.tostring(p, encoding='unicode'), flags=re.IGNORECASE):
                highlight = True
        # detect numbering (w:numPr)
        numPr = p.find(f"{W_NS}pPr/{W_NS}numPr")
        label_prefix = ""
        if numPr is not None:
            # find numId and ilvl
            numIdElem = numPr.find(f"{W_NS}numId")
            ilvlElem = numPr.find(f"{W_NS}ilvl")
            numId = None
            ilvl = 0
            if numIdElem is not None:
                numId = numIdElem.get(f"{{http://schemas.openxmlformats.org/wordprocessingml/2006/main}}val") or numIdElem.get("val") or numIdElem.text
            if ilvlElem is not None:
                try:
                    ilvl = int(ilvlElem.get(f"{{http://schemas.openxmlformats.org/wordprocessingml/2006/main}}val") or ilvlElem.get("val") or ilvlElem.text or "0")
                except Exception:
                    ilvl = 0
            if numId:
                try:
                    label_prefix = _compute_number_label_for_para(numid_to_abstract, abstract_levels, str(numId), ilvl, counters_by_num)
                except Exception:
                    label_prefix = ""
        # If paragraph text empty but numbering label present, still keep label
        final_text = (label_prefix + para_text).strip()
        out.append({"text": final_text, "highlight": bool(highlight)})
    # If python-docx (Document) exists, we may prefer its paragraph order/text for robustness:
    # But keep numbering computed above because python-docx does not expose it normally.
    # For now we return out as computed.
    return out

# -------------------------
# PDF extraction + OCR fallback (unchanged)
# -------------------------
def _ocr_image_to_text(img) -> str:
    reader = _get_easyocr_reader()
    res = reader.readtext(img, detail=1, paragraph=False)
    if not res:
        return ""
    items = []
    for bbox, text, conf in res:
        if not text:
            continue
        ys = [pt[1] for pt in bbox]
        xs = [pt[0] for pt in bbox]
        y = sum(ys) / len(ys)
        x = min(xs)
        items.append((y, x, text))
    items.sort(key=lambda t: (round(t[0] / 8), t[1]))
    lines = []
    cur_bucket = None
    buf = []
    for y, x, text in items:
        b = int(round(y / 8))
        if cur_bucket is None:
            cur_bucket = b
            buf = [text]
        elif b == cur_bucket:
            buf.append(text)
        else:
            lines.append(" ".join(buf))
            cur_bucket = b
            buf = [text]
    if buf:
        lines.append(" ".join(buf))
    return "\n".join(lines)

def extract_pdf_pages(path: str) -> List[str]:
    _lazy_imports()
    if _fitz:
        try:
            doc = _fitz.open(path)
            pages = [page.get_text("text") or "" for page in doc]
            if any(p.strip() for p in pages):
                return pages
        except Exception:
            pass
    if _pdfplumber:
        try:
            pages = []
            with _pdfplumber.open(path) as pdf:
                for p in pdf.pages:
                    pages.append(p.extract_text() or "")
            if any(p.strip() for p in pages):
                return pages
        except Exception:
            pass
    if PdfReader:
        try:
            try:
                r = PdfReader(path)
            except TypeError:
                with open(path, "rb") as f:
                    r = PdfReader(f)
            pages = []
            for p in getattr(r, "pages", []):
                try:
                    pages.append(p.extract_text() or "")
                except Exception:
                    pages.append("")
            if any(p.strip() for p in pages):
                return pages
        except Exception:
            pass
    _lazy_imports()
    if not _fitz or not Image:
        raise RuntimeError(
            "Text extraction failed and OCR fallback unavailable. Install PyMuPDF + Pillow + easyocr."
        )
    try:
        doc = _fitz.open(path)
        zoom = _fitz.Matrix(2, 2)
        pages = []
        for page in doc:
            pm = page.get_pixmap(matrix=zoom, alpha=False)
            img = Image.frombytes("RGB", (pm.width, pm.height), pm.samples)
            pages.append(_ocr_image_to_text(img) or "")
        return pages
    except Exception as e:
        raise RuntimeError(f"OCR fallback failed: {e}") from e

# -------------------------
# helpers (header/footer cleaning, columns)
# -------------------------
def _detect_repeated_lines_across_pages(pages: List[str], min_pages_ratio: float = 0.4) -> List[str]:
    normalized_lines_per_page = []
    for p in pages:
        lines = [normalize_text(l) for l in p.splitlines() if normalize_text(l)]
        normalized_lines_per_page.append(set(lines))
    freq = collections.Counter()
    for s in normalized_lines_per_page:
        for line in s:
            if len(line) < 120:
                freq[line] += 1
    threshold = max(1, int(len(pages) * min_pages_ratio))
    repeated = [line for line, cnt in freq.items() if cnt >= threshold]
    filtered = [l for l in repeated if not FOOTER_HEADER_CLEAN_RE.match(l)]
    return filtered

def _clean_headers_footers_from_pages(pages: List[str], verbose_logs: Optional[List[str]] = None) -> List[str]:
    repeated = _detect_repeated_lines_across_pages(pages)
    if verbose_logs is not None:
        verbose_logs.append(f"Detected {len(repeated)} repeated header/footer candidates")
    cleaned_pages = []
    for p in pages:
        lines = p.splitlines()
        new_lines = []
        for ln in lines:
            n = normalize_text(ln)
            if not n:
                continue
            if any(n == r or n.startswith(r + " ") or r.startswith(n + " ") for r in repeated):
                continue
            if PAGE_NUM_RE.match(n):
                continue
            new_lines.append(ln)
        cleaned_pages.append("\n".join(new_lines))
    return cleaned_pages

def _column_choose_most_likely_column(line: str) -> str:
    if '\t' in line:
        parts = [p.strip() for p in line.split('\t') if p.strip()]
        if parts:
            return parts[-1]
    if re.search(r'\s{3,}', line):
        parts = [p.strip() for p in re.split(r'\s{3,}', line) if p.strip()]
        if parts:
            return parts[-1]
    if '|' in line:
        parts = [p.strip() for p in line.split('|') if p.strip()]
        if parts:
            return parts[-1]
    return line

# -------------------------
# segmentation helpers (identical logic retained, highlight-aware)
# -------------------------
def _strip_timecode_prefix(text: str) -> str:
    return TIME_PREFIX_RE.sub("", text, count=1)

def _split_sentences(text: str) -> List[str]:
    if not text:
        return []
    parts = [s.strip() for s in SENT_SPLIT.split(text) if s.strip()]
    if not parts:
        return [text.strip()]
    return parts

def _is_probable_cue(line: str) -> bool:
    s = (line or "").strip()
    if not s:
        return False
    if re.match(r'^[A-ZА-ЯЁ][a-zа-яё]+(?:\s+[A-ZА-ЯЁ][a-zа-яё]+)?\:??$', s):
        return True
    if re.search(r'[a-zа-яё]', s) and s.upper() != s:
        if s.endswith(":") and len(s.split()) <= 3:
            return True
        return False
    if "," in s:
        return False
    if not CHAR_CUE_HARD_RE.match(s):
        return False
    words = [w for w in s.split() if w]
    if not (1 <= len(words) <= 4):
        return False
    if len(s) > 60:
        return False
    if words and words[0] in {"С", "И", "А", "НА", "В", "ВО", "О", "ОТ", "ДО"}:
        return False
    if not re.search(r'[A-ZА-ЯЁ]', s):
        return False
    return True

def _ends_open(prev_text: str) -> bool:
    if not prev_text:
        return True
    st = prev_text.rstrip()
    if not st:
        return True
    if re.search(r'[\.!\?…:]$', st):
        return False
    if DASH_END_RE.search(st):
        return True
    if re.search(r'[,;]\s*$', st):
        return True
    return True

def _is_parenthetical(text: str) -> bool:
    t = (text or "").strip()
    return t.startswith("(") and len(t) > 1

def _is_short_parenthetical(text: str) -> bool:
    t = (text or "").strip()
    return _is_parenthetical(t) and len(t) <= 60

def _merge_action_blocks(blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not blocks:
        return blocks
    merged: List[Dict[str, Any]] = []
    buf: Optional[Dict[str, Any]] = None
    for b in blocks:
        if b["type"] != "action":
            if buf:
                merged.append(buf)
                buf = None
            merged.append(b)
            continue
        if buf is None:
            buf = b.copy()
            continue
        prev = buf["text"]
        curr = b["text"]
        cond = (
            _ends_open(prev)
            or _is_parenthetical(curr)
            or _is_short_parenthetical(curr)
            or (curr and (curr[0].islower() or COMMON_LOWER_START.match(curr)))
            or UPPER_COMMA_CONT_RE.match(curr)
        )
        if cond:
            if DASH_END_RE.search(prev.rstrip()):
                prev = re.sub(DASH_END_RE, "", prev).rstrip()
                buf["text"] = prev
            buf["text"] = (buf["text"].rstrip() + " " + curr.lstrip()).strip()
        else:
            merged.append(buf)
            buf = b.copy()
    if buf:
        merged.append(buf)
    for m in merged:
        if m["type"] == "action":
            m["text"] = re.sub(r"\s{2,}", " ", m["text"]).strip()
            if m["text"].endswith('-') and not re.search(r'\w-\Z', m["text"]):
                m["text"] = m["text"][:-1].rstrip()
    return merged

def _is_slug(line: str) -> Optional[dict]:
    txt = line.strip()
    if not txt:
        return None
    m = SLUG_RE.match(txt)
    if m:
        gd = m.groupdict()
        if not gd.get("num") and not re.match(rf"^{IE_TOK}\b", txt, re.IGNORECASE):
            return None
        rest = gd.get("rest") or ""
        if rest and COMMON_LOWER_START.match(rest.strip()):
            return None
        rm = REST_TIME_RE.match(rest.strip())
        loc = tod = shoot_day = timecode = ""
        if rm:
            loc = (rm.group("loc") or "").strip(" .\t")
            tod = (rm.group("tod") or "").upper()
            shoot_day = (rm.group("shoot_day") or "")
            timecode = (rm.group("timecode") or "")
        if not (loc or tod or shoot_day or timecode):
            rest_up = (rest or "").upper()
            if rest_up and re.search(r'\b(INT|ИНТ|EXT|ЭКСТ|NAT|НАТ|ДЕНЬ|НОЧЬ|УТРО|ВЕЧЕР)\b', rest_up):
                loc = rest.strip()
        if not loc and not tod and not shoot_day and not timecode:
            return None
        ie = re.sub(r"\s*/\s*", "/", (gd.get("ie") or "").upper()).rstrip(".")
        return {
            "raw": txt,
            "number": gd.get("num") or "",
            "number_suffix": (gd.get("num_suffix") or "").strip(),
            "ie": ie,
            "location": loc,
            "time_of_day": tod,
            "shoot_day": shoot_day,
            "timecode": timecode,
            "removed": bool(gd.get("removed"))
        }
    if re.match(rf"^\s*{IE_TOK}\b", txt, re.IGNORECASE):
        rest = re.sub(rf"^\s*{IE_TOK}\b\.?\s*", "", txt, flags=re.IGNORECASE).strip()
        rm = REST_TIME_RE.match(rest)
        loc = tod = shoot_day = timecode = ""
        if rm:
            loc = (rm.group("loc") or "").strip(" .\t")
            tod = (rm.group("tod") or "").upper()
            shoot_day = (rm.group("shoot_day") or "")
            timecode = (rm.group("timecode") or "")
        if not (loc or tod or shoot_day or timecode):
            if rest and not COMMON_LOWER_START.match(rest):
                loc = rest
        if loc or tod or shoot_day or timecode:
            ie = re.match(rf"^\s*{IE_TOK}\b", txt, re.IGNORECASE).group(0).upper()
            ie = re.sub(r"\s*/\s*", "/", ie).rstrip(".")
            return {
                "raw": txt,
                "number": "",
                "number_suffix": "",
                "ie": ie,
                "location": loc,
                "time_of_day": tod,
                "shoot_day": shoot_day,
                "timecode": timecode,
                "removed": False
            }
    return None

def _try_join_slug_wrapped(lines: List[Union[str, Dict[str,Any]]], i: int) -> Optional[Tuple[str, int]]:
    def get_text(idx):
        ln = lines[idx]
        if isinstance(ln, dict):
            return ln.get("text","")
        return ln
    head = get_text(i).rstrip()
    if SLUG_HEAD_RE.match(head):
        for extra in range(1, 4):
            if i + extra < len(lines):
                cand = head
                for k in range(1, extra + 1):
                    cand = (cand + " " + get_text(i + k).lstrip()).strip()
                if _is_slug(cand):
                    return cand, extra
    for extra in range(1, 4):
        if i + extra < len(lines):
            cand = get_text(i).rstrip()
            for k in range(1, extra + 1):
                cand = (cand + " " + get_text(i + k).lstrip()).strip()
            if _is_slug(cand):
                return cand, extra
    return None

def _finalize_scene(scene: Dict[str, Any], verbose_logs: Optional[List[str]] = None) -> Dict[str, Any]:
    scene["blocks"] = _merge_action_blocks(scene.get("blocks", []))
    if SPLIT_ACTION_BLOCKS_INTO_SENTENCES:
        new_blocks: List[Dict[str, Any]] = []
        for b in scene["blocks"]:
            if b["type"] != "action":
                new_blocks.append(b)
                continue
            sents = _split_sentences(b["text"])
            if len(sents) <= 1:
                new_blocks.append(b)
            else:
                for s in sents:
                    new_blocks.append({"type": "action", "text": s, "line_no": b.get("line_no")})
        scene["blocks"] = new_blocks
    sentences: List[Dict[str, Any]] = []
    for b in scene.get("blocks", []):
        if b["type"] == "action":
            for s in _split_sentences(b["text"]):
                sentences.append({"text": s, "kind": "action", "speaker": None, "line_no": b.get("line_no")})
        elif b["type"] == "dialogue":
            parts = _split_sentences(b["text"]) or [b["text"]]
            for s in parts:
                sentences.append({"text": s, "kind": "dialogue", "speaker": b.get("speaker"), "line_no": b.get("line_no")})
    scene["sentences"] = sentences
    scene["meta"] = scene.get("meta", {})
    scene["meta"].setdefault("char_count", sum(len(b.get("text","")) for b in scene.get("blocks", [])))
    scene["meta"].setdefault("block_count", len(scene.get("blocks", [])))
    if scene.get("meta") is not None:
        scene["meta"].setdefault("verbose", VERBOSE)
    return scene

# -------------------------
# Core segmentation (uses highlight-aware docx extraction)
# -------------------------
def segment_lines_to_scenes(lines: List[Union[str, Dict[str,Any]]], skip_removed: bool = True, verbose: bool = False) -> List[Dict[str, Any]]:
    """
    lines: list of either strings (from PDF parsing) or dicts {"text":..., "highlight":bool} (from DOCX)
    """
    logs: List[str] = [] if verbose else None

    def get_text(idx):
        ln = lines[idx]
        if isinstance(ln, dict):
            return normalize_text(ln.get("text",""))
        return normalize_text(ln or "")

    def get_highlight(idx):
        ln = lines[idx]
        if isinstance(ln, dict):
            return bool(ln.get("highlight", False))
        return False

    # Preprocess: normalize & basic column choice, but DO NOT strip numbering prefix:
    norm: List[Union[str, Dict[str,Any]]] = []
    for idx, ln in enumerate(lines):
        if isinstance(ln, dict):
            txt = normalize_text(ln.get("text","") or "")
            highlight = bool(ln.get("highlight", False))
            txt = _column_choose_most_likely_column(txt)
            norm.append({"text": txt, "highlight": highlight})
        else:
            txt = normalize_text(ln or "")
            txt = _column_choose_most_likely_column(txt)
            norm.append(txt)

    # collapse blanks
    collapsed: List[Union[str, Dict[str,Any]]] = []
    prev_blank = False
    for ln in norm:
        txt = ln["text"] if isinstance(ln, dict) else ln
        if not txt:
            if not prev_blank:
                collapsed.append("" if isinstance(ln, str) else {"text":"", "highlight": ln.get("highlight", False) if isinstance(ln, dict) else False})
            prev_blank = True
        else:
            collapsed.append(ln)
            prev_blank = False
    norm = collapsed

    scenes: List[Dict[str, Any]] = []
    cur: Optional[Dict[str, Any]] = None
    cur_speaker: Optional[str] = None
    cur_dialogue_buf: List[str] = []

    def close_dialogue():
        nonlocal cur_speaker, cur_dialogue_buf, cur
        if cur:
            text = " ".join(t.strip() for t in cur_dialogue_buf if t.strip())
            if cur_speaker and text:
                cur["blocks"].append({"type": "dialogue", "speaker": cur_speaker, "text": text, "line_no": None})
        cur_speaker = None
        cur_dialogue_buf = []

    i = 0
    n = len(norm)
    while i < n:
        ln = norm[i]
        line = ln["text"] if isinstance(ln, dict) else ln
        if not line:
            close_dialogue()
            i += 1
            continue

        # Try slug on current raw (numbering prefix preserved if present)
        slug = _is_slug(line)
        if not slug:
            joined = _try_join_slug_wrapped(norm, i)
            if joined:
                jline, extra = joined
                slug = _is_slug(jline)
                if slug:
                    i += extra

        if slug:
            close_dialogue()
            if slug["removed"] and skip_removed:
                cur = None
                i += 1
                continue
            if cur is not None:
                _finalize_scene(cur, logs)
                scenes.append(cur)
            cur = {
                "heading": slug["raw"],
                "number": slug["number"],
                "number_suffix": slug["number_suffix"],
                "ie": slug["ie"],
                "location": slug["location"],
                "time_of_day": slug["time_of_day"],
                "shoot_day": slug["shoot_day"],
                "timecode": slug["timecode"],
                "removed": slug["removed"],
                "blocks": [],
                "cast_list": [],
                "meta": {"start_line": i+1}
            }
            i += 1
            continue

        if cur is None:
            if re.match(rf"^\s*{IE_TOK}\b", line, re.IGNORECASE):
                fake_slug = _is_slug(line) or {"raw": line, "number": "", "number_suffix": "", "ie": line.split()[0].upper(), "location": "", "time_of_day": "", "shoot_day": "", "timecode": "", "removed": False}
                cur = {
                    "heading": fake_slug["raw"],
                    "number": fake_slug["number"],
                    "number_suffix": fake_slug["number_suffix"],
                    "ie": fake_slug["ie"],
                    "location": fake_slug["location"],
                    "time_of_day": fake_slug["time_of_day"],
                    "shoot_day": fake_slug["shoot_day"],
                    "timecode": fake_slug["timecode"],
                    "removed": fake_slug["removed"],
                    "blocks": [],
                    "cast_list": [],
                    "meta": {"implicit": True, "start_line": i+1}
                }
                i += 1
                continue
            i += 1
            continue

        # Vertical cast block detection ignoring highlighted lines as candidates
        j = i
        names_block = []
        while j < n and ( (norm[j]["text"] if isinstance(norm[j], dict) else norm[j]).strip() ) and len(names_block) < MAX_VERTICAL_CAST_LINES:
            candidate = norm[j]["text"] if isinstance(norm[j], dict) else norm[j]
            candidate_highlight = get_highlight(j)
            if candidate_highlight:
                break
            if (re.match(r'^[A-ZА-ЯЁ][A-ZА-ЯЁ\-\s\.]+$', candidate) and not re.search(r'[0-9;:!?]', candidate)) \
               or (len(candidate.split()) <= 3 and not re.search(r'[0-9;:!?\.]', candidate) and candidate.istitle()):
                if len(candidate) <= MAX_LINE_LEN_FOR_NAME:
                    names_block.append(candidate)
                    j += 1
                    continue
            break
        if len(names_block) >= MIN_LINES_FOR_VERTICAL_CAST:
            close_dialogue()
            if sum(1 for x in names_block if looks_like_name(x)) >= 1:
                cur.setdefault("cast_list", []).append({"text": ", ".join(n.strip() for n in names_block), "line_no": i+1})
            else:
                cur["blocks"].append({"type":"action","text": " ".join(names_block), "line_no": i+1})
            i = j
            continue

        # standalone cast header (ignore if highlighted)
        highlight_here = get_highlight(i)
        cast_names = _is_cast_header_line(line, highlight=highlight_here)
        if cast_names:
            close_dialogue()
            cur.setdefault("cast_list", []).append({"text": ", ".join(cast_names), "line_no": i + 1})
            i += 1
            continue

        # legacy uppercase cast line (skip if highlighted)
        if not highlight_here and re.search(r'[A-ZА-ЯЁ].*,.*[A-ZА-ЯЁ]', line) and line.strip().upper() == line.strip():
            close_dialogue()
            parts = [p.strip() for p in line.split(",") if p.strip()]
            if sum(1 for p in parts if looks_like_name(p)) >= 1:
                cur.setdefault("cast_list", []).append({"text": line.strip(), "line_no": i+1})
            else:
                cur["blocks"].append({"type":"action","text": line, "line_no": i+1})
            i += 1
            continue

        # Dialogue cue
        if _is_probable_cue(line):
            close_dialogue()
            sp = line.strip().rstrip(":")
            cur_speaker = sp
            cur_dialogue_buf = []
            i += 1
            continue

        # inline "Name + rest"
        m_name_rest = re.match(r'^([A-ZА-ЯЁ][a-zа-яё\-]+(?:\s+[A-ZА-ЯЁ][a-zа-яё\-]+)?)\s+(.+)$', line)
        if m_name_rest:
            maybe_name, rest = m_name_rest.group(1), m_name_rest.group(2)
            if looks_like_name(maybe_name):
                close_dialogue()
                if rest and (rest[0].isupper() or rest[0] in ['"', '«', '—', '-']):
                    cur_speaker = maybe_name
                    cur_dialogue_buf = [rest]
                    i += 1
                    continue
                cur["blocks"].append({"type":"action","text": line, "line_no": i+1})
                i += 1
                continue

        if cur_speaker:
            cur_dialogue_buf.append(line)
            i += 1
            continue

        # Action: also support inline cast+action (skip if highlighted)
        action_text = _strip_timecode_prefix(line).strip()
        if action_text:
            names_inline, rest = _extract_cast_header_and_action(action_text)
            inline_highlight = get_highlight(i)
            if names_inline and not inline_highlight and sum(1 for n in names_inline if looks_like_name(n)) >= 1:
                cur.setdefault("cast_list", []).append({"text": ", ".join(names_inline), "line_no": i + 1})
                action_text = rest
        if action_text:
            cur["blocks"].append({"type": "action", "text": action_text, "line_no": i + 1})
        i += 1

        # safety split if scene becomes extremely large
        if cur and sum(len(b.get("text","")) for b in cur.get("blocks", [])) > MAX_SCENE_CHARS_BEFORE_FORCED_SPLIT:
            combined = "\n".join(b.get("text","") for b in cur.get("blocks", []))
            internal_lines = [ln for ln in combined.splitlines() if ln.strip()]
            split_found = False
            for idx, candidate in enumerate(internal_lines):
                if re.match(rf"^\s*{IE_TOK}\b", candidate, re.IGNORECASE) and idx > 2:
                    cut_text = "\n".join(internal_lines[:idx])
                    rest_text = "\n".join(internal_lines[idx:])
                    cur["blocks"] = [{"type":"action","text":cut_text,"line_no":cur["blocks"][0].get("line_no") if cur["blocks"] else None}]
                    _finalize_scene(cur, logs)
                    scenes.append(cur)
                    cur = {
                        "heading": candidate.strip(),
                        "number": "",
                        "number_suffix": "",
                        "ie": candidate.strip().split()[0].upper(),
                        "location": "",
                        "time_of_day": "",
                        "shoot_day": "",
                        "timecode": "",
                        "removed": False,
                        "blocks": [{"type":"action","text":rest_text,"line_no": None}],
                        "cast_list": [],
                        "meta": {"forced_split": True}
                    }
                    split_found = True
                    break
            if split_found:
                pass

    close_dialogue()
    if cur is not None:
        _finalize_scene(cur, logs)
        scenes.append(cur)

    # fallback: split by IE tokens if nothing found
    if not scenes:
        if verbose:
            logs.append("No scenes detected by primary pass — applying fallback split by IE tokens.")
        cur = None
        for idx, ln in enumerate(norm):
            line = ln["text"] if isinstance(ln, dict) else ln
            if re.search(rf"\b{IE_TOK}\b", line, re.IGNORECASE):
                if cur:
                    _finalize_scene(cur, logs)
                    scenes.append(cur)
                cur = {
                    "heading": line.strip(),
                    "number": "",
                    "number_suffix": "",
                    "ie": line.strip().split()[0].upper(),
                    "location": "",
                    "time_of_day": "",
                    "shoot_day": "",
                    "timecode": "",
                    "removed": False,
                    "blocks": [],
                    "cast_list": [],
                    "meta": {"fallback_split": True, "start_line": idx+1}
                }
                continue
            if cur is None:
                continue
            cur["blocks"].append({"type":"action","text":line,"line_no": idx+1})
        if cur:
            _finalize_scene(cur, logs)
            scenes.append(cur)

    if verbose and logs is not None:
        summary = {"scene_count": len(scenes), "lines_processed": len(lines)}
        for s in scenes:
            s.setdefault("meta", {}).setdefault("logs", []).append(f"PARSE_SUMMARY: {summary}")
    return scenes

# -------------------------
# page-level parse helpers
# -------------------------
def parse_pages_to_scenes(pages: List[str], verbose: bool = False) -> List[Dict[str, Any]]:
    verbose_logs: List[str] = [] if verbose else None
    try:
        cleaned_pages = _clean_headers_footers_from_pages(pages, verbose_logs)
    except Exception:
        cleaned_pages = pages
    lines: List[Union[str, Dict[str,Any]]] = []
    for p in cleaned_pages:
        pnorm = normalize_text(p or "")
        if pnorm:
            lines.extend(pnorm.splitlines())
        lines.append("")
    scenes = segment_lines_to_scenes(lines, skip_removed=True, verbose=verbose)
    return scenes

def parse_file_to_scenes(path: str, verbose: bool = False) -> List[Dict[str, Any]]:
    ext = os.path.splitext(path or "")[1].lower()
    if ext == ".pdf":
        pages = extract_pdf_pages(path)
        return parse_pages_to_scenes(pages, verbose=verbose)
    if ext == ".docx":
        doc_lines = extract_docx_lines(path)  # list of dicts {"text","highlight"}
        return segment_lines_to_scenes(doc_lines, skip_removed=True, verbose=verbose)
    if ext == ".json":
        import json as _json
        with open(path, "r", encoding="utf-8") as f:
            data = _json.load(f)
        if isinstance(data, list) and data and isinstance(data[0], dict) and "heading" in data[0]:
            return data
        raise ValueError("JSON is not a scene array with 'heading'.")
    raise ValueError(f"Unsupported extension: {ext} (use .pdf/.docx/.json)")

# -------------------------
# CLI runner
# -------------------------
if __name__ == "__main__":
    import argparse, json, sys
    p = argparse.ArgumentParser(description="Numbering-aware screenplay parser")
    p.add_argument("--file", default="C:/Users/Mitya/Downloads/Трек 3 - тестовый образец.docx",help="Path to .pdf/.docx/.json screenplay")
    p.add_argument("--verbose", action="store_true", help="Include verbose logs")
    p.add_argument("--out", default='gpt/v9/sc.json', help="Output JSON path (optional)")
    args = p.parse_args()
    try:
        scenes = parse_file_to_scenes(args.file, verbose=args.verbose)
        if args.out:
            with open(args.out, "w", encoding="utf-8") as f:
                json.dump(scenes, f, ensure_ascii=False, indent=2)
            print(f"Wrote {len(scenes)} scenes to {args.out}")
        else:
            print(f"Parsed {len(scenes)} scenes.")
            if scenes:
                print("First scene heading:", scenes[0].get("heading"))
                print("Last scene heading:", scenes[-1].get("heading"))
    except Exception as e:
        print("Error:", e)
        sys.exit(2)
