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
const AVATAR_DIR = path.join(SESSION_DIR, 'avatars');

// Ensure session directory exists
if (!fs.existsSync(SESSION_DIR)) {
    fs.mkdirSync(SESSION_DIR, { recursive: true });
}
if (!fs.existsSync(AVATAR_DIR)) {
    fs.mkdirSync(AVATAR_DIR, { recursive: true });
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
        
        // Emit ready event to all connected clients
        io.emit('whatsapp_status', {
            is_connected: true,
            is_authenticated: true,
            message: 'Connected to WhatsApp'
        });
    });
    
    // Message event - fired when a message is received
    client.on('message', async (message) => {
        try {
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
            unread_count: chat.unreadCount || 0,
            avatar_url: null
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
        if (!isReady || !client) {
            return res.status(400).json({
                success: false,
                error: 'WhatsApp not connected. Please authenticate first.'
            });
        }

        const { contact_id, limit = 50, include_media } = req.body;

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
        const message = await client.getMessageById(messageId);
        
        if (!message) {
            return res.status(404).json({
                success: false,
                error: 'Message not found'
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
        const filename = media.filename || `media_${messageId}.${media.mimetype.split('/')[1]}`;
        res.setHeader('Content-Type', media.mimetype);
        const download = String(req.query.download || '').toLowerCase() === 'true';
        const disposition = download ? 'attachment' : 'inline';
        res.setHeader('Content-Disposition', `${disposition}; filename="${filename}"`);
        res.setHeader('Content-Length', buffer.length);

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

// Health check endpoint
app.get('/health', (req, res) => {
    res.json({ status: 'ok', service: 'whatsapp-server' });
});

// Socket.IO connection handling
io.on('connection', (socket) => {
    console.log('[WhatsApp] Client connected via WebSocket:', socket.id);
    
    // Send current status when client connects
    const sessionPath = path.join(SESSION_DIR, '.wwebjs_auth');
    const hasSession = fs.existsSync(sessionPath);
    
    socket.emit('whatsapp_status', {
        is_connected: isReady && isAuthenticated,
        is_authenticated: isAuthenticated,
        has_session: hasSession,
        message: isReady ? 'Connected to WhatsApp' : (hasSession ? 'Session found - connecting...' : 'QR code authentication required')
    });
    
    socket.on('disconnect', () => {
        console.log('[WhatsApp] Client disconnected from WebSocket:', socket.id);
    });
});

// Start server
server.listen(PORT, () => {
    console.log(`[WhatsApp Server] Server running on http://localhost:${PORT}`);
    console.log(`[WhatsApp Server] WebSocket server ready`);
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

