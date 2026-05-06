/**
 * NodeDetailSheet - Side panel showing node input/output details.
 * Larger panel (520px), copy buttons on input/output sections.
 * Flat log-style panel, no glow.
 * Uses CSS variables for theming.
 */

import { useState, useCallback } from 'react';
import { User, Wrench, Brain, Bot, Copy, Check, X } from 'lucide-react';
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from '@/components/ui/sheet';
import type { DAGNodeData } from '../../types/dag';
import { formatToolOutput } from '../../utils/dagBuilder';
import { useI18n } from '@/i18n';

interface NodeDetailSheetProps {
  nodeData: DAGNodeData | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

function CopyButton({ text }: { text: string }) {
  const { t } = useI18n();
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
        background: copied ? 'var(--dag-success-light)' : 'rgba(255,255,255,0.06)',
        border: `1px solid ${copied ? 'var(--dag-success-border)' : 'var(--dag-border)'}`,
        color: copied ? 'var(--dag-success)' : 'var(--dag-text-dim)',
      }}
    >
      {copied ? <Check className="w-3 h-3" /> : <Copy className="w-3 h-3" />}
      {copied ? t('common.copied') : t('common.copy')}
    </button>
  );
}

function NodeDetailSheet({ nodeData, open, onOpenChange }: NodeDetailSheetProps) {
  const { t } = useI18n();

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
          title: t('process.user') || 'User Message',
          description: `Step #${nodeData.stepNumber}`,
          accentColor: 'var(--dag-node-user)',
          accentLight: 'var(--dag-node-user-light)',
          accentBorder: 'var(--dag-node-user-border)',
        };
      case 'ai':
        return {
          icon: nodeData.thinking ? <Brain className="w-5 h-5" /> : <Bot className="w-5 h-5" />,
          title: nodeData.isFinal ? (t('process.ai') || 'AI Response') : (t('process.ai') || 'AI Processing'),
          description: nodeData.modelName
            ? `${nodeData.modelName} · Step #${nodeData.stepNumber}`
            : `Step #${nodeData.stepNumber}`,
          accentColor: nodeData.isFinal ? 'var(--dag-success)' : 'var(--dag-node-ai)',
          accentLight: nodeData.isFinal ? 'var(--dag-success-light)' : 'var(--dag-node-ai-light)',
          accentBorder: nodeData.isFinal ? 'var(--dag-success-border)' : 'var(--dag-node-ai-border)',
        };
      case 'tool':
        return {
          icon: <Wrench className="w-5 h-5" />,
          title: nodeData.toolName,
          description: `Step #${nodeData.stepNumber}`,
          accentColor: 'var(--dag-node-tool)',
          accentLight: 'var(--dag-node-tool-light)',
          accentBorder: 'var(--dag-node-tool-border)',
        };
      case 'subagent':
        return {
          icon: <Bot className="w-5 h-5" />,
          title: nodeData.agentName,
          description: `SubAgent · Step #${nodeData.stepNumber}`,
          accentColor: 'var(--dag-node-ai)',
          accentLight: 'var(--dag-node-ai-light)',
          accentBorder: 'var(--dag-node-ai-border)',
        };
      default:
        return null;
    }
  };

  const getInput = (): { label: string; content: string } | null => {
    switch (nodeData.type) {
      case 'human':
        return nodeData.content ? { label: t('process.input') || 'Message', content: nodeData.content } : null;
      case 'ai':
        return nodeData.thinking ? { label: t('process.thinking') || 'Thinking', content: nodeData.thinking } : null;
      case 'tool':
        if (nodeData.toolArgs && Object.keys(nodeData.toolArgs).length > 0) {
          return { label: t('process.arguments') || 'Arguments', content: JSON.stringify(nodeData.toolArgs, null, 2) };
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
        return nodeData.content ? { label: t('process.content') || 'Response', content: nodeData.content } : null;
      case 'tool':
        return nodeData.toolOutput
          ? { label: t('process.content') || 'Result', content: formatToolOutput(nodeData.toolOutput, 5000) }
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
          background: 'var(--dag-bg-panel)',
          borderLeft: '1px solid var(--dag-border)',
          borderRadius: '16px 0 0 16px',
          boxShadow: '0 4px 12px rgba(0, 0, 0, 0.4)',
        }}
      >
        {/* Custom close button */}
        <button
          onClick={() => onOpenChange(false)}
          className="absolute top-4 right-4 w-8 h-8 flex items-center justify-center rounded-lg transition-colors hover:bg-white/10"
          style={{
            background: 'rgba(255,255,255,0.04)',
            border: '1px solid var(--dag-border)',
            color: 'var(--dag-text-dim)',
            zIndex: 10,
            cursor: 'pointer',
          }}
        >
          <X className="w-4 h-4" />
        </button>
        {/* Header */}
        <SheetHeader
          className="pb-4"
          style={{ borderBottom: '1px solid var(--dag-border)' }}
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
                style={{ color: 'var(--dag-text-primary)' }}
              >
                {headerInfo.title}
              </SheetTitle>
              <SheetDescription
                className="text-sm mt-0.5"
                style={{ color: 'var(--dag-text-dim)' }}
              >
                {headerInfo.description}
              </SheetDescription>
            </div>
          </div>
        </SheetHeader>

        <div
          className="mt-4 space-y-4 overflow-y-auto max-h-[calc(100vh-10rem)] px-1 pb-4"
        >
          {/* Input Section */}
          {input && (
            <div
              className="rounded-lg p-4"
              style={{
                background: 'var(--dag-bg-main)',
                border: '1px solid var(--dag-border)',
              }}
            >
              <div className="flex items-center justify-between mb-2">
                <span
                  className="text-xs font-medium"
                  style={{ color: 'var(--dag-text-secondary)' }}
                >
                  {input.label}
                </span>
                <CopyButton text={input.content} />
              </div>
              <pre
                className="text-sm whitespace-pre-wrap break-words font-mono overflow-auto max-h-[200px] p-3 rounded-md"
                style={{
                  background: 'rgba(255,255,255,0.02)',
                  color: 'var(--dag-text-primary)',
                }}
              >
                {input.content}
              </pre>
            </div>
          )}

          {/* Output Section */}
          {output && (
            <div
              className="rounded-lg p-4"
              style={{
                background: 'var(--dag-bg-main)',
                border: '1px solid var(--dag-border)',
              }}
            >
              <div className="flex items-center justify-between mb-2">
                <span
                  className="text-xs font-medium"
                  style={{ color: 'var(--dag-text-secondary)' }}
                >
                  {output.label}
                </span>
                <CopyButton text={output.content} />
              </div>
              <pre
                className="text-sm whitespace-pre-wrap break-words font-mono overflow-auto max-h-[200px] p-3 rounded-md"
                style={{
                  background: 'rgba(255,255,255,0.02)',
                  color: 'var(--dag-text-primary)',
                }}
              >
                {output.content}
              </pre>
            </div>
          )}

          {/* Tool Calls Section for AI nodes */}
          {nodeData.type === 'ai' && nodeData.toolCalls && nodeData.toolCalls.length > 0 && (
            <div
              className="rounded-lg p-4"
              style={{
                background: 'var(--dag-bg-main)',
                border: '1px solid var(--dag-border)',
              }}
            >
              <span
                className="text-xs font-medium"
                style={{ color: 'var(--dag-text-secondary)' }}
              >
                {t('process.toolCalls') || 'Tool Calls'} ({nodeData.toolCalls.length})
              </span>
              <div className="mt-2 space-y-2">
                {nodeData.toolCalls.map((tc, idx) => (
                  <div
                    key={idx}
                    className="text-sm p-2 rounded-md cursor-pointer"
                    style={{ background: 'var(--dag-node-tool-light)' }}
                  >
                    <span className="font-medium" style={{ color: 'var(--dag-node-tool)' }}>
                      {tc.name}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}

export default NodeDetailSheet;