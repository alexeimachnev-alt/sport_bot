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


# --- БЕЗОПАСНЫЕ СИМВОЛЫ И ЭМОДЗИ (ЧИСТЫЙ ЮНИКОД БЕЗ ОШИБОК GITHUB) ---
FLAG_RU = "\U0001F1F7\U0001F1FA"      # Флаг РФ
FLAG_EN = "\U0001F3F4\U000E0067\U000E0062\U000E0065\U000E006E\U000E0067\U0007F"  # Флаг Англии
FLAG_ES = "\U0001F1EA\U0001F1F8"      # Флаг Испании
ICON_BALL = "\u26bd"                   # Футбольный мяч
ICON_LIVE = "\U0001F534"               # Красный кружок LIVE
ICON_TIME = "\u23f1"                   # Секундомер
ICON_CUP  = "\U0001F3C6"               # Кубок

# Разделители внутреннего фида Flashscore
SEP_BLOCK = chr(126)  # ~
SEP_FIELD = chr(172)  # ¬
SEP_PAIR  = chr(247)  # ÷

FS_HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148",
    "x-fsign": "SW9D1eZo"
}

def parse_flashscore_feed(feed_type="f_1_0_3_ru_1"):
    url = f"https://local-global.flashscore.ninja/2/x/feed/{feed_type}"
    try:
        res = requests.get(url, headers=FS_HEADERS, timeout=8)
        if res.status_code != 200:
            return []

        blocks = res.text.split(SEP_BLOCK)
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
        logger.error(f"Feed error: {e}")
        return []


def get_matches_by_mode(mode: str) -> str:
    matches = parse_flashscore_feed()
    if not matches:
        return f"{ICON_BALL} Временная ошибка связи с Flashscore или сегодня нет матчей."

    lines = []

    for m in matches:
        country_low = m['country'].lower()
        league_low = m['league'].lower()
        
        has_score = (m['score_home'] != "" and m['score_away'] != "")
        score = f"{m['score_home']}:{m['score_away']}" if has_score else "—"

        # 1. LIVE
        if mode == "live":
            if m['status_code'] == "2":
                lines.append(
                    f"{ICON_LIVE} <b>{m['league']}</b>\n"
                    f"   <b>{m['home']}</b> {score} <b>{m['away']}</b> ({ICON_TIME} <i>{m['status_text']}</i>)"
                )

        # 2. РПЛ
        elif mode == "rpl":
            if ("россия" in country_low or "russia" in country_low) and ("премьер" in league_low or "premier" in league_low):
                lines.append(f"{FLAG_RU} <b>{m['home']}</b> {score} <b>{m['away']}</b> | <i>{m['status_text']}</i>")

        # 3. АПЛ
        elif mode == "epl":
            if ("англия" in country_low or "england" in country_low) and "премьер" in league_low:
                lines.append(f"{FLAG_EN} <b>{m['home']}</b> {score} <b>{m['away']}</b> | <i>{m['status_text']}</i>")

        # 4. Ла Лига
        elif mode == "laliga":
            if ("испания" in country_low or "spain" in country_low) and ("лалига" in league_low or "примера" in league_low):
                lines.append(f"{FLAG_ES} <b>{m['home']}</b> {score} <b>{m['away']}</b> | <i>{m['status_text']}</i>")

    if not lines:
        names = {
            "live": "активных LIVE-матчей",
            "rpl": "матчей РПЛ",
            "epl": "матчей АПЛ",
            "laliga": "матчей Ла Лиги"
        }
        return f"{ICON_BALL} Прямо сейчас {names.get(mode, 'матчей')} не найдено."

    header_titles = {
        "live": f"{ICON_LIVE} <b>ТЕКУЩИЕ МАТЧИ В LIVE:</b>\n",
        "rpl": f"{FLAG_RU} <b>РОССИЙСКАЯ ПРЕМЬЕР-ЛИГА:</b>\n",
        "epl": f"{FLAG_EN} <b>АНГЛИЙСКАЯ ПРЕМЬЕР-ЛИГА:</b>\n",
        "laliga": f"{FLAG_ES} <b>ИСПАНСКАЯ ЛА ЛИГА:</b>\n"
    }

    return header_titles.get(mode, "") + "\n" + "\n\n".join(lines[:15])


# --- КРАСИВОЕ МЕНЮ КНОПОК ---

def make_keyboard():
    kb = types.InlineKeyboardMarkup(row_width=2)
    btn_live = types.InlineKeyboardButton(f"{ICON_LIVE} Текущий LIVE", callback_data="fs_live")
    btn_rpl = types.InlineKeyboardButton(f"{FLAG_RU} РПЛ", callback_data="fs_rpl")
    btn_epl = types.InlineKeyboardButton(f"{FLAG_EN} АПЛ", callback_data="fs_epl")
    btn_laliga = types.InlineKeyboardButton(f"{FLAG_ES} Ла Лига", callback_data="fs_laliga")

    kb.add(btn_live)
    kb.add(btn_rpl, btn_epl)
    kb.add(btn_laliga)
    return kb


@bot.message_handler(commands=['start', 'scores'])
def start_cmd(message):
    bot.send_message(
        message.chat.id,
        f"{ICON_BALL} <b>Футбольный Live-Score (Flashscore)</b>\n\n"
        "Выберите интересующий турнир для мгновенного просмотра счета:",
        parse_mode="HTML",
        reply_markup=make_keyboard()
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith('fs_'))
def callback_handler(call):
    bot.answer_callback_query(call.id, "Загружаю данные с Flashscore...")
    mode = call.data.replace('fs_', '')
    text = get_matches_by_mode(mode)
    bot.send_message(call.message.chat.id, text, parse_mode="HTML", reply_markup=make_keyboard())


# --- БЕСКОНЕЧНЫЙ ЦИКЛ POLLING БЕЗ ВЫЛЕТОВ ---

def run_polling():
    time.sleep(1)
    logger.info("Запуск Telegram Polling...")
    try:
        bot.remove_webhook()
    except Exception:
        pass

    while True:
        try:
            bot.infinity_polling(timeout=20, long_polling_timeout=20)
        except Exception as err:
            logger.error(f"Сбой polling: {err}. Перезапуск через 5 сек...")
            time.sleep(5)

threading.Thread(target=run_polling, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    server.run(host="0.0.0.0", port=port)
