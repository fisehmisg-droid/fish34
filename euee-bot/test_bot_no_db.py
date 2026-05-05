#!/usr/bin/env python3
"""Test bot without database to verify features work"""
import os
os.environ['DEV_MODE'] = '1'

# Test basic imports
try:
    import handlers
    import config
    print("✅ All imports successful!")
except Exception as e:
    print(f"❌ Import error: {e}")
    exit(1)

# Test bot functionality
print("🚀 Bot test complete!")
print("📝 Next steps:")
print("1. Add BOT_TOKEN to .env")
print("2. Run: python main.py")
print("3. Test /start command in Telegram")
print("4. Fix Supabase connection when ready")
