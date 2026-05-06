# Telegram-бот на Claude

Головний файл — agent_bot.py. Залежності — requirements.txt.

## Сервер
Бот працює на VPS DigitalOcean.
- Шлях: /root/-
- Сервіс: mybot.service (systemd) → запускає agent_bot.py
- Автодеплой: /root/autodeploy.sh щохвилини робить git pull і перезапускає сервіс при змінах.

## Git Relay
Claude може виконувати команди на сервері через GitHub без прямого доступу до термінала.

- cmd_runner.py — раз на 5 сек читає cmds/pending.json через GitHub API
- Якщо є нова команда (новий id) — виконує shell-команду, пише результат у cmds/result.json
- Сервіс: cmdrunner.service (systemd)

**Формат запиту** (cmds/pending.json):
```json
{"id": "унікальний-id", "cmd": "команда"}
```

**Формат відповіді** (cmds/result.json):
```json
{"id": "...", "cmd": "...", "stdout": "...", "stderr": "...", "returncode": 0, "ts": "..."}
```

## Workflow
Усе через GitHub: коміт у main → за хвилину сервер оновиться.
До Browser terminal більше не повертаємося.

## Користувач
Говорить українською, не програміст — пояснювати простими словами.
