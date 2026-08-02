from elasticsearch import Elasticsearch
import time

import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

def test_elasticsearch():
    print("Connecting to Elastic Cloud Serverless...")
    # 1. Paste your Elasticsearch Endpoint URL
    # 2. Paste your API Key
    es = Elasticsearch(
        os.getenv("ELASTIC_URL"),
        api_key=os.getenv("ELASTIC_API_KEY")
    )
    
    # (Local Docker backup connection - commented out)
    # es = Elasticsearch("http://127.0.0.1:9200")
    
    # Wait for connection
    retries = 0
    while True:
        try:
            info = es.info()
            print(f"Connected to cluster: {info['cluster_name']}")
            break
        except Exception as e:
            print(f"Exception during connection: {e}")
        
        print("Waiting for Elasticsearch to start...")
        time.sleep(5)
        retries += 1
        if retries > 6:
            print("Failed to connect to Elasticsearch.")
            return

    print("Successfully connected to Elasticsearch!")

    index_name = "security-logs-test"

    # 1. Add (Index) Data
    print(f"\n--- Adding a document to index '{index_name}' ---")
    doc = {
        "@timestamp": "2026-08-01T12:00:00Z",
        "source": {"ip": "192.168.1.105"},
        "destination": {"port": 22},
        "event": {"action": "failed_login"},
        "message": "Failed password for root from 192.168.1.105 port 22 ssh2"
    }
    
    res = es.index(index=index_name, document=doc)
    doc_id = res['_id']
    print(f"Document added! ID: {doc_id}")
    
    # Force a refresh so the document is immediately searchable
    es.indices.refresh(index=index_name)

    # 2. Read (Search) Data
    print("\n--- Searching for the document ---")
    query = {
        "match": {
            "source.ip": "192.168.1.105"
        }
    }
    search_res = es.search(index=index_name, query=query)
    print(f"Found {search_res['hits']['total']['value']} hits.")
    for hit in search_res['hits']['hits']:
        print(f"Log content: {hit['_source']}")

    # 3. Delete Data
    print(f"\n--- Deleting the document ---")
    es.delete(index=index_name, id=doc_id)
    print("Document deleted.")

    # 4. Verify Deletion
    es.indices.refresh(index=index_name)
    search_res_after = es.search(index=index_name, query=query)
    print(f"Found {search_res_after['hits']['total']['value']} hits after deletion.")

if __name__ == "__main__":
    test_elasticsearch()
