import requests
import os
from dotenv import load_dotenv

load_dotenv()
token = os.getenv("BOT_TOKEN")

def check_bot():
    url = f"https://api.telegram.org/bot{token}/getMe"
    resp = requests.get(url).json()
    print(resp)

if __name__ == "__main__":
    check_bot()
