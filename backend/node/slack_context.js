/**
 * Per-user Slack session state (multi-tenant). Legacy single-tenant uses one shared context.
 */
const path = require('path');
const fs = require('fs');

const PROJECT_ROOT = path.join(__dirname, '..', '..');

function createSlackContext(userId) {
  const uid = userId != null ? Number(userId) : null;
  const sessionRoot =
    uid != null && !Number.isNaN(uid)
      ? path.join(PROJECT_ROOT, 'slack_session_node', `user_${uid}`)
      : path.join(PROJECT_ROOT, 'slack_session_node');
  const avatarDir = path.join(sessionRoot, 'avatars');
  try {
    if (!fs.existsSync(sessionRoot)) fs.mkdirSync(sessionRoot, { recursive: true });
    if (!fs.existsSync(avatarDir)) fs.mkdirSync(avatarDir, { recursive: true });
  } catch (e) {
    console.error('[SlackContext] mkdir failed:', e && e.message);
  }

  return {
    userId: uid,
    SESSION_DIR: sessionRoot,
    AVATAR_DIR: avatarDir,
    client: null,
    isAuthenticated: false,
    isReady: false,
    currentUserId: null,
    currentTeamId: null,
    channelCache: new Map(),
    messageCache: new Map(),
    avatarCache: new Map(),
    userCache: new Map(),
    activeChannels: new Set(),
    lastMessageTimestamps: new Map(),
    realtimePollInterval: null,
    socketModeClient: null,
    socketModeEnabled: false,
    lastToken: null,
  };
}

module.exports = { createSlackContext, PROJECT_ROOT };
