import os
from elasticsearch import Elasticsearch
from dotenv import load_dotenv

# Load credentials from .env
load_dotenv()

def clear_database():
    try:
        # Initialize Elasticsearch
        es = Elasticsearch(
            os.getenv("ELASTIC_URL"),
            api_key=os.getenv("ELASTIC_API_KEY")
        )

        print("Connected to Elasticsearch. Preparing to wipe data...")

        # We fetch all indices first because Elastic Cloud prevents deleting by wildcard for safety
        all_indices = es.indices.get_alias(index="*").keys()
        
        # Filter indices that match our project patterns
        indices_to_delete = [
            idx for idx in all_indices 
            if idx.startswith("security-logs") or idx.startswith("secops-logs")
        ]

        if not indices_to_delete:
            print("ℹ️ No matching indices found to delete.")
        
        for idx in indices_to_delete:
            response = es.indices.delete(index=idx, ignore_unavailable=True)
            if response.get("acknowledged"):
                print(f"✅ Successfully deleted index: {idx}")
            else:
                print(f"⚠️ Failed to delete index: {idx}")

        print("Database wipe complete. It is now completely clean!")

    except Exception as e:
        print(f"❌ Failed to clear database: {e}")

if __name__ == "__main__":
    # Prompt the user for safety
    print("⚠️ WARNING: This will delete all mock security logs from your Elastic Cloud database.")
    confirm = input("Are you sure you want to proceed? (y/n): ")
    
    if confirm.lower() == 'y':
        clear_database()
    else:
        print("Operation cancelled.")
