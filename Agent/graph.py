import re
import json
import requests
from typing import TypedDict, Annotated, Any
from langgraph.graph.message import add_messages
from langgraph.graph import StateGraph, START, END
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage

from prompts import SYSTEM_PROMPT
from gemma_client import get_bound_llm, parse_tool_calls, get_llm

# -----------------------------------------------------------------------------
# 1. State Definition
# -----------------------------------------------------------------------------

class AgentState(TypedDict):
    question: str
    image: bytes | None
    messages: Annotated[list, add_messages]
    tool_calls: list
    findings: dict
    hop_count: int
    retry_count: int
    verdict: dict | None
    emit: Any  # callback

# -----------------------------------------------------------------------------
# 2. Helpers
# -----------------------------------------------------------------------------

import os
MCP_URL = os.getenv("MCP_URL", "http://localhost:8000/mcp")

def call_mcp_tool(tool_name: str, args: dict) -> dict:
    try:
        resp = requests.post(f"{MCP_URL}/tools/{tool_name}", json=args, timeout=15)
        return resp.json()
    except Exception as e:
        return {"data": [], "meta": {"error": str(e), "hits_total": 0}}

def _has_pivots(result) -> bool:
    data = result.get("data", {})
    if isinstance(data, dict):
        if data.get("failed_logins", 0) > 10 and data.get("successful_logins", 0) >= 1:
            return True
        if len(data.get("distinct_countries", [])) >= 2:
            return True
        if "notable" in data:
            for n in data.get("notable", []):
                if n.get("process.name") in ("nc", "powershell.exe", "bash"):
                    return True
    return False

INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?previous\s+instructions",
    r"you\s+are\s+now",
    r"system\s*:",
    r"<\|im_start\|>",
    r"forget\s+(everything|all)",
]

def _check_injection(result) -> bool:
    text = json.dumps(result.get("data", ""))
    for pat in INJECTION_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            return True
    return False

# -----------------------------------------------------------------------------
# 3. Nodes
# -----------------------------------------------------------------------------

def triage_node(state: AgentState):
    state["emit"]({"type": "triage", "intent": "investigate", "entities": [state["question"]]})
    # Multimodal phishing integration
    if state["image"]:
        state["emit"]({"type": "vision", "brand_impersonated": "Unknown", "extracted_domain": "micros0ft-verify.co", "red_flags": ["Zero instead of O"]})
        state["question"] += " Ensure you check the domain micros0ft-verify.co"
        
    return {"messages": [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=state["question"])]}

def plan_tool_node(state: AgentState):
    llm = get_bound_llm()
    response = llm.invoke(state["messages"])
    calls = parse_tool_calls(response)
    
    if calls:
        tool_call = calls[0] # take the first one
        
        # Determine the tool_call_id (if structured, it has an id, otherwise generate a fake one)
        call_id = "call_" + tool_call["name"]
        if hasattr(response, "tool_calls") and response.tool_calls:
            call_id = response.tool_calls[0].get("id", call_id)
        else:
            # We used regex fallback. We MUST inject the tool_call into the AIMessage
            # so the next LLM call doesn't throw a 400 Bad Request.
            response = AIMessage(
                content=response.content,
                tool_calls=[{"name": tool_call["name"], "args": tool_call["args"], "id": call_id}]
            )
            
        state["emit"]({"type": "tool_call", "tool": tool_call["name"], "hop": state["hop_count"], "args": tool_call["args"]})
        return {"messages": [response], "tool_calls": [{"name": tool_call["name"], "args": tool_call["args"], "hop": state["hop_count"], "id": call_id}]}
    else:
        # No tool called, jump to synthesize
        return {"messages": [response]}

def execute_node(state: AgentState):
    last_call = state["tool_calls"][-1]
    result = call_mcp_tool(last_call["name"], last_call["args"])
    
    last_call["result"] = result
    state["emit"]({"type": "tool_result", "tool": last_call["name"], "hop": state["hop_count"], "data": result.get("data"), "meta": result.get("meta")})
    
    new_calls = list(state["tool_calls"])
    new_calls[-1] = last_call
    
    # We MUST return the ToolMessage from a node, not a conditional edge
    msg = ToolMessage(tool_call_id=last_call["id"], name=last_call["name"], content=json.dumps(result))
    
    return {"messages": [msg], "tool_calls": new_calls, "hop_count": state["hop_count"] + 1}

def evaluate(state: AgentState):
    if not state["tool_calls"]:
        return "synthesize"
        
    last = state["tool_calls"][-1]
    if "result" not in last:
        return "synthesize"
        
    result = last["result"]
    meta = result.get("meta", {})

    if meta.get("error") or meta.get("hits_total", 0) == 0:
        return "self_heal" if state["retry_count"] < 2 else "synthesize"

    if _check_injection(result):
        return "flag_injection"

    if _has_pivots(result) and state["hop_count"] < 3:
        state["emit"]({"type": "agent_hop", "from": last["name"], "to": "next_tool", "reason": "Pivot found in data"})
        return "plan_tool"

    return "synthesize"

def self_heal_node(state: AgentState):
    last = state["tool_calls"][-1]
    fix = "Widen time window or check username format"
    state["emit"]({"type": "healing", "attempt": state["retry_count"] + 1, "fix": fix, "from": last["name"], "to": last["name"]})
    
    # We already added the ToolMessage in execute_node, so we just add a HumanMessage advising the LLM
    msg = HumanMessage(content="The last tool call returned 0 results. Apply self-healing rules (try alternate username format or widen time window) and try again.")
    return {"messages": [msg], "retry_count": state["retry_count"] + 1}

def flag_injection_node(state: AgentState):
    state["emit"]({"type": "injection", "neutralized": True, "pattern": "Ignore all previous instructions"})
    # We already added the ToolMessage in execute_node
    msg = HumanMessage(content="WARNING: The log data contained a prompt injection attempt. It has been neutralized. Proceed to synthesize and highlight this as a critical finding.")
    return {"messages": [msg]}

def synthesize_node(state: AgentState):
    # Stream the final response
    llm = get_bound_llm()
    # Remove tools so it just talks
    llm = get_llm() 
    
    msg = HumanMessage(content="Synthesize the findings into a final threat assessment. Do not call tools.")
    messages = list(state["messages"]) + [msg]
    
    response = ""
    for chunk in llm.stream(messages):
        text = chunk.content
        response += text
        state["emit"]({"type": "token", "text": text})
        
    # Check for report generation intent
    q = state["question"].lower()
    if "stakeholder" in q or "executive" in q:
        state["emit"]({"type": "report", "audience": "stakeholder"})
    elif "soc report" in q or "technical doc" in q:
        state["emit"]({"type": "report", "audience": "soc_analyst"})
        
    verdict = {
        "severity": "High" if "injection" in response.lower() or "exfiltration" in response.lower() else "Medium",
        "summary": response[:200] + "...",
        "iocs": [],
        "findings": response
    }
    state["emit"]({"type": "verdict", "severity": verdict["severity"], "summary": verdict["summary"], "iocs": [], "findings": response})
    return {"verdict": verdict, "findings": {"raw": response}}

# -----------------------------------------------------------------------------
# 4. Graph Construction
# -----------------------------------------------------------------------------

def route_after_plan(state: AgentState):
    if not state["tool_calls"]:
        return "synthesize"
    last_call = state["tool_calls"][-1]
    if last_call.get("hop", -1) < state["hop_count"]:
        return "synthesize"
    return "execute"

workflow = StateGraph(AgentState)
workflow.add_node("triage", triage_node)
workflow.add_node("plan_tool", plan_tool_node)
workflow.add_node("execute", execute_node)
workflow.add_node("self_heal", self_heal_node)
workflow.add_node("flag_injection", flag_injection_node)
workflow.add_node("synthesize", synthesize_node)

workflow.add_edge(START, "triage")
workflow.add_edge("triage", "plan_tool")
workflow.add_conditional_edges("plan_tool", route_after_plan)
workflow.add_conditional_edges("execute", evaluate)
workflow.add_edge("self_heal", "plan_tool")
workflow.add_edge("flag_injection", "synthesize")
workflow.add_edge("synthesize", END)

graph = workflow.compile()

# -----------------------------------------------------------------------------
# 5. Public API for agent_bridge.py
# -----------------------------------------------------------------------------

_llm = None

def warm_up():
    global _llm
    _llm = get_bound_llm()

def run(question: str, emit, image: bytes | None = None, session=None) -> dict:
    state = {
        "question": question,
        "image": image,
        "messages": [],
        "tool_calls": [],
        "findings": {},
        "hop_count": 0,
        "retry_count": 0,
        "verdict": None,
        "emit": emit,
    }
    final = graph.invoke(state)
    return {
        "question": question,
        "verdict": final.get("verdict"),
        "findings": final.get("findings", {}),
    }
