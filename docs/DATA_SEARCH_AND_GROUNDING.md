# Data Search Performance vs ChatGPT.com

## Why the app felt worse than ChatGPT.com

ChatGPT.com uses **grounding**: it runs a web search (e.g. Bing), injects the results into the model’s context, then generates an answer. So the model “sees” current web data and can cite it.

This app was **not** doing that for general chat:

| Key | What ChatGPT.com does | What this app did before |
|-----|------------------------|---------------------------|
| **OpenAI** | Chat + optional grounding with web context | Chat only, no web context in most cases |
| **News API** | N/A (ChatGPT uses Bing/web) | Only for **news-style** queries (regex: “news”, “latest”, “who is the current …”). Not used for general “what is X” or “current Y”. |
| **Bing** | Used to run web search and ground answers | Used **only for finding email addresses** (contact resolver). Never used to augment general chat. |

So:

1. **Bing was underused** – Only used for “find email of X”, not for answering factual or current-events questions in chat.
2. **No web grounding in chat** – For most questions the model only had its training data (with a knowledge cutoff), so answers were often outdated or generic.
3. **News API is narrow** – Only headlines/articles and only when the query matched news-style keywords.
4. **Model** – App uses `gpt-3.5-turbo`; ChatGPT.com often uses stronger models and always has the option of web grounding.

## What we changed (Bing grounding in chat)

- **Bing Web Search is now used for chat grounding** when:
  - `BING_API_KEY` (or `BING_SEARCH_API_KEY`) is set in `.env`, and
  - The user message looks like a factual/search question (e.g. ends with `?`, or contains “what”, “who”, “latest”, “current”, etc.).
- The app calls the Bing Web Search API with the user’s query, gets snippets + URLs, injects them into the prompt as “Web search results”, then calls OpenAI. The model can use that context to give up-to-date, grounded answers.
- This is done in both `chat_server.py` and `chat_server_simple.py`.

So with your paid **Bing API key**, the app now uses it for:

1. **Email finder** – “Find email of X from company Y” (unchanged).
2. **Chat grounding** – Real-time web context for factual/search questions in chat (new).

News API is still used only for explicit news-style queries; Bing grounding covers the rest of “search” behavior and brings the app closer to ChatGPT.com-style data search.

## Optional: use a stronger model

For even better answers you can switch the chat to a stronger model (e.g. `gpt-4` or `gpt-4-turbo`) where the code calls `client.chat.completions.create(model="gpt-3.5-turbo", ...)`. That will increase cost but can improve quality.
