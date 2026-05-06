import os, logging, json, math, base64
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
import httpx
from bs4 import BeautifulSoup
import anthropic
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
log = logging.getLogger(__name__)

claude = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
history: dict[int, list[dict]] = {}

NOTES_DIR = Path(__file__).parent / "notes"
NOTES_DIR.mkdir(exist_ok=True)

SYSTEM_PROMPT = (
    "Ти досвідчений бізнес-асистент. Відповідай завжди українською мовою. "
    "Допомагаєш з аналізом, плануванням, математикою, нотатками та пошуком інформації. "
    "Будь конкретним і лаконічним. Використовуй інструменти коли потрібно."
)

TOOLS = [
    {
        "name": "calculate",
        "description": "Виконує математичні розрахунки. Підтримує вирази Python та функції math.",
        "input_schema": {
            "type": "object",
            "properties": {
                "expression": {"type": "string", "description": "Математичний вираз"}
            },
            "required": ["expression"]
        }
    },
    {
        "name": "save_note",
        "description": "Зберігає нотатку для користувача",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Заголовок нотатки"},
                "content": {"type": "string", "description": "Зміст нотатки"}
            },
            "required": ["title", "content"]
        }
    },
    {
        "name": "list_notes",
        "description": "Показує список всіх нотаток користувача",
        "input_schema": {"type": "object", "properties": {}}
    },
    {
        "name": "delete_note",
        "description": "Видаляє нотатку за заголовком",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Заголовок нотатки"}
            },
            "required": ["title"]
        }
    },
    {
        "name": "get_datetime",
        "description": "Повертає поточну дату та час українською мовою",
        "input_schema": {"type": "object", "properties": {}}
    },
    {
        "name": "read_url",
        "description": "Читає текстовий вміст веб-сторінки за URL",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL сторінки"}
            },
            "required": ["url"]
        }
    }
]


def _notes_file(user_id: int) -> Path:
    return NOTES_DIR / f"{user_id}.json"

def _load_notes(user_id: int) -> dict:
    f = _notes_file(user_id)
    return json.loads(f.read_text()) if f.exists() else {}

def _save_notes(user_id: int, notes: dict):
    _notes_file(user_id).write_text(json.dumps(notes, ensure_ascii=False, indent=2))


def tool_calculate(expression: str) -> str:
    try:
        safe_globals = {k: v for k, v in math.__dict__.items() if not k.startswith("_")}
        safe_globals.update({"abs": abs, "round": round, "int": int, "float": float, "sum": sum})
        result = eval(expression, {"__builtins__": {}}, safe_globals)
        return f"Результат: {result}"
    except Exception as e:
        return f"Помилка обчислення: {e}"

def tool_save_note(user_id: int, title: str, content: str) -> str:
    notes = _load_notes(user_id)
    notes[title] = {"content": content, "created": datetime.now().strftime("%d.%m.%Y %H:%M")}
    _save_notes(user_id, notes)
    return f"Нотатку «{title}» збережено."

def tool_list_notes(user_id: int) -> str:
    notes = _load_notes(user_id)
    if not notes:
        return "У тебе поки немає нотаток."
    lines = [f"• {title} ({v['created']})" for title, v in notes.items()]
    return "Твої нотатки:\n" + "\n".join(lines)

def tool_delete_note(user_id: int, title: str) -> str:
    notes = _load_notes(user_id)
    if title not in notes:
        return f"Нотатку «{title}» не знайдено."
    del notes[title]
    _save_notes(user_id, notes)
    return f"Нотатку «{title}» видалено."

def tool_get_datetime() -> str:
    MONTHS = ["січня","лютого","березня","квітня","травня","червня",
              "липня","серпня","вересня","жовтня","листопада","грудня"]
    DAYS = ["понеділок","вівторок","середа","четвер","п'ятниця","субота","неділя"]
    now = datetime.now()
    return f"{DAYS[now.weekday()]}, {now.day} {MONTHS[now.month-1]} {now.year} р., {now.strftime('%H:%M')}"

def tool_read_url(url: str) -> str:
    try:
        resp = httpx.get(url, timeout=15, follow_redirects=True,
                         headers={"User-Agent": "Mozilla/5.0 (compatible; bot/1.0)"})
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        return text[:3500] + ("…" if len(text) > 3500 else "")
    except Exception as e:
        return f"Помилка читання URL: {e}"

def execute_tool(name: str, inputs: dict, user_id: int) -> str:
    if name == "calculate":
        return tool_calculate(inputs["expression"])
    if name == "save_note":
        return tool_save_note(user_id, inputs["title"], inputs["content"])
    if name == "list_notes":
        return tool_list_notes(user_id)
    if name == "delete_note":
        return tool_delete_note(user_id, inputs["title"])
    if name == "get_datetime":
        return tool_get_datetime()
    if name == "read_url":
        return tool_read_url(inputs["url"])
    return "Невідомий інструмент."


async def run_agent(user_id: int, messages: list) -> str:
    for _ in range(10):
        resp = claude.messages.create(
            model="claude-opus-4-7",
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )

        if resp.stop_reason == "end_turn":
            for block in resp.content:
                if hasattr(block, "text"):
                    return block.text
            return "Немає відповіді."

        if resp.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": resp.content})
            tool_results = []
            for block in resp.content:
                if block.type == "tool_use":
                    result = execute_tool(block.name, block.input, user_id)
                    log.info("tool %s -> %s", block.name, result[:80])
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })
            messages.append({"role": "user", "content": tool_results})
        else:
            break

    return "Не вдалося отримати відповідь."


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привіт! Я твій бізнес-асистент на Claude.\n\n"
        "Вмію:\n"
        "🧮 Рахувати математику\n"
        "📝 Зберігати нотатки\n"
        "🌐 Читати веб-сторінки\n"
        "📅 Показувати дату й час\n"
        "🖼 Аналізувати фото\n\n"
        "Команди: /notes — переглянути нотатки\n"
        "/reset — очистити історію"
    )

async def reset(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    history.pop(update.effective_user.id, None)
    await update.message.reply_text("Історію очищено.")

async def notes_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(tool_list_notes(update.effective_user.id))

async def chat(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    msgs = history.setdefault(uid, [])
    msgs.append({"role": "user", "content": update.message.text})
    await ctx.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    try:
        answer = await run_agent(uid, msgs)
        history[uid] = msgs[-20:]
        await update.message.reply_text(answer)
    except Exception:
        log.exception("chat error")
        await update.message.reply_text("Помилка. Спробуй ще раз.")

async def photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await ctx.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    try:
        file = await update.message.photo[-1].get_file()
        file_bytes = bytes(await file.download_as_bytearray())
        img_b64 = base64.standard_b64encode(file_bytes).decode()
        caption = update.message.caption or "Що зображено на фото? Опиши детально."
        resp = claude.messages.create(
            model="claude-opus-4-7",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": img_b64}},
                    {"type": "text", "text": caption}
                ]
            }]
        )
        await update.message.reply_text(resp.content[0].text)
    except Exception:
        log.exception("photo error")
        await update.message.reply_text("Помилка обробки фото.")


def main():
    app = ApplicationBuilder().token(os.environ["TELEGRAM_BOT_TOKEN"]).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("notes", notes_cmd))
    app.add_handler(MessageHandler(filters.PHOTO, photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat))
    log.info("Agent bot started with tools")
    app.run_polling()


if __name__ == "__main__":
    main()
