"""
Database Cleaner
=================
Wipes all project indices from Elastic Cloud.
Handles Elastic Cloud Serverless's restriction on wildcard deletion
by listing indices first and deleting explicitly by name.

Usage:  python db/clear_db.py
"""

import os
from elasticsearch import Elasticsearch
from dotenv import load_dotenv

# Load .env from project root
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(ROOT_DIR, ".env"))

# Index patterns to match (checked via startswith, not wildcards)
INDEX_PREFIXES = ["secops-logs-", "security-logs"]


def clear_database():
    try:
        es = Elasticsearch(
            os.getenv("ELASTIC_URL"),
            api_key=os.getenv("ELASTIC_API_KEY"),
        )
        print("[OK] Connected to Elasticsearch. Scanning for project indices...\n")

        # List all indices (Elastic Cloud blocks wildcard deletes)
        all_indices = list(es.indices.get_alias(index="*").keys())

        # Filter to our project indices
        to_delete = [
            idx for idx in all_indices
            if any(idx.startswith(prefix) for prefix in INDEX_PREFIXES)
        ]

        if not to_delete:
            print("[INFO] No matching project indices found. Database is already clean.")
            return

        print(f"Found {len(to_delete)} project index(es):")
        for idx in to_delete:
            print(f"  • {idx}")
        print()

        for idx in to_delete:
            response = es.indices.delete(index=idx, ignore_unavailable=True)
            if response.get("acknowledged"):
                print(f"  [DEL] Deleted: {idx}")
            else:
                print(f"  [WARN] Failed to delete: {idx}")

        print("\n[DONE] Database wipe complete!")

    except Exception as e:
        print(f"[ERR] Failed to clear database: {e}")


if __name__ == "__main__":
    print("[WARNING] This will permanently delete ALL project security logs")
    print("   from your Elastic Cloud database.\n")
    confirm = input("Are you sure? (y/n): ")

    if confirm.lower() == "y":
        clear_database()
    else:
        print("Operation cancelled.")
