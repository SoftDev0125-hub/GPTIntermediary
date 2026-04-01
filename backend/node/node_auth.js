/**
 * Shared JWT + multi-tenant checks for Node integration servers (WhatsApp, Telegram, Slack).
 * Must match backend/python/auth_utils.py (HS256, SECRET_KEY, payload.user_id).
 */
const path = require('path');
try {
  require('dotenv').config({ path: path.join(__dirname, '..', '..', '.env') });
} catch (e) { /* optional */ }

function isMultiTenant() {
  const v = (process.env.MULTI_TENANT_MODE || '').trim().toLowerCase();
  return v === '1' || v === 'true' || v === 'yes' || v === 'on';
}

function getJwtSecret() {
  return (
    process.env.SECRET_KEY ||
    'your-secret-key-change-this-in-production-please-use-a-secure-random-string'
  );
}

/**
 * @param {string|undefined} authHeader - Authorization header value
 * @returns {number|null} user_id or null
 */
function verifyBearerUserId(authHeader) {
  if (!authHeader || typeof authHeader !== 'string') return null;
  const m = authHeader.match(/^Bearer\s+(.+)$/i);
  if (!m) return null;
  let jwt;
  try {
    jwt = require('jsonwebtoken');
  } catch (e) {
    console.error('[node_auth] Install jsonwebtoken: npm install jsonwebtoken');
    return null;
  }
  try {
    const payload = jwt.verify(m[1].trim(), getJwtSecret(), { algorithms: ['HS256'] });
    const uid = payload.user_id;
    if (uid == null) return null;
    const n = Number(uid);
    return Number.isFinite(n) ? n : null;
  } catch (e) {
    return null;
  }
}

function backendBaseUrl() {
  return (
    (process.env.BACKEND_URL || process.env.API_BASE || 'http://127.0.0.1:8000').replace(
      /\/$/,
      ''
    )
  );
}

function httpGetJson(urlStr, headers) {
  const http = require('http');
  const https = require('https');
  const u = new URL(urlStr);
  const lib = u.protocol === 'https:' ? https : http;
  return new Promise((resolve, reject) => {
    const req = lib.request(
      urlStr,
      {
        method: 'GET',
        headers: headers || {},
        timeout: 15000,
      },
      (res) => {
        let b = '';
        res.on('data', (c) => {
          b += c;
        });
        res.on('end', () => {
          if (res.statusCode < 200 || res.statusCode >= 300) {
            resolve(null);
            return;
          }
          try {
            resolve(JSON.parse(b));
          } catch (e) {
            resolve(null);
          }
        });
      }
    );
    req.on('error', (e) => reject(e));
    req.on('timeout', () => {
      req.destroy();
      reject(new Error('timeout'));
    });
    req.end();
  });
}

/**
 * @param {string} authHeader
 * @returns {Promise<{ api_id: string|null, api_hash: string|null, phone: string|null }|null>}
 */
async function fetchTelegramConfigFromApi(authHeader) {
  const url = `${backendBaseUrl()}/api/integrations/telegram-config`;
  try {
    return await httpGetJson(url, {
      Authorization: authHeader,
      Accept: 'application/json',
    });
  } catch (e) {
    console.error('[node_auth] fetchTelegramConfigFromApi failed:', e.message || e);
    return null;
  }
}

/**
 * @param {string} authHeader
 * @returns {Promise<{ slack_user_token: string|null, slack_bot_token?: string|null, slack_app_token?: string|null }|null>}
 */
async function fetchSlackConfigFromApi(authHeader) {
  const url = `${backendBaseUrl()}/api/integrations/slack-config`;
  try {
    return await httpGetJson(url, {
      Authorization: authHeader,
      Accept: 'application/json',
    });
  } catch (e) {
    console.error('[node_auth] fetchSlackConfigFromApi failed:', e.message || e);
    return null;
  }
}

module.exports = {
  isMultiTenant,
  getJwtSecret,
  verifyBearerUserId,
  backendBaseUrl,
  fetchTelegramConfigFromApi,
  fetchSlackConfigFromApi,
};
