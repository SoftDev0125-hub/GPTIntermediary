"""
Fetch readable text from a company's official site for leadership / CEO questions.
Uses Google Custom Search (site:domain) to find IR / leadership URLs, then HTTP GET + HTML stripping.
"""
from __future__ import annotations

import logging
import os
import re
from html import unescape
from typing import Any, List, Optional
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

# Hosts to skip when picking a "corporate" homepage from generic name search
_BAD_RESULT_HOSTS = frozenset(
    {
        "wikipedia.org",
        "linkedin.com",
        "facebook.com",
        "twitter.com",
        "x.com",
        "youtube.com",
        "instagram.com",
        "reddit.com",
        "crunchbase.com",
        "bloomberg.com",
        "reuters.com",
        "sec.gov",
        "finance.yahoo.com",
        "marketwatch.com",
        "seekingalpha.com",
    }
)

_FETCH_UA = (
    "GPTIntermediary/1.0 (+https://example.local; company leadership page fetch for user chat)"
)
_MAX_FETCH_BYTES = int(os.getenv("COMPANY_SITE_MAX_FETCH_BYTES", "524288") or "524288")
_MAX_TEXT_PER_URL = int(os.getenv("COMPANY_SITE_MAX_TEXT_PER_URL", "8000") or "8000")
_MAX_TOTAL_GROUNDING = int(os.getenv("COMPANY_SITE_MAX_TOTAL_CHARS", "14000") or "14000")


def _host_bad(netloc: str) -> bool:
    h = (netloc or "").lower().split("@")[-1]
    if h.startswith("www."):
        h = h[4:]
    return any(b == h or h.endswith("." + b) for b in _BAD_RESULT_HOSTS)


def infer_company_name(user_message: str, history: Any, topic_fallback: Optional[str]) -> Optional[str]:
    """
    Best-effort company / brand name for IR lookup.
    Uses explicit patterns, optional topic from chat_server, then recent user/assistant text.
    """
    if topic_fallback:
        t = topic_fallback.strip().strip("?.!\"'")
        if 2 <= len(t) <= 72 and not re.match(
            r"^(who|what|why|how|when|where|which|news|today|headlines?|updates?)\b",
            t,
            re.I,
        ):
            if not re.search(r"\b(current|former|latest)\s+(ceo|president|news)\b", t, re.I):
                return t

    parts: List[str] = [user_message or ""]
    if isinstance(history, list):
        for msg in history[-8:]:
            if isinstance(msg, dict) and msg.get("content"):
                parts.append(str(msg["content"]))
    blob = "\n".join(parts)

    m = re.search(
        r"\b(?:ceo|chief\s+executive(?:\s+officer)?|c\.e\.o\.)\s+of\s+([A-Za-z0-9][A-Za-z0-9\s&\-\.]{1,68})",
        blob,
        re.I,
    )
    if m:
        return _clean_company_candidate(m.group(1))

    m = re.search(
        r"\b([A-Za-z0-9][A-Za-z0-9\s&\-\.]{1,68})\s+(?:ceo|\'s\s+ceo|c\.e\.o\.)\b",
        blob,
        re.I,
    )
    if m:
        return _clean_company_candidate(m.group(1))

    m = re.search(
        r"\b(?:about|for|at|from|regarding)\s+([A-Z][A-Za-z0-9&\-\s]{1,50})(?:\s*[,\.\?]|$)",
        blob,
    )
    if m:
        return _clean_company_candidate(m.group(1))

    for q in re.findall(r'"([^"]{2,72})"', blob):
        cand = _clean_company_candidate(q)
        if cand and len(cand) >= 2:
            return cand

    return None


def _clean_company_candidate(s: str) -> Optional[str]:
    s = (s or "").strip().strip("?.!\"'")
    s = re.sub(r"\s+", " ", s)
    if len(s) < 2 or len(s) > 72:
        return None
    low = s.lower()
    if re.match(r"^(the|a|an|my|our|this|that|your)\s+", low):
        s = re.sub(r"^(the|a|an|my|our|this|that|your)\s+", "", s, flags=re.I).strip()
    if not s:
        return None
    if re.search(r"^(who|what|why|how|company|corporation|content|details|information)\b", s, re.I):
        return None
    return s


def resolve_company_domain(company_name: str) -> Optional[str]:
    """Return registrable-style host (e.g. opentext.com) using a broad CSE lookup."""
    from services.google_cse import google_custom_search

    q = f'"{company_name.strip()}" official site'
    items = google_custom_search(q, num=5)
    for it in items or []:
        url = (it.get("url") or "").strip()
        if not url.startswith(("http://", "https://")):
            continue
        try:
            host = urlparse(url).netloc.lower()
            if not host or _host_bad(host):
                continue
            return host
        except Exception:
            continue
    return None


def _html_to_text(html: str) -> str:
    html = re.sub(r"<script[^>]*>[\s\S]*?</script>", " ", html, flags=re.I)
    html = re.sub(r"<style[^>]*>[\s\S]*?</style>", " ", html, flags=re.I)
    html = re.sub(r"<noscript[^>]*>[\s\S]*?</noscript>", " ", html, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", html)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def fetch_page_text(url: str) -> Optional[str]:
    if not url.startswith(("http://", "https://")):
        return None
    try:
        p = urlparse(url)
        host = (p.hostname or "").lower()
        if host in ("localhost", "127.0.0.1") or host.startswith("192.168.") or host.endswith(".local"):
            return None
    except Exception:
        return None
    try:
        r = requests.get(
            url,
            timeout=12,
            headers={"User-Agent": _FETCH_UA, "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8"},
            allow_redirects=True,
            stream=True,
        )
        if r.status_code != 200:
            return None
        raw = b""
        for chunk in r.iter_content(chunk_size=65536):
            if not chunk:
                break
            raw += chunk
            if len(raw) >= _MAX_FETCH_BYTES:
                break
        enc = r.encoding or "utf-8"
        html = raw.decode(enc, errors="replace")
        text = _html_to_text(html)
        if len(text) > _MAX_TEXT_PER_URL:
            text = text[:_MAX_TEXT_PER_URL].rsplit(" ", 1)[0] + "…"
        return text if len(text) > 80 else None
    except Exception as e:
        logger.debug("fetch_page_text failed for %s: %s", url, e)
        return None


def site_search_urls(domain: str, query: str, num: int = 5) -> List[str]:
    from services.google_cse import google_custom_search

    host = domain.strip().lower()
    if host.startswith("www."):
        host = host[4:]
    q = f"site:{host} {query}".strip()[:200]
    items = google_custom_search(q, num=num)
    out: List[str] = []
    for it in items or []:
        u = (it.get("url") or "").strip()
        if u.startswith("http") and host in urlparse(u).netloc.lower():
            out.append(u)
    return out


def build_official_leadership_grounding(user_message: str, history: Any, topic_fallback: Optional[str]) -> Optional[str]:
    """
    Returns a single system-text block with fetched on-domain excerpts for CEO / leadership questions.
    """
    name = infer_company_name(user_message, history, topic_fallback)
    if not name:
        logger.debug("company_site_fetch: could not infer company name")
        return None
    domain = resolve_company_domain(name)
    if not domain:
        logger.debug("company_site_fetch: no domain for %s", name)
        return None

    queries = [
        "CEO chief executive officer",
        "leadership executive management team",
        "investor relations officers",
    ]
    seen: set[str] = set()
    urls: List[str] = []
    for sq in queries:
        for u in site_search_urls(domain, sq, num=4):
            if u not in seen:
                seen.add(u)
                urls.append(u)
        if len(urls) >= 5:
            break

    if not urls:
        home = f"https://{domain}/"
        urls = [home]

    chunks: List[str] = []
    total = 0
    header = (
        f"Official company website excerpts (fetched over HTTP) for **{name}** (domain {domain}). "
        f"Prefer this over generic memory when describing current CEO / leadership if the text is relevant.\n\n"
    )
    total += len(header)

    for u in urls[:4]:
        txt = fetch_page_text(u)
        if not txt:
            continue
        block = f"---\nSource URL: {u}\n{txt}\n"
        if total + len(block) > _MAX_TOTAL_GROUNDING:
            remain = _MAX_TOTAL_GROUNDING - total - 50
            if remain < 400:
                break
            block = block[:remain].rsplit(" ", 1)[0] + "…\n"
        chunks.append(block)
        total += len(block)

    if not chunks:
        return None
    return header + "\n".join(chunks)
