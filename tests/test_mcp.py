"""
Comprehensive tests for MCP (Model Context Protocol) implementation.
Tests: schemas, JSON-RPC handling, server protocol, client registry, tool routing.
"""
import json
import pytest
from src.mcp import (
    MCPProtocolHandler, TOOL_SCHEMAS, SERVER_INFO, SERVER_CAPABILITIES,
    get_runtime_tool_schemas,
    _jsonrpc_result, _jsonrpc_error,
    PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INTERNAL_ERROR,
    list_mcp_clients, get_all_mcp_tools,
)


# ============================================================
# Tool Schema Tests
# ============================================================

class TestToolSchemas:
    def test_schema_count(self):
        """All tools except 'done' should have schemas."""
        from src.tools import TOOL_REGISTRY
        expected = len([n for n in TOOL_REGISTRY if n != "done"])
        assert len(TOOL_SCHEMAS) == expected

    def test_all_tools_have_schemas(self):
        from src.tools import TOOL_REGISTRY
        for name in TOOL_REGISTRY:
            if name == "done":
                continue
            assert name in TOOL_SCHEMAS, f"Missing schema for tool: {name}"

    def test_schema_structure(self):
        for name, schema in TOOL_SCHEMAS.items():
            assert "description" in schema, f"{name} missing description"
            assert "inputSchema" in schema, f"{name} missing inputSchema"
            assert schema["inputSchema"]["type"] == "object", f"{name} inputSchema not object"
            assert "properties" in schema["inputSchema"], f"{name} missing properties"

    def test_required_fields_are_valid(self):
        for name, schema in TOOL_SCHEMAS.items():
            required = schema["inputSchema"].get("required", [])
            props = schema["inputSchema"]["properties"]
            for req_field in required:
                assert req_field in props, f"{name}: required field '{req_field}' not in properties"

    def test_typed_params_not_all_string(self):
        """Ensure we have properly typed params (int, bool) not just strings."""
        int_found = False
        bool_found = False
        for name, schema in TOOL_SCHEMAS.items():
            for prop_name, prop in schema["inputSchema"]["properties"].items():
                if prop.get("type") == "integer":
                    int_found = True
                if prop.get("type") == "boolean":
                    bool_found = True
        assert int_found, "No integer-typed parameters found"
        assert bool_found, "No boolean-typed parameters found"

    def test_specific_types(self):
        assert TOOL_SCHEMAS["read"]["inputSchema"]["properties"]["offset"]["type"] == "integer"
        assert TOOL_SCHEMAS["read"]["inputSchema"]["properties"]["limit"]["type"] == "integer"
        assert TOOL_SCHEMAS["git_diff"]["inputSchema"]["properties"]["staged"]["type"] == "boolean"
        assert TOOL_SCHEMAS["kill_process"]["inputSchema"]["properties"]["pid"]["type"] == "integer"
        assert TOOL_SCHEMAS["generate_image"]["inputSchema"]["properties"]["width"]["type"] == "integer"
        assert TOOL_SCHEMAS["multi_search"]["inputSchema"]["properties"]["queries"]["type"] == "array"
        assert TOOL_SCHEMAS["batch_edit"]["inputSchema"]["properties"]["edits"]["type"] == "array"

    def test_no_params_tools(self):
        """Tools with no parameters should have empty properties."""
        for name in ["git_status", "run_tests", "process_list", "network_info", "screenshot"]:
            assert TOOL_SCHEMAS[name]["inputSchema"]["properties"] == {}, f"{name} should have empty properties"

    def test_runtime_schemas_include_dynamic_registered_tools(self):
        from src.tools import TOOL_REGISTRY
        TOOL_REGISTRY["plugin_echo"] = {
            "fn": lambda name, mode="brief": f"{mode}:{name}",
            "description": "Echo a name for testing runtime schema generation",
            "args": "name, [mode]",
        }
        try:
            schemas = get_runtime_tool_schemas()
            assert "plugin_echo" in schemas
            schema = schemas["plugin_echo"]["inputSchema"]
            assert schema["required"] == ["name"]
            assert set(schema["properties"]) == {"name", "mode"}
        finally:
            TOOL_REGISTRY.pop("plugin_echo", None)


# ============================================================
# JSON-RPC Helper Tests
# ============================================================

class TestJsonRpcHelpers:
    def test_result(self):
        r = _jsonrpc_result(1, {"data": "test"})
        assert r["jsonrpc"] == "2.0"
        assert r["id"] == 1
        assert r["result"]["data"] == "test"

    def test_error(self):
        r = _jsonrpc_error(2, -32600, "Invalid")
        assert r["jsonrpc"] == "2.0"
        assert r["id"] == 2
        assert r["error"]["code"] == -32600
        assert r["error"]["message"] == "Invalid"

    def test_error_with_data(self):
        r = _jsonrpc_error(3, -32603, "Crash", {"trace": "..."})
        assert r["error"]["data"]["trace"] == "..."


# ============================================================
# MCP Protocol Handler Tests
# ============================================================

class TestMCPProtocolHandler:
    def setup_method(self):
        self.handler = MCPProtocolHandler()

    def _init(self):
        return self.handler.handle_message({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                       "clientInfo": {"name": "pytest", "version": "1.0"}}
        })

    # --- Initialize ---

    def test_initialize(self):
        r = self._init()
        assert r["result"]["protocolVersion"] == "2024-11-05"
        assert r["result"]["serverInfo"]["name"] == "omniagent"
        from src.config import VERSION as _V; assert r["result"]["serverInfo"]["version"] == _V

    def test_initialize_capabilities(self):
        r = self._init()
        caps = r["result"]["capabilities"]
        assert "tools" in caps
        assert "resources" in caps
        assert "prompts" in caps

    def test_initialized_notification(self):
        self._init()
        result = self.handler.handle_message({
            "jsonrpc": "2.0", "method": "notifications/initialized", "params": {}
        })
        assert result is None  # Notifications return None
        assert self.handler.initialized

    # --- Ping ---

    def test_ping(self):
        r = self.handler.handle_message({"jsonrpc": "2.0", "id": 99, "method": "ping", "params": {}})
        assert r["result"] == {}

    # --- Tools ---

    def test_tools_list(self):
        r = self.handler.handle_message({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        tools = r["result"]["tools"]
        assert len(tools) == 46  # 47 minus 'done'
        names = {t["name"] for t in tools}
        assert "read" in names
        assert "write" in names
        assert "shell" in names
        assert "done" not in names

    def test_tools_list_has_schemas(self):
        r = self.handler.handle_message({"jsonrpc": "2.0", "id": 3, "method": "tools/list", "params": {}})
        for tool in r["result"]["tools"]:
            assert "name" in tool
            assert "description" in tool
            assert "inputSchema" in tool
            assert tool["inputSchema"]["type"] == "object"

    def test_tools_list_includes_runtime_registered_tool(self):
        from src.tools import TOOL_REGISTRY
        TOOL_REGISTRY["plugin_echo"] = {
            "fn": lambda name: f"plugin:{name}",
            "description": "Echo a name for testing runtime tool exposure",
            "args": "name",
        }
        try:
            r = self.handler.handle_message({"jsonrpc": "2.0", "id": 31, "method": "tools/list", "params": {}})
            names = {tool["name"] for tool in r["result"]["tools"]}
            assert "plugin_echo" in names
        finally:
            TOOL_REGISTRY.pop("plugin_echo", None)

    def test_tools_call_success(self):
        r = self.handler.handle_message({
            "jsonrpc": "2.0", "id": 4, "method": "tools/call",
            "params": {"name": "python_eval", "arguments": {"expression": "42 + 8"}}
        })
        content = r["result"]["content"]
        assert len(content) == 1
        assert content[0]["type"] == "text"
        assert "50" in content[0]["text"]
        assert not r["result"]["isError"]

    def test_tools_call_unknown(self):
        r = self.handler.handle_message({
            "jsonrpc": "2.0", "id": 5, "method": "tools/call",
            "params": {"name": "nonexistent_tool", "arguments": {}}
        })
        assert r["result"]["isError"]

    def test_tools_call_runtime_registered_tool(self):
        from src.tools import TOOL_REGISTRY
        TOOL_REGISTRY["plugin_echo"] = {
            "fn": lambda name: f"plugin:{name}",
            "description": "Echo a name for testing runtime tool calls",
            "args": "name",
        }
        try:
            r = self.handler.handle_message({
                "jsonrpc": "2.0", "id": 32, "method": "tools/call",
                "params": {"name": "plugin_echo", "arguments": {"name": "alice"}}
            })
            assert not r["result"]["isError"]
            assert "plugin:alice" in r["result"]["content"][0]["text"]
        finally:
            TOOL_REGISTRY.pop("plugin_echo", None)

    def test_tools_call_env_get(self):
        import os
        os.environ["_MCP_TEST_VAR"] = "hello_mcp"
        r = self.handler.handle_message({
            "jsonrpc": "2.0", "id": 6, "method": "tools/call",
            "params": {"name": "env_get", "arguments": {"name": "_MCP_TEST_VAR"}}
        })
        assert "hello_mcp" in r["result"]["content"][0]["text"]
        del os.environ["_MCP_TEST_VAR"]

    # --- Resources ---

    def test_resources_list(self):
        r = self.handler.handle_message({"jsonrpc": "2.0", "id": 10, "method": "resources/list", "params": {}})
        resources = r["result"]["resources"]
        assert len(resources) == 4
        uris = {res["uri"] for res in resources}
        assert "omniagent://config" in uris
        assert "omniagent://metrics" in uris
        assert "omniagent://agents" in uris
        assert "omniagent://tools" in uris

    def test_resource_read_config(self):
        r = self.handler.handle_message({
            "jsonrpc": "2.0", "id": 11, "method": "resources/read",
            "params": {"uri": "omniagent://config"}
        })
        content = r["result"]["contents"][0]
        assert content["mimeType"] == "application/json"
        data = json.loads(content["text"])
        assert "models" in data

    def test_resource_read_agents(self):
        r = self.handler.handle_message({
            "jsonrpc": "2.0", "id": 12, "method": "resources/read",
            "params": {"uri": "omniagent://agents"}
        })
        data = json.loads(r["result"]["contents"][0]["text"])
        assert "coder" in data
        assert "reasoner" in data
        assert data["coder"]["max_tool_steps"] == 30

    def test_resource_read_tools(self):
        r = self.handler.handle_message({
            "jsonrpc": "2.0", "id": 13, "method": "resources/read",
            "params": {"uri": "omniagent://tools"}
        })
        data = json.loads(r["result"]["contents"][0]["text"])
        assert len(data) >= 47

    def test_resource_read_unknown(self):
        r = self.handler.handle_message({
            "jsonrpc": "2.0", "id": 14, "method": "resources/read",
            "params": {"uri": "omniagent://nonexistent"}
        })
        assert "Unknown" in r["result"]["contents"][0]["text"]

    # --- Prompts ---

    def test_prompts_list(self):
        r = self.handler.handle_message({"jsonrpc": "2.0", "id": 20, "method": "prompts/list", "params": {}})
        prompts = r["result"]["prompts"]
        assert len(prompts) == 6
        names = {p["name"] for p in prompts}
        assert "code_review" in names
        assert "debug" in names
        assert "security_audit" in names

    def test_prompt_arguments(self):
        r = self.handler.handle_message({"jsonrpc": "2.0", "id": 21, "method": "prompts/list", "params": {}})
        code_review = [p for p in r["result"]["prompts"] if p["name"] == "code_review"][0]
        assert len(code_review["arguments"]) >= 1
        assert code_review["arguments"][0]["name"] == "file_path"
        assert code_review["arguments"][0]["required"]

    def test_prompt_get(self):
        r = self.handler.handle_message({
            "jsonrpc": "2.0", "id": 22, "method": "prompts/get",
            "params": {"name": "debug", "arguments": {"error_message": "TypeError: cannot add int and str"}}
        })
        messages = r["result"]["messages"]
        assert len(messages) == 1
        assert messages[0]["role"] == "user"
        assert "TypeError" in messages[0]["content"]["text"]

    def test_prompt_get_unknown(self):
        r = self.handler.handle_message({
            "jsonrpc": "2.0", "id": 23, "method": "prompts/get",
            "params": {"name": "nonexistent", "arguments": {}}
        })
        assert "Unknown" in r["result"]["messages"][0]["content"]["text"]

    # --- Completion ---

    def test_completion_tools(self):
        r = self.handler.handle_message({
            "jsonrpc": "2.0", "id": 30, "method": "completion/complete",
            "params": {"ref": {"type": "ref/tool"}, "argument": {"value": "git"}}
        })
        values = r["result"]["completion"]["values"]
        assert all(v.startswith("git") for v in values)
        assert "git_status" in values

    def test_completion_resources(self):
        r = self.handler.handle_message({
            "jsonrpc": "2.0", "id": 31, "method": "completion/complete",
            "params": {"ref": {"type": "ref/resource"}, "argument": {"value": "omniagent://m"}}
        })
        assert "omniagent://metrics" in r["result"]["completion"]["values"]

    def test_completion_prompts(self):
        r = self.handler.handle_message({
            "jsonrpc": "2.0", "id": 32, "method": "completion/complete",
            "params": {"ref": {"type": "ref/prompt"}, "argument": {"value": "code"}}
        })
        assert "code_review" in r["result"]["completion"]["values"]

    # --- Error handling ---

    def test_unknown_method(self):
        r = self.handler.handle_message({"jsonrpc": "2.0", "id": 40, "method": "bogus/method", "params": {}})
        assert "error" in r
        assert r["error"]["code"] == METHOD_NOT_FOUND

    def test_notification_returns_none(self):
        r = self.handler.handle_message({
            "jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 99}
        })
        assert r is None


# ============================================================
# MCP Client Registry Tests
# ============================================================

class TestMCPClientRegistry:
    def test_list_empty(self):
        clients = list_mcp_clients()
        assert isinstance(clients, list)

    def test_get_all_tools_empty(self):
        tools = get_all_mcp_tools()
        assert isinstance(tools, list)


# ============================================================
# MCP Tool Routing Tests (server__tool convention)
# ============================================================

class TestMCPToolRouting:
    def test_local_tool_still_works(self):
        from src.tools import execute_tool
        result = execute_tool("python_eval", {"expression": "1 + 1"})
        assert "2" in result

    def test_unknown_mcp_server(self):
        from src.tools import execute_tool
        result = execute_tool("nonexistent__some_tool", {"arg": "val"})
        assert "ERROR" in result

    def test_mcp_routing_format(self):
        """Verify server__tool format is recognized."""
        from src.tools import execute_tool
        # This should route to MCP, not raise "unknown tool"
        result = execute_tool("test_server__test_tool", {})
        assert "ERROR" in result  # Will error because no server is connected
        assert "not found" in result.lower() or "not connected" in result.lower() or "MCP" in result


# ============================================================
# Server Info Tests
# ============================================================

class TestServerInfo:
    def test_server_name(self):
        assert SERVER_INFO["name"] == "omniagent"

    def test_server_version(self):
        from src.config import VERSION as _V2; assert SERVER_INFO["version"] == _V2

    def test_capabilities(self):
        assert "tools" in SERVER_CAPABILITIES
        assert "resources" in SERVER_CAPABILITIES
        assert "prompts" in SERVER_CAPABILITIES
