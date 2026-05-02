/**
 * NodeDetailSheet - Side panel showing node input/output details.
 * Larger panel (520px), copy buttons on input/output sections.
 * Flat log-style panel, no glow.
 */

import { useState, useCallback } from 'react';
import { User, Wrench, Brain, Bot, CheckCircle, Copy, Check, X } from 'lucide-react';
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from '@/components/ui/sheet';
import type { DAGNodeData } from '../../types/dag';
import { formatToolOutput } from '../../utils/dagBuilder';
import { DARK_THEME } from '../../styles/theme';

interface NodeDetailSheetProps {
  nodeData: DAGNodeData | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Fallback for non-HTTPS contexts
      const textarea = document.createElement('textarea');
      textarea.value = text;
      textarea.style.position = 'fixed';
      textarea.style.opacity = '0';
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand('copy');
      document.body.removeChild(textarea);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  }, [text]);

  return (
    <button
      onClick={handleCopy}
      className="flex items-center gap-1 px-2 py-1 rounded-md transition-colors cursor-pointer text-xs"
      style={{
        background: copied ? DARK_THEME.successLight : 'rgba(255,255,255,0.06)',
        border: `1px solid ${copied ? DARK_THEME.successBorder : DARK_THEME.border}`,
        color: copied ? DARK_THEME.success : DARK_THEME.textDim,
      }}
      onMouseEnter={e => {
        if (!copied) {
          e.currentTarget.style.background = 'rgba(255,255,255,0.10)';
          e.currentTarget.style.color = DARK_THEME.textSecondary;
        }
      }}
      onMouseLeave={e => {
        if (!copied) {
          e.currentTarget.style.background = 'rgba(255,255,255,0.06)';
          e.currentTarget.style.color = DARK_THEME.textDim;
        }
      }}
    >
      {copied ? <Check className="w-3 h-3" /> : <Copy className="w-3 h-3" />}
      {copied ? 'Copied' : 'Copy'}
    </button>
  );
}

function NodeDetailSheet({ nodeData, open, onOpenChange }: NodeDetailSheetProps) {
  if (!nodeData) return null;

  const getNodeHeader = (): {
    icon: React.ReactNode;
    title: string;
    description: string;
    accentColor: string;
    accentLight: string;
    accentBorder: string;
  } | null => {
    switch (nodeData.type) {
      case 'human':
        return {
          icon: <User className="w-5 h-5" />,
          title: 'User Message',
          description: `Step #${nodeData.stepNumber}`,
          accentColor: DARK_THEME.nodeUser,
          accentLight: DARK_THEME.nodeUserLight,
          accentBorder: DARK_THEME.nodeUserBorder,
        };
      case 'ai':
        return {
          icon: nodeData.thinking ? <Brain className="w-5 h-5" /> : <Bot className="w-5 h-5" />,
          title: nodeData.isFinal ? 'AI Response' : 'AI Processing',
          description: nodeData.modelName
            ? `${nodeData.modelName} · Step #${nodeData.stepNumber}`
            : `Step #${nodeData.stepNumber}`,
          accentColor: nodeData.isFinal ? DARK_THEME.success : DARK_THEME.nodeAI,
          accentLight: nodeData.isFinal ? DARK_THEME.successLight : DARK_THEME.nodeAILight,
          accentBorder: nodeData.isFinal ? DARK_THEME.successBorder : DARK_THEME.nodeAIBorder,
        };
      case 'tool':
        return {
          icon: <Wrench className="w-5 h-5" />,
          title: nodeData.toolName,
          description: `Step #${nodeData.stepNumber}`,
          accentColor: DARK_THEME.nodeTool,
          accentLight: DARK_THEME.nodeToolLight,
          accentBorder: DARK_THEME.nodeToolBorder,
        };
      case 'subagent':
        return {
          icon: <Bot className="w-5 h-5" />,
          title: nodeData.agentName,
          description: `SubAgent · Step #${nodeData.stepNumber}`,
          accentColor: DARK_THEME.nodeAI,
          accentLight: DARK_THEME.nodeAILight,
          accentBorder: DARK_THEME.nodeAIBorder,
        };
      default:
        return null;
    }
  };

  const getInput = (): { label: string; content: string } | null => {
    switch (nodeData.type) {
      case 'human':
        return nodeData.content ? { label: 'Message', content: nodeData.content } : null;
      case 'ai':
        return nodeData.thinking ? { label: 'Thinking', content: nodeData.thinking } : null;
      case 'tool':
        if (nodeData.toolArgs && Object.keys(nodeData.toolArgs).length > 0) {
          return { label: 'Arguments', content: JSON.stringify(nodeData.toolArgs, null, 2) };
        }
        return null;
      case 'subagent':
        return null;
    }
  };

  const getOutput = (): { label: string; content: string } | null => {
    switch (nodeData.type) {
      case 'human':
        return null;
      case 'ai':
        return nodeData.content ? { label: 'Response', content: nodeData.content } : null;
      case 'tool':
        return nodeData.toolOutput
          ? { label: 'Result', content: formatToolOutput(nodeData.toolOutput, 5000) }
          : null;
      case 'subagent':
        return null;
    }
  };

  const headerInfo = getNodeHeader();
  const input = getInput();
  const output = getOutput();

  if (!headerInfo) return null;

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        className="!top-12 !bottom-4 !h-auto !max-h-[calc(100vh-4rem)] overflow-hidden"
        showCloseButton={false}
        style={{
          width: '520px',
          maxWidth: '520px',
          background: '#0F172A',
          borderLeft: `1px solid ${DARK_THEME.border}`,
          borderRadius: '16px 0 0 16px',
          boxShadow: DARK_THEME.shadowLg,
        }}
      >
        {/* Custom close button */}
        <button
          onClick={() => onOpenChange(false)}
          className="absolute top-4 right-4 w-8 h-8 flex items-center justify-center rounded-lg transition-all cursor-pointer"
          style={{
            background: 'rgba(255,255,255,0.04)',
            border: `1px solid ${DARK_THEME.border}`,
            color: DARK_THEME.textDim,
          }}
          onMouseEnter={e => {
            e.currentTarget.style.background = 'rgba(255,255,255,0.08)';
            e.currentTarget.style.color = DARK_THEME.textSecondary;
          }}
          onMouseLeave={e => {
            e.currentTarget.style.background = 'rgba(255,255,255,0.04)';
            e.currentTarget.style.color = DARK_THEME.textDim;
          }}
        >
          <X className="w-4 h-4" />
        </button>
        {/* Header */}
        <SheetHeader
          className="pb-4"
          style={{ borderBottom: `1px solid ${DARK_THEME.border}` }}
        >
          <div className="flex items-center gap-3">
            <div
              className="flex items-center justify-center w-10 h-10 rounded-lg flex-shrink-0"
              style={{
                background: headerInfo.accentLight,
                border: `1px solid ${headerInfo.accentBorder}`,
              }}
            >
              <span style={{ color: headerInfo.accentColor }}>{headerInfo.icon}</span>
            </div>
            <div className="flex-1 min-w-0">
              <SheetTitle
                className="text-lg font-semibold"
                style={{ color: DARK_THEME.textPrimary }}
              >
                {headerInfo.title}
              </SheetTitle>
              <SheetDescription
                className="text-sm mt-0.5"
                style={{ color: DARK_THEME.textDim }}
              >
                {headerInfo.description}
              </SheetDescription>
            </div>
          </div>
        </SheetHeader>

        <div
          className="mt-4 space-y-4 overflow-y-auto max-h-[calc(100vh-10rem)] px-1 pb-4"
          style={{ scrollbarColor: `${DARK_THEME.border} transparent` }}
        >
          {/* Input Section */}
          {input && (
            <div
              className="rounded-lg p-4"
              style={{
                background: DARK_THEME.bgMain,
                border: `1px solid ${DARK_THEME.border}`,
              }}
            >
              <div className="flex items-center justify-between mb-2">
                <span
                  className="text-xs font-medium"
                  style={{ color: DARK_THEME.textDim }}
                >
                  {input.label}
                </span>
                <CopyButton text={input.content} />
              </div>
              <div
                className="rounded-md p-3 text-sm font-mono whitespace-pre-wrap overflow-auto"
                style={{
                  background: 'rgba(255,255,255,0.02)',
                  border: `1px solid ${DARK_THEME.border}`,
                  color: DARK_THEME.textPrimary,
                  maxHeight: '400px',
                  lineHeight: '1.6',
                }}
              >
                {input.content}
              </div>
            </div>
          )}

          {/* Output Section */}
          {output && (
            <div
              className="rounded-lg p-4"
              style={{
                background: DARK_THEME.bgMain,
                border: `1px solid ${DARK_THEME.border}`,
              }}
            >
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  <span
                    className="text-xs font-medium"
                    style={{ color: DARK_THEME.textDim }}
                  >
                    {output.label}
                  </span>
                  {nodeData.type === 'tool' && (
                    <CheckCircle className="w-3.5 h-3.5" style={{ color: DARK_THEME.success }} />
                  )}
                </div>
                <CopyButton text={output.content} />
              </div>
              <div
                className="rounded-md p-3 text-sm font-mono whitespace-pre-wrap overflow-auto"
                style={{
                  background: 'rgba(255,255,255,0.02)',
                  border: `1px solid ${DARK_THEME.border}`,
                  color: DARK_THEME.textPrimary,
                  maxHeight: '400px',
                  lineHeight: '1.6',
                }}
              >
                {output.content}
              </div>
            </div>
          )}

          {/* Tool Calls list for AI node */}
          {nodeData.type === 'ai' && nodeData.toolCalls && nodeData.toolCalls.length > 0 && (
            <div
              className="rounded-lg p-4"
              style={{
                background: DARK_THEME.bgMain,
                border: `1px solid ${DARK_THEME.border}`,
              }}
            >
              <div className="flex items-center gap-2 mb-3">
                <Wrench className="w-4 h-4" style={{ color: DARK_THEME.nodeTool }} />
                <span
                  className="text-sm font-medium"
                  style={{ color: DARK_THEME.textSecondary }}
                >
                  Tool Calls ({nodeData.toolCalls.length})
                </span>
              </div>
              <div className="space-y-2">
                {nodeData.toolCalls.map((tc, idx) => (
                  <div
                    key={idx}
                    className="rounded-md p-3"
                    style={{
                      background: 'rgba(255,255,255,0.02)',
                      border: `1px solid ${DARK_THEME.border}`,
                    }}
                  >
                    <div
                      className="font-medium mb-1.5 text-sm"
                      style={{ color: DARK_THEME.textPrimary }}
                    >
                      {tc.name}
                    </div>
                    {tc.args && Object.keys(tc.args).length > 0 && (
                      <div
                        className="text-xs font-mono whitespace-pre-wrap overflow-auto rounded p-2"
                        style={{
                          background: DARK_THEME.bgPanel,
                          color: DARK_THEME.textSecondary,
                          maxHeight: '120px',
                        }}
                      >
                        {JSON.stringify(tc.args, null, 2)}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Empty state */}
          {!input && !output && nodeData.type !== 'ai' && (
            <div
              className="text-center py-8"
              style={{ color: DARK_THEME.textDim }}
            >
              No content available
            </div>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}

export default NodeDetailSheet;