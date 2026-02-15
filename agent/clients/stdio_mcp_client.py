import logging
from typing import Optional, Any

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.types import CallToolResult, TextContent

logger = logging.getLogger(__name__)


class StdioMCPClient:
    """Handles MCP server connection and tool execution via stdio"""

    def __init__(self, docker_image: str) -> None:
        self.docker_image = docker_image
        self.session: Optional[ClientSession] = None
        self._stdio_context = None
        self._session_context = None
        logger.debug("StdioMCPClient instance created", extra={"docker_image": docker_image})

    @classmethod
    async def create(cls, docker_image: str) -> 'StdioMCPClient':
        """Async factory method to create and connect MCPClient"""
        instance = cls(docker_image)
        await instance.connect()
        return instance

    async def connect(self):
        """Connect to MCP server via Docker"""
        server_params = StdioServerParameters(
            command="docker",
            args=["run", "--rm", "-i", self.docker_image],
        )
        self._stdio_context = stdio_client(server_params)
        read_stream, write_stream = await self._stdio_context.__aenter__()
        self._session_context = ClientSession(read_stream, write_stream)
        self.session = await self._session_context.__aenter__()
        init_result = await self.session.initialize()
        logger.info("StdioMCPClient connected to %s, capabilities: %s", self.docker_image, init_result)

    async def get_tools(self) -> list[dict[str, Any]]:
        """Get available tools from MCP server"""
        if not self.session:
            raise RuntimeError("MCP client is not connected to MCP server")

        tools_result = await self.session.list_tools()
        tools = []
        for tool in tools_result.tools:
            tools.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description or "",
                    "parameters": tool.inputSchema if tool.inputSchema else {"type": "object", "properties": {}},
                },
            })

        logger.info("Retrieved %d tools from %s: %s", len(tools), self.docker_image,
                     [t["function"]["name"] for t in tools])
        return tools

    async def call_tool(self, tool_name: str, tool_args: dict[str, Any]) -> Any:
        """Call a specific tool on the MCP server"""
        if not self.session:
            raise RuntimeError("MCP client is not connected to MCP server")

        logger.info("Calling tool '%s' on %s with args: %s", tool_name, self.docker_image, tool_args)
        result: CallToolResult = await self.session.call_tool(tool_name, tool_args)
        content = result.content
        if content and len(content) > 0:
            first = content[0]
            if isinstance(first, TextContent):
                return first.text
        return content
