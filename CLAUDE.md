# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Python-based AI Agent for User Management with MCP (Model Context Protocol) tool integration. The agent uses a FastAPI backend with streaming SSE support, connects to three MCP servers for tools, persists conversations in Redis, and is served through a vanilla JS chat UI (`index.html`).

## Development Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Start infrastructure (UMS service, MCP server, Redis, Redis Insight)
docker-compose up

# Run the application (port 8011)
python -m agent.app

# Open chat UI
open index.html
```

There is no test framework configured. Manual testing via browser UI or Postman. No linting/formatting tools are configured.

## Architecture

### Request Flow

User → FastAPI (`agent/app.py`) → `ConversationManager` → `DialClient` (AI model + tool loop) → MCP clients → back through chain with streaming/non-streaming response → Redis persistence.

### Key Components

- **`agent/app.py`** — FastAPI app with lifespan startup (initializes all clients), CORS middleware, REST endpoints for conversation CRUD and chat (streaming via SSE).
- **`agent/conversation_manager.py`** — Orchestrates conversations: creates/lists/gets/deletes via Redis, delegates AI calls to `DialClient`, saves message history. Uses Redis sorted sets (`conversations:list`) for ordering and string keys (`conversation:{id}`) for conversation data.
- **`agent/clients/dial_client.py`** — Wraps `AsyncAzureOpenAI` for chat completions with recursive tool-calling loop. Handles both streaming (delta chunk assembly) and non-streaming flows. Maps tool names to MCP clients via `tool_name_client_map`.
- **`agent/clients/http_mcp_client.py`** — MCP client using `streamablehttp_client` transport. Connects to HTTP-based MCP servers (UMS MCP at `localhost:8005/mcp`, Fetch MCP at `remote.mcpservers.org`). Converts MCP tool schemas to OpenAI-compatible format.
- **`agent/clients/stdio_mcp_client.py`** — MCP client using Docker stdio transport (`docker run --rm -i`). Used for DuckDuckGo search (`mcp/duckduckgo:latest`). Same tool schema conversion as HTTP client.
- **`agent/models/message.py`** — Pydantic `Message` model with roles (SYSTEM, USER, ASSISTANT, TOOL) and optional tool_calls/tool_call_id fields. Has `to_dict()` for serialization.
- **`agent/prompts.py`** — System prompt defining the agent's behavior for user management tasks.
- **`index.html`** — Single-file frontend with conversation sidebar, chat area, and SSE streaming display.

### MCP Servers (3 total, started via docker-compose or remote)

| Server | Transport | URL / Image | Purpose |
|---|---|---|---|
| UMS MCP | HTTP | `http://localhost:8005/mcp` | User management (CRUD on mock user service) |
| Fetch MCP | HTTP | `https://remote.mcpservers.org/fetch/mcp` | Web content fetching |
| DuckDuckGo | Stdio/Docker | `mcp/duckduckgo:latest` | Web search |

### Infrastructure (docker-compose.yml)

- **userservice** (port 8041) — Mock user service with 1000 generated users
- **ums-mcp-server** (port 8005) — MCP server wrapping the user service
- **redis-ums** (port 6379) — Conversation persistence (2GB, LRU eviction, AOF+RDB)
- **redis-insight** (port 6380) — Redis UI (connect to `redis-ums:6379`)

### AI Model

Uses DIAL proxy (`https://ai-proxy.lab.epam.com`) with Azure OpenAI-compatible API. Models: `gpt-4o` or `claude-3-7-sonnet@20250219`. API key loaded from `.env` (`DIAL_API_KEY`). Requires EPAM VPN.

## Key Patterns

- All MCP clients use async factory pattern (`await Client.create(...)`) for initialization
- Tool calling uses a recursive loop: model response → extract tool_calls → execute via MCP → feed results back → repeat until no more tool_calls
- Streaming uses SSE format (`data: {json}\n\n`) with OpenAI-compatible chunk structure and `[DONE]` terminator
- MCP tools must be converted from Anthropic/MCP schema to OpenAI function-calling format before passing to DIAL
- Conversation state is always persisted to Redis after each chat interaction
