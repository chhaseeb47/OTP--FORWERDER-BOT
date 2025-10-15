# otp_bot.py
# -*- coding: utf-8 -*-
"""
OTP Forwarder Bot (Telegram) - GitHub-ready minimal version
This bot fetches SMS/OTP messages from an IVASMS-like service (configured via env vars)
and forwards parsed OTPs to registered Telegram chat IDs.

SECURITY:
- Do NOT hardcode secrets. Use environment variables as shown below.
- This repository is a template. Replace/extend SERVICE_KEYWORDS and parsing logic as needed.
"""

import os
import asyncio
import re
import json
import traceback
from datetime import datetime, timedelta
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# ------------ Config from environment ------------
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")  # Telegram Bot Token
ADMIN_CHAT_IDS = os.environ.get("ADMIN_CHAT_IDS", "").split(",") if os.environ.get("ADMIN_CHAT_IDS") else []
INITIAL_CHAT_IDS = os.environ.get("INITIAL_CHAT_IDS", "").split(",") if os.environ.get("INITIAL_CHAT_IDS") else ["-1003030778414"]

LOGIN_URL = os.environ.get("IVASMS_LOGIN_URL", "https://www.ivasms.com/login")
BASE_URL = os.environ.get("IVASMS_BASE_URL", "https://www.ivasms.com/")
SMS_API_ENDPOINT = os.environ.get("IVASMS_SMS_ENDPOINT", "https://www.ivasms.com/portal/sms/received/getsms")
USERNAME = os.environ.get("IVASMS_USERNAME", "mdsajibvai095@gmail.com")
PASSWORD = os.environ.get("IVASMS_PASSWORD", "sojibbro22@@##")

POLLING_INTERVAL_SECONDS = int(os.environ.get("POLLING_INTERVAL_SECONDS", "5"))
STATE_FILE = os.environ.get("STATE_FILE", "processed_sms_ids.json")
CHAT_IDS_FILE = os.environ.get("CHAT_IDS_FILE", "chat_ids.json")

# Minimal SERVICE_KEYWORDS and EMOJIS (you can expand)
SERVICE_KEYWORDS = {
    "WhatsApp": ["whatsapp"], "Google": ["google", "gmail"], "Telegram": ["telegram"], "Unknown": ["unknown"]
}
SERVICE_EMOJIS = {"WhatsApp":"🟢","Google":"🔍","Telegram":"📩","Unknown":"❓"}
COUNTRY_FLAGS = {"Pakistan":"🇵🇰", "Unknown Country":"🏴‍☠️"}

# ------------ Utilities: load/save chat ids & processed ids ------------
def load_chat_ids():
    if not os.path.exists(CHAT_IDS_FILE):
        with open(CHAT_IDS_FILE, 'w') as f:
            json.dump(INITIAL_CHAT_IDS, f)
        return INITIAL_CHAT_IDS
    try:
        with open(CHAT_IDS_FILE, 'r') as f:
            return json.load(f)
    except Exception:
        return INITIAL_CHAT_IDS

def save_chat_ids(chat_ids):
    with open(CHAT_IDS_FILE, 'w') as f:
        json.dump(chat_ids, f, indent=2)

def load_processed_ids():
    if not os.path.exists(STATE_FILE):
        return set()
    try:
        with open(STATE_FILE, 'r') as f:
            return set(json.load(f))
    except Exception:
        return set()

def save_processed_ids(processed_set):
    with open(STATE_FILE, 'w') as f:
        json.dump(list(processed_set), f, indent=2)

def escape_markdown(text):
    escape_chars = r'\\_*[]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', str(text))

# ------------ Telegram command handlers ------------
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if user_id in ADMIN_CHAT_IDS:
        await update.message.reply_text(
            "Welcome Admin!\nCommands:\n"
            "/add_chat <chat_id>\n"
            "/remove_chat <chat_id>\n"
            "/list_chats\n\n"
            "Bot will forward new OTPs to registered chat IDs."
        )
    else:
        await update.message.reply_text("You are not authorized to use admin commands.")

async def add_chat_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if user_id not in ADMIN_CHAT_IDS:
        await update.message.reply_text("Only admins can add chat IDs.")
        return
    try:
        new_chat = context.args[0]
        chat_ids = load_chat_ids()
        if new_chat in chat_ids:
            await update.message.reply_text("Chat ID already registered.")
            return
        chat_ids.append(new_chat)
        save_chat_ids(chat_ids)
        await update.message.reply_text(f"Added chat ID: {new_chat}")
    except Exception:
        await update.message.reply_text("Usage: /add_chat <chat_id>")

async def remove_chat_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if user_id not in ADMIN_CHAT_IDS:
        await update.message.reply_text("Only admins can remove chat IDs.")
        return
    try:
        rem = context.args[0]
        chat_ids = load_chat_ids()
        if rem in chat_ids:
            chat_ids.remove(rem)
            save_chat_ids(chat_ids)
            await update.message.reply_text(f"Removed chat ID: {rem}")
        else:
            await update.message.reply_text("Chat ID not found.")
    except Exception:
        await update.message.reply_text("Usage: /remove_chat <chat_id>")

async def list_chats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if user_id not in ADMIN_CHAT_IDS:
        await update.message.reply_text("Only admins can view chat IDs.")
        return
    chat_ids = load_chat_ids()
    await update.message.reply_text("Registered chat IDs:\n" + "\n".join(chat_ids))

# ------------ Core: fetch SMS from IVASMS (adapted) ------------
async def fetch_sms_from_api(client: httpx.AsyncClient, headers: dict, csrf_token: str):
    all_messages = []
    try:
        today = datetime.utcnow()
        start_date = today - timedelta(days=1)
        from_date_str, to_date_str = start_date.strftime('%m/%d/%Y'), today.strftime('%m/%d/%Y')
        first_payload = {'from': from_date_str, 'to': to_date_str, '_token': csrf_token}
        summary_response = await client.post(SMS_API_ENDPOINT, headers=headers, data=first_payload)
        summary_response.raise_for_status()
        soup = BeautifulSoup(summary_response.text, 'html.parser')
        group_divs = soup.find_all('div', {'class': 'pointer'})
        if not group_divs:
            return []
        group_ids = []
        for div in group_divs:
            onclick = div.get('onclick','')
            m = re.search(r"getDetials\\('(.+?)'\\)", onclick)
            if m: group_ids.append(m.group(1))
        numbers_url = urljoin(BASE_URL, "portal/sms/received/getsms/number")
        sms_url = urljoin(BASE_URL, "portal/sms/received/getsms/number/sms")
        for group_id in group_ids:
            numbers_payload = {'start': from_date_str, 'end': to_date_str, 'range': group_id, '_token': csrf_token}
            numbers_res = await client.post(numbers_url, headers=headers, data=numbers_payload)
            numbers_soup = BeautifulSoup(numbers_res.text, 'html.parser')
            number_divs = numbers_soup.select("div[onclick*='getDetialsNumber']")
            phone_numbers = [d.get_text(strip=True) for d in number_divs]
            for phone in phone_numbers:
                sms_payload = {'start': from_date_str, 'end': to_date_str, 'Number': phone, 'Range': group_id, '_token': csrf_token}
                sms_res = await client.post(sms_url, headers=headers, data=sms_payload)
                sms_soup = BeautifulSoup(sms_res.text, 'html.parser')
                cards = sms_soup.find_all('div', class_='card-body')
                for card in cards:
                    p = card.find('p', class_='mb-0')
                    if not p: continue
                    sms_text = p.get_text(separator='\\n').strip()
                    date_str = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
                    country = group_id.split()[0] if group_id else "Unknown Country"
                    service = "Unknown"
                    lower = sms_text.lower()
                    for sname, kws in SERVICE_KEYWORDS.items():
                        if any(k in lower for k in kws):
                            service = sname
                            break
                    mcode = re.search(r'\\b(\\d{4,8})\\b', sms_text)
                    code = mcode.group(1) if mcode else "N/A"
                    unique_id = f"{phone}-{hash(sms_text)}"
                    flag = COUNTRY_FLAGS.get(country, COUNTRY_FLAGS.get("Unknown Country"))
                    all_messages.append({
                        "id": unique_id,
                        "time": date_str,
                        "number": phone,
                        "country": country,
                        "flag": flag,
                        "service": service,
                        "code": code,
                        "full_sms": sms_text
                    })
        return all_messages
    except Exception as e:
        print("Error in fetch_sms:", e)
        traceback.print_exc()
        return []

# ------------ Send message to Telegram chat IDs ------------
async def send_telegram_message(app: Application, chat_id: str, message_data: dict):
    try:
        time_str = message_data.get("time","N/A")
        number = message_data.get("number","N/A")
        country = message_data.get("country","N/A")
        flag = message_data.get("flag","")
        service = message_data.get("service","N/A")
        code = message_data.get("code","N/A")
        full_sms = message_data.get("full_sms","")
        emoji = SERVICE_EMOJIS.get(service, "❓")
        full_message = (
            f"🔔 *New OTP Received*\n\n"
            f"📞 *Number:* `{escape_markdown(number)}`\n"
            f"🔑 *Code:* `{escape_markdown(code)}`\n"
            f"🏷️ *Service:* {emoji} {escape_markdown(service)}\n"
            f"🌍 *Country:* {escape_markdown(country)} {flag}\n"
            f"⏱️ *Time:* `{escape_markdown(time_str)}`\n\n"
            f"💬 *Message:*\n```\n{full_sms}\n```"
        )
        await app.bot.send_message(chat_id=chat_id, text=full_message, parse_mode='MarkdownV2')
    except Exception as e:
        print("Error sending to", chat_id, e)

# ------------ The periodic job ------------
async def check_sms_job(context: ContextTypes.DEFAULT_TYPE):
    app = context.application
    print(f"[{datetime.utcnow().isoformat()}] Running check_sms_job")
    headers = {'User-Agent':'Mozilla/5.0'}
    processed = load_processed_ids()
    chat_ids = load_chat_ids()
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        try:
            login_page = await client.get(LOGIN_URL, headers=headers)
            soup = BeautifulSoup(login_page.text, 'html.parser')
            token_input = soup.find('input', {'name':'_token'})
            login_data = {'email': USERNAME, 'password': PASSWORD}
            if token_input:
                login_data['_token'] = token_input.get('value')
            login_res = await client.post(LOGIN_URL, data=login_data, headers=headers)
            if "login" in str(login_res.url).lower():
                print("Login failed for IVASMS. Check credentials.")
                return
            dash = BeautifulSoup(login_res.text, 'html.parser')
            csrf_meta = dash.find('meta', {'name':'csrf-token'})
            if not csrf_meta:
                print("CSRF token not found on dashboard.")
                return
            csrf_token = csrf_meta.get('content')
            headers['Referer'] = str(login_res.url)
            messages = await fetch_sms_from_api(client, headers, csrf_token)
            if not messages:
                print("No messages fetched.")
                return
            for msg in messages:
                if msg['id'] in processed:
                    continue
                # send to all registered chat_ids
                for cid in chat_ids:
                    try:
                        await send_telegram_message(app, cid, msg)
                    except Exception as e:
                        print("Send error:", e)
                processed.add(msg['id'])
            save_processed_ids(processed)
        except Exception as e:
            print("Error in check_sms_job main:", e)
            traceback.print_exc()

# ------------ Main: start bot and job queue ------------
def main():
    if not TELEGRAM_TOKEN:
        print("Please set TELEGRAM_TOKEN in environment.")
        return
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    # Handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("add_chat", add_chat_command))
    app.add_handler(CommandHandler("remove_chat", remove_chat_command))
    app.add_handler(CommandHandler("list_chats", list_chats_command))

    # Schedule periodic job
    app.job_queue.run_repeating(check_sms_job, interval=POLLING_INTERVAL_SECONDS, first=5)

    print("Bot starting... Press Ctrl+C to stop.")
    app.run_polling()

if __name__ == "__main__":
    main()
