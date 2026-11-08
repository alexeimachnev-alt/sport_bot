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
bot = telebot.TeleBot(BOT_TOKEN, threaded=False)

server = Flask(__name__)

# Иконки и флаги
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
SEP_PAIR = chr(247)   # ÷

# Заголовки русской зоны Flashscore
FS_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Accept-Language": "ru-RU,ru;q=0.9",
    "Origin": "https://www.flashscorekz.com",
    "Referer": "https://www.flashscorekz.com/",
    "x-fsign": "SW9D1eZo"
}

# Словарь перевода стран и лиг, если CDN отдал латиницу
COUNTRY_TRANSLATE = {
    "russia": "Россия",
    "belarus": "Беларусь",
    "belgium": "Бельгия",
    "europe": "Европа",
    "england": "Англия",
    "spain": "Испания",
    "germany": "Германия",
    "italy": "Италия",
    "france": "Франция",
    "usa": "США",
    "world": "Мир"
}

LEAGUE_TRANSLATE = {
    "khl": "КХЛ",
    "vhl": "ВХЛ",
    "mhl": "МХЛ",
    "nhl": "НХЛ",
    "extraleague": "Экстралига",
    "premier league": "Премьер-лига",
    "laliga": "Ла Лига",
    "champions league": "Лига Чемпионов"
}

def translate_meta(text: str, dictionary: dict) -> str:
    cleaned = text.strip()
    low = cleaned.lower()
    for en_key, ru_val in dictionary.items():
        if en_key in low:
            return ru_val
    return cleaned


@server.route('/')
def home():
    return "Flashscore Bot is running 24/7", 200

@server.route('/health')
def health():
    return {"status": "ok"}, 200

def self_ping_worker():
    time.sleep(30)
    app_url = os.getenv("RENDER_EXTERNAL_URL", "")
    if not app_url:
        return
    while True:
        try:
            requests.get(app_url, timeout=10)
        except Exception:
            pass
        time.sleep(480)


def parse_flashscore_feed(sport_id=1):
    feed_name = f"f_{sport_id}_0_3_ru_1"
    # Стучимся в RU-ноду Flashscore (46-й кластер)
    url = f"https://46.flashscore.ninja/2/x/feed/{feed_name}"

    try:
        res = requests.get(url, headers=FS_HEADERS, timeout=6)
        if res.status_code != 200:
            # Резервный хост
            url_backup = f"https://local-global.flashscore.ninja/2/x/feed/{feed_name}"
            res = requests.get(url_backup, headers=FS_HEADERS, timeout=6)
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

            if "ZA" in data:
                raw_league = data.get("ZA", "")
                raw_country = data.get("ZY", "")
                current_league = translate_meta(raw_league, LEAGUE_TRANSLATE)
                current_country = translate_meta(raw_country, COUNTRY_TRANSLATE)

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
                elif match_status == "2" and not status_desc:
                    status_desc = "LIVE"

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
        logger.error(f"Ошибка фида ({sport_id}): {e}")
        return []


def get_sport_matches(mode: str) -> str:
    sport_id = 4 if mode in ["hockey_live", "khl", "nhl"] else 1
    matches = parse_flashscore_feed(sport_id=sport_id)

    if not matches:
        return "Временная ошибка связи с Flashscore или сейчас нет матчей в этом разделе."

    lines = []

    for m in matches:
        country_low = m['country'].lower()
        league_low = m['league'].lower()

        has_score = (m['score_home'] != "" and m['score_away'] != "")
        score = f"{m['score_home']}:{m['score_away']}" if has_score else "-"

        # Футбол
        if mode == "football_live":
            if m['status_code'] == "2":
                lines.append(f"{ICON_LIVE} <b>{m['country']}: {m['league']}</b>\n   {m['home']} <b>{score}</b> {m['away']} ({ICON_TIME} <i>{m['status_text']}</i>)")

        elif mode == "rpl":
            if ("россия" in country_low or "russia" in country_low) and ("премьер" in league_low or "premier" in league_low):
                lines.append(f"{FLAG_RU} <b>{m['home']}</b> {score} <b>{m['away']}</b> | <i>{m['status_text']}</i>")

        elif mode == "epl":
            if ("англия" in country_low or "england" in country_low) and ("премьер" in league_low or "premier" in league_low):
                lines.append(f"{FLAG_EN} <b>{m['home']}</b> {score} <b>{m['away']}</b> | <i>{m['status_text']}</i>")

        elif mode == "laliga":
            if ("испания" in country_low or "spain" in country_low) and ("лалига" in league_low or "примера" in league_low or "laliga" in league_low):
                lines.append(f"{FLAG_ES} <b>{m['home']}</b> {score} <b>{m['away']}</b> | <i>{m['status_text']}</i>")

        # Хоккей
        elif mode == "hockey_live":
            if m['status_code'] == "2":
                lines.append(f"{ICON_LIVE} <b>{m['country']}: {m['league']}</b>\n   {m['home']} <b>{score}</b> {m['away']} ({ICON_TIME} <i>{m['status_text']}</i>)")

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
    btn_f_live = types.InlineKeyboardButton(f"{ICON_BALL} LIVE Футбол", callback_data="sp_football_live")
    btn_rpl = types.InlineKeyboardButton(f"{FLAG_RU} РПЛ", callback_data="sp_rpl")
    btn_epl = types.InlineKeyboardButton(f"{FLAG_EN} АПЛ", callback_data="sp_epl")
    btn_laliga = types.InlineKeyboardButton(f"{FLAG_ES} Ла Лига", callback_data="sp_laliga")

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
    try:
        bot.send_message(
            message.chat.id,
            f"{ICON_BALL} {ICON_PUCK} <b>Flashscore Live (Футбол & Хоккей)</b>\n\n"
            "Выберите раздел для просмотра счета на русском языке:",
            parse_mode="HTML",
            reply_markup=make_main_keyboard()
        )
    except Exception as e:
        logger.error(f"Ошибка отправки старта: {e}")


@bot.callback_query_handler(func=lambda call: call.data.startswith('sp_'))
def callback_handler(call):
    try:
        bot.answer_callback_query(call.id, "Загрузка с Flashscore...")
        mode = call.data.replace('sp_', '')
        text = get_sport_matches(mode)
        bot.send_message(call.message.chat.id, text, parse_mode="HTML", reply_markup=make_main_keyboard())
    except Exception as e:
        logger.error(f"Ошибка обработки кнопки: {e}")


_bot_started = False
_lock = threading.Lock()

def run_polling_loop():
    global _bot_started
    with _lock:
        if _bot_started:
            return
        _bot_started = True

    logger.info("Инициализация Telegram соединения...")
    try:
        bot.remove_webhook()
        time.sleep(1)
    except Exception as e:
        logger.warning(f"Сброс вебхука: {e}")

    while True:
        try:
            bot.infinity_polling(timeout=15, long_polling_timeout=15, skip_pending=True)
        except Exception as err:
            logger.error(f"Сбой polling: {err}. Перезапуск...")
            time.sleep(5)

threading.Thread(target=run_polling_loop, daemon=True).start()
threading.Thread(target=self_ping_worker, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    server.run(host="0.0.0.0", port=port)
