/**
 * Optimized chat state management hook
 * 
 * This hook provides:
 * - Memoized selectors to prevent unnecessary re-renders
 * - Message limit to prevent memory leaks
 * - Optimized state updates
 */

import { useState, useCallback, useMemo, useRef, useEffect } from 'react';
import type { LocalChatMessage } from '@/types/chat';

// Maximum number of messages to keep in memory to prevent leaks
const MAX_MESSAGES = 100;
const MAX_MESSAGE_SEQUENCE = 1000;

interface UseOptimizedChatReturn {
  // State
  messages: LocalChatMessage[];
  messageSequence: string[];
  streamingContent: string;
  streamingReasoning: string;
  isStreaming: boolean;

  // Actions
  addMessage: (message: LocalChatMessage) => void;
  updateMessage: (id: string, updates: Partial<LocalChatMessage>) => void;
  removeMessage: (id: string) => void;
  clearMessages: () => void;
  appendStreamingContent: (content: string) => void;
  appendStreamingReasoning: (reasoning: string) => void;
  startStreaming: () => void;
  stopStreaming: () => void;

  // Memoized selectors
  aiMessageSessionIds: string[];
  latestUserMessageId: string | null;
}

export function useOptimizedChat(): UseOptimizedChatReturn {
  // Core state
  const [messages, setMessages] = useState<LocalChatMessage[]>([]);
  const [messageSequence, setMessageSequence] = useState<string[]>([]);
  const [streamingContent, setStreamingContent] = useState('');
  const [streamingReasoning, setStreamingReasoning] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);

  // Refs for streaming to avoid re-renders on every token
  const streamingContentRef = useRef('');
  const streamingReasoningRef = useRef('');
  const streamingTimerRef = useRef<NodeJS.Timeout | null>(null);

  // Limit messages to prevent memory leaks
  const trimMessages = useCallback((msgs: LocalChatMessage[]) => {
    if (msgs.length > MAX_MESSAGES) {
      return msgs.slice(-MAX_MESSAGES);
    }
    return msgs;
  }, []);

  const trimSequence = useCallback((seq: string[]) => {
    if (seq.length > MAX_MESSAGE_SEQUENCE) {
      return seq.slice(-MAX_MESSAGE_SEQUENCE);
    }
    return seq;
  }, []);

  // Add message with automatic trimming
  const addMessage = useCallback((message: LocalChatMessage) => {
    setMessages(prev => {
      const newMessages = [...prev, message];
      return trimMessages(newMessages);
    });
    setMessageSequence(prev => {
      const newSeq = [...prev, message.id];
      return trimSequence(newSeq);
    });
  }, [trimMessages, trimSequence]);

  // Update existing message
  const updateMessage = useCallback((id: string, updates: Partial<LocalChatMessage>) => {
    setMessages(prev =>
      prev.map(msg =>
        msg.id === id ? { ...msg, ...updates } : msg
      )
    );
  }, []);

  // Remove message
  const removeMessage = useCallback((id: string) => {
    setMessages(prev => prev.filter(msg => msg.id !== id));
    setMessageSequence(prev => prev.filter(seqId => seqId !== id));
  }, []);

  // Clear all messages
  const clearMessages = useCallback(() => {
    setMessages([]);
    setMessageSequence([]);
    setStreamingContent('');
    setStreamingReasoning('');
    streamingContentRef.current = '';
    streamingReasoningRef.current = '';
  }, []);

  // Optimized streaming - batch updates
  const appendStreamingContent = useCallback((content: string) => {
    streamingContentRef.current += content;

    // Debounce state update
    if (streamingTimerRef.current) {
      clearTimeout(streamingTimerRef.current);
    }

    streamingTimerRef.current = setTimeout(() => {
      setStreamingContent(streamingContentRef.current);
    }, 16); // ~60fps
  }, []);

  const appendStreamingReasoning = useCallback((reasoning: string) => {
    streamingReasoningRef.current += reasoning;

    if (streamingTimerRef.current) {
      clearTimeout(streamingTimerRef.current);
    }

    streamingTimerRef.current = setTimeout(() => {
      setStreamingReasoning(streamingReasoningRef.current);
    }, 16);
  }, []);

  const startStreaming = useCallback(() => {
    setIsStreaming(true);
    streamingContentRef.current = '';
    streamingReasoningRef.current = '';
    setStreamingContent('');
    setStreamingReasoning('');
  }, []);

  const stopStreaming = useCallback(() => {
    setIsStreaming(false);
    // Final flush
    setStreamingContent(streamingContentRef.current);
    setStreamingReasoning(streamingReasoningRef.current);
    if (streamingTimerRef.current) {
      clearTimeout(streamingTimerRef.current);
    }
  }, []);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (streamingTimerRef.current) {
        clearTimeout(streamingTimerRef.current);
      }
    };
  }, []);

  // Memoized selectors - expensive computations
  const aiMessageSessionIds = useMemo(() => {
    const result: string[] = [];
    for (let i = 0; i < messageSequence.length; i++) {
      const msgId = messageSequence[i];
      const msg = messages.find(m => m.id === msgId);
      if (msg?.role === 'assistant' && msg.sessionId) {
        if (i === 0 || messageSequence[i - 1] !== msgId) {
          result.push(msgId);
        }
      }
    }
    return result;
  }, [messageSequence, messages]);

  const latestUserMessageId = useMemo(() => {
    for (let i = messageSequence.length - 1; i >= 0; i--) {
      const msgId = messageSequence[i];
      const msg = messages.find(m => m.id === msgId);
      if (msg?.role === 'user') {
        return msgId;
      }
    }
    return null;
  }, [messageSequence, messages]);

  return {
    messages,
    messageSequence,
    streamingContent,
    streamingReasoning,
    isStreaming,
    addMessage,
    updateMessage,
    removeMessage,
    clearMessages,
    appendStreamingContent,
    appendStreamingReasoning,
    startStreaming,
    stopStreaming,
    aiMessageSessionIds,
    latestUserMessageId,
  };
}
