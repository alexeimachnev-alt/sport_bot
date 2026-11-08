import os
import time
import logging
import threading
from datetime import datetime, timezone, timedelta
import requests
from flask import Flask
import telebot
from telebot import types

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")
bot = telebot.TeleBot(BOT_TOKEN, threaded=False)

server = Flask(__name__)

# Иконки и флаги через chr(), чтобы GitHub не ругался на hidden characters
FLAG_RU = chr(0x1F1F7) + chr(0x1F1FA)
FLAG_EN = chr(0x1F3F4) + chr(0xE0067) + chr(0xE0062) + chr(0xE0065) + chr(0xE006E) + chr(0xE0067) + chr(0xE007F)
FLAG_ES = chr(0x1F1EA) + chr(0x1F1F8)
FLAG_US = chr(0x1F1FA) + chr(0x1F1F8)
ICON_BALL = chr(0x26BD)
ICON_PUCK = chr(0x1F3D2)
ICON_LIVE = chr(0x1F534)
ICON_TIME = chr(0x23F1)
ICON_CAL = chr(0x1F4C5)

SEP_BLOCK = chr(126)  # ~
SEP_FIELD = chr(172)  # ¬
SEP_PAIR = chr(247)   # ÷

FS_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Accept-Language": "ru-RU,ru;q=0.9",
    "Origin": "https://www.flashscorekz.com",
    "Referer": "https://www.flashscorekz.com/",
    "x-fsign": "SW9D1eZo"
}

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

# МСК часовой пояс (UTC+3)
MSK_TZ = timezone(timedelta(hours=3))

def format_timestamp_msk(ts_str: str) -> str:
    """Конвертирует Unix timestamp матча в формат: ДД.ММ в ЧЧ:ММ МСК"""
    try:
        ts = int(ts_str)
        dt = datetime.fromtimestamp(ts, tz=MSK_TZ)
        return dt.strftime("%d.%m в %H:%M МСК")
    except Exception:
        return "Скоро"


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


def parse_flashscore_feed(sport_id=1, day_offset=0):
    """
    sport_id: 1 - Футбол, 4 - Хоккей
    day_offset: -1 (вчера), 0 (сегодня), 1 (завтра), 2 (послезавтра)
    """
    feed_name = f"f_{sport_id}_{day_offset}_3_ru_1"
    url = f"https://46.flashscore.ninja/2/x/feed/{feed_name}"

    try:
        res = requests.get(url, headers=FS_HEADERS, timeout=6)
        if res.status_code != 200:
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
                match_time_raw = data.get("AD", "")

                # Формируем читаемое время матча
                start_time_formatted = format_timestamp_msk(match_time_raw) if match_time_raw else "Скоро"

                status_desc = stage_text
                if match_status == "3" and not status_desc:
                    status_desc = "Завершен"
                elif match_status == "1":
                    status_desc = start_time_formatted
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
                    "status_text": status_desc,
                    "time_str": start_time_formatted
                })

        return matches
    except Exception as e:
        logger.error(f"Ошибка фида ({sport_id}, день {day_offset}): {e}")
        return []


def get_sport_matches(target_league: str, day_mode: str) -> str:
    """
    target_league: 'all_football', 'rpl', 'epl', 'laliga', 'all_hockey', 'khl', 'nhl'
    day_mode: 'yesterday' (-1), 'today' (0), 'tomorrow' (1), 'future' (1 + 2)
    """
    sport_id = 4 if target_league in ["all_hockey", "khl", "nhl"] else 1

    # Загружаем матчи за выбранные дни
    matches = []
    if day_mode == "yesterday":
        matches = parse_flashscore_feed(sport_id=sport_id, day_offset=-1)
    elif day_mode == "today":
        matches = parse_flashscore_feed(sport_id=sport_id, day_offset=0)
    elif day_mode == "tomorrow":
        matches = parse_flashscore_feed(sport_id=sport_id, day_offset=1)
    elif day_mode == "future":
        # Ближайшие дни: завтра + послезавтра
        m1 = parse_flashscore_feed(sport_id=sport_id, day_offset=1)
        m2 = parse_flashscore_feed(sport_id=sport_id, day_offset=2)
        matches = m1 + m2

    if not matches:
        return f"{ICON_CAL} На выбранный период данных о матчах в сетке Flashscore пока нет."

    lines = []

    for m in matches:
        country_low = m['country'].lower()
        league_low = m['league'].lower()

        # Проверка лиги/турнира
        is_target = False
        if target_league in ["all_football", "all_hockey"]:
            is_target = True
        elif target_league == "rpl":
            if ("россия" in country_low or "russia" in country_low) and ("премьер" in league_low or "premier" in league_low):
                is_target = True
        elif target_league == "epl":
            if ("англия" in country_low or "england" in country_low) and ("премьер" in league_low or "premier" in league_low):
                is_target = True
        elif target_league == "laliga":
            if ("испания" in country_low or "spain" in country_low) and ("лалига" in league_low or "примера" in league_low or "laliga" in league_low):
                is_target = True
        elif target_league == "khl":
            if "кхл" in league_low or "khl" in league_low:
                is_target = True
        elif target_league == "nhl":
            if "нхл" in league_low or "nhl" in league_low:
                is_target = True

        if not is_target:
            continue

        has_score = (m['score_home'] != "" and m['score_away'] != "")
        score = f"{m['score_home']}:{m['score_away']}" if has_score else "vs"

        # Форматирование в зависимости от статуса:
        if m['status_code'] == "2":
            # Идет прямо сейчас (LIVE)
            lines.append(f"{ICON_LIVE} <b>{m['country']}: {m['league']}</b>\n   {m['home']} <b>{score}</b> {m['away']} ({ICON_TIME} <i>{m['status_text']}</i>)")
        elif m['status_code'] == "3":
            # Завершен (вчера или сегодня)
            lines.append(f"✅ <b>{m['home']}</b> <b>{score}</b> <b>{m['away']}</b> ({m['country']}: {m['league']})")
        else:
            # Будущий матч (завтра или позже) с датой и временем
            lines.append(f"⏳ <b>{m['home']}</b> — <b>{m['away']}</b>\n   └ {ICON_TIME} <i>{m['time_str']}</i> | {m['country']}: {m['league']}")

    if not lines:
        day_names = {
            "yesterday": "вчера не проводились",
            "today": "сегодня не запланированы",
            "tomorrow": "на завтра не запланированы",
            "future": "на ближайшие дни не найдены"
        }
        return f"{ICON_CAL} Матчи выбранного турнира {day_names.get(day_mode, 'не найдены')}."

    league_headers = {
        "all_football": f"{ICON_BALL} <b>ФУТБОЛ</b>",
        "rpl": f"{FLAG_RU} <b>РОССИЙСКАЯ ПРЕМЬЕР-ЛИГА (РПЛ)</b>",
        "epl": f"{FLAG_EN} <b>АНГЛИЙСКАЯ ПРЕМЬЕР-ЛИГА (АПЛ)</b>",
        "laliga": f"{FLAG_ES} <b>ИСПАНСКАЯ ЛА ЛИГА</b>",
        "all_hockey": f"{ICON_PUCK} <b>ХОККЕЙ</b>",
        "khl": f"{FLAG_RU} <b>КХЛ (ХОККЕЙ)</b>",
        "nhl": f"{FLAG_US} <b>НХЛ (ХОККЕЙ)</b>"
    }

    day_headers = {
        "yesterday": "Результаты за ВЧЕРА",
        "today": "СЕГОДНЯ / LIVE",
        "tomorrow": "Расписание на ЗАВТРА",
        "future": "БЛИЖАЙШИЕ МАТЧИ С ДАТОЙ И ВРЕМЕНЕМ"
    }

    head = f"{league_headers.get(target_league, 'Матчи')} — <i>{day_headers.get(day_mode, '')}</i>:\n\n"
    return head + "\n\n".join(lines[:20])


# --- МЕНЮ И КНОПКИ В TELEGRAM ---

def make_tournaments_keyboard():
    """Меню 1: Выбор лиги или общего спорта"""
    kb = types.InlineKeyboardMarkup(row_width=2)
    btn_rpl = types.InlineKeyboardButton(f"{FLAG_RU} РПЛ", callback_data="sel_rpl")
    btn_khl = types.InlineKeyboardButton(f"{FLAG_RU} КХЛ (Хоккей)", callback_data="sel_khl")
    btn_epl = types.InlineKeyboardButton(f"{FLAG_EN} АПЛ", callback_data="sel_epl")
    btn_nhl = types.InlineKeyboardButton(f"{FLAG_US} НХЛ (Хоккей)", callback_data="sel_nhl")
    btn_laliga = types.InlineKeyboardButton(f"{FLAG_ES} Ла Лига", callback_data="sel_laliga")
    btn_f_all = types.InlineKeyboardButton(f"{ICON_BALL} Все матчи (Футбол)", callback_data="sel_all_football")
    btn_h_all = types.InlineKeyboardButton(f"{ICON_PUCK} Все матчи (Хоккей)", callback_data="sel_all_hockey")

    kb.add(btn_rpl, btn_khl)
    kb.add(btn_epl, btn_nhl)
    kb.add(btn_laliga)
    kb.add(btn_f_all, btn_h_all)
    return kb


def make_day_keyboard(league_key: str):
    """Меню 2: Выбор периода (Вчера, Сегодня, Завтра, Будущие)"""
    kb = types.InlineKeyboardMarkup(row_width=2)
    btn_yest = types.InlineKeyboardButton("⏪ Вчера", callback_data=f"res_{league_key}_yesterday")
    btn_today = types.InlineKeyboardButton(f"{ICON_LIVE} Сегодня / LIVE", callback_data=f"res_{league_key}_today")
    btn_tom = types.InlineKeyboardButton("⏩ Завтра", callback_data=f"res_{league_key}_tomorrow")
    btn_fut = types.InlineKeyboardButton(f"{ICON_CAL} Ближайшие (3 дня)", callback_data=f"res_{league_key}_future")
    btn_back = types.InlineKeyboardButton("⬅️ Выбрать другую лигу", callback_data="go_main_menu")

    kb.add(btn_yest, btn_today)
    kb.add(btn_tom, btn_fut)
    kb.add(btn_back)
    return kb


@bot.message_handler(commands=['start', 'scores', 'help'])
def start_cmd(message):
    try:
        bot.send_message(
            message.chat.id,
            f"{ICON_BALL} {ICON_PUCK} <b>Flashscore Спорт-Центр (Футбол & Хоккей)</b>\n\n"
            "Выберите интересующий турнир:",
            parse_mode="HTML",
            reply_markup=make_tournaments_keyboard()
        )
    except Exception as e:
        logger.error(f"Ошибка старта: {e}")


@bot.callback_query_handler(func=lambda call: call.data.startswith('sel_'))
def handle_select_league(call):
    league_key = call.data.replace('sel_', '')
    bot.answer_callback_query(call.id)
    bot.edit_message_text(
        f"{ICON_CAL} Выберите период для просмотра матчей:",
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=make_day_keyboard(league_key)
    )


@bot.callback_query_handler(func=lambda call: call.data == "go_main_menu")
def handle_back_menu(call):
    bot.answer_callback_query(call.id)
    bot.edit_message_text(
        f"{ICON_BALL} {ICON_PUCK} <b>Выберите интересующий турнир:</b>",
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        parse_mode="HTML",
        reply_markup=make_tournaments_keyboard()
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith('res_'))
def handle_show_results(call):
    # Формат data: res_{league}_{day_mode}
    parts = call.data.split('_')
    league_key = "_".join(parts[1:-1])
    day_mode = parts[-1]

    bot.answer_callback_query(call.id, "Загружаю матчи с Flashscore...")
    text = get_sport_matches(league_key, day_mode)

    bot.send_message(
        call.message.chat.id,
        text,
        parse_mode="HTML",
        reply_markup=make_day_keyboard(league_key)
    )


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
            logger.error(f"Сбой polling: {err}. Перезапуск через 5 сек...")
            time.sleep(5)

threading.Thread(target=run_polling_loop, daemon=True).start()
threading.Thread(target=self_ping_worker, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    server.run(host="0.0.0.0", port=port)
