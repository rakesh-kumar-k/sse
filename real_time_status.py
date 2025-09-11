# ag2_integration.py
# from __future__ import annotations

import os
import asyncio
from typing import Annotated, List, Optional
import contextlib
from pydantic import BaseModel

# FastAPI bits are assumed from your existing main.py; import your manager
# from your websocket module:
# from main import manager, WebSocketManager
# Or refactor to pass the manager in from your FastAPI service function.

# --- AG2 imports ---
from autogen import ConversableAgent, LLMConfig
from autogen.agentchat import initiate_group_chat
from autogen.agentchat.group.patterns import AutoPattern
from autogen.agentchat.group import ReplyResult, AgentNameTarget, ContextVariables
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from pydantic import BaseModel

app = FastAPI()

# ---------- Request/Response Models ----------
class GenerateInsightsRequest(BaseModel):
    query: str
    session_id: str
    user_id: str
    topic: Optional[str] = None


class GenerateInsightsResponse(BaseModel):
    answer: str
    sources: List[str]
    suggestions: List[str]


# 1) Define the event_update tool as a closure bound to your manager.
#    It receives ContextVariables automatically; we read session_id from it.
async def event_update(
    message: Annotated[str, "A short status update to stream to the UI"],
    context_variables: Annotated[ContextVariables, 'context']=None,
) -> ReplyResult:
    """
    Send a real-time status message to the UI via WebSocket using session_id stored in context.
    """
    session_id = context_variables.get("session_id")
    if session_id:
        # Fire and forget to avoid blocking the tool execution
        try:
            await manager_sir.send_json(session_id, f"{message}\n\n")
        except RuntimeError:
            # If no running loop (unlikely here), ignore
            pass
    # ReplyResult message is visible in the transcript; no routing change needed.
    return ReplyResult(message="")


# ---------- AG2 Orchestration with AutoPattern and event_update tool ----------
async def run_agents_with_updates(
    req: GenerateInsightsRequest,
    ws_manager,  # your WebSocketManager instance
) -> GenerateInsightsResponse:
    """
    Builds a small AutoPattern with a few agents and a single status tool (event_update).
    Agents must call event_update(message: str) to stream progress; the tool reads session_id
    from context_variables and schedules a WebSocket send via ws_manager.
    """

    # 2) LLM configuration (adjust provider/model via env)
    #    Example uses OpenAI-style config; change to your provider as needed
    llm_config = LLMConfig(api_type="google", model="gemini-2.5-flash", api_key="dummy_keys")

    # 3) Define agents: planner -> researcher -> writer
    #    Each agent is instructed to call event_update as the only way to report progress.
    planner = ConversableAgent(
        name="planner",
        llm_config=llm_config,
        system_message=(
            "Role: Plan an approach to answer the user's query. in 50 tokens\n"
            "Rules:\n"
            "- On start, provide what you are going to do in a one liner by calling event_update(message) \n"
            "- Do not answer; hand off implicitly by speaking and let the manager select next.\n"
        ),
        functions=[event_update],  # register tool with this agent
    )

    researcher = ConversableAgent(
        name="researcher",
        llm_config=llm_config,
        system_message=(
            "Role: Gather and analyze info needed for the answer. in 50 tokens\n"
            "Rules:\n"
            "- On start, provide what you are going to do in a one liner by calling event_update(message) \n"
            "- Provide a concise analysis, then let writer finalize.\n"
        ),
        functions=[event_update],  # register tool
    )

    writer = ConversableAgent(
        name="writer",
        llm_config=llm_config,
        system_message=(
            "Role: Produce the final structured answer. in 50 tokens\n"
            "Output JSON with keys: answer(str), sources(list[str]), suggestions(list[str]).\n"
            "Rules:\n"
            "- On start, provide what you are going to do in a one liner by calling event_update(message) \n"
        ),
        functions=[event_update],  # register tool
    )

    # 4) A silent user proxy (no manual input)
    user = ConversableAgent(name="user", human_input_mode="NEVER")

    # 5) Initialize context with the session_id so the tool can read it
    context = ContextVariables(data={"session_id": req.session_id,
    # "manager_obj": ws_manager
    })

    # 6) AutoPattern with manager selection; event_update is visible to the agents via functions=[...]
    pattern = AutoPattern(
        initial_agent=planner,
        agents=[planner, researcher, writer],
        user_agent=user,
        group_manager_args={"llm_config": llm_config},
        context_variables=context,
    )

    # 7) Kick off the group chat. Prompt includes topic/query to guide agents.
    initial_prompt = (
        f"Topic: {req.topic or 'general'}\n"
        f"Query: {req.query}\n"
        "Follow the role rules. Writer must output the final JSON object only."
    )

    # Optionally send an initial event before the chat
    await ws_manager.send_json(req.session_id, f"started\n\n")

    # Run the group chat; the Group Manager will pick speakers adaptively
    result, _, _ = initiate_group_chat(
        pattern=pattern,
        messages=initial_prompt,
        max_rounds=15,
    )

    # 8) Try to parse a JSON object from the writer's last message; fall back gracefully
    print(result)
    answer = result.chat_history[-1]["content"]
    sources: List[str] = []
    suggestions: List[str] = []

    try:
        import json

        parsed = json.loads(content)
        if isinstance(parsed, dict):
            answer = str(parsed.get("answer", answer))
            sources = list(parsed.get("sources", sources))
            suggestions = list(parsed.get("suggestions", suggestions))
    except Exception:
        # Leave defaults; the message wasn't JSON
        pass

    # Final event
    await ws_manager.send_json(
        req.session_id,
         f"Answer: {answer}\n\n",
    )

    return GenerateInsightsResponse(answer=answer, sources=sources, suggestions=suggestions)



# ---------- WebSocket manager keyed by session_id ----------
class WebSocketManager:
    def __init__(self) -> None:
        self._connections: Dict[str, WebSocket] = {}
        self._lock = asyncio.Lock()

    async def connect(self, session_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections[session_id] = websocket

    async def disconnect(self, session_id: str) -> None:
        async with self._lock:
            ws = self._connections.pop(session_id, None)
        if ws:
            with contextlib.suppress(Exception):
                await ws.close()

    async def send_json(self, session_id: str, data: dict) -> None:
        # Retrieve outside lock to avoid holding it during network IO
        async with self._lock:
            ws = self._connections.get(session_id)
        if ws is None:
            return
        try:
            await ws.send_json(data)
        except Exception:
            # If sending fails (client gone), drop the mapping
            await self.disconnect(session_id)

    async def has(self, session_id: str) -> bool:
        async with self._lock:
            return session_id in self._connections


manager_sir = WebSocketManager()


# ---------- WebSocket endpoint ----------
@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    # Register this socket under the session_id
    await manager_sir.connect(session_id, websocket)
    try:
        # Keep the connection alive; optionally handle client pings/messages
        while True:
            # You can receive and ignore messages or implement ping/pong
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await manager_sir.disconnect(session_id)


# ---------- HTTP POST that returns final response but streams status via WS ----------
@app.post("/generate_insights", response_model=GenerateInsightsResponse)
async def generate_insights(req: GenerateInsightsRequest) -> GenerateInsightsResponse:
    if not await manager_sir.has(req.session_id):
        # It's okay to continue without WS; choose policy—either warn or reject
        # Here we warn via HTTP error if you want to enforce WS presence
        # raise HTTPException(status_code=400, detail="WebSocket not connected for session_id")
        pass

    try:
        # Option A: Sequential processing with awaited status sends
        result = await run_agents_with_updates(req, manager_sir)
        return result
    except Exception as error:
        ws_manager.send_json(req.session_id, f"encountered error {str(error)}")

    # Option B: If you want to parallelize long-running work and immediately return HTTP 202,
    # you can spawn a task and return an ack (commented out by default):
    # asyncio.create_task(generate_insights_service(req, manager))
    # return GenerateInsightsResponse(answer="", sources=[], suggestions=[])


import uvicorn
if __name__ == "__main__":
    from fastapi.middleware.cors import CORSMiddleware

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # dev only; restrict in prod
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    uvicorn.run(app, host="0.0.0.0", port=9898)
