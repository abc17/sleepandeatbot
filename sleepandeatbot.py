# bot_main.py
import os
import json
import logging
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
import re
from datetime import datetime, timedelta, time
from io import BytesIO
from telegram import Update, InputFile
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters

# === Логирование ===
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# === Глобальные паттерны ===
sleep_pattern = re.compile(r'(\d{1,2}:\d{2})[\u2013\-](\d{1,2}:\d{2}).*сон', re.IGNORECASE)
feed_pattern = re.compile(r'(\d{1,2}:\d{2}) смесь[^\d]*(\d+)')
cmap = plt.cm.Blues

def get_color_by_amount(amount):
    if amount <= 40:
        return cmap(0.3)
    elif amount <= 70:
        return cmap(0.5)
    elif amount <= 100:
        return cmap(0.7)
    else:
        return cmap(0.9)

def parse_chat(chat_data):
    messages = chat_data['messages']
    sleep_data = []
    feed_data = []

    for msg in messages:
        if msg.get('type') != 'message':
            continue

        text = msg.get('text')
        if isinstance(text, list):
            text = ''.join([t if isinstance(t, str) else t.get('text', '') for t in text])

        msg_date = datetime.fromisoformat(msg['date'])

        sleep_match = sleep_pattern.search(text)
        if sleep_match:
            start_str, end_str = sleep_match.groups()
            start_time = datetime.strptime(start_str, "%H:%M").time()
            end_time = datetime.strptime(end_str, "%H:%M").time()
            start_dt = datetime.combine(msg_date.date(), start_time)
            end_dt = datetime.combine(msg_date.date(), end_time)
            if end_time <= start_time:
                end_dt += timedelta(days=1)
                if msg_date.time() < time(4, 0):
                    start_dt -= timedelta(days=1)
                    end_dt -= timedelta(days=1)
            sleep_data.append({'date': start_dt.date(), 'start': start_dt, 'end': end_dt})
            continue

        feed_match = feed_pattern.search(text)
        if feed_match:
            feed_time = datetime.strptime(feed_match.group(1), "%H:%M").time()
            amount = int(feed_match.group(2))
            feed_dt = datetime.combine(msg_date.date(), feed_time)
            feed_data.append({'date': msg_date.date(), 'time': feed_dt, 'amount': amount})

    return pd.DataFrame(sleep_data), pd.DataFrame(feed_data)

def create_plot(sleep_df, feed_df):
    fig, ax = plt.subplots(figsize=(12, 6))
    all_dates = sorted(set(feed_df['date']).union(sleep_df['date']))

    for i, day in enumerate(all_dates):
        base_time = datetime.combine(day, datetime.min.time())
        for _, row in sleep_df[sleep_df['date'] == day].iterrows():
            start = row['start']
            end = row['end']
            ax.hlines(i, (start - base_time).total_seconds() / 3600,
                      (end - base_time).total_seconds() / 3600,
                      colors='skyblue', linewidth=10)
        for _, row in feed_df[feed_df['date'] == day].iterrows():
            time_val = row['time']
            amount = row['amount']
            time_offset = (time_val - base_time).total_seconds() / 3600
            ax.plot(time_offset, i, 'o', color=get_color_by_amount(amount), markersize=8)

    ax.set_yticks(range(len(all_dates)))
    ax.set_yticklabels([day.strftime('%Y-%m-%d') for day in all_dates])
    ax.set_xlim(0, 24)
    ax.invert_yaxis()
    ax.grid(True, axis='x', linestyle='--', alpha=0.5)
    ax.set_xlabel('Время суток (часы)')
    ax.set_title('Сон и кормления по дням')
    plt.tight_layout()
    return fig


async def handle_graph(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global feed_data, sleep_data  # твои списки словарей

    args = context.args
    if not (feed_data and sleep_data):
        update.message.reply_text("Сначала загрузите чат командой /load.")
        return

    # парсим даты из команды
    try:
        if len(args) == 0:
            start_date = min(d["date"] for d in feed_data + sleep_data)
            end_date = max(d["date"] for d in feed_data + sleep_data)
        elif len(args) == 1:
            start_date = end_date = datetime.strptime(args[0], "%Y-%m-%d").date()
        elif len(args) == 2:
            start_date = datetime.strptime(args[0], "%Y-%m-%d").date()
            end_date = datetime.strptime(args[1], "%Y-%m-%d").date()
        else:
            raise ValueError()
    except ValueError:
        update.message.reply_text("Неверный формат даты. Используйте YYYY-MM-DD или диапазон.")
        return

    # фильтруем по периоду
    feed_filtered = [x for x in feed_data if start_date <= x["date"] <= end_date]
    sleep_filtered = [x for x in sleep_data if start_date <= x["date"] <= end_date]

    if not feed_filtered and not sleep_filtered:
        update.message.reply_text("Нет данных за указанный период.")
        return

    # передаём отфильтрованные данные в график
    fig = plot_graph(feed_filtered, sleep_filtered)  # ← твоя функция отрисовки
    buf = io.BytesIO()
    fig.savefig(buf, format='png')
    buf.seek(0)
    update.message.reply_photo(photo=buf)
    buf.close()


async def handle_load(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.document:
        await update.message.reply_text("Прикрепи json-файл")
        return

    doc = update.message.document
    if not doc.file_name.endswith(".json"):
        await update.message.reply_text("Это не json-файл")
        return

    file = await doc.get_file()
    content = await file.download_as_bytearray()
    chat_data = json.loads(content)
    context.bot_data['chat_data'] = chat_data

    await update.message.reply_text("Файл успешно загружен. Теперь отправь /график")

if __name__ == '__main__':
    from dotenv import load_dotenv
    load_dotenv()

    TOKEN = os.getenv("TELEGRAM_TOKEN")

    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("график", handle_graph))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_load))

    print("Бот запущен")
    app.run_polling()
