# Project Brief

## Project Overview

**AgentHub** is a modular AI Agent collection framework that provides a modern web interface for experimenting with LangChain and LangGraph agents. Built with FastAPI (backend) and React (frontend), featuring a clean separation of concerns and modern development practices.

This is the GUI version of the [AgentLab](https://github.com/realyinchen/AgentLab) project.

Inspired by: [agent-service-toolkit](https://github.com/JoshuaC215/agent-service-toolkit)

## Core Goals

1. **Provide a modern web interface** for experimenting with LangChain and LangGraph agents
2. **Enable easy agent development** with a clean architecture and reusable components
3. **Support real-time streaming** of agent responses via Server-Sent Events (SSE)
4. **Offer multi-agent support** with a registry pattern for easy agent addition
5. **Support Thinking Mode** for models like DeepSeek-R1 and Qwen3 with structured reasoning output

## Target Users

Students and developers who want to efficiently showcase their LangChain and LangGraph learning achievements in an interactive, visual format.

## Key Features

- **FastAPI Backend** — Robust RESTful API layer for agent orchestration and async task management
- **Modern React Frontend** — Interactive web interface built with Vite + React + TypeScript + Tailwind CSS + shadcn/ui
- **LangChain/LangGraph Integration** — Easy to build, design, and connect multi-agent reasoning workflows
- **Streaming & Event-Driven** — Real-time token streaming and agent execution event visualization
- **Thinking Mode** — Toggle between standard and thinking modes for deeper reasoning
- **Multi-language Support** — Built-in internationalization with English and Chinese translations
- **Dark/Light Theme** — Customizable theme support for comfortable viewing

## Available Agents

1. **chatbot** — Conversational agent with tools:
   - `get_current_time` — Get current time in any timezone
   - `web_search` — Search the web for real-time information (via Tavily)
   - Supports real-time queries (weather, news, current time, etc.)

2. **rag-agent** — Advanced RAG agent with:
   - Question routing (vector store / web search / direct answer)
   - Qdrant vector store retrieval
   - Document relevance grading
   - Hallucination grading
   - Answer quality grading
   - Tavily web search fallback
   - Reporter node for final answer formatting

## Branches

- **main** (default): Stable release branch with tested, production-ready features
- **dev**: Development branch with the latest features and improvements

## Repository

- **GitHub**: https://github.com/realyinchen/AgentHub