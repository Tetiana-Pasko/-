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
