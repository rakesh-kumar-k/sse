"use client";
import { useEffect, useRef, useState } from "react";

type Message = {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: number;
};

type AgentStatus = {
  agent: string;
  content: string;
};

export default function ChatBot() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [currentAgent, setCurrentAgent] = useState<AgentStatus | null>(null);
  const [connectionError, setConnectionError] = useState<string>("");
  const [connectionStatus, setConnectionStatus] = useState<string>("Disconnected");
  
  const wsRef = useRef<WebSocket | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const backendUrl = "ws://localhost:9898/ws";

  // Auto scroll to bottom
  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, currentAgent]);

  // Focus input on mount
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  // WebSocket connection management
  useEffect(() => {
    const connectWebSocket = () => {
      try {
        const ws = new WebSocket(backendUrl);
        wsRef.current = ws;

        ws.onopen = () => {
          console.log("✅ WebSocket connected");
          setConnectionStatus("Connected");
          setConnectionError("");
        };

        ws.onmessage = (event) => {
          try {
            const message = JSON.parse(event.data);
            console.log("📨 Received:", message);
            handleWebSocketMessage(message);
          } catch (error) {
            console.error("Error parsing WebSocket message:", error);
          }
        };

        ws.onclose = (event) => {
          console.log("🔌 WebSocket disconnected:", event.code, event.reason);
          setConnectionStatus("Disconnected");
          setIsStreaming(false);
          setCurrentAgent(null);
          
          // Attempt to reconnect after 3 seconds
          setTimeout(() => {
            if (!wsRef.current || wsRef.current.readyState === WebSocket.CLOSED) {
              connectWebSocket();
            }
          }, 3000);
        };

        ws.onerror = (error) => {
          console.error("❌ WebSocket error:", error);
          setConnectionError("WebSocket connection error. Retrying...");
          setConnectionStatus("Error");
        };

      } catch (error) {
        console.error("Failed to create WebSocket connection:", error);
        setConnectionError("Failed to connect to server");
      }
    };

    connectWebSocket();

    // Cleanup on unmount
    return () => {
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, []);

  const handleWebSocketMessage = (message: any) => {
    const { type, data } = message;

    switch (type) {
      case "status":
        if (data.step === "received" || data.step === "accepted") {
          setCurrentAgent({ agent: "System", content: "Request accepted, starting agents..." });
        } else if (data.step === "group:start") {
          setCurrentAgent({ agent: "AG2", content: "Agents are collaborating..." });
        } else if (data.step === "group:done") {
          setCurrentAgent({ agent: "Finalizing", content: "Completing response..." });
        }
        break;

      case "agent_message":
        if (data.agent && data.content) {
          setCurrentAgent({ 
            agent: data.agent, 
            content: `${data.agent} is working...` 
          });
        }
        break;

      case "data":
        if (data.final) {
          // Add assistant message with final content
          const assistantMessage: Message = {
            id: generateId(),
            role: "assistant",
            content: data.final,
            timestamp: Date.now(),
          };

          setMessages(prev => [...prev, assistantMessage]);
          
          // Clean up
          setIsStreaming(false);
          setCurrentAgent(null);
        }
        break;

      case "error":
        console.error("Server error:", data.message);
        setConnectionError(data.message);
        setIsStreaming(false);
        setCurrentAgent(null);
        break;

      default:
        console.log("Unknown message type:", type, data);
    }
  };

  const generateId = () => Date.now().toString(36) + Math.random().toString(36).substr(2);

  const sendMessage = () => {
    const topic = input.trim();
    if (!topic || isStreaming || !wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      return;
    }

    console.log("Sending topic:", topic);
    setConnectionError("");
    setInput("");

    // Add user message
    const userMessage: Message = {
      id: generateId(),
      role: "user",
      content: topic,
      timestamp: Date.now(),
    };

    setMessages(prev => [...prev, userMessage]);
    setIsStreaming(true);
    setCurrentAgent({ agent: "Connecting", content: "Initializing agents..." });

    // Send message to WebSocket
    const message = {
      type: "generate_joke",
      topic: topic
    };

    wsRef.current.send(JSON.stringify(message));
  };

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  return (
    <div style={{ 
      display: "flex", 
      flexDirection: "column", 
      height: "100vh", 
      backgroundColor: "#f7f8fc",
      fontFamily: "system-ui, -apple-system, sans-serif" 
    }}>
      {/* Header */}
      <div style={{ 
        padding: "16px 24px", 
        backgroundColor: "#ffffff", 
        borderBottom: "1px solid #e1e5e9",
        boxShadow: "0 1px 3px rgba(0,0,0,0.1)"
      }}>
        <h1 style={{ 
          margin: 0, 
          fontSize: "20px", 
          fontWeight: "600", 
          color: "#1f2937" 
        }}>
          🤖 AG2 WebSocket Joke Generator
        </h1>
        <p style={{ 
          margin: "4px 0 0 0", 
          fontSize: "14px", 
          color: "#6b7280" 
        }}>
          WebSocket connection: <span style={{ 
            color: connectionStatus === "Connected" ? "#10b981" : "#ef4444",
            fontWeight: "600"
          }}>{connectionStatus}</span>
        </p>
        {connectionError && (
          <div style={{ 
            marginTop: "8px", 
            padding: "8px 12px", 
            backgroundColor: "#fee2e2", 
            color: "#dc2626", 
            borderRadius: "6px", 
            fontSize: "12px" 
          }}>
            {connectionError}
          </div>
        )}
      </div>

      {/* Messages Area */}
      <div style={{ 
        flex: 1, 
        overflowY: "auto", 
        padding: "24px",
        display: "flex",
        flexDirection: "column",
        gap: "16px"
      }}>
        {messages.length === 0 && !isStreaming && (
          <div style={{ 
            textAlign: "center", 
            padding: "60px 20px", 
            color: "#6b7280" 
          }}>
            <div style={{ fontSize: "48px", marginBottom: "16px" }}>😄</div>
            <h2 style={{ fontSize: "24px", marginBottom: "8px", color: "#1f2937" }}>
              Welcome to AG2 WebSocket Joke Generator!
            </h2>
            <p style={{ fontSize: "16px", lineHeight: "1.5" }}>
              Type a topic below and watch our AI agents collaborate over WebSocket to create the perfect joke!
            </p>
          </div>
        )}

        {messages.map(message => (
          <div
            key={message.id}
            style={{
              display: "flex",
              justifyContent: message.role === "user" ? "flex-end" : "flex-start",
              marginBottom: "4px"
            }}
          >
            <div
              style={{
                maxWidth: "70%",
                padding: "12px 16px",
                borderRadius: "18px",
                backgroundColor: message.role === "user" ? "#007bff" : "#ffffff",
                color: message.role === "user" ? "white" : "#1f2937",
                border: message.role === "assistant" ? "1px solid #e1e5e9" : "none",
                boxShadow: "0 1px 2px rgba(0,0,0,0.1)",
                fontSize: "14px",
                lineHeight: "1.4",
                whiteSpace: "pre-wrap"
              }}
            >
              {message.role === "assistant" && (
                <div style={{ 
                  fontSize: "12px", 
                  color: "#6b7280", 
                  marginBottom: "6px",
                  fontWeight: "500"
                }}>
                  🤖 AG2 WebSocket Assistant
                </div>
              )}
              {message.content}
              <div style={{ 
                fontSize: "10px", 
                opacity: 0.7, 
                marginTop: "4px",
                textAlign: message.role === "user" ? "right" : "left"
              }}>
                {new Date(message.timestamp).toLocaleTimeString()}
              </div>
            </div>
          </div>
        ))}

        {/* Agent Status/Typing Indicator */}
        {isStreaming && currentAgent && (
          <div style={{
            display: "flex",
            justifyContent: "flex-start",
            marginBottom: "4px"
          }}>
            <div style={{
              maxWidth: "70%",
              padding: "12px 16px",
              borderRadius: "18px",
              backgroundColor: "#f3f4f6",
              border: "1px solid #e1e5e9",
              fontSize: "14px",
              color: "#4b5563",
              display: "flex",
              alignItems: "center",
              gap: "8px"
            }}>
              <div style={{
                display: "flex",
                gap: "2px"
              }}>
                <div style={{
                  width: "8px",
                  height: "8px",
                  backgroundColor: "#007bff",
                  borderRadius: "50%",
                  animation: "pulse 1.4s ease-in-out infinite"
                }} />
                <div style={{
                  width: "8px",
                  height: "8px", 
                  backgroundColor: "#007bff",
                  borderRadius: "50%",
                  animation: "pulse 1.4s ease-in-out 0.2s infinite"
                }} />
                <div style={{
                  width: "8px",
                  height: "8px",
                  backgroundColor: "#007bff", 
                  borderRadius: "50%",
                  animation: "pulse 1.4s ease-in-out 0.4s infinite"
                }} />
              </div>
              <span>
                <strong>{currentAgent.agent}</strong> is thinking...
              </span>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input Area */}
      <div style={{ 
        padding: "16px 24px", 
        backgroundColor: "#ffffff", 
        borderTop: "1px solid #e1e5e9",
        boxShadow: "0 -1px 3px rgba(0,0,0,0.1)"
      }}>
        <div style={{ 
          display: "flex", 
          gap: "12px", 
          alignItems: "flex-end",
          maxWidth: "800px",
          margin: "0 auto"
        }}>
          <input
            ref={inputRef}
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyPress={handleKeyPress}
            placeholder="Ask for a joke about anything... (e.g., 'programming', 'cats', 'Monday mornings')"
            disabled={isStreaming || connectionStatus !== "Connected"}
            style={{
              flex: 1,
              padding: "12px 16px",
              border: "2px solid #e1e5e9",
              borderRadius: "24px",
              fontSize: "14px",
              outline: "none",
              backgroundColor: isStreaming || connectionStatus !== "Connected" ? "#f9fafb" : "#ffffff",
              transition: "border-color 0.2s ease"
            }}
            onFocus={(e) => e.target.style.borderColor = "#007bff"}
            onBlur={(e) => e.target.style.borderColor = "#e1e5e9"}
          />
          <button
            onClick={sendMessage}
            disabled={isStreaming || !input.trim() || connectionStatus !== "Connected"}
            style={{
              padding: "12px 20px",
              backgroundColor: (isStreaming || !input.trim() || connectionStatus !== "Connected") ? "#9ca3af" : "#007bff",
              color: "white",
              border: "none",
              borderRadius: "24px",
              cursor: (isStreaming || !input.trim() || connectionStatus !== "Connected") ? "not-allowed" : "pointer",
              fontSize: "14px",
              fontWeight: "600",
              transition: "background-color 0.2s ease",
              display: "flex",
              alignItems: "center",
              gap: "6px"
            }}
          >
            {isStreaming ? (
              <>
                <div style={{
                  width: "16px",
                  height: "16px",
                  border: "2px solid #ffffff",
                  borderTop: "2px solid transparent",
                  borderRadius: "50%",
                  animation: "spin 1s linear infinite"
                }} />
                Generating...
              </>
            ) : (
              <>
                🚀 Generate Joke
              </>
            )}
          </button>
        </div>
        <div style={{ 
          fontSize: "12px", 
          color: "#6b7280", 
          marginTop: "8px",
          textAlign: "center",
          maxWidth: "800px",
          margin: "8px auto 0"
        }}>
          Press Enter to send • Real-time WebSocket communication with AG2 agents
        </div>
      </div>

      {/* CSS Animations */}
      <style jsx>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; transform: scale(1); }
          50% { opacity: 0.5; transform: scale(0.8); }
        }
        @keyframes spin {
          0% { transform: rotate(0deg); }
          100% { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  );
}
