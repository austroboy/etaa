/**
 * ETAA WhatsApp Bridge
 *
 * Forwards group / DM messages from WhatsApp to the Django backend
 * webhook, and exposes a small REST API the backend can call to send
 * messages back.
 *
 * Environment variables are loaded (in order of precedence):
 *   1. Variables already set in the shell / Docker environment
 *   2. bridge/.env             (a bridge-specific override file)
 *   3. ../.env                 (the project-root .env file used by Django)
 *
 * That last one is what most users want – the same .env file that
 * configures Django will also configure this bridge, so the
 * WHATSAPP_API_TOKEN cannot drift between the two processes.
 */

const path = require("path");
const fs   = require("fs");

// Load .env from bridge/, then from the project root. `override: false`
// means a value already set in process.env wins.
try { require("dotenv").config({ path: path.join(__dirname, ".env"), override: false }); } catch (e) {}
try { require("dotenv").config({ path: path.join(__dirname, "..", ".env"), override: false }); } catch (e) {}

const { Client, LocalAuth, MessageMedia } = require("whatsapp-web.js");
const qrcode  = require("qrcode-terminal");
const express = require("express");
const multer  = require("multer");
const axios   = require("axios");

// ── Configuration ─────────────────────────────────────────────────────────
const PORT       = process.env.WA_BRIDGE_PORT     || 3000;
const API_TOKEN  = process.env.WHATSAPP_API_TOKEN || "etaa-bridge-token";
const DJANGO_URL = process.env.DJANGO_WEBHOOK_URL || "http://localhost:8000/api/messaging/webhook/";

// Debug helpers ─────────────────────────────────────────────────────────────
function tokenFingerprint(t) {
  if (!t) return "(empty)";
  if (t.length <= 6) return `"${t}" (len=${t.length})`;
  return `"${t.slice(0, 3)}…${t.slice(-3)}" (len=${t.length})`;
}

console.log(`[ETAA Bridge] API token fingerprint: ${tokenFingerprint(API_TOKEN)}`);
console.log(`[ETAA Bridge] Django webhook: ${DJANGO_URL}`);

// ── WhatsApp Client ────────────────────────────────────────────────────────
const waClient = new Client({
  authStrategy: new LocalAuth({ dataPath: "./.wwebjs_auth" }),
  puppeteer: {
    headless: true,
    args: ["--no-sandbox", "--disable-setuid-sandbox"],
  },
});

waClient.on("qr", (qr) => {
  console.log("\n[ETAA Bridge] Scan this QR code with your WhatsApp:\n");
  qrcode.generate(qr, { small: true });
});

waClient.on("ready", () => {
  console.log("[ETAA Bridge] WhatsApp client ready.");
  try {
    const myWid = waClient.info && waClient.info.wid;
    if (myWid) {
      console.log(`[ETAA Bridge] Bot phone number: ${myWid.user}`);
      console.log(`[ETAA Bridge] Bot serialized id: ${myWid._serialized}`);
    }
    if (waClient.info && waClient.info.me && waClient.info.me.lid) {
      console.log(`[ETAA Bridge] Bot LID: ${waClient.info.me.lid}`);
    }
  } catch (e) {}
});

// Comma-separated list of phone numbers (no '+', country code included)
// for the three core operators. The bridge forwards DMs only from these.
// Group messages are handled differently – see the addressing logic below.
const CORE_OPERATORS = (process.env.CORE_OPERATOR_PHONES || "")
  .split(",")
  .map(s => s.replace(/\D/g, ""))
  .filter(Boolean);

console.log(`[ETAA Bridge] Core operators (DM whitelist): ${CORE_OPERATORS.join(", ") || "(none configured)"}`);

// Trigger words that count as "addressing the bot" in a group chat,
// in addition to @-mentioning the bot's number / LID.
const TRIGGER_WORDS = (process.env.BOT_TRIGGER_WORDS ||
  "@bot,/bot,/agent,@etaa,hey etaa,hi etaa,etaa,@assistant,@robi,robi")
  .split(",")
  .map(s => s.trim().toLowerCase())
  .filter(Boolean);

console.log(`[ETAA Bridge] Trigger words: ${TRIGGER_WORDS.join(" | ")}`);

/**
 * Decide whether a group message is actually addressed to the bot.
 *
 * The bot must NOT process every message in a group – there could be
 * dozens of people chatting. Only run intent classification when ANY
 * of the following is true:
 *   1. The message @-mentions the bot's phone number, serialized id, or LID.
 *   2. The message is a reply to a previous message the bot sent.
 *   3. The message text contains a trigger word like "@bot", "robi".
 *   4. The sender is a core operator typing a short yes/no/cancel
 *      (probably a confirmation response) or an authorize/revoke command.
 */
async function isAddressedToBot(msg, body) {
  // 1. @-mention
  try {
    const myInfo  = waClient.info || {};
    const myWid   = myInfo.wid || {};
    const myPhone = myWid.user || "";
    const myFull  = myWid._serialized || "";
    const myLid   = (myInfo.me && myInfo.me.lid) || "";

    const idsToCheck = [];
    if (Array.isArray(msg.mentionedIds)) {
      for (const id of msg.mentionedIds) {
        const s = typeof id === "string" ? id : (id && id._serialized) || "";
        if (s) idsToCheck.push(s);
      }
    }
    try {
      const mentions = await msg.getMentions();
      if (Array.isArray(mentions)) {
        for (const m of mentions) {
          if (!m || !m.id) continue;
          if (m.isMe) return true;
          if (m.id._serialized && m.id._serialized === myFull) return true;
          if (m.id._serialized) idsToCheck.push(m.id._serialized);
          if (m.id.user)        idsToCheck.push(m.id.user);
        }
      }
    } catch (e) {}

    for (const id of idsToCheck) {
      if (!id) continue;
      if (myPhone && id.includes(myPhone)) return true;
      if (myFull  && id === myFull)        return true;
      if (myLid   && id.includes(myLid))   return true;
    }
  } catch (e) {}

  // 2. Reply to a bot message
  try {
    if (msg.hasQuotedMsg) {
      const quoted = await msg.getQuotedMessage();
      if (quoted && quoted.fromMe) return true;
    }
  } catch (e) {}

  // 3. Trigger words
  const lower = (body || "").toLowerCase().trim();
  if (!lower) return false;
  for (const trigger of TRIGGER_WORDS) {
    if (lower.startsWith(trigger) || lower.includes(" " + trigger) ||
        lower.includes(trigger + " ") || lower === trigger) {
      return true;
    }
  }

  // 4. Short yes/no or authorize/revoke from a core operator
  try {
    const myContact   = await msg.getContact();
    const senderPhone = myContact.id.user;
    if (CORE_OPERATORS.includes(senderPhone)) {
      if (lower.length <= 20) {
        const yesNo = /^(yes|y|ok|okay|confirm|approved|approve|go|proceed|sure|no|n|cancel|deny|stop|abort)\b[\s.!?]*$/i;
        if (yesNo.test(lower)) return true;
      }
      const authVerb = /\b(authori[sz]e|revoke|grant\s+access|give\s+access|remove\s+access|unauthori[sz]e|approve)\b/i;
      const listVerb = /\b(?:list|show)\s+(?:authorized|authorised|members|operators)\b/i;
      if (authVerb.test(lower) || listVerb.test(lower)) return true;
    }
  } catch (e) {}

  return false;
}

waClient.on("message", async (msg) => {
  try {
    const chat = await msg.getChat();
    const isGroup = !!chat.isGroup;
    const groupJid = isGroup ? chat.id._serialized : "";

    const contact = await msg.getContact();
    const senderPhone = contact.id.user;
    const senderName  = contact.pushname || contact.name || senderPhone;

    const body      = msg.body || "";
    const messageId = msg.id._serialized;

    if (!isGroup) {
      if (CORE_OPERATORS.length && !CORE_OPERATORS.includes(senderPhone)) {
        return;
      }
    } else {
      const addressed = await isAddressedToBot(msg, body);
      if (!addressed) {
        if (process.env.BRIDGE_DEBUG === "1") {
          console.log(
            `[ETAA Bridge] (skip, not addressed) GROUP from ${senderName}: ` +
            `${body.slice(0, 40)}`
          );
        }
        return;
      }
    }

    let quotedPhone = "";
    let quotedName  = "";
    if (msg.hasQuotedMsg) {
      try {
        const quoted = await msg.getQuotedMessage();
        const quotedContact = await quoted.getContact();
        quotedPhone = quotedContact.id.user || "";
        quotedName  = quotedContact.pushname || quotedContact.name || "";
      } catch (e) {}
    }

    // Strip the bot's @-mention or trigger word from the body so the
    // intent parser sees clean instruction text.
    let cleanBody = body;
    try {
      const myInfo  = waClient.info || {};
      const myPhone = (myInfo.wid && myInfo.wid.user) || "";
      const myLid   = (myInfo.me && myInfo.me.lid) || "";
      // Strip @-mentions of any of the bot's identifiers
      for (const id of [myPhone, myLid].filter(Boolean)) {
        cleanBody = cleanBody.replace(new RegExp(`@${id}\\b`, "g"), "").trim();
      }
      // Strip *any* leading @<digits> mention (LIDs we may not have captured)
      cleanBody = cleanBody.replace(/^@\d{8,}\s*/, "").trim();
    } catch (e) {}

    for (const trigger of TRIGGER_WORDS) {
      const lower = cleanBody.toLowerCase();
      if (lower.startsWith(trigger)) {
        cleanBody = cleanBody.slice(trigger.length).trim();
        cleanBody = cleanBody.replace(/^[:,\-]+\s*/, "");
        break;
      }
    }

    console.log(
      `[ETAA Bridge] ${isGroup ? "GROUP→bot" : "DM"} from ${senderName} ` +
      `(${senderPhone}): ${cleanBody.slice(0, 60)}`
    );

    await axios.post(
      DJANGO_URL,
      {
        message_id:   messageId,
        sender_phone: senderPhone,
        sender_name:  senderName,
        group_jid:    groupJid,
        is_group:     isGroup,
        body:         cleanBody,
        media_url:    "",
        quoted_phone: quotedPhone,
        quoted_name:  quotedName,
      },
      { headers: { "Content-Type": "application/json" }, timeout: 90000 }
    );
  } catch (err) {
    console.error("[ETAA Bridge] Error forwarding message:", err.message);
  }
});

waClient.initialize();

// ── Express REST API ─────────────────────────────────────────────────────
const app  = express();
const os = require("os");
const upload = multer({ dest: os.tmpdir() });
app.use(express.json());

function requireToken(req, res, next) {
  const auth = req.headers["authorization"] || "";
  const expected = `Bearer ${API_TOKEN}`;
  if (auth !== expected) {
    const recv = auth.startsWith("Bearer ") ? auth.slice(7) : auth;
    console.error(
      `[ETAA Bridge] 401 unauthorized | expected=${tokenFingerprint(API_TOKEN)} | ` +
      `received=${tokenFingerprint(recv)}`
    );
    return res.status(401).json({ error: "Unauthorised" });
  }
  next();
}

app.post("/api/send/text", requireToken, async (req, res) => {
  const { jid, text } = req.body;
  if (!jid || !text) return res.status(400).json({ error: "jid and text required" });
  try {
    await waClient.sendMessage(jid, text);
    res.json({ ok: true });
  } catch (err) {
    console.error("[ETAA Bridge] send/text error:", err.message);
    res.status(500).json({ error: err.message });
  }
});

app.post("/api/send/image", requireToken, upload.single("file"), async (req, res) => {
  const { jid, caption } = req.body;
  if (!jid || !req.file) return res.status(400).json({ error: "jid and file required" });
  try {
    const media = MessageMedia.fromFilePath(req.file.path);
    await waClient.sendMessage(jid, media, { caption: caption || "" });
    fs.unlinkSync(req.file.path);
    res.json({ ok: true });
  } catch (err) {
    console.error("[ETAA Bridge] send/image error:", err.message);
    res.status(500).json({ error: err.message });
  }
});

app.post("/api/send/file", requireToken, upload.single("file"), async (req, res) => {
  const { jid, caption } = req.body;
  if (!jid || !req.file) return res.status(400).json({ error: "jid and file required" });
  try {
    const media = MessageMedia.fromFilePath(req.file.path);
    await waClient.sendMessage(jid, media, { caption: caption || "", sendMediaAsDocument: true });
    fs.unlinkSync(req.file.path);
    res.json({ ok: true });
  } catch (err) {
    console.error("[ETAA Bridge] send/file error:", err.message);
    res.status(500).json({ error: err.message });
  }
});

app.get("/health", (req, res) => res.json({ status: "ok" }));

const httpServer = app.listen(PORT, () => {
  console.log(`[ETAA Bridge] HTTP server listening on port ${PORT}`);
});

// ── Graceful shutdown ─────────────────────────────────────────────────────
// Without this, Ctrl+C kills the Node process but leaves the puppeteer
// Chrome child running, which holds onto port 3000 and prevents the
// next start. We listen for SIGINT/SIGTERM, close the HTTP server,
// destroy the WhatsApp client (which closes Chrome), then exit.
let isShuttingDown = false;

async function gracefulShutdown(signal) {
  if (isShuttingDown) return;
  isShuttingDown = true;
  console.log(`\n[ETAA Bridge] ${signal} received – shutting down…`);

  // Stop accepting new HTTP requests.
  try { httpServer.close(); } catch (e) {}

  // Tell whatsapp-web.js to close its Chrome process.
  try {
    await waClient.destroy();
    console.log("[ETAA Bridge] WhatsApp client destroyed.");
  } catch (e) {
    console.warn("[ETAA Bridge] Error destroying WA client:", e.message);
  }

  // Force-exit if anything is still hanging after 5s.
  setTimeout(() => {
    console.warn("[ETAA Bridge] Forced exit after timeout.");
    process.exit(0);
  }, 5000).unref();

  process.exit(0);
}

process.on("SIGINT",  () => gracefulShutdown("SIGINT"));
process.on("SIGTERM", () => gracefulShutdown("SIGTERM"));

// Windows-specific: Ctrl+C arrives differently in some shells; this
// covers PowerShell and cmd.exe.
if (process.platform === "win32") {
  const readline = require("readline");
  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
  rl.on("SIGINT", () => process.emit("SIGINT"));
}