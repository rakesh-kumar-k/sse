# server.py
import asyncio
import json
from typing import Dict, Any
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# AG2 WebSocket imports
from autogen import ConversableAgent, LLMConfig
from autogen.agentchat.group.patterns.auto import AutoPattern
from autogen.agentchat import a_initiate_group_chat
from autogen.io import IOWebsockets

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[WebSocket, bool] = {}

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[websocket] = True

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            del self.active_connections[websocket]

    async def send_message(self, websocket: WebSocket, message: dict):
        if websocket in self.active_connections:
            try:
                await websocket.send_text(json.dumps(message))
            except:
                self.disconnect(websocket)

manager = ConnectionManager()

async def run_ag2_joke_generation(topic: str, websocket: WebSocket):
    """Run AG2 workflow and stream results via WebSocket"""
    
    async def emit(event_type: str, data: Dict[str, Any]):
        """Helper function to emit events to WebSocket"""
        await manager.send_message(websocket, {
            "type": event_type,
            "data": data,
            "timestamp": asyncio.get_event_loop().time()
        })

    try:
        # Configure LLM
        llm_cfg = LLMConfig(
            api_type="google", 
            model="gemini-2.5-flash", 
            api_key="dummy_keys"
        )
        
        with llm_cfg:
            # Define agents
            generator = ConversableAgent(
                name="generator",
                system_message="Generate a creative and funny one-line joke based on the given topic."
            )
            evaluator = ConversableAgent(
                name="evaluator", 
                system_message="Evaluate the joke for humor, clarity, and appropriateness. Provide feedback."
            )
            editor = ConversableAgent(
                name="editor",
                system_message="Edit and polish the joke for maximum impact. Create the final version."
            )

            user = ConversableAgent(name="user")

            # Agent message callback for streaming
            def on_agent_message(agent: ConversableAgent, messages, sender, config):
                if messages:
                    last = messages[-1]
                    content = last if isinstance(last, str) else getattr(last, "content", str(last))
                    
                    # Emit agent message
                    asyncio.create_task(emit("agent_message", {
                        "agent": agent.name,
                        "from": getattr(sender, "name", "unknown"),
                        "content": content
                    }))
                return False, None

            # Register callbacks
            for agent in [generator, evaluator, editor]:
                agent.register_reply([ConversableAgent, None], reply_func=on_agent_message, config={})

            # Create AutoPattern
            pattern = AutoPattern(
                initial_agent=generator,
                agents=[generator, evaluator, editor],
                user_agent=user,
                summary_method="last_msg",
            )

            # Start workflow
            await emit("status", {"step": "accepted", "topic": topic})
            await emit("status", {"step": "group:start", "topic": topic})
            
            # Run group chat
            chat_result, ctx, last_speaker = await a_initiate_group_chat(
                pattern=pattern,
                messages=f"Write a one-line joke on '{topic}'",
                max_rounds=4
            )
            
            await emit("status", {"step": "group:done", "last_speaker": getattr(last_speaker, "name", "unknown")})

            # Send final result
            final_content = ""
            if chat_result and getattr(chat_result, "summary", None):
                final_content = chat_result.summary
            elif chat_result and getattr(chat_result, "chat_history", None):
                msgs = chat_result.chat_history
                final_text = msgs[-1] if msgs else ""
                final_content = getattr(final_text, "content", str(final_text))

            await emit("data", {"final": final_content})
            
    except Exception as e:
        await emit("error", {"message": f"Error during joke generation: {str(e)}"})

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for AG2 joke generation"""
    await manager.connect(websocket)
    print("Client connected via WebSocket")
    
    try:
        while True:
            # Receive message from client
            data = await websocket.receive_text()
            message = json.loads(data)
            
            print(f"Received: {message}")
            
            if message.get("type") == "generate_joke":
                topic = message.get("topic", "").strip()
                if topic:
                    # Send acknowledgment
                    await manager.send_message(websocket, {
                        "type": "status",
                        "data": {"step": "received", "topic": topic}
                    })
                    
                    # Run AG2 workflow
                    await run_ag2_joke_generation(topic, websocket)
                else:
                    await manager.send_message(websocket, {
                        "type": "error", 
                        "data": {"message": "Topic cannot be empty"}
                    })
            
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        print("Client disconnected")
    except Exception as e:
        print(f"WebSocket error: {e}")
        manager.disconnect(websocket)

@app.get("/")
async def get():
    return {"message": "AG2 WebSocket Joke Generator Server"}

@app.get("/health")
async def health():
    return {"status": "healthy", "service": "ag2-websocket-server"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=9898)
