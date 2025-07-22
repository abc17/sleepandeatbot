import json
import re
import io
import os
import logging
from datetime import datetime, timedelta, time
from collections import defaultdict
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
        
        # Хранение последних обработанных данных
        self.last_sleep_data = []
        self.last_feed_data = []
        
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

        # Сохраняем данные для использования в команде /data
        self.last_sleep_data = sleep_data
        self.last_feed_data = feed_data
        
        return sleep_data, feed_data
    
    def get_daily_stats(self, start_date, end_date):
        """Получение статистики по дням за указанный период"""
        if not self.last_sleep_data and not self.last_feed_data:
            return None
            
        stats = {}
        current_date = start_date
        
        while current_date <= end_date:
            daily_stats = {
                'date': current_date,
                'total_food': 0,
                'sleep_hours': 0,
                'awake_hours': 0
            }
            
            # Статистика по питанию
            for feed in self.last_feed_data:
                if feed['date'] == current_date:
                    daily_stats['total_food'] += feed['amount']
            
            # Статистика по сну
            total_sleep_seconds = 0
            for sleep in self.last_sleep_data:
                if sleep['date'] == current_date:
                    sleep_duration = (sleep['end'] - sleep['start']).total_seconds()
                    total_sleep_seconds += sleep_duration
            
            daily_stats['sleep_hours'] = total_sleep_seconds / 3600
            daily_stats['awake_hours'] = 24 - daily_stats['sleep_hours']
            
            stats[current_date] = daily_stats
            current_date += timedelta(days=1)
            
        return stats
    
    def format_daily_stats(self, stats):
        """Форматирование статистики по дням для вывода"""
        if not stats:
            return "Нет данных за указанный период."
            
        result = []
        for date, data in stats.items():
            date_str = date.strftime('%d.%m.%Y')
            result.append(f"{date_str}")
            result.append(f"Всего съедено: {int(data['total_food'])} мл")
            result.append(f"Время сна: {data['sleep_hours']:.1f} часов")
            result.append(f"Время бодрствования: {data['awake_hours']:.1f} часов")
            result.append("")  # Пустая строка между днями
            
        return "\n".join(result).strip()
    
    def create_timeline_chart(self, sleep_data, feed_data):
        """Создание временной диаграммы"""
        if not sleep_data and not feed_data:
            return None
            
        # Получаем все уникальные даты
        all_dates = set()
        for sleep in sleep_data:
            all_dates.add(sleep['date'])
        for feed in feed_data:
            all_dates.add(feed['date'])
            
        all_dates = sorted(all_dates)
        
        if not all_dates:
            return None
            
        fig, ax = plt.subplots(figsize=(12, len(all_dates) * 0.6))
        
        # Цветовая карта для объемов смеси
        cmap = plt.cm.Blues

        for i, day in enumerate(all_dates):
            base_time = datetime.combine(day, datetime.min.time())

            # Отображение сна
            for sleep in sleep_data:
                if sleep['date'] == day:
                    start = sleep['start']
                    end = sleep['end']
                    ax.hlines(i, (start - base_time).total_seconds() / 3600,
                              (end - base_time).total_seconds() / 3600,
                              colors='skyblue', linewidth=10, 
                              label='Сон' if i == 0 else "")

            # Отображение кормления
            first_feed = True
            for feed in feed_data:
                if feed['date'] == day:
                    time_point = feed['time']
                    amount = feed['amount']
                    time_offset = (time_point - base_time).total_seconds() / 3600
                    color = self.get_color_by_amount(amount, cmap)
                    ax.plot(time_offset, i, 'o', color=color, markersize=8,
                           label='Смесь' if i == 0 and first_feed else "")
                    first_feed = False

        # Настройка осей
        ax.set_yticks(range(len(all_dates)))
        ax.set_yticklabels([day.strftime('%Y-%m-%d') for day in all_dates])
        ax.set_xlabel('Время суток (часы)')
        ax.set_xlim(0, 24)
        ax.invert_yaxis()
        ax.grid(True, axis='x', linestyle='--', alpha=0.5)
        ax.set_xticks(range(0, 24))
        ax.set_xticklabels([f'{h}' for h in range(0, 24)])
        
        if sleep_data or feed_data:
            ax.legend()
        
        plt.title('Режим сна и кормления по дням')
        plt.tight_layout()
        
        # Сохранение в буфер
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=300, bbox_inches='tight')
        buf.seek(0)
        plt.close()
        return buf
    
    def create_summary_chart(self, sleep_data, feed_data):
        """Создание сводного графика по дням"""
        if not sleep_data and not feed_data:
            return None
            
        # Подготовка данных
        daily_data = defaultdict(dict)
        
        # Группировка данных о кормлении по дням
        for feed in feed_data:
            date = feed['date']
            if 'amount' not in daily_data[date]:
                daily_data[date]['amount'] = 0
            daily_data[date]['amount'] += feed['amount']
        
        # Группировка данных о сне по дням
        sleep_by_date = defaultdict(float)
        for sleep in sleep_data:
            date = sleep['date']
            duration_hours = (sleep['end'] - sleep['start']).total_seconds() / 3600
            sleep_by_date[date] += duration_hours
        
        for date, duration in sleep_by_date.items():
            daily_data[date]['duration_hr'] = duration
        
        if not daily_data:
            return None
        
        # Сортировка данных по датам
        sorted_dates = sorted(daily_data.keys())
        amounts = [daily_data[date].get('amount', 0) for date in sorted_dates]
        durations = [daily_data[date].get('duration_hr', 0) for date in sorted_dates]
        
        # Создание графика
        fig, ax1 = plt.subplots(figsize=(10, 5))
        
        # График смеси (левая ось)
        if any(amounts):
            color1 = 'tab:orange'
            ax1.set_xlabel('Дата')
            ax1.set_ylabel('Смесь (мл)', color=color1)
            ax1.bar(sorted_dates, amounts, 
                   color=color1, alpha=0.6, label='Смесь (мл)')
            ax1.tick_params(axis='y', labelcolor=color1)
            max_amount = max(amounts) if amounts else 120
            ax1.set_ylim(0, max(max_amount, 120))
        
        # График сна (правая ось)
        if any(durations):
            ax2 = ax1.twinx()
            color2 = 'tab:blue'
            ax2.set_ylabel('Сон (часы)', color=color2)
            ax2.plot(sorted_dates, durations, 
                    color=color2, marker='o', label='Сон (часы)')
            ax2.tick_params(axis='y', labelcolor=color2)
            max_sleep = max(durations) if durations else 15
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

def parse_date(date_str):
    """Парсинг даты из строки в формате dd.mm.yyyy"""
    try:
        return datetime.strptime(date_str, "%d.%m.%Y").date()
    except ValueError:
        return None

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
/data <дата1> <дата2> - показать данные за период (формат: dd.mm.yyyy)
/data today - показать данные за сегодня
/data yesterday - показать данные за вчера

Пример: /data 21.07.2025 22.07.2025
    """
    await update.message.reply_text(welcome_text)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /help"""
    help_text = """
Инструкция по использованию:

1. Экспортируйте чат Telegram в JSON формате
2. Отправьте файл боту
3. Получите два графика:
   • Временная диаграмма по дням
   • Сводная статистика

4. Используйте команду /data для просмотра статистики:
   • /data 21.07.2025 22.07.2025 - за период
   • /data today - за сегодня
   • /data yesterday - за вчера

Поддерживаемые форматы записей:
• Сон: "09:30–11:00 сон" или "09:30-11:00 сон"
• Смесь: "14:20 смесь 80" (время и объем в мл)

Требования к файлу:
• Формат: JSON
• Размер: до 20 МБ
• Структура: экспорт чата Telegram
    """
    await update.message.reply_text(help_text)

async def data_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /data"""
    if not analyzer.last_sleep_data and not analyzer.last_feed_data:
        await update.message.reply_text(
            "Сначала загрузите JSON файл с данными для анализа."
        )
        return
    
    args = context.args
    
    if not args:
        await update.message.reply_text(
            "Укажите период для анализа:\n"
            "/data 21.07.2025 22.07.2025 - за период\n"
            "/data today - за сегодня\n"
            "/data yesterday - за вчера"
        )
        return
    
    today = datetime.now().date()
    
    if args[0].lower() == 'today':
        start_date = end_date = today
    elif args[0].lower() == 'yesterday':
        yesterday = today - timedelta(days=1)
        start_date = end_date = yesterday
    elif len(args) == 2:
        start_date = parse_date(args[0])
        end_date = parse_date(args[1])
        
        if not start_date or not end_date:
            await update.message.reply_text(
                "Неверный формат даты. Используйте формат dd.mm.yyyy\n"
                "Пример: /data 21.07.2025 22.07.2025"
            )
            return
            
        if start_date > end_date:
            start_date, end_date = end_date, start_date
    else:
        await update.message.reply_text(
            "Неверное количество аргументов. Используйте:\n"
            "/data 21.07.2025 22.07.2025 - за период\n"
            "/data today - за сегодня\n"
            "/data yesterday - за вчера"
        )
        return
    
    # Получение и форматирование статистики
    stats = analyzer.get_daily_stats(start_date, end_date)
    formatted_stats = analyzer.format_daily_stats(stats)
    
    if not formatted_stats or formatted_stats == "Нет данных за указанный период.":
        await update.message.reply_text("Нет данных за указанный период.")
    else:
        await update.message.reply_text(formatted_stats)

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик загрузки документов"""
    document = update.message.document
    
    if not document.file_name.endswith('.json'):
        await update.message.reply_text("Пожалуйста, отправьте JSON файл.")
        return
    
    if document.file_size > 20 * 1024 * 1024:  # 20 МБ
        await update.message.reply_text("Файл слишком большой. Максимальный размер: 20 МБ.")
        return
    
    await update.message.reply_text("Файл получен, анализирую данные...")
    
    try:
        # Скачивание файла
        file = await context.bot.get_file(document.file_id)
        file_bytes = await file.download_as_bytearray()
        
        # Парсинг JSON
        data = json.loads(file_bytes.decode('utf-8'))
        
        # Анализ данных
        sleep_data, feed_data = analyzer.parse_chat_data(data)
        
        if not sleep_data and not feed_data:
            await update.message.reply_text(
                "Не удалось найти данные о сне или кормлении в файле.\n"
                "Проверьте формат записей:\n"
                "• Сон: '09:30–11:00 сон'\n"
                "• Смесь: '14:20 смесь 80'"
            )
            return
        
        # Отправка статистики
        stats_text = f"Найдено данных:\n"
        if sleep_data:
            stats_text += f"• Записей о сне: {len(sleep_data)}\n"
        if feed_data:
            stats_text += f"• Записей о кормлении: {len(feed_data)}\n"
        
        await update.message.reply_text(stats_text + "\nСоздаю графики...")
        
        # Создание и отправка временной диаграммы
        timeline_chart = analyzer.create_timeline_chart(sleep_data, feed_data)
        if timeline_chart:
            await update.message.reply_photo(
                photo=timeline_chart,
                caption="Режим дня"
            )
        
        # Создание и отправка сводного графика
        summary_chart = analyzer.create_summary_chart(sleep_data, feed_data)
        if summary_chart:
            await update.message.reply_photo(
                photo=summary_chart,
                caption="Сводная статистика по дням"
            )
        
        await update.message.reply_text(
            "Анализ завершен. Теперь вы можете использовать команду /data для просмотра статистики по дням."
        )
        
    except json.JSONDecodeError:
        await update.message.reply_text("Ошибка: файл не является корректным JSON.")
    except KeyError as e:
        await update.message.reply_text(f"Ошибка: не найден ключ {e} в структуре файла.")
    except Exception as e:
        logger.error(f"Ошибка при обработке файла: {e}")
        await update.message.reply_text("Произошла ошибка при обработке файла. Попробуйте еще раз.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик текстовых сообщений"""
    await update.message.reply_text(
        "Отправьте мне JSON файл с экспортом чата для анализа\n"
        "Или используйте /help для получения справки."
    )

def main():
    """Основная функция запуска бота"""
    if not TOKEN:
        print("Ошибка: не найден TELEGRAM_TOKEN в переменных окружения")
        return
    
    # Создание приложения
    application = Application.builder().token(TOKEN).build()
    
    # Добавление обработчиков
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("data", data_command))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Запуск бота
    print("Бот запущен")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
