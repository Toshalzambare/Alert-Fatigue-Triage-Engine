# Autonomous Security Agent - Mock Data Schema

This document outlines the Elastic Common Schema (ECS) design used to generate hyper-realistic dummy data for the Gemma 4 Agent hackathon project.

## Core Objective
To make the advanced AI features (Vision UI Hunter, Autonomous Hopping, Sigma Rule Forge) work seamlessly, the database simulates **three different log sources**. By standardizing them using ECS, the AI agent can instantly pivot across different datasets.

---

## 1. Identity & Access Logs (Simulating Okta / Entra ID)
**Purpose:** Triggers the "Self-Healing Search" and "Verify MFA" tool.

### Core Columns:
*   `@timestamp`: Microsecond precision ISO 8601.
*   `event.dataset`: Always `"okta.system"`.
*   `event.action`: e.g., `"user.session.start"`, `"user.mfa.challenge"`.
*   `event.outcome`: `"success"` or `"failure"`.
*   `user.name`: The target username (Contains intentional variations like `j_smith` and `john.smith` to test self-healing).
*   `source.ip`: The IP attempting the login.
*   `user_agent.original`: What browser/device they are using.

---

## 2. Web Proxy / Network Logs (Simulating Palo Alto / Zscaler)
**Purpose:** Triggers the "Multimodal Phishing (Vision)" feature.

### Core Columns:
*   `@timestamp`: Microsecond precision ISO 8601.
*   `event.dataset`: Always `"panw.traffic"`.
*   `event.action`: `"network_flow"`.
*   `source.ip`: Internal employee IP.
*   `url.domain`: e.g., `"microsoft-secure-login-update.com"` (Domain extracted by Vision model).
*   `url.full`: The exact phishing URL clicked.
*   `http.response.status_code`: e.g., `200` (meaning the employee successfully loaded the phishing site).

---

## 3. Endpoint Process Logs (Simulating CrowdStrike / Sysmon)
**Purpose:** Triggers "Time-Travel", "Hopping", and "Sigma Rule Forge".

### Core Columns:
*   `@timestamp`: Microsecond precision ISO 8601.
*   `event.dataset`: Always `"windows.sysmon"`.
*   `event.code`: Windows Event ID (e.g., `"1"` for Process Creation, `"3"` for Network Connection).
*   `process.name`: The executed file (e.g., `"powershell.exe"`).
*   `process.command_line`: The malicious payload.
*   `process.parent.name`: e.g., `"excel.exe"` (Showing the malware came from a phishing document).

---

## Example Log Payloads

These examples demonstrate how the data looks in Elasticsearch, sharing common fields (like `source.ip` and `user.name`) so the agent can autonomously "hop" between them.

### Log 1: The Phishing Click (Proxy Log)
```json
{
  "@timestamp": "2026-08-01T09:14:02.105Z",
  "event": {
    "dataset": "panw.traffic",
    "action": "network_flow",
    "outcome": "success"
  },
  "user": {
    "name": "john.smith"
  },
  "source": {
    "ip": "10.0.0.45"
  },
  "url": {
    "domain": "microsoft-secure-update.com",
    "full": "https://microsoft-secure-update.com/login?token=abc12345"
  },
  "http": {
    "response": {
      "status_code": 200
    }
  }
}
```

### Log 2: The Malicious Script Execution (Endpoint Log)
*Happens exactly 3 minutes after the click, enabling the "Time-Travel" feature.*
```json
{
  "@timestamp": "2026-08-01T09:17:45.882Z",
  "event": {
    "dataset": "windows.sysmon",
    "code": "1",
    "action": "ProcessCreate"
  },
  "host": {
    "ip": "10.0.0.45" 
  },
  "process": {
    "name": "powershell.exe",
    "command_line": "powershell.exe -NoProfile -WindowStyle Hidden -EncodedCommand JABzAD0ATg...",
    "parent": {
      "name": "winword.exe"
    }
  }
}
```

## How the Agent Exploits This Schema
1.  **Vision Feature:** The user uploads a screenshot of the fake Microsoft email. Gemma 4 reads the image, extracts `"microsoft-secure-update.com"`.
2.  **MCP Search:** It runs `search_proxy_clicks(domain="microsoft-secure-update.com")` and retrieves **Log 1**.
3.  **Follow-Up Hopping:** The agent sees the victim is `10.0.0.45`. It autonomously runs `search_endpoint_activity(ip="10.0.0.45")`.
4.  **Sigma Forge:** It retrieves **Log 2**, identifying `winword.exe` spawning `powershell.exe -WindowStyle Hidden`. It instantly generates a Sigma rule to detect that exact behavior globally!
