import os
import sys
from dotenv import load_dotenv

load_dotenv()

# Add Agent to path so we can import modules with absolute imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "Agent"))

import graph

def mock_emit(event):
    print(f"[{event.get('type')}] {event}")

if __name__ == "__main__":
    graph.warm_up()
    print("Agent warmed up. Running Q1...")
    res = graph.run("What IPs seem malicious today and why?", mock_emit)
    print("VERDICT:", res["verdict"])
