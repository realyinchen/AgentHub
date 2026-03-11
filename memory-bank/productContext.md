# Product Context

## Why AgentHub Exists

AgentHub was created to bridge the gap between learning LangChain/LangGraph concepts and presenting those learnings in a polished, interactive format. Rather than running agents from the command line or Jupyter notebooks, AgentHub provides a proper web application interface — evolving from a simple Streamlit demo to a modern, professional web app.

## Problems It Solves

1. **Presentation Gap**: LangChain/LangGraph agents are typically demonstrated via CLI or notebooks — AgentHub provides a professional, browser-based GUI.
2. **Multi-Agent Management**: Centralizes multiple agents in one place with a unified API and intuitive UI.
3. **Conversation Persistence**: Maintains conversation history across sessions via PostgreSQL checkpointing.
4. **Real-time Feedback**: Streams agent responses token-by-token so users see progress immediately.
5. **Limited Customization & Responsiveness** (addressed via current migration): Original Streamlit frontend lacks modern interactivity, mobile support, custom styling freedom, and extensibility for future features.

## How It Works (Target State after Frontend Migration)

### User Flow
1. User opens the modern React frontend at `http://localhost:9527`.
2. User sees a clean layout: top-left logo, agent selector dropdown, left sidebar for conversation history, main right area for chat.
3. User selects an agent from the dropdown (dynamically loaded from backend).
4. User types a message in the chat input and submits.
5. Frontend sends request to FastAPI backend (`/api/v1/chat/stream` endpoints).
6. Backend routes to the appropriate LangGraph agent (may involve tool calls, RAG retrieval, etc.).
7. Response streams back in real-time via Server-Sent Events (SSE), rendered progressively in the chat UI with proper formatting for messages, tool calls, and results.

### Agent Selection & Persistence
- Available agents loaded dynamically from PostgreSQL `agents` table.
- Active agents use a shared LangGraph checkpointer for state persistence.
- Conversations tied to `agent_id` + `thread_id` for routing and history resumption.
- Sidebar allows creating new threads, switching between existing ones, with visual indicators.

## User Experience Goals

- **Simplicity**: One-click agent selection, natural chat interface with minimal friction.
- **Transparency**: Real-time streaming shows agent "thinking" process (token-by-token typing effect, tool call indicators).
- **Persistence & Discoverability**: Conversations saved/resumable; easy access to history; API docs via Swagger at `http://localhost:8080/docs`.
- **Modern & Responsive** (post-migration priorities):
  - Clean, customizable UI with Tailwind CSS (dark mode support, responsive layout for desktop/mobile).
  - Smooth interactions: auto-scroll chat, loading states, error handling.
  - Better visual feedback for complex agent flows (e.g., tool calls shown as expandable cards).
  - Future-proof extensibility: easier to add features like multi-modal input, agent visualization, or integrations.

This migration keeps the powerful FastAPI + LangGraph backend unchanged while upgrading the frontend to match professional web app standards.