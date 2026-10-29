# -*- coding: utf-8 -*-
"""
Model Context Protocol (MCP) Streamable HTTP / SSE Engine.
Complies with MCP Specification 2024-11-05.
Supports:
  - SSE transport (GET /sse -> event: endpoint, POST /message -> JSON-RPC)
  - Direct HTTP transport (POST / -> JSON-RPC 2.0 response)
  - Standard methods: initialize, notifications/initialized, tools/list, tools/call, ping
"""

import json
import uuid
import queue
import time
import logging
from typing import Dict, Any, Callable, List, Optional
from flask import Blueprint, request, Response, jsonify

logger = logging.getLogger("mcp")


class MCPTool:
    def __init__(self, name: str, description: str, input_schema: Dict[str, Any], handler: Callable):
        self.name = name
        self.description = description
        self.input_schema = input_schema
        self.handler = handler

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
        }


class MCPServer:
    def __init__(self, name: str, version: str = "1.0.0", description: str = ""):
        self.name = name
        self.version = version
        self.description = description
        self.tools: Dict[str, MCPTool] = {}
        # Active SSE client queues: session_id -> queue.Queue
        self.sessions: Dict[str, queue.Queue] = {}

    def register_tool(self, name: str, description: str, input_schema: Dict[str, Any]):
        def decorator(fn: Callable):
            self.tools[name] = MCPTool(name, description, input_schema, fn)
            return fn
        return decorator

    def handle_jsonrpc(self, req: Dict[str, Any], session_context: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        req_id = req.get("id")
        method = req.get("method")
        params = req.get("params") or {}

        if not method:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32600, "message": "Invalid Request: missing method"}
            }

        logger.info(f"[{self.name}] JSON-RPC method={method} id={req_id}")

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {
                        "tools": {"listChanged": False}
                    },
                    "serverInfo": {
                        "name": self.name,
                        "version": self.version,
                        "description": self.description
                    }
                }
            }

        elif method in ("notifications/initialized", "initialized"):
            # Notifications do not have a response
            return None

        elif method == "ping":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {}
            }

        elif method == "tools/list":
            tools_list = [tool.to_dict() for tool in self.tools.values()]
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "tools": tools_list
                }
            }

        elif method == "tools/call":
            tool_name = params.get("name")
            arguments = params.get("arguments") or {}

            if tool_name not in self.tools:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {
                        "code": -32601,
                        "message": f"Tool '{tool_name}' not found on server '{self.name}'"
                    }
                }

            tool = self.tools[tool_name]
            try:
                # Execute tool handler
                output = tool.handler(arguments, context=session_context)
                if isinstance(output, dict) or isinstance(output, list):
                    text_content = json.dumps(output, ensure_ascii=False, indent=2, default=str)
                else:
                    text_content = str(output)

                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": text_content
                            }
                        ],
                        "isError": False
                    }
                }
            except Exception as e:
                logger.exception(f"Error executing tool {tool_name}: {e}")
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": f"Error executing {tool_name}: {str(e)}"
                            }
                        ],
                        "isError": True
                    }
                }

        else:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {
                    "code": -32601,
                    "message": f"Method '{method}' not implemented"
                }
            }

    def create_blueprint(self, url_prefix: str, auth_validator: Optional[Callable] = None) -> Blueprint:
        bp_name = f"mcp_{self.name.replace('-', '_')}"
        bp = Blueprint(bp_name, __name__, url_prefix=url_prefix)

        @bp.route("", methods=["GET", "POST", "OPTIONS"])
        @bp.route("/", methods=["GET", "POST", "OPTIONS"])
        def root_handler():
            if request.method == "OPTIONS":
                return self._cors_response(Response(status=204))

            # If client requests SSE stream at root
            if request.method == "GET":
                accept = request.headers.get("Accept", "")
                if "text/event-stream" in accept:
                    return self._handle_sse_connect(url_prefix)
                # Otherwise return JSON server info
                return jsonify({
                    "status": "online",
                    "server": self.name,
                    "version": self.version,
                    "description": self.description,
                    "transport": "streamable-http",
                    "endpoints": {
                        "sse": f"{url_prefix}/sse",
                        "message": f"{url_prefix}/message",
                        "direct": url_prefix
                    },
                    "tools_count": len(self.tools)
                })

            # Direct JSON-RPC POST
            auth_ctx = auth_validator(request) if auth_validator else {}
            if auth_ctx is False or (isinstance(auth_ctx, dict) and auth_ctx.get("error")):
                err_msg = auth_ctx.get("error") if isinstance(auth_ctx, dict) else "Unauthorized"
                return jsonify({"jsonrpc": "2.0", "id": None, "error": {"code": -32000, "message": err_msg}}), 401

            body = request.get_json(silent=True) or {}
            resp = self.handle_jsonrpc(body, session_context=auth_ctx)
            if resp is None:
                return Response(status=204)
            return self._cors_response(jsonify(resp))

        @bp.route("/sse", methods=["GET"])
        def sse_handler():
            return self._handle_sse_connect(url_prefix)

        @bp.route("/message", methods=["POST", "OPTIONS"])
        def message_handler():
            if request.method == "OPTIONS":
                return self._cors_response(Response(status=204))

            session_id = request.args.get("sessionId")
            auth_ctx = auth_validator(request) if auth_validator else {}
            if auth_ctx is False or (isinstance(auth_ctx, dict) and auth_ctx.get("error")):
                err_msg = auth_ctx.get("error") if isinstance(auth_ctx, dict) else "Unauthorized"
                return jsonify({"jsonrpc": "2.0", "id": None, "error": {"code": -32000, "message": err_msg}}), 401

            body = request.get_json(silent=True) or {}
            resp = self.handle_jsonrpc(body, session_context=auth_ctx)

            # If an active SSE session exists, also push into SSE queue
            if session_id and session_id in self.sessions and resp:
                self.sessions[session_id].put(f"event: message\ndata: {json.dumps(resp)}\n\n")

            if resp is None:
                return Response(status=202)
            return self._cors_response(jsonify(resp))

        return bp

    def _handle_sse_connect(self, url_prefix: str) -> Response:
        session_id = str(uuid.uuid4())
        q = queue.Queue()
        self.sessions[session_id] = q

        def event_stream():
            # Initial endpoint event per MCP SSE spec
            message_url = f"{url_prefix}/message?sessionId={session_id}"
            yield f"event: endpoint\ndata: {message_url}\n\n"
            try:
                while True:
                    try:
                        msg = q.get(timeout=20)
                        yield msg
                    except queue.Empty:
                        # Keepalive comment
                        yield ": keepalive\n\n"
            finally:
                self.sessions.pop(session_id, None)

        resp = Response(event_stream(), mimetype="text/event-stream")
        resp.headers["Cache-Control"] = "no-cache"
        resp.headers["X-Accel-Buffering"] = "no"
        return self._cors_response(resp)

    def _cors_response(self, resp: Response) -> Response:
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Headers"] = "*"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        return resp
