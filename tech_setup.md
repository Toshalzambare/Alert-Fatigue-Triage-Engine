# Technology Stack & Setup Guide

This document outlines the complete technology stack and installation commands required to run the Autonomous Security Agent hackathon project.

## 1. Project Tech Stack

### 🖥️ Frontend (`/ui`)
*   **Framework:** React
*   **Build Tool:** Vite
*   **Languages:** JavaScript / JSX (or TypeScript)
*   **Purpose:** Two-pane UI rendering the Analyst Chat and Agent Reasoning trace.

### 🧠 Backend Agent (`/agent`)
*   **Framework:** Flask (Python)
*   **Orchestration:** LangGraph & LangChain
*   **Model:** Gemma 4
*   **Purpose:** Translates intent, plans tool calls, handles time-travel logic, and synthesizes reports. Connects to `/mcp` via MCP Client.

### 🔧 MCP Server (`/mcp`)
*   **Framework:** FastMCP
*   **Purpose:** Exposes 5 strict tools (`search_logs`, `check_ip`, etc.) to the Agent over the Model Context Protocol.

### 💾 Database & Mock Data (`/data`)
*   **Database:** Elastic Cloud Serverless
*   **Client:** `elasticsearch` Python package
*   **Purpose:** Houses the ECS-formatted security narratives and provides script pipelines to inject mock data.

---

## 2. Global Setup Instructions

### Prerequisites
- Python 3.10+
- Node.js 18+ & npm
- An Elastic Cloud Serverless account

### Environment Variables
1. Copy the example `.env` file to your active environment.
   ```bash
   cp eg.env .env
   ```
2. Fill in your `ELASTIC_URL` and `ELASTIC_API_KEY` from Elastic Cloud.

### Python Backend & MCP Setup (Root Folder)
Install all Python dependencies for the `/agent`, `/mcp`, and `/data` folders.

```bash
# 1. (Optional but recommended) Create a virtual environment
python -m venv venv
venv\Scripts\activate  # Windows
# source venv/bin/activate # Mac/Linux

# 2. Install requirements
pip install -r requirements.txt
```

### Frontend Setup (`/ui` folder)
Initialize and install the React environment.

```bash
# 1. Move into the UI folder
cd ui

# 2. Install dependencies
npm install

# 3. Start the Vite development server
npm run dev
```

---

## 3. Running the Stack (Development)

To test the full stack, you will need three terminal windows running simultaneously:

**Terminal 1: Start the MCP Server**
```bash
python mcp/server.py
```

**Terminal 2: Start the Flask Backend (Agent)**
```bash
python agent/app.py
```

**Terminal 3: Start the React Frontend**
```bash
cd ui
npm run dev
```

*(Note: Prior to running the stack, you must populate your Elastic database by running `python data/generate.py` once).*
