import os
import db_supabase as db

def check_boss():
    try:
        print("Fetching boss fight...")
        boss = db.get_boss_fight_week()
        print(f"Boss fight data: {boss}")
    except Exception as e:
        print(f"Error fetching boss fight: {e}")

if __name__ == "__main__":
    check_boss()
