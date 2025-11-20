from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackContext, CallbackQueryHandler
from telegram.ext import filters
from telegram.constants import ChatAction
import requests
import json
import re
import logging
import pytz
import asyncio
import speech_recognition as sr
import os
import tempfile
from PIL import Image
import pytesseract
import io

# === Конфигурация основная ===
TELEGRAM_TOKEN = 'your_botapi_key'
OPENROUTER_API_KEY = 'your_api_key'
OPENROUTER_API_URL = 'https://openrouter.ai/api/v1/chat/completions'
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

# Discord webhook (опционально)
DISCORD_WEBHOOK_URL = 'your_discord_webhook_here'

# === Конфигурация моделей ===
MODEL = 'deepseek/deepseek-chat'
MODEL_NAME = 'DeepSeek AI'

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)
logging.getLogger('telegram').setLevel(logging.WARNING)
logging.getLogger('PIL').setLevel(logging.WARNING)

# Инициализация бота
application = Application.builder().token(TELEGRAM_TOKEN).build()

# Контекст диалогов
dialog_context = {}

# === Форматирование кода ===
def detect_language(code_snippet):
    """Определяет язык программирования по сниппету кода"""
    code_snippet = code_snippet.strip()
    
    # Python
    if re.search(r'^(import |from |def |class |print\(|\.py$|__name__)', code_snippet, re.MULTILINE):
        return 'python'
    # JavaScript
    elif re.search(r'(function|const |let |var |=>|console\.log|\.js$)', code_snippet):
        return 'javascript'
    # HTML
    elif re.search(r'<(!DOCTYPE|html|head|body|div|span|p)[> ]', code_snippet):
        return 'html'
    # CSS
    elif re.search(r'[.{][^{}]*{[^}]*}|@media|\.css$', code_snippet):
        return 'css'
    # Java
    elif re.search(r'(public|private|class|void main|System\.out|\.java$)', code_snippet):
        return 'java'
    # C/C++
    elif re.search(r'#include|<iostream>|printf\(|cout<<|\.(c|cpp|h)$', code_snippet):
        return 'cpp'
    # SQL
    elif re.search(r'SELECT|INSERT|UPDATE|DELETE|FROM|WHERE|CREATE TABLE', code_snippet, re.IGNORECASE):
        return 'sql'
    # PHP
    elif re.search(r'<\?php|\$[a-zA-Z_]|echo |\.php$', code_snippet):
        return 'php'
    # Ruby
    elif re.search(r'def |end$|puts |\.rb$', code_snippet):
        return 'ruby'
    # Go
    elif re.search(r'package |func |import \(|fmt\.Print|\.go$', code_snippet):
        return 'go'
    # Rust
    elif re.search(r'fn |let |println!|\.rs$', code_snippet):
        return 'rust'
    # TypeScript
    elif re.search(r'interface |type |: [^{]*[;=]|\.ts$', code_snippet):
        return 'typescript'
    # Shell/Bash
    elif re.search(r'^#!|echo |grep |sed |awk |\.sh$', code_snippet):
        return 'bash'
    # JSON
    elif re.search(r'^{.*}|\[.*\]$', code_snippet) and ('"' in code_snippet or "'" in code_snippet):
        return 'json'
    # XML
    elif re.search(r'^<\?xml|<\/[^>]+>', code_snippet):
        return 'xml'
    # Markdown
    elif re.search(r'^#+|\[.*\]\(.*\)|\*.*\*|_.*_', code_snippet):
        return 'markdown'
    
    return 'text'

def format_code_message(text):
    """Форматирует сообщение с кодом, добавляя подсветку и кнопки копирования"""
    # Разделяем текст на части с кодом и без
    parts = []
    current_pos = 0
    
    # Ищем блоки кода в тексте
    code_blocks = re.finditer(r'```(\w+)?\s*(.*?)```', text, re.DOTALL)
    
    for match in code_blocks:
        # Текст до блока кода
        if match.start() > current_pos:
            parts.append({
                'type': 'text',
                'content': text[current_pos:match.start()]
            })
        
        # Блок кода
        language = match.group(1) or detect_language(match.group(2))
        code_content = match.group(2).strip()
        
        parts.append({
            'type': 'code',
            'language': language,
            'content': code_content
        })
        
        current_pos = match.end()
    
    # Остаток текста после последнего блока кода
    if current_pos < len(text):
        parts.append({
            'type': 'text',
            'content': text[current_pos:]
        })
    
    # Если не найдено блоков кода, проверяем весь текст на наличие кода
    if not parts:
        # Простая эвристика для определения, содержит ли текст код
        if any(keyword in text.lower() for keyword in ['def ', 'function', 'class ', 'import ', 'var ', 'const ', 'let ', 'print', 'console']):
            language = detect_language(text)
            if language != 'text':
                parts.append({
                    'type': 'code',
                    'language': language,
                    'content': text
                })
            else:
                parts.append({
                    'type': 'text',
                    'content': text
                })
        else:
            parts.append({
                'type': 'text',
                'content': text
            })
    
    return parts

def create_code_keyboard(code_content, language):
    """Создает клавиатуру для копирования кода"""
    callback_code = code_content[:20] if len(code_content) > 20 else code_content
    
    callback_code = re.sub(r'[^\w\s]', '', callback_code)
    
    keyboard = [
        [
            InlineKeyboardButton(f"📋 Копировать {language.upper()}", 
                               callback_data=f"copy_{language}"),
            InlineKeyboardButton("📁 Копировать всё", 
                               callback_data="copy_all")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

# === Обработчики команд ===
async def start(update: Update, context: CallbackContext) -> None:
    keyboard = [
        ['/help', '/clear'],
        ['/info', '/stats']
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=False, resize_keyboard=True)
    
    welcome_text = f"""
🤖 *Добро пожаловать в OpenRouter AI!*

Я работаю с помощью *{MODEL_NAME}* - продвинутого помощника с искусственным интеллектом.

✨ *Основное:*
• OpenRouter AI - Работа с API сервиса

🎤 *Новые возможности:*
• Поддержка голосовых сообщений
• Автоматическое распознавание речи
• 📷 Распознавание текста с изображений
• Индикатор печати во время обработки

🛠 *Поддерживаемые ЯП:* Python, JavaScript, Java, C++, HTML, CSS, SQL, PHP, Ruby, Go, Rust, TypeScript и другие!

*Доступные команды:*
/help - Показать все команды
/info - Информация о боте
/clear - Очистить историю чата
/stats - Показывать статистику использования

Просто отправь мне сообщение *текстом, голосом или фото*, и я тебе помогу 🤖
    """
    
    await update.message.reply_text(
        text=welcome_text,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def help_command(update: Update, context: CallbackContext) -> None:
    help_text = f"""
🔧 *Доступные команды:*

/help - Показать все команды
/info - Информация о боте
/clear - Очистить историю чата
/stats - Показывать статистику использования

💬 *Как использовать:*
Просто отправьте любое сообщение *текстом, голосом или фото*, чтобы начать общение в чате!

🎤 *Голосовые сообщения:*
• Поддержка русского языка
• Автоматическое распознавание речи
• Быстрая обработка аудио

📷 *Работа с изображениями:*
• Распознавание текста с фото
• Решение задач по изображениям
• Поддержка математических формул
• Обработка скриншотов кода

📝 *Особенности кода:*
• Автоматическое определение ЯП
• Копирование кода в один клик
• Чистое форматирование
• Поддержка более 15 языков программирования!

🧠 *Текущая модель:* {MODEL_NAME}
    """
    
    await update.message.reply_text(
        text=help_text,
        parse_mode='Markdown'
    )

async def info_command(update: Update, context: CallbackContext) -> None:
    info_text = f"""
🤖 *OpenRouter AI - Информация о боте*

*Модель:* {MODEL_NAME}
*Провайдер API:* NeonCLUOD, NeonHOST
*Поддержка кода:* Полная подсветка синтаксиса
*Голосовые сообщения:* ✅ Включено
*Распознавание изображений:* ✅ Включено

🛠 *Поддерживаемые языки программирования:*
• Python, JavaScript, TypeScript
• Java, C++, C#, Go, Rust
• HTML, CSS, PHP, Ruby
• SQL, Bash, JSON, XML
• Markdown и другие!

🎤 *Голосовой ввод:*
• Распознавание русского языка
• Поддержка длинных сообщений
• Автоматическая конвертация в текст

📷 *Работа с изображениями:*
• OCR распознавание текста
• Математические задачи
• Скриншоты кода
• Документы и схемы

✨ *Особенности:*
• Интеллектуальное обнаружение кода
• Копирование в один клик
• Чистое форматирование кода
• Контекст разговора
• Обработка ошибок
• Индикатор печати

Просто присылайте код или задавайте вопросы *текстом, голосом или фото*! 🚀
    """
    
    await update.message.reply_text(
        text=info_text,
        parse_mode='Markdown'
    )

async def clear(update: Update, context: CallbackContext) -> None:
    chat_id = update.effective_chat.id
    dialog_context[chat_id] = []
    await update.message.reply_text("✅ История разговоров очищена!")

async def stats_command(update: Update, context: CallbackContext) -> None:
    chat_id = update.effective_chat.id
    await update.message.reply_text(
        text=f"📊 *Текущие настройки:*\n\n• *Модель:* {MODEL_NAME}\n• *Контекст сообщения:* `{len(dialog_context.get(chat_id, []))}`\n• *API:* NeonCLOUD\n• *Голосовые сообщения:* ✅ Включено\n• *Распознавание изображений:* ✅ Включено",
        parse_mode='Markdown'
    )

# === COPY BUTTON HANDLER ===
async def handle_copy_button(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    await query.answer()
    
    callback_data = query.data
    
    if callback_data.startswith('copy_'):
        parts = callback_data.split('_', 1)
        if len(parts) >= 2:
            action = parts[1]  # language or 'all'
            
            if action == 'all':
                await query.edit_message_text(
                    text="📋 *Код, готовый к копированию!*\n\nИспользуйте кнопки копирования над каждым блоком кода, чтобы скопировать определенные фрагменты.",
                    parse_mode='Markdown'
                )
            else:
                language = action
                await query.edit_message_text(
                    text=f"📋 *{language.upper()} код готовый к копированию!*\n\nВыберите и скопируйте код из приведенного выше сообщения.",
                    parse_mode='Markdown'
                )

# === Интеграция с дискордом ===
def send_to_discord(username, user_id, message, response, model):
    if not DISCORD_WEBHOOK_URL or 'your_discord_webhook' in DISCORD_WEBHOOK_URL:
        return
        
    telegram_link = f"[{username}](https://t.me/{username})" if username else f"UserID: {user_id}"
    
    data = {
        'content': f"🤖 **DeepSeek AI Bot Log**\n👤 From: {telegram_link}\n🧠 Модель: {model}\n💬 Сообщение: {message}\n🤖 Ответ: {response[:500]}..." if len(response) > 500 else f"🤖 Ответ: {response}"
    }
    
    try:
        requests.post(DISCORD_WEBHOOK_URL, json=data, timeout=5)
    except Exception as e:
        logger.error(f"Discord webhook error: {e}")

# === Обработка изображений ===
def extract_text_from_image(image_path):
    """Извлекает текст из изображения с помощью OCR"""
    try:
        # Открываем изображение
        image = Image.open(image_path)
        
        # Улучшаем качество изображения для лучшего распознавания
        # Увеличиваем контраст и резкость
        image = image.convert('L')  # Конвертируем в grayscale
        
        # Используем pytesseract для распознавания текста
        custom_config = r'--oem 3 --psm 6 -l rus+eng'
        text = pytesseract.image_to_string(image, config=custom_config)
        
        return text.strip()
    
    except Exception as e:
        logger.error(f"OCR Error: {e}")
        return None

async def handle_photo_message(update: Update, context: CallbackContext) -> None:
    chat_id = update.effective_chat.id
    
    # Показываем что бот работает с изображением
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    
    try:
        # Получаем фото с наилучшим качеством
        photo_file = await update.message.photo[-1].get_file()
        
        # Создаем временный файл
        with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as temp_photo:
            await photo_file.download_to_drive(temp_photo.name)
            photo_path = temp_photo.name
        
        # Извлекаем текст с изображения
        await update.message.reply_text("📷 *Обрабатываю изображение...*", parse_mode='Markdown')
        
        extracted_text = extract_text_from_image(photo_path)
        
        # Удаляем временный файл
        os.unlink(photo_path)
        
        if extracted_text and len(extracted_text) > 10:  # Если текст достаточно длинный
            await update.message.reply_text(
                text=f"📷 *Распознанный текст:*\n```\n{extracted_text}\n```",
                parse_mode='Markdown'
            )
            
            # Добавляем контекст что это распознанный текст
            user_message = f"РАСПОЗНАННЫЙ ТЕКСТ С ИЗОБРАЖЕНИЯ:\n{extracted_text}\n\nПожалуйста, проанализируй этот текст и помоги с решением задачи/ответом на вопрос."
            
            # Обрабатываем распознанный текст как обычное сообщение
            await handle_message(update, context, text_content=user_message)
        else:
            await update.message.reply_text(
                text="❌ Не удалось распознать текст на изображении или текст слишком короткий. Попробуйте отправить более четкое изображение с читаемым текстом.",
                parse_mode='Markdown'
            )
        
    except Exception as e:
        logger.error(f"Photo processing error: {e}")
        await update.message.reply_text("❌ Ошибка обработки изображения. Попробуйте отправить другое фото.")

# === Обработка голосовых сообщений ===
async def handle_voice_message(update: Update, context: CallbackContext) -> None:
    chat_id = update.effective_chat.id
    voice = update.message.voice
    
    # Показываем что бот работает с голосовым сообщением
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    
    try:
        # Скачиваем голосовое сообщение
        voice_file = await voice.get_file()
        
        # Создаем временный файл
        with tempfile.NamedTemporaryFile(delete=False, suffix='.ogg') as temp_audio:
            await voice_file.download_to_drive(temp_audio.name)
            audio_path = temp_audio.name
        
        # Конвертируем и распознаем речь
        recognizer = sr.Recognizer()
        
        # Конвертируем OGG в WAV
        wav_path = audio_path.replace('.ogg', '.wav')
        os.system(f'ffmpeg -i {audio_path} {wav_path} -y')  # -y для перезаписи
        
        with sr.AudioFile(wav_path) as source:
            audio_data = recognizer.record(source)
            text = recognizer.recognize_google(audio_data, language='ru-RU')
        
        # Удаляем временные файлы
        os.unlink(audio_path)
        os.unlink(wav_path)
        
        # Отправляем распознанный текст
        await update.message.reply_text(
            text=f"🎤 *Распознанный текст:*\n{text}",
            parse_mode='Markdown'
        )
        
        # Обрабатываем распознанный текст как обычное сообщение
        await handle_message(update, context, text_content=text)
        
    except sr.UnknownValueError:
        await update.message.reply_text("❌ Не удалось распознать речь. Попробуйте говорить четче.")
    except sr.RequestError as e:
        await update.message.reply_text(f"❌ Ошибка сервиса распознавания речи: {e}")
    except Exception as e:
        logger.error(f"Voice processing error: {e}")
        await update.message.reply_text("❌ Ошибка обработки голосового сообщения.")

# === Основной обработчик ===
async def handle_message(update: Update, context: CallbackContext, text_content: str = None) -> None:
    if text_content is None:
        user_message = update.message.text
    else:
        user_message = text_content
    
    username = update.message.from_user.username if update.message else "VoiceUser"
    user_id = update.message.from_user.id if update.message else "VoiceUser"
    chat_id = update.effective_chat.id

    # Пропускаем команды
    if user_message and user_message.startswith('/'):
        return

    # Функция для периодической отправки индикатора "печатает"
    async def keep_typing():
        while True:
            await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
            await asyncio.sleep(4)  # Обновляем каждые 4 секунды

    # Запускаем индикатор в фоне
    typing_task = asyncio.create_task(keep_typing())

    try:
        # Инициализируем контекст чата
        if chat_id not in dialog_context:
            dialog_context[chat_id] = [
                {
                    "role": "system", 
                    "content": f"You are OpenRouter AI assistant using {MODEL_NAME}. Provide helpful, accurate responses in a friendly manner. When providing code examples, use proper markdown code blocks with language specification. Format: ```language\ncode\n```"
                }
            ]

        # Добавляем сообщение пользователя
        dialog_context[chat_id].append({"role": "user", "content": user_message})

        # Подготавливаем запрос к Open Router
        headers = {
            'Authorization': f'Bearer {OPENROUTER_API_KEY}',
            'Content-Type': 'application/json',
            'HTTP-Referer': 'https://t.me/',
            'X-Title': 'OpenRouter Telegram Bot'
        }

        data = {
            'model': MODEL,
            'messages': dialog_context[chat_id],
            'max_tokens': 4000,
            'temperature': 0.7,
            'top_p': 0.9,
        }

        try:
            logger.info(f"Sending request to OpenRouter API with data: {json.dumps(data, ensure_ascii=False)}")
            
            response = requests.post(OPENROUTER_API_URL, headers=headers, json=data, timeout=60)
            response.raise_for_status()
            
            response_data = response.json()
            logger.info(f"OpenRouter response: {json.dumps(response_data, ensure_ascii=False)}")
            
            # Извлекаем ответ
            if 'choices' in response_data and len(response_data['choices']) > 0:
                bot_response = response_data['choices'][0]['message']['content']
                logger.info(f"Bot response: {bot_response}")
                
                # Добавляем ответ ассистента в контекст
                dialog_context[chat_id].append({"role": "assistant", "content": bot_response})
                
                # Ограничиваем историю сообщений (последние 12 сообщений)
                if len(dialog_context[chat_id]) > 12:
                    dialog_context[chat_id] = [dialog_context[chat_id][0]] + dialog_context[chat_id][-11:]
                
                # Форматируем ответ с подсветкой кода
                formatted_parts = format_code_message(bot_response)
                logger.info(f"Formatted parts: {len(formatted_parts)}")
                
                # Отправляем форматированное сообщение
                for i, part in enumerate(formatted_parts):
                    logger.info(f"Sending part {i}: type={part['type']}")
                    if part['type'] == 'text':
                        if part['content'].strip():  # Отправляем только если есть текст
                            await context.bot.send_message(
                                chat_id=chat_id, 
                                text=part['content'],
                                parse_mode='Markdown'
                            )
                    elif part['type'] == 'code':
                        # Форматируем код с подсветкой
                        code_message = f"```{part['language']}\n{part['content']}\n```"
                        
                        # Создаем клавиатуру для копирования
                        keyboard = create_code_keyboard(part['content'], part['language'])
                        
                        await context.bot.send_message(
                            chat_id=chat_id,
                            text=code_message,
                            parse_mode='Markdown',
                            reply_markup=keyboard
                        )
                
                # Логируем в Discord
                send_to_discord(username, user_id, user_message, bot_response, MODEL_NAME)
                
            else:
                logger.error("No choices in response")
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="❌ Ответа не последовало. Пожалуйста, попробуйте снова."
                )

        except requests.exceptions.HTTPError as err:
            error_msg = f"HTTP Error {response.status_code}"
            if response.status_code == 401:
                error_msg += ": Недопустимый ключ API"
            elif response.status_code == 429:
                error_msg += ": Превышен лимит запросов"
            elif response.status_code == 400:
                try:
                    error_data = response.json()
                    detailed_error = error_data.get('error', {}).get('message', 'Неизвестная ошибка')
                    error_msg += f": {detailed_error}"
                except:
                    error_msg += ": Неверный запрос - проверьте Ваш запрос."
            else:
                error_msg += ": Неизвестная ошибка"
            
            logger.error(f"OpenRouter Error: {error_msg}")
            logger.error(f"Response text: {response.text}")
            
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"❌ Ошибка API: {error_msg}"
            )
            
        except requests.exceptions.ConnectionError:
            logger.error("Connection error", exc_info=True)
            await context.bot.send_message(
                chat_id=chat_id,
                text="❌ Ошибка соединения. Пожалуйста, проверьте свой доступ в Интернет."
            )
            
        except requests.exceptions.Timeout:
            logger.error("Request timeout", exc_info=True)
            await context.bot.send_message(
                chat_id=chat_id,
                text="⏰ Тайм-аут соединения. Пожалуйста, попробуйте снова."
            )
            
        except Exception as e:
            logger.error(f"Unexpected error: {e}", exc_info=True)
            await context.bot.send_message(
                chat_id=chat_id,
                text="❌ Произошла непредвиденная ошибка. Пожалуйста, попробуйте снова."
            )

    except Exception as e:
        logger.error(f"Error in handle_message: {e}", exc_info=True)
        await context.bot.send_message(
            chat_id=chat_id,
            text="❌ Произошла непредвиденная ошибка. Пожалуйста, попробуйте снова."
        )
    finally:
        # Останавливаем индикатор печати
        typing_task.cancel()

async def unknown_command(update: Update, context: CallbackContext) -> None:
    await update.message.reply_text(
        text="❌ Неизвестная команда. Используй /help чтобы посмотреть список команд."
    )

# Основные команды
application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("help", help_command))
application.add_handler(CommandHandler("clear", clear))
application.add_handler(CommandHandler("info", info_command))
application.add_handler(CommandHandler("stats", stats_command))

# Обработчик кнопок копирования
application.add_handler(CallbackQueryHandler(handle_copy_button, pattern='^copy_'))

# Обработчики сообщений
application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
application.add_handler(MessageHandler(filters.VOICE, handle_voice_message))
application.add_handler(MessageHandler(filters.PHOTO, handle_photo_message))
application.add_handler(MessageHandler(filters.COMMAND, unknown_command))

# === Запуск Бота ===
if __name__ == '__main__':
    print("🤖 OpenRouter Telegram Bot Started!")
    print(f"🔧 Model: {MODEL_NAME}")
    print("🎤 Voice messages: ENABLED")
    print("📷 Photo OCR: ENABLED")
    print("📍 Bot is running with code formatting, voice and photo support...")
    print("📝 Debug logging is enabled - check logs for details")
    
    # Проверяем наличие tesseract
    try:
        pytesseract.get_tesseract_version()
        print("✅ Tesseract OCR: Found")
    except:
        print("❌ Tesseract OCR: Not found - please install")
    
    # Игнорируем предупреждения
    import warnings
    warnings.filterwarnings("ignore", category=UserWarning)
    
    # Запуск бота
    application.run_polling()