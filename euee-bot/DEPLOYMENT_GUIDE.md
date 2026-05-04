# 🚀 EUEE Abebe Bot — Railway Deployment Guide

This guide will show you how to deploy your Telegram bot to **Railway.app** for free so it runs 24/7 without needing your computer.

## Step 1: Push your code to GitHub
Railway pulls your code directly from GitHub.

1. Open your terminal in the bot folder: `c:\Users\HP\Desktop\telegram bot\euee-bot`
2. Run these commands:
   ```bash
   git init
   git add .
   git commit -m "Initial commit of EUEE Bot"
   ```
3. Create a new empty repository on [GitHub](https://github.com/new).
4. Follow GitHub's instructions to push your code:
   ```bash
   git branch -M main
   git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO_NAME.git
   git push -u origin main
   ```

*Note: Your `.env` and `firebase_key.json` will NOT be pushed to GitHub because we added them to `.gitignore`. This is good! It keeps your secrets safe.*

## Step 2: Set up Railway Project
1. Go to [Railway.app](https://railway.app/) and sign in with GitHub.
2. Click **New Project** → **Deploy from GitHub repo**.
3. Select the repository you just created.
4. Click **Add Variables** (do not deploy just yet).

## Step 3: Configure Environment Variables
Because your `.env` and `firebase_key.json` were ignored by Git, you must provide these secrets to Railway manually.

1. In your Railway project dashboard, go to the **Variables** tab.
2. Add all the variables from your local `.env` file one by one:
   - `BOT_TOKEN`
   - `GROQ_API_KEY`
   - `CHAPA_SECRET_KEY`
   - `WEBHOOK_SECRET`
   - `EUEE_EXAM_DATE`
   - `ADMIN_USER_ID`

3. **Handling the Firebase Key:**
   Since Railway doesn't have your `firebase_key.json` file, we need to pass it as a JSON string environment variable.
   - Open your `firebase_key.json` file locally.
   - Copy all the contents.
   - Go to [JSON Minifier](https://codebeautify.org/jsonminifier) and paste it to compress it into one line.
   - In Railway, add a new variable called `FIREBASE_CREDENTIALS` and paste the minified JSON string as the value.

4. **Update `config.py` and `db.py` to use `FIREBASE_CREDENTIALS`:**
   In your local `db.py`, replace the `firebase_admin.initialize_app(cred)` lines with this code to handle both local files and cloud JSON strings:
   ```python
   import json
   import os
   
   FIREBASE_CRED_STR = os.getenv("FIREBASE_CREDENTIALS")
   if FIREBASE_CRED_STR:
       cred_dict = json.loads(FIREBASE_CRED_STR)
       cred = credentials.Certificate(cred_dict)
   else:
       cred = credentials.Certificate(FIREBASE_KEY)
       
   firebase_admin.initialize_app(cred)
   ```

## Step 4: Add a Procfile (Optional but recommended)
Create a file named `Procfile` (no extension) in your bot folder with this line:
```
web: python main.py
```
This tells Railway to run the bot entrypoint, which also serves the admin dashboard and Chapa callback endpoint.

## Step 5: Deploy!
1. Once your variables are set, go to the **Deployments** tab in Railway.
2. Railway will automatically build and deploy your bot.
3. Check the **View Logs** button. If you see `🎓  ABEBE EUEE BOT — RUNNING!`, your bot is live!

## How to update your bot
When you make changes to your code locally:
1. `git add .`
2. `git commit -m "Update bot features"`
3. `git push`
Railway will automatically detect the change, rebuild, and restart your bot.

Happy deploying! 🚀
