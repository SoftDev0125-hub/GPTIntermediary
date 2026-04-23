/**
 * WhatsApp Node.js Backend Server
 * Handles QR code authentication and WhatsApp operations using whatsapp-web.js
 */

// Log uncaught errors before exit (so dist/logs/whatsapp_server.log shows the real cause)
process.on('uncaughtException', (err) => {
  console.error('[WhatsApp] Uncaught exception:', err && err.stack ? err.stack : err);
  process.exit(1);
});
process.on('unhandledRejection', (reason, p) => {
  console.error('[WhatsApp] Unhandled rejection:', reason);
  process.exit(1);
});

const express = require('express');
const qrcode = require('qrcode');
const path = require('path');
const fs = require('fs');
try {
    require('dotenv').config({ path: path.join(__dirname, '..', '..', '.env') });
} catch (e) {
    /* dotenv optional at runtime */
}
const cors = require('cors');
const http = require('http');
const { Server } = require('socket.io');
// Defer heavy requires until after server.listen() so the port binds immediately (avoids "not listening" on slow/copied dist)
let Client = null;
let LocalAuth = null;
let puppeteer = undefined; // undefined = not loaded yet, null = load failed, object = loaded

const app = express();
const server = http.createServer(app);
const io = new Server(server, {
    cors: {
        origin: "*",
        methods: ["GET", "POST"]
    }
});

// Use WHATSAPP_PORT only; do not use process.env.PORT (often 8000 for the Python backend)
const PORT = process.env.WHATSAPP_PORT ? parseInt(process.env.WHATSAPP_PORT, 10) : 3000;

// Middleware
app.use(cors());
app.use(express.json());

// WhatsApp client instance
let client = null;
let qrCodeData = null;
let isAuthenticated = false;
let isReady = false;
// Time when we last became authenticated (used to avoid clearing client before LocalAuth writes session to disk)
let lastAuthenticatedAt = 0;
// Time when client became ready (used for warmup delay before getChats/getChatById)
let readyAt = 0;
// Timeout for fallback when 'ready' never fires (whatsapp-web.js known issue)
let readyFallbackTimeout = null;
// Warmup delay: wait this many ms after 'ready' before allowing getChats/getChatById (WhatsApp Web needs time to initialize).
// Large accounts (5k–10k+ contacts) need more time; set WHATSAPP_CHATS_WARMUP_MS=45000 if you see getChats retries/failures.
const CHATS_WARMUP_MS = process.env.WHATSAPP_CHATS_WARMUP_MS ? Math.max(5000, parseInt(process.env.WHATSAPP_CHATS_WARMUP_MS, 10)) : 20000; // default 20s
/** When to start background getChats() after `ready` (runs in parallel with warmup; was equal to CHATS_WARMUP_MS). */
const CHATS_PREFETCH_MS = process.env.WHATSAPP_CHATS_PREFETCH_MS ? Math.max(1000, parseInt(process.env.WHATSAPP_CHATS_PREFETCH_MS, 10)) : 3000; // default 3s
/**
 * Optional ms to wait after `ready` before the first message fetch (WhatsApp Web race mitigation).
 * Default 0 restores immediate fetches like earlier builds; set e.g. WHATSAPP_MESSAGES_MIN_READY_MS=5000 if you see empty first loads.
 */
const MESSAGES_MIN_READY_MS = (() => {
    const raw = process.env.WHATSAPP_MESSAGES_MIN_READY_MS;
    if (raw != null && String(raw).trim() !== '') {
        const n = parseInt(String(raw).trim(), 10);
        return Number.isFinite(n) ? Math.max(0, n) : 0;
    }
    return 0;
})();
// Cache getChats() result for pagination (avoid repeated heavy getChats() calls)
const CHATS_CACHE_MS = 300000; // 5 minutes (large accounts may scroll 10k+ contacts)
let chatsCache = null;
let chatsCacheAt = 0;
/** Serialized sidebar rows built once per chatsCache refresh (mapping 10k+ chats per HTTP request was freezing the UI) */
let chatsListRowsCache = null;
/** True while getChats() is running in the background; clients get loading: true until cache is ready */
let chatsCacheLoading = false;
/** Stop spinning getChats after repeated failures until next ready or client sends reset_chat_list_retry */
let chatListBackgroundDisabled = false;
let chatsCacheConsecutiveFailures = 0;
let chatsCacheLastLoadError = null;
// Cache messages so media can be fetched later even when whatsapp-web.js can't resolve by id (common for older messages)
const messageCacheById = new Map(); // messageId -> Message

/** After each `ready`, allow one consolidated "degraded mode" log when WA Web breaks wwebjs (reduces log noise). */
let wwebDegradedBannerLogged = false;

function logWWebDegradedModeBanner(symptom) {
    if (wwebDegradedBannerLogged) return;
    wwebDegradedBannerLogged = true;
    const hint = symptom === 'isNewsletter' ? 'isNewsletter' : 'waitForChatLoading';
    console.warn(
        '[WhatsApp] DEGRADED MODE (logged once until next ready): whatsapp-web.js cannot drive the current WhatsApp Web page JS (' +
            hint +
            '). Messages and avatars may fail.'
    );
    const pinned = process.env.WHATSAPP_WEB_VERSION && String(process.env.WHATSAPP_WEB_VERSION).trim();
    if (pinned) {
        console.warn(
            '[WhatsApp] WHATSAPP_WEB_VERSION is ' +
                pinned +
                ' — the page still loads scripts from static.whatsapp.net; if errors continue, try another html/ build from https://github.com/wppconnect-team/wa-version or check for a newer whatsapp-web.js on npm/GitHub.'
        );
    } else {
        console.warn(
            '[WhatsApp] Fix: set WHATSAPP_WEB_VERSION + WHATSAPP_WEB_VERSION_CACHE_TYPE=remote in .env (see .env.example), restart this process, or upgrade whatsapp-web.js when a fix ships.'
        );
    }
}

/** Puppeteer/eval errors often embed multi-line stacks in message; keep logs readable. */
function wwebErrorFirstLine(msg) {
    return String(msg || '')
        .split('\n')[0]
        .trim();
}

function isWWebKnownBreakageMessage(msg) {
    return /waitForChatLoading|isNewsletter/i.test(String(msg || ''));
}

/** If banner already ran this session, skip repeated one-line logs for the same WA Web breakage. */
function suppressWWebKnownBreakagePerRequestLog(msg) {
    return isWWebKnownBreakageMessage(msg) && wwebDegradedBannerLogged;
}

/** After DEGRADED MODE, avoid one line per contact for missing avatars (same root cause). */
let wwebDegradedAvatarBulkWarned = false;

function sanitizeFilenameForHeader(name, fallback = 'file') {
    let s = '';
    try { s = name ? String(name) : ''; } catch (e) { s = ''; }
    // Remove control characters (including CR/LF) which are illegal in headers
    s = s.replace(/[\u0000-\u001F\u007F]/g, '');
    // Replace characters that frequently break quoted header values
    s = s.replace(/[\\"]/g, '_');
    // Force ASCII in the fallback filename to avoid Node header validation errors
    s = s.replace(/[^\x20-\x7E]/g, '_').trim();
    if (!s) s = fallback;
    if (s.length > 180) s = s.slice(0, 180);
    return s;
}

function buildContentDisposition(filename, download) {
    const original = filename ? String(filename) : 'file';
    const safeAscii = sanitizeFilenameForHeader(original, 'file');
    const encoded = encodeURIComponent(original);
    const type = download ? 'attachment' : 'inline';
    return `${type}; filename=\"${safeAscii}\"; filename*=UTF-8''${encoded}`;
}

/** Safe filename for avatar cache (no path chars, no control chars). */
function sanitizeAvatarCacheKey(contactId) {
    let s = String(contactId || '').replace(/[\0-\x1F\x7F\\/:*?"<>|]/g, '_').trim();
    if (!s) s = 'unknown';
    if (s.length > 200) s = s.slice(0, 200);
    return s;
}

/** Get current user's contact ID string for profile picture (robust extraction from client.info.wid). */
function getMyContactId() {
    try {
        if (!client || !client.info || !client.info.wid) return null;
        const wid = client.info.wid;
        if (typeof wid === 'string') return wid;
        if (wid._serialized) return wid._serialized;
        if (wid.id && typeof wid.id === 'string') return wid.id;
        if (wid.user) return `${wid.user}@${wid.server || 'c.us'}`;
        return null;
    } catch (e) {
        return null;
    }
}

/**
 * Safely get chat/contact ID string (handles LID, _serialized, or plain string from whatsapp-web.js).
 * Returns null if not extractable.
 */
/** Compare sidebar/API contact_id to serialized chat id (handles encoding and minor format differences). */
function waIdsLooselyEqual(a, b) {
    const x = String(a || '').trim();
    const y = String(b || '').trim();
    if (!x || !y) return false;
    if (x === y) return true;
    const dec = (s) => {
        try {
            return decodeURIComponent(s);
        } catch (e) {
            return s;
        }
    };
    if (dec(x) === y || x === dec(y) || dec(x) === dec(y)) return true;
    return false;
}

function serializeChatId(chat) {
    try {
        if (!chat || !chat.id) return null;
        const id = chat.id;
        if (typeof id === 'string') return id;
        if (id._serialized) return String(id._serialized);
        if (id.user) return `${id.user}@${id.server || 'c.us'}`;
        // LID or other formats: id.id (string) or Jid.toString()
        if (id.id && typeof id.id === 'string') return id.id.includes('@') ? id.id : `${id.id}@${id.server || 'c.us'}`;
        if (typeof id.toString === 'function') {
            const s = id.toString();
            if (s && s !== '[object Object]') return s;
        }
        return null;
    } catch (e) {
        return null;
    }
}

/**
 * Safely get message ID string (handles _serialized or plain string from whatsapp-web.js).
 * Returns null if not extractable.
 */
function serializeMessageId(msg) {
    try {
        if (!msg) return null;
        if (msg.id) {
            const id = msg.id;
            if (typeof id === 'string') return id;
            if (id._serialized) return String(id._serialized);
            if (typeof id === 'object' && id.remote != null && id.id != null) {
                const remote = typeof id.remote === 'string'
                    ? id.remote
                    : (id.remote && id.remote._serialized ? String(id.remote._serialized) : '');
                const part = id.id;
                let mid = '';
                if (typeof part === 'string' && part.length) mid = part;
                else if (typeof part === 'number' && !Number.isNaN(part)) mid = String(part);
                else if (part && typeof part === 'object' && part._serialized) mid = String(part._serialized);
                const fromMe = id.fromMe === true ? 'true' : 'false';
                if (remote && mid) return `${fromMe}_${remote}_${mid}`;
            }
            if (typeof id === 'object' && id.id != null) {
                const inner = id.id;
                if (typeof inner === 'string' && inner.length) return inner.includes('@') ? inner : String(inner);
                if (typeof inner === 'number' && !Number.isNaN(inner)) return String(inner);
                if (inner && typeof inner === 'object' && inner._serialized) return String(inner._serialized);
            }
            if (typeof id.toString === 'function') {
                const s = id.toString();
                if (s && s !== '[object Object]') return s;
            }
        }
        // whatsapp-web.js raw payload (some builds omit normalized msg.id)
        const key = msg._data && msg._data.key;
        if (key) {
            if (key._serialized) return String(key._serialized);
            const rjid = (key.remoteJid || key.participant || '').toString();
            const mid = key.id != null ? String(key.id) : '';
            const fromMe = key.fromMe === true ? 'true' : 'false';
            if (mid && rjid) return `${fromMe}_${rjid}_${mid}`;
        }
        // Newer whatsapp-web.js / WA Web payloads (id shape varies by version)
        try {
            const d = msg._data;
            if (d && d.id != null) {
                const rawId = d.id;
                if (typeof rawId === 'string' && rawId.length) return rawId;
                if (rawId && typeof rawId === 'object' && rawId._serialized) return String(rawId._serialized);
            }
        } catch (e) { /* ignore */ }
        try {
            const midObj = msg.id;
            if (midObj && typeof midObj === 'object' && midObj.id != null && !midObj._serialized) {
                const piece = String(midObj.id);
                const remote =
                    (midObj.remote &&
                        (typeof midObj.remote === 'string'
                            ? midObj.remote
                            : midObj.remote._serialized && String(midObj.remote._serialized))) ||
                    (msg.from && String(msg.from)) ||
                    '';
                const fromMe = midObj.fromMe === true ? 'true' : 'false';
                if (piece && remote) return `${fromMe}_${remote}_${piece}`;
            }
        } catch (e) { /* ignore */ }
        return null;
    } catch (e) {
        return null;
    }
}

/**
 * Scroll-up pagination: messages strictly older than beforeTimestamp.
 * chat.fetchMessages({ limit }) only materializes the *newest* N messages in the client; filtering that list by
 * before_timestamp often yields nothing for long chats (all N are newer than the cursor). This repeatedly
 * calls WAWebChatLoadMessages.loadEarlierMsgs until enough rows exist older than the cursor, or history ends.
 *
 * @returns {{ messages: Array, exhausted: boolean }}
 */
async function fetchOlderMessagesThanCursor(chatSerializedId, beforeTimestampSec, fetchLimit) {
    const empty = { messages: [], exhausted: true };
    if (!client || !client.pupPage || !chatSerializedId) return empty;
    const Message = require('whatsapp-web.js').Message;
    const beforeTs = Number(beforeTimestampSec);
    const limit = Math.min(Math.max(parseInt(fetchLimit, 10) || 30, 1), 100);
    if (!Number.isFinite(beforeTs)) return empty;

    const result = await client.pupPage.evaluate(
        async (chatId, beforeTsInner, limitInner) => {
            const WU = window.WWebJS;
            if (!WU || typeof WU.getChat !== 'function') {
                return { models: [], exhausted: true };
            }
            let chat;
            try {
                chat = await WU.getChat(chatId, { getAsModel: false });
            } catch (e) {
                return { models: [], exhausted: true };
            }
            if (!chat) return { models: [], exhausted: true };

            const msgFilter = (m) => m && !m.isNotification;
            const ts = (m) => {
                if (!m) return 0;
                if (typeof m.t === 'number' && !Number.isNaN(m.t)) return m.t;
                if (typeof m.timestamp === 'number' && !Number.isNaN(m.timestamp)) return m.timestamp;
                return 0;
            };

            let msgs = (chat.msgs && chat.msgs.getModelsArray ? chat.msgs.getModelsArray() : []).filter(msgFilter);
            let iterations = 0;
            const maxIter = 300;
            const countOlder = (list) => list.filter((m) => ts(m) < beforeTsInner).length;

            let loadMod;
            try {
                loadMod = window.require && window.require('WAWebChatLoadMessages');
            } catch (e) {
                loadMod = null;
            }
            if (!loadMod || typeof loadMod.loadEarlierMsgs !== 'function') {
                return { models: [], exhausted: true };
            }

            let hitEndOfHistory = false;
            while (countOlder(msgs) < limitInner && iterations < maxIter) {
                iterations += 1;
                const loaded = await loadMod.loadEarlierMsgs({ chat });
                if (!loaded || !loaded.length) {
                    hitEndOfHistory = true;
                    break;
                }
                msgs = [...loaded.filter(msgFilter), ...msgs];
            }

            let older = msgs.filter((m) => ts(m) < beforeTsInner);
            older.sort((a, b) => ts(a) - ts(b));
            if (older.length > limitInner) {
                older = older.slice(older.length - limitInner);
            }

            const exhausted = hitEndOfHistory || older.length < limitInner;
            const models = older
                .map((m) => {
                    try {
                        return WU.getMessageModel(m);
                    } catch (e) {
                        return null;
                    }
                })
                .filter(Boolean);

            return { models, exhausted };
        },
        chatSerializedId,
        beforeTs,
        limit
    );

    const models = result && Array.isArray(result.models) ? result.models : [];
    const exhausted = !!(result && result.exhausted);
    try {
        const messages = models.map((d) => new Message(client, d));
        return { messages, exhausted };
    } catch (e) {
        console.error('[WhatsApp] fetchOlderMessagesThanCursor wrap Message:', e && e.message);
        return empty;
    }
}

/** Try alternate encodings of the same chat id (proxy / JSON sometimes alter @ or %). */
function contactIdCandidates(raw) {
    const s = String(raw || '').trim();
    if (!s) return [];
    const out = [];
    const add = (x) => {
        const t = String(x || '').trim();
        if (t && !out.includes(t)) out.push(t);
    };
    add(s);
    try {
        const dec = decodeURIComponent(s);
        if (dec !== s) add(dec);
    } catch (e) { /* ignore */ }
    return out;
}

/**
 * Expand chat id candidates using getContactById (LID → @c.us phone jid when WA exposes it).
 * Without this, list rows can show @lid while getChatById only accepts the PN jid — messages never load.
 */
async function contactIdCandidatesWithLookup(rawContactId) {
    const out = [];
    const add = (x) => {
        const t = String(x || '').trim();
        if (t && !out.includes(t)) out.push(t);
    };
    const primary = String(rawContactId || '').trim();
    if (!primary) return out;

    // Prefer ids from the in-memory chat list (matches what the UI shows; helps LID/@c.us mismatches).
    try {
        if (chatsCache && Array.isArray(chatsCache)) {
            for (const ch of chatsCache) {
                let sid = null;
                try {
                    sid = serializeChatId(ch);
                } catch (e) {
                    continue;
                }
                if (!sid || !waIdsLooselyEqual(sid, primary)) continue;
                const ido = ch.id;
                if (ido && typeof ido === 'object') {
                    if (ido._serialized) add(String(ido._serialized));
                    if (ido.user && ido.server) add(`${ido.user}@${ido.server}`);
                }
                add(sid);
                break;
            }
        }
    } catch (e) { /* ignore */ }

    contactIdCandidates(rawContactId).forEach(add);
    if (!client) return out;
    try {
        const contact = await client.getContactById(primary);
        if (contact && contact.id) {
            const cid = contact.id;
            if (typeof cid === 'string') add(cid);
            else if (cid._serialized) add(String(cid._serialized));
            const num = contact.number != null ? String(contact.number).replace(/\D/g, '') : '';
            if (num.length >= 8) add(`${num}@c.us`);
        }
    } catch (e) { /* ignore */ }
    return out;
}

function chatToContactRow(chat) {
    const last = chat.lastMessage || null;
    const chatId = serializeChatId(chat);
    const lastMsgId = serializeMessageId(last);
    const idObj = chat && chat.id && typeof chat.id === 'object' ? chat.id : null;
    return {
        contact_id: chatId,
        contact_user: idObj && idObj.user ? idObj.user : null,
        contact_server: idObj && idObj.server ? idObj.server : null,
        name: chat.name || (idObj && idObj.user) || 'Unknown',
        is_group: !!chat.isGroup,
        last_message_id: lastMsgId,
        last_message: last && last.body ? String(last.body) : '',
        last_message_time: last && typeof last.timestamp === 'number' ? last.timestamp : null,
        last_message_from_me: last && typeof last.fromMe === 'boolean' ? last.fromMe : null,
        last_message_type: last && last.type ? String(last.type) : null,
        last_message_has_media: last && typeof last.hasMedia === 'boolean' ? last.hasMedia : null,
        unread_count: chat.unreadCount || 0,
        avatar_url: null
    };
}

function rebuildChatsListRowsCacheFromChats(chats) {
    if (!chats || !Array.isArray(chats)) {
        chatsListRowsCache = null;
        return;
    }
    const rows = [];
    for (let i = 0; i < chats.length; i++) {
        try {
            const row = chatToContactRow(chats[i]);
            if (row.contact_id) rows.push(row);
        } catch (e) {
            /* skip malformed chat */
        }
    }
    chatsListRowsCache = rows;
}

/** Resolve a Chat instance from the getChats() cache (same object fetchMessages needs when getChatById(id) fails). */
function findCachedChatByContactId(rawContactId) {
    const primary = String(rawContactId || '').trim();
    if (!primary || !chatsCache || !Array.isArray(chatsCache)) return null;
    for (const ch of chatsCache) {
        try {
            const sid = serializeChatId(ch);
            if (sid && waIdsLooselyEqual(sid, primary)) return ch;
        } catch (e) {
            /* ignore */
        }
    }
    return null;
}

function cacheWhatsAppMessage(msg) {
    try {
        const id = serializeMessageId(msg);
        if (!id) return;
        messageCacheById.set(id, msg);
        // Keep memory bounded
        if (messageCacheById.size > 5000) {
            const firstKey = messageCacheById.keys().next().value;
            if (firstKey) messageCacheById.delete(firstKey);
        }
    } catch (e) {}
}

// Session directory
// Keep session data at the project root so moving this file doesn't break existing sessions.
const PROJECT_ROOT = path.join(__dirname, '..', '..');
const SESSION_DIR = path.join(PROJECT_ROOT, 'whatsapp_session_node');
// LocalAuth with dataPath: SESSION_DIR stores Puppeteer profile in SESSION_DIR/session (not .wwebjs_auth)
const SESSION_DATA_PATH = path.join(SESSION_DIR, 'session');
const AVATAR_DIR = path.join(SESSION_DIR, 'avatars');
// Flag file: written only after successful auth so we can tell "has stored login" from "session dir exists"
const AUTH_FLAG_FILE = path.join(SESSION_DIR, '.authenticated');

// Ensure session directory exists
if (!fs.existsSync(SESSION_DIR)) {
    fs.mkdirSync(SESSION_DIR, { recursive: true });
}
if (!fs.existsSync(AVATAR_DIR)) {
    fs.mkdirSync(AVATAR_DIR, { recursive: true });
}

/**
 * True if we have persisted authentication (user has logged in before); false if QR is needed.
 * Uses a flag file written on authenticated/ready; the session dir alone is not enough (it's created on first init).
 */
function hasAuthenticatedSession() {
    return fs.existsSync(AUTH_FLAG_FILE);
}

/** Remove the auth flag (e.g. on auth_failure or LOGOUT) so we show QR next time. */
function clearAuthFlag() {
    try {
        if (fs.existsSync(AUTH_FLAG_FILE)) {
            fs.unlinkSync(AUTH_FLAG_FILE);
        }
    } catch (e) {
        console.error('[WhatsApp] Could not clear auth flag:', e);
    }
}

/**
 * Check if session folder was deleted while we think we're connected, and reset if so
 * Returns true if client state was reset, false otherwise
 */
async function checkAndResetIfSessionDeleted() {
    const sessionDataDirExists = fs.existsSync(SESSION_DATA_PATH);
    const authGraceMs = 20000;
    const withinGracePeriod = lastAuthenticatedAt && (Date.now() - lastAuthenticatedAt < authGraceMs);
    
    if (isAuthenticated && isReady && client && !sessionDataDirExists && !withinGracePeriod) {
        console.log('[WhatsApp] Session folder deleted while connected - resetting client state');
        try {
            await client.destroy();
        } catch (err) {
            console.error('[WhatsApp] Error destroying client:', err);
        }
        client = null;
        chatsCache = null;
        chatsCacheAt = 0;
        chatsListRowsCache = null;
        isAuthenticated = false;
        isReady = false;
        lastAuthenticatedAt = 0;
        readyAt = 0;
        qrCodeData = null;
        clearAuthFlag();
        if (readyFallbackTimeout) {
            clearTimeout(readyFallbackTimeout);
            readyFallbackTimeout = null;
        }
        return true;
    }
    return false;
}

/**
 * Optional: pin WhatsApp Web HTML to a version archived by wwebjs (helps when live web.whatsapp.com
 * breaks whatsapp-web.js — e.g. "Cannot read properties of undefined (reading 'waitForChatLoading')").
 * Set WHATSAPP_WEB_VERSION to a build listed under html/ in https://github.com/wppconnect-team/wa-version
 * (the old wwebjs/wa-version raw URLs often 404).
 */
function getWhatsAppWebVersionClientOptions() {
    const defaultRemoteHtml =
        'https://raw.githubusercontent.com/wppconnect-team/wa-version/main/html/{version}.html';
    const wv = process.env.WHATSAPP_WEB_VERSION && String(process.env.WHATSAPP_WEB_VERSION).trim();
    if (!wv) return {};
    const cacheType = (process.env.WHATSAPP_WEB_VERSION_CACHE_TYPE || 'remote').toLowerCase().trim();
    const strict =
        process.env.WHATSAPP_WEB_VERSION_STRICT === '1' ||
        process.env.WHATSAPP_WEB_VERSION_STRICT === 'true';
    const out = { webVersion: wv };
    if (cacheType === 'remote') {
        const remotePath =
            (process.env.WHATSAPP_WEB_VERSION_REMOTE_PATH && String(process.env.WHATSAPP_WEB_VERSION_REMOTE_PATH).trim()) ||
            defaultRemoteHtml;
        out.webVersionCache = { type: 'remote', remotePath, strict };
    } else if (cacheType === 'local') {
        out.webVersionCache = { type: 'local' };
    } else if (cacheType === 'none') {
        out.webVersionCache = { type: 'none' };
    } else {
        out.webVersionCache = { type: 'remote', remotePath: defaultRemoteHtml, strict };
    }
    console.log('[WhatsApp] Client webVersion override:', wv, 'webVersionCache.type=', out.webVersionCache.type);
    return out;
}

/**
 * Initialize WhatsApp client
 */
function initializeWhatsApp() {
    if (client) {
        console.log('[WhatsApp] Client already initialized');
        return;
    }

    console.log('[WhatsApp] Initializing WhatsApp client...');

    // Load heavy deps here (after server is already listening) so startup binds port quickly on slow/copied dist
    if (!Client || !LocalAuth) {
        const wweb = require('whatsapp-web.js');
        Client = wweb.Client;
        LocalAuth = wweb.LocalAuth;
    }
    if (typeof puppeteer === 'undefined') {
        try {
            puppeteer = require('puppeteer');
        } catch (e) {
            puppeteer = null;
        }
    }

    // Ensure session directory exists (e.g. after user deleted whatsapp_session_node)
    if (!fs.existsSync(SESSION_DIR)) {
        fs.mkdirSync(SESSION_DIR, { recursive: true });
    }
    if (!fs.existsSync(AVATAR_DIR)) {
        fs.mkdirSync(AVATAR_DIR, { recursive: true });
    }

    if (hasAuthenticatedSession()) {
        console.log('[WhatsApp] Existing session found - will auto-connect');
    } else {
        console.log('[WhatsApp] No session found - QR code authentication required');
    }

    // Create client with LocalAuth for session persistence
    // Use 1.34.6 for getChats fix (GroupMetadata undefined → PR #5779). If you see "auth timeout" on QR
    // login, try downgrading to 1.34.2 temporarily; then upgrade again when a fix is released.
    const puppeteerOpts = {
        headless: true,
        args: [
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--disable-dev-shm-usage',
            '--disable-accelerated-2d-canvas',
            '--no-first-run',
            '--no-zygote',
            '--disable-gpu'
        ]
    };
    // Default Puppeteer CDP timeout (~180s) aborts client.getChats() on very large accounts mid-call.
    const protoTimeoutRaw = process.env.WHATSAPP_PUPPETEER_PROTOCOL_TIMEOUT_MS;
    let protocolTimeoutMs = 600000;
    if (protoTimeoutRaw != null && String(protoTimeoutRaw).trim() !== '') {
        const n = parseInt(String(protoTimeoutRaw).trim(), 10);
        if (Number.isFinite(n) && n >= 0) protocolTimeoutMs = n;
    }
    puppeteerOpts.protocolTimeout = protocolTimeoutMs;
    if (protocolTimeoutMs > 0) {
        console.log('[WhatsApp] Puppeteer protocolTimeout ms:', protocolTimeoutMs);
    }

    /**
     * Puppeteer 24+ does not ship Chromium inside node_modules; it must be downloaded (`npx puppeteer browsers install chrome`)
     * or you use an existing Chrome/Edge. Without a real browser, client.initialize() never reaches the QR event — unrelated to Node major version.
     */
    let browserResolved = '';
    const envExe = process.env.PUPPETEER_EXECUTABLE_PATH && String(process.env.PUPPETEER_EXECUTABLE_PATH).trim();
    if (envExe && fs.existsSync(envExe)) {
        puppeteerOpts.executablePath = envExe;
        browserResolved = 'PUPPETEER_EXECUTABLE_PATH';
        console.log('[WhatsApp] Using browser from PUPPETEER_EXECUTABLE_PATH:', envExe);
    }

    // 1) Prefer a Chromium that is bundled inside the app (works in dist/ on machines without internet)
    const BUNDLED_CHROME_DIR_WIN = path.join(PROJECT_ROOT, 'whatsapp_chrome_win');
    const BUNDLED_CHROME_EXE_WIN = path.join(BUNDLED_CHROME_DIR_WIN, 'chrome.exe');
    if (!browserResolved && process.platform === 'win32' && fs.existsSync(BUNDLED_CHROME_EXE_WIN)) {
        puppeteerOpts.executablePath = BUNDLED_CHROME_EXE_WIN;
        browserResolved = 'bundled';
        console.log('[WhatsApp] Using bundled Chromium at:', BUNDLED_CHROME_EXE_WIN);
    } else if (!browserResolved && puppeteer && typeof puppeteer.executablePath === 'function') {
        // 2) Puppeteer cache (only if the file exists — executablePath() may point to a version not yet downloaded)
        try {
            const exe = puppeteer.executablePath();
            if (exe && typeof exe === 'string' && exe.length > 0 && fs.existsSync(exe)) {
                puppeteerOpts.executablePath = exe;
                browserResolved = 'puppeteer-cache';
                console.log('[WhatsApp] Using Puppeteer downloaded Chromium at:', exe);
            }
        } catch (e) {
            console.warn('[WhatsApp] Could not resolve Puppeteer executablePath:', e && e.message);
        }
    }

    if (!browserResolved && process.platform === 'win32') {
        const pf = process.env.PROGRAMFILES || 'C:\\Program Files';
        const pf86 = process.env['PROGRAMFILES(X86)'] || 'C:\\Program Files (x86)';
        const winChrome = [
            path.join(pf, 'Google', 'Chrome', 'Application', 'chrome.exe'),
            path.join(pf86, 'Google', 'Chrome', 'Application', 'chrome.exe'),
        ];
        for (const p of winChrome) {
            if (p && fs.existsSync(p)) {
                puppeteerOpts.executablePath = p;
                browserResolved = 'system-chrome';
                console.log('[WhatsApp] Using system Google Chrome at:', p);
                break;
            }
        }
    }

    if (!browserResolved && process.platform === 'darwin') {
        const macChrome = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
        if (fs.existsSync(macChrome)) {
            puppeteerOpts.executablePath = macChrome;
            browserResolved = 'system-chrome';
            console.log('[WhatsApp] Using system Google Chrome at:', macChrome);
        }
    }

    if (!browserResolved && process.platform === 'linux') {
        const linuxBrowsers = [
            '/usr/bin/google-chrome-stable',
            '/usr/bin/google-chrome',
            '/usr/bin/chromium-browser',
            '/usr/bin/chromium',
        ];
        for (const p of linuxBrowsers) {
            if (fs.existsSync(p)) {
                puppeteerOpts.executablePath = p;
                browserResolved = 'system-linux';
                console.log('[WhatsApp] Using system browser at:', p);
                break;
            }
        }
    }

    if (!browserResolved) {
        puppeteerOpts.channel = 'chrome';
        browserResolved = 'channel-chrome';
        console.log(
            '[WhatsApp] Using Puppeteer channel=chrome (expects Google Chrome installed). If the client fails to start, run from project root: npm run setup:puppeteer-chrome'
        );
    }

    client = new Client(
        Object.assign(
            {
                authStrategy: new LocalAuth({
                    dataPath: SESSION_DIR
                }),
                puppeteer: puppeteerOpts
            },
            getWhatsAppWebVersionClientOptions()
        )
    );

    // QR code event - fired when QR code is generated
    client.on('qr', async (qr) => {
        console.log('[WhatsApp] QR code received');
        try {
            // Ensure payload is a single string (whatsapp-web.js may pass string or array in some versions)
            const qrPayload = Array.isArray(qr) ? qr.join('') : String(qr || '');
            if (!qrPayload) {
                qrCodeData = null;
                return;
            }
            // Generate QR as data URL with options for reliable scanning (size, margin, error correction)
            qrCodeData = await qrcode.toDataURL(qrPayload, {
                width: 320,
                margin: 2,
                errorCorrectionLevel: 'M',
                type: 'image/png'
            });
            console.log('[WhatsApp] QR code generated successfully');
            // Emit to all connected clients so the QR appears immediately without waiting for HTTP poll
            try {
                io.emit('whatsapp_qr_code', {
                    qr_code: qrCodeData,
                    message: 'Scan the QR code with WhatsApp to connect'
                });
            } catch (e) {
                console.error('[WhatsApp] Error emitting QR to socket:', e && e.message);
            }
        } catch (err) {
            console.error('[WhatsApp] Error generating QR code:', err);
            qrCodeData = null;
        }
    });

    // Ready event - fired when client is ready to use
    client.on('ready', () => {
        if (readyFallbackTimeout) {
            clearTimeout(readyFallbackTimeout);
            readyFallbackTimeout = null;
        }
        console.log('[WhatsApp] Client is ready!');
        wwebDegradedBannerLogged = false;
        wwebDegradedAvatarBulkWarned = false;
        chatListBackgroundDisabled = false;
        chatsCacheConsecutiveFailures = 0;
        chatsCacheLastLoadError = null;
        isAuthenticated = true;
        isReady = true;
        lastAuthenticatedAt = Date.now();
        readyAt = Date.now();
        qrCodeData = null; // Clear QR code when authenticated
        try {
            fs.writeFileSync(AUTH_FLAG_FILE, String(Date.now()), 'utf8');
        } catch (e) {
            console.error('[WhatsApp] Could not write auth flag:', e);
        }
        // Preload chats soon after ready (parallel with warmup; sidebar can show as soon as getChats() fills cache)
        setTimeout(() => startBackgroundGetChats(), CHATS_PREFETCH_MS);
        console.log('[WhatsApp] Chat list prefetch in', CHATS_PREFETCH_MS, 'ms (warmup gate', CHATS_WARMUP_MS, 'ms unless cache ready)');

        // Emit ready event to all connected clients
        const readyPayload = {
            is_connected: true,
            is_authenticated: true,
            is_ready: true,
            message: 'Connected to WhatsApp'
        };
        try {
            const myId = getMyContactId();
            if (myId) {
                readyPayload.my_contact_id = myId;
                readyPayload.my_name = (client.info && client.info.pushname) || null;
            }
        } catch (e) { /* ignore */ }
        io.emit('whatsapp_status', readyPayload);
    });
    
    // Message event - fired when a message is received
    client.on('message', async (message) => {
        try {
            cacheWhatsAppMessage(message);
            console.log('[WhatsApp] New message received:', message.from, message.body?.substring(0, 50));
            
            // Get chat first so contact_id matches the open conversation (1:1 or group)
            const chat = await message.getChat();
            const quickMessage = {
                id: serializeMessageId(message),
                body: message.body || '',
                from: message.from,
                fromMe: message.fromMe,
                timestamp: message.timestamp,
                type: message.type,
                hasMedia: message.hasMedia,
                mediaUrl: null,
                mediaMimetype: null,
                mediaFilename: null,
                contact_id: serializeChatId(chat),
                contact_name: 'Loading...',
                is_group: !!chat.isGroup
            };
            
            // If message has media, try to download it asynchronously
            if (message.hasMedia) {
                message.downloadMedia().then(media => {
                    if (media) {
                        quickMessage.mediaUrl = `data:${media.mimetype};base64,${media.data}`;
                        quickMessage.mediaMimetype = media.mimetype;
                        quickMessage.mediaFilename = media.filename || null;
                        io.emit('whatsapp_message_update', quickMessage);
                    }
                }).catch(err => {
                    console.error('[WhatsApp] Error downloading media:', err);
                });
            }
            
            io.emit('whatsapp_message', quickMessage);
            
            try {
                const contact = await message.getContact();
                const formattedMessage = {
                    id: serializeMessageId(message),
                    body: message.body || '',
                    from: message.from,
                    fromMe: message.fromMe,
                    timestamp: message.timestamp,
                    type: message.type,
                    hasMedia: message.hasMedia,
                    mediaUrl: quickMessage.mediaUrl,
                    mediaMimetype: quickMessage.mediaMimetype,
                    mediaFilename: quickMessage.mediaFilename,
                    contact_id: serializeChatId(chat),
                    contact_name: chat.name || contact.name || 'Unknown',
                    is_group: !!chat.isGroup
                };
                io.emit('whatsapp_message_update', formattedMessage);
            } catch (chatError) {
                console.error('[WhatsApp] Error getting chat info:', chatError);
            }

            console.log('[WhatsApp] Message emitted via WebSocket');
        } catch (error) {
            console.error('[WhatsApp] Error processing incoming message:', error);
        }
    });

    // Message create event - fired when a message is created (sent or received)
    client.on('message_create', async (message) => {
        // Only handle sent messages here (received messages are handled by 'message' event)
        if (message.fromMe) {
            try {
                cacheWhatsAppMessage(message);
                const chat = await message.getChat();
                const quickMessage = {
                    id: serializeMessageId(message),
                    body: message.body || '',
                    from: message.from,
                    fromMe: true,
                    timestamp: message.timestamp,
                    type: message.type,
                    hasMedia: message.hasMedia,
                    mediaUrl: null,
                    mediaMimetype: null,
                    mediaFilename: null,
                    contact_id: serializeChatId(chat),
                    contact_name: 'Loading...',
                    is_group: !!chat.isGroup
                };
                
                if (message.hasMedia) {
                    message.downloadMedia().then(media => {
                        if (media) {
                            quickMessage.mediaUrl = `data:${media.mimetype};base64,${media.data}`;
                            quickMessage.mediaMimetype = media.mimetype;
                            quickMessage.mediaFilename = media.filename || null;
                            io.emit('whatsapp_message_update', quickMessage);
                        }
                    }).catch(err => {
                        console.error('[WhatsApp] Error downloading media:', err);
                    });
                }
                
                io.emit('whatsapp_message', quickMessage);
                
                try {
                    const contact = await message.getContact();
                    
                    const formattedMessage = {
                        id: serializeMessageId(message),
                        body: message.body || '',
                        from: message.from,
                        fromMe: true,
                        timestamp: message.timestamp,
                        type: message.type,
                        hasMedia: message.hasMedia,
                        mediaUrl: quickMessage.mediaUrl,
                        mediaMimetype: quickMessage.mediaMimetype,
                        mediaFilename: quickMessage.mediaFilename,
                        contact_id: serializeChatId(chat),
                        contact_name: chat.name || contact.name || 'Unknown',
                        is_group: !!chat.isGroup
                    };

                    // Emit updated message with full info
                    io.emit('whatsapp_message_update', formattedMessage);
                } catch (chatError) {
                    console.error('[WhatsApp] Error getting chat info for sent message:', chatError);
                }
            } catch (error) {
                console.error('[WhatsApp] Error processing sent message:', error);
            }
        }
    });

    // Authentication event - fired when authentication is successful
    client.on('authenticated', () => {
        console.log('[WhatsApp] Authentication successful!');
        isAuthenticated = true;
        lastAuthenticatedAt = Date.now();
        try {
            fs.writeFileSync(AUTH_FLAG_FILE, String(Date.now()), 'utf8');
        } catch (e) {
            console.error('[WhatsApp] Could not write auth flag:', e);
        }
        // Emit status update when authenticated (even if not ready yet)
        io.emit('whatsapp_status', {
            // Authenticated does not guarantee chats API is ready yet; wait for `ready`
            is_connected: false,
            is_authenticated: true,
            is_ready: false,
            has_session: true,
            message: 'Connected to WhatsApp (initializing...)'
        });
        // Fallback: whatsapp-web.js sometimes never fires 'ready'. After 3s, treat as ready so chats/messages work.
        if (readyFallbackTimeout) clearTimeout(readyFallbackTimeout);
        readyFallbackTimeout = setTimeout(() => {
            readyFallbackTimeout = null;
            if (client && isAuthenticated && !isReady) {
                console.log('[WhatsApp] Using authenticated fallback (ready event did not fire)');
                isReady = true;
                readyAt = Date.now();
                chatListBackgroundDisabled = false;
                chatsCacheConsecutiveFailures = 0;
                chatsCacheLastLoadError = null;
                setTimeout(() => startBackgroundGetChats(), CHATS_PREFETCH_MS);
                const fallbackPayload = {
                    is_connected: true,
                    is_authenticated: true,
                    is_ready: true,
                    message: 'Connected to WhatsApp'
                };
                try {
                    const myId = getMyContactId();
                    if (myId) {
                        fallbackPayload.my_contact_id = myId;
                        fallbackPayload.my_name = (client.info && client.info.pushname) || null;
                    }
                } catch (e) { /* ignore */ }
                io.emit('whatsapp_status', fallbackPayload);
            }
        }, 3000);
    });

    // Authentication failure event
    client.on('auth_failure', (msg) => {
        console.error('[WhatsApp] Authentication failure:', msg);
        isAuthenticated = false;
        isReady = false;
        lastAuthenticatedAt = 0;
        readyAt = 0;
        qrCodeData = null;
        clearAuthFlag();
    });

    // Disconnected event
    client.on('disconnected', (reason) => {
        console.log('[WhatsApp] Client disconnected:', reason);
        isAuthenticated = false;
        isReady = false;
        lastAuthenticatedAt = 0;
        readyAt = 0;
        qrCodeData = null;
        if (reason === 'LOGOUT') {
            clearAuthFlag();
        }
        
        // If session was deleted, reinitialize
        if (reason === 'LOGOUT') {
            console.log('[WhatsApp] Session logged out - reinitializing...');
            client = null;
            chatsCache = null;
            chatsCacheAt = 0;
            chatsListRowsCache = null;
                initializeWhatsApp();
        }
    });

    // Initialize the client
    client.initialize().catch(err => {
        console.error('[WhatsApp] Error initializing client:', err);
    });
}

/**
 * GET /api/whatsapp/qr-code
 * Get QR code for authentication
 * Only returns QR code if there is no existing session (unless force_refresh is true)
 */
app.get('/api/whatsapp/qr-code', async (req, res) => {
    res.setHeader('Cache-Control', 'no-store, no-cache, must-revalidate'); // QR codes expire; never use cached
    try {
        const forceRefresh = req.query.force_refresh === 'true';
        
        // Check if session folder was deleted and reset if needed (unless forcing refresh)
        if (!forceRefresh) {
            await checkAndResetIfSessionDeleted();
        }
        
        const hasSession = hasAuthenticatedSession();

        // If already authenticated and we have stored session, return (no QR needed)
        if (isAuthenticated && isReady && hasSession && !forceRefresh) {
            return res.json({
                success: true,
                is_authenticated: true,
                has_session: hasSession,
                message: 'Already authenticated'
            });
        }

        // If we have stored auth, client is running, and we're not forcing refresh, don't show QR (client is restoring)
        if (hasSession && client && !forceRefresh) {
            console.log('[WhatsApp] Session exists - not generating QR code. Wait for session restoration.');
            return res.json({
                success: false,
                is_authenticated: false,
                has_session: true,
                message: 'Session exists - connecting... Please wait for authentication.'
            });
        }

        // Force refresh: always destroy client and clear session, then show new QR
        if (forceRefresh) {
            console.log('[WhatsApp] Force refresh requested - clearing session for different account...');
            try {
                if (readyFallbackTimeout) {
                    clearTimeout(readyFallbackTimeout);
                    readyFallbackTimeout = null;
                }
                if (client) {
                    try {
                        await client.destroy();
                    } catch (err) {
                        console.error('[WhatsApp] Error destroying client:', err);
                    }
                    client = null;
                    chatsCache = null;
                    chatsCacheAt = 0;
                    chatsListRowsCache = null;
                }
                isAuthenticated = false;
                isReady = false;
                lastAuthenticatedAt = 0;
                readyAt = 0;
                qrCodeData = null;
                if (fs.existsSync(SESSION_DIR)) {
                    fs.rmSync(SESSION_DIR, { recursive: true, force: true });
                    console.log('[WhatsApp] Session directory removed for force refresh');
                }
                fs.mkdirSync(SESSION_DIR, { recursive: true });
                if (!fs.existsSync(AVATAR_DIR)) {
                    fs.mkdirSync(AVATAR_DIR, { recursive: true });
                }
                await new Promise(resolve => setTimeout(resolve, 1500));
            } catch (err) {
                console.error('[WhatsApp] Error clearing session:', err);
            }
        }

        // Do NOT destroy client here when !hasSession && client: that client is the one showing the QR
        // and waiting for scan.

        // If client is not initialized, initialize it now (server may have already started it on startup)
        if (!client) {
            console.log('[WhatsApp] Client not initialized - initializing now...');
            initializeWhatsApp();
        }

        // If QR code is already available (e.g. client was pre-initialized on server start), return immediately
        if (qrCodeData) {
            console.log('[WhatsApp] Returning QR code to client');
            return res.json({
                success: true,
                qr_code: qrCodeData,
                is_authenticated: false,
                message: 'Scan the QR code with WhatsApp to connect'
            });
        }

        // Short wait only (3s) so the request doesn't block; frontend will get QR via socket or poll again
        const maxShortWait = 6;
        for (let i = 0; i < maxShortWait; i++) {
            await new Promise(resolve => setTimeout(resolve, 500));
            if (qrCodeData) {
                console.log('[WhatsApp] QR code became available after short wait');
                return res.json({
                    success: true,
                    qr_code: qrCodeData,
                    is_authenticated: false,
                    message: 'Scan the QR code with WhatsApp to connect'
                });
            }
        }

        // QR not ready yet – return loading so frontend can show "Generating..." and poll or use socket
        console.log('[WhatsApp] QR code not ready yet - returning loading (client will get it via socket or next poll)');
        return res.json({
            success: false,
            loading: true,
            is_authenticated: false,
            message: 'Generating QR code... Please wait a moment or keep this tab open.',
            error: 'qr_loading'
        });
    } catch (error) {
        console.error('[WhatsApp] Error getting QR code:', error);
        res.status(500).json({
            success: false,
            error: error.message
        });
    }
});

/**
 * GET /api/whatsapp/status
 * Check WhatsApp connection status
 */
app.get('/api/whatsapp/status', async (req, res) => {
    try {
        // Check if session folder was deleted and reset if needed
        await checkAndResetIfSessionDeleted();
        
        const hasSession = hasAuthenticatedSession();

        // Check if client exists and is ready
        if (isAuthenticated && isReady && client) {
            const payload = {
                success: true,
                is_connected: true,
                is_authenticated: true,
                is_ready: true,
                has_session: hasSession,
                message: 'Connected to WhatsApp'
            };
        try {
            const myId = getMyContactId();
            if (myId) {
                payload.my_contact_id = myId;
                payload.my_name = (client.info && client.info.pushname) || null;
            }
        } catch (e) { /* ignore */ }
            return res.json(payload);
        }

        // Authenticated but not ready yet (client still initializing; chats API may not work yet)
        if (isAuthenticated && !isReady && client) {
            return res.json({
                success: true,
                is_connected: false,
                is_authenticated: true,
                is_ready: false,
                has_session: hasSession,
                message: 'Connected to WhatsApp (initializing...)'
            });
        }

        // Session exists but client not authenticated yet - restoring
        if (hasSession && !isAuthenticated && client) {
            return res.json({
                success: true,
                is_connected: false,
                is_authenticated: false,
                is_ready: false,
                has_session: true,
                message: 'Session found - restoring connection...'
            });
        }

        // Session exists but no client initialized yet
        if (hasSession && !client) {
            return res.json({
                success: true,
                is_connected: false,
                is_authenticated: false,
                is_ready: false,
                has_session: true,
                message: 'Session found - initializing client...'
            });
        }

        return res.json({
            success: true,
            is_connected: false,
            is_authenticated: false,
            is_ready: false,
            has_session: hasSession,
            message: hasSession ? 'Session found - connecting...' : 'QR code authentication required'
        });
    } catch (error) {
        console.error('[WhatsApp] Error checking status:', error);
        res.status(500).json({
            success: false,
            error: error.message
        });
    }
});

/**
 * POST /api/whatsapp/initialize
 * Initialize WhatsApp service
 */
app.post('/api/whatsapp/initialize', async (req, res) => {
    try {
        if (!client) {
            initializeWhatsApp();
        }

        const hasSession = hasAuthenticatedSession();

        if (isAuthenticated && isReady) {
            return res.json({
                success: true,
                message: 'WhatsApp service initialized and connected'
            });
        }

        if (hasSession) {
            return res.json({
                success: true,
                message: 'WhatsApp service initialized. Session found, attempting to restore connection.'
            });
        }

        return res.json({
            success: true,
            message: 'WhatsApp service initialized. QR code authentication required.'
        });
    } catch (error) {
        console.error('[WhatsApp] Error initializing:', error);
        res.status(500).json({
            success: false,
            error: error.message
        });
    }
});

/**
 * POST /api/whatsapp/contacts
 * Get WhatsApp contacts/chats
 */
app.post('/api/whatsapp/contacts', async (req, res) => {
    // Allow up to 10 minutes for getChats() when user has 10k+ chats (no server-side timeout)
    req.setTimeout(600000);
    res.setTimeout(600000);
    try {
        // Check if session folder was deleted and reset if needed
        await checkAndResetIfSessionDeleted();

        if (req.body && req.body.reset_chat_list_retry) {
            chatListBackgroundDisabled = false;
            chatsCacheConsecutiveFailures = 0;
            chatsCacheLastLoadError = null;
        }

        if (!isReady || !client) {
            return res.status(400).json({
                success: false,
                error: 'WhatsApp not connected. Please authenticate first.'
            });
        }

        // During warmup, return loading unless getChats() already finished — then return contacts immediately.
        const timeSinceReady = readyAt ? (Date.now() - readyAt) : 0;
        const chatListReadyForUi = chatsCache && chatsCache.length > 0 && !chatsCacheLoading;
        if (timeSinceReady < CHATS_WARMUP_MS && !chatListReadyForUi) {
            const waitMs = CHATS_WARMUP_MS - timeSinceReady;
            const waitSeconds = Math.max(2, Math.ceil(waitMs / 1000));
            console.log(`[WhatsApp] Still in warmup (${waitMs}ms remaining) - returning loading so client can poll`);
            return res.json({
                success: true,
                count: 0,
                total_count: null,
                has_more: true,
                loading: true,
                wait_seconds: waitSeconds,
                contacts: [],
                message: `WhatsApp is initializing. Chats appear as soon as the list is ready (up to ~${waitSeconds}s).`
            });
        }

        if (chatListBackgroundDisabled && !chatsCache) {
            const hint =
                (chatsCacheLastLoadError ? `Could not load chats: ${chatsCacheLastLoadError}. ` : '') +
                'See logs/whatsapp_server.log. For very large accounts try WHATSAPP_PUPPETEER_PROTOCOL_TIMEOUT_MS=900000 and WHATSAPP_CHATS_WARMUP_MS=45000, then click Refresh.';
            return res.json({
                success: true,
                count: 0,
                total_count: 0,
                has_more: false,
                loading: false,
                contacts: [],
                chat_list_error: hint
            });
        }

        const limit = Math.min(Math.max(parseInt(req.body.limit, 10) || 20, 1), 100);
        const offset = Math.max(parseInt(req.body.offset, 10) || 0, 0);
        const now = Date.now();
        const cacheValid = chatsCache && (now - chatsCacheAt) < CHATS_CACHE_MS;

        if (chatsCacheLoading || (!cacheValid && !chatsCache) || (chatsCache && chatsCache.length === 0)) {
            if ((!cacheValid && !chatsCache) || (chatsCache && chatsCache.length === 0)) {
                if (!chatsCacheLoading) startBackgroundGetChats();
            }
            const warmupRemaining = readyAt ? Math.max(0, CHATS_WARMUP_MS - (Date.now() - readyAt)) : 0;
            const waitSeconds = warmupRemaining > 0 ? Math.max(2, Math.ceil(warmupRemaining / 1000)) : 5;
            return res.json({
                success: true,
                count: 0,
                total_count: null,
                has_more: true,
                loading: true,
                wait_seconds: waitSeconds,
                contacts: []
            });
        }

        const chats = chatsCache;
        if (!chatsListRowsCache && chats && chats.length) {
            try {
                rebuildChatsListRowsCacheFromChats(chats);
            } catch (e) {
                console.error('[WhatsApp] contacts: rebuild rows cache failed:', e.message);
            }
        }
        const allContacts = chatsListRowsCache || [];
        const contacts = allContacts.slice(offset, offset + limit);
        const totalCount = allContacts.length;
        const has_more = offset + contacts.length < totalCount;

        // If we had chats but all were filtered out (unexpected id format), tell the user to retry
        const rawCount = chats && chats.length ? chats.length : 0;
        if (rawCount > 0 && totalCount === 0) {
            console.warn('[WhatsApp] All', rawCount, 'chats were filtered out (contact_id could not be extracted). Returning loading so client can retry.');
            return res.json({
                success: true,
                count: 0,
                total_count: null,
                has_more: true,
                loading: true,
                contacts: [],
                warning: 'Chat list is still loading. Please wait a moment and click Refresh again.'
            });
        }

        console.log('[WhatsApp] Contacts loaded:', contacts.length, 'of', totalCount, '(offset', offset, ')');
        return res.json({
            success: true,
            count: contacts.length,
            total_count: totalCount,
            has_more: has_more,
            contacts: contacts
        });
    } catch (error) {
        console.error('[WhatsApp] Error getting contacts:', error);
        const msg = error.message || String(error);
        const isGetChatModelError = /undefined|update|getChatModel|Evaluation failed/i.test(msg);
        if (isGetChatModelError) {
            console.log('[WhatsApp] Returning empty chats so user can retry; WhatsApp Web may need more time or a library update.');
            return res.json({
                success: true,
                count: 0,
                contacts: [],
                warning: 'Chats could not be loaded yet. Ensure whatsapp-web.js is 1.34.6+ (npm install), restart the WhatsApp server, then click Refresh. If it still fails, log out and scan the QR code again.'
            });
        }
        res.status(500).json({
            success: false,
            error: msg
        });
    }
});

async function ensureChatsWarmupReady() {
    // Wait for warmup period after 'ready' before allowing chat operations (WhatsApp Web needs time to initialize)
    const timeSinceReady = readyAt ? (Date.now() - readyAt) : 0;
    if (timeSinceReady < CHATS_WARMUP_MS) {
        const waitMs = CHATS_WARMUP_MS - timeSinceReady;
        console.log(`[WhatsApp] Waiting ${waitMs}ms for WhatsApp Web to fully initialize before chat operations...`);
        await new Promise(r => setTimeout(r, waitMs));
    }
}

/** Short post-ready wait so getChatById/fetchMessages is less likely to race WhatsApp Web initialization. */
async function ensureMessagesMinReadyAfterReady() {
    if (!readyAt || MESSAGES_MIN_READY_MS <= 0) return;
    const elapsed = Date.now() - readyAt;
    if (elapsed >= MESSAGES_MIN_READY_MS) return;
    const wait = MESSAGES_MIN_READY_MS - elapsed;
    console.log(`[WhatsApp] Waiting ${wait}ms before message fetch (stabilize WhatsApp Web)`);
    await new Promise((r) => setTimeout(r, wait));
}

async function getChatsWithRetryAndCache() {
    const now = Date.now();
    if (chatsCache && (now - chatsCacheAt) < CHATS_CACHE_MS) {
        return chatsCache;
    }
    const maxTries = 18;
    const retryDelayMs = 8000;
    for (let attempt = 1; attempt <= maxTries; attempt++) {
        try {
            const chats = await client.getChats();
            if (chats && chats.length > 0) {
                chatsCache = chats;
                chatsCacheAt = Date.now();
                try {
                    rebuildChatsListRowsCacheFromChats(chats);
                } catch (e) {
                    console.error('[WhatsApp] rebuildChatsListRowsCacheFromChats:', e.message);
                    chatsListRowsCache = null;
                }
            }
            return chats || [];
        } catch (err) {
            const isRetryable = /undefined|update|getChatModel|Evaluation failed/i.test(String(err.message || ''));
            if (attempt < maxTries && isRetryable) {
                console.log(`[WhatsApp] getChats attempt ${attempt}/${maxTries} failed, retrying in ${retryDelayMs}ms...`, err.message);
                await new Promise(r => setTimeout(r, retryDelayMs));
            } else {
                throw err;
            }
        }
    }
    return [];
}

/**
 * Start getChats() in the background so the first page can be served once ready.
 * Used for large accounts (10k+ contacts) so the first request does not block/timeout.
 * Call after warmup. Safe to call when already loading (no-op).
 */
function startBackgroundGetChats() {
    if (chatListBackgroundDisabled || chatsCacheLoading || !client) return;
    const now = Date.now();
    if (chatsCache && (now - chatsCacheAt) < CHATS_CACHE_MS) return;
    chatsCacheLoading = true;
    console.log('[WhatsApp] Loading all chats in background (first page will appear when ready)...');
    getChatsWithRetryAndCache()
        .then((chats) => {
            console.log('[WhatsApp] Background getChats completed:', (chats || []).length, 'chats');
            chatsCacheConsecutiveFailures = 0;
            chatListBackgroundDisabled = false;
            chatsCacheLastLoadError = null;
        })
        .catch((err) => {
            console.error('[WhatsApp] Background getChats failed:', err.message);
            chatsCacheLastLoadError = err.message || String(err);
            chatsCacheConsecutiveFailures += 1;
            if (chatsCacheConsecutiveFailures >= 3) {
                chatListBackgroundDisabled = true;
                console.error(
                    '[WhatsApp] Chat list loading paused after repeated failures. Fix the underlying error (see log), adjust WHATSAPP_PUPPETEER_PROTOCOL_TIMEOUT_MS if needed, then click Refresh.'
                );
            }
        })
        .finally(() => {
            chatsCacheLoading = false;
        });
}

function buildChatPreview(chat) {
    const last = chat && chat.lastMessage ? chat.lastMessage : null;
    const idObj = chat && chat.id && typeof chat.id === 'object' ? chat.id : null;
    return {
        contact_id: serializeChatId(chat),
        name: chat.name || (idObj && idObj.user) || 'Unknown',
        is_group: !!chat.isGroup,
        unread_count: chat.unreadCount || 0,
        last_message_id: serializeMessageId(last),
        last_message: (last && last.body) ? String(last.body) : '',
        last_message_time: (last && typeof last.timestamp === 'number') ? last.timestamp : null,
        last_message_from_me: (last && typeof last.fromMe === 'boolean') ? last.fromMe : null,
        last_message_type: (last && last.type) ? String(last.type) : null,
        last_message_has_media: (last && typeof last.hasMedia === 'boolean') ? last.hasMedia : null
    };
}

/**
 * POST /api/whatsapp/resolve
 * Resolve a WhatsApp chat/contact ID by name/phone/id.
 * Body: { query: string, max_candidates?: number, include_groups?: boolean }
 */
app.post('/api/whatsapp/resolve', async (req, res) => {
    try {
        await checkAndResetIfSessionDeleted();
        if (!isReady || !client) {
            return res.status(400).json({ success: false, error: 'WhatsApp not connected. Please authenticate first.' });
        }

        await ensureChatsWarmupReady();

        const rawQuery = (req.body && req.body.query != null) ? String(req.body.query) : '';
        // Normalize: trim, collapse spaces, strip trailing " on whatsapp" etc. so we match the intended contact
        let query = rawQuery.trim().replace(/\s+/g, ' ');
        query = query.replace(/\s+(?:on|via|in)\s+(?:my\s+)?(?:whats\s*app|whatsapp)\s*$/i, '').trim();
        query = query.replace(/\s+please\s*$/i, '').trim();
        const includeGroups = (req.body && req.body.include_groups != null) ? !!req.body.include_groups : true;
        const maxCandidates = Math.min(Math.max(parseInt(req.body && req.body.max_candidates, 10) || 5, 1), 20);

        if (!query) {
            return res.status(400).json({ success: false, error: 'query is required' });
        }

        // If the user passed a serialized chat id already, accept it directly.
        if (/@(c\.us|g\.us)$/i.test(query) || /@broadcast$/i.test(query)) {
            try {
                const chat = await client.getChatById(query);
                return res.json({ success: true, match: buildChatPreview(chat), candidates: [] });
            } catch (e) {
                // fall through to search
            }
        }

        // Phone heuristic: if query contains enough digits, treat it as a phone number.
        const digits = query.replace(/[^\d]/g, '');
        if (digits && digits.length >= 7) {
            const contactId = `${digits}@c.us`;
            try {
                const chat = await client.getChatById(contactId);
                return res.json({ success: true, match: buildChatPreview(chat), candidates: [] });
            } catch (e) {
                // fall through to chats list search
            }
        }

        const chats = await getChatsWithRetryAndCache();
        const qLower = query.toLowerCase();
        const queryWords = qLower.split(/\s+/).filter(Boolean);
        const scored = [];

        for (const chat of (chats || [])) {
            try {
                if (!includeGroups && chat.isGroup) continue;
                const name = (chat.name || (chat.id && chat.id.user) || '').toString();
                const nameLower = name.toLowerCase();
                if (!nameLower) continue;
                let score = 0;
                if (nameLower === qLower) score += 1000;
                // Prefer "John Smith" over "Johnny" when user said "John": first word of name equals query
                const firstWord = nameLower.split(/\s+/)[0] || '';
                if (firstWord === qLower) score += 700;
                if (nameLower.startsWith(qLower)) score += 500;
                if (nameLower.includes(qLower)) score += 200;
                // Prefer 1:1 chats when query looks like a person name (1–2 words, no digits)
                const looksLikePerson = queryWords.length <= 2 && !/\d{5,}/.test(query);
                if (looksLikePerson && !chat.isGroup) score += 100;
                const ts = chat.lastMessage && typeof chat.lastMessage.timestamp === 'number' ? chat.lastMessage.timestamp : 0;
                score += Math.min(ts / 1000000, 50); // tiny recency tiebreaker
                if (score > 0) scored.push({ score, chat });
            } catch (e) { /* ignore */ }
        }

        scored.sort((a, b) => b.score - a.score);
        const candidates = scored.slice(0, maxCandidates).map(({ chat }) => buildChatPreview(chat));

        if (!candidates.length) {
            return res.status(404).json({ success: false, error: 'No matching contact/chat found', candidates: [] });
        }

        return res.json({ success: true, match: candidates[0], candidates });
    } catch (error) {
        console.error('[WhatsApp] Error resolving contact:', error);
        return res.status(500).json({ success: false, error: error.message || String(error) });
    }
});

/**
 * GET /api/whatsapp/unread/recent
 * Return the latest unread message preview per chat (one per contact).
 * Query params: limit (optional, default 50, max 200)
 */
app.get('/api/whatsapp/unread/recent', async (req, res) => {
    try {
        await checkAndResetIfSessionDeleted();
        if (!isReady || !client) {
            return res.status(400).json({ success: false, error: 'WhatsApp not connected. Please authenticate first.' });
        }

        await ensureChatsWarmupReady();

        const limit = Math.min(Math.max(parseInt(req.query.limit, 10) || 50, 1), 200);
        const chats = await getChatsWithRetryAndCache();

        const items = [];
        for (const chat of (chats || [])) {
            try {
                const unread = chat.unreadCount || 0;
                const last = chat.lastMessage || null;
                // Rule: only consider if there are unread messages, and the last message was NOT sent by me.
                if (!unread || !last || last.fromMe) continue;
                items.push(buildChatPreview(chat));
            } catch (e) { /* ignore */ }
        }

        items.sort((a, b) => (b.last_message_time || 0) - (a.last_message_time || 0));
        return res.json({ success: true, count: Math.min(items.length, limit), messages: items.slice(0, limit) });
    } catch (error) {
        console.error('[WhatsApp] Error getting unread recent:', error);
        return res.status(500).json({ success: false, error: error.message || String(error) });
    }
});

/**
 * POST /api/whatsapp/unread/last
 * Check if a specific contact has a new (unread) last message, and return it if so.
 * Body: { contact_id?: string, query?: string }
 */
app.post('/api/whatsapp/unread/last', async (req, res) => {
    try {
        await checkAndResetIfSessionDeleted();
        if (!isReady || !client) {
            return res.status(400).json({ success: false, error: 'WhatsApp not connected. Please authenticate first.' });
        }

        await ensureChatsWarmupReady();

        let contactId = (req.body && req.body.contact_id) ? String(req.body.contact_id).trim() : '';
        const query = (req.body && req.body.query != null) ? String(req.body.query).trim() : '';

        if (!contactId && query) {
            // First try phone/id heuristics, then chat list name match.
            if (/@(c\.us|g\.us)$/i.test(query) || /@broadcast$/i.test(query)) {
                contactId = query;
            } else {
                const digits = query.replace(/[^\d]/g, '');
                if (digits && digits.length >= 7) {
                    contactId = `${digits}@c.us`;
                } else {
                    const chats = await getChatsWithRetryAndCache();
                    const qLower = query.toLowerCase();
                    let best = null;
                    let bestScore = -1;
                    for (const chat of (chats || [])) {
                        const name = (chat.name || (chat.id && chat.id.user) || '').toString();
                        const nameLower = name.toLowerCase();
                        if (!nameLower) continue;
                        let score = 0;
                        if (nameLower === qLower) score += 1000;
                        if (nameLower.startsWith(qLower)) score += 500;
                        if (nameLower.includes(qLower)) score += 200;
                        const ts = chat.lastMessage && typeof chat.lastMessage.timestamp === 'number' ? chat.lastMessage.timestamp : 0;
                        score += Math.min(ts / 1000000, 50);
                        if (score > bestScore) {
                            bestScore = score;
                            best = chat;
                        }
                    }
                    const bestId = best ? serializeChatId(best) : null;
                    if (bestId) contactId = bestId;
                }
            }
        }

        if (!contactId) {
            return res.status(400).json({ success: false, error: 'contact_id or query is required' });
        }

        const chat = await client.getChatById(contactId);
        const preview = buildChatPreview(chat);

        // Determine "new message" according to spec:
        // - If last message is from me => no new messages
        // - Else if unread_count > 0 => new (unread) message exists
        const hasNew = !!(preview && preview.unread_count > 0 && preview.last_message_from_me === false);

        return res.json({
            success: true,
            has_new: hasNew,
            contact: { contact_id: preview.contact_id, name: preview.name, is_group: preview.is_group },
            message: hasNew ? {
                id: preview.last_message_id,
                body: preview.last_message,
                timestamp: preview.last_message_time,
                type: preview.last_message_type,
                has_media: preview.last_message_has_media
            } : null
        });
    } catch (error) {
        console.error('[WhatsApp] Error getting unread last:', error);
        return res.status(500).json({ success: false, error: error.message || String(error) });
    }
});

/**
 * GET /api/whatsapp/avatar
 * Fetch WhatsApp profile picture (cached on disk).
 * Query params:
 * - contact_id (required)
 * - refresh (optional, boolean)
 */
app.get('/api/whatsapp/avatar', async (req, res) => {
    try {
        if (!isReady || !client) {
            return res.status(400).json({ success: false, error: 'WhatsApp not connected. Please authenticate first.' });
        }
        const contactId = (req.query.contact_id || '').toString().trim();
        const refresh = String(req.query.refresh || '').toLowerCase() === 'true';
        if (!contactId) {
            return res.status(400).json({ success: false, error: 'contact_id is required' });
        }
        const cacheKey = sanitizeAvatarCacheKey(contactId);
        const cacheFile = path.join(AVATAR_DIR, `${cacheKey}.json`);
        if (!refresh && fs.existsSync(cacheFile)) {
            try {
                const cached = JSON.parse(fs.readFileSync(cacheFile, 'utf8'));
                if (cached && cached.avatar_url) {
                    return res.json({ success: true, avatar_url: cached.avatar_url });
                }
            } catch (e) {
                // ignore cache parse errors
            }
        }
        
        const url = await client.getProfilePicUrl(contactId);
        if (!url) {
            return res.json({ success: true, avatar_url: null });
        }
        
        // Proxy to base64 to avoid CORS/hotlinking issues (browser-like headers so CDN allows the request)
        const resp = await fetch(url, {
            headers: {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8'
            }
        });
        if (!resp.ok) {
            return res.json({ success: true, avatar_url: null });
        }
        const buf = Buffer.from(await resp.arrayBuffer());
        const contentType = (resp.headers.get('content-type') || 'image/jpeg').split(';')[0].trim();
        const base64 = buf.toString('base64');
        const avatarUrl = `data:${contentType};base64,${base64}`;
        
        try {
            fs.writeFileSync(cacheFile, JSON.stringify({ avatar_url: avatarUrl }), 'utf8');
        } catch (e) {
            // ignore cache write errors
        }
        
        return res.json({ success: true, avatar_url: avatarUrl });
    } catch (error) {
        const em = error && error.message ? String(error.message) : '';
        if (/waitForChatLoading|isNewsletter/i.test(em)) {
            logWWebDegradedModeBanner(/isNewsletter/i.test(em) ? 'isNewsletter' : 'waitForChatLoading');
        }
        console.error('[WhatsApp] Error fetching avatar:', error);
        res.status(500).json({ success: false, error: error.message || String(error) });
    }
});

/**
 * Fallback: get profile pic as base64 using ProfilePicThumb (avoids broken ProfilePic.profilePicFind/requestProfilePicFromServer isNewsletter path).
 * Returns base64 string or null. Uses client.pupPage.evaluate with window.WWebJS.getProfilePicThumbToBase64.
 */
async function getProfilePicThumbBase64(contactId) {
    if (!client || !client.pupPage) return null;
    try {
        const base64 = await client.pupPage.evaluate(async (contactId) => {
            if (typeof window.Store === 'undefined' || !window.Store.WidFactory || !window.WWebJS || typeof window.WWebJS.getProfilePicThumbToBase64 !== 'function') return null;
            const chatWid = window.Store.WidFactory.createWid(contactId);
            return await window.WWebJS.getProfilePicThumbToBase64(chatWid);
        }, contactId);
        return base64 && typeof base64 === 'string' ? base64 : null;
    } catch (e) {
        return null;
    }
}

/**
 * GET /api/whatsapp/avatar/me
 * Serve the logged-in WhatsApp account's profile picture (no contact_id needed).
 */
app.get('/api/whatsapp/avatar/me', async (req, res) => {
    try {
        if (!isReady || !client) {
            return res.status(400).send();
        }
        const contactId = getMyContactId();
        if (!contactId) {
            console.warn('[WhatsApp] Avatar/me: getMyContactId() returned null (client.info.wid not set?)');
            return res.status(404).send();
        }
        const refresh = String(req.query.refresh || '').toLowerCase() === 'true';
        const cacheKey = sanitizeAvatarCacheKey(contactId);
        const cacheFile = path.join(AVATAR_DIR, `${cacheKey}.json`);
        let avatarUrl = null;
        if (!refresh && fs.existsSync(cacheFile)) {
            try {
                const cached = JSON.parse(fs.readFileSync(cacheFile, 'utf8'));
                avatarUrl = cached && cached.avatar_url ? cached.avatar_url : null;
            } catch (e) { /* ignore */ }
        }
        if (!avatarUrl) {
            let url = null;
            try {
                url = await client.getProfilePicUrl(contactId);
            } catch (e) {
                // WhatsApp Web API can throw (e.g. "Cannot read properties of undefined (reading 'isNewsletter')") when their internal API changes
                const em = e && e.message ? String(e.message) : '';
                if (/waitForChatLoading/i.test(em)) logWWebDegradedModeBanner('waitForChatLoading');
                else if (/isNewsletter/i.test(em)) logWWebDegradedModeBanner('isNewsletter');
                if (!suppressWWebKnownBreakagePerRequestLog(em)) {
                    if (isWWebKnownBreakageMessage(em)) {
                        console.warn('[WhatsApp] Avatar/me: getProfilePicUrl failed:', wwebErrorFirstLine(em));
                    } else {
                        console.warn('[WhatsApp] Avatar/me: getProfilePicUrl threw, trying contact fallback:', e && e.message);
                    }
                }
                try {
                    const contact = await client.getContactById(contactId);
                    if (contact) url = await contact.getProfilePicUrl();
                } catch (e2) { /* ignore */ }
            }
            if (!url) {
                try {
                    const contact = await client.getContactById(contactId);
                    if (contact) url = await contact.getProfilePicUrl();
                } catch (e) { /* ignore */ }
            }
            if (!url) {
                // Fallback: use ProfilePicThumb (getProfilePicThumbToBase64) - avoids broken ProfilePic isNewsletter path
                const thumbBase64 = await getProfilePicThumbBase64(contactId);
                if (thumbBase64) {
                    avatarUrl = `data:image/jpeg;base64,${thumbBase64}`;
                    try {
                        fs.writeFileSync(cacheFile, JSON.stringify({ avatar_url: avatarUrl }), 'utf8');
                    } catch (e) { /* ignore */ }
                    const buf = Buffer.from(thumbBase64, 'base64');
                    res.set('Cache-Control', 'private, max-age=86400');
                    res.type('image/jpeg');
                    return res.send(buf);
                }
                if (wwebDegradedBannerLogged) {
                    if (!wwebDegradedAvatarBulkWarned) {
                        wwebDegradedAvatarBulkWarned = true;
                        console.warn(
                            '[WhatsApp] Avatar/me: no profile pic (WA Web mismatch; suppressing further missing-avatar lines until next ready)'
                        );
                    }
                } else {
                    console.warn(
                        '[WhatsApp] Avatar/me: no profile pic URL for contactId=',
                        contactId,
                        '(privacy or WhatsApp Web API may block profile pics)'
                    );
                }
                return res.status(404).send();
            }
            const resp = await fetch(url, {
                headers: {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8'
                }
            });
            if (!resp.ok) {
                console.warn('[WhatsApp] Avatar/me: fetch profile pic failed status=', resp.status, 'for contactId=', contactId);
                return res.status(404).send();
            }
            const buf = Buffer.from(await resp.arrayBuffer());
            const contentType = (resp.headers.get('content-type') || 'image/jpeg').split(';')[0].trim();
            const base64 = buf.toString('base64');
            avatarUrl = `data:${contentType};base64,${base64}`;
            try {
                fs.writeFileSync(cacheFile, JSON.stringify({ avatar_url: avatarUrl }), 'utf8');
            } catch (e) { /* ignore */ }
            res.set('Cache-Control', 'private, max-age=86400');
            res.type(contentType);
            return res.send(buf);
        }
        const match = /^data:([^;,]+)(?:;base64)?,(.+)$/.exec(avatarUrl);
        if (!match) {
            try { fs.unlinkSync(cacheFile); } catch (e) { /* ignore */ }
            return res.status(404).send();
        }
        let buf;
        try {
            buf = Buffer.from(match[2], 'base64');
        } catch (e) {
            console.warn('[WhatsApp] Avatar/me: invalid base64 in cache, clearing cache file');
            try { fs.unlinkSync(cacheFile); } catch (e2) { /* ignore */ }
            return res.status(404).send();
        }
        const contentType = match[1].trim().split(';')[0] || 'image/jpeg';
        res.set('Cache-Control', 'private, max-age=86400');
        res.type(contentType);
        return res.send(buf);
    } catch (error) {
        console.error('[WhatsApp] Error serving me avatar:', error);
        res.status(500).send();
    }
});

/**
 * GET /api/whatsapp/avatar/image
 * Serve avatar as raw image (avoids huge base64 in JSON / data URL display issues).
 * Query params: contact_id (required), refresh (optional)
 */
app.get('/api/whatsapp/avatar/image', async (req, res) => {
    try {
        if (!isReady || !client) {
            return res.status(400).send();
        }
        const contactId = (req.query.contact_id || '').toString().trim();
        const refresh = String(req.query.refresh || '').toLowerCase() === 'true';
        if (!contactId) {
            return res.status(400).send();
        }
        const cacheKey = sanitizeAvatarCacheKey(contactId);
        const cacheFile = path.join(AVATAR_DIR, `${cacheKey}.json`);
        let avatarUrl = null;
        if (!refresh && fs.existsSync(cacheFile)) {
            try {
                const cached = JSON.parse(fs.readFileSync(cacheFile, 'utf8'));
                avatarUrl = cached && cached.avatar_url ? cached.avatar_url : null;
            } catch (e) { /* ignore */ }
        }
        if (!avatarUrl) {
            let url = null;
            try {
                url = await client.getProfilePicUrl(contactId);
            } catch (e) {
                const em = e && e.message ? String(e.message) : '';
                if (/waitForChatLoading/i.test(em)) logWWebDegradedModeBanner('waitForChatLoading');
                else if (/isNewsletter/i.test(em)) logWWebDegradedModeBanner('isNewsletter');
                if (!suppressWWebKnownBreakagePerRequestLog(em)) {
                    if (isWWebKnownBreakageMessage(em)) {
                        console.warn('[WhatsApp] Avatar/image: getProfilePicUrl failed:', wwebErrorFirstLine(em));
                    } else {
                        console.warn('[WhatsApp] Avatar/image: getProfilePicUrl threw, trying contact fallback:', e && e.message);
                    }
                }
                try {
                    const contact = await client.getContactById(contactId);
                    if (contact) url = await contact.getProfilePicUrl();
                } catch (e2) { /* ignore */ }
            }
            if (!url) {
                try {
                    const contact = await client.getContactById(contactId);
                    if (contact) url = await contact.getProfilePicUrl();
                } catch (e) { /* ignore */ }
            }
            if (!url) {
                const thumbBase64 = await getProfilePicThumbBase64(contactId);
                if (thumbBase64) {
                    avatarUrl = `data:image/jpeg;base64,${thumbBase64}`;
                    try {
                        fs.writeFileSync(cacheFile, JSON.stringify({ avatar_url: avatarUrl }), 'utf8');
                    } catch (e) { /* ignore */ }
                    const buf = Buffer.from(thumbBase64, 'base64');
                    res.set('Cache-Control', 'private, max-age=86400');
                    res.type('image/jpeg');
                    return res.send(buf);
                }
                if (wwebDegradedBannerLogged) {
                    if (!wwebDegradedAvatarBulkWarned) {
                        wwebDegradedAvatarBulkWarned = true;
                        console.warn(
                            '[WhatsApp] Avatar/image: no profile pic (WA Web mismatch; suppressing further missing-avatar lines until next ready)'
                        );
                    }
                } else {
                    console.warn('[WhatsApp] Avatar/image: no profile pic URL for contactId=', contactId);
                }
                return res.status(404).send();
            }
            const resp = await fetch(url, {
                headers: {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8'
                }
            });
            if (!resp.ok) {
                console.warn('[WhatsApp] Avatar/image: fetch failed status=', resp.status, 'contactId=', contactId);
                return res.status(404).send();
            }
            const buf = Buffer.from(await resp.arrayBuffer());
            const contentType = (resp.headers.get('content-type') || 'image/jpeg').split(';')[0].trim();
            const base64 = buf.toString('base64');
            avatarUrl = `data:${contentType};base64,${base64}`;
            try {
                fs.writeFileSync(cacheFile, JSON.stringify({ avatar_url: avatarUrl }), 'utf8');
            } catch (e) { /* ignore */ }
            res.set('Cache-Control', 'private, max-age=86400');
            res.type(contentType);
            return res.send(buf);
        }
        // Parse data URL and serve as raw image (so browser gets a normal image response)
        const match = /^data:([^;,]+)(?:;base64)?,(.+)$/.exec(avatarUrl);
        if (!match) {
            try { fs.unlinkSync(cacheFile); } catch (e) { /* ignore */ }
            return res.status(404).send();
        }
        let buf;
        try {
            buf = Buffer.from(match[2], 'base64');
        } catch (e) {
            try { fs.unlinkSync(cacheFile); } catch (e2) { /* ignore */ }
            return res.status(404).send();
        }
        const contentType = match[1].trim().split(';')[0] || 'image/jpeg';
        res.set('Cache-Control', 'private, max-age=86400');
        res.type(contentType);
        return res.send(buf);
    } catch (error) {
        console.error('[WhatsApp] Error serving avatar image:', error);
        res.status(500).send();
    }
});

/**
 * POST /api/whatsapp/messages
 * Get messages for a specific contact/chat
 */
app.post('/api/whatsapp/messages', async (req, res) => {
    // Allow up to 10 minutes for fetchMessages when chat has hundreds of messages (prioritize displaying messages)
    req.setTimeout(600000);
    res.setTimeout(600000);
    try {
        // Check if session folder was deleted and reset if needed
        await checkAndResetIfSessionDeleted();
        
        if (!isReady || !client) {
            return res.status(400).json({
                success: false,
                error: 'WhatsApp not connected. Please authenticate first.'
            });
        }

        await ensureMessagesMinReadyAfterReady();

        const { contact_id, limit = 50, include_media, before_id, before_timestamp } = req.body;
        const fetchLimit = Math.min(Math.max(parseInt(limit, 10) || 30, 1), 100);
        const loadOlder = before_id != null && before_timestamp != null;

        if (!contact_id) {
            return res.status(400).json({
                success: false,
                error: 'contact_id is required'
            });
        }

        const maxTries = 18;
        let chat = null;
        let messages = null;
        let resolvedContactId = String(contact_id).trim();
        let lastErr = null;
        /** True when load-older pagination hit the start of stored history (see fetchOlderMessagesThanCursor). */
        let loadOlderExhausted = false;

        // Fast path: reuse Chat from getChats() cache only when fetchMessages actually returns rows.
        // If we accept an empty [] from the cached object, we skip getChatById entirely — that was breaking history
        // (whatsapp-web often returns [] briefly or for a stale Chat reference until the same chat is resolved by id).
        // Do not use cache for scroll-up (older) loads — fetchMessages(limit) is newest-N-only; see fetchOlderMessagesThanCursor.
        const cachedChat = !loadOlder && findCachedChatByContactId(contact_id);
        if (cachedChat) {
            try {
                const requestLimit = fetchLimit;
                const fetched = await cachedChat.fetchMessages({ limit: requestLimit });
                if (fetched && fetched.length > 0) {
                    messages = fetched;
                    chat = cachedChat;
                    resolvedContactId = serializeChatId(cachedChat) || resolvedContactId;
                    console.log('[WhatsApp] Messages via chats cache for', resolvedContactId, 'count=', fetched.length);
                } else {
                    messages = null;
                    chat = null;
                }
            } catch (e) {
                lastErr = e;
                const em = e && e.message ? String(e.message) : '';
                if (/waitForChatLoading/i.test(em)) logWWebDegradedModeBanner('waitForChatLoading');
                else if (/isNewsletter/i.test(em)) logWWebDegradedModeBanner('isNewsletter');
                if (!suppressWWebKnownBreakagePerRequestLog(em)) {
                    if (isWWebKnownBreakageMessage(em)) {
                        console.warn(
                            '[WhatsApp] fetchMessages on cached chat failed, falling back to getChatById:',
                            wwebErrorFirstLine(em)
                        );
                    } else {
                        console.warn('[WhatsApp] fetchMessages on cached chat failed, falling back to getChatById:', e && e.message);
                    }
                }
                chat = null;
                messages = null;
            }
        }

        if (!chat) {
            let idCandidates = await contactIdCandidatesWithLookup(contact_id);
            if (!idCandidates || !idCandidates.length) {
                idCandidates = [String(contact_id).trim()];
            }
            resolvedContactId = idCandidates[0] || resolvedContactId;
            for (let attempt = 1; attempt <= maxTries; attempt++) {
                let roundOk = false;
                for (const cid of idCandidates) {
                    try {
                        chat = await client.getChatById(cid);
                        if (loadOlder) {
                            const sid = serializeChatId(chat);
                            const olderRes = await fetchOlderMessagesThanCursor(
                                sid,
                                Number(before_timestamp),
                                fetchLimit
                            );
                            messages = olderRes.messages;
                            loadOlderExhausted = olderRes.exhausted;
                        } else {
                            messages = await chat.fetchMessages({ limit: fetchLimit });
                        }
                        resolvedContactId = cid;
                        roundOk = true;
                        break;
                    } catch (messagesErr) {
                        lastErr = messagesErr;
                    }
                }
                if (roundOk) break;
                const errStr = String(lastErr && lastErr.message ? lastErr.message : lastErr || '');
                // Live WA Web can ship JS incompatible with this whatsapp-web.js; retries never fix it.
                const isBrokenWWebPairing = /waitForChatLoading/i.test(errStr);
                const isRetryable =
                    !isBrokenWWebPairing &&
                    /undefined|update|getChatModel|Evaluation failed|timeout|Target closed|Session closed|detached|Navigation|Protocol error|WSS|ECONNRESET|WebSocket|net::|Execution context|not found|invalid wid|could not find|no chat/i.test(
                        errStr
                    );
                if (attempt < maxTries && isRetryable) {
                    const retryDelayMs = Math.min(6000, 450 * Math.pow(2, attempt - 1));
                    console.log(`[WhatsApp] getChatById/fetchMessages attempt ${attempt}/${maxTries} failed, retrying in ${retryDelayMs}ms...`, errStr);
                    await new Promise(r => setTimeout(r, retryDelayMs));
                } else if (lastErr) {
                    throw lastErr;
                } else {
                    throw new Error('getChatById failed for all contact_id variants');
                }
            }
        }
        if (!loadOlder && (!messages || messages.length === 0) && chat) {
            try {
                const lm = await chat.lastMessage;
                if (lm) {
                    messages = [lm];
                    console.warn('[WhatsApp] fetchMessages returned 0; using lastMessage as fallback for', resolvedContactId);
                }
            } catch (e) { /* ignore */ }
        }
        try { (messages || []).forEach(cacheWhatsAppMessage); } catch (e) {}

        if (loadOlder) {
            // Older pages are built in fetchOlderMessagesThanCursor (do not re-filter newest-N fetchMessages output).
            if (Array.isArray(messages)) {
                messages.sort((a, b) => (a.timestamp || 0) - (b.timestamp || 0));
            }
        } else if (Array.isArray(messages)) {
            messages.sort((a, b) => (a.timestamp || 0) - (b.timestamp || 0));
        }

        const preFormatCount = Array.isArray(messages) ? messages.length : 0;

        // Format messages for frontend (skip messages with no extractable id)
        const msgId = (m) => serializeMessageId(m);
        const formattedMessages = (await Promise.all((messages || []).map(async (msg) => {
            const id = msgId(msg);
            if (!id) return null;
            const baseMessage = {
                id,
                body: msg.body || '',
                from: msg.from || resolvedContactId,
                fromMe: msg.fromMe,
                timestamp: msg.timestamp,
                type: msg.type,
                hasMedia: msg.hasMedia,
                mediaUrl: null,
                mediaMimetype: null,
                mediaFilename: null
            };

            // Media can be large; default to on-demand streaming via /api/whatsapp/media/:messageId
            baseMessage.mediaFetchUrl = `/api/whatsapp/media/${id}?inline=1`;
            baseMessage.mediaDownloadUrl = `/api/whatsapp/media/${id}?download=true`;
            
            // Best-effort mimetype/filename without downloading the whole file
            if (msg.hasMedia) {
                try {
                    if (msg._data && msg._data.mimetype) {
                        baseMessage.mediaMimetype = msg._data.mimetype;
                    } else if (msg.type === 'image' || msg.type === 'sticker') {
                        baseMessage.mediaMimetype = (msg.type === 'sticker') ? 'image/webp' : 'image/jpeg';
                    } else if (msg.type === 'video' || msg.type === 'gif') {
                        baseMessage.mediaMimetype = 'video/mp4';
                    } else if (msg.type === 'audio' || msg.type === 'ptt') {
                        baseMessage.mediaMimetype = 'audio/ogg';
                    } else if (msg.type === 'document') {
                        baseMessage.mediaMimetype = 'application/octet-stream';
                    }
                    if (msg._data && msg._data.filename) {
                        baseMessage.mediaFilename = msg._data.filename;
                    }
                } catch (e) {
                    // ignore
                }
            }

            if (include_media && msg.hasMedia) {
                try {
                    const media = await msg.downloadMedia();
                    if (media) {
                        baseMessage.mediaUrl = `data:${media.mimetype};base64,${media.data}`;
                        baseMessage.mediaMimetype = media.mimetype;
                        baseMessage.mediaFilename = media.filename || null;
                    }
                } catch (mediaError) {
                    console.error('[WhatsApp] Error downloading media:', mediaError);
                    baseMessage.mediaUrl = null;
                }
            }

            return baseMessage;
        }))).filter(Boolean);

        // Sort by timestamp (oldest first for display)
        formattedMessages.sort((a, b) => a.timestamp - b.timestamp);

        if (preFormatCount > 0 && formattedMessages.length === 0) {
            console.warn('[WhatsApp] All', preFormatCount, 'raw messages dropped (serializeMessageId) for', resolvedContactId);
            return res.json({
                success: true,
                contact_id: resolvedContactId,
                contact_name: (chat && chat.name) || 'Unknown',
                count: 0,
                messages: [],
                warning: 'Messages are present but could not be read yet (WhatsApp Web format). Try Refresh messages in a moment.',
                reached_start: false,
                oldest_id: null,
                oldest_timestamp: null
            });
        }

        const reached_start = loadOlder
            ? loadOlderExhausted || formattedMessages.length === 0
            : formattedMessages.length === 0 || formattedMessages.length < fetchLimit;
        const oldest_id = formattedMessages.length > 0 ? formattedMessages[0].id : null;
        const oldest_timestamp = formattedMessages.length > 0 ? formattedMessages[0].timestamp : null;

        console.log('[WhatsApp] Messages loaded for', resolvedContactId, ':', formattedMessages.length, 'messages' + (loadOlder ? ' (older)' : ''));
        return res.json({
            success: true,
            contact_id: resolvedContactId,
            contact_name: chat.name || 'Unknown',
            count: formattedMessages.length,
            messages: formattedMessages,
            reached_start: reached_start,
            oldest_id: oldest_id,
            oldest_timestamp: oldest_timestamp
        });
    } catch (error) {
        const msg = error.message || String(error);
        if (/waitForChatLoading/i.test(msg)) {
            logWWebDegradedModeBanner('waitForChatLoading');
            return res.status(503).json({
                success: false,
                error:
                    'WhatsApp Web is incompatible with the current whatsapp-web.js build (waitForChatLoading). Add WHATSAPP_WEB_VERSION + WHATSAPP_WEB_VERSION_CACHE_TYPE=remote to .env (see .env.example), use the wppconnect-team wa-version HTML archive, restart the WhatsApp Node process, and scan QR again if needed.'
            });
        }
        if (isWWebKnownBreakageMessage(msg)) {
            // waitForChatLoading already returned above; here e.g. isNewsletter from fetchMessages
            if (/isNewsletter/i.test(msg)) logWWebDegradedModeBanner('isNewsletter');
            else logWWebDegradedModeBanner('waitForChatLoading');
            if (!suppressWWebKnownBreakagePerRequestLog(msg)) {
                console.warn('[WhatsApp] Error getting messages:', wwebErrorFirstLine(msg));
            }
        } else {
            console.error('[WhatsApp] Error getting messages:', error);
        }
        const isPageNotReady =
            !/waitForChatLoading/i.test(msg) &&
            /undefined|update|getChatModel|Evaluation failed|timeout|Target closed|Session closed|detached|Protocol error|Execution context/i.test(msg);
        if (isPageNotReady) {
            console.log('[WhatsApp] Returning empty messages so client can retry; chat may still be loading.');
            return res.status(200).json({
                success: true,
                contact_id: req.body.contact_id,
                contact_name: 'Unknown',
                count: 0,
                messages: [],
                warning: 'Chat is still loading. Please wait or try again.',
                reached_start: true,
                oldest_id: null,
                oldest_timestamp: null
            });
        }
        res.status(500).json({
            success: false,
            error: msg
        });
    }
});

/**
 * GET /api/whatsapp/media/:messageId
 * Download media from a message
 */
app.get('/api/whatsapp/media/:messageId', async (req, res) => {
    try {
        if (!isReady || !client) {
            return res.status(400).json({
                success: false,
                error: 'WhatsApp not connected. Please authenticate first.'
            });
        }

        const { messageId } = req.params;

        // Get message by ID
        let message = messageCacheById.get(String(messageId)) || null;
        if (!message) {
            try { message = await client.getMessageById(messageId); } catch (e) {}
        }

        // Fallback: try to parse chatId from serialized id and search recent messages in that chat
        if (!message) {
            try {
                const parts = String(messageId).split('_');
                const chatId = parts.length >= 3 ? parts[1] : null;
                if (chatId) {
                    const chat = await client.getChatById(chatId);
                    const recent = await chat.fetchMessages({ limit: 500 });
                    message = (recent || []).find(m => serializeMessageId(m) === messageId) || null;
                    if (message) cacheWhatsAppMessage(message);
                }
            } catch (e) {}
        }
        
        if (!message) {
            return res.status(404).json({
                success: false,
                error: 'Message not found (it may be too old to resolve). Try refreshing the chat and retry.'
            });
        }

        if (!message.hasMedia) {
            return res.status(400).json({
                success: false,
                error: 'Message does not contain media'
            });
        }

        // Download media
        const media = await message.downloadMedia();
        
        if (!media) {
            return res.status(500).json({
                success: false,
                error: 'Failed to download media'
            });
        }

        // Convert base64 to buffer
        const buffer = Buffer.from(media.data, 'base64');
        
        // Set appropriate headers (inline by default so <img>/<video> can display)
        const safeMime = media.mimetype ? String(media.mimetype) : 'application/octet-stream';
        const ext = safeMime.includes('/') ? safeMime.split('/')[1] : 'bin';
        const filename = media.filename || `media_${messageId}.${ext || 'bin'}`;
        res.setHeader('Content-Type', safeMime);
        const download = String(req.query.download || '').toLowerCase() === 'true';
        res.setHeader('Content-Disposition', buildContentDisposition(filename, download));
        res.setHeader('Accept-Ranges', 'bytes');

        // Support Range requests (needed by many browsers for <video> playback/seek)
        const size = buffer.length;
        const range = req.headers.range;
        if (range) {
            const m = /^bytes=(\d*)-(\d*)$/i.exec(String(range).trim());
            if (!m) {
                res.status(416);
                res.setHeader('Content-Range', `bytes */${size}`);
                return res.end();
            }
            const start = m[1] ? parseInt(m[1], 10) : 0;
            const end = m[2] ? parseInt(m[2], 10) : (size - 1);
            if (!Number.isFinite(start) || !Number.isFinite(end) || start < 0 || end < 0 || start > end || start >= size) {
                res.status(416);
                res.setHeader('Content-Range', `bytes */${size}`);
                return res.end();
            }
            const safeEnd = Math.min(end, size - 1);
            const chunk = buffer.subarray(start, safeEnd + 1);
            res.status(206);
            res.setHeader('Content-Range', `bytes ${start}-${safeEnd}/${size}`);
            res.setHeader('Content-Length', chunk.length);
            if (req.method === 'HEAD') return res.end();
            return res.send(chunk);
        }

        res.setHeader('Content-Length', size);
        if (req.method === 'HEAD') return res.end();
        return res.send(buffer);
    } catch (error) {
        console.error('[WhatsApp] Error downloading media:', error);
        res.status(500).json({
            success: false,
            error: error.message
        });
    }
});

/**
 * DELETE /api/whatsapp/message/:messageId
 * Delete a message
 */
app.delete('/api/whatsapp/message/:messageId', async (req, res) => {
    try {
        if (!isReady || !client) {
            return res.status(400).json({
                success: false,
                error: 'WhatsApp not connected. Please authenticate first.'
            });
        }

        const { messageId } = req.params;

        // Get message by ID
        const message = await client.getMessageById(messageId);
        
        if (!message) {
            return res.status(404).json({
                success: false,
                error: 'Message not found'
            });
        }

        // Check if message was sent by current user (can only delete own messages)
        if (!message.fromMe) {
            return res.status(403).json({
                success: false,
                error: 'You can only delete your own messages'
            });
        }

        // Delete message
        await message.delete(true); // true = delete for everyone

        return res.json({
            success: true,
            message: 'Message deleted successfully'
        });
    } catch (error) {
        console.error('[WhatsApp] Error deleting message:', error);
        res.status(500).json({
            success: false,
            error: error.message
        });
    }
});

/**
 * PUT /api/whatsapp/message/:messageId
 * Edit a message
 */
app.put('/api/whatsapp/message/:messageId', async (req, res) => {
    try {
        if (!isReady || !client) {
            return res.status(400).json({
                success: false,
                error: 'WhatsApp not connected. Please authenticate first.'
            });
        }

        const { messageId } = req.params;
        const { text } = req.body;

        if (!text) {
            return res.status(400).json({
                success: false,
                error: 'text is required'
            });
        }

        // Get message by ID
        const message = await client.getMessageById(messageId);
        
        if (!message) {
            return res.status(404).json({
                success: false,
                error: 'Message not found'
            });
        }

        // Check if message was sent by current user (can only edit own messages)
        if (!message.fromMe) {
            return res.status(403).json({
                success: false,
                error: 'You can only edit your own messages'
            });
        }

        // Edit message
        const editedMessage = await message.edit(text);

        return res.json({
            success: true,
            message: 'Message edited successfully',
            message_id: serializeMessageId(editedMessage),
            body: editedMessage.body
        });
    } catch (error) {
        console.error('[WhatsApp] Error editing message:', error);
        res.status(500).json({
            success: false,
            error: error.message
        });
    }
});

/**
 * POST /api/whatsapp/send
 * Send a WhatsApp message
 */
app.post('/api/whatsapp/send', async (req, res) => {
    try {
        if (!isReady || !client) {
            return res.status(400).json({
                success: false,
                error: 'WhatsApp not connected. Please authenticate first.'
            });
        }

        const { contact_id, text } = req.body;

        if (!contact_id || !text) {
            return res.status(400).json({
                success: false,
                error: 'contact_id and text are required'
            });
        }

        // Send message. Use sendSeen: false to avoid WhatsApp Web bug (TypeError: Cannot read properties of undefined (reading 'markedUnread')) in sendSeen
        const message = await client.sendMessage(contact_id, text, { sendSeen: false });

        return res.json({
            success: true,
            message: 'Message sent successfully',
            message_id: serializeMessageId(message)
        });
    } catch (error) {
        console.error('[WhatsApp] Error sending message:', error);
        res.status(500).json({
            success: false,
            error: error.message
        });
    }
});

/**
 * POST /api/whatsapp/open
 * Emit an `open_url` event to client(s) so the browser can open the URL locally.
 * Body: { url: string, socket_id?: string }
 */
app.post('/api/whatsapp/open', (req, res) => {
    try {
        const { url, socket_id } = req.body || {};
        if (!url) return res.status(400).json({ success: false, error: 'url required' });

        let parsed;
        try { parsed = new URL(String(url)); } catch (e) {
            return res.status(400).json({ success: false, error: 'invalid url' });
        }
        if (!['http:', 'https:'].includes(parsed.protocol)) {
            return res.status(400).json({ success: false, error: 'only http/https allowed' });
        }

        const payload = { url: parsed.toString() };

        if (socket_id) {
            io.to(String(socket_id)).emit('open_url', payload);
        } else {
            io.emit('open_url', payload);
        }

        return res.json({ success: true, emitted_to: socket_id || 'all' });
    } catch (err) {
        console.error('[WhatsApp] Error in /api/whatsapp/open:', err);
        return res.status(500).json({ success: false, error: err.message });
    }
});

// Health check endpoint
app.get('/health', (req, res) => {
    res.json({ status: 'ok', service: 'whatsapp-server' });
});

// Socket.IO connection handling
io.on('connection', (socket) => {
    console.log('[WhatsApp] Client connected via WebSocket:', socket.id);
    
    // Send current status when client connects
    const hasSession = hasAuthenticatedSession();
    const payload = {
        is_connected: isReady && isAuthenticated,
        is_authenticated: isAuthenticated,
        is_ready: isReady && isAuthenticated,
        has_session: hasSession,
        message: isReady ? 'Connected to WhatsApp' : (hasSession ? 'Session found - connecting...' : 'QR code authentication required')
    };
    try {
        const myId = getMyContactId();
        if (myId) {
            payload.my_contact_id = myId;
            payload.my_name = (client.info && client.info.pushname) || null;
        }
    } catch (e) { /* ignore */ }
    socket.emit('whatsapp_status', payload);

    /**
     * Load chat history over the same Socket.IO connection (avoids extra HTTP hop through the chat proxy).
     * Delegates to POST /api/whatsapp/messages so behavior matches REST exactly.
     */
    socket.on('whatsapp_get_messages', async (payload, ack) => {
        const reply = (json) => {
            if (typeof ack === 'function') ack(json);
            else socket.emit('whatsapp_messages_result', json);
        };
        try {
            const res = await fetch(`http://127.0.0.1:${PORT}/api/whatsapp/messages`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload && typeof payload === 'object' ? payload : {})
            });
            const json = await res.json().catch(() => ({ success: false, error: 'Invalid response from messages API' }));
            reply(json);
        } catch (e) {
            console.error('[WhatsApp] whatsapp_get_messages:', e && e.message);
            reply({ success: false, error: e.message || String(e) });
        }
    });

    socket.on('disconnect', () => {
        console.log('[WhatsApp] Client disconnected from WebSocket:', socket.id);
    });
});

// Start server first so port 3000 is bound immediately (before heavy WhatsApp/Puppeteer init)
server.listen(PORT, '0.0.0.0', () => {
    console.log(`[WhatsApp Server] Server running on http://0.0.0.0:${PORT}`);
    console.log(`[WhatsApp Server] WebSocket server ready`);
    console.log(`[WhatsApp Server] WhatsApp client initializing...`);
    // Defer WhatsApp client init so the process is listening on port 3000 right away
    setImmediate(() => initializeWhatsApp());
});

// Global error handlers to avoid silent exits and get better diagnostics
process.on('unhandledRejection', (reason, promise) => {
    console.error('[WhatsApp] Unhandled Rejection:', reason);
});

process.on('uncaughtException', (err) => {
    console.error('[WhatsApp] Uncaught Exception:', err);
});

// Graceful shutdown
process.on('SIGINT', async () => {
    console.log('\n[WhatsApp Server] Shutting down...');
    if (client) {
        await client.destroy();
    }
    process.exit(0);
});

