"""
Extra Google Custom Search queries for public information about a *person* (biography + social URLs).
Uses only the same GOOGLE_CUSTOM_SEARCH_* credentials as the rest of the app.
"""
from __future__ import annotations

import logging
import re
from typing import Any, List, Optional

logger = logging.getLogger(__name__)

# Names / phrases that are not individual people lookups
_NAME_BLOCKLIST = frozenset(
    {
        "python",
        "javascript",
        "java",
        "rust",
        "golang",
        "asyncio",
        "kubernetes",
        "docker",
        "react",
        "vue",
        "angular",
        "node",
        "nodejs",
        "typescript",
        "html",
        "css",
        "sql",
        "openai",
        "chatgpt",
        "machine learning",
        "deep learning",
        "artificial intelligence",
        "the company",
        "this company",
        "our company",
        "stock market",
        "the stock",
        "your app",
        "this app",
    }
)


def is_person_information_intent(message: str) -> bool:
    """User wants public info / profiles about an individual (not role-of-office at a company)."""
    low = (message or "").lower().strip()
    if len(low) < 8:
        return False
    if re.search(
        r"\b(information|details|info|data|background)\s+(about|on|regarding)\s+\S",
        low,
    ):
        return True
    if re.search(r"\btell\s+me\s+about\s+\S", low) and not re.search(
        r"\btell\s+me\s+about\s+the\s+company\b", low
    ):
        return True
    if re.search(r"\bwhat\s+do\s+you\s+know\s+about\s+\S", low):
        return True
    if re.search(r"\blookup\s+\S", low):
        return True
    if re.search(r"\bfind\s+(?:information|details|info)\s+(?:about|on)\s+\S", low):
        return True
    if re.search(r"\bsearch\s+for\s+\S", low):
        return True
    if re.search(r"\banything\s+on\s+\S", low):
        return True
    if re.search(r"\bprofile\s+(?:for|of)\s+\S", low):
        return True
    m = re.search(r"\bwho\s+is\s+(.+?)\s*[?.!]?\s*$", low)
    if m:
        rest = m.group(1).strip()
        if re.match(
            r"the\s+(current\s+)?(ceo|c\.e\.o\.|chief\s+executive|president|prime\s+minister|chairman)\s+of\b",
            rest,
        ):
            return False
        return True
    return False


def _normalize_candidate(raw: str) -> Optional[str]:
    s = (raw or "").strip().strip('?!.,;:"\'')
    s = re.sub(r"^(the|a|an)\s+", "", s, flags=re.I)
    s = re.sub(r"\s+", " ", s)
    if len(s) < 3 or len(s) > 90:
        return None
    low = s.lower()
    if low in _NAME_BLOCKLIST:
        return None
    if any(low == b or low.startswith(b + " ") for b in _NAME_BLOCKLIST if len(b) > 4):
        return None
    if re.match(
        r"^(python|java|javascript|typescript|rust|golang|react|node|kubernetes|docker|html|css|sql)\b",
        low,
    ):
        return None
    return s


def extract_person_search_name(
    user_message: str,
    topic: Optional[str],
    history: Any,
) -> Optional[str]:
    """Best-effort person name for site-targeted searches."""
    msg = (user_message or "").strip()

    for q in re.findall(r'"([^"]{2,80})"', msg):
        cand = _normalize_candidate(q)
        if cand and " " in cand:
            return cand

    patterns = (
        r"(?:information|details|info|background)\s+(?:about|on|regarding)\s+([A-Za-z][^?.\n]{2,80}?)(?:\s*[?.]|$)",
        r"\btell\s+me\s+about\s+([A-Za-z][^?.\n]{2,80}?)(?:\s*[?.]|$)",
        r"\bwhat\s+do\s+you\s+know\s+about\s+([A-Za-z][^?.\n]{2,80}?)(?:\s*[?.]|$)",
        r"\blookup\s+([A-Za-z][^?.\n]{2,80}?)(?:\s*[?.]|$)",
        r"\bfind\s+(?:information|details|info)\s+(?:about|on)\s+([A-Za-z][^?.\n]{2,80}?)(?:\s*[?.]|$)",
        r"\bsearch\s+for\s+([A-Za-z][^?.\n]{2,80}?)(?:\s*[?.]|$)",
        r"\bprofile\s+(?:for|of)\s+([A-Za-z][^?.\n]{2,80}?)(?:\s*[?.]|$)",
        r"\bwho\s+is\s+(?!the\s)([A-Z][^?.\n]{2,80}?)(?:\s*[?.]|$)",
    )
    for pat in patterns:
        m = re.search(pat, msg, re.I | re.DOTALL)
        if m:
            cand = _normalize_candidate(m.group(1))
            if cand:
                return cand

    if topic:
        t = _normalize_candidate(topic)
        if t and " " in t and not re.search(
            r"\b(inc|corp|ltd|plc|llc|technologies|systems|software|group)\b", t, re.I
        ):
            return t

    if isinstance(history, list):
        blob = ""
        for h in history[-6:]:
            if isinstance(h, dict) and h.get("content"):
                blob += " " + str(h["content"])
        m = re.search(
            r"(?:about|regarding)\s+([A-Z][a-z]+\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b",
            blob,
        )
        if m:
            cand = _normalize_candidate(m.group(1))
            if cand:
                return cand

    return None


def gather_person_profile_cse_items(name: str, max_total: int = 12) -> list:
    """Run focused Custom Search queries for public profiles + general hits."""
    from services.google_cse import google_custom_search

    name = (name or "").strip()
    if len(name) < 3:
        return []

    safe = name.replace('"', " ").strip()[:80]
    queries = [
        f'"{safe}"',
        f'"{safe}" site:linkedin.com/in',
        f'"{safe}" (site:twitter.com OR site:x.com)',
        f'"{safe}" (site:instagram.com OR site:facebook.com)',
        f'"{safe}" biography interview news',
    ]

    seen: set[str] = set()
    out: list = []
    for q in queries:
        try:
            for it in google_custom_search(q, num=4):
                u = (it.get("url") or "").strip()
                key = u or str(len(seen))
                if key in seen:
                    continue
                seen.add(key)
                out.append(it)
                if len(out) >= max_total:
                    return out
        except Exception as e:
            logger.debug("person_profile CSE query failed (%s): %s", q[:60], e)
    return out
