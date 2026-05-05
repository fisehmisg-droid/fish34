"""Initialize the bot database schema."""

from __future__ import annotations


def main() -> None:
    import db_supabase as db  # importing db creates the schema automatically

    print("Database schema is ready.")


if __name__ == "__main__":
    main()