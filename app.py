import logging
import logging.config
import uvicorn
import requests
from typing import List, Dict, Any
from datetime import datetime

# MCP imports
from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.routing import Mount, Route
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.endpoints import HTTPEndpoint

# Import configuration
from config import settings, logging_config

# Configure logging
logging.config.dictConfig(logging_config)
logger = logging.getLogger(__name__)

# Configure debug mode based on settings
if settings.MCP_DEBUG:
    logger.setLevel(logging.DEBUG)
    logger.debug("DEBUG mode activated")

def log(message: str, level: str = "info"):
    """Helper function for consistent logging."""
    log_func = getattr(logger, level.lower(), logger.info)
    log_func(message)

# Create MCP server
mcp = FastMCP("Azure Pricing MCP")

# ... [mantenha todos os @mcp.tool existentes] ...

# HEALTH CHECK SUPER SIMPLES - responde em texto puro
async def health_check(request):
    """Health check endpoint - retorna texto simples."""
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    message = f"healthy - {now}"
    log("Health check accessed")
    return PlainTextResponse(message)

# ROOT ENDPOINT SIMPLES - retorna HTML básico
async def root(request):
    """Root endpoint - retorna HTML com informações básicas."""
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Azure Pricing MCP Server</title>
        <meta charset="utf-8">
        <style>
            body {{ font-family: Arial, sans-serif; margin: 40px; background: #f5f5f5; }}
            .container {{ background: white; padding: 30px; border-radius: 8px; max-width: 800px; margin: 0 auto; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
            h1 {{ color: #0078d4; }}
            .status {{ color: #107c10; font-weight: bold; font-size: 1.2em; }}
            .info {{ margin: 20px 0; padding: 15px; background: #f0f0f0; border-radius: 4px; }}
            a {{ color: #0078d4; text-decoration: none; }}
            a:hover {{ text-decoration: underline; }}
            .endpoint {{ margin: 10px 0; padding: 10px; background: #e8f4fd; border-left: 3px solid #0078d4; }}
            .timestamp {{ color: #666; font-size: 0.9em; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🚀 Azure Pricing MCP Server</h1>
            <div class="status">✅ Status: Running</div>
            <p class="timestamp">Timestamp: {now}</p>
            
            <div class="info">
                <h2>📡 Available Endpoints:</h2>
                <div class="endpoint">
                    <strong>GET /</strong> - This page (API information)
                </div>
                <div class="endpoint">
                    <strong>GET /health</strong> - Health check endpoint<br>
                    <a href="/health" target="_blank">→ Test health check</a>
                </div>
                <div class="endpoint">
                    <strong>GET /tools</strong> - List available MCP tools (JSON)<br>
                    <a href="/tools" target="_blank">→ View tools</a>
                </div>
                <div class="endpoint">
                    <strong>GET /sse</strong> - Server-Sent Events (MCP protocol)
                </div>
            </div>
            
            <div class="info">
                <h2>📖 About:</h2>
                <p>This is a Model Context Protocol (MCP) server for querying Azure pricing information.</p>
                <p>Use the <strong>/sse</strong> endpoint for MCP client connections.</p>
            </div>
            
            <div class="info">
                <h2>🔧 Quick Test:</h2>
                <p>Click on the links above to test each endpoint, or use:</p>
                <pre style="background: #333; color: #0f0; padding: 10px; border-radius: 4px; overflow-x: auto;">
curl http://localhost:8080/health
curl http://localhost:8080/tools</pre>
            </div>
        </div>
    </body>
    </html>
    """
    return PlainTextResponse(html, media_type="text/html")

# Endpoint to list available tools in the MCP
class ToolsEndpoint(HTTPEndpoint):
    """
    Endpoint to list available tools in the MCP.
    
    This endpoint returns information about all registered tools
    in the MCP, including their names, descriptions, and expected parameters.
    """
    async def get(self, request):
        tools = mcp.list_tools()
        return JSONResponse(tools)

# Create the Starlette application with routes
app = Starlette(routes=[
    Route("/", root),
    Route("/health", health_check),
    Mount("/sse", app=mcp.sse_app()),
    Route("/tools", ToolsEndpoint)
])

# Create the FastAPI application with Model Context Protocol
def get_application():
    """Create and return the Starlette application."""
    return app

if __name__ == "__main__":
    log(f"Starting MCP server at http://{settings.MCP_HOST}:{settings.MCP_PORT}")
    log(f"Root Endpoint: http://{settings.MCP_HOST}:{settings.MCP_PORT}/")
    log(f"Health Check: http://{settings.MCP_HOST}:{settings.MCP_PORT}/health")
    log(f"SSE Endpoint: http://{settings.MCP_HOST}:{settings.MCP_PORT}/sse")
    log(f"Tools Endpoint: http://{settings.MCP_HOST}:{settings.MCP_PORT}/tools")
    log(f"Debug mode: {'ON' if settings.MCP_DEBUG else 'OFF'}")
    log(f"Auto-reload: {'ENABLED' if settings.MCP_RELOAD else 'DISABLED'}")
    
    # Configure uvicorn
    uvicorn_config = {
        "app": "azure_pricing_mcp_server:get_application",
        "host": settings.MCP_HOST,
        "port": settings.MCP_PORT,
        "reload": settings.MCP_RELOAD,
        "log_level": "debug" if settings.MCP_DEBUG else settings.LOG_LEVEL.lower()
    }
    
    logger.debug(f"Uvicorn configuration: {uvicorn_config}")
    
    if settings.MCP_DEBUG:
        logger.debug("DEBUG mode enabled for uvicorn")
    
    uvicorn.run(**uvicorn_config)