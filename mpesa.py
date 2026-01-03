# mpesa.py
import os
import base64
import requests
import time
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

CONSUMER_KEY = os.getenv("MPESA_CONSUMER_KEY")
CONSUMER_SECRET = os.getenv("MPESA_CONSUMER_SECRET")
SHORTCODE = os.getenv("MPESA_SHORTCODE")
PASSKEY = os.getenv("MPESA_PASSKEY")
CALLBACK_URL = os.getenv("MPESA_CALLBACK_URL")
BASE_URL = "https://sandbox.safaricom.co.ke"  # Change to live when ready

MAX_RETRIES = 3

def get_token():
    for _ in range(MAX_RETRIES):
        try:
            r = requests.get(
                f"{BASE_URL}/oauth/v1/generate?grant_type=client_credentials",
                auth=(CONSUMER_KEY, CONSUMER_SECRET)
            )
            r.raise_for_status()
            return r.json()["access_token"]
        except:
            time.sleep(2)
    raise Exception("Failed to get MPESA token")

def initiate_stk_push(phone, amount, account_ref):
    for _ in range(MAX_RETRIES):
        try:
            token = get_token()
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
            password = base64.b64encode(f"{SHORTCODE}{PASSKEY}{timestamp}".encode()).decode()
            payload = {
                "BusinessShortCode": SHORTCODE,
                "Password": password,
                "Timestamp": timestamp,
                "TransactionType": "CustomerPayBillOnline",
                "Amount": amount,
                "PartyA": phone,
                "PartyB": SHORTCODE,
                "PhoneNumber": phone,
                "CallBackURL": CALLBACK_URL,
                "AccountReference": account_ref,
                "TransactionDesc": "Viral Music Shares"
            }
            headers = {"Authorization": f"Bearer {token}"}
            r = requests.post(f"{BASE_URL}/mpesa/stkpush/v1/processrequest", json=payload, headers=headers)
            return r.json()
        except Exception as e:
            time.sleep(2)
    return {"error": "STK push failed after retries"}
