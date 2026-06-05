import asyncio
import json
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from flow import Executor

app = FastAPI(title="Agent Orchestrator API")

class QueryRequest(BaseModel):
    query: str
    session_id: str | None = None
    resume: bool = False

@app.get("/api/stream")
async def run_agent_stream(query: str, session_id: str | None = None, resume: bool = False) -> StreamingResponse:
    """Run the agent and stream progress events via Server-Sent Events (SSE)."""
    
    queue = asyncio.Queue()
    
    async def event_callback(event: dict):
        await queue.put(event)

    async def executor_task():
        executor = Executor()
        try:
            await executor.run(query, session_id=session_id, resume=resume, on_event=event_callback)
        except Exception as e:
            await queue.put({"type": "error", "message": f"Execution failed: {str(e)}"})
        finally:
            await queue.put({"type": "done", "message": "Execution finished"})

    async def event_generator() -> AsyncGenerator[str, None]:
        task = asyncio.create_task(executor_task())
        
        while True:
            event = await queue.get()
            yield f"data: {json.dumps(event)}\n\n"
            
            if event.get("type") == "done":
                break
                
        await task

    return StreamingResponse(event_generator(), media_type="text/event-stream")

# Mount static files (frontend)
import os
static_dir = os.path.join(os.path.dirname(__file__), "static")
if not os.path.exists(static_dir):
    os.makedirs(static_dir)

app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
