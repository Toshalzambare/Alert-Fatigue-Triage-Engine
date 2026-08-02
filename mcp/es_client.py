import os
import json
import logging
from elasticsearch import Elasticsearch
from dotenv import load_dotenv

load_dotenv()

# Fields returned to the agent — NEVER includes labels.*
SAFE_FIELDS = [
    "@timestamp", "event.category", "event.action", "event.outcome",
    "source.ip", "source.geo.country", "source.geo.city",
    "user.name", "user.id",
    "host.name", "host.ip",
    "url.domain", "url.full",
    "network.bytes", "network.direction",
    "process.name", "process.pid",
    "message",
]

class ESClient:
    """Singleton Elasticsearch client wrapper for all tools."""
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ESClient, cls).__new__(cls)
            cls._instance._init_client()
        return cls._instance
        
    def _init_client(self):
        url = os.getenv("ELASTIC_URL")
        api_key = os.getenv("ELASTIC_API_KEY")
        if not url or not api_key:
            logging.warning("Elasticsearch credentials missing in .env")
            
        self.es = Elasticsearch(
            url,
            api_key=api_key,
            request_timeout=15,
            retry_on_timeout=True,
            max_retries=3
        )
        self.default_index = os.getenv("ES_INDEX", "secops-logs-*")
        
    def search(self, body, index=None, include_labels=False):
        """Execute a search query.
        
        Args:
            body: ES DSL dict
            index: Index pattern (defaults to secops-logs-*)
            include_labels: If True, skips projection constraint. DANGEROUS.
                            Only use for validate_detection_rule.
        """
        search_body = dict(body)
        
        # Enforce Rule #1: NEVER return raw _source wholesale.
        if not include_labels and "_source" not in search_body:
            search_body["_source"] = SAFE_FIELDS
            
        target_index = index or self.default_index
        return self.es.search(index=target_index, body=search_body)

    def count(self, body, index=None):
        """Execute a count query."""
        target_index = index or self.default_index
        return self.es.count(index=target_index, body=body)

# Expose a singleton instance
es_client = ESClient()
