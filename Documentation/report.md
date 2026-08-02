# Autonomous Security Agent - Setup & Debug Report

## 1. Project Overview
This project targets the **Autonomous Security Agent Track**. The goal is to build a local, agentic workflow using Gemma 4 that acts as a natural language interface for security logs. The agent uses the **Model Context Protocol (MCP)** to autonomously query an Elastic database, analyze payloads, and return reasoned threat assessments.

## 2. Infrastructure Setup
To ensure a robust development environment, we established a dual-database strategy:
*   **Primary (Production):** Elastic Cloud (Managed cluster)
*   **Backup (Local Dev):** Docker-based Elasticsearch container

### Local Docker Backup Architecture
We configured a single-node Elasticsearch instance using Docker Compose:
*   **Image:** `docker.elastic.co/elasticsearch/elasticsearch:8.14.0`
*   **Security:** X-Pack security disabled for rapid local prototyping (`xpack.security.enabled=false`).
*   **Ports:** `9200`

## 3. Connection Issue & Resolution (Important Debug Log)

During the initial testing of the local Docker container using the Python `elasticsearch` client, we encountered a connection timeout issue.

**The Symptoms:**
*   The Docker container (`elasticsearch_hackathon`) started successfully and the logs indicated the server was healthy and listening on port 9200.
*   However, the Python test script (`test_elastic.py`) timed out and threw a connection error when attempting to ping the database using `es.ping()` and `es.info()`.

**The Root Cause:**
The initial connection string was set to `http://localhost:9200`. On Windows machines, Python's underlying networking libraries (like `urllib3` used by the Elasticsearch client) often resolve `localhost` to the IPv6 loopback address (`::1`). Docker Desktop, however, maps the published ports to the IPv4 loopback interface (`127.0.0.1`). Because the Python script was sending requests to the IPv6 address, the connection hung and eventually timed out.

Additionally, `es.ping()` silently returns `False` on failure without raising an exception, which temporarily obscured the root cause until we switched to `es.info()` to force the exception stack trace.

**The Fix:**
We updated the connection string in the Python client to explicitly enforce IPv4 routing:
```diff
- es = Elasticsearch("http://localhost:9200")
+ es = Elasticsearch("http://127.0.0.1:9200")
```
After this minor networking change, the Python client successfully connected, indexed a mock malicious SSH log, searched it, and deleted it.

## 4. Next Steps: Cloud Integration & MCP Server
With the database foundation proven locally, the next phase involves:
1.  Deploying an **Elastic Cloud** cluster to serve as the production backend for the hackathon demo.
2.  Finalizing the `mcp_server.py` script to expose three core tools to the Gemma 4 agent:
    *   `search_security_logs`
    *   `get_ip_reputation`
    *   `block_malicious_ip`
