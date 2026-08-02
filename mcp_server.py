from typing import Any
import json

# Note: You will need to install the 'mcp' python package
# pip install mcp
from fastmcp import FastMCP
from elasticsearch import Elasticsearch

import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Create the MCP Server instance
app = FastMCP("security-agent-mcp")

# Initialize Elasticsearch with Cloud credentials
es = Elasticsearch(
    os.getenv("ELASTIC_URL"),
    api_key=os.getenv("ELASTIC_API_KEY")
)

@app.tool()
async def search_security_logs(query: str, timeframe: str = "now-24h") -> str:
    """
    Search the Elastic database for security logs.
    Use this tool when the user asks to find malicious IPs, suspicious activity, or specific logs.
    """
    print(f"[MCP TOOL CALLED] Searching logs with query: {query} for timeframe: {timeframe}")
    
    # Mock response for now until DB is hooked up
    mock_results = [
        {"timestamp": "2026-08-01T12:00:00Z", "ip": "192.168.1.105", "action": "failed_login", "count": 500},
        {"timestamp": "2026-08-01T12:05:00Z", "ip": "10.0.0.5", "action": "port_scan", "count": 120}
    ]
    return json.dumps(mock_results, indent=2)


@app.tool()
async def get_ip_reputation(ip_address: str) -> str:
    """
    Check the reputation of an IP address against known threat intelligence databases.
    Use this tool when you find a suspicious IP in the logs and need to verify if it is malicious.
    """
    print(f"[MCP TOOL CALLED] Checking reputation for IP: {ip_address}")
    
    # Simple mock logic
    if ip_address == "192.168.1.105":
        return json.dumps({"ip": ip_address, "status": "MALICIOUS", "confidence": "99%", "threat_type": "SSH_Bruteforce_Node"})
    return json.dumps({"ip": ip_address, "status": "CLEAN"})


@app.tool()
async def block_malicious_ip(ip_address: str) -> str:
    """
    Block an IP address at the firewall level.
    ONLY use this tool if the user explicitly asks you to block or remediate the threat.
    """
    print(f"!!! [FIREWALL ACTION] !!! Blocking IP: {ip_address}")
    return f"SUCCESS: IP {ip_address} has been successfully blocked on the firewall."


if __name__ == "__main__":
    print("Starting Security Agent MCP Server...")
    # FastMCP handles stdio automatically
    app.run()
