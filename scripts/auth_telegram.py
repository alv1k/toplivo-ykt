#!/usr/bin/env python3
import sys
import os
import asyncio

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from telethon import TelegramClient

API_ID = 2040
API_HASH = "b18441a1ff607e10a989891a5462e627"
SESSION_FILE = os.path.join(BASE_DIR, "data", "toplivo_tg_user")

async def auth():
    client = TelegramClient(SESSION_FILE, API_ID, API_HASH)
    await client.connect()
    
    if not await client.is_user_authorized():
        phone = input("Enter your phone number (e.g. +7914...): ").strip()
        sent = await client.send_code_request(phone)
        code = input("Enter the code received in Telegram: ").strip()
        try:
            await client.sign_in(phone, code)
        except Exception as e:
            if "Two-steps" in str(e) or "password" in str(e).lower():
                pwd = input("Enter your 2FA Cloud Password: ").strip()
                await client.sign_in(password=pwd)
            else:
                raise e

    me = await client.get_me()
    print(f"\nSUCCESS! Authenticated as {me.first_name} (@{me.username or me.phone})")
    await client.disconnect()

if __name__ == '__main__':
    asyncio.run(auth())
