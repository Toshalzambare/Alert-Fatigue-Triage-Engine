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
    print("\n=== TEST 1: Timeline Around (15 min) ===")
    res1 = graph.run("Show me what happened 15 minutes before and after the vpn-gw-01 incident", mock_emit)
    
    print("\n=== TEST 2: SOC Analyst Report Generation ===")
    res2 = graph.run("Write a SOC analyst report for the a.patel impossible travel incident", mock_emit)
    
    print("\n=== TEST 3: Multimodal Phishing Image ===")
    # Simulate an image upload by passing dummy bytes
    res3 = graph.run("Can you check if anyone visited the domain in this image?", mock_emit, image=b"fake_image_bytes")
    
    print("\n=== ALL TESTS FINISHED ===")
