import os
import time
import logging
import threading
import requests
from flask import Flask
import telebot
from telebot import types

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")
bot = telebot.TeleBot(BOT_TOKEN, threaded=True)

server = Flask(__name__)

@server.route('/')
def home():
    return "Flashscore Bot is running 24/7", 200

@server.route('/health')
def health():
    return {"status": "ok"}, 200


# --- ВСТРОЕННЫЙ ПАРСЕР FLASHSCORE (ОТКРЫТЫЙ CDN FEED) ---

FS_HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148",
    "x-fsign": "SW9D1eZo"
}

# Безопасные ASCII-эквиваленты разделителей Flashscore:
SEP_BLOCK = "\x7e"  # символ ~
SEP_FIELD = "\xac"  # символ ¬
SEP_PAIR = "\xf7"   # символ ÷

def parse_flashscore_feed(feed_type="f_1_0_3_ru_1"):
    url = f"https://local-global.flashscore.ninja/2/x/feed/{feed_type}"
    try:
        res = requests.get(url, headers=FS_HEADERS, timeout=8)
        if res.status_code != 200:
            return []

        raw_text = res.text
        blocks = raw_text.split(SEP_BLOCK)

        matches = []
        current_league = "Футбол"
        current_country = ""

        for block in blocks:
            if not block.strip():
                continue

            items = block.split(SEP_FIELD)
            data = {}
            for item in items:
                if SEP_PAIR in item:
                    k, v = item.split(SEP_PAIR, 1)
                    data[k] = v

            if "ZA" in data:
                current_league = data.get("ZA", "")
                current_country = data.get("ZY", "")

            if "AA" in data:
                home_team = data.get("AE", "")
                away_team = data.get("AF", "")
                score_home = data.get("AG", "")
                score_away = data.get("AH", "")
                match_status = data.get("AB", "")
                stage_text = data.get("AC", "")

                status_desc = stage_text
                if match_status == "3" and not status_desc:
                    status_desc = "Завершен"
                elif match_status == "1" and not status_desc:
                    status_desc = "Скоро"

                matches.append({
                    "country": current_country,
                    "league": current_league,
                    "home": home_team,
                    "away": away_team,
                    "score_home": score_home,
                    "score_away": score_away,
                    "status_code": match_status,
                    "status_text": status_desc
                })

        return matches
    except Exception as e:
        logger.error(f"Error fetching Flashscore: {e}")
        return []


def get_matches_by_mode(mode: str) -> str:
    matches = parse_flashscore_feed()
    if not matches:
        return "⚠️ Временная ошибка связи с Flashscore или сегодня нет матчей."

    lines = []

    for m in matches:
        country_low = m['country'].lower()
        league_low = m['league'].lower()
        score = f"{m['score_home']}:{m['score_away']}" if (m['score_home'] != "" and m['score_away'] != "") else "vs"

        if mode == "live":
            if m['status_code'] == "2":
                lines.append(f"🔴 <b>[{m['league']}]</b>\n  └ {m['home']} <b>{score}</b> {m['away']} (<i>{m['status_text']}</i>)")

        elif mode == "rpl":
            if "россия" in country_low or "russia" in country_low:
                if "премьер" in league_low or "premier" in league_low:
                    lines.append(f"🇷🇺 <b>{m['home']}</b> {score} <b>{m['away']}</b> ({m['status_text']})")

        elif mode == "epl":
            if ("англия" in country_low or "england" in country_low) and "премьер" in league_low:
                lines.append(f"🏴󠁧󠁢󠁥󠁮󠁧󠁿 <b>{m['home']}</b> {score} <b>{m['away']}</b> ({m['status_text']})")

        elif mode == "laliga":
            if ("испания" in country_low or "spain" in country_low) and ("лалига" in league_low or "примера" in league_low):
                lines.append(f"🇪🇸 <b>{m['home']}</b> {score} <b>{m['away']}</b> ({m['status_text']})")

    if not lines:
        names = {
            "live": "активных LIVE-матчей",
            "rpl": "матчей РПЛ",
            "epl": "матчей АПЛ",
            "laliga": "матчей Ла Лиги"
        }
        return f"📅 Прямо сейчас {names.get(mode, 'матчей')} не найдено."

    return "\n\n".join(lines[:15])


# --- КНОПКИ И ОБРАБОТЧИКИ TELEGRAM ---

def make_keyboard():
    kb = types.InlineKeyboardMarkup(row_width=2)
    btn_live = types.InlineKeyboardButton("🔴 Текущий LIVE", callback_data="fs_live")
    btn_rpl = types.InlineKeyboardButton("🇷🇺 РПЛ", callback_data="fs_rpl")
    btn_epl = types.InlineKeyboardButton("🏴󠁧󠁢󠁥󠁮󠁧󠁿 АПЛ", callback_data="fs_epl")
    btn_laliga = types.InlineKeyboardButton("🇪🇸 Ла Лига", callback_data="fs_laliga")

    kb.add(btn_live)
    kb.add(btn_rpl, btn_epl)
    kb.add(btn_laliga)
    return kb


@bot.message_handler(commands=['start', 'scores'])
def start_cmd(message):
    bot.send_message(
        message.chat.id,
        "⚽️ <b>Flashscore Live-Bot</b>\n\nВыберите раздел для просмотра счета в реальном времени:",
        parse_mode="HTML",
        reply_markup=make_keyboard()
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith('fs_'))
def callback_handler(call):
    bot.answer_callback_query(call.id, "Загружаю...")
    mode = call.data.replace('fs_', '')
    text = get_matches_by_mode(mode)
    bot.send_message(call.message.chat.id, text, parse_mode="HTML", reply_markup=make_keyboard())


# --- ЗАПУСК POLLING В ФОНЕ С ЗАЩИТОЙ ОТ ПАДЕНИЙ ---

def run_polling():
    time.sleep(1)
    logger.info("Starting Telegram Polling...")
    try:
        bot.remove_webhook()
    except Exception:
        pass

    while True:
        try:
            bot.infinity_polling(timeout=20, long_polling_timeout=20)
        except Exception as err:
            logger.error(f"Polling error: {err}. Restarting in 5s...")
            time.sleep(5)

threading.Thread(target=run_polling, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    server.run(host="0.0.0.0", port=port)
