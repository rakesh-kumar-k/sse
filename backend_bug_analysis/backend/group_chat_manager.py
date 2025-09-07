# autonomous_groupchat_manager.py
from typing import AsyncIterator, Dict, Any, Callable
import os
import yaml
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, JSONResponse
import uvicorn
from typing import Annotated
from datetime import datetime
import asyncio
import json
import autogen
from autogen import (
    ConversableAgent,
    GroupChat,
    GroupChatManager,
    LLMConfig,
)
from autogen.agentchat.group import ContextVariables
from fastapi.middleware.cors import CORSMiddleware

# pip install "ag2[openai]" fastapi uvicorn PyYAML

CONFIG_PATH = os.getenv("AGENT_CONFIG_PATH", "agents.yaml")

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)

def sse_event(data: Dict[str, Any]) -> bytes:
    return f"{json.dumps(data, ensure_ascii=False)}\n\n".encode("utf-8")

# ---------------------------
# 2) TOOL FUNCTIONS (unchanged)
# ---------------------------
def log_task_completion(
    task_name: Annotated[str, "Name of the completed task"],
    details: Annotated[str, "Task completion details"],
    context_variables: ContextVariables,
    ):
    """Log completed tasks with details"""
    tasks = context_variables.get("tasks_completed", [])
    task_entry = {
        "timestamp": datetime.now().isoformat(),
        "task": task_name,
        "details": details,
        "completed_by": "coordinator"
    }
    tasks.append(task_entry)
    context_variables["tasks_completed"] = tasks
    context_variables["task_count"] = len(tasks)
    context_variables["last_task"] = task_name
    return f"Task logged: {task_name} - {details}"

def record_finding(
    finding: Annotated[str, "Technical finding or observation"],
    severity: Annotated[str, "Severity level: low, medium, high, critical"] = "medium",
    context_variables: ContextVariables = None,
    ):
    """Record technical findings"""
    findings = context_variables.get("findings", [])
    finding_entry = {
        "timestamp": datetime.now().isoformat(),
        "finding": finding,
        "severity": severity,
        "discovered_by": "analyst"
    }
    findings.append(finding_entry)
    context_variables["findings"] = findings
    if severity in ["high", "critical"]:
        context_variables["analysis_depth"] = "deep"
    return f"Finding recorded: {finding} (Severity: {severity})"

def create_recommendation(
    recommendation: Annotated[str, "Recommended action or solution"],
    priority: Annotated[str, "Priority: low, medium, high"] = "medium",
    estimated_effort: Annotated[str, "Estimated implementation effort"] = "unknown",
    context_variables: ContextVariables = None,
    ):
    """Create actionable recommendations"""
    recommendations = context_variables.get("recommendations", [])
    rec_entry = {
        "timestamp": datetime.now().isoformat(),
        "recommendation": recommendation,
        "priority": priority,
        "effort": estimated_effort,
        "created_by": "strategist"
    }
    recommendations.append(rec_entry)
    context_variables["recommendations"] = recommendations
    return f"Recommendation created: {recommendation} (Priority: {priority}, Effort: {estimated_effort})"

def generate_summary_report(context_variables: ContextVariables):
    """Generate comprehensive project summary"""
    tasks = len(context_variables.get("tasks_completed", []))
    findings = len(context_variables.get("findings", []))
    recommendations = len(context_variables.get("recommendations", []))
    critical_findings = [f for f in context_variables.get("findings", []) if f.get("severity") == "critical"]
    high_priority_recs = [r for r in context_variables.get("recommendations", []) if r.get("priority") == "high"]
    summary = {
        "project": context_variables.get("project_name"),
        "session_duration": "calculated_from_start_time",
        "tasks_completed": tasks,
        "findings_discovered": findings,
        "recommendations_made": recommendations,
        "critical_issues": len(critical_findings),
        "high_priority_actions": len(high_priority_recs),
        "analysis_depth": context_variables.get("analysis_depth"),
    }
    context_variables["final_summary"] = summary
    return f"Summary report generated: {tasks} tasks, {findings} findings, {recommendations} recommendations"

def update_project_status(
    status: Annotated[str, "Current project status"],
    notes: Annotated[str, "Status update notes"] = "",
    context_variables: ContextVariables = None,
    ):
    """Update overall project status"""
    status_history = context_variables.get("status_history", [])
    status_entry = {
        "timestamp": datetime.now().isoformat(),
        "status": status,
        "notes": notes
    }
    status_history.append(status_entry)
    context_variables["status_history"] = status_history
    context_variables["current_status"] = status
    return f"Project status updated to: {status}"

# ---------------------------
# YAML LOADING
# ---------------------------
def _load_yaml_config() -> Dict[str, Any]:
    if not os.path.exists(CONFIG_PATH):
        return {}
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

CFG = _load_yaml_config()

def _agent_cfg_by_name(name: str) -> Dict[str, Any]:
    agents = CFG.get("agents") or []
    for a in agents:
        if a.get("name") == name:
            return a
    return {}

def _gc_cfg() -> Dict[str, Any]:
    return CFG.get("group_chat") or {}

AGENT_CARD = CFG.get("agent_card") or {}

# ---------------------------
# 8) AUTONOMOUS EXECUTION FUNCTION
# ---------------------------
def run_autonomous_analysis(initial_message, emit):
    """Run the entire analysis autonomously with no human input"""

    # 1) Shared context variables
    project_ctx = ContextVariables(data={
        "session_start": datetime.now().isoformat(),
        "project_name": CFG.get("project_name", "Backend Performance Analysis"),
        "tasks_completed": [],
        "findings": [],
        "recommendations": [],
        "task_count": 0,
        "analysis_depth": "initial",
        "priority_level": "high",
    })

    # 3) LLM Configuration from YAML
    llm_cfg = LLMConfig(api_type="google", model="gemini-2.5-flash", api_key="dummy_keys")

    with llm_cfg:
        # 4) CONVERSABLE AGENTS - configured from YAML, defaults preserved
        def mk_agent(yaml_name: str, default_system: str, description: str):
            a = _agent_cfg_by_name(yaml_name)
            return ConversableAgent(
                name=yaml_name,
                description=a.get("description", description),
                system_message=a.get("system_message", default_system),
                human_input_mode=a.get("human_input_mode", "NEVER"),
                code_execution_config=False,
                max_consecutive_auto_reply=a.get("max_consecutive_auto_reply", 10),
            )

        coordinator = mk_agent(
            "Coordinator",
            (
                "You are the project coordinator. Your role is to manage tasks, track progress, "
                "and ensure smooth workflow. Use log_task_completion to document finished work "
                "and update_project_status to track overall progress. Coordinate with other agents effectively."
            ),
            "Coordinates the project workflow and progress tracking."
        )
        analyst = mk_agent(
            "Analyst",
            (
                "You are the technical analyst. Perform deep analysis of the backend timeout issues, "
                "identify root causes, and use record_finding to document your discoveries. "
                "Focus on performance bottlenecks, resource utilization, and system constraints."
            ),
            "Performs technical analysis and records findings."
        )
        strategist = mk_agent(
            "Strategist",
            (
                "You are the solution strategist. Based on findings from the analyst, "
                "create actionable recommendations using create_recommendation. Prioritize solutions "
                "by impact and implementation effort. Focus on practical, implementable solutions."
            ),
            "Creates actionable recommendations."
        )
        reporter = mk_agent(
            "Reporter",
            (
                "You are the final reporter. Synthesize all work done by other agents and "
                "use generate_summary_report to create comprehensive documentation. "
                "Ensure all findings and recommendations are properly summarized."
            ),
            "Synthesizes output and generates summary."
        )

    # 5) REGISTER TOOLS FOR EACH AGENT (unchanged)
    coordinator.register_for_llm()(log_task_completion)
    coordinator.register_for_execution()(log_task_completion)
    coordinator.register_for_llm()(update_project_status)
    coordinator.register_for_execution()(update_project_status)

    analyst.register_for_llm()(record_finding)
    analyst.register_for_execution()(record_finding)

    strategist.register_for_llm()(create_recommendation)
    strategist.register_for_execution()(create_recommendation)

    reporter.register_for_llm()(generate_summary_report)
    reporter.register_for_execution()(generate_summary_report)

    # 7) GroupChat setup from YAML while preserving your selection logic
    gc = _gc_cfg()
    groupchat = GroupChat(
        agents=[coordinator, analyst, strategist, reporter],
        messages=[],
        max_round=gc.get("max_round", 8),
        speaker_selection_method=gc.get("speaker_selection_method", "auto"),
        select_speaker_auto_verbose=gc.get("select_speaker_auto_verbose", True),
        select_speaker_message_template=gc.get("select_speaker_message_template", """You are in a role play game. The following roles are available:
        {roles}.
        Read the following conversation.
        Then select the next role from {agentlist} to play along with the task it is supposed to do(in continuous tense. example: 'reviewing the answer'). Only return the role and the one-liner task"""),
                select_speaker_prompt_template=gc.get("select_speaker_prompt_template", "Read the above conversation. Then select the next role from {agentlist} to play along with the task it is supposed to do. Only return the role and the one-liner task"),
        )

    with llm_cfg:
        manager = GroupChatManager(
            groupchat=groupchat,
            context_variables=project_ctx,
        )

    print("=== AUTONOMOUS BACKEND ANALYSIS STARTING ===")
    print("Initial Context:")
    print(json.dumps(project_ctx.to_dict(), indent=2))
    print("\n" + "="*60)

    # Emit selector/validator reasoning -> status updates
    def print_received_message_new(self, message: dict[str, Any] | str, sender, skip_head: bool = False):
        if sender.name == "speaker_selection_agent":
            print(message)
            try:
                emit({"status": message['content'].split(":")[-1].strip()})
            except Exception:
                pass

    ConversableAgent._print_received_message = print_received_message_new

    # Initiate chat - completely autonomous, no human input requested
    result = coordinator.initiate_chat(
        manager,
        message=initial_message,
        clear_history=True,
    )

    final_context = project_ctx.to_dict()

    print("\n" + "="*60)
    print("AUTONOMOUS ANALYSIS COMPLETED")
    print("="*60)
    print(f"\n📊 EXECUTION SUMMARY:")
    print(f"   Project: {final_context.get('project_name')}")
    print(f"   Tasks Completed: {final_context.get('task_count', 0)}")
    print(f"   Findings Discovered: {len(final_context.get('findings', []))}")
    print(f"   Recommendations Made: {len(final_context.get('recommendations', []))}")
    print(f"   Final Status: {final_context.get('current_status', 'completed')}")

    if final_context.get('findings'):
        print(f"\n🔍 KEY FINDINGS:")
        for finding in final_context.get('findings', []):
            print(f"   - [{finding['severity'].upper()}] {finding['finding']}")
    if final_context.get('recommendations'):
        print(f"\n💡 RECOMMENDATIONS:")
        for rec in final_context.get('recommendations', []):
            print(f"   - [{rec['priority'].upper()}] {rec['recommendation']}")

    print(f"\n📋 COMPLETE FINAL CONTEXT:")
    print(json.dumps(final_context, indent=2))

    emit(final_context)
    return final_context

@app.get("/.well-known/agent.json")
def agent_card():
    """
    Serve an Agent Card so UIs/other agents can discover capabilities.
    Values come from agents.yaml agent_card section, with sensible defaults.
    """
    card = {
        "name": AGENT_CARD.get("name", "backend_analysis_team"),
        "description": AGENT_CARD.get("description", "Multi-agent backend performance analysis with SSE"),
        "url": AGENT_CARD.get("url", ""),
        "version": AGENT_CARD.get("version", "1.0.0"),
        "capabilities": {
            "streaming": True,
            **(AGENT_CARD.get("capabilities") or {})
        },
        "authentication": AGENT_CARD.get("authentication", {"schemes": []}),
        "defaultInputModes": AGENT_CARD.get("defaultInputModes", ["text"]),
        "defaultOutputModes": AGENT_CARD.get("defaultOutputModes", ["json"]),
        "skills": AGENT_CARD.get("skills", [
            {
                "id": "sse_article",
                "name": "Autonomous Analysis",
                "description": "Runs an autonomous multi-agent analysis and streams updates via SSE",
                "inputModes": ["text"],
                "outputModes": ["json"]
            }
        ]),
    }
    return JSONResponse(card)

@app.get("/sse/article")
async def sse_article(request: Request, topic: str):
    """
    GET /sse/article?topic=...
    Emits named events: 'status', 'agent_message', 'data' (JSON payloads).
    """
    initial_message = (
        "We need to analyze the backend timeout issues after the recent deployment. "
        "The production system is experiencing performance degradation under load. "
        "Please coordinate a comprehensive analysis, identify root causes, "
        "develop recommendations, and provide a final report. "
        "Work together autonomously to complete this analysis."
    )

    queue: asyncio.Queue[bytes] = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def emit(payload: Dict[str, Any]):
        loop.call_soon_threadsafe(queue.put_nowait, sse_event(payload))

    async def event_stream() -> AsyncIterator[bytes]:
        yield sse_event({"status": "started the flow"})
        task = asyncio.create_task(asyncio.to_thread(run_autonomous_analysis, initial_message, emit))
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    chunk = await asyncio.wait_for(queue.get(), timeout=0.5)
                    yield chunk
                except asyncio.TimeoutError:
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
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 9898)))
