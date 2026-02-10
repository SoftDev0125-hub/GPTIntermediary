"""
Contact resolver service
- Primary strategy: People APIs (Clearbit/Hunter) if API keys provided
- Fallback: Bing Web Search API to find candidate email addresses in public pages

Returns list of candidate dicts: {"email": ..., "source": ..., "confidence": float}

Note: This module is intentionally conservative: it does not auto-send. Caller should require confirmation before sending to inferred addresses.
"""
import os
import re
import requests
import logging
from typing import List, Optional, Dict

logger = logging.getLogger(__name__)
EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")

CLEARBIT_KEY = os.getenv('CLEARBIT_KEY') or os.getenv('CLEARBIT_API_KEY')
HUNTER_KEY = os.getenv('HUNTER_KEY') or os.getenv('HUNTER_API_KEY')
# Primary key names for Settings / .env: BING_SEARCH_API_KEY, PEOPLE_API_KEY
BING_KEY = (
    os.getenv('BING_SEARCH_API_KEY')
    or os.getenv('BING_SEARCH_KEY')
    or os.getenv('BING_API_KEY')
)
PEOPLE_API_KEY = os.getenv('PEOPLE_API_KEY') or HUNTER_KEY


def _uniq_emails(emails: List[str]) -> List[str]:
    seen = set()
    out = []
    for e in emails:
        e = e.strip().lower()
        if not e or e in seen:
            continue
        seen.add(e)
        out.append(e)
    return out


def _extract_emails_from_text(text: str) -> List[str]:
    if not text:
        return []
    return EMAIL_RE.findall(text)


def resolve_with_bing(query: str, max_results: int = 5) -> List[Dict]:
    """Use Bing Web Search API to search for pages that may include emails for the query."""
    if not BING_KEY:
        logger.info("Bing API key not configured; skipping Bing resolver")
        return []
    try:
        endpoint = 'https://api.bing.microsoft.com/v7.0/search'
        # craft query to find email addresses and the person's name/company
        q = f'"{query}" email OR contact OR "@"'
        params = {'q': q, 'count': max_results}
        headers = {'Ocp-Apim-Subscription-Key': BING_KEY}
        r = requests.get(endpoint, params=params, headers=headers, timeout=8)
        data = r.json()
        candidates = []
        # Search webPages.value items for snippet and URL
        items = data.get('webPages', {}).get('value', [])
        for it in items:
            snippet = it.get('snippet', '') or ''
            url = it.get('url') or ''
            # Extract emails from snippet first
            emails = _extract_emails_from_text(snippet)
            # If none found in snippet, try fetching the page body (best-effort)
            if not emails:
                try:
                    page = requests.get(url, timeout=6)
                    emails = _extract_emails_from_text(page.text)
                except Exception:
                    emails = []
            for e in emails:
                candidates.append({
                    'email': e,
                    'source': url,
                    'confidence': 0.6  # baseline confidence for web-extracted
                })
        # Deduplicate by email
        seen = set()
        out = []
        for c in candidates:
            e = c.get('email').lower()
            if e in seen:
                continue
            seen.add(e)
            out.append(c)
        return out
    except Exception as e:
        logger.warning(f"Bing resolver failed: {e}")
        return []


def resolve_with_people_api(name: str, company: Optional[str] = None, domain: Optional[str] = None) -> List[Dict]:
    """Use People/Email Finder API (e.g. Hunter.io) when key is present. Needs first name, last name, optional domain."""
    if not PEOPLE_API_KEY:
        return []
    try:
        parts = name.strip().split(None, 1)
        first_name = (parts[0] or '').strip()
        last_name = (parts[1] or '').strip() if len(parts) > 1 else ''
        if not first_name:
            return []
        # Hunter.io Email Finder: domain + first_name + last_name
        if domain or company:
            dom = (domain or '').strip() or (company or '').strip().lower().replace(' ', '')
            if not dom or '.' not in dom:
                return []
            url = 'https://api.hunter.io/v2/email-finder'
            params = {
                'domain': dom,
                'first_name': first_name,
                'last_name': last_name,
                'api_key': PEOPLE_API_KEY,
            }
            r = requests.get(url, params=params, timeout=8)
            data = r.json() if r.ok else {}
            if data.get('data', {}).get('email'):
                e = data['data']['email']
                return [{'email': e, 'source': 'hunter.io', 'confidence': 0.85}]
        return []
    except Exception as e:
        logger.warning(f"People API resolver error: {e}")
        return []


def resolve_with_clearbit(name: str, company: Optional[str] = None) -> List[Dict]:
    """Attempt to use Clearbit (Prospector/Person) if key present. This is a lightweight attempt and may not be available.
    Implementation uses Clearbit's Person API when an email is known; otherwise this is a placeholder for integration.
    """
    if not CLEARBIT_KEY:
        return []
    # Clearbit Prospector requires a paid plan; we make a conservative best-effort call to the Enrichment endpoint only when possible
    try:
        # If company provided, attempt a domain-based search using company name heuristics
        if company:
            # No official public person search without paid Prospector - skip
            return []
        return []
    except Exception as e:
        logger.warning(f"Clearbit resolver error: {e}")
        return []


def resolve_name_to_emails(query: str, company: Optional[str] = None, max_results: int = 5) -> List[Dict]:
    """Main resolver entrypoint. Returns list of candidate dicts sorted by descending confidence."""
    q = query.strip()
    if not q:
        return []

    candidates = []

    # 1) People APIs (Clearbit/Hunter) - reserved for when keys present
    try:
        if CLEARBIT_KEY:
            cb = resolve_with_clearbit(q, company=company)
            candidates.extend(cb)
    except Exception:
        pass

    # 2) People API (Hunter.io etc.) when domain/company known
    try:
        people = resolve_with_people_api(q, company=company)
        candidates.extend(people)
    except Exception:
        pass

    # 3) Bing Web Search
    try:
        bing = resolve_with_bing(q, max_results=max_results)
        candidates.extend(bing)
    except Exception:
        pass

    # Normalize and score candidates (simple heuristics)
    unique = {}
    for c in candidates:
        e = c.get('email')
        if not e:
            continue
        e_l = e.strip().lower()
        if e_l not in unique:
            unique[e_l] = {'email': e_l, 'sources': [c.get('source')], 'confidence': float(c.get('confidence', 0.5))}
        else:
            unique[e_l]['sources'].append(c.get('source'))
            # boost confidence slightly for multiple sources
            unique[e_l]['confidence'] = min(0.99, unique[e_l]['confidence'] + 0.15)

    # Convert to list and sort
    out = []
    for v in unique.values():
        out.append({'email': v['email'], 'sources': v['sources'], 'confidence': v['confidence']})
    out_sorted = sorted(out, key=lambda x: -x.get('confidence', 0))
    return out_sorted


def email_finder_keys_status() -> dict:
    """Return status of API keys for email finder and user-facing instructions if missing."""
    bing = bool(BING_KEY)
    people = bool(PEOPLE_API_KEY)
    configured = bing or people
    instructions = (
        "Email finder uses paid APIs. To enable:\n\n"
        "1. **Bing Web Search API** (finds emails via web search):\n"
        "   • Go to https://www.microsoft.com/en-us/bing/apis/bing-web-search-api\n"
        "   • Create a resource in Azure Portal, get your subscription key.\n"
        "   • Add BING_SEARCH_API_KEY=your_key to the .env file or Settings tab.\n\n"
        "2. **People/Email Finder API** (e.g. Hunter.io for professional emails):\n"
        "   • Go to https://hunter.io/api (or your provider)\n"
        "   • Sign up and get an API key.\n"
        "   • Add PEOPLE_API_KEY=your_key to the .env file or Settings tab.\n\n"
        "At least one key is required to find email addresses by name when they are not in your contacts."
    )
    return {"bing_configured": bing, "people_configured": people, "any_configured": configured, "instructions": instructions}


if __name__ == '__main__':
    print('Contact resolver module loaded')