import asyncio
import json
from contextlib import asynccontextmanager
from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp.client.session import ClientSession
from pydantic import BaseModel

from core.orchestrator import Agent6Orchestrator
from core.memory import MemoryService
from core.perception import Perception
from core.decision import Decision
from core.action import Action
from core.artifacts import ArtifactStore
from core.models import GatewayResponse, GatewayToolCall, RouterDecision
from llm_gatewayV3.client import LLM

class GatewayAdapter:
    def __init__(self, llm: LLM):
        self.llm = llm

    def invoke(
        self,
        *,
        prompt: str,
        tools: list[dict],
        tool_choice: str,
        auto_route: str,
    ) -> GatewayResponse:
        
        import httpx
        import time
        max_retries = 3
        for attempt in range(max_retries):
            try:
                resp = self.llm.chat(
                    prompt=prompt,
                    tools=tools,
                    tool_choice=tool_choice,
                    auto_route=auto_route,
                )
                break
            except httpx.HTTPStatusError as e:
                if e.response.status_code in [502, 503, 504] and attempt < max_retries - 1:
                    time.sleep(2)
                else:
                    raise
        
        router_decision = None
        if resp.get("router_decision"):
            router_decision = RouterDecision(
                tier=resp["router_decision"].get("tier", "UNKNOWN"),
                reason=resp["router_decision"].get("reason")
            )
            
        tool_calls = []
        if resp.get("tool_calls"):
            for tc in resp["tool_calls"]:
                args = tc.get("arguments", {})
                if isinstance(args, str):
                    args = json.loads(args)
                tool_calls.append(
                    GatewayToolCall(
                        name=tc["name"],
                        arguments=args
                    )
                )
                
        return GatewayResponse(
            text=resp.get("text"),
            tool_calls=tool_calls,
            router_decision=router_decision,
        )

    def structured(
        self,
        *,
        prompt: str,
        schema: type[BaseModel],
        auto_route: str,
    ):
        import httpx
        import time
        max_retries = 3
        schema_dict = schema.model_json_schema()
        
        for attempt in range(max_retries):
            try:
                resp = self.llm.chat(
                    prompt=prompt,
                    response_format={
                        "type": "json_schema", 
                        "name": schema.__name__,
                        "schema": schema_dict,
                        "strict": True
                    },
                    auto_route=auto_route,
                )
                break
            except httpx.HTTPStatusError as e:
                if e.response.status_code in [502, 503, 504] and attempt < max_retries - 1:
                    time.sleep(2)
                else:
                    raise
                    
        return schema.model_validate_json(resp["text"])


@asynccontextmanager
async def mcp_session_manager():
    server_params = StdioServerParameters(
        command="python",
        args=["tools/mcp_server.py"],
    )
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session

async def load_mcp_tools(session: ClientSession):
    return await session.list_tools()

def format_tools_for_decision(mcp_tools):
    tools = mcp_tools.tools if hasattr(mcp_tools, "tools") else mcp_tools
    formatted = []
    for t in tools:
        formatted.append({
            "name": t.name,
            "description": t.description,
            "input_schema": getattr(t, "inputSchema", {}),
        })
    return formatted

async def run_agent():
    artifacts = ArtifactStore()
    llm = LLM()
    gateway = GatewayAdapter(llm)
    
    orchestrator = Agent6Orchestrator(
        memory=MemoryService(),
        perception=Perception(llm=gateway),
        decision=Decision(gateway=gateway),
        action=Action(artifact_store=artifacts),
        artifacts=artifacts,
        gateway=gateway,
        mcp_session=mcp_session_manager,
        load_tools=load_mcp_tools,
        mcp_tools_for_decision=format_tools_for_decision,
    )
    
    print("Welcome to week6_assgnmt Agent6 Orchestrator!")
    while True:
        try:
            query = input("\nUser > ")
            if not query.strip():
                continue
            if query.lower() in ["exit", "quit"]:
                break
            
            result = await orchestrator.run(query)
            print(f"\n{result}")
            
        except (EOFError, KeyboardInterrupt):
            break

def main():
    asyncio.run(run_agent())

if __name__ == "__main__":
    main()
