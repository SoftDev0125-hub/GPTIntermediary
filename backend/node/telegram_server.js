/**
 * Telegram Node.js Backend Server
 * Handles Telegram authentication and operations using GramJS (telegram package)
 */

// Load environment variables from .env file
require('dotenv').config();

const express = require('express');
const { TelegramClient } = require('telegram');
const { StringSession } = require('telegram/sessions');
const { Api } = require('telegram/tl');
const { NewMessage, Raw } = require('telegram/events');
const path = require('path');
const fs = require('fs');
const cors = require('cors');
const http = require('http');
const { Server } = require('socket.io');

const app = express();
const server = http.createServer(app);
const io = new Server(server, {
    cors: {
        origin: "*",
        methods: ["GET", "POST"]
    }
});

const PORT = 3001; // Different port from WhatsApp server

// Middleware - CORS with explicit configuration
app.use(cors({
    origin: '*',
    methods: ['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'],
    allowedHeaders: ['Content-Type', 'Authorization'],
    credentials: false
}));

// Handle preflight OPTIONS requests
app.options('*', cors());

app.use(express.json());

// Health check endpoint - must be defined before other routes
app.get('/health', (req, res) => {
    res.json({ status: 'ok', service: 'telegram-server' });
});

// Telegram client instance
let client = null;
let isAuthenticated = false;
let isReady = false;
let authCodeRequired = false;
let authPasswordRequired = false;
let authPhoneCode = null;
let authPhoneNumber = null;
let messageHandlerInitialized = false;
let receiptHandlerInitialized = false;
// In-memory entity cache (id -> full entity with accessHash)
// Helps avoid "Could not find the input entity" errors when resolving by numeric id alone.
const entityCacheById = new Map();

/**
 * Normalize GramJS message date into a unix timestamp (seconds).
 * GramJS may expose dates as JS Date, number (seconds), bigint, or string.
 */
function toUnixSeconds(dateValue) {
    if (!dateValue) return null;
    try {
        if (dateValue instanceof Date) {
            return Math.floor(dateValue.getTime() / 1000);
        }
        if (typeof dateValue === 'number') {
            // GramJS commonly uses seconds
            return Math.floor(dateValue);
        }
        if (typeof dateValue === 'bigint') {
            return Number(dateValue);
        }
        if (typeof dateValue === 'string') {
            const n = Number(dateValue);
            if (!Number.isNaN(n)) return Math.floor(n);
        }
        // Some objects might have a getTime()
        if (typeof dateValue === 'object' && typeof dateValue.getTime === 'function') {
            return Math.floor(dateValue.getTime() / 1000);
        }
    } catch (e) {
        // ignore and fall through
    }
    return null;
}

function truncateText(value, maxLen) {
    if (value === null || value === undefined) return '';
    const str = String(value);
    if (!maxLen || typeof maxLen !== 'number' || maxLen <= 0) return str;
    if (str.length <= maxLen) return str;
    return str.slice(0, maxLen) + '…';
}

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
    // Avoid ridiculously long header values
    if (s.length > 180) s = s.slice(0, 180);
    return s;
}

function buildContentDisposition(filename, download) {
    const original = filename ? String(filename) : 'file';
    const safeAscii = sanitizeFilenameForHeader(original, 'file');
    // RFC 5987 encoding for UTF-8 filenames (ASCII-only header value)
    const encoded = encodeURIComponent(original);
    const type = download ? 'attachment' : 'inline';
    return `${type}; filename="${safeAscii}"; filename*=UTF-8''${encoded}`;
}

function guessMimeTypeFromFilename(filename) {
    if (!filename) return null;
    const name = String(filename).toLowerCase();
    const ext = name.includes('.') ? name.split('.').pop() : '';
    switch (ext) {
        case 'm4a':
            return 'audio/mp4';
        case 'mp3':
            return 'audio/mpeg';
        case 'wav':
            return 'audio/wav';
        case 'ogg':
            return 'audio/ogg';
        case 'opus':
            // Common for Telegram voice notes
            return 'audio/ogg';
        case 'webm':
            return 'audio/webm';
        case 'mp4':
            return 'video/mp4';
        case 'mov':
            return 'video/quicktime';
        case 'webp':
            return 'image/webp';
        case 'gif':
            return 'image/gif';
        case 'jpg':
        case 'jpeg':
            return 'image/jpeg';
        case 'png':
            return 'image/png';
        default:
            return null;
    }
}

function getTelegramMediaMeta(message) {
    const media = message && message.media ? message.media : null;
    if (!media) return { hasMedia: false, mimeType: null, filename: null };
    const className = String(media.className || '');
    if (!className || className.includes('MessageMediaEmpty')) {
        return { hasMedia: false, mimeType: null, filename: null };
    }

    // Only treat clearly downloadable media as "hasMedia" to avoid broken <img>/<video>
    if (!className.includes('Photo') && !className.includes('Document')) {
        return { hasMedia: false, mimeType: null, filename: null };
    }

    let mimeType = null;
    let filename = null;

    try {
        if (className.includes('Photo')) {
            mimeType = 'image/jpeg';
        } else if (className.includes('Document')) {
            const doc = media.document || media;
            mimeType = (doc && doc.mimeType) ? String(doc.mimeType) : (media.mimeType ? String(media.mimeType) : null);

            // filename can live in different places depending on GramJS object shape
            filename = media.fileName || doc.fileName || null;

            const attrs = (doc && Array.isArray(doc.attributes)) ? doc.attributes : (Array.isArray(media.attributes) ? media.attributes : []);
            const fnAttr = attrs.find(a => a && String(a.className || '') === 'DocumentAttributeFilename' && a.fileName);
            if (fnAttr && fnAttr.fileName) filename = String(fnAttr.fileName);
        }
    } catch (e) {
        // ignore
    }

    // Telegram animated stickers are commonly .tgs (gzipped Lottie JSON).
    // Ensure the MIME type is present so the frontend can render them properly.
    try {
        const lowerName = filename ? String(filename).toLowerCase() : '';
        if (lowerName.endsWith('.tgs')) {
            mimeType = 'application/x-tgsticker';
        }
    } catch (e) {}

    // If Telegram doesn't provide a reliable mimeType (common for documents),
    // infer it from the filename extension so browsers can play audio/video.
    try {
        const guessed = guessMimeTypeFromFilename(filename);
        const current = mimeType ? String(mimeType).split(';')[0].trim().toLowerCase() : '';
        if (guessed) {
            // Prefer guessed when mimeType is missing/generic, or obviously wrong for the extension
            if (!current || current === 'application/octet-stream' || (current === 'audio/mpeg' && String(filename || '').toLowerCase().endsWith('.m4a'))) {
                mimeType = guessed;
            }
        }
    } catch (e) {}

    return { hasMedia: true, mimeType: mimeType || null, filename: filename || null };
}

function peerToContactId(peer) {
    if (!peer || typeof peer !== 'object') return null;
    if ('userId' in peer && peer.userId !== undefined && peer.userId !== null) return String(peer.userId);
    if ('chatId' in peer && peer.chatId !== undefined && peer.chatId !== null) return String(peer.chatId);
    if ('channelId' in peer && peer.channelId !== undefined && peer.channelId !== null) return String(peer.channelId);
    return null;
}

async function getEntityForChatId(chatId) {
    const key = String(chatId || '').trim();
    if (!key) throw new Error('chat_id is required');
    if (entityCacheById.has(key)) return entityCacheById.get(key);

    // Best effort: direct getEntity (may fail if accessHash isn't known)
    try {
        const ent = await client.getEntity(key);
        if (ent && ent.id !== undefined && ent.id !== null) {
            entityCacheById.set(String(ent.id), ent);
        }
        entityCacheById.set(key, ent);
        return ent;
    } catch (e) {
        // Fall through to dialog seeding
    }

    // Seed cache from dialogs and retry
    try {
        const dialogs = await client.getDialogs({ limit: 200 });
        for (const d of dialogs || []) {
            try {
                const ent = d && d.entity ? d.entity : null;
                if (ent && ent.id !== undefined && ent.id !== null) {
                    entityCacheById.set(String(ent.id), ent);
                }
            } catch (e) {}
        }
    } catch (e) {}

    if (entityCacheById.has(key)) return entityCacheById.get(key);
    throw new Error(`Could not resolve chat entity for ${key}. Try Refresh to reload chats.`);
}

/**
 * Setup Telegram new-message handler (idempotent).
 * Must be callable from anywhere (e.g. after auth completes).
 */
function setupMessageHandler() {
    if (!client || !isReady) return;
    if (messageHandlerInitialized) return;
    messageHandlerInitialized = true;
    
    client.addEventHandler(async (event) => {
        try {
            const message = event.message;
            if (!message) return;
            
            console.log('[Telegram] New message received:', message.id);
            
            // Get chat info
            const chat = await client.getEntity(message.peerId);
            const sender = message.fromId ? await client.getEntity(message.fromId) : null;
            
            // Format message for frontend
            const formattedMessage = {
                id: message.id.toString(),
                body: message.message || '',
                from: sender ? (sender.id ? sender.id.toString() : '') : '',
                fromMe: message.out || false,
                timestamp: toUnixSeconds(message.date) ?? Math.floor(Date.now() / 1000),
                type: 'text',
                hasMedia: false,
                mediaUrl: null,
                mediaMimetype: null,
                mediaFilename: null,
                fileUrl: null,
                contact_id: chat.id ? chat.id.toString() : '',
                contact_name: chat.title || (chat.firstName ? `${chat.firstName} ${chat.lastName || ''}`.trim() : 'Unknown'),
                is_group: chat.className === 'Chat' || chat.className === 'Channel'
            };
            
            // Provide inline stream URL + best-effort mimetype/filename without downloading
            const meta = getTelegramMediaMeta(message);
            formattedMessage.hasMedia = meta.hasMedia;
            formattedMessage.mediaMimetype = meta.mimeType;
            formattedMessage.mediaFilename = meta.filename;
            if (formattedMessage.hasMedia) {
                formattedMessage.fileUrl = `/api/telegram/media/file?chat_id=${encodeURIComponent(formattedMessage.contact_id)}&message_id=${encodeURIComponent(formattedMessage.id)}`;
            }

            // Emit message immediately (media can be fetched on-demand via /api/telegram/media)
            io.emit('telegram_message', formattedMessage);
        } catch (error) {
            console.error('[Telegram] Error processing new message:', error);
        }
    }, new NewMessage({}));
}

/**
 * Setup Telegram receipt handler (idempotent).
 * Emits read receipts for outgoing messages (best-effort).
 */
function setupReceiptHandler() {
    if (!client || !isReady) return;
    if (receiptHandlerInitialized) return;
    receiptHandlerInitialized = true;

    client.addEventHandler((update) => {
        try {
            if (update instanceof Api.UpdateReadHistoryOutbox) {
                const contactId = peerToContactId(update.peer);
                if (!contactId) return;
                io.emit('telegram_receipt', {
                    kind: 'read',
                    contact_id: contactId,
                    max_id: String(update.maxId)
                });
                return;
            }
            if (update instanceof Api.UpdateReadChannelOutbox) {
                io.emit('telegram_receipt', {
                    kind: 'read',
                    contact_id: String(update.channelId),
                    max_id: String(update.maxId)
                });
            }
        } catch (e) {
            // do not crash on update parsing
        }
    }, new Raw({}));
}

// Session directory
// Keep session data at the project root so moving this file doesn't break existing sessions.
const PROJECT_ROOT = path.join(__dirname, '..', '..');
const SESSION_DIR = path.join(PROJECT_ROOT, 'telegram_session_node');
const SESSION_FILE = path.join(SESSION_DIR, 'session.txt');
const AVATAR_DIR = path.join(SESSION_DIR, 'avatars');

// Ensure session directory exists
if (!fs.existsSync(SESSION_DIR)) {
    fs.mkdirSync(SESSION_DIR, { recursive: true });
}
if (!fs.existsSync(AVATAR_DIR)) {
    fs.mkdirSync(AVATAR_DIR, { recursive: true });
}

// Get API credentials from environment variables
const API_ID = process.env.TELEGRAM_API_ID ? parseInt(process.env.TELEGRAM_API_ID) : null;
const API_HASH = process.env.TELEGRAM_API_HASH || null;
// GramJS expects apiCredentials in sendCode()
const API_CREDENTIALS = (API_ID && API_HASH) ? { apiId: API_ID, apiHash: API_HASH } : null;

// Load session if exists
let stringSession = '';
if (fs.existsSync(SESSION_FILE)) {
    stringSession = fs.readFileSync(SESSION_FILE, 'utf8').trim();
    console.log('[Telegram] Found existing session');
} else {
    console.log('[Telegram] No session found - authentication required');
}

/**
 * Initialize Telegram client
 */
function initializeTelegram() {
    if (client) {
        console.log('[Telegram] Client already initialized');
        return;
    }

    if (!API_ID || !API_HASH) {
        console.error('[Telegram] API_ID and API_HASH are required. Set TELEGRAM_API_ID and TELEGRAM_API_HASH environment variables.');
        return;
    }

    console.log('[Telegram] Initializing Telegram client...');

    // Create client with StringSession for session persistence
    client = new TelegramClient(
        new StringSession(stringSession),
        API_ID,
        API_HASH,
        {
            connectionRetries: 5,
        }
    );

    // Connect event
    client.on('connection', (update) => {
        console.log('[Telegram] Connection update:', update.className);
    });

    // Note: GramJS doesn't have a 'ready' event, we check authorization status instead

    // Authentication required event
    client.on('auth', async () => {
        console.log('[Telegram] Authentication required');
        isAuthenticated = false;
        isReady = false;
        authCodeRequired = true;
        
        io.emit('telegram_status', {
            is_connected: false,
            is_authenticated: false,
            auth_required: true,
            message: 'Authentication required'
        });
    });

    // Initialize the client
    (async () => {
        try {
            await client.connect();
            console.log('[Telegram] Client connected');
            
            // Check if already authorized
            if (await client.checkAuthorization()) {
                console.log('[Telegram] Already authorized');
                isAuthenticated = true;
                isReady = true;
                
                // Save session
                const sessionString = client.session.save();
                fs.writeFileSync(SESSION_FILE, sessionString);
                
                // Setup message handler
                setupMessageHandler();
                setupReceiptHandler();
                
                io.emit('telegram_status', {
                    is_connected: true,
                    is_authenticated: true,
                    message: 'Connected to Telegram'
                });
            } else {
                console.log('[Telegram] Not authorized - authentication required');
                authCodeRequired = true;
                io.emit('telegram_status', {
                    is_connected: false,
                    is_authenticated: false,
                    auth_required: true,
                    message: 'Authentication required'
                });
            }
        } catch (error) {
            console.error('[Telegram] Error initializing client:', error);
            io.emit('telegram_status', {
                is_connected: false,
                is_authenticated: false,
                error: error.message,
                message: 'Failed to initialize Telegram client'
            });
        }
    })();
}

// Initialize Telegram on server start (if API credentials are available)
if (API_ID && API_HASH) {
    initializeTelegram();
} else {
    console.warn('[Telegram] API credentials not found. Set TELEGRAM_API_ID and TELEGRAM_API_HASH environment variables.');
}

/**
 * GET /api/telegram/status
 * Check Telegram connection status
 */
app.get('/api/telegram/status', async (req, res) => {
    try {
        const hasSession = fs.existsSync(SESSION_FILE) && stringSession.length > 0;
        const hasCredentials = !!(API_ID && API_HASH);

        if (!hasCredentials) {
            return res.json({
                success: true,
                is_connected: false,
                is_authenticated: false,
                has_session: hasSession,
                has_api_credentials: false,
                message: 'API credentials required. Set TELEGRAM_API_ID and TELEGRAM_API_HASH environment variables.'
            });
        }

        if (isAuthenticated && isReady) {
            return res.json({
                success: true,
                is_connected: true,
                is_authenticated: true,
                has_session: hasSession,
                has_api_credentials: true,
                message: 'Connected to Telegram'
            });
        }

        if (hasSession && !isReady) {
            return res.json({
                success: true,
                is_connected: false,
                is_authenticated: false,
                has_session: true,
                has_api_credentials: true,
                auth_required: authCodeRequired,
                message: 'Session found - connecting...'
            });
        }

        return res.json({
            success: true,
            is_connected: false,
            is_authenticated: false,
            has_session: hasSession,
            has_api_credentials: true,
            auth_required: true,
            message: 'Authentication required'
        });
    } catch (error) {
        console.error('[Telegram] Error checking status:', error);
        res.status(500).json({
            success: false,
            error: error.message
        });
    }
});

/**
 * POST /api/telegram/auth/phone
 * Start authentication with phone number
 */
app.post('/api/telegram/auth/phone', async (req, res) => {
    try {
        console.log('[Telegram] Phone auth request received:', { body: req.body });
        
        if (!API_ID || !API_HASH) {
            console.error('[Telegram] API credentials missing');
            return res.status(400).json({
                success: false,
                error: 'API credentials not configured. Set TELEGRAM_API_ID and TELEGRAM_API_HASH environment variables.'
            });
        }

        const { phone_number } = req.body;

        if (!phone_number) {
            console.error('[Telegram] Phone number missing from request');
            return res.status(400).json({
                success: false,
                error: 'phone_number is required'
            });
        }

        // Validate phone number format (should start with +)
        if (!phone_number.startsWith('+')) {
            console.error('[Telegram] Invalid phone number format:', phone_number);
            return res.status(400).json({
                success: false,
                error: 'Phone number must include country code and start with + (e.g., +1234567890)'
            });
        }

        if (!client) {
            console.log('[Telegram] Client not initialized, initializing now...');
            initializeTelegram();
            // Wait a bit for client to initialize
            await new Promise(resolve => setTimeout(resolve, 2000));
        }

        if (!client) {
            console.error('[Telegram] Failed to initialize client');
            return res.status(500).json({
                success: false,
                error: 'Failed to initialize Telegram client'
            });
        }

        // Ensure client is connected before sending code
        if (!client.connected) {
            console.log('[Telegram] Client not connected, connecting now...');
            try {
                await client.connect();
                console.log('[Telegram] Client connected');
            } catch (connectError) {
                console.error('[Telegram] Error connecting client:', String(connectError));
                let connectErrorMsg = 'Failed to connect to Telegram';
                try {
                    if (connectError && typeof connectError === 'object' && 'message' in connectError) {
                        connectErrorMsg += ': ' + String(connectError.message);
                    } else if (connectError) {
                        connectErrorMsg += ': ' + String(connectError);
                    }
                } catch (e) {
                    // Use default message
                }
                return res.status(500).json({
                    success: false,
                    error: connectErrorMsg
                });
            }
        }

        try {
            console.log('[Telegram] ===== Starting sendCode =====');
            console.log('[Telegram] Phone number:', phone_number);
            console.log('[Telegram] Client connected:', client.connected);
            console.log('[Telegram] Client ready:', isReady);
            
            authPhoneNumber = phone_number;
            
            // sendCode returns a SentCode object in GramJS
            console.log('[Telegram] Calling client.sendCode...');
            // IMPORTANT: GramJS signature is sendCode(apiCredentials, phoneNumber, forceSMS?)
            const result = await client.sendCode(API_CREDENTIALS, phone_number);
            
            console.log('[Telegram] sendCode completed, result type:', typeof result);
            console.log('[Telegram] Result is null:', result === null);
            console.log('[Telegram] Result is undefined:', result === undefined);
            
            // Extract phoneCodeHash - GramJS SentCode object has phoneCodeHash property
            let phoneCodeHash = null;
            
            // Try the most common property names first
            if (result && typeof result === 'object') {
                console.log('[Telegram] Result is an object, extracting phoneCodeHash...');
                
                // Direct property access (most common in GramJS)
                if (result.phoneCodeHash !== undefined && result.phoneCodeHash !== null) {
                    phoneCodeHash = String(result.phoneCodeHash);
                    console.log('[Telegram] ✓ Found phoneCodeHash property:', phoneCodeHash.substring(0, 10) + '...');
                } 
                // Try snake_case variant
                else if (result.phone_code_hash !== undefined && result.phone_code_hash !== null) {
                    phoneCodeHash = String(result.phone_code_hash);
                    console.log('[Telegram] ✓ Found phone_code_hash property:', phoneCodeHash.substring(0, 10) + '...');
                }
                // Try accessing via 'in' operator
                else if ('phoneCodeHash' in result) {
                    const hash = result.phoneCodeHash;
                    if (hash !== undefined && hash !== null) {
                        phoneCodeHash = String(hash);
                        console.log('[Telegram] ✓ Found phoneCodeHash via in operator:', phoneCodeHash.substring(0, 10) + '...');
                    }
                }
                else if ('phone_code_hash' in result) {
                    const hash = result.phone_code_hash;
                    if (hash !== undefined && hash !== null) {
                        phoneCodeHash = String(hash);
                        console.log('[Telegram] ✓ Found phone_code_hash via in operator:', phoneCodeHash.substring(0, 10) + '...');
                    }
                }
                // Try to get all keys and find hash-like values
                else {
                    try {
                        const keys = Object.keys(result);
                        console.log('[Telegram] Result keys:', keys.join(', '));
                        
                        // Look for hash-like string values
                        for (const key of keys) {
                            try {
                                const value = result[key];
                                if (typeof value === 'string' && value.length > 10 && /^[a-zA-Z0-9_]+$/.test(value)) {
                                    phoneCodeHash = value;
                                    console.log('[Telegram] ✓ Found hash-like value in key:', key, ':', phoneCodeHash.substring(0, 10) + '...');
                                    break;
                                }
                            } catch (e) {
                                // Skip this key
                            }
                        }
                    } catch (keyError) {
                        console.error('[Telegram] Error getting keys:', String(keyError));
                    }
                }
            } else if (typeof result === 'string') {
                // Some versions might return just the hash
                phoneCodeHash = result;
                console.log('[Telegram] ✓ Result is a string (phoneCodeHash):', phoneCodeHash.substring(0, 10) + '...');
            } else {
                console.error('[Telegram] Result is not an object or string, type:', typeof result);
            }

            if (!phoneCodeHash) {
                console.error('[Telegram] ✗ Could not extract phoneCodeHash from result');
                console.error('[Telegram] Result type:', typeof result);
                if (result && typeof result === 'object') {
                    try {
                        const keys = Object.keys(result);
                        console.error('[Telegram] Result keys:', keys.join(', '));
                        // Log first few key-value pairs for debugging
                        for (const key of keys.slice(0, 5)) {
                            try {
                                const val = result[key];
                                console.error(`[Telegram]   ${key}:`, typeof val, val !== null && val !== undefined ? String(val).substring(0, 50) : 'null/undefined');
                            } catch (e) {
                                console.error(`[Telegram]   ${key}: [error reading]`);
                            }
                        }
                    } catch (e) {
                        console.error('[Telegram] Could not get result keys:', String(e));
                    }
                }
                return res.status(400).json({
                    success: false,
                    error: 'Failed to get phone code hash from Telegram API. Check server console for details.'
                });
            }

            console.log('[Telegram] ===== sendCode SUCCESS =====');
            console.log('[Telegram] phone_code_hash:', phoneCodeHash.substring(0, 10) + '...');
            authCodeRequired = true;
            authPasswordRequired = false;

            return res.json({
                success: true,
                message: 'Code sent to Telegram',
                phone_code_hash: phoneCodeHash
            });
        } catch (error) {
            // Safely extract error message without accessing undefined properties
            let errorMessage = 'Failed to send code';
            let errorString = '';
            
            try {
                // Try to get error as string first
                errorString = String(error);
                console.error('[Telegram] Error sending code:', errorString);
                
                // Try to extract message safely
                if (error) {
                    // Check if error has message property (safely)
                    try {
                        if (typeof error === 'object' && 'message' in error) {
                            const msg = error.message;
                            if (msg && typeof msg === 'string') {
                                errorMessage = msg;
                            }
                        }
                    } catch (e) {
                        // Ignore
                    }
                    
                    // Try errorMessage property
                    try {
                        if (typeof error === 'object' && 'errorMessage' in error) {
                            const errMsg = error.errorMessage;
                            if (errMsg && typeof errMsg === 'string') {
                                errorMessage = errMsg;
                            }
                        }
                    } catch (e) {
                        // Ignore
                    }
                    
                    // If error is a string, use it directly
                    if (typeof error === 'string') {
                        errorMessage = error;
                    }
                }
                
                // Provide more specific error messages based on content
                const errorText = errorMessage.toLowerCase();
                if (errorText.includes('phone_number_invalid') || errorText.includes('invalid phone')) {
                    errorMessage = 'Invalid phone number format. Please include country code (e.g., +1234567890)';
                } else if (errorText.includes('phone_number_flood') || errorText.includes('flood')) {
                    errorMessage = 'Too many requests. Please wait before trying again.';
                } else if (errorText.includes('phone_number_banned') || errorText.includes('banned')) {
                    errorMessage = 'This phone number is banned.';
                } else if (errorText.includes('auth_restart')) {
                    errorMessage = 'Authentication session expired. Please try again.';
                } else if (errorText.includes('flood_wait')) {
                    errorMessage = 'Too many requests. Please wait a few minutes before trying again.';
                }
                
            } catch (logError) {
                // If all else fails, use the string representation
                errorMessage = errorString || 'Failed to send code';
                console.error('[Telegram] Error during error handling:', String(logError));
            }
            
            // Ensure we return a valid JSON response
            return res.status(400).json({
                success: false,
                error: String(errorMessage)
            });
        }
    } catch (outerError) {
        // Safely handle outer catch block errors - ensure valid JSON response
        let errorMessage = 'Internal server error';
        try {
            if (outerError) {
                // Try to get error message safely
                if (typeof outerError === 'object' && 'message' in outerError) {
                    const msg = outerError.message;
                    if (msg && typeof msg === 'string') {
                        errorMessage = msg;
                    }
                } else if (typeof outerError === 'string') {
                    errorMessage = outerError;
                } else {
                    errorMessage = String(outerError);
                }
            }
        } catch (e) {
            errorMessage = 'Internal server error';
        }
        
        console.error('[Telegram] Error in phone auth:', errorMessage);
        
        // Ensure we always return valid JSON
        try {
            res.status(500).json({
                success: false,
                error: String(errorMessage)
            });
        } catch (jsonError) {
            // If JSON response fails, send plain text
            res.status(500).send(String(errorMessage));
        }
    }
});

/**
 * POST /api/telegram/auth/code
 * Verify authentication code
 */
app.post('/api/telegram/auth/code', async (req, res) => {
    try {
        const { phone_code, phone_code_hash, password } = req.body;

        if (!phone_code && !password) {
            return res.status(400).json({
                success: false,
                error: 'phone_code or password is required'
            });
        }

        if (!client) {
            return res.status(400).json({
                success: false,
                error: 'Client not initialized. Please start authentication with phone number first.'
            });
        }
        
        if (!API_CREDENTIALS) {
            return res.status(400).json({
                success: false,
                error: 'API credentials not configured. Set TELEGRAM_API_ID and TELEGRAM_API_HASH environment variables.'
            });
        }

        try {
            // 1) If a code is provided, try signing in with the code first.
            //    If 2FA is enabled, Telegram returns SESSION_PASSWORD_NEEDED.
            if (phone_code) {
                try {
                    await client.invoke(
                        new Api.auth.SignIn({
                            phoneNumber: authPhoneNumber,
                            phoneCodeHash: phone_code_hash,
                            phoneCode: phone_code
                        })
                    );
                } catch (signInError) {
                    // If 2FA is required, proceed to password step if password is provided.
                    if (
                        signInError &&
                        typeof signInError === 'object' &&
                        'errorMessage' in signInError &&
                        String(signInError.errorMessage).includes('SESSION_PASSWORD_NEEDED')
                    ) {
                        authPasswordRequired = true;
                        if (!password) {
                            return res.json({
                                success: false,
                                password_required: true,
                                error: '2FA password required'
                            });
                        }
                        // Continue to password handling below.
                    } else {
                        throw signInError;
                    }
                }
            }

            // 2) If a password is provided, verify it using GramJS' SRP flow.
            //    IMPORTANT: Api.auth.CheckPassword expects an InputCheckPasswordSRP object, not a raw string.
            if (password) {
                await client.signInWithPassword(API_CREDENTIALS, {
                    password: async () => String(password),
                    onError: async (err) => {
                        // Fail fast; do not loop waiting for a new password.
                        throw err;
                    }
                });
            }

            // Save session
            const sessionString = client.session.save();
            fs.writeFileSync(SESSION_FILE, sessionString);
            console.log('[Telegram] Session saved after authentication');

            isAuthenticated = true;
            isReady = true;
            authCodeRequired = false;
            authPasswordRequired = false;

            // Setup message handler
            setupMessageHandler();
            setupReceiptHandler();

            io.emit('telegram_status', {
                is_connected: true,
                is_authenticated: true,
                message: 'Connected to Telegram'
            });

            return res.json({
                success: true,
                message: 'Authentication successful',
                is_authenticated: true
            });
        } catch (error) {
            console.error('[Telegram] Error verifying code:', error);
            
            // Check if 2FA password is required
            if (error && typeof error === 'object' && 'errorMessage' in error && String(error.errorMessage).includes('SESSION_PASSWORD_NEEDED')) {
                authPasswordRequired = true;
                return res.json({
                    success: false,
                    password_required: true,
                    error: '2FA password required'
                });
            }

            return res.status(400).json({
                success: false,
                error: error.message || 'Failed to verify code'
            });
        }
    } catch (error) {
        console.error('[Telegram] Error in code auth:', error);
        res.status(500).json({
            success: false,
            error: error.message
        });
    }
});

/**
 * POST /api/telegram/contacts
 * Get Telegram contacts/chats with contact information
 */
app.post('/api/telegram/contacts', async (req, res) => {
    try {
        if (!isReady || !client) {
            return res.status(400).json({
                success: false,
                error: 'Telegram not connected. Please authenticate first.'
            });
        }

        const limit = req.body.limit || 100;
        const includeAvatars = !!req.body.include_avatars; // default false (faster/more reliable)
        const maxLastMessageLen = Math.min(
            Math.max(parseInt(req.body.max_last_message_len || '500', 10) || 500, 50),
            5000
        );

        try {
            // Get dialogs (chats)
            const dialogs = await client.getDialogs({ limit: limit });
            
            // Format contacts/chats with detailed information
            const contacts = await Promise.all(dialogs.map(async (dialog) => {
                const entity = dialog.entity;
                const isGroup = entity.className === 'Chat' || entity.className === 'Channel';
                
                // Get contact information
                let contactInfo = {
                    contact_id: entity.id ? entity.id.toString() : '',
                    name: '',
                    username: null,
                    phone: null,
                    is_group: isGroup,
                    is_channel: entity.className === 'Channel',
                    unread_count: dialog.unreadCount || 0,
                    // Keep payload small; UI only shows preview anyway
                    last_message: dialog.message ? truncateText(dialog.message.message || '', maxLastMessageLen) : '',
                    last_message_time: dialog.message ? toUnixSeconds(dialog.message.date) : null,
                    avatar_url: null,
                    // Use these to compute ✓ / ✓✓ for historical outgoing messages
                    read_inbox_max_id: dialog.dialog && dialog.dialog.readInboxMaxId !== undefined ? Number(dialog.dialog.readInboxMaxId) : null,
                    read_outbox_max_id: dialog.dialog && dialog.dialog.readOutboxMaxId !== undefined ? Number(dialog.dialog.readOutboxMaxId) : null
                };

                // Extract name and additional info based on entity type
                if (isGroup) {
                    contactInfo.name = entity.title || 'Unknown Group';
                    contactInfo.username = entity.username || null;
                } else {
                    // User contact
                    contactInfo.name = entity.firstName ? 
                        `${entity.firstName} ${entity.lastName || ''}`.trim() : 
                        (entity.title || 'Unknown');
                    contactInfo.username = entity.username || null;
                    contactInfo.phone = entity.phone || null;
                }

                // Cache entity so later /messages and /media calls can resolve input entities reliably
                try {
                    if (contactInfo.contact_id) {
                        entityCacheById.set(String(contactInfo.contact_id), entity);
                    }
                } catch (e) {}

                // Profile photos are expensive and can trigger extra DC downloads/reconnects.
                // Only fetch when explicitly requested.
                if (includeAvatars && entity.photo && entity.photo.className === 'UserProfilePhoto') {
                    try {
                        const photo = await client.downloadProfilePhoto(entity);
                        if (photo) {
                            const base64 = photo.toString('base64');
                            contactInfo.avatar_url = `data:image/jpeg;base64,${base64}`;
                        }
                    } catch (photoError) {
                        // Ignore photo errors
                        console.log('[Telegram] Could not download profile photo:', photoError.message);
                    }
                }

                return contactInfo;
            }));

            // Sort by last message time (most recent first)
            contacts.sort((a, b) => {
                const timeA = a.last_message_time || 0;
                const timeB = b.last_message_time || 0;
                return timeB - timeA;
            });

            return res.json({
                success: true,
                count: contacts.length,
                contacts: contacts
            });
        } catch (error) {
            console.error('[Telegram] Error getting contacts:', error);
            throw error;
        }
    } catch (error) {
        console.error('[Telegram] Error in contacts endpoint:', error);
        res.status(500).json({
            success: false,
            error: error.message
        });
    }
});

/**
 * POST /api/telegram/messages
 * Get messages for a specific contact/chat
 */
app.post('/api/telegram/messages', async (req, res) => {
    try {
        if (!isReady || !client) {
            return res.status(400).json({
                success: false,
                error: 'Telegram not connected. Please authenticate first.'
            });
        }

        const { chat_id, limit = 50, before_id } = req.body;
        const includeMedia = !!req.body.include_media; // default false (faster/more reliable)

        if (!chat_id) {
            return res.status(400).json({
                success: false,
                error: 'chat_id is required'
            });
        }

        try {
            // Get entity (chat/user)
            const entity = await getEntityForChatId(chat_id);
            
            // Get messages
            const params = { limit: limit };
            if (before_id !== undefined && before_id !== null && String(before_id).trim() !== '') {
                const beforeNum = parseInt(String(before_id), 10);
                if (Number.isFinite(beforeNum) && beforeNum > 1) {
                    // Older messages: ids < beforeNum
                    params.maxId = beforeNum - 1;
                }
            }
            const messages = await client.getMessages(entity, params);

            // Format messages for frontend
            const formattedMessages = await Promise.all(messages.map(async (message) => {
                const meta = getTelegramMediaMeta(message);
                const baseMessage = {
                    id: message.id.toString(),
                    body: message.message || '',
                    from: message.fromId ? message.fromId.toString() : '',
                    fromMe: message.out || false,
                    timestamp: toUnixSeconds(message.date) ?? Math.floor(Date.now() / 1000),
                    type: 'text',
                    hasMedia: meta.hasMedia,
                    mediaUrl: null,
                    mediaMimetype: meta.mimeType,
                    mediaFilename: meta.filename,
                    fileUrl: null
                };
                
                if (baseMessage.hasMedia) {
                    baseMessage.fileUrl = `/api/telegram/media/file?chat_id=${encodeURIComponent(String(chat_id))}&message_id=${encodeURIComponent(baseMessage.id)}`;
                }

                // Get sender info
                if (message.fromId) {
                    try {
                        const sender = await client.getEntity(message.fromId);
                        baseMessage.sender_name = sender.firstName ? 
                            `${sender.firstName} ${sender.lastName || ''}`.trim() : 
                            (sender.title || 'Unknown');
                    } catch (e) {
                        baseMessage.sender_name = 'Unknown';
                    }
                }

                // Media downloads are expensive and can trigger extra DC downloads/reconnects.
                // Only fetch when explicitly requested.
                if (includeMedia && baseMessage.hasMedia && message.media) {
                    try {
                        const buffer = await client.downloadMedia(message, {});
                        if (buffer) {
                            const base64 = buffer.toString('base64');
                            const mimeType = meta.mimeType || 'application/octet-stream';
                            baseMessage.mediaUrl = `data:${mimeType};base64,${base64}`;
                            baseMessage.mediaMimetype = mimeType;
                            baseMessage.mediaFilename = meta.filename || null;
                        }
                    } catch (mediaError) {
                        console.error('[Telegram] Error downloading media:', mediaError);
                        baseMessage.mediaUrl = null;
                    }
                }

                return baseMessage;
            }));

            // Sort by timestamp (oldest first for display)
            formattedMessages.sort((a, b) => a.timestamp - b.timestamp);
            
            const oldestId = formattedMessages.length > 0
                ? String(formattedMessages[0].id)
                : null;
            const reachedStart = formattedMessages.length < limit;

            // Get chat name
            let chatName = 'Unknown';
            if (entity.title) {
                chatName = entity.title;
            } else if (entity.firstName) {
                chatName = `${entity.firstName} ${entity.lastName || ''}`.trim();
            }

            return res.json({
                success: true,
                chat_id: chat_id,
                chat_name: chatName,
                count: formattedMessages.length,
                messages: formattedMessages,
                oldest_id: oldestId,
                reached_start: reachedStart
            });
        } catch (error) {
            console.error('[Telegram] Error getting messages:', error);
            throw error;
        }
    } catch (error) {
        console.error('[Telegram] Error in messages endpoint:', error);
        res.status(500).json({
            success: false,
            error: error.message
        });
    }
});

/**
 * GET /api/telegram/avatar
 * Fetch a Telegram profile photo for a user/chat/channel (cached on disk).
 * Query params:
 * - contact_id (required)
 * - refresh (optional, boolean) to re-download
 */
app.get('/api/telegram/avatar', async (req, res) => {
    try {
        if (!isReady || !client) {
            return res.status(400).json({ success: false, error: 'Telegram not connected' });
        }
        const contactId = (req.query.contact_id || '').toString().trim();
        const refresh = String(req.query.refresh || '').toLowerCase() === 'true';
        if (!contactId) {
            return res.status(400).json({ success: false, error: 'contact_id is required' });
        }
        
        const cacheFile = path.join(AVATAR_DIR, `${contactId}.b64`);
        if (!refresh && fs.existsSync(cacheFile)) {
            const base64 = fs.readFileSync(cacheFile, 'utf8').trim();
            if (base64) {
                return res.json({ success: true, avatar_url: `data:image/jpeg;base64,${base64}` });
            }
        }
        
        const entity = await client.getEntity(contactId);
        const photo = await client.downloadProfilePhoto(entity);
        if (!photo) {
            return res.json({ success: true, avatar_url: null });
        }
        const base64 = photo.toString('base64');
        try { fs.writeFileSync(cacheFile, base64); } catch (e) {}
        return res.json({ success: true, avatar_url: `data:image/jpeg;base64,${base64}` });
    } catch (error) {
        console.error('[Telegram] Error fetching avatar:', error);
        return res.status(500).json({ success: false, error: error.message || String(error) });
    }
});

/**
 * POST /api/telegram/media
 * Download media for a single message on-demand.
 * Body: { chat_id, message_id }
 */
app.post('/api/telegram/media', async (req, res) => {
    try {
        if (!isReady || !client) {
            return res.status(400).json({ success: false, error: 'Telegram not connected' });
        }
        const { chat_id, message_id } = req.body || {};
        if (!chat_id || !message_id) {
            return res.status(400).json({ success: false, error: 'chat_id and message_id are required' });
        }
        
        const entity = await getEntityForChatId(chat_id);
        const msgIdNum = parseInt(String(message_id), 10);
        if (!Number.isFinite(msgIdNum)) {
            return res.status(400).json({ success: false, error: 'message_id must be a number' });
        }
        
        const msgs = await client.getMessages(entity, { ids: [msgIdNum] });
        const message = Array.isArray(msgs) ? msgs[0] : msgs;
        const meta = getTelegramMediaMeta(message);
        if (!message || !meta.hasMedia) {
            return res.status(404).json({ success: false, error: 'Media not found for this message' });
        }
        
        const buffer = await client.downloadMedia(message, {});
        if (!buffer) {
            return res.status(500).json({ success: false, error: 'Failed to download media' });
        }
        
        const base64 = buffer.toString('base64');
        const mimeType = meta.mimeType || 'application/octet-stream';
        const filename = meta.filename || null;
        
        return res.json({
            success: true,
            mediaUrl: `data:${mimeType};base64,${base64}`,
            mediaMimetype: mimeType,
            mediaFilename: filename,
            // Prefer this for large videos/files (no huge base64 in the DOM)
            fileUrl: `/api/telegram/media/file?chat_id=${encodeURIComponent(String(chat_id))}&message_id=${encodeURIComponent(String(message_id))}`
        });
    } catch (error) {
        console.error('[Telegram] Error downloading media:', error);
        return res.status(500).json({ success: false, error: error.message || String(error) });
    }
});

/**
 * GET /api/telegram/media/file
 * Stream media for a message inline (better for large video/gif).
 * Query: chat_id, message_id, download=true(optional)
 */
app.get('/api/telegram/media/file', async (req, res) => {
    try {
        if (!isReady || !client) {
            return res.status(400).json({ success: false, error: 'Telegram not connected' });
        }
        const chatId = (req.query.chat_id || '').toString().trim();
        const msgId = (req.query.message_id || '').toString().trim();
        const download = String(req.query.download || '').toLowerCase() === 'true';
        if (!chatId || !msgId) {
            return res.status(400).json({ success: false, error: 'chat_id and message_id are required' });
        }
        const entity = await getEntityForChatId(chatId);
        const msgIdNum = parseInt(String(msgId), 10);
        if (!Number.isFinite(msgIdNum)) {
            return res.status(400).json({ success: false, error: 'message_id must be a number' });
        }

        const msgs = await client.getMessages(entity, { ids: [msgIdNum] });
        const message = Array.isArray(msgs) ? msgs[0] : msgs;
        const meta = getTelegramMediaMeta(message);
        if (!message || !meta.hasMedia) {
            return res.status(404).json({ success: false, error: 'Media not found for this message' });
        }

        const buffer = await client.downloadMedia(message, {});
        if (!buffer) {
            return res.status(500).json({ success: false, error: 'Failed to download media' });
        }

        const mimeType = meta.mimeType || 'application/octet-stream';
        let filename = meta.filename || `telegram_media_${msgIdNum}`;
        if (!meta.filename) {
            // Add a best-effort extension when we don't have a real filename
            const baseMime = String(mimeType).split(';')[0].trim();
            const ext = baseMime.includes('/') ? baseMime.split('/')[1] : 'bin';
            filename += `.${ext || 'bin'}`;
        }

        res.setHeader('Content-Type', mimeType);
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
        console.error('[Telegram] Error streaming media:', error);
        return res.status(500).json({ success: false, error: error.message || String(error) });
    }
});

/**
 * POST /api/telegram/sendFile
 * Send a file (base64) to a chat.
 * Body: { chat_id, filename, mimeType, data_base64, caption? }
 */
app.post('/api/telegram/sendFile', async (req, res) => {
    try {
        if (!isReady || !client) {
            return res.status(400).json({ success: false, error: 'Telegram not connected. Please authenticate first.' });
        }
        const { chat_id, data_base64, caption } = req.body || {};
        if (!chat_id || !data_base64) {
            return res.status(400).json({ success: false, error: 'chat_id and data_base64 are required' });
        }
        
        const entity = await getEntityForChatId(chat_id);
        const buf = Buffer.from(String(data_base64), 'base64');
        const sent = await client.sendFile(entity, {
            file: buf,
            caption: caption ? String(caption) : undefined,
            forceDocument: true
        });
        
        try {
            io.emit('telegram_outgoing_sent', {
                contact_id: String(chat_id),
                message_id: sent && sent.id ? String(sent.id) : null
            });
        } catch (e) {}
        
        return res.json({
            success: true,
            message: 'File sent successfully',
            message_id: sent && sent.id ? String(sent.id) : null
        });
    } catch (error) {
        console.error('[Telegram] Error sending file:', error);
        return res.status(500).json({ success: false, error: error.message || String(error) });
    }
});

/**
 * POST /api/telegram/edit
 * Edit a message you sent.
 * Body: { chat_id, message_id, text }
 */
app.post('/api/telegram/edit', async (req, res) => {
    try {
        if (!isReady || !client) {
            return res.status(400).json({ success: false, error: 'Telegram not connected. Please authenticate first.' });
        }
        const { chat_id, message_id, text } = req.body || {};
        if (!chat_id || !message_id || typeof text !== 'string') {
            return res.status(400).json({ success: false, error: 'chat_id, message_id, and text are required' });
        }
        const entity = await getEntityForChatId(chat_id);
        const edited = await client.editMessage(entity, {
            message: parseInt(String(message_id), 10),
            text: text
        });
        return res.json({ success: true, message: 'Message edited', message_id: edited && edited.id ? String(edited.id) : String(message_id) });
    } catch (error) {
        console.error('[Telegram] Error editing message:', error);
        return res.status(500).json({ success: false, error: error.message || String(error) });
    }
});

/**
 * POST /api/telegram/clear
 * Clear chat history for a chat (best-effort).
 * Body: { chat_id, revoke?: boolean }
 */
app.post('/api/telegram/clear', async (req, res) => {
    try {
        if (!isReady || !client) {
            return res.status(400).json({ success: false, error: 'Telegram not connected. Please authenticate first.' });
        }
        const { chat_id, revoke } = req.body || {};
        if (!chat_id) {
            return res.status(400).json({ success: false, error: 'chat_id is required' });
        }
        const entity = await getEntityForChatId(chat_id);
        await client.invoke(new Api.messages.DeleteHistory({
            peer: entity,
            maxId: 0,
            justClear: true,
            revoke: !!revoke
        }));
        return res.json({ success: true, message: 'Chat history cleared' });
    } catch (error) {
        console.error('[Telegram] Error clearing chat history:', error);
        return res.status(500).json({ success: false, error: error.message || String(error) });
    }
});

/**
 * POST /api/telegram/delete
 * Delete a single message from a chat.
 * Body: { chat_id, message_id, revoke?: boolean }
 */
app.post('/api/telegram/delete', async (req, res) => {
    try {
        if (!isReady || !client) {
            return res.status(400).json({ success: false, error: 'Telegram not connected. Please authenticate first.' });
        }
        const { chat_id, message_id, revoke } = req.body || {};
        if (!chat_id || !message_id) {
            return res.status(400).json({ success: false, error: 'chat_id and message_id are required' });
        }
        const entity = await getEntityForChatId(chat_id);
        const mid = parseInt(String(message_id), 10);
        if (!Number.isFinite(mid)) {
            return res.status(400).json({ success: false, error: 'message_id must be a number' });
        }
        await client.deleteMessages(entity, [mid], { revoke: revoke !== undefined ? !!revoke : true });
        return res.json({ success: true, message: 'Message deleted', message_id: String(mid) });
    } catch (error) {
        console.error('[Telegram] Error deleting message:', error);
        return res.status(500).json({ success: false, error: error.message || String(error) });
    }
});

/**
 * POST /api/telegram/send
 * Send a Telegram message
 */
app.post('/api/telegram/send', async (req, res) => {
    try {
        if (!isReady || !client) {
            return res.status(400).json({
                success: false,
                error: 'Telegram not connected. Please authenticate first.'
            });
        }

        const { chat_id, text } = req.body;

        if (!chat_id || !text) {
            return res.status(400).json({
                success: false,
                error: 'chat_id and text are required'
            });
        }

        try {
            // Get entity
            const entity = await getEntityForChatId(chat_id);
            
            // Send message
            const message = await client.sendMessage(entity, { message: text });

            // Best-effort "sent" event; NewMessage handler may also emit the full message later.
            try {
                io.emit('telegram_outgoing_sent', {
                    contact_id: String(chat_id),
                    message_id: message && message.id ? String(message.id) : null,
                    timestamp: toUnixSeconds(message && message.date) ?? Math.floor(Date.now() / 1000)
                });
            } catch (e) {}

            return res.json({
                success: true,
                message: 'Message sent successfully',
                message_id: message.id.toString(),
                timestamp: toUnixSeconds(message.date) ?? Math.floor(Date.now() / 1000)
            });
        } catch (error) {
            console.error('[Telegram] Error sending message:', error);
            throw error;
        }
    } catch (error) {
        console.error('[Telegram] Error in send endpoint:', error);
        res.status(500).json({
            success: false,
            error: error.message
        });
    }
});

// Debug endpoint to test sendCode
app.post('/api/telegram/debug/sendcode', async (req, res) => {
    try {
        const { phone_number } = req.body;
        
        if (!phone_number) {
            return res.status(400).json({ error: 'phone_number required' });
        }
        
        if (!client) {
            return res.status(500).json({ error: 'Client not initialized' });
        }
        if (!API_CREDENTIALS) {
            return res.status(400).json({ error: 'API credentials not configured. Set TELEGRAM_API_ID and TELEGRAM_API_HASH.' });
        }
        
        if (!client.connected) {
            try {
                await client.connect();
            } catch (connectError) {
                return res.status(500).json({ error: 'Failed to connect: ' + connectError.message });
            }
        }
        
        console.log('[DEBUG] Testing sendCode with phone:', phone_number);
        const result = await client.sendCode(API_CREDENTIALS, phone_number);
        
        // Safely extract information
        const debugInfo = {
            resultType: typeof result,
            resultIsNull: result === null,
            resultIsUndefined: result === undefined,
            hasPhoneCodeHash: result && 'phoneCodeHash' in result,
            hasPhone_code_hash: result && 'phone_code_hash' in result,
            keys: result && typeof result === 'object' ? Object.keys(result) : [],
        };
        
        if (result && typeof result === 'object') {
            try {
                debugInfo.phoneCodeHash = result.phoneCodeHash;
            } catch (e) {}
            try {
                debugInfo.phone_code_hash = result.phone_code_hash;
            } catch (e) {}
        }
        
        res.json({ success: true, debug: debugInfo });
    } catch (error) {
        res.status(400).json({ 
            success: false, 
            error: error.message || String(error),
            errorType: typeof error
        });
    }
});

// Socket.IO connection handling
io.on('connection', (socket) => {
    console.log('[Telegram] Client connected via WebSocket:', socket.id);
    
    // Send current status when client connects
    const hasSession = fs.existsSync(SESSION_FILE) && stringSession.length > 0;
    const hasCredentials = !!(API_ID && API_HASH);
    
    socket.emit('telegram_status', {
        is_connected: isReady && isAuthenticated,
        is_authenticated: isAuthenticated,
        has_session: hasSession,
        has_api_credentials: hasCredentials,
        message: isReady ? 'Connected to Telegram' : 
                 (hasSession ? 'Session found - connecting...' : 
                  (hasCredentials ? 'Authentication required' : 'API credentials required'))
    });
    
    socket.on('disconnect', () => {
        console.log('[Telegram] Client disconnected from WebSocket:', socket.id);
    });
});

// Start server - listen on all interfaces (0.0.0.0) for VPS compatibility
server.listen(PORT, '0.0.0.0', () => {
    console.log(`[Telegram Server] Server running on http://0.0.0.0:${PORT}`);
    console.log(`[Telegram Server] WebSocket server ready`);
    if (API_ID && API_HASH) {
        console.log(`[Telegram Server] API credentials found - initializing client...`);
    } else {
        console.log(`[Telegram Server] API credentials not found - set TELEGRAM_API_ID and TELEGRAM_API_HASH`);
    }
});

// Graceful shutdown
process.on('SIGINT', async () => {
    console.log('\n[Telegram Server] Shutting down...');
    if (client) {
        await client.disconnect();
    }
    process.exit(0);
});

