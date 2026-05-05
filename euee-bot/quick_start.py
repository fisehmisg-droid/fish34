#!/usr/bin/env python3
"""Quick bot start in DEV_MODE to test features"""
import os
os.environ['DEV_MODE'] = '1'

# Import and start bot
import main
from telegram.ext import Application

def main():
    print("🚀 Starting Abebe Bot in DEV_MODE...")
    print("✅ Database connection will be skipped")
    print("📱 Bot features will work (except database-dependent)")
    print("🔧 You can test: /start, menu, practice questions, etc.")
    
    # Build the app (this will show if imports work)
    app = main.build_app()
    
    print("✅ Bot built successfully!")
    print("📝 Add your BOT_TOKEN to .env to test with real Telegram")
    print("🌐 Bot ready for testing!")

if __name__ == "__main__":
    main()
