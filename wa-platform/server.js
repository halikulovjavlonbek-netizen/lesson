require('dotenv').config();
const express = require('express');
const path = require('path');
const QRCode = require('qrcode');
const { Client, LocalAuth } = require('whatsapp-web.js');

const app = express();
app.use(express.json());
app.use(express.urlencoded({ extended: true }));
app.use(express.static(path.join(__dirname, 'public')));

// CORS рухсатномаси (Django ёки бошқа доменлардан сўровлар бемалол ишлаши учун)
app.use((req, res, next) => {
  res.header('Access-Control-Allow-Origin', '*');
  res.header('Access-Control-Allow-Headers', 'Origin, X-Requested-With, Content-Type, Accept, x-api-key');
  res.header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  if (req.method === 'OPTIONS') return res.sendStatus(200);
  next();
});

const API_KEY = process.env.API_KEY;
const WEBHOOK_URL = process.env.WEBHOOK_URL;
const PORT = process.env.PORT || 3000;

// ---------- Қозоғистон ёрдамчи функциялари ----------

/**
 * Қозоғистон рақамларини ягона форматга (E.164: 77XXXXXXXXX) келтириш.
 * Қабул қилинади:
 * - 8 701 234 56 78 -> 77012345678
 * - +7 (701) 234-56-78 -> 77012345678
 * - 7012345678 -> 77012345678
 * - 77012345678 -> 77012345678
 */
function normalizeKZ(input) {
  let d = String(input || '').replace(/\D/g, '');
  if (d.length === 11 && d.startsWith('8')) {
    d = '7' + d.slice(1);
  } else if (d.length === 10) {
    d = '7' + d;
  }
  
  // Қозоғистон рақамлари: 11 хонали ва 77, 70, 74, 76 билан бошланиши (масалан: 7701, 7708, 7777...)
  if (d.length === 11 && (d.startsWith('77') || d.startsWith('70') || d.startsWith('74') || d.startsWith('76'))) {
    return d;
  }
  // Умумий халқаро рақамлар (10 дан 15 рақамгача)
  if (d.length >= 10 && d.length <= 15) {
    return d;
  }
  return null;
}

/**
 * Валюта: Қозоғистон теңгеси (KZT, ₸). Мисол: 15 000 ₸
 */
function formatKZT(amount) {
  const num = Number(amount) || 0;
  return new Intl.NumberFormat('ru-KZ', {
    style: 'currency',
    currency: 'KZT',
    maximumFractionDigits: 0,
  }).format(num);
}

/**
 * Олмаота (Asia/Almaty) вақт зонаси бўйича ҳозирги вақт
 */
function almatyTime(date = new Date()) {
  return date.toLocaleString('ru-RU', { timeZone: 'Asia/Almaty' });
}

// ---------- Хавфсизлик (Аутентификация) ----------
function auth(req, res, next) {
  if (!API_KEY) return next();
  const incomingKey = req.headers['x-api-key'] || req.query.api_key;
  if (incomingKey === API_KEY) return next();
  return res.status(401).json({ ok: false, error: 'Unauthorized: API калит нотўғри ёки кўрсатилмаган' });
}

const fs = require('fs');

function getBrowserExecutablePath() {
  // Windows: .env faylida backslash (\ ) to'g'ri o'qilishi uchun
  const rawPath = process.env.CHROME_PATH || process.env.PUPPETEER_EXECUTABLE_PATH;
  const customPath = rawPath ? rawPath.replace(/\\\\/g, '\\') : null;
  if (customPath && fs.existsSync(customPath)) return customPath;

  const candidates = [
    'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
    (process.env.LOCALAPPDATA || '') + '\\Google\\Chrome\\Application\\chrome.exe',
    'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
    'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
    '/usr/bin/google-chrome-stable',
    '/usr/bin/google-chrome',
    '/usr/bin/chromium-browser',
    '/usr/bin/chromium',
  ];
  for (const p of candidates) {
    if (p && fs.existsSync(p)) return p;
  }
  return undefined;
}

let qrImage = null;
let qrTimestamp = Date.now();
let qrCounter = 0;
let status = 'starting'; // starting | waiting_qr | authenticated | connected | disconnected | reconnecting
let clientInfo = null;
let isRestarting = false;

// ---------- WhatsApp клиент созламаси ----------
function createClient() {
  const browserPath = getBrowserExecutablePath();
  if (browserPath) {
    console.log(`[Браузер] Ишлатилаётган браузер: ${browserPath}`);
  }

  const c = new Client({
    authStrategy: new LocalAuth({
      dataPath: path.join(__dirname, '.wwebjs_auth')
    }),
    puppeteer: {
      headless: true,
      executablePath: browserPath,
      args: [
        '--no-sandbox',
        '--disable-setuid-sandbox',
        '--disable-dev-shm-usage',
        '--disable-accelerated-2d-canvas',
        '--no-first-run',
        '--no-zygote',
        '--disable-gpu'
      ],
    },
  });

  c.on('qr', async (qr) => {
    try {
      qrImage = await QRCode.toDataURL(qr);
      qrTimestamp = Date.now();
      qrCounter++;
      status = 'waiting_qr';
      console.log(`[${almatyTime()}] QR-код #${qrCounter} янгиланди. Телефон орқали сканерланг.`);
    } catch (e) {
      console.error('QR тайёрлашда хато:', e.message);
    }
  });

  c.on('authenticated', () => {
    status = 'authenticated';
    console.log(`[${almatyTime()}] WhatsApp муваффақиятли авторизациядан ўтди.`);
  });

  c.on('auth_failure', (msg) => {
    status = 'disconnected';
    qrImage = null;
    console.error(`[${almatyTime()}] WhatsApp авторизация хатоси:`, msg);
    restartClient(3000);
  });

  c.on('ready', () => {
    status = 'connected';
    qrImage = null;
    clientInfo = c.info ? {
      pushname: c.info.pushname,
      wid: c.info.wid ? c.info.wid.user : null
    } : null;
    console.log(`[${almatyTime()}] ✅ WhatsApp муваффақиятли уланди! Рақам: ${clientInfo?.wid || 'номаълум'}`);
  });

  c.on('disconnected', (reason) => {
    status = 'disconnected';
    qrImage = null;
    clientInfo = null;
    console.log(`[${almatyTime()}] WhatsApp уланмаси узилди:`, reason);
    restartClient(5000);
  });

  // Келган хабарлар -> платформа webhook манзилига юборилади
  c.on('message', async (msg) => {
    try {
      let fromId = msg.from || '';
      let displayPhone = fromId;
      let realPhone = null;

      // Ҳақиқий телефон рақамини аниқлаш
      if (fromId.endsWith('@lid')) {
        const resolved = await resolvePhoneNumber(c, fromId);
        if (resolved && resolved.phone) {
          realPhone = '+' + resolved.phone;
          displayPhone = realPhone;
          console.log(`[Ҳақиқий Рақам] @lid (${fromId}) -> ${realPhone}`);
        } else {
          displayPhone = fromId;
        }
      } else if (fromId.endsWith('@c.us')) {
        displayPhone = '+' + fromId.replace('@c.us', '');
      }

      // Юборувчи исмини олиш
      let contactName = '';
      try {
        const contact = await msg.getContact();
        contactName = contact?.pushname || contact?.name || '';
      } catch (e) {}

      const cleanFrom = displayPhone.replace('@c.us', '');
      const payload = {
        from: cleanFrom.startsWith('+') ? cleanPhoneFix(cleanFrom) : '+' + cleanPhoneFix(cleanFrom),
        text: msg.body,
        name: contactName,
        lid: fromId.endsWith('@lid') ? fromId : null,
        time: almatyTime(),
        timestamp: msg.timestamp,
      };
      console.log(`[${almatyTime()}] Келган хабар:`, payload.from, contactName ? `(${contactName})` : '', '->', payload.text);
      if (WEBHOOK_URL) {
        await fetch(WEBHOOK_URL, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        }).catch((err) => console.error('Webhook сўрови хатоси:', err.message));
      }
    } catch (e) {
      console.error('Webhook хатолиги:', e.message);
    }
  });

  return c;
}

let client = createClient();

async function restartClient(delay = 3000) {
  if (isRestarting) return;
  isRestarting = true;
  status = 'reconnecting';
  qrImage = null;
  console.log(`WhatsApp қайта ишга туширилмоқда (${delay / 1000} сония кутилмоқда)...`);
  
  setTimeout(async () => {
    try {
      await client.destroy().catch(() => {});
      client = createClient();
      await client.initialize();
    } catch (err) {
      console.error('Қайта уланишда хато:', err.message);
    } finally {
      isRestarting = false;
    }
  }, delay);
}

// Биринчи марта ишга тушириш
client.initialize().catch((err) => {
  console.error('Ишга туширишда хато:', err.message);
});

function cleanPhoneFix(str) {
  return String(str || '').replace(/^\++/, '');
}

/**
 * WhatsApp контакт ёки LID дан ҳақиқий телефон рақамини топиш
 */
async function resolvePhoneNumber(cInstance, idOrLid) {
  if (!cInstance || !cInstance.pupPage) return null;
  try {
    const raw = String(idOrLid || '').trim().replace(/^\+/, '');
    const cleanId = raw.includes('@') ? raw : (raw.length >= 14 ? `${raw}@lid` : `${raw}@c.us`);

    const result = await cInstance.pupPage.evaluate(async (userId) => {
      try {
        const wid = window.require('WAWebWidFactory').createWid(userId);
        if (wid.server === 'c.us') {
          return { phone: wid.user, formatted: '+' + wid.user, lid: null };
        }

        // 1. WAWebLidMigrationUtils.toPn
        try {
          const { toPn } = window.require('WAWebLidMigrationUtils') || {};
          if (typeof toPn === 'function') {
            const pn = toPn(wid);
            if (pn && pn.user) {
              return { phone: pn.user, formatted: '+' + pn.user, lid: wid.user };
            }
          }
        } catch (e) {}

        // 2. WWebJS.enforceLidAndPnRetrieval
        try {
          if (window.WWebJS && typeof window.WWebJS.enforceLidAndPnRetrieval === 'function') {
            const r = await window.WWebJS.enforceLidAndPnRetrieval(userId);
            if (r && r.phone && r.phone.user) {
              return { phone: r.phone.user, formatted: '+' + r.phone.user, lid: wid.user };
            }
          }
        } catch (e) {}

        // 3. WAWebApiContact.getPhoneNumber
        try {
          const apiContact = window.require('WAWebApiContact');
          if (apiContact && typeof apiContact.getPhoneNumber === 'function') {
            const pn = apiContact.getPhoneNumber(wid);
            if (pn && pn.user) {
              return { phone: pn.user, formatted: '+' + pn.user, lid: wid.user };
            }
          }
        } catch (e) {}

        // 4. Contact Collection
        try {
          const c = window.require('WAWebCollections').Contact.get(wid);
          if (c && c.phoneNumber && c.phoneNumber.user) {
            return { phone: c.phoneNumber.user, formatted: '+' + c.phoneNumber.user, lid: wid.user };
          }
        } catch (e) {}

        return { phone: null, formatted: null, lid: wid.user };
      } catch (err) {
        return { error: err.message, lid: userId };
      }
    }, cleanId);

    return result;
  } catch (e) {
    return null;
  }
}

// ---------- Хабар навбати ва LID хатосини ҳал қилиш ----------
let queue = Promise.resolve();

async function sendWithLidHandling(targetId, text) {
  let idToSend = String(targetId || '').trim();

  // Агар targetId 14+ хонали бўлиб @c.us бўлса (масалан: 265764154171404@c.us) — бу аслида @lid!
  const userPart = idToSend.replace(/@.*$/, '').replace(/^\+/, '');
  const isLidNumber = userPart.length >= 14;

  if (isLidNumber && idToSend.endsWith('@c.us')) {
    idToSend = `${userPart}@lid`;
    console.log(`[LID Тўғрилаш] ${targetId} аслида LID эканлиги аниқланди -> ${idToSend}`);
  }

  // 1-уриниш: берилган ID бўйича юбориш
  try {
    return await client.sendMessage(idToSend, text);
  } catch (err) {
    console.warn(`[Юбориш хатоси] ${idToSend} га юборишда хато: "${err.message}". Муқобиллар синалмоқда...`);

    // 2-уриниш: Агар @lid бўлса ёки 14+ хонали бўлса, ҳақиқий телефон рақамини (toPn) топиб ўшанга юбориш
    if (idToSend.endsWith('@lid') || isLidNumber) {
      try {
        const resolved = await resolvePhoneNumber(client, idToSend);
        if (resolved && resolved.phone) {
          const pnId = `${resolved.phone}@c.us`;
          console.log(`[LID Тўғрилаш] ${idToSend} -> ҳақиқий телефон рақамига юборилмоқда: ${pnId}`);
          return await client.sendMessage(pnId, text);
        }
      } catch (e) {}
    }

    // 3-уриниш: Агар @c.us бўлиб хато берса -> @lid сифатида уриниб кўриш
    if (idToSend.endsWith('@c.us')) {
      const lidId = `${userPart}@lid`;
      try {
        console.log(`[LID Тўғрилаш] ${idToSend} -> @lid сифатида юборилмоқда: ${lidId}`);
        return await client.sendMessage(lidId, text);
      } catch (e) {}
    }

    // 4-уриниш: Браузерда чатни мажбурий топиш ва юклаш
    try {
      if (client.pupPage) {
        await client.pupPage.evaluate(async (id) => {
          try {
            const wid = window.require('WAWebWidFactory').createWid(id);
            await window.require('WAWebFindChatAction').findOrCreateLatestChat(wid);
          } catch (e) {}
        }, idToSend);
        return await client.sendMessage(idToSend, text);
      }
    } catch (e) {}

    throw err;
  }
}

function sendQueued(chatId, text) {
  const job = queue.then(async () => {
    await sendWithLidHandling(chatId, text);
    const pause = 1500 + Math.random() * 1500; // 1.5 - 3 сония кутиш
    await new Promise((r) => setTimeout(r, pause));
  });
  queue = job.catch(() => {});
  return job;
}

// ---------- API ЭНДПОИНТЛАРИ ----------

// Sog'liqni tekshirish (autentifikatsiyasiz - Django tomonidan ishlatiladi)
app.get('/health', (req, res) => {
  res.json({ ok: true, service: 'wa-platform', port: PORT, time: almatyTime() });
});

// Ҳолатни олиш
app.get('/whatsapp/status', auth, (req, res) => {
  const expiresIn = Math.max(0, 30 - Math.floor((Date.now() - qrTimestamp) / 1000));
  res.json({
    ok: true,
    status,
    has_qr: Boolean(qrImage),
    info: clientInfo,
    qrCounter,
    qrTimestamp,
    expiresIn,
    time: almatyTime()
  });
});

// QR-код суратини олиш
app.get('/whatsapp/qr', auth, (req, res) => {
  const expiresIn = Math.max(0, 30 - Math.floor((Date.now() - qrTimestamp) / 1000));
  res.json({
    ok: true,
    qr: qrImage,
    status,
    qrCounter,
    qrTimestamp,
    expiresIn
  });
});

// QR-кодни қайта янгилаш (ҳар 30 сонияда ёки қўлда талаб қилинганда)
async function triggerQrRefresh() {
  if (status === 'connected') return false;
  if (client && client.pupPage) {
    try {
      const clicked = await client.pupPage.evaluate(() => {
        const reloadSelectors = [
          'span[data-icon="refresh"]',
          'button[type="button"]',
          'div[role="button"]',
          'div[data-testid="qrcode"]'
        ];
        for (const s of reloadSelectors) {
          const el = document.querySelector(s);
          if (el) { el.click(); return true; }
        }
        return false;
      }).catch(() => false);

      if (!clicked) {
        await client.pupPage.reload({ waitUntil: 'networkidle0' }).catch(() => {});
      }
      return true;
    } catch (e) {
      restartClient(1000);
      return true;
    }
  } else {
    restartClient(1000);
    return true;
  }
}

app.all('/whatsapp/qr/refresh', auth, async (req, res) => {
  try {
    await triggerQrRefresh();
    res.json({ ok: true, message: 'QR янгилаш буйруғи юборилди' });
  } catch (err) {
    res.status(500).json({ ok: false, error: err.message });
  }
});

// Ҳар 30 сонияда QR-код янгиланиб туришини таъминлаш
setInterval(async () => {
  if (status === 'waiting_qr') {
    const elapsed = Date.now() - qrTimestamp;
    if (elapsed >= 30000) {
      console.log(`[${almatyTime()}] 30 сония ўтди: QR-код янгиланмоқда...`);
      await triggerQrRefresh().catch(() => {});
    }
  }
}, 5000);


/**
 * Хабар юбориш API
 * POST /whatsapp/send
 * Headers: { "x-api-key": "..." }
 * Body: {
 *   "phone": "8 701 234 56 78",
 *   "message": "Салем! Сизнинг буюртмангиз тайёр.",
 *   "amount": 15000
 * }
 */
app.post('/whatsapp/send', auth, async (req, res) => {
  try {
    if (status !== 'connected') {
      return res.status(503).json({
        ok: false,
        error: `WhatsApp серверга ҳали тўлиқ уланмаган (Ҳозирги ҳолат: ${status}). QR-кодни сканерланг.`
      });
    }

    const rawInput = String(req.body.phone || '').trim();
    if (!rawInput) {
      return res.status(400).json({ ok: false, error: 'Телефон рақами бўш бўлиши мумкин эмас' });
    }

    const digitsOnly = rawInput.replace(/\D/g, '');
    let targetChatId = null;
    let displayPhone = rawInput;

    // Агар кирувчи рақамда @lid бўлса
    if (rawInput.includes('@lid')) {
      const clean = rawInput.replace(/^\+/, '');
      targetChatId = clean.endsWith('@lid') ? clean : `${clean}@lid`;
      displayPhone = targetChatId;
    } else if (rawInput.includes('@c.us')) {
      const clean = rawInput.replace(/^\+/, '');
      targetChatId = clean.endsWith('@c.us') ? clean : `${clean}@c.us`;
      displayPhone = targetChatId;
    } else if (digitsOnly.length >= 14) {
      // 14-16 хонали бўлса — бу WhatsApp LID! Ҳеч қачон @c.us қилмаймиз!
      targetChatId = `${digitsOnly}@lid`;
      displayPhone = targetChatId;
    } else {
      const phone = normalizeKZ(rawInput);
      if (!phone) {
        return res.status(400).json({
          ok: false,
          error: 'Қозоғистон телефон рақами нотўғри! Тўғри мисол: +7 701 234 56 78 ёки 87012345678'
        });
      }
      targetChatId = `${phone}@c.us`;
      displayPhone = '+' + phone;

      // WhatsApp фойдаланувчиси мавжудлигини текшириш
      try {
        const numberId = await client.getNumberId(targetChatId);
        if (numberId && numberId._serialized) {
          targetChatId = numberId._serialized;
        }
      } catch (e) {}
    }

    let text = (req.body.message || '').trim();
    if (req.body.amount !== undefined && req.body.amount !== null && req.body.amount !== '') {
      text += (text ? '\n\n' : '') + `Сумма: ${formatKZT(req.body.amount)}`;
    }

    if (!text) {
      return res.status(400).json({ ok: false, error: 'Хабар матни бўш бўлиши мумкин эмас' });
    }

    await sendQueued(targetChatId, text);

    res.json({
      ok: true,
      message: 'Хабар муваффақиятли юборилди',
      phone: displayPhone,
      chatId: targetChatId,
      time: almatyTime()
    });
  } catch (e) {
    console.error('Хабар юбориш хатоси:', e);
    res.status(500).json({ ok: false, error: e.message || 'Сервер хатолиги' });
  }
});

// Контактнинг ҳақиқий телефон рақамини аниқлаш (Django учун)
app.post('/whatsapp/resolve-contact', auth, async (req, res) => {
  try {
    const { id } = req.body;
    const result = await resolvePhoneNumber(client, id);
    res.json({ ok: true, result });
  } catch (e) {
    res.status(500).json({ ok: false, error: e.message });
  }
});

// Сессияни узиш (Logout)
app.post('/whatsapp/logout', auth, async (req, res) => {
  try {
    if (client) {
      await client.logout().catch(() => {});
    }
    status = 'disconnected';
    qrImage = null;
    clientInfo = null;
    restartClient(2000);
    res.json({ ok: true, message: 'WhatsApp сессияси муваффақиятли узилди. Қайта QR-код кутилмоқда.' });
  } catch (e) {
    res.status(500).json({ ok: false, error: e.message });
  }
});

// Серверни тинглаш
app.listen(PORT, () => {
  console.log(`[WhatsApp Сервис] Ишга тушди: http://localhost:${PORT}`);
  console.log(`[Вақт зонаси] Олмаота: ${almatyTime()}`);
});
