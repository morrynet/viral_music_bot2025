# Viral Music + MPESA Bot

## Features
- Quiz unlock (20 free shares)
- MPESA packages: 20 / 50 / 100 shares
- Promote links to registered groups
- Admin dashboard (`/stats`, `/listgroups`)
- Auto MPESA verification

## Setup
1. `pip install python-telegram-bot flask python-dotenv requests`
2. Fill `.env`
3. Run: `python bot.py`
4. Expose `/mpesa_callback` publicly (use Render, Railway, or Ngrok)

Database: `database.db` auto-created.
