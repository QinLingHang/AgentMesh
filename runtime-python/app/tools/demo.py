from app.tools.contracts import ToolDefinition
from app.tools.registry import ToolRegistry

def register_demo_tools(registry: ToolRegistry) -> None:
    schema = {"type":"object", "properties":{"query":{"type":"string"}}, "additionalProperties": True}
    registry.register(ToolDefinition(name="get_order", description="Get deterministic demo order", input_schema=schema), lambda a: {"orderId":"ORD-1001","status":"PAID","query":a.get("query","")})
    registry.register(ToolDefinition(name="get_logistics", description="Get deterministic demo logistics", input_schema=schema), lambda a: {"trackingNo":"SF10001","status":"IN_TRANSIT","eta":"2026-09-03"})
    registry.register(ToolDefinition(name="diagnose_service", description="Diagnose deterministic demo service", input_schema=schema), lambda a: {"service":"demo-api","healthy":False,"cause":"upstream timeout"})
