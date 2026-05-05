#!/usr/bin/env python3
"""Test Supabase Connection"""
import os
import psycopg2
from urllib.parse import urlparse

def test_connection():
    # Your Supabase details - use environment variables
    url = os.getenv("NEXT_PUBLIC_SUPABASE_URL", "https://your_supabase_url_here")
    password = os.getenv("SUPABASE_DB_PASSWORD", "your_supabase_password_here")
    
    # Extract project ref from URL
    parsed = urlparse(url)
    project_ref = parsed.netloc.replace('.supabase.co', '')
    
    # Test different connection string formats
    formats_to_try = [
        f"postgresql://postgres:{password}@db.{project_ref}.supabase.co:5432/postgres",
        f"postgresql://postgres:{password}@{project_ref}.supabase.co:5432/postgres",
        f"postgresql://postgres:{password}@aws-0-us-east-1.pooler.supabase.com:6543/postgres",
    ]
    
    for i, conn_str in enumerate(formats_to_try):
        print(f"Testing format {i+1}: {conn_str}")
        try:
            conn = psycopg2.connect(conn_str)
            print(f"✅ Format {i+1} connected successfully!")
            conn.close()
            return True
        except Exception as e:
            print(f"❌ Format {i+1} failed: {e}")
    
    print("\n🔍 Check these in your Supabase dashboard:")
    print("1. Settings → Database → Connection string")
    print("2. Look for the correct host format")
    print("3. Verify your database password")

if __name__ == "__main__":
    test_connection()
