import makeWASocket, { 
    DisconnectReason, 
    useMultiFileAuthState,
    fetchLatestBaileysVersion,
    downloadMediaMessage,
    Browsers
} from '@whiskeysockets/baileys';
import qrcode from 'qrcode-terminal';
import pino from 'pino';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { spawn } from 'child_process';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const AUTH_FOLDER = path.join(__dirname, 'auth_info');
const CONFIG_FILE = path.join(__dirname, 'config.json');
const MEDIA_FOLDER = path.join(__dirname, '..', 'media', 'whatsapp');

if (!fs.existsSync(MEDIA_FOLDER)) {
    fs.mkdirSync(MEDIA_FOLDER, { recursive: true });
}

// Читаем конфиг
let config = { targetGroupJids: [] };
if (fs.existsSync(CONFIG_FILE)) {
    try {
        config = JSON.parse(fs.readFileSync(CONFIG_FILE, 'utf-8'));
    } catch (e) {
        console.error('Error reading config.json:', e);
    }
}

// Загружаем .env для Telegram оповещений
function loadEnv() {
    const envFile = path.join(__dirname, '..', '.env');
    const env = {};
    if (fs.existsSync(envFile)) {
        try {
            const content = fs.readFileSync(envFile, 'utf-8');
            for (const line of content.split('\n')) {
                const trimmed = line.trim();
                if (!trimmed || trimmed.startsWith('#') || !trimmed.includes('=')) continue;
                const idx = trimmed.indexOf('=');
                const key = trimmed.slice(0, idx).trim();
                let val = trimmed.slice(idx + 1).trim();
                if ((val.startsWith('"') && val.endsWith('"')) || (val.startsWith("'") && val.endsWith("'"))) {
                    val = val.slice(1, -1);
                }
                env[key] = val;
            }
        } catch (e) {
            console.error('[WA] Failed to read .env:', e);
        }
    }
    return env;
}

const envConfig = loadEnv();
const BOT_TOKEN = process.env.BOT_TOKEN || envConfig.BOT_TOKEN || '';
const ADMIN_IDS = (process.env.ADMIN_IDS || envConfig.ADMIN_IDS || '').split(',').map(x => x.trim()).filter(Boolean);

let isNotifying = false;
async function notifyAdmins(text) {
    if (isNotifying || !BOT_TOKEN || ADMIN_IDS.length === 0) return;
    isNotifying = true;
    for (const adminId of ADMIN_IDS) {
        try {
            await fetch(`https://api.telegram.org/bot${BOT_TOKEN}/sendMessage`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    chat_id: adminId,
                    text,
                    parse_mode: 'HTML'
                })
            });
        } catch (e) {
            console.error(`[WA Alert] Failed to send Telegram alert to ${adminId}:`, e.message);
        }
    }
    isNotifying = false;
}

// Слушатели критических ошибок процесса
process.on('uncaughtException', async (err) => {
    console.error('[WA Crash] Uncaught Exception:', err);
    try {
        await notifyAdmins(`🚨 <b>Toplivo WhatsApp Crash</b>\n\nНеобработанная ошибка (Uncaught Exception):\n<code>${(err.message || err).toString().slice(0, 500)}</code>`);
    } catch (_) {}
    process.exit(1);
});

process.on('unhandledRejection', async (reason) => {
    console.error('[WA Crash] Unhandled Rejection:', reason);
    try {
        const errorMsg = reason instanceof Error ? (reason.stack || reason.message) : String(reason);
        await notifyAdmins(`🚨 <b>Toplivo WhatsApp Crash</b>\n\nНеобработанный отказ промиса (Unhandled Rejection):\n<code>${errorMsg.slice(0, 500)}</code>`);
    } catch (_) {}
    process.exit(1);
});

async function connectToWhatsApp() {
    const { state, saveCreds } = await useMultiFileAuthState(AUTH_FOLDER);
    const { version, isLatest } = await fetchLatestBaileysVersion();

    console.log(`[WA] Using Baileys version: ${version.join('.')}, isLatest: ${isLatest}`);

    const sock = makeWASocket({
        version,
        logger: pino({ level: 'silent' }),
        auth: state,
        printQRInTerminal: false,
        browser: Browsers.ubuntu('Chrome')
    });

    sock.ev.on('connection.update', async (update) => {
        const { connection, lastDisconnect, qr } = update;

        if (qr) {
            console.log('\n================== SCAN QR CODE WITH WHATSAPP ==================');
            qrcode.generate(qr, { small: true });
            console.log('Open WhatsApp > Settings > Linked Devices > Link a Device');
            console.log('=================================================================\n');
        }

        if (connection === 'close') {
            const statusCode = lastDisconnect?.error?.output?.statusCode;
            const isLoggedOut = statusCode === DisconnectReason.loggedOut;
            const reasonMsg = lastDisconnect?.error?.message || `Status code: ${statusCode}`;
            const shouldReconnect = !isLoggedOut;

            console.log(`[WA] Connection closed. Reason: ${reasonMsg}. Reconnecting: ${shouldReconnect}`);

            if (shouldReconnect) {
                setTimeout(connectToWhatsApp, 5000);
            } else {
                console.log('[WA] Logged out. Alerting admins and stopping service to prevent restart loop.');
                await notifyAdmins(
                    `⚠️ <b>Toplivo WhatsApp Alert</b>\n\n` +
                    `Сессия WhatsApp завершена (<code>Logged Out</code>).\n` +
                    `Служба остановлена во избежание бесконечных перезапусков.\n\n` +
                    `<i>Для повторной привязки очистите папку <code>auth_info</code> и запустите спаривание по QR.</i>`
                );
                // Код выхода 42 сигнализирует systemd не перезапускать службу (RestartPreventExitStatus=42)
                process.exit(42);
            }
        } else if (connection === 'open') {
            console.log('[WA] Connected successfully!');
        }
    });

    sock.ev.on('creds.update', saveCreds);

    // Слушаем входящие сообщения
    sock.ev.on('messages.upsert', async ({ messages, type }) => {
        for (const msg of messages) {
            if (!msg.message) continue;
            
            const from = msg.key.remoteJid;
            const pushName = msg.pushName || 'Unknown';
            const sender = msg.key.participant || msg.key.remoteJid;

            // Проверяем фильтр по целевым группам (если задан)
            if (config.targetGroupJids && config.targetGroupJids.length > 0) {
                if (!config.targetGroupJids.includes(from)) {
                    continue;
                }
            }

            // Извлекаем текст сообщения
            const text = msg.message.conversation || 
                         msg.message.extendedTextMessage?.text || 
                         msg.message.imageMessage?.caption || 
                         '';

            let savedImagePath = null;

            // Проверяем наличие фото
            if (msg.message.imageMessage) {
                try {
                    const buffer = await downloadMediaMessage(
                        msg,
                        'buffer',
                        {},
                        { 
                            logger: pino({ level: 'silent' }),
                            reuploadRequest: sock.updateMediaMessage 
                        }
                    );
                    const filename = `wa_${Date.now()}_${Math.random().toString(36).substring(7)}.jpg`;
                    savedImagePath = path.join(MEDIA_FOLDER, filename);
                    fs.writeFileSync(savedImagePath, buffer);
                    console.log(`[WA] Photo downloaded: ${savedImagePath}`);
                } catch (err) {
                    console.error('[WA] Failed to download photo:', err);
                }
            }

            if (!text.trim() && !savedImagePath) continue;

            console.log(`\n[WA MSG] [From: ${from}] [User: ${pushName} (${sender})] [HasPhoto: ${Boolean(savedImagePath)}]:\n${text}`);

            // Передаем в Python обработчик
            handleMessageWithPython({
                jid: from,
                sender,
                pushName,
                text,
                imagePath: savedImagePath,
                timestamp: msg.messageTimestamp
            });
        }
    });
}

function handleMessageWithPython(payload) {
    const pythonScript = path.join(__dirname, '..', 'scripts', 'parse_whatsapp_message.py');
    const pythonBin = path.join(__dirname, '..', 'venv', 'bin', 'python');
    const execBin = fs.existsSync(pythonBin) ? pythonBin : 'python3';

    if (!fs.existsSync(pythonScript)) {
        return;
    }

    const child = spawn(execBin, [pythonScript], {
        stdio: ['pipe', 'inherit', 'inherit']
    });

    child.stdin.write(JSON.stringify(payload));
    child.stdin.end();
}

connectToWhatsApp();
