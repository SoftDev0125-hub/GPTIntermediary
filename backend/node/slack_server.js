/**
 * Slack Node.js Backend Server
 * Handles Slack authentication and operations using Slack Web API (slack-sdk)
 */

require('dotenv').config();

const express = require('express');
const { WebClient } = require('@slack/web-api');
const { SocketModeClient } = require('@slack/socket-mode');
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

const PORT = 3002; // Different port from Telegram (3001) and WhatsApp (3000)

// Middleware
app.use(cors());
app.use(express.json());

// Slack client instance
let client = null;
let isAuthenticated = false;
let isReady = false;
let currentUserId = null;
let currentTeamId = null;

// Cache for performance
const channelCache = new Map(); // channelId -> channel info
const messageCache = new Map(); // channelId -> messages array
const avatarCache = new Map(); // userId -> avatar URL
const userCache = new Map(); // userId -> user info

// Real-time polling state
const activeChannels = new Set(); // Channels being monitored
const lastMessageTimestamps = new Map(); // channelId -> last message timestamp
let realtimePollInterval = null;

// Socket Mode (true real-time) state
let socketModeClient = null;
let socketModeEnabled = false;

function getAppToken() {
    // Slack Socket Mode app token starts with xapp-
    const t = process.env.SLACK_APP_TOKEN ? String(process.env.SLACK_APP_TOKEN).trim() : '';
    return t || null;
}

// Session directory for avatars
// Keep session data at the project root so moving this file doesn't break existing sessions.
const PROJECT_ROOT = path.join(__dirname, '..', '..');
const SESSION_DIR = path.join(PROJECT_ROOT, 'slack_session_node');
const AVATAR_DIR = path.join(SESSION_DIR, 'avatars');

// Ensure session directory exists
if (!fs.existsSync(SESSION_DIR)) {
    fs.mkdirSync(SESSION_DIR, { recursive: true });
}
if (!fs.existsSync(AVATAR_DIR)) {
    fs.mkdirSync(AVATAR_DIR, { recursive: true });
}

/**
 * Initialize Slack client
 */
function initializeSlack() {
    // Prefer bot token if available (recommended for Socket Mode + Events)
    const token = process.env.SLACK_BOT_TOKEN || process.env.SLACK_USER_TOKEN;
    
    if (!token) {
        console.log('[Slack] No token found. Set SLACK_BOT_TOKEN or SLACK_USER_TOKEN in .env');
        return;
    }

    if (client) {
        console.log('[Slack] Client already initialized');
        return;
    }

    console.log('[Slack] Initializing Slack client...');
    
    try {
        client = new WebClient(token);
        isAuthenticated = false;
        isReady = false;
        
        // Test connection
        testConnection();
    } catch (error) {
        console.error('[Slack] Error initializing client:', error);
    }
}

/**
 * Test Slack connection
 */
async function testConnection() {
    if (!client) return;
    
    try {
        const result = await client.auth.test();
        if (result.ok) {
            isAuthenticated = true;
            isReady = true;
            currentUserId = result.user_id;
            currentTeamId = result.team_id;
            console.log('[Slack] Connected successfully');
            console.log(`[Slack] User: ${result.user} (${result.user_id})`);
            console.log(`[Slack] Team: ${result.team} (${result.team_id})`);
            
            // Setup real-time event listeners
            setupEventListeners();
        } else {
            console.error('[Slack] Authentication failed:', result.error);
            isAuthenticated = false;
            isReady = false;
        }
    } catch (error) {
        console.error('[Slack] Connection test failed:', error.message);
        isAuthenticated = false;
        isReady = false;
    }
}

/**
 * Setup Slack event listeners for real-time updates
 */
function setupEventListeners() {
    // Prefer Socket Mode if app token is provided; otherwise fallback to polling
    startSocketModeIfConfigured();
    if (!socketModeEnabled) {
        startRealtimePolling();
    }
}

function startSocketModeIfConfigured() {
    const appToken = getAppToken();
    if (!appToken) {
        socketModeEnabled = false;
        console.log('[Slack] Socket Mode not enabled (SLACK_APP_TOKEN missing). Using polling fallback.');
        return;
    }

    if (!process.env.SLACK_BOT_TOKEN) {
        socketModeEnabled = false;
        console.log('[Slack] Socket Mode requires SLACK_BOT_TOKEN. Using polling fallback.');
        return;
    }

    if (socketModeClient) {
        socketModeEnabled = true;
        return;
    }

    try {
        socketModeClient = new SocketModeClient({
            appToken: appToken,
            client: client // reuse WebClient (bot token)
        });

        socketModeClient.on('connected', () => {
            socketModeEnabled = true;
            console.log('[Slack] Socket Mode connected ✓ (instant real-time enabled)');
            // We can stop polling to avoid rate limits
            stopRealtimePolling();
        });

        socketModeClient.on('disconnected', () => {
            socketModeEnabled = false;
            console.log('[Slack] Socket Mode disconnected (falling back to polling)');
            startRealtimePolling();
        });

        socketModeClient.on('error', (err) => {
            socketModeEnabled = false;
            console.error('[Slack] Socket Mode error:', err && err.message ? err.message : err);
            // Keep polling as fallback
            startRealtimePolling();
        });

        // Handle events (message create/update/delete)
        socketModeClient.on('events_api', async ({ body, ack }) => {
            try {
                await ack();
            } catch (e) {}

            try {
                const event = body && body.event ? body.event : null;
                if (!event) return;

                // We only care about messages in channels the UI is currently viewing (activeChannels)
                const channelId = event.channel;
                if (!channelId || !activeChannels.has(channelId)) return;

                // message.* events
                if (event.type === 'message') {
                    // Ignore bot/self echoes where possible (still allow if you want to see them)
                    if (event.subtype === 'message_changed') {
                        const updated = event.message || null;
                        if (!updated || !updated.ts) return;
                        const channelInfo = await getChannelInfo(channelId);
                        await getUserInfo(updated.user || updated.user_id || event.user);
                        const formatted = formatSlackMessage({ ...updated, channel: channelId }, channelInfo);
                        if (formatted) {
                            lastMessageTimestamps.set(channelId, formatted.id);
                            io.to(`channel_${channelId}`).emit('slack_message_updated', formatted);
                        }
                        return;
                    }

                    if (event.subtype === 'message_deleted') {
                        const deletedTs = event.deleted_ts || (event.previous_message && event.previous_message.ts) || null;
                        if (!deletedTs) return;
                        io.to(`channel_${channelId}`).emit('slack_message_deleted', {
                            channel_id: channelId,
                            message_ts: String(deletedTs)
                        });
                        return;
                    }

                    // Normal message (no subtype) or other subtypes we still render if they have ts/text
                    const channelInfo = await getChannelInfo(channelId);
                    await getUserInfo(event.user);
                    const formatted = formatSlackMessage({ ...event, channel: channelId }, channelInfo);
                    if (formatted) {
                        // Update last timestamp so polling (if running) doesn't duplicate
                        lastMessageTimestamps.set(channelId, formatted.id);
                        io.to(`channel_${channelId}`).emit('slack_message', formatted);
                    }
                }
            } catch (err) {
                console.error('[Slack] Socket Mode events_api handler error:', err && err.message ? err.message : err);
            }
        });

        socketModeClient.start().catch((e) => {
            socketModeEnabled = false;
            console.error('[Slack] Socket Mode start failed:', e && e.message ? e.message : e);
            startRealtimePolling();
        });
    } catch (e) {
        socketModeEnabled = false;
        console.error('[Slack] Socket Mode init failed:', e && e.message ? e.message : e);
        startRealtimePolling();
    }
}

/**
 * Start server-side polling for real-time message updates
 */
function startRealtimePolling() {
    if (realtimePollInterval) {
        clearInterval(realtimePollInterval);
    }

    console.log('[Slack] Starting server-side real-time polling...');
    
    realtimePollInterval = setInterval(async () => {
        if (!client || !isReady) {
            return;
        }
        
        if (activeChannels.size === 0) {
            // No active channels, skip polling
            return;
        }

        // Poll all active channels for new messages
        // Process channels sequentially to avoid rate limits
        for (const channelId of activeChannels) {
            try {
                const lastTs = lastMessageTimestamps.get(channelId);
                
                // Fetch the most recent messages (without timestamp filter)
                // We'll filter for new messages by comparing timestamps
                const result = await client.conversations.history({
                    channel: channelId,
                    limit: 10 // Reduced to avoid rate limits
                });

                if (result.ok && result.messages && result.messages.length > 0) {
                    // Get channel info and user info for new messages
                    const channelInfo = await getChannelInfo(channelId);
                    const userIds = new Set();
                    result.messages.forEach(msg => {
                        if (msg.user) userIds.add(msg.user);
                    });
                    await Promise.all(Array.from(userIds).map(userId => getUserInfo(userId)));

                    // Format messages and filter for NEW messages only
                    const newMessages = [];
                    let newestTs = lastTs;
                    
                    // Slack returns messages in reverse chronological order (newest first)
                    // So we iterate forward and check if each message is newer than lastTs
                    for (const msg of result.messages) {
                        const msgTs = msg.ts;
                        const msgTsNum = parseFloat(msgTs);
                        const lastTsNum = lastTs ? parseFloat(lastTs) : 0;
                        
                        // Only process messages newer than lastTs
                        if (!lastTs || msgTsNum > lastTsNum) {
                            // conversations.history messages don't include channel; inject it so frontend can route correctly
                            const formattedMessage = formatSlackMessage({ ...msg, channel: channelId }, channelInfo);
                            if (formattedMessage) {
                                newMessages.push(formattedMessage);
                                // Track newest timestamp
                                if (!newestTs || msgTsNum > parseFloat(newestTs)) {
                                    newestTs = msgTs;
                                }
                            }
                        } else {
                            // Messages are in reverse order, so if we hit an older one, we can stop
                            break;
                        }
                    }

                    // Emit new messages and update timestamp
                    if (newMessages.length > 0) {
                        lastMessageTimestamps.set(channelId, newestTs);
                        
                        // Emit each message to all clients in this channel room
                        for (const formattedMessage of newMessages) {
                            const room = io.sockets.adapter.rooms.get(`channel_${channelId}`);
                            const roomSize = room ? room.size : 0;
                            console.log(`[Slack] Emitting message to channel ${channelId} (${roomSize} clients in room)`);
                            io.to(`channel_${channelId}`).emit('slack_message', formattedMessage);
                            console.log(`[Slack] ✓ New message in ${channelId} from ${formattedMessage.fromName || formattedMessage.from}: ${formattedMessage.body.substring(0, 50)}...`);
                        }
                    }
                }
                
                // Small delay between channels to avoid rate limits
                await new Promise(resolve => setTimeout(resolve, 100));
            } catch (error) {
                // Handle rate limiting gracefully
                if (error.message && error.message.includes('rate limit')) {
                    console.log(`[Slack] Rate limited for channel ${channelId}, will retry later`);
                    // Skip this channel for now
                    continue;
                }
                // Silently handle other errors (channel might not be accessible, etc.)
                if (error.message && !error.message.includes('not_in_channel') && !error.message.includes('channel_not_found')) {
                    console.error(`[Slack] Error polling channel ${channelId}:`, error.message);
                }
            }
        }
    }, 3000); // Poll every 3 seconds to avoid rate limits
}

/**
 * Stop server-side polling
 */
function stopRealtimePolling() {
    if (realtimePollInterval) {
        clearInterval(realtimePollInterval);
        realtimePollInterval = null;
        console.log('[Slack] Stopped server-side real-time polling');
    }
}

/**
 * Format Slack message for frontend
 */
function formatSlackMessage(msg, channelInfo = null) {
    if (!msg) return null;
    
    const message = {
        id: msg.ts || msg.client_msg_id || Date.now().toString(),
        body: msg.text || '',
        from: msg.user || '',
        fromMe: msg.user === currentUserId,
        fromName: null, // Will be resolved from user cache
        timestamp: msg.ts ? parseFloat(msg.ts) * 1000 : Date.now(),
        channel_id: msg.channel || '',
        channel_name: channelInfo ? channelInfo.name : '',
        hasMedia: false,
        mediaUrl: null,
        mediaMimetype: null,
        mediaFilename: null,
        file_id: null,
        is_thread: !!msg.thread_ts,
        thread_ts: msg.thread_ts || null,
        reactions: msg.reactions || [],
        attachments: msg.files || [],
        blocks: msg.blocks || []
    };

    // Handle files/attachments
    if (msg.files && msg.files.length > 0) {
        const file = msg.files[0];
        message.hasMedia = true;
        message.file_id = file.id;
        message.mediaUrl = file.url_private || file.permalink || null;
        message.mediaMimetype = file.mimetype || null;
        message.mediaFilename = file.name || null;
    }

    // Resolve user name from cache
    if (msg.user && userCache.has(msg.user)) {
        const user = userCache.get(msg.user);
        message.fromName = user.real_name || user.name || user.display_name || '';
    }

    return message;
}

/**
 * Get user info (with caching)
 */
async function getUserInfo(userId) {
    if (!userId || !client) return null;
    
    if (userCache.has(userId)) {
        return userCache.get(userId);
    }

    try {
        const result = await client.users.info({ user: userId });
        if (result.ok && result.user) {
            userCache.set(userId, result.user);
            return result.user;
        }
    } catch (error) {
        console.error(`[Slack] Error fetching user ${userId}:`, error.message);
    }
    
    return null;
}

/**
 * Get channel info (with caching)
 */
async function getChannelInfo(channelId) {
    if (!channelId || !client) return null;
    
    if (channelCache.has(channelId)) {
        return channelCache.get(channelId);
    }

    try {
        const result = await client.conversations.info({ channel: channelId });
        if (result.ok && result.channel) {
            channelCache.set(channelId, result.channel);
            return result.channel;
        }
    } catch (error) {
        console.error(`[Slack] Error fetching channel ${channelId}:`, error.message);
    }
    
    return null;
}

// Health check endpoint
app.get('/health', (req, res) => {
    res.json({ status: 'running', service: 'Slack Server', port: PORT });
});

// Status endpoint
app.get('/api/slack/status', async (req, res) => {
    try {
        if (!client) {
            initializeSlack();
        }

        if (!isReady || !isAuthenticated) {
            await testConnection();
        }

        res.json({
            success: true,
            connected: isAuthenticated && isReady,
            authenticated: isAuthenticated,
            message: isAuthenticated ? 'Connected to Slack' : 'Not connected. Please check your token.',
            user_id: currentUserId,
            team_id: currentTeamId
        });
    } catch (error) {
        console.error('[Slack] Status error:', error);
        res.status(500).json({
            success: false,
            connected: false,
            authenticated: false,
            error: error.message
        });
    }
});

// Get channels list
app.get('/api/slack/channels', async (req, res) => {
    try {
        if (!client || !isReady) {
            return res.status(503).json({
                success: false,
                error: 'Slack not connected. Please check your token.'
            });
        }

        const startTime = Date.now();
        console.log('[Slack] Fetching channels list...');
        
        // Fetch all channel types: public channels, private channels, DMs, group DMs
        const [publicChannels, privateChannels, conversations] = await Promise.all([
            client.conversations.list({ types: 'public_channel', limit: 200, exclude_archived: true }).catch(() => ({ ok: false, channels: [] })),
            client.conversations.list({ types: 'private_channel', limit: 200, exclude_archived: true }).catch(() => ({ ok: false, channels: [] })),
            client.conversations.list({ types: 'im,mpim', limit: 200, exclude_archived: true }).catch(() => ({ ok: false, channels: [] }))
        ]);

        const allChannels = [
            ...(publicChannels.ok ? publicChannels.channels : []),
            ...(privateChannels.ok ? privateChannels.channels : []),
            ...(conversations.ok ? conversations.channels : [])
        ];

        // Cache all channels first
        allChannels.forEach(channel => {
            channelCache.set(channel.id, channel);
        });

        // Batch fetch user info for DMs (much faster than sequential)
        const dmUserIds = allChannels.filter(c => c.is_im && c.user).map(c => c.user);
        const uniqueUserIds = [...new Set(dmUserIds)];
        await Promise.all(uniqueUserIds.map(userId => getUserInfo(userId)));

        // Format channels without fetching last message (load on-demand for speed)
        const channels = allChannels.map(channel => {
            // Determine channel name
            let channelName = channel.name || '';
            if (channel.is_im) {
                const userId = channel.user;
                if (userId && userCache.has(userId)) {
                    const user = userCache.get(userId);
                    channelName = user.real_name || user.name || user.display_name || 'Unknown';
                } else {
                    channelName = 'Direct Message';
                }
            } else if (channel.is_mpim) {
                channelName = channel.name || 'Group DM';
            }

            return {
                channel_id: channel.id,
                channel_name: channelName,
                channel_type: channel.is_im ? 'DM' : (channel.is_mpim ? 'Group DM' : (channel.is_private ? 'Private' : 'Channel')),
                last_message: null, // Load on-demand
                last_message_time: null, // Load on-demand
                unread_count: 0, // Load on-demand
                is_archived: channel.is_archived || false,
                is_member: channel.is_member || false
            };
        });

        // Sort by channel name (alphabetical) for faster display
        channels.sort((a, b) => {
            return a.channel_name.localeCompare(b.channel_name);
        });

        console.log(`[Slack] Found ${channels.length} channels (loaded in ${Date.now() - startTime}ms)`);
        
        res.json({
            success: true,
            count: channels.length,
            channels: channels
        });
    } catch (error) {
        console.error('[Slack] Error fetching channels:', error);
        res.status(500).json({
            success: false,
            error: error.message
        });
    }
});

// Get messages for a channel
app.post('/api/slack/messages', async (req, res) => {
    try {
        if (!client || !isReady) {
            return res.status(503).json({
                success: false,
                error: 'Slack not connected. Please check your token.'
            });
        }

        const { channel_id, limit = 50 } = req.body;

        if (!channel_id) {
            return res.status(400).json({
                success: false,
                error: 'channel_id is required'
            });
        }

        console.log(`[Slack] Fetching messages for channel ${channel_id}...`);

        // Get channel info
        const channelInfo = await getChannelInfo(channel_id);
        if (!channelInfo) {
            return res.status(404).json({
                success: false,
                error: 'Channel not found'
            });
        }

        // Fetch messages
        const result = await client.conversations.history({
            channel: channel_id,
            limit: Math.min(limit, 200) // Slack API limit
        });

        if (!result.ok) {
            return res.status(500).json({
                success: false,
                error: result.error || 'Failed to fetch messages'
            });
        }

        // Fetch user info for all unique users in messages
        const userIds = new Set();
        result.messages.forEach(msg => {
            if (msg.user) userIds.add(msg.user);
        });

        await Promise.all(Array.from(userIds).map(userId => getUserInfo(userId)));

        // Format messages
        const messages = result.messages
            // conversations.history messages don't include channel; inject it so frontend can route correctly
            .map(msg => formatSlackMessage({ ...msg, channel: channel_id }, channelInfo))
            .filter(msg => msg !== null)
            .reverse(); // Oldest first

        // Cache messages
        messageCache.set(channel_id, messages);

        // Update last message timestamp for real-time polling
        // Use the actual timestamp (ts) from the original message, not the formatted id
        if (result.messages && result.messages.length > 0) {
            // Slack returns newest first, so first message is the newest
            const newestMsg = result.messages[0];
            if (newestMsg.ts) {
                lastMessageTimestamps.set(channel_id, newestMsg.ts);
                console.log(`[Slack] Set last timestamp for ${channel_id}: ${newestMsg.ts}`);
            }
        }

        console.log(`[Slack] Found ${messages.length} messages`);

        res.json({
            success: true,
            count: messages.length,
            total_count: result.response_metadata?.next_cursor ? 'more' : messages.length,
            messages: messages
        });
    } catch (error) {
        console.error('[Slack] Error fetching messages:', error);
        res.status(500).json({
            success: false,
            error: error.message
        });
    }
});

// Send message
app.post('/api/slack/send', async (req, res) => {
    try {
        if (!client || !isReady) {
            return res.status(503).json({
                success: false,
                error: 'Slack not connected. Please check your token.'
            });
        }

        const { channel_id, text, thread_ts } = req.body;

        if (!channel_id || !text) {
            return res.status(400).json({
                success: false,
                error: 'channel_id and text are required'
            });
        }

        console.log(`[Slack] Sending message to channel ${channel_id}...`);

        const result = await client.chat.postMessage({
            channel: channel_id,
            text: text,
            thread_ts: thread_ts || undefined
        });

        if (!result.ok) {
            return res.status(500).json({
                success: false,
                error: result.error || 'Failed to send message'
            });
        }

        // Emit real-time update
        const channelInfo = await getChannelInfo(channel_id);
        const formattedMessage = formatSlackMessage(result.message, channelInfo);
        if (formattedMessage) {
            io.emit('slack_message', formattedMessage);
        }

        res.json({
            success: true,
            message: 'Message sent successfully',
            message_ts: result.ts,
            message_id: result.ts
        });
    } catch (error) {
        console.error('[Slack] Error sending message:', error);
        res.status(500).json({
            success: false,
            error: error.message
        });
    }
});

// Get avatar
app.get('/api/slack/avatar', async (req, res) => {
    try {
        if (!client || !isReady) {
            return res.status(503).json({
                success: false,
                error: 'Slack not connected'
            });
        }

        const { user_id } = req.query;
        if (!user_id) {
            return res.status(400).json({
                success: false,
                error: 'user_id is required'
            });
        }

        // Check cache
        const avatarPath = path.join(AVATAR_DIR, `${user_id}.json`);
        if (fs.existsSync(avatarPath)) {
            try {
                const cached = JSON.parse(fs.readFileSync(avatarPath, 'utf8'));
                if (cached.avatar_url) {
                    return res.json({
                        success: true,
                        avatar_url: cached.avatar_url
                    });
                }
            } catch (e) {
                // Ignore cache read errors
            }
        }

        // Fetch user info
        const user = await getUserInfo(user_id);
        if (!user) {
            return res.status(404).json({
                success: false,
                error: 'User not found'
            });
        }

        const avatarUrl = user.profile?.image_72 || user.profile?.image_48 || user.profile?.image_32 || null;

        // Cache avatar URL
        if (avatarUrl) {
            try {
                fs.writeFileSync(avatarPath, JSON.stringify({ avatar_url: avatarUrl }), 'utf8');
            } catch (e) {
                // Ignore cache write errors
            }
        }

        res.json({
            success: true,
            avatar_url: avatarUrl
        });
    } catch (error) {
        console.error('[Slack] Error fetching avatar:', error);
        res.status(500).json({
            success: false,
            error: error.message
        });
    }
});

// Get media/file
app.get('/api/slack/media/:file_id', async (req, res) => {
    try {
        if (!client || !isReady) {
            return res.status(503).json({
                success: false,
                error: 'Slack not connected'
            });
        }

        const { file_id } = req.params;
        const { download } = req.query;

        console.log(`[Slack] Fetching file ${file_id}...`);

        const result = await client.files.info({ file: file_id });
        if (!result.ok || !result.file) {
            return res.status(404).json({
                success: false,
                error: 'File not found'
            });
        }

        const file = result.file;
        const fileUrl = file.url_private || file.permalink;

        if (!fileUrl) {
            return res.status(404).json({
                success: false,
                error: 'File URL not available'
            });
        }

        // Redirect to Slack's file URL (requires authentication)
        // In production, you might want to proxy the file through your server
        res.redirect(fileUrl);
    } catch (error) {
        console.error('[Slack] Error fetching media:', error);
        res.status(500).json({
            success: false,
            error: error.message
        });
    }
});

// Edit message endpoint
app.post('/api/slack/edit', async (req, res) => {
    try {
        if (!client || !isReady) {
            return res.status(503).json({
                success: false,
                error: 'Slack not connected. Please check your token.'
            });
        }

        const { channel_id, message_ts, text } = req.body;

        if (!channel_id || !message_ts || !text) {
            return res.status(400).json({
                success: false,
                error: 'channel_id, message_ts, and text are required'
            });
        }

        console.log(`[Slack] Editing message ${message_ts} in channel ${channel_id}...`);

        const result = await client.chat.update({
            channel: channel_id,
            ts: message_ts,
            text: text
        });

        if (!result.ok) {
            return res.status(500).json({
                success: false,
                error: result.error || 'Failed to edit message'
            });
        }

        // Emit real-time update
        const channelInfo = await getChannelInfo(channel_id);
        const formattedMessage = formatSlackMessage(result.message, channelInfo);
        if (formattedMessage) {
            io.emit('slack_message_updated', formattedMessage);
        }

        res.json({
            success: true,
            message: 'Message edited successfully',
            message_ts: result.ts
        });
    } catch (error) {
        console.error('[Slack] Error editing message:', error);
        res.status(500).json({
            success: false,
            error: error.message
        });
    }
});

// Delete message endpoint
app.post('/api/slack/delete', async (req, res) => {
    try {
        if (!client || !isReady) {
            return res.status(503).json({
                success: false,
                error: 'Slack not connected. Please check your token.'
            });
        }

        const { channel_id, message_ts } = req.body;

        if (!channel_id || !message_ts) {
            return res.status(400).json({
                success: false,
                error: 'channel_id and message_ts are required'
            });
        }

        console.log(`[Slack] Deleting message ${message_ts} from channel ${channel_id}...`);

        const result = await client.chat.delete({
            channel: channel_id,
            ts: message_ts
        });

        if (!result.ok) {
            return res.status(500).json({
                success: false,
                error: result.error || 'Failed to delete message'
            });
        }

        // Emit real-time update
        io.emit('slack_message_deleted', {
            channel_id: channel_id,
            message_ts: message_ts
        });

        res.json({
            success: true,
            message: 'Message deleted successfully'
        });
    } catch (error) {
        console.error('[Slack] Error deleting message:', error);
        res.status(500).json({
            success: false,
            error: error.message
        });
    }
});

// Reply to message (thread) endpoint
app.post('/api/slack/reply', async (req, res) => {
    try {
        if (!client || !isReady) {
            return res.status(503).json({
                success: false,
                error: 'Slack not connected. Please check your token.'
            });
        }

        const { channel_id, thread_ts, text } = req.body;

        if (!channel_id || !thread_ts || !text) {
            return res.status(400).json({
                success: false,
                error: 'channel_id, thread_ts, and text are required'
            });
        }

        console.log(`[Slack] Replying to thread ${thread_ts} in channel ${channel_id}...`);

        const result = await client.chat.postMessage({
            channel: channel_id,
            thread_ts: thread_ts,
            text: text
        });

        if (!result.ok) {
            return res.status(500).json({
                success: false,
                error: result.error || 'Failed to send reply'
            });
        }

        // Emit real-time update
        const channelInfo = await getChannelInfo(channel_id);
        const formattedMessage = formatSlackMessage(result.message, channelInfo);
        if (formattedMessage) {
            io.emit('slack_message', formattedMessage);
        }

        res.json({
            success: true,
            message: 'Reply sent successfully',
            message_ts: result.ts,
            message_id: result.ts
        });
    } catch (error) {
        console.error('[Slack] Error sending reply:', error);
        res.status(500).json({
            success: false,
            error: error.message
        });
    }
});

// Polling endpoint for real-time updates (fallback when WebSocket isn't available)
app.post('/api/slack/poll', async (req, res) => {
    try {
        if (!client || !isReady) {
            return res.status(503).json({
                success: false,
                error: 'Slack not connected'
            });
        }

        const { channel_id, last_message_ts } = req.body;

        if (!channel_id) {
            return res.status(400).json({
                success: false,
                error: 'channel_id is required'
            });
        }

        // Fetch new messages since last_message_ts
        // Use 'oldest' with a timestamp slightly after last_message_ts to get newer messages
        // Slack returns messages in reverse chronological order (newest first)
        const result = await client.conversations.history({
            channel: channel_id,
            limit: 50,
            oldest: last_message_ts ? (parseFloat(last_message_ts) + 0.000001).toString() : undefined
        });

        if (!result.ok) {
            return res.status(500).json({
                success: false,
                error: result.error || 'Failed to poll messages'
            });
        }

        const channelInfo = await getChannelInfo(channel_id);
        const userIds = new Set();
        result.messages.forEach(msg => {
            if (msg.user) userIds.add(msg.user);
        });
        await Promise.all(Array.from(userIds).map(userId => getUserInfo(userId)));

        const messages = result.messages
            // conversations.history messages don't include channel; inject it so frontend can route correctly
            .map(msg => formatSlackMessage({ ...msg, channel: channel_id }, channelInfo))
            .filter(msg => msg !== null);

        res.json({
            success: true,
            count: messages.length,
            messages: messages
        });
    } catch (error) {
        console.error('[Slack] Error polling messages:', error);
        res.status(500).json({
            success: false,
            error: error.message
        });
    }
});

// WebSocket connection
io.on('connection', (socket) => {
    console.log('[Slack] Client connected');
    
    socket.on('disconnect', () => {
        console.log('[Slack] Client disconnected');
    });

    // Join channel room for targeted updates
    socket.on('join_channel', async (channelId) => {
        socket.join(`channel_${channelId}`);
        activeChannels.add(channelId);
        console.log(`[Slack] Client joined channel ${channelId} (${activeChannels.size} active channels)`);
        
        // Initialize last message timestamp if not set
        if (!lastMessageTimestamps.has(channelId)) {
            try {
                // Get the latest message timestamp
                const result = await client.conversations.history({
                    channel: channelId,
                    limit: 1
                });
                
                if (result.ok && result.messages && result.messages.length > 0) {
                    const latestTs = result.messages[0].ts;
                    lastMessageTimestamps.set(channelId, latestTs);
                    console.log(`[Slack] Initialized timestamp for ${channelId}: ${latestTs}`);
                } else {
                    // No messages yet, set to current time minus a bit
                    const now = (Date.now() / 1000).toString();
                    lastMessageTimestamps.set(channelId, now);
                }
            } catch (error) {
                console.error(`[Slack] Error initializing timestamp for ${channelId}:`, error.message);
                // Set to current time as fallback
                const now = (Date.now() / 1000).toString();
                lastMessageTimestamps.set(channelId, now);
            }
        }
    });

    socket.on('leave_channel', (channelId) => {
        socket.leave(`channel_${channelId}`);
        // Only remove from active channels if no other clients are in this channel
        const room = io.sockets.adapter.rooms.get(`channel_${channelId}`);
        if (!room || room.size === 0) {
            activeChannels.delete(channelId);
            lastMessageTimestamps.delete(channelId);
        }
        console.log(`[Slack] Client left channel ${channelId}`);
    });
});

// Initialize on startup
initializeSlack();

// Cleanup on shutdown
process.on('SIGINT', () => {
    console.log('\n[Slack] Shutting down...');
    stopRealtimePolling();
    try { if (socketModeClient) socketModeClient.disconnect(); } catch (e) {}
    process.exit(0);
});

process.on('SIGTERM', () => {
    console.log('\n[Slack] Shutting down...');
    stopRealtimePolling();
    try { if (socketModeClient) socketModeClient.disconnect(); } catch (e) {}
    process.exit(0);
});

// Start server
server.listen(PORT, () => {
    console.log(`[Slack] Server running on http://72.62.162.44:${PORT}`);
    console.log(`[Slack] Health check: http://72.62.162.44:${PORT}/health`);
});

