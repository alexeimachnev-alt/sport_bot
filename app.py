import os
import time
import logging
import threading
from flask import Flask
import telebot
from telebot import types
from flashscore import FlashscoreApi

# Настройка логирования
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Токен бота (из переменных Render или локально)
BOT_TOKEN = os.getenv("BOT_TOKEN", "ТВОЙ_ТЕЛЕГРАМ_ТОКЕН")
bot = telebot.TeleBot(BOT_TOKEN, threaded=True)

# Инициализируем парсер Flashscore (API-ключ НЕ требуется)
fs = FlashscoreApi()

# --- ВЕБ-СЕРВЕР ДЛЯ RENDER (Healthcheck & Anti-Sleep) ---
server = Flask(__name__)

@server.route('/')
def home():
    return "Flashscore Bot is active and running 24/7!", 200

@server.route('/health')
def health():
    return {"status": "ok"}, 200


# --- ЛОГИКА СБОРА ДАННЫХ FLASHSCORE ---

def get_flashscore_data(mode: str) -> str:
    """
    Безопасно извлекает матчи через fs-football с защитой от сбоев.
    mode: 'live', 'rpl', 'epl', 'laliga', 'ucl'
    """
    try:
        matches = fs.get_today_matches()
        if not matches:
            return "⚽️ На сегодня матчей в сетке Flashscore пока нет."

        results = []

        # Ограничиваем обход первыми 40 матчами, чтобы не перегружать CPU
        for match in matches[:40]:
            try:
                match.load_content()
            except Exception:
                continue

            home = getattr(match, 'home_team_name', 'Команда 1')
            away = getattr(match, 'away_team_name', 'Команда 2')
            score_h = getattr(match, 'home_team_score', None)
            score_a = getattr(match, 'away_team_score', None)
            country = str(getattr(match, 'country_name', '')).strip().lower()
            league = str(getattr(match, 'tournament', '') or getattr(match, 'league_name', '')).strip().lower()
            status = str(getattr(match, 'status', '')).strip()
            date_time = str(getattr(match, 'date', '')).strip()

            score_str = f"{score_h}:{score_a}" if score_h is not None and score_a is not None else "vs"

            # 1. LIVE
            if mode == "live":
                st_low = status.lower()
                is_live = any(x in st_low for x in ['1st', '2nd', 'half', 'live', 'тайм', 'перерыв']) or (status.isdigit())
                if is_live:
                    disp_league = getattr(match, 'tournament', '') or getattr(match, 'league_name', 'Матч')
                    results.append(f"🔴 <b>{disp_league}</b>\n  └ {home} <b>{score_str}</b> {away} <i>({status})</i>")

            # 2. РПЛ
            elif mode == "rpl":
                if ("russia" in country or "россия" in country) and ("premier" in league or "премьер" in league):
                    results.append(f"🇷🇺 <b>{home}</b> {score_str} <b>{away}</b> | <i>{date_time or status}</i>")

            # 3. АПЛ
            elif mode == "epl":
                if ("england" in country or "англия" in country) and "premier" in league:
                    results.append(f"🏴󠁧󠁢󠁥󠁮󠁧󠁿 <b>{home}</b> {score_str} <b>{away}</b> | <i>{date_time or status}</i>")

            # 4. Ла Лига
            elif mode == "laliga":
                if ("spain" in country or "испания" in country) and ("laliga" in league or "примера" in league):
                    results.append(f"🇪🇸 <b>{home}</b> {score_str} <b>{away}</b> | <i>{date_time or status}</i>")

            # 5. Лига Чемпионов
            elif mode == "ucl":
                if "champions league" in league or "лига чемпионов" in league:
                    results.append(f"🏆 <b>{home}</b> {score_str} <b>{away}</b> | <i>{date_time or status}</i>")

        if not results:
            names = {
                "live": "активных LIVE-матчей",
                "rpl": "матчей РПЛ",
                "epl": "матчей АПЛ",
                "laliga": "матчей Ла Лиги",
                "ucl": "матчей Лиги Чемпионов"
            }
            return f"📅 Прямо сейчас {names.get(mode, 'матчей')} на сегодня не найдено."

        return "\n\n".join(results[:15])

    except Exception as e:
        logger.error(f"Ошибка парсинга: {e}")
        return f"⚠️ Временная ошибка получения данных с Flashscore: {e}"


# --- КЛАВИАТУРА И ОБРАБОТЧИКИ TELEGRAM ---

def build_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=2)
    btn_live = types.InlineKeyboardButton("🔴 Текущий LIVE", callback_data="btn_live")
    btn_rpl = types.InlineKeyboardButton("🇷🇺 РПЛ", callback_data="btn_rpl")
    btn_epl = types.InlineKeyboardButton("🏴󠁧󠁢󠁥󠁮󠁧󠁿 АПЛ", callback_data="btn_epl")
    btn_laliga = types.InlineKeyboardButton("🇪🇸 Ла Лига", callback_data="btn_laliga")
    btn_ucl = types.InlineKeyboardButton("🏆 Лига Чемпионов", callback_data="btn_ucl")
    
    markup.add(btn_live)
    markup.add(btn_rpl, btn_epl)
    markup.add(btn_laliga, btn_ucl)
    return markup


@bot.message_handler(commands=['start', 'scores', 'help'])
def start_handler(message):
    bot.send_message(
        message.chat.id,
        "⚽️ <b>Футбольный Live-Score (Flashscore)</b>\n\nВыберите раздел для просмотра счета и расписания:",
        parse_mode="HTML",
        reply_markup=build_keyboard()
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith('btn_'))
def handle_button_clicks(call):
    bot.answer_callback_query(call.id, "Запрашиваю Flashscore...")
    mode = call.data.replace('btn_', '')
    text_result = get_flashscore_data(mode)
    
    bot.send_message(
        call.message.chat.id,
        text_result,
        parse_mode="HTML",
        reply_markup=build_keyboard()
    )


# --- ЗАПУСК POLLING В БЕСКОНЕЧНОМ ОТКАЗОУСТОЙЧИВОМ ЦИКЛЕ ---

def run_bot_polling():
    time.sleep(2)
    logger.info("Запуск Telegram Polling...")
    
    # Удаляем вебхуки перед стартом, чтобы избежать конфликта 409
    try:
        bot.remove_webhook()
    except Exception as e:
        logger.warning(f"Ошибка сброса вебхука: {e}")

    while True:
        try:
            bot.infinity_polling(timeout=20, long_polling_timeout=20)
        except Exception as err:
            logger.error(f"Сбой polling: {err}. Перезапуск через 5 секунд...")
            time.sleep(5)


# Фоновый поток для бота при старте через Gunicorn
threading.Thread(target=run_bot_polling, daemon=True).start()

if __name__ == "__main__":
    # Локальный запуск
    port = int(os.environ.get("PORT", 5000))
    server.run(host="0.0.0.0", port=port)
