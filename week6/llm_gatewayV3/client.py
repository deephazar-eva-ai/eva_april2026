"""Python client for LLM Gateway V3. Adds auto_route kwarg on top of V2."""
from click import shell_completion
from click import shell_completion
import os, json, httpx
from typing import Any, Optional

DEFAULT_URL = os.getenv("LLM_GATEWAY_V3_URL", "http://localhost:8101")


class LLM:
    def __init__(self, base_url: str = DEFAULT_URL, timeout: float = 600):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def chat(self, prompt: str = None, *,
             messages: Optional[list] = None,
             system: Any = None,
             provider: str = None, model: str = None,
             max_tokens: int = 2048, temperature: float = 0.7,
             tools: Optional[list] = None,
             tool_choice: Any = None,
             cache_system: Optional[bool] = None,
             reasoning: Optional[str] = None,
             response_format: Any = None,
             auto_route: Optional[str] = None) -> dict:
        body = {
            "prompt": prompt, "messages": messages, "system": system,
            "provider": provider, "model": model,
            "max_tokens": max_tokens, "temperature": temperature, "stream": False,
            "tools": tools, "tool_choice": tool_choice,
            "cache_system": cache_system, "reasoning": reasoning,
            "response_format": response_format,
            "auto_route": auto_route,
        }
        body = {k: v for k, v in body.items() if v is not None}
        r = httpx.post(f"{self.base_url}/v1/chat", json=body, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def stream(self, prompt: str = None, *, messages=None, system=None,
               provider: str = None, model: str = None,
               max_tokens: int = 2048, temperature: float = 0.7,
               tools=None, tool_choice=None,
               cache_system=None, reasoning=None, response_format=None):
        body = {
            "prompt": prompt, "messages": messages, "system": system,
            "provider": provider, "model": model,
            "max_tokens": max_tokens, "temperature": temperature, "stream": True,
            "tools": tools, "tool_choice": tool_choice,
            "cache_system": cache_system, "reasoning": reasoning,
            "response_format": response_format,
        }
        body = {k: v for k, v in body.items() if v is not None}
        with httpx.stream("POST", f"{self.base_url}/v1/chat", json=body, timeout=self.timeout) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if not line or not line.startswith("data: "):
                    continue
                d = json.loads(line[6:])
                if "delta" in d:
                    yield d["delta"]
                if d.get("done") or d.get("error"):
                    return

    def capabilities(self):
        return httpx.get(f"{self.base_url}/v1/capabilities", timeout=30).json()


def ask(prompt: str, provider: str = None, **kw) -> str:
    return LLM().chat(prompt, provider=provider, **kw)["text"]


if __name__ == "__main__":
    import sys
    p = sys.argv[1] if len(sys.argv) > 1 else None
    print(ask("Say hello in one short line.", provider=p))

    # 2) Auto-routed call (cognitive layer = perception)
    llm = LLM()
    result =  llm.chat(
    "What is the capital of France?",
    auto_route="perception",
    )
    print(result["text"])
    print(result["router_decision"])
# {
#   "role": "perception",
#   "tier": "TINY",
#   "estimated_tokens": 15,
#   "router_provider": "cerebras",
#   "router_model": "llama3.1-8b",
#   "router_latency_ms": 84,
#   "chosen_worker_provider": "github",
#   "chosen_worker_model": "openai/gpt-4.1-mini",
#   "fallback_used": false
# }

# 3) Memory layer routing — summarizing retrieved facts
    result = llm.chat(
    f"Summarize for relevance to '{query}':\n\n{retrieved_chunk}",
    auto_route="memory",
    )

# 4) Decision layer routing — planning the next step
    result = llm.chat(
    plan_state_serialized,
    auto_route="decision",
    )

# 5) Explicit provider beats auto_route (debugging escape hatch)
    result = llm.chat(
    "Hello",
    auto_route="perception",       # logged but ignored
    provider="g",                  # gemini wins
    )
    assert result["router_decision"] is None

    # 6) All V2 features still work — tools, caching, reasoning, structured output
    result = llm.chat(
    messages=[{"role": "user", "content": "What is 7+5? Use the add tool."}],
    tools=[{"name":"add","description":"a+b",
            "input_schema":{"type":"object","properties":{"a":{"type":"number"},"b":{"type":"number"}},"required":["a","b"]}}],
    tool_choice="auto",
    auto_route="decision",          # routes via cognitive-layer hint
    )
