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

const app = express();
const PORT = 3000;

// Middleware
app.use(cors());
app.use(express.json());

// WhatsApp client instance
let client = null;
let qrCodeData = null;
let isAuthenticated = false;
let isReady = false;

// Session directory
const SESSION_DIR = path.join(__dirname, 'whatsapp_session_node');

// Ensure session directory exists
if (!fs.existsSync(SESSION_DIR)) {
    fs.mkdirSync(SESSION_DIR, { recursive: true });
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

    // Check if session exists
    const sessionPath = path.join(SESSION_DIR, '.wwebjs_auth');
    const hasSession = fs.existsSync(sessionPath);

    if (hasSession) {
        console.log('[WhatsApp] Existing session found - will auto-connect');
    } else {
        console.log('[WhatsApp] No session found - QR code authentication required');
    }

    // Create client with LocalAuth for session persistence
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
        }
    });

    // QR code event - fired when QR code is generated
    client.on('qr', async (qr) => {
        console.log('[WhatsApp] QR code received');
        try {
            // Generate QR code as base64 data URL
            qrCodeData = await qrcode.toDataURL(qr);
            console.log('[WhatsApp] QR code generated successfully');
        } catch (err) {
            console.error('[WhatsApp] Error generating QR code:', err);
            qrCodeData = null;
        }
    });

    // Ready event - fired when client is ready to use
    client.on('ready', () => {
        console.log('[WhatsApp] Client is ready!');
        isAuthenticated = true;
        isReady = true;
        qrCodeData = null; // Clear QR code when authenticated
    });

    // Authentication event - fired when authentication is successful
    client.on('authenticated', () => {
        console.log('[WhatsApp] Authentication successful!');
        isAuthenticated = true;
    });

    // Authentication failure event
    client.on('auth_failure', (msg) => {
        console.error('[WhatsApp] Authentication failure:', msg);
        isAuthenticated = false;
        isReady = false;
        qrCodeData = null;
    });

    // Disconnected event
    client.on('disconnected', (reason) => {
        console.log('[WhatsApp] Client disconnected:', reason);
        isAuthenticated = false;
        isReady = false;
        qrCodeData = null;
        
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

// Initialize WhatsApp on server start
initializeWhatsApp();

/**
 * GET /api/whatsapp/qr-code
 * Get QR code for authentication
 */
app.get('/api/whatsapp/qr-code', async (req, res) => {
    try {
        const forceRefresh = req.query.force_refresh === 'true';
        
        // If already authenticated, return success
        if (isAuthenticated && isReady) {
            return res.json({
                success: true,
                is_authenticated: true,
                message: 'Already authenticated'
            });
        }

        // If session exists but not ready yet, wait a bit
        if (isAuthenticated && !isReady) {
            return res.json({
                success: false,
                is_authenticated: false,
                has_session: true,
                message: 'Session exists - connecting...'
            });
        }

        // If force refresh, reinitialize client to get new QR code
        if (forceRefresh && client) {
            console.log('[WhatsApp] Force refreshing QR code - reinitializing client...');
            qrCodeData = null;
            try {
                await client.destroy();
            } catch (err) {
                console.error('[WhatsApp] Error destroying client:', err);
            }
            client = null;
            isAuthenticated = false;
            isReady = false;
            initializeWhatsApp();
            // Wait a moment for QR code to be generated
            await new Promise(resolve => setTimeout(resolve, 2000));
        }

        // If QR code is available, return it
        if (qrCodeData) {
            return res.json({
                success: true,
                qr_code: qrCodeData,
                is_authenticated: false,
                message: 'Scan the QR code with WhatsApp to connect'
            });
        }

        // If no QR code yet, wait a bit and check again
        // This handles the case where client is initializing
        return res.json({
            success: false,
            is_authenticated: false,
            message: 'QR code not available yet. Please wait...'
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
        const sessionPath = path.join(SESSION_DIR, '.wwebjs_auth');
        const hasSession = fs.existsSync(sessionPath);

        if (isAuthenticated && isReady) {
            return res.json({
                success: true,
                is_connected: true,
                is_authenticated: true,
                has_session: hasSession,
                message: 'Connected to WhatsApp'
            });
        }

        if (hasSession && !isReady) {
            return res.json({
                success: true,
                is_connected: false,
                is_authenticated: false,
                has_session: true,
                message: 'Session found - restoring connection...'
            });
        }

        return res.json({
            success: true,
            is_connected: false,
            is_authenticated: false,
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

        const sessionPath = path.join(SESSION_DIR, '.wwebjs_auth');
        const hasSession = fs.existsSync(sessionPath);

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
        if (!isReady || !client) {
            return res.status(400).json({
                success: false,
                error: 'WhatsApp not connected. Please authenticate first.'
            });
        }

        const limit = req.body.limit || 100;
        const chats = await client.getChats();
        
        const contacts = chats.slice(0, limit).map(chat => ({
            contact_id: chat.id._serialized,
            name: chat.name || chat.id.user || 'Unknown',
            is_group: chat.isGroup,
            last_message: chat.lastMessage?.body || '',
            last_message_time: chat.lastMessage?.timestamp || null,
            unread_count: chat.unreadCount || 0
        }));

        return res.json({
            success: true,
            count: contacts.length,
            contacts: contacts
        });
    } catch (error) {
        console.error('[WhatsApp] Error getting contacts:', error);
        res.status(500).json({
            success: false,
            error: error.message
        });
    }
});

/**
 * POST /api/whatsapp/messages
 * Get messages for a specific contact/chat
 */
app.post('/api/whatsapp/messages', async (req, res) => {
    try {
        if (!isReady || !client) {
            return res.status(400).json({
                success: false,
                error: 'WhatsApp not connected. Please authenticate first.'
            });
        }

        const { contact_id, limit = 50 } = req.body;

        if (!contact_id) {
            return res.status(400).json({
                success: false,
                error: 'contact_id is required'
            });
        }

        // Get chat by contact ID
        const chat = await client.getChatById(contact_id);
        
        // Fetch messages from the chat
        const messages = await chat.fetchMessages({ limit: limit });

        // Format messages for frontend
        const formattedMessages = messages.map(msg => ({
            id: msg.id._serialized,
            body: msg.body || '',
            from: msg.from || contact_id,
            fromMe: msg.fromMe,
            timestamp: msg.timestamp,
            type: msg.type,
            hasMedia: msg.hasMedia,
            mediaUrl: msg.hasMedia ? (msg.mediaKey ? 'media_available' : null) : null
        }));

        // Sort by timestamp (oldest first for display)
        formattedMessages.sort((a, b) => a.timestamp - b.timestamp);

        return res.json({
            success: true,
            contact_id: contact_id,
            contact_name: chat.name || 'Unknown',
            count: formattedMessages.length,
            messages: formattedMessages
        });
    } catch (error) {
        console.error('[WhatsApp] Error getting messages:', error);
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

// Health check endpoint
app.get('/health', (req, res) => {
    res.json({ status: 'ok', service: 'whatsapp-server' });
});

// Start server
app.listen(PORT, () => {
    console.log(`[WhatsApp Server] Server running on http://localhost:${PORT}`);
    console.log(`[WhatsApp Server] WhatsApp client initializing...`);
});

// Graceful shutdown
process.on('SIGINT', async () => {
    console.log('\n[WhatsApp Server] Shutting down...');
    if (client) {
        await client.destroy();
    }
    process.exit(0);
});

