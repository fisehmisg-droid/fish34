# 🚀 Abebe EUEE Bot - Complete Setup Guide

## 📋 Prerequisites

- Python 3.8+ installed
- Git repository cloned
- Supabase project created

## 🔧 Step 1: Update Environment Variables

### For Local Testing:

```bash
# Update your .env file with:
BOT_TOKEN=your_bot_token_here
ADMIN_TOKEN=your_admin_token_here
WEBHOOK_SECRET=your_webhook_secret_here
TELEBIRR_NUMBER=your_telebirr_number_here

# Supabase (optional for testing)
NEXT_PUBLIC_SUPABASE_URL=your_supabase_url_here
SUPABASE_DB_PASSWORD=your_supabase_password_here

# AI (add at least one)
GROQ_API_KEY=your_groq_key_here
```

## 🏃 Step 2: Start Bot Locally

### Option A: Development Mode (Recommended)

```bash
# Enable DEV_MODE to skip database connection
set DEV_MODE=1
python main.py
```

### Option B: Full Mode (with database)

```bash
# Make sure Supabase schema is run first
python main.py
```

## 📱 Step 3: Test Bot Features

Send these commands to your bot:

- `/start` - Initialize bot
- Try menu options like "Practice", "Study Notes"
- Test upgrade flow
- Verify all features work

## 🚀 Step 4: Deploy to Railway

### 4.1 Prepare for Deployment

```bash
# Make sure all dependencies are installed
pip install -r requirements.txt

# Test one more time
python main.py
```

### 4.2 Deploy to Railway

1. **Push to GitHub**:

   ```bash
   git add .
   git commit -m "Ready for Railway deployment"
   git push origin main
   ```

2. **Deploy on Railway**:
   - Go to https://railway.app
   - Click "New Project" → "Deploy from GitHub"
   - Select your repository
   - Railway will auto-detect Python app

### 4.3 Set Railway Environment Variables

In Railway dashboard → Settings → Variables:

```
BOT_TOKEN=your_bot_token_here
ADMIN_TOKEN=your_admin_token_here
WEBHOOK_SECRET=your_webhook_secret_here
WEBHOOK_URL=https://your-app-name.railway.app/webhook
BASE_WEB_URL=https://your-app-name.railway.app
TELEBIRR_NUMBER=your_telebirr_number_here

# Supabase
NEXT_PUBLIC_SUPABASE_URL=your_supabase_url_here
SUPABASE_DB_PASSWORD=your_supabase_password_here

# AI
GROQ_API_KEY=your_groq_key_here
```

### 4.4 Configure Railway Settings

- **Port**: 8080 (auto-detected)
- **Start Command**: `python main.py`
- **Health Check Path**: `/`

### 4.5 Deploy and Test

- Railway will build and deploy
- Once deployed, test your bot
- Check logs for any errors

## 🔍 Troubleshooting

### Bot Not Responding:

- Check bot token is correct
- Verify Railway environment variables
- Check Railway logs

### Database Issues:

- Run Supabase schema first
- Check connection strings
- Enable DEV_MODE for testing

### Railway Deployment Issues:

- Check requirements.txt
- Verify start command
- Check build logs

## ✅ Success Checklist

- [ ] Bot starts locally without errors
- [ ] All menu options work
- [ ] Payment flow works
- [ ] Railway deployment successful
- [ ] Bot responds on Railway
- [ ] Database connected (if using Supabase)

## 🎯 Final Notes

- Bot auto-switches between polling (local) and webhook (Railway)
- In-memory fallback works even if database is down
- All features tested and working
- Ready for production users!
