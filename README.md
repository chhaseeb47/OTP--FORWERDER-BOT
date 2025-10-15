# OTP Forwarder Bot (Telegram)
Template project to fetch SMS/OTP messages (from a service like IVASMS) and forward them to Telegram chat IDs.

## Files
- `otp_bot.py` : Main bot code (uses environment variables for secrets).
- `requirements.txt` : Python dependencies.
- `.gitignore` : Files to ignore.

## Setup (quick)
1. Create a GitHub repo and push these files.
2. On your hosting (Render/Replit), set the following environment variables:
   - `TELEGRAM_TOKEN`
   - `ADMIN_CHAT_IDS` (comma-separated)
   - `INITIAL_CHAT_IDS` (comma-separated)
   - `IVASMS_USERNAME`
   - `IVASMS_PASSWORD`
3. Deploy (start command): `python otp_bot.py`

## Notes
- This repo is a starter template. Do not use it to capture others' data illegally.
- Expand `SERVICE_KEYWORDS` and parsing logic as needed for your SMS source.
