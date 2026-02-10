/**
 * WhatsApp Node.js Backend Server
 * Handles QR code authentication and WhatsApp operations using whatsapp-web.js
 */

const express = require('express');
const { Client, LocalAuth } = require('whatsapp-web.js');
const qrcode = require('qrcode');
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
// Warmup delay: wait this many ms after 'ready' before allowing getChats/getChatById (WhatsApp Web needs time to initialize)
const CHATS_WARMUP_MS = 15000;
// Cache messages so media can be fetched later even when whatsapp-web.js can't resolve by id (common for older messages)
const messageCacheById = new Map(); // messageId -> Message

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

function cacheWhatsAppMessage(msg) {
    try {
        const id = msg && msg.id && msg.id._serialized ? String(msg.id._serialized) : null;
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
 * Initialize WhatsApp client
 */
function initializeWhatsApp() {
    if (client) {
        console.log('[WhatsApp] Client already initialized');
        return;
    }

    console.log('[WhatsApp] Initializing WhatsApp client...');

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
    // webVersionCache: { type: 'none' } = use latest compatible WhatsApp Web (avoids "Cannot read 'default'" after scan)
    client = new Client({
        authStrategy: new LocalAuth({
            dataPath: SESSION_DIR
        }),
        puppeteer: {
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
        },
        webVersionCache: {
            type: 'none'
        }
    });

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
        
        // Emit ready event to all connected clients
        io.emit('whatsapp_status', {
            is_connected: true,
            is_authenticated: true,
            is_ready: true,
            message: 'Connected to WhatsApp'
        });
    });
    
    // Message event - fired when a message is received
    client.on('message', async (message) => {
        try {
            cacheWhatsAppMessage(message);
            console.log('[WhatsApp] New message received:', message.from, message.body?.substring(0, 50));
            
            // Emit immediately with basic info (don't wait for async operations)
            const quickMessage = {
                id: message.id._serialized,
                body: message.body || '',
                from: message.from,
                fromMe: message.fromMe,
                timestamp: message.timestamp,
                type: message.type,
                hasMedia: message.hasMedia,
                mediaUrl: null,
                mediaMimetype: null,
                mediaFilename: null,
                contact_id: message.from, // Use from as contact_id initially
                contact_name: 'Loading...', // Will be updated
                is_group: false
            };
            
            // If message has media, try to download it asynchronously
            if (message.hasMedia) {
                message.downloadMedia().then(media => {
                    if (media) {
                        quickMessage.mediaUrl = `data:${media.mimetype};base64,${media.data}`;
                        quickMessage.mediaMimetype = media.mimetype;
                        quickMessage.mediaFilename = media.filename || null;
                        // Emit update with media
                        io.emit('whatsapp_message_update', quickMessage);
                    }
                }).catch(err => {
                    console.error('[WhatsApp] Error downloading media:', err);
                });
            }
            
            // Emit immediately for instant display
            io.emit('whatsapp_message', quickMessage);
            
            // Get chat info asynchronously and emit update
            try {
                const chat = await message.getChat();
                const contact = await message.getContact();
                
                const formattedMessage = {
                    id: message.id._serialized,
                    body: message.body || '',
                    from: message.from,
                    fromMe: message.fromMe,
                    timestamp: message.timestamp,
                    type: message.type,
                    hasMedia: message.hasMedia,
                    mediaUrl: quickMessage.mediaUrl,
                    mediaMimetype: quickMessage.mediaMimetype,
                    mediaFilename: quickMessage.mediaFilename,
                    contact_id: chat.id._serialized,
                    contact_name: chat.name || contact.name || 'Unknown',
                    is_group: chat.isGroup
                };
                
                // Emit updated message with full info
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
                // Emit immediately with basic info
                const quickMessage = {
                    id: message.id._serialized,
                    body: message.body || '',
                    from: message.from,
                    fromMe: true,
                    timestamp: message.timestamp,
                    type: message.type,
                    hasMedia: message.hasMedia,
                    mediaUrl: null,
                    mediaMimetype: null,
                    mediaFilename: null,
                    contact_id: message.to, // Use 'to' for sent messages
                    contact_name: 'Loading...',
                    is_group: false
                };
                
                // If message has media, try to download it asynchronously
                if (message.hasMedia) {
                    message.downloadMedia().then(media => {
                        if (media) {
                            quickMessage.mediaUrl = `data:${media.mimetype};base64,${media.data}`;
                            quickMessage.mediaMimetype = media.mimetype;
                            quickMessage.mediaFilename = media.filename || null;
                            // Emit update with media
                            io.emit('whatsapp_message_update', quickMessage);
                        }
                    }).catch(err => {
                        console.error('[WhatsApp] Error downloading media:', err);
                    });
                }
                
                // Emit immediately for instant display
                io.emit('whatsapp_message', quickMessage);
                
                // Get chat info and emit update
                try {
                    const chat = await message.getChat();
                    const contact = await message.getContact();
                    
                    const formattedMessage = {
                        id: message.id._serialized,
                        body: message.body || '',
                        from: message.from,
                        fromMe: true,
                        timestamp: message.timestamp,
                        type: message.type,
                        hasMedia: message.hasMedia,
                        mediaUrl: quickMessage.mediaUrl,
                        mediaMimetype: quickMessage.mediaMimetype,
                        mediaFilename: quickMessage.mediaFilename,
                        contact_id: chat.id._serialized,
                        contact_name: chat.name || contact.name || 'Unknown',
                        is_group: chat.isGroup
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
                io.emit('whatsapp_status', {
                    is_connected: true,
                    is_authenticated: true,
                    is_ready: true,
                    message: 'Connected to WhatsApp'
                });
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

        // If client is not initialized, initialize it now
        if (!client) {
            console.log('[WhatsApp] Client not initialized - initializing now...');
            initializeWhatsApp();
            // Wait for QR code to be generated (up to 10 seconds)
            for (let i = 0; i < 20; i++) {
                await new Promise(resolve => setTimeout(resolve, 500));
                if (qrCodeData) {
                    break;
                }
            }
        }

        // If QR code is available, return it
        if (qrCodeData) {
            console.log('[WhatsApp] Returning QR code to client');
            return res.json({
                success: true,
                qr_code: qrCodeData,
                is_authenticated: false,
                message: 'Scan the QR code with WhatsApp to connect'
            });
        }

        // If no QR code yet, wait longer and check again (up to 15 seconds)
        // This handles the case where client is still initializing (e.g. on VPS or after reinit)
        console.log('[WhatsApp] QR code not available yet - waiting for client to initialize...');
        for (let i = 0; i < 30; i++) {
            await new Promise(resolve => setTimeout(resolve, 500));
            if (qrCodeData) {
                console.log('[WhatsApp] QR code became available after waiting');
                return res.json({
                    success: true,
                    qr_code: qrCodeData,
                    is_authenticated: false,
                    message: 'Scan the QR code with WhatsApp to connect'
                });
            }
            if (!client) {
                console.log('[WhatsApp] Client not ready - initializing...');
                initializeWhatsApp();
            }
        }
        
        // Still no QR code after waiting - return error
        console.error('[WhatsApp] QR code not available after waiting - client may have failed to initialize');
        return res.json({
            success: false,
            is_authenticated: false,
            message: 'QR code generation failed. Please try refreshing the page or check server logs.',
            error: 'qr_generation_timeout'
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
            return res.json({
                success: true,
                is_connected: true,
                is_authenticated: true,
                is_ready: true,
                has_session: hasSession,
                message: 'Connected to WhatsApp'
            });
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
    try {
        // Check if session folder was deleted and reset if needed
        await checkAndResetIfSessionDeleted();
        
        if (!isReady || !client) {
            return res.status(400).json({
                success: false,
                error: 'WhatsApp not connected. Please authenticate first.'
            });
        }

        // Wait for warmup period after 'ready' before allowing getChats (WhatsApp Web needs time to initialize)
        const timeSinceReady = readyAt ? (Date.now() - readyAt) : 0;
        if (timeSinceReady < CHATS_WARMUP_MS) {
            const waitMs = CHATS_WARMUP_MS - timeSinceReady;
            console.log(`[WhatsApp] Waiting ${waitMs}ms for WhatsApp Web to fully initialize before getChats...`);
            await new Promise(r => setTimeout(r, waitMs));
        }

        const limit = req.body.limit || 100;
        let chats;
        const maxTries = 6;
        const retryDelayMs = 5000;
        for (let attempt = 1; attempt <= maxTries; attempt++) {
            try {
                chats = await client.getChats();
                break;
            } catch (getChatsErr) {
                const isRetryable = /undefined|update|getChatModel|Evaluation failed/i.test(String(getChatsErr.message || ''));
                if (attempt < maxTries && isRetryable) {
                    console.log(`[WhatsApp] getChats attempt ${attempt}/${maxTries} failed, retrying in ${retryDelayMs}ms...`, getChatsErr.message);
                    await new Promise(r => setTimeout(r, retryDelayMs));
                } else {
                    throw getChatsErr;
                }
            }
        }
        
        const contacts = (chats || []).slice(0, limit).map(chat => ({
            contact_id: chat.id._serialized,
            name: chat.name || chat.id.user || 'Unknown',
            is_group: chat.isGroup,
            last_message: chat.lastMessage?.body || '',
            last_message_time: chat.lastMessage?.timestamp || null,
            unread_count: chat.unreadCount || 0,
            avatar_url: null
        }));

        console.log('[WhatsApp] Contacts loaded:', contacts.length, 'chats');
        return res.json({
            success: true,
            count: contacts.length,
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
                warning: 'Chats could not be loaded yet. Run "npm install" (to get the latest WhatsApp library fix), restart the WhatsApp server, then click Refresh. If it still fails, log out and scan the QR code again.'
            });
        }
        res.status(500).json({
            success: false,
            error: msg
        });
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
        
        const cacheFile = path.join(AVATAR_DIR, `${contactId}.json`);
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
        
        // Proxy to base64 to avoid CORS/hotlinking issues
        const resp = await fetch(url);
        if (!resp.ok) {
            return res.json({ success: true, avatar_url: null });
        }
        const buf = Buffer.from(await resp.arrayBuffer());
        const contentType = resp.headers.get('content-type') || 'image/jpeg';
        const base64 = buf.toString('base64');
        const avatarUrl = `data:${contentType};base64,${base64}`;
        
        try {
            fs.writeFileSync(cacheFile, JSON.stringify({ avatar_url: avatarUrl }), 'utf8');
        } catch (e) {
            // ignore cache write errors
        }
        
        return res.json({ success: true, avatar_url: avatarUrl });
    } catch (error) {
        console.error('[WhatsApp] Error fetching avatar:', error);
        res.status(500).json({ success: false, error: error.message || String(error) });
    }
});

/**
 * POST /api/whatsapp/messages
 * Get messages for a specific contact/chat
 */
app.post('/api/whatsapp/messages', async (req, res) => {
    try {
        // Check if session folder was deleted and reset if needed
        await checkAndResetIfSessionDeleted();
        
        if (!isReady || !client) {
            return res.status(400).json({
                success: false,
                error: 'WhatsApp not connected. Please authenticate first.'
            });
        }

        // Wait for warmup period after 'ready' before allowing getChatById (WhatsApp Web needs time to initialize)
        const timeSinceReady = readyAt ? (Date.now() - readyAt) : 0;
        if (timeSinceReady < CHATS_WARMUP_MS) {
            const waitMs = CHATS_WARMUP_MS - timeSinceReady;
            console.log(`[WhatsApp] Waiting ${waitMs}ms for WhatsApp Web to fully initialize before getChatById...`);
            await new Promise(r => setTimeout(r, waitMs));
        }

        const { contact_id, limit = 50, include_media } = req.body;

        if (!contact_id) {
            return res.status(400).json({
                success: false,
                error: 'contact_id is required'
            });
        }

        const maxTries = 6;
        const retryDelayMs = 5000;
        let chat;
        let messages;
        for (let attempt = 1; attempt <= maxTries; attempt++) {
            try {
                chat = await client.getChatById(contact_id);
                messages = await chat.fetchMessages({ limit: limit });
                break;
            } catch (messagesErr) {
                const isRetryable = /undefined|update|getChatModel|Evaluation failed/i.test(String(messagesErr.message || ''));
                if (attempt < maxTries && isRetryable) {
                    console.log(`[WhatsApp] getChatById/fetchMessages attempt ${attempt}/${maxTries} failed, retrying in ${retryDelayMs}ms...`, messagesErr.message);
                    await new Promise(r => setTimeout(r, retryDelayMs));
                } else {
                    throw messagesErr;
                }
            }
        }
        try { (messages || []).forEach(cacheWhatsAppMessage); } catch (e) {}

        // Format messages for frontend
        const formattedMessages = await Promise.all(messages.map(async (msg) => {
            const baseMessage = {
                id: msg.id._serialized,
                body: msg.body || '',
                from: msg.from || contact_id,
                fromMe: msg.fromMe,
                timestamp: msg.timestamp,
                type: msg.type,
                hasMedia: msg.hasMedia,
                mediaUrl: null,
                mediaMimetype: null,
                mediaFilename: null
            };

            // Media can be large; default to on-demand streaming via /api/whatsapp/media/:messageId
            baseMessage.mediaFetchUrl = `/api/whatsapp/media/${msg.id._serialized}?inline=1`;
            baseMessage.mediaDownloadUrl = `/api/whatsapp/media/${msg.id._serialized}?download=true`;
            
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
        }));

        // Sort by timestamp (oldest first for display)
        formattedMessages.sort((a, b) => a.timestamp - b.timestamp);

        console.log('[WhatsApp] Messages loaded for', contact_id, ':', formattedMessages.length, 'messages');
        return res.json({
            success: true,
            contact_id: contact_id,
            contact_name: chat.name || 'Unknown',
            count: formattedMessages.length,
            messages: formattedMessages
        });
    } catch (error) {
        console.error('[WhatsApp] Error getting messages:', error);
        const msg = error.message || String(error);
        const isPageNotReady = /undefined|update|getChatModel|Evaluation failed/i.test(msg);
        res.status(500).json({
            success: false,
            error: isPageNotReady
                ? 'WhatsApp is still loading. Please wait a few seconds and try again.'
                : msg
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
                    message = (recent || []).find(m => m && m.id && m.id._serialized === messageId) || null;
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
            message_id: editedMessage.id._serialized,
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

        // Send message
        const message = await client.sendMessage(contact_id, text);

        return res.json({
            success: true,
            message: 'Message sent successfully',
            message_id: message.id._serialized
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
    
    socket.emit('whatsapp_status', {
        is_connected: isReady && isAuthenticated,
        is_authenticated: isAuthenticated,
        is_ready: isReady && isAuthenticated,
        has_session: hasSession,
        message: isReady ? 'Connected to WhatsApp' : (hasSession ? 'Session found - connecting...' : 'QR code authentication required')
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

