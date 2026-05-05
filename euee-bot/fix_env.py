import os
import shutil

# Backup current .env if present (preserve existing secrets locally)
if os.path.exists('.env'):
    shutil.copy('.env', '.env.backup')
    print("✅ Backed up current .env to .env.backup")

# Generate a safe env.example template (do NOT commit real secrets)
env_content = """# Reference environment template — copy to .env and populate real values.
# This file is a template and must NOT be used in production as-is.

# Bot Configuration
BOT_TOKEN=your_telegram_bot_token_here
ADMIN_TOKEN=your_admin_token_here
WEBHOOK_SECRET=your_webhook_secret_here
TELEBIRR_NUMBER=your_phone_number_here
ADMIN_USER_ID=your_admin_user_id_here
WEBHOOK_URL=https://your-app-name.railway.app
BASE_WEB_URL=https://your-app-name.railway.app
EUEE_EXAM_DATE=YYYY-MM-DD

# Development Mode - Force polling mode (1 = polling, 0 = webhook)
DEV_MODE=1

# Supabase Configuration
NEXT_PUBLIC_SUPABASE_URL=https://your-supabase-project.supabase.co
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=sb_publishable_YOUR_KEY_HERE
SUPABASE_DB_PASSWORD=your_supabase_db_password_here
DATABASE_URL=postgresql://postgres:your_password_here@db.your_supabase_instance.supabase.co:5432/postgres

# AI Configuration
GROQ_API_KEY=your_groq_api_key_here
ANTHROPIC_API_KEY=your_anthropic_api_key_here
GEMINI_API_KEY=your_gemini_api_key_here

# Other Configuration
ALLOW_DEMO_UPGRADE=false
PREFER_ELEVENLABS_FOR_AUDIO=false
"""

with open('env.example', 'w') as f:
    f.write(env_content)

print("✅ Wrote env.example template (copy to .env and populate real secrets)")
print("🔧 To use locally: copy env.example .env and fill in secrets")
