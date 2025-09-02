# server.py
import asyncio
import json
from typing import AsyncIterator, Dict, Any, Callable

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
import uvicorn

# AG2 (formerly AutoGen)
from autogen import ConversableAgent, LLMConfig
from autogen.agentchat.group.patterns.auto import AutoPattern
from autogen.agentchat import a_initiate_group_chat


# pip install "ag2[openai]" fastapi uvicorn
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)


def sse_event(event: str, data: Dict[str, Any], event_id: str | None = None) -> bytes:
    print(event, data, event_id)
    lines = []
    if event_id is not None:
        lines.append(f"id: {event_id}")
    if event:
        lines.append(f"event: {event}")
    lines.append(f"data: {json.dumps(data, ensure_ascii=False)}")
    lines.append("")
    return ("\n".join(lines) + "\n").encode("utf-8")

async def run_autopattern_article_flow(
    topic: str,
    emit: Callable[[str, Dict[str, Any]], None],
) -> None:
    # Configure LLM for all agents in this context
    llm_cfg = LLMConfig(api_type="google", model="gemini-2.5-flash", api_key="dummy")
    with llm_cfg:
        # Define role agents (descriptions help the group manager route turns)
        generator = ConversableAgent(
            name="generator",
            system_message="generate joke"
        )
        evaluator = ConversableAgent(
            name="evaluator",
            system_message="Evaluate the output and provide feedback"
        )
        editor = ConversableAgent(
            name="editor",
            system_message="Edit for clarity, correctness, and coherence; finalize the output."
        )

        # Optional: a user proxy if needed by the pattern
        user = ConversableAgent(name="user")

        # Stream every agent message via register_reply
        def on_msg(agent: ConversableAgent, messages, sender, config):
            if messages:
                last = messages[-1]
                emit("agent_message", {
                    "agent": agent.name,
                    "from": getattr(sender, "name", "unknown"),
                    "content": last if isinstance(last, str) else getattr(last, "content", str(last))
                })
            return False, None  # don't short-circuit normal handling

        for a in [generator, evaluator, editor]:
            a.register_reply([ConversableAgent, None], reply_func=on_msg, config={})

        # Build AutoPattern: manager routes speakers automatically
        pattern = AutoPattern(
            initial_agent=generator,
            agents=[generator, evaluator, editor],
            user_agent=user,
            summary_method="last_msg",
        )

        emit("status", {"step": "group:start", "topic": topic})
        # Run the group chat asynchronously; returns when the conversation completes
        chat_result, ctx, last_speaker = await a_initiate_group_chat(
            pattern=pattern,
            messages=f"Write an one line joke on '{topic}'",
            max_rounds=4
        )
        emit("status", {"step": "group:done", "last_speaker": getattr(last_speaker, "name", "unknown")})

        # Optionally surface the final message/content to the UI
        if chat_result and getattr(chat_result, "summary", None):
            emit("data", {"final": chat_result.summary})
        elif chat_result and getattr(chat_result, "chat_history", None):
            # Fallback: take the last message
            msgs = chat_result.chat_history
            final_text = msgs[-1] if msgs else ""
            emit("data", {"final": getattr(final_text, "content", str(final_text))})

@app.get("/sse/article")
async def sse_article(request: Request, topic: str):
    """
    GET /sse/article?topic=...
    Emits named events: 'status', 'agent_message', 'data' (JSON payloads).
    """
    queue: asyncio.Queue[bytes] = asyncio.Queue()

    def emit(event: str, payload: Dict[str, Any]):
        queue.put_nowait(sse_event(event, payload))

    async def event_stream() -> AsyncIterator[bytes]:
        task = asyncio.create_task(run_autopattern_article_flow(topic, emit))
        # Initial hello
        yield sse_event("status", {"step": "accepted", "topic": topic})
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    chunk = await asyncio.wait_for(queue.get(), timeout=0.5)
                    yield chunk
                except asyncio.TimeoutError:
                    # keep-alive to prevent idle intermediaries from closing the connection
                    yield b": keep-alive\n\n"
                if task.done():
                    while not queue.empty():
                        yield queue.get_nowait()
                    break
        finally:
            if not task.done():
                task.cancel()

    headers = {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache", 
        "Connection": "keep-alive",
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, OPTIONS",
        "Access-Control-Allow-Headers": "*",
    }
    return StreamingResponse(event_stream(), headers=headers)

if __name__ == "__main__":
        uvicorn.run(app, host="0.0.0.0", port=9898)
