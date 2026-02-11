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
# Bing key: prefer BING_API_KEY (as in .env), then BING_SEARCH_API_KEY, BING_SEARCH_KEY, and Bing_API_KEY (common .env spelling)
def _get_bing_key():
    return (
        os.getenv('BING_API_KEY')
        or os.getenv('BING_SEARCH_API_KEY')
        or os.getenv('BING_SEARCH_KEY')
        or os.getenv('Bing_API_KEY')
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


def bing_web_search_grounding(query: str, max_results: int = 6) -> List[Dict]:
    """Run a general Bing Web Search and return snippets + URLs for chat grounding.
    Use this to inject real-time web context into the LLM prompt (like ChatGPT.com with Bing).
    Returns list of dicts: [{"snippet": str, "url": str}, ...]."""
    bing_key = _get_bing_key()
    if not bing_key:
        return []
    try:
        endpoint = 'https://api.bing.microsoft.com/v7.0/search'
        params = {'q': query.strip(), 'count': max_results}
        headers = {'Ocp-Apim-Subscription-Key': bing_key}
        r = requests.get(endpoint, params=params, headers=headers, timeout=10)
        data = r.json()
        out = []
        for it in data.get('webPages', {}).get('value', []) or []:
            snippet = (it.get('snippet') or '').strip()
            url = (it.get('url') or '').strip()
            if snippet or url:
                out.append({'snippet': snippet, 'url': url})
        return out
    except Exception as e:
        logger.warning(f"Bing grounding search failed: {e}")
        return []


def resolve_with_bing(query: str, company: Optional[str] = None, max_results: int = 5) -> List[Dict]:
    """Use Bing Web Search API to search for pages that may include emails for the query.
    When company is provided, includes it in the search to narrow results (e.g. "Find email of xxx from company Y")."""
    bing_key = _get_bing_key()
    if not bing_key:
        logger.info("Bing API key not configured; skipping Bing resolver")
        return []
    try:
        endpoint = 'https://api.bing.microsoft.com/v7.0/search'
        # Craft query: person name, optional company, and email-related terms
        q = f'"{query}"'
        if company and company.strip():
            q += f' "{company.strip()}"'
        q += ' email OR contact OR "@"'
        params = {'q': q, 'count': max_results}
        headers = {'Ocp-Apim-Subscription-Key': bing_key}
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

    # 3) Bing Web Search (include company in query when provided)
    try:
        bing = resolve_with_bing(q, company=company, max_results=max_results)
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
    bing = bool(_get_bing_key())
    people = bool(PEOPLE_API_KEY)
    configured = bing or people
    instructions = (
        "Email finder uses paid APIs. To enable:\n\n"
        "1. **Bing Web Search API** (finds emails via web search):\n"
        "   • Go to https://www.microsoft.com/en-us/bing/apis/bing-web-search-api\n"
        "   • Create a resource in Azure Portal, get your subscription key.\n"
        "   • Add BING_API_KEY=your_key (or BING_SEARCH_API_KEY) to the .env file or Settings tab.\n\n"
        "2. **People/Email Finder API** (e.g. Hunter.io for professional emails):\n"
        "   • Go to https://hunter.io/api (or your provider)\n"
        "   • Sign up and get an API key.\n"
        "   • Add PEOPLE_API_KEY=your_key to the .env file or Settings tab.\n\n"
        "At least one key is required to find email addresses by name when they are not in your contacts."
    )
    return {"bing_configured": bing, "people_configured": people, "any_configured": configured, "instructions": instructions}


def message_keys_required() -> str:
    """User-friendly notification when Bing/People API keys are not in .env."""
    return (
        "Email finder APIs are not configured. To find or send to someone by name when they're not in your contacts, "
        "add at least one of these keys to the .env file (or the Settings tab):\n\n"
        "• BING_API_KEY (or BING_SEARCH_API_KEY) – Bing Web Search API (Azure). Get a key at https://www.microsoft.com/en-us/bing/apis/bing-web-search-api\n"
        "• PEOPLE_API_KEY – e.g. Hunter.io Email Finder. Get a key at https://hunter.io/api\n\n"
        "After adding a key, restart the app and try again."
    )


def message_email_not_found(name: str) -> str:
    """User-friendly notification when keys are set but no email could be found for the person."""
    return (
        f'No email address could be found for "{name}". '
        "Possible reasons: the person's email is not publicly available, search results did not contain a valid address, "
        "or the name is too generic. Try adding more context (e.g. company name) or add the contact manually in Settings."
    )


if __name__ == '__main__':
    print('Contact resolver module loaded')