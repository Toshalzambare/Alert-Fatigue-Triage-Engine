"""
Test script: Verify Gemma 4 27B access via OpenRouter API
Uses GEMMA_API_KEY from .env file
Model: google/gemma-3-27b-it (Gemma 4 27B)
"""

import os
import sys
import json
import requests
from dotenv import load_dotenv

# Force UTF-8 output on Windows terminals
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Load .env from project root (one level up from /test)
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

OPENROUTER_API_KEY = os.getenv("GEMMA_API_KEY")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
MODEL = "google/gemma-4-26b-a4b-it:free"  # Gemma 4 27B on OpenRouter


def check_api_key():
    """Verify that the API key is loaded."""
    if not OPENROUTER_API_KEY:
        print("[FAIL] GEMMA_API_KEY not found in environment / .env file.")
        sys.exit(1)
    masked = OPENROUTER_API_KEY[:10] + "..." + OPENROUTER_API_KEY[-4:]
    print(f"[OK]   API Key loaded: {masked}")


def test_simple_completion():
    """Send a simple prompt and check the response."""
    print(f"\n[...] Testing model: {MODEL}")
    print("   Sending prompt: 'What is 2 + 2? Answer in one sentence.'\n")

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost",       # required by OpenRouter
        "X-Title": "Alert Fatigue Triage Engine",  # optional app name
    }

    payload = {
        "model": MODEL,
        "messages": [
            {
                "role": "user",
                "content": "What is 2 + 2? Answer in one sentence."
            }
        ],
        "max_tokens": 64,
        "temperature": 0.1,
    }

    try:
        response = requests.post(
            f"{OPENROUTER_BASE_URL}/chat/completions",
            headers=headers,
            json=payload,
            timeout=30,
        )

        if response.status_code == 200:
            data = response.json()
            content = data["choices"][0]["message"]["content"].strip()
            usage = data.get("usage", {})
            print(f"[OK]   SUCCESS -- HTTP 200")
            print(f"   Model response : {content}")
            print(f"   Prompt tokens  : {usage.get('prompt_tokens', 'N/A')}")
            print(f"   Output tokens  : {usage.get('completion_tokens', 'N/A')}")
            print(f"   Total tokens   : {usage.get('total_tokens', 'N/A')}")
            return True
        else:
            print(f"[FAIL] FAILED -- HTTP {response.status_code}")
            print(f"   Response body  : {response.text[:500]}")
            return False

    except requests.exceptions.Timeout:
        print("[FAIL] Request timed out (30 s). Check your network or OpenRouter status.")
        return False
    except requests.exceptions.ConnectionError as e:
        print(f"[FAIL] Connection error: {e}")
        return False
    except Exception as e:
        print(f"[FAIL] Unexpected error: {e}")
        return False


def test_model_list():
    """Optional: confirm the model is listed as available on OpenRouter."""
    print(f"\n[...] Checking model availability on OpenRouter...")

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
    }

    try:
        response = requests.get(
            f"{OPENROUTER_BASE_URL}/models",
            headers=headers,
            timeout=15,
        )

        if response.status_code == 200:
            models = response.json().get("data", [])
            ids = [m["id"] for m in models]
            if MODEL in ids:
                print(f"[OK]   Model '{MODEL}' is available on OpenRouter.")
            else:
                # Search for partial match
                gemma_models = [m for m in ids if "gemma" in m.lower()]
                print(f"[WARN] Model '{MODEL}' not found exactly. Available Gemma models:")
                for gm in gemma_models:
                    print(f"       - {gm}")
        else:
            print(f"[WARN] Could not fetch model list (HTTP {response.status_code})")

    except Exception as e:
        print(f"[WARN] Model list check failed: {e}")


if __name__ == "__main__":
    print("=" * 60)
    print("  Gemma 4 27B — OpenRouter API Test")
    print("=" * 60)

    check_api_key()
    test_model_list()
    ok = test_simple_completion()

    print("\n" + "=" * 60)
    if ok:
        print("All tests passed! The model is accessible and working.")
    else:
        print("Test FAILED. Check the errors above.")
    print("=" * 60)
