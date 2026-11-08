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
    return "Flashscore Bot (Football + Hockey) is running 24/7", 200

@server.route('/health')
def health():
    return {"status": "ok"}, 200


# Символы и флаги через chr(), чтобы GitHub не выдавал предупреждений
FLAG_RU = chr(0x1F1F7) + chr(0x1F1FA)
FLAG_EN = chr(0x1F3F4) + chr(0xE0067) + chr(0xE0062) + chr(0xE0065) + chr(0xE006E) + chr(0xE0067) + chr(0xE007F)
FLAG_ES = chr(0x1F1EA) + chr(0x1F1F8)
FLAG_US = chr(0x1F1FA) + chr(0x1F1F8)
ICON_BALL = chr(0x26BD)
ICON_PUCK = chr(0x1F3D2)
ICON_LIVE = chr(0x1F534)
ICON_TIME = chr(0x23F1)

SEP_BLOCK = chr(126)  # ~
SEP_FIELD = chr(172)  # ¬
SEP_PAIR  = chr(247)  # ÷

# Заголовки для принудительного получения данных на русском языке
FS_HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
    "x-fsign": "SW9D1eZo"
}

def parse_flashscore_feed(sport_id=1):
    """
    sport_id=1: Футбол (лента f_1_0_3_ru_1)
    sport_id=4: Хоккей (лента f_4_0_3_ru_1)
    """
    feed_name = f"f_{sport_id}_0_3_ru_1"
    url = "https://local-global.flashscore.ninja/2/x/feed/" + feed_name
    
    try:
        res = requests.get(url, headers=FS_HEADERS, timeout=8)
        if res.status_code != 200:
            return []

        blocks = res.text.split(SEP_BLOCK)
        matches = []
        current_league = "Турнир"
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

            # Турнир и страна
            if "ZA" in data:
                current_league = data.get("ZA", "")
                current_country = data.get("ZY", "")

            # Матч
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
        logger.error(f"Feed error ({sport_id}): {e}")
        return []


def get_sport_matches(mode: str) -> str:
    # Определяем, какой фид запрашивать: 1 - Футбол, 4 - Хоккей
    sport_id = 4 if mode in ["hockey_live", "khl", "nhl"] else 1
    matches = parse_flashscore_feed(sport_id=sport_id)

    if not matches:
        return "Временная ошибка связи с Flashscore или сегодня нет матчей в этом виде спорта."

    lines = []

    for m in matches:
        country_low = m['country'].lower()
        league_low = m['league'].lower()

        has_score = (m['score_home'] != "" and m['score_away'] != "")
        score = f"{m['score_home']}:{m['score_away']}" if has_score else "-"

        # --- ФУТБОЛ ---
        if mode == "football_live":
            if m['status_code'] == "2":
                lines.append(f"{ICON_LIVE} <b>{m['league']}</b>\n   {m['home']} <b>{score}</b> {m['away']} ({ICON_TIME} <i>{m['status_text']}</i>)")

        elif mode == "rpl":
            if ("россия" in country_low or "russia" in country_low) and ("премьер" in league_low or "premier" in league_low):
                lines.append(f"{FLAG_RU} <b>{m['home']}</b> {score} <b>{m['away']}</b> | <i>{m['status_text']}</i>")

        elif mode == "epl":
            if ("англия" in country_low or "england" in country_low) and "премьер" in league_low:
                lines.append(f"{FLAG_EN} <b>{m['home']}</b> {score} <b>{m['away']}</b> | <i>{m['status_text']}</i>")

        elif mode == "laliga":
            if ("испания" in country_low or "spain" in country_low) and ("лалига" in league_low or "примера" in league_low):
                lines.append(f"{FLAG_ES} <b>{m['home']}</b> {score} <b>{m['away']}</b> | <i>{m['status_text']}</i>")

        # --- ХОККЕЙ ---
        elif mode == "hockey_live":
            if m['status_code'] == "2":
                lines.append(f"{ICON_LIVE} <b>{m['league']}</b>\n   {m['home']} <b>{score}</b> {m['away']} ({ICON_TIME} <i>{m['status_text']}</i>)")

        elif mode == "khl":
            if "кхл" in league_low or "khl" in league_low:
                lines.append(f"{FLAG_RU} <b>{m['home']}</b> {score} <b>{m['away']}</b> | <i>{m['status_text']}</i>")

        elif mode == "nhl":
            if "нхл" in league_low or "nhl" in league_low:
                lines.append(f"{FLAG_US} <b>{m['home']}</b> {score} <b>{m['away']}</b> | <i>{m['status_text']}</i>")

    if not lines:
        names = {
            "football_live": "футбольных LIVE-матчей",
            "rpl": "матчей РПЛ",
            "epl": "матчей АПЛ",
            "laliga": "матчей Ла Лиги",
            "hockey_live": "хоккейных LIVE-матчей",
            "khl": "матчей КХЛ",
            "nhl": "матчей НХЛ"
        }
        return f"Прямо сейчас {names.get(mode, 'матчей')} не найдено."

    headers = {
        "football_live": f"{ICON_BALL} {ICON_LIVE} <b>ФУТБОЛ: МАТЧИ В LIVE:</b>\n",
        "rpl": f"{FLAG_RU} <b>РОССИЙСКАЯ ПРЕМЬЕР-ЛИГА:</b>\n",
        "epl": f"{FLAG_EN} <b>АНГЛИЙСКАЯ ПРЕМЬЕР-ЛИГА:</b>\n",
        "laliga": f"{FLAG_ES} <b>ИСПАНСКАЯ ЛА ЛИГА:</b>\n",
        "hockey_live": f"{ICON_PUCK} {ICON_LIVE} <b>ХОККЕЙ: МАТЧИ В LIVE:</b>\n",
        "khl": f"{FLAG_RU} <b>КОНТИНЕНТАЛЬНАЯ ХОККЕЙНАЯ ЛИГА (КХЛ):</b>\n",
        "nhl": f"{FLAG_US} <b>НАЦИОНАЛЬНАЯ ХОККЕЙНАЯ ЛИГА (НХЛ):</b>\n"
    }

    return headers.get(mode, "") + "\n" + "\n\n".join(lines[:15])


def make_main_keyboard():
    kb = types.InlineKeyboardMarkup(row_width=2)
    # Футбол
    btn_f_live = types.InlineKeyboardButton(f"{ICON_BALL} LIVE Футбол", callback_data="sp_football_live")
    btn_rpl = types.InlineKeyboardButton(f"{FLAG_RU} РПЛ", callback_data="sp_rpl")
    btn_epl = types.InlineKeyboardButton(f"{FLAG_EN} АПЛ", callback_data="sp_epl")
    btn_laliga = types.InlineKeyboardButton(f"{FLAG_ES} Ла Лига", callback_data="sp_laliga")

    # Хоккей
    btn_h_live = types.InlineKeyboardButton(f"{ICON_PUCK} LIVE Хоккей", callback_data="sp_hockey_live")
    btn_khl = types.InlineKeyboardButton(f"{ICON_PUCK} КХЛ", callback_data="sp_khl")
    btn_nhl = types.InlineKeyboardButton(f"{FLAG_US} НХЛ", callback_data="sp_nhl")

    kb.add(btn_f_live, btn_h_live)
    kb.add(btn_rpl, btn_khl)
    kb.add(btn_epl, btn_nhl)
    kb.add(btn_laliga)
    return kb


@bot.message_handler(commands=['start', 'scores'])
def start_cmd(message):
    bot.send_message(
        message.chat.id,
        f"{ICON_BALL} {ICON_PUCK} <b>Flashscore Live (Футбол & Хоккей)</b>\n\n"
        "Выберите раздел для просмотра счета на русском языке:",
        parse_mode="HTML",
        reply_markup=make_main_keyboard()
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith('sp_'))
def callback_handler(call):
    bot.answer_callback_query(call.id, "Загрузка с Flashscore...")
    mode = call.data.replace('sp_', '')
    text = get_sport_matches(mode)
    bot.send_message(call.message.chat.id, text, parse_mode="HTML", reply_markup=make_main_keyboard())


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
