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
    
    print("\n=== TEST 5: Audio Processing ===")
    with open("test_audio.mp3", "rb") as f:
        audio_bytes = f.read()
    res5 = graph.run("Analyze this audio recording", mock_emit, audio=audio_bytes)
    
    print("\n=== ALL TESTS FINISHED ===")
