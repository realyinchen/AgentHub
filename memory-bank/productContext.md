# Product Context: AgentHub

## Why This Project Exists

AgentHub is the GUI version of AgentLab, created to provide a visual and interactive platform for experimenting with LangChain and LangGraph agents. While AgentLab focuses on command-line experimentation, AgentHub brings these capabilities to a modern web interface, making it easier for users to interact with and visualize agent behaviors.

## Problems It Solves

1. **Learning Visualization** — Students learning LangChain/LangGraph need a visual way to see how agents reason, use tools, and stream responses
2. **Agent Experimentation** — Developers want to quickly test different agent configurations without writing code
3. **Real-time Feedback** — Users need immediate visual feedback on agent thinking processes and tool calls
4. **Multi-agent Comparison** — Ability to compare different agent behaviors and tool sets side by side

## How It Works

### User Flow
1. User selects an agent (chatbot or navigator) from the web interface
2. User enters a message/query in the chat interface
3. Agent processes the request using LangGraph workflow
4. Real-time streaming shows:
   - Token-by-token response generation
   - Thinking process (when enabled)
   - Tool calls and their results
5. User can quote previous messages to continue conversation with context

### Key Features

- **Thinking Mode** — Toggle between standard and thinking modes for deeper reasoning with separate UI for thought process and tool calls
- **Quote Messages** — Quote any historical message to continue the conversation with context. Quotes persist across page refreshes
- **Multi-language Support** — Built-in internationalization with English and Chinese translations
- **Dark/Light Theme** — Customizable theme support for comfortable viewing
- **Image Zoom & Drag** — Click any image in markdown to zoom in/out and drag to pan
- **Token Stats Display** — Real-time token consumption visualization with vertical bar chart showing Input/Output/Reasoning tokens

## User Experience Goals

- **Responsive** — Instant feedback with streaming responses
- **Intuitive** — Clean, modern UI that doesn't require documentation to use
- **Informative** — Clear visualization of agent reasoning and tool usage
- **Accessible** — Multi-language support and theme options for different user preferences