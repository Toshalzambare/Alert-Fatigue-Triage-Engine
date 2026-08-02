import os
import re
import json
from langchain_openai import ChatOpenAI
from langchain_core.tools import tool

# 1. Fallback Architecture
def get_llm():
    api_key = os.getenv("GEMMA_API_KEY")
    if api_key:
        return ChatOpenAI(
            model="google/gemma-4-26b-a4b-it:free", # OpenRouter model string for Gemma 4
            openai_api_key=api_key,
            openai_api_base="https://openrouter.ai/api/v1",
            temperature=0.3,
            max_tokens=4096,
        )
    
    # Fallback to local
    return ChatOpenAI(
        model="gemma-4-12b-it",
        openai_api_base=os.getenv("GEMMA_LOCAL_URL", "http://localhost:11434/v1"),
        openai_api_key="not-needed",
        temperature=0.3,
        max_tokens=4096,
    )

# 2. Tool-Call Parser (Regex Fallback)
def parse_tool_calls(response):
    """Extract tool calls from LLM response. Handles structured and prose."""
    calls = []
    
    # 1. Structured Tool Calls (LangChain native)
    if hasattr(response, 'tool_calls') and response.tool_calls:
        for tc in response.tool_calls:
            calls.append({
                "name": tc["name"],
                "args": tc.get("args", {})
            })
        if calls:
            return calls
            
    # 2. Regex fallback for when Gemma narrates calls
    text = response.content if hasattr(response, 'content') else str(response)
    
    # Matches patterns like: search_logs({"query": "failed", ...})
    pattern = r'(\w+)\s*\(\s*({[^}]+})\s*\)'
    matches = re.findall(pattern, text)
    
    for name, args_str in matches:
        try:
            # Fix single quotes to double quotes for JSON parsing if needed
            args_str_fixed = args_str.replace("'", '"')
            args = json.loads(args_str_fixed)
            calls.append({
                "name": name,
                "args": args
            })
        except Exception:
            continue
            
    return calls

# 3. Tool Schemas (Bound to LLM)
@tool
def search_logs(query: str, category: str = None, start: str = "now-24h", end: str = "now", limit: int = 20) -> dict:
    """Search logs via free-text (e.g. IPs, usernames, domains) and filters."""
    pass

@tool
def check_ip(ip: str, window_hours: int = 24) -> dict:
    """Profile an IP's history (total events, countries, targeted users, auth success/fail)."""
    pass

@tool
def get_user_activity(user: str, start: str = "now-24h", end: str = "now") -> dict:
    """Profile a user's recent activity across categories and IPs."""
    pass

@tool
def timeline_around(timestamp: str = None, anchor: str = None, minutes_before: int = 15, minutes_after: int = 15, host: str = None, ip: str = None) -> dict:
    """Get events surrounding a specific time anchor."""
    pass

@tool
def validate_detection_rule(query: str, start: str = "now-48h", end: str = "now") -> dict:
    """Test a Sigma/Elastic query against history for True Positive / False Positive rates."""
    pass

ALL_TOOLS = [search_logs, check_ip, get_user_activity, timeline_around, validate_detection_rule]

def get_bound_llm():
    return get_llm().bind_tools(ALL_TOOLS)
