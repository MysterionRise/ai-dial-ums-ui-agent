import logging
import os
import sys
from contextlib import asynccontextmanager
from typing import Optional

import redis.asyncio as redis
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from starlette.middleware.cors import CORSMiddleware

PROJECT_ROOT = Path(__file__).resolve().parent.parent

from agent.clients.dial_client import DialClient
from agent.clients.http_mcp_client import HttpMCPClient
from agent.clients.stdio_mcp_client import StdioMCPClient
from agent.conversation_manager import ConversationManager
from agent.models.message import Message

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

conversation_manager: Optional[ConversationManager] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize MCP clients, Redis, and ConversationManager on startup"""
    global conversation_manager

    logger.info("Application startup initiated")

    tools = []
    tool_name_client_map: dict[str, HttpMCPClient | StdioMCPClient] = {}

    # UMS MCP (HTTP)
    ums_mcp = await HttpMCPClient.create("http://localhost:8005/mcp")
    ums_tools = await ums_mcp.get_tools()
    tools.extend(ums_tools)
    for t in ums_tools:
        tool_name_client_map[t["function"]["name"]] = ums_mcp

    # Fetch MCP (HTTP)
    fetch_mcp = await HttpMCPClient.create("https://remote.mcpservers.org/fetch/mcp")
    fetch_tools = await fetch_mcp.get_tools()
    tools.extend(fetch_tools)
    for t in fetch_tools:
        tool_name_client_map[t["function"]["name"]] = fetch_mcp

    # DuckDuckGo MCP (Stdio/Docker)
    ddg_mcp = await StdioMCPClient.create("mcp/duckduckgo:latest")
    ddg_tools = await ddg_mcp.get_tools()
    tools.extend(ddg_tools)
    for t in ddg_tools:
        tool_name_client_map[t["function"]["name"]] = ddg_mcp

    # Initialize DialClient
    api_key = os.environ.get("DIAL_API_KEY", "")
    dial_client = DialClient(
        api_key=api_key,
        endpoint="https://ai-proxy.lab.epam.com",
        model="gpt-4o",
        tools=tools,
        tool_name_client_map=tool_name_client_map,
    )

    # Initialize Redis
    redis_client = redis.Redis(host="localhost", port=6379, decode_responses=True)
    await redis_client.ping()
    logger.info("Redis connection established")

    # Initialize ConversationManager
    conversation_manager = ConversationManager(dial_client, redis_client)

    yield


app = FastAPI(
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Request/Response Models
class ChatRequest(BaseModel):
    message: Message
    stream: bool = True


class ChatResponse(BaseModel):
    content: str
    conversation_id: str


class ConversationSummary(BaseModel):
    id: str
    title: str
    created_at: str
    updated_at: str
    message_count: int


class CreateConversationRequest(BaseModel):
    title: str = None


# Endpoints
@app.get("/health")
async def health():
    """Health check endpoint"""
    logger.debug("Health check requested")
    return {
        "status": "healthy",
        "conversation_manager_initialized": conversation_manager is not None
    }


@app.post("/conversations")
async def create_conversation(request: CreateConversationRequest):
    """Create a new conversation"""
    title = request.title or "New Conversation"
    conversation = await conversation_manager.create_conversation(title)
    return conversation


@app.get("/conversations")
async def list_conversations():
    """List all conversations"""
    conversations = await conversation_manager.list_conversations()
    return conversations


@app.get("/conversations/{conversation_id}")
async def get_conversation(conversation_id: str):
    """Get a specific conversation"""
    conversation = await conversation_manager.get_conversation(conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


@app.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str):
    """Delete a conversation"""
    deleted = await conversation_manager.delete_conversation(conversation_id)
    if deleted:
        return {"message": f"Conversation {conversation_id} deleted successfully"}
    raise HTTPException(status_code=404, detail="Conversation not found")


@app.post("/conversations/{conversation_id}/chat")
async def chat(conversation_id: str, request: ChatRequest):
    """Chat endpoint that processes messages and returns assistant response"""
    try:
        result = await conversation_manager.chat(request.message, conversation_id, request.stream)
        if request.stream:
            return StreamingResponse(result, media_type="text/event-stream")
        else:
            return ChatResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/")
async def serve_index():
    """Serve the chat UI"""
    return FileResponse(PROJECT_ROOT / "index.html")


if __name__ == "__main__":
    import uvicorn
    logger.info("Starting UMS Agent server")
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8011,
        log_level="debug",
    )
