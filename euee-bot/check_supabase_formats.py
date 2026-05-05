#!/usr/bin/env python3
"""Check different Supabase connection formats"""
import psycopg2

def test_formats():
    base_url = "https://your_supabase_url_here"  # Set from environment
    password = "your_supabase_password_here"  # Set from environment
    
    # Extract project ref
    project_ref = base_url.replace("https://", "").replace(".supabase.co", "")
    
    # Different possible host formats
    formats = [
        # Standard format
        f"postgresql://postgres:{password}@db.{project_ref}.supabase.co:5432/postgres",
        # Direct format  
        f"postgresql://postgres:{password}@{project_ref}.supabase.co:5432/postgres",
        # Pooler format
        f"postgresql://postgres:{password}@aws-0-us-east-1.pooler.supabase.com:6543/postgres",
        # Alternative direct
        f"postgresql://postgres:{password}@aws-0-us-east-1.pooler.supabase.com/postgres",
    ]
    
    print(f"Project ref: {project_ref}")
    print(f"Testing {len(formats)} formats...\n")
    
    for i, conn_str in enumerate(formats):
        try:
            print(f"Test {i+1}: {conn_str[:50]}...")
            conn = psycopg2.connect(conn_str, connect_timeout=10)
            print(f"✅ Format {i+1} SUCCESS!")
            conn.close()
            return conn_str
        except Exception as e:
            print(f"❌ Format {i+1} failed: {str(e)[:100]}")
    
    print("\n🔍 Try the SUCCESSFUL format in your DATABASE_URL")

if __name__ == "__main__":
    test_formats()
