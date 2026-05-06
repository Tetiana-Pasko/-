#!/bin/bash
set -e

# Tokens passed as environment variables
: "${TG_TOKEN:?Need TG_TOKEN}"
: "${ANTHROPIC_KEY:?Need ANTHROPIC_KEY}"
: "${GH_USER:?Need GH_USER}"
: "${GH_TOKEN:?Need GH_TOKEN}"
: "${REPO_NAME:?Need REPO_NAME}"

echo "=== 1. Оновлення системи ==="
apt-get update -q && DEBIAN_FRONTEND=noninteractive apt-get upgrade -y -q

echo "=== 2. Пакети ==="
apt-get install -y git python3 python3-pip python3-venv

echo "=== 3. Клонування репо ==="
cd /root
rm -rf "${REPO_NAME}"
git clone "https://${GH_TOKEN}@github.com/${GH_USER}/${REPO_NAME}.git"
cd "/root/${REPO_NAME}"
git config user.name "auto-deploy"
git config user.email "deploy@server"

cat > bot.py <<'PYEOF'
import os, logging
for v in ("HTTP_PROXY","HTTPS_PROXY","http_proxy","https_proxy","ALL_PROXY","all_proxy"):
    os.environ.pop(v, None)
from dotenv import load_dotenv
import anthropic
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
log = logging.getLogger(__name__)

claude = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
history: dict[int, list[dict]] = {}

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привіт! Я бот на Claude. Питай будь-що.")

async def reset(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    history.pop(update.effective_user.id, None)
    await update.message.reply_text("Історію очищено.")

async def chat(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    history.setdefault(uid, []).append({"role": "user", "content": update.message.text})
    await ctx.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    try:
        resp = claude.messages.create(
            model="claude-opus-4-7", max_tokens=1024,
            system="Ти доброзичливий асистент. Відповідай коротко та по суті українською.",
            messages=history[uid],
        )
        text = resp.content[0].text
        history[uid].append({"role": "assistant", "content": text})
        history[uid] = history[uid][-20:]
        await update.message.reply_text(text)
    except Exception:
        log.exception("error")
        await update.message.reply_text("Помилка. Спробуй ще раз.")

def main():
    app = ApplicationBuilder().token(os.environ["TELEGRAM_BOT_TOKEN"]).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat))
    log.info("Bot started")
    app.run_polling()

if __name__ == "__main__":
    main()
PYEOF

cat > requirements.txt <<'EOF'
anthropic>=0.40.0
python-telegram-bot>=21.0
python-dotenv>=1.0.0
EOF

cat > .gitignore <<'EOF'
.env
venv/
__pycache__/
*.pyc
EOF

cat > .env <<EOF
TELEGRAM_BOT_TOKEN=${TG_TOKEN}
ANTHROPIC_API_KEY=${ANTHROPIC_KEY}
GITHUB_TOKEN=${GH_TOKEN}
GH_USER=${GH_USER}
GH_REPO=${REPO_NAME}
EOF

cat > CLAUDE.md <<'EOF'
# Telegram-бот на Claude

Головний файл — bot.py. Залежності — requirements.txt.

## Сервер
Бот працює на VPS DigitalOcean.
- Шлях: /root/my-bot
- Сервіс: mybot.service (systemd)
- Автодеплой: /root/autodeploy.sh щохвилини робить git pull і перезапускає сервіс.

## Git Relay
- cmd_runner.py — читає cmds/pending.json з GitHub кожні 5 сек
- Виконує команду, пише результат у cmds/result.json
- Сервіс: cmdrunner.service

## Workflow
Усе через GitHub: коміт у main → за хвилину сервер оновиться.
Єдиний виняток: перші команди через Browser terminal (один раз).

## Користувач
Говорить українською, не програміст — пояснювати простими словами.
EOF

cat > cmd_runner.py <<'PYEOF'
import os, json, time, subprocess, base64, urllib.request
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

GH_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GH_USER = os.environ.get("GH_USER", "")
REPO = os.environ.get("GH_REPO", "")
PENDING_PATH = "cmds/pending.json"
RESULT_PATH = "cmds/result.json"
POLL_INTERVAL = 5

def gh_get(path):
    url = f"https://api.github.com/repos/{GH_USER}/{REPO}/contents/{path}"
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"token {GH_TOKEN}")
    req.add_header("Accept", "application/vnd.github.v3+json")
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())

def gh_put(path, content, sha, message):
    url = f"https://api.github.com/repos/{GH_USER}/{REPO}/contents/{path}"
    encoded = base64.b64encode(json.dumps(content, ensure_ascii=False).encode()).decode()
    data = json.dumps({"message": message, "content": encoded, "sha": sha}).encode()
    req = urllib.request.Request(url, data=data, method="PUT")
    req.add_header("Authorization", f"token {GH_TOKEN}")
    req.add_header("Accept", "application/vnd.github.v3+json")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())

def get_file(path):
    result = gh_get(path)
    content = base64.b64decode(result["content"]).decode()
    return json.loads(content), result["sha"]

def main():
    last_id = None
    print("cmd_runner started", flush=True)
    while True:
        try:
            pending, _ = get_file(PENDING_PATH)
            cmd_id = pending.get("id")
            cmd = pending.get("cmd", "")
            if cmd_id and cmd_id != last_id:
                last_id = cmd_id
                print(f"Executing [{cmd_id}]: {cmd}", flush=True)
                try:
                    proc = subprocess.run(
                        cmd, shell=True, capture_output=True,
                        text=True, timeout=120
                    )
                    stdout = proc.stdout[-3000:] if proc.stdout else ""
                    stderr = proc.stderr[-1000:] if proc.stderr else ""
                    rc = proc.returncode
                except subprocess.TimeoutExpired:
                    stdout, stderr, rc = "", "timeout", -1
                _, sha = get_file(RESULT_PATH)
                result = {
                    "id": cmd_id,
                    "cmd": cmd,
                    "stdout": stdout,
                    "stderr": stderr,
                    "returncode": rc,
                    "ts": datetime.now(timezone.utc).isoformat()
                }
                gh_put(RESULT_PATH, result, sha, f"result: {cmd_id}")
                print(f"Done [{cmd_id}] rc={rc}", flush=True)
        except Exception as e:
            print(f"Error: {e}", flush=True)
        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    main()
PYEOF

mkdir -p cmds
printf '{"id":"init","cmd":"echo ready"}' > cmds/pending.json
printf '{}' > cmds/result.json

echo "=== Встановлення venv ==="
python3 -m venv venv
./venv/bin/pip install -q -r requirements.txt

echo "=== Коміт і пуш ==="
git add bot.py requirements.txt .gitignore CLAUDE.md cmd_runner.py cmds/
git commit -m "Initial bot + Git Relay setup"
git branch -M main
git push -u origin main

echo "=== systemd ==="
cat > /etc/systemd/system/mybot.service <<EOF
[Unit]
Description=Telegram Bot on Claude
After=network.target

[Service]
Type=simple
WorkingDirectory=/root/${REPO_NAME}
ExecStart=/root/${REPO_NAME}/venv/bin/python /root/${REPO_NAME}/bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

cat > /root/autodeploy.sh <<EOF
#!/bin/bash
cd /root/${REPO_NAME} || exit 1
BEFORE=\$(git rev-parse HEAD)
git pull --quiet
AFTER=\$(git rev-parse HEAD)
if [ "\$BEFORE" != "\$AFTER" ]; then
    /root/${REPO_NAME}/venv/bin/pip install -q -r requirements.txt
    systemctl restart mybot.service
fi
EOF
chmod +x /root/autodeploy.sh

cat > /etc/systemd/system/autodeploy.service <<'EOF'
[Unit]
Description=Auto deploy from GitHub
[Service]
Type=oneshot
ExecStart=/root/autodeploy.sh
EOF

cat > /etc/systemd/system/autodeploy.timer <<'EOF'
[Unit]
Description=Run autodeploy every minute
[Timer]
OnBootSec=1min
OnUnitActiveSec=1min
[Install]
WantedBy=timers.target
EOF

cat > /etc/systemd/system/cmdrunner.service <<EOF
[Unit]
Description=Git Relay cmd_runner
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/${REPO_NAME}
ExecStart=/root/${REPO_NAME}/venv/bin/python /root/${REPO_NAME}/cmd_runner.py
Restart=always
RestartSec=10
EnvironmentFile=-/root/${REPO_NAME}/.env

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now mybot.service
systemctl enable --now autodeploy.timer
systemctl enable --now cmdrunner.service

echo ""
echo "============================================="
echo "✅ ВСЕ ГОТОВО!"
echo "Відкрий Telegram, знайди бота, напиши /start"
echo "Бот + автодеплой + Git Relay — все активне"
echo "============================================="
