import os
import asyncio
import logging
from datetime import datetime, timedelta

import certifi
from pymongo import MongoClient
from telebot.async_telebot import AsyncTeleBot
from telebot.types import ReplyKeyboardMarkup, KeyboardButton
from telebot.asyncio_handler_backends import State, StatesGroup
from telebot.asyncio_storage import StateMemoryStorage
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configuration
TOKEN = os.getenv('BOT_TOKEN')
MONGO_URI = os.getenv('MONGO_URI')
FORWARD_CHANNEL_ID = int(os.getenv('FORWARD_CHANNEL_ID'))
CHANNEL_ID = int(os.getenv('CHANNEL_ID'))
ERROR_CHANNEL_ID = int(os.getenv('ERROR_CHANNEL_ID'))

# Logging setup
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# MongoDB setup
client = MongoClient(MONGO_URI, tlsCAFile=certifi.where())
db = client['soul']
users_collection = db.users

# Constants
REQUEST_INTERVAL = 1
BLOCKED_PORTS = [8700, 20000, 443, 17500, 9031, 20002, 20001]

# Bot setup
state_storage = StateMemoryStorage()
bot = AsyncTeleBot(TOKEN, state_storage=state_storage)

class AttackStates(StatesGroup):
    waiting_for_details = State()

async def is_user_admin(user_id, chat_id):
    try:
        chat_member = await bot.get_chat_member(chat_id, user_id)
        return chat_member.status in ['administrator', 'creator']
    except Exception as e:
        logger.error(f"Error checking admin status: {e}")
        return False

@bot.message_handler(commands=['approve', 'disapprove'])
async def approve_or_disapprove_user(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    is_admin = await is_user_admin(user_id, CHANNEL_ID)
    cmd_parts = message.text.split()

    if not is_admin:
        await bot.send_message(chat_id, "*You are not authorized to use this command*", parse_mode='Markdown')
        return

    if len(cmd_parts) < 2:
        await bot.send_message(chat_id, "*Invalid command format. Use /approve <user_id> <plan> <days> or /disapprove <user_id>.*", parse_mode='Markdown')
        return

    action = cmd_parts[0].lower()
    target_user_id = int(cmd_parts[1])
    plan = int(cmd_parts[2]) if len(cmd_parts) >= 3 else 0
    days = int(cmd_parts[3]) if len(cmd_parts) >= 4 else 0

    if action == '/approve':
        if plan == 1 and users_collection.count_documents({"plan": 1}) >= 99:
            await bot.send_message(chat_id, "*Approval failed: Instant Plan 🧡 limit reached (99 users).*", parse_mode='Markdown')
            return
        elif plan == 2 and users_collection.count_documents({"plan": 2}) >= 499:
            await bot.send_message(chat_id, "*Approval failed: Instant++ Plan 💥 limit reached (499 users).*", parse_mode='Markdown')
            return

        valid_until = (datetime.now() + timedelta(days=days)).date().isoformat() if days > 0 else datetime.now().date().isoformat()
        users_collection.update_one(
            {"user_id": target_user_id},
            {"$set": {"plan": plan, "valid_until": valid_until, "access_count": 0}},
            upsert=True
        )
        msg_text = f"*User {target_user_id} approved with plan {plan} for {days} days.*"
    else:  # disapprove
        users_collection.update_one(
            {"user_id": target_user_id},
            {"$set": {"plan": 0, "valid_until": "", "access_count": 0}},
            upsert=True
        )
        msg_text = f"*User {target_user_id} disapproved and reverted to free.*"

    await bot.send_message(chat_id, msg_text, parse_mode='Markdown')
    await bot.send_message(CHANNEL_ID, msg_text, parse_mode='Markdown')

@bot.message_handler(commands=['attack'])
async def attack_command(message):
    user_id = message.from_user.id
    chat_id = message.chat.id

    try:
        user_data = users_collection.find_one({"user_id": user_id})
        if not user_data or user_data['plan'] == 0:
            await bot.send_message(chat_id, "*You are not approved to use this bot. Please contact the administrator.*", parse_mode='Markdown')
            return

        if user_data['plan'] == 1 and users_collection.count_documents({"plan": 1}) > 99:
            await bot.send_message(chat_id, "*Your Instant Plan 🧡 is currently not available due to limit reached.*", parse_mode='Markdown')
            return

        if user_data['plan'] == 2 and users_collection.count_documents({"plan": 2}) > 499:
            await bot.send_message(chat_id, "*Your Instant++ Plan 💥 is currently not available due to limit reached.*", parse_mode='Markdown')
            return

        valid_until = datetime.fromisoformat(user_data['valid_until'])
        if valid_until < datetime.now():
            await bot.send_message(chat_id, "*Your plan has expired. Please contact the administrator.*", parse_mode='Markdown')
            return

        await bot.send_message(chat_id, "*Enter the target IP, port, and duration (in seconds) separated by spaces.*", parse_mode='Markdown')
        await bot.set_state(message.from_user.id, AttackStates.waiting_for_details, message.chat.id)
    except Exception as e:
        logger.error(f"Error in attack command: {e}")
        await bot.send_message(chat_id, "*An error occurred. Please try again later.*", parse_mode='Markdown')

@bot.message_handler(state=AttackStates.waiting_for_details)
async def process_attack_command(message):
    try:
        args = message.text.split()
        if len(args) != 3:
            await bot.send_message(message.chat.id, "*Invalid command format. Please use: target_ip target_port time*", parse_mode='Markdown')
            await bot.delete_state(message.from_user.id, message.chat.id)
            return
        target_ip, target_port, duration = args[0], int(args[1]), int(args[2])

        if target_port in BLOCKED_PORTS:
            await bot.send_message(message.chat.id, f"*Port {target_port} is blocked. Please use a different port.*", parse_mode='Markdown')
            await bot.delete_state(message.from_user.id, message.chat.id)
            return

        if duration > 3600:  # Example: limit attack duration to 1 hour
            await bot.send_message(message.chat.id, "*Attack duration is too long. Please use a shorter duration.*", parse_mode='Markdown')
            await bot.delete_state(message.from_user.id, message.chat.id)
            return

        # Here you would implement the actual attack logic
        # For demonstration, we'll just log the attack details
        logger.info(f"Attack initiated: IP={target_ip}, Port={target_port}, Duration={duration}")

        await bot.send_message(message.chat.id, f"*Attack started 💥\n\nHost: {target_ip}\nPort: {target_port}\nTime: {duration}*", parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Error in processing attack command: {e}")
        await bot.send_message(message.chat.id, "*An error occurred while processing your request.*", parse_mode='Markdown')
    finally:
        await bot.delete_state(message.from_user.id, message.chat.id)

@bot.message_handler(commands=['start'])
async def send_welcome(message):
    markup = ReplyKeyboardMarkup(row_width=2, resize_keyboard=True, one_time_keyboard=True)
    buttons = [
        KeyboardButton("Instant Plan 🧡"),
        KeyboardButton("Instant++ Plan 💥"),
        KeyboardButton("Canary Download✔️"),
        KeyboardButton("My Account🏦"),
        KeyboardButton("Help❓"),
        KeyboardButton("Contact admin✔️")
    ]
    markup.add(*buttons)
    await bot.send_message(message.chat.id, "*Choose an option:*", reply_markup=markup, parse_mode='Markdown')

@bot.message_handler(func=lambda message: True)
async def handle_message(message):
    chat_id = message.chat.id
    text = message.text

    if text == "Instant Plan 🧡":
        await bot.reply_to(message, "*Instant Plan selected*", parse_mode='Markdown')
    elif text == "Instant++ Plan 💥":
        await bot.reply_to(message, "*Instant++ Plan selected*", parse_mode='Markdown')
        await attack_command(message)
    elif text == "Canary Download✔️":
        await bot.send_message(chat_id, "*Please use the following link for Canary Download: https://t.me/SOULCRACKS/10599*", parse_mode='Markdown')
    elif text == "My Account🏦":
        user_id = message.from_user.id
        user_data = users_collection.find_one({"user_id": user_id})
        if user_data:
            username = message.from_user.username
            plan = user_data.get('plan', 'N/A')
            valid_until = user_data.get('valid_until', 'N/A')
            current_time = datetime.now().isoformat()
            response = (f"*USERNAME: {username}\n"
                        f"Plan: {plan}\n"
                        f"Valid Until: {valid_until}\n"
                        f"Current Time: {current_time}*")
        else:
            response = "*No account information found. Please contact the administrator.*"
        await bot.reply_to(message, response, parse_mode='Markdown')
    elif text == "Help❓":
        await bot.reply_to(message, "*Help selected*", parse_mode='Markdown')
    elif text == "Contact admin✔️":
        await bot.reply_to(message, "*Contact admin selected*", parse_mode='Markdown')
    else:
        await bot.reply_to(message, "*Invalid option*", parse_mode='Markdown')

if __name__ == "__main__":
    logger.info("Starting Telegram bot...")
    asyncio.run(bot.polling())
