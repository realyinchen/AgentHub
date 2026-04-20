# Project Brief: AgentHub

## Overview

AgentHub is a modular AI Agent collection framework that provides a modern web interface for experimenting with LangChain and LangGraph agents. It is the GUI version of the [AgentLab](https://github.com/realyinchen/AgentLab) project.

## Core Requirements

1. **FastAPI Backend** — Robust RESTful API layer for agent orchestration and async task management
2. **Modern React Frontend** — Interactive web interface built with Vite + React + TypeScript + Tailwind CSS + shadcn/ui
3. **LangChain/LangGraph Integration** — Easy to build, design, and connect multi-agent reasoning workflows with visualization
4. **Streaming & Event-Driven** — Real-time token streaming and agent execution event visualization
5. **Database Support** — PostgreSQL for persistent storage, Qdrant for vector search (RAG)

## Project Goals

- Provide a GUI platform for students and developers to showcase their LangChain and LangGraph learning achievements
- Enable interactive, visual experimentation with AI agents
- Support multiple agent types with different tool sets
- Offer real-time streaming responses and thinking mode for deeper reasoning

## Target Audience

Students and developers who want to efficiently showcase their LangChain and LangGraph learning achievements in an interactive, visual format.

## Project Scope

### In Scope
- Agent orchestration and execution
- Real-time streaming responses
- Multi-language support (English, Chinese)
- Dark/Light theme support
- Token usage tracking
- Image zoom and drag in markdown
- Quote messages for context continuation
- Docker deployment

### Out of Scope (Current)
- Unit/integration tests
- Agent graph visualization in React UI
- Conversation search and filtering
- Document upload UI for Qdrant population