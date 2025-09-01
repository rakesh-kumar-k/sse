import asyncio
import json
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import uvicorn

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

@app.get("/test")
async def test():
    return {"status": "success", "message": "Backend working"}

@app.get("/sse/article")
async def sse_article(request: Request, topic: str):
    async def event_generator():
        # CRITICAL: Send immediate connection message
        yield f"data: {json.dumps({'connected': True, 'topic': topic})}\n\n"
        
        # Small delay to ensure message is sent
        await asyncio.sleep(0.1)
        
        # Send status events
        yield f"event: status\ndata: {json.dumps({'step': 'accepted', 'topic': topic})}\n\n"
        await asyncio.sleep(1)
        
        # Agent messages
        yield f"event: agent_message\ndata: {json.dumps({'agent': 'researcher', 'content': 'Starting research...'})}\n\n"
        await asyncio.sleep(2)
        
        yield f"event: agent_message\ndata: {json.dumps({'agent': 'writer', 'content': 'Writing article...'})}\n\n"
        await asyncio.sleep(2)
        
        yield f"event: agent_message\ndata: {json.dumps({'agent': 'editor', 'content': 'Editing final draft...'})}\n\n"
        await asyncio.sleep(1)
        
        # Final result
        final_article = f"""# {topic}

This is a comprehensive article about {topic}.

## Introduction
Research has been conducted on this important topic.

## Main Content
The article covers key aspects and provides valuable insights.

## Conclusion
This demonstrates the AG2 multi-agent system working effectively.
"""
        
        yield f"event: data\ndata: {json.dumps({'final': final_article})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
            "Access-Control-Allow-Origin": "http://localhost:3000",
        }
    )

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
