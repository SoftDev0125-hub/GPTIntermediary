// Parses many natural-language WhatsApp send/reply commands.
// Returns { platform: 'whatsapp', action: 'send'|'reply', recipient, body, fromAccount } or null.
function parseWhatsAppCommand(text) {
  if (!text || typeof text !== 'string') return null;
  const s = text.trim();

  const reReply = /^\s*(?:reply|respond)(?:\s+to)?\s+(.+?)(?:\s+(?:on|via)\s+whatsapp)?(?:\s*(?:\:|with)\s*)([\s\S]+)$/i;
  const reSendWithContent = /^\s*(?:send|send a message|send message)\s+(?:with\s+(?:the\s+)?content\s+)?["']?([\s\S]+?)["']?\s+(?:to)\s+(.+?)(?:\s+(?:on|via)\s+whatsapp)?(?:\s+from\s+(.+))?$/i;
  const reMessageColon = /^\s*(?:message|msg)\s+(.+?)(?:\s+(?:on|via)\s+whatsapp)?\s*(?:\:|\-)\s*([\s\S]+)$/i;
  const reSendTo = /^\s*(?:send)\s+["']?([\s\S]+?)["']?\s+to\s+(.+?)(?:\s+(?:on|via)\s+whatsapp)?(?:\s+from\s+(.+))?$/i;
  const reSimpleTo = /^\s*(?:send|message)\s+(.+?)\s+(?:on|via)\s+whatsapp\b(?:\s*(?:\:|\-)\s*|\s+)([\s\S]+)$/i;
  const reToThenText = /^\s*(?:send|message)\s+(.+?)\s+to\s+(.+?)(?:\s+(?:on|via)\s+whatsapp)?(?:\s*(?:\:|\-)\s*|\s+)([\s\S]+)$/i;

  let m;
  if ((m = s.match(reReply))) {
    return { platform: 'whatsapp', action: 'reply', recipient: m[1].trim(), body: m[2].trim() };
  }
  if ((m = s.match(reSendWithContent))) {
    return { platform: 'whatsapp', action: 'send', recipient: m[2].trim(), body: m[1].trim(), fromAccount: m[3] ? m[3].trim() : null };
  }
  if ((m = s.match(reMessageColon))) {
    return { platform: 'whatsapp', action: 'send', recipient: m[1].trim(), body: m[2].trim() };
  }
  if ((m = s.match(reSendTo))) {
    return { platform: 'whatsapp', action: 'send', recipient: m[2].trim(), body: m[1].trim(), fromAccount: m[3] ? m[3].trim() : null };
  }
  if ((m = s.match(reSimpleTo))) {
    return { platform: 'whatsapp', action: 'send', recipient: m[1].trim(), body: m[2].trim() };
  }
  if ((m = s.match(reToThenText))) {
    return { platform: 'whatsapp', action: 'send', recipient: m[2].trim(), body: m[3].trim() };
  }

  const lower = s.toLowerCase();
  if (lower.includes('whatsapp') && lower.includes(' to ')) {
    const parts = s.split(/\s+to\s+/i);
    const last = parts.pop();
    const rest = parts.join(' to ');
    if (last && rest) {
      const recip = last.replace(/\s+(?:on|via)\s+whatsapp\b/i, '').trim();
      const body = rest.replace(/\s+(?:on|via)\s+whatsapp\b/i, '').trim();
      if (recip && body) return { platform: 'whatsapp', action: 'send', recipient: recip, body: body };
    }
  }

  return null;
}

module.exports = { parseWhatsAppCommand };
// Parses many natural-language WhatsApp send/reply commands.
// Returns { platform: 'whatsapp', action: 'send'|'reply', recipient, body, fromAccount } or null.
function parseWhatsAppCommand(text) {
  if (!text || typeof text !== 'string') return null;
  const s = text.trim();

  const reReply = /^\s*(?:reply|respond)(?:\s+to)?\s+(.+?)(?:\s+(?:on|via)\s+whatsapp)?(?:\s*(?:\:|with)\s*)([\s\S]+)$/i;
  const reSendWithContent = /^\s*(?:send|send a message|send message)\s+(?:with\s+(?:the\s+)?content\s+)?["']?([\s\S]+?)["']?\s+(?:to)\s+(.+?)(?:\s+(?:on|via)\s+whatsapp)?(?:\s+from\s+(.+))?$/i;
  const reMessageColon = /^\s*(?:message|msg)\s+(.+?)(?:\s+(?:on|via)\s+whatsapp)?\s*(?:\:|\-)\s*([\s\S]+)$/i;
  const reSendTo = /^\s*(?:send)\s+["']?([\s\S]+?)["']?\s+to\s+(.+?)(?:\s+(?:on|via)\s+whatsapp)?(?:\s+from\s+(.+))?$/i;
  const reSimpleTo = /^\s*(?:send|message)\s+(.+?)\s+(?:on|via)\s+whatsapp\b(?:\s*(?:\:|\-)\s*|\s+)([\s\S]+)$/i;
  const reToThenText = /^\s*(?:send|message)\s+(.+?)\s+to\s+(.+?)(?:\s+(?:on|via)\s+whatsapp)?(?:\s*(?:\:|\-)\s*|\s+)([\s\S]+)$/i;

  let m;
  if ((m = s.match(reReply))) {
    return { platform: 'whatsapp', action: 'reply', recipient: m[1].trim(), body: m[2].trim() };
  }
  if ((m = s.match(reSendWithContent))) {
    return { platform: 'whatsapp', action: 'send', recipient: m[2].trim(), body: m[1].trim(), fromAccount: m[3] ? m[3].trim() : null };
  }
  if ((m = s.match(reMessageColon))) {
    return { platform: 'whatsapp', action: 'send', recipient: m[1].trim(), body: m[2].trim() };
  }
  if ((m = s.match(reSendTo))) {
    return { platform: 'whatsapp', action: 'send', recipient: m[2].trim(), body: m[1].trim(), fromAccount: m[3] ? m[3].trim() : null };
  }
  if ((m = s.match(reSimpleTo))) {
    return { platform: 'whatsapp', action: 'send', recipient: m[1].trim(), body: m[2].trim() };
  }
  if ((m = s.match(reToThenText))) {
    return { platform: 'whatsapp', action: 'send', recipient: m[2].trim(), body: m[3].trim() };
  }

  const lower = s.toLowerCase();
  if (lower.includes('whatsapp') && lower.includes(' to ')) {
    const parts = s.split(/\s+to\s+/i);
    const last = parts.pop();
    const rest = parts.join(' to ');
    if (last && rest) {
      const recip = last.replace(/\s+(?:on|via)\s+whatsapp\b/i, '').trim();
      const body = rest.replace(/\s+(?:on|via)\s+whatsapp\b/i, '').trim();
      if (recip && body) return { platform: 'whatsapp', action: 'send', recipient: recip, body: body };
    }
  }

  return null;
}

module.exports = { parseWhatsAppCommand };
