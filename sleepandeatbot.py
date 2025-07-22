import json
import re
import io
import os
import logging
from datetime import datetime, timedelta, time
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("TELEGRAM_TOKEN")

class BabyDataAnalyzer:
    def __init__(self):
        # Регулярные выражения
        self.sleep_pattern = re.compile(r'(\d{1,2}:\d{2})[–\-](\d{1,2}:\d{2}).*сон', re.IGNORECASE)
        self.feed_pattern = re.compile(r'(\d{1,2}:\d{2}) смесь[^\d]*(\d+)')
        
    def get_color_by_amount(self, amount, cmap):
        """Определение цвета по количеству смеси"""
        if amount <= 40:
            return cmap(0.3)
        elif amount <= 70:
            return cmap(0.5)
        elif amount <= 100:
            return cmap(0.7)
        else:
            return cmap(0.9)
    
    def parse_chat_data(self, data):
        """Парсинг данных из JSON файла чата"""
        messages = data['messages']
        sleep_data = []
        feed_data = []

        for msg in messages:
            if msg.get('type') != 'message':
                continue

            text = msg.get('text')
            if isinstance(text, list):
                text = ''.join([t if isinstance(t, str) else t.get('text', '') for t in text])

            msg_date = datetime.fromisoformat(msg['date'])

            # Парсинг данных о сне
            sleep_match = self.sleep_pattern.search(text)
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

            # Парсинг данных о кормлении
            feed_match = self.feed_pattern.search(text)
            if feed_match:
                feed_time = datetime.strptime(feed_match.group(1), "%H:%M").time()
                amount = int(feed_match.group(2))
                feed_dt = datetime.combine(msg_date.date(), feed_time)
                feed_data.append({'date': msg_date.date(), 'time': feed_dt, 'amount': amount})

        return pd.DataFrame(sleep_data), pd.DataFrame(feed_data)
    
    def create_timeline_chart(self, sleep_df, feed_df):
        """Создание временной диаграммы"""
        if sleep_df.empty and feed_df.empty:
            return None
            
        all_dates = sorted(set(feed_df['date'] if not feed_df.empty else set()).union(
                          set(sleep_df['date'] if not sleep_df.empty else set())))
        
        if not all_dates:
            return None
            
        fig, ax = plt.subplots(figsize=(12, len(all_dates) * 0.6))
        
        # Цветовая карта для объемов смеси
        cmap = plt.cm.Blues
        if not feed_df.empty:
            norm = plt.Normalize(feed_df['amount'].min(), feed_df['amount'].max())

        for i, day in enumerate(all_dates):
            base_time = datetime.combine(day, datetime.min.time())

            # Отображение сна
            if not sleep_df.empty:
                day_sleep = sleep_df[sleep_df['date'] == day]
                for _, row in day_sleep.iterrows():
                    start = row['start']
                    end = row['end']
                    ax.hlines(i, (start - base_time).total_seconds() / 3600,
                              (end - base_time).total_seconds() / 3600,
                              colors='skyblue', linewidth=10, 
                              label='Сон' if i == 0 else "")

            # Отображение кормления
            if not feed_df.empty:
                day_feed = feed_df[feed_df['date'] == day]
                for _, row in day_feed.iterrows():
                    time_point = row['time']
                    amount = row['amount']
                    time_offset = (time_point - base_time).total_seconds() / 3600
                    color = self.get_color_by_amount(amount, cmap)
                    ax.plot(time_offset, i, 'o', color=color, markersize=8,
                           label='Смесь' if i == 0 and _ == day_feed.index[0] else "")

        # Настройка осей
        ax.set_yticks(range(len(all_dates)))
        ax.set_yticklabels([day.strftime('%Y-%m-%d') for day in all_dates])
        ax.set_xlabel('Время суток (часы)')
        ax.set_xlim(0, 24)
        ax.invert_yaxis()
        ax.grid(True, axis='x', linestyle='--', alpha=0.5)
        ax.set_xticks(range(0, 24))
        ax.set_xticklabels([f'{h}' for h in range(0, 24)])
        
        if not sleep_df.empty or not feed_df.empty:
            ax.legend()
        
        plt.title('Режим сна и кормления по дням')
        plt.tight_layout()
        
        # Сохранение в буфер
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=300, bbox_inches='tight')
        buf.seek(0)
        plt.close()
        return buf
    
    def create_summary_chart(self, sleep_df, feed_df):
        """Создание сводного графика по дням"""
        if sleep_df.empty and feed_df.empty:
            return None
            
        # Подготовка данных
        daily_data = {}
        
        if not feed_df.empty:
            daily_feed = feed_df.groupby('date')['amount'].sum().reset_index()
            for _, row in daily_feed.iterrows():
                daily_data[row['date']] = {'amount': row['amount']}
        
        if not sleep_df.empty:
            sleep_df['duration_min'] = (sleep_df['end'] - sleep_df['start']).dt.total_seconds() / 60
            daily_sleep = sleep_df.groupby('date')['duration_min'].sum().reset_index()
            for _, row in daily_sleep.iterrows():
                if row['date'] not in daily_data:
                    daily_data[row['date']] = {}
                daily_data[row['date']]['duration_hr'] = row['duration_min'] / 60
        
        if not daily_data:
            return None
            
        # Создание DataFrame
        merged_data = []
        for date, values in daily_data.items():
            row = {'date': date}
            row.update(values)
            merged_data.append(row)
        
        merged = pd.DataFrame(merged_data).sort_values('date')
        
        # Создание графика
        fig, ax1 = plt.subplots(figsize=(10, 5))
        
        # График смеси (левая ось)
        if 'amount' in merged.columns:
            color1 = 'tab:orange'
            ax1.set_xlabel('Дата')
            ax1.set_ylabel('Смесь (мл)', color=color1)
            ax1.bar(merged['date'], merged.get('amount', 0), 
                   color=color1, alpha=0.6, label='Смесь (мл)')
            ax1.tick_params(axis='y', labelcolor=color1)
            max_amount = merged.get('amount', pd.Series([0])).max()
            ax1.set_ylim(0, max(max_amount, 120))
        
        # График сна (правая ось)
        if 'duration_hr' in merged.columns:
            ax2 = ax1.twinx()
            color2 = 'tab:blue'
            ax2.set_ylabel('Сон (часы)', color=color2)
            ax2.plot(merged['date'], merged['duration_hr'], 
                    color=color2, marker='o', label='Сон (часы)')
            ax2.tick_params(axis='y', labelcolor=color2)
            max_sleep = merged['duration_hr'].max()
            ax2.set_ylim(0, max(max_sleep, 15))
        
        ax1.grid(axis='y', linestyle='--', alpha=0.5)
        fig.autofmt_xdate()
        plt.title('Суммарная смесь и сон по дням')
        plt.tight_layout()
        
        # Сохранение в буфер
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=300, bbox_inches='tight')
        buf.seek(0)
        plt.close()
        return buf

# Создание экземпляра анализатора
analyzer = BabyDataAnalyzer()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    welcome_text = """
Бот для анализа режима сна и кормления ребенка.

• Анализирует JSON файлы экспорта чатов Telegram
• Находит записи о сне (формат "09:30–11:00 сон")  
• Находит записи о кормлении (формат "14:20 смесь 80")
• Строит графики режима дня и статистики

Для начала работы отправьте сообщением JSON файл с экспортом чата.

Команды:
/help - показать справку
    """
    await update.message.reply_text(welcome_text)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /help"""
    help_text = """

1. Экспортируйте чат Telegram в JSON формате
2. Отправьте файл боту
3. Получите два графика:
   • Временная диаграмма по дням
   • Сводная статистика

Поддерживаемые форматы записей:
• Сон: "09:30–11:00 сон" или "09:30-11:00 сон"
• Смесь: "14:20 смесь 80" (время и объем в мл)

Требования к файлу:
• Формат: JSON
• Размер: до 20 МБ
• Структура: экспорт чата Telegram
    """
    await update.message.reply_text(help_text)

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик загрузки документов"""
    document = update.message.document
    
    if not document.file_name.endswith('.json'):
        await update.message.reply_text("❌ Пожалуйста, отправьте JSON файл.")
        return
    
    if document.file_size > 20 * 1024 * 1024:  # 20 МБ
        await update.message.reply_text("❌ Файл слишком большой. Максимальный размер: 20 МБ.")
        return
    
    await update.message.reply_text("Файл получен, анализирую данные...")
    
    try:
        # Скачивание файла
        file = await context.bot.get_file(document.file_id)
        file_bytes = await file.download_as_bytearray()
        
        # Парсинг JSON
        data = json.loads(file_bytes.decode('utf-8'))
        
        # Анализ данных
        sleep_df, feed_df = analyzer.parse_chat_data(data)
        
        if sleep_df.empty and feed_df.empty:
            await update.message.reply_text(
                "❌ Не удалось найти данные о сне или кормлении в файле.\n"
                "Проверьте формат записей:\n"
                "• Сон: '09:30–11:00 сон'\n"
                "• Смесь: '14:20 смесь 80'"
            )
            return
        
        # Отправка статистики
        stats_text = f"Найдено данных:\n"
        if not sleep_df.empty:
            stats_text += f"• Записей о сне: {len(sleep_df)}\n"
        if not feed_df.empty:
            stats_text += f"• Записей о кормлении: {len(feed_df)}\n"
        
        await update.message.reply_text(stats_text + "\n Создаю графики...")
        
        # Создание и отправка временной диаграммы
        timeline_chart = analyzer.create_timeline_chart(sleep_df, feed_df)
        if timeline_chart:
            await update.message.reply_photo(
                photo=timeline_chart,
                caption="Режим дня"
            )
        
        # Создание и отправка сводного графика
        summary_chart = analyzer.create_summary_chart(sleep_df, feed_df)
        if summary_chart:
            await update.message.reply_photo(
                photo=summary_chart,
                caption="Сводная статистика по дням"
            )
        
        await update.message.reply_text("Анализ завершен")
        
    except json.JSONDecodeError:
        await update.message.reply_text("❌ Ошибка: файл не является корректным JSON.")
    except KeyError as e:
        await update.message.reply_text(f"❌ Ошибка: не найден ключ {e} в структуре файла.")
    except Exception as e:
        logger.error(f"Ошибка при обработке файла: {e}")
        await update.message.reply_text("❌ Произошла ошибка при обработке файла. Попробуйте еще раз.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик текстовых сообщений"""
    await update.message.reply_text(
        "Отправьте мне JSON файл с экспортом чата для анализа\n"
        "Или используйте /help для получения справки."
    )

def main():
    """Основная функция запуска бота"""
    if not TOKEN:
        print("❌ Ошибка: не найден TELEGRAM_TOKEN в переменных окружения")
        return
    
    # Создание приложения
    application = Application.builder().token(TOKEN).build()
    
    # Добавление обработчиков
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Запуск бота
    print("Бот запущен")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
