/**
 * CodeBackground - Semi-transparent code/decorative characters floating in background.
 * Fixed dark theme — all colors hardcoded.
 */

import { memo, useMemo } from 'react';

const CODE_SNIPPETS = [
  'const agent = new Agent()',
  'await tool.execute()',
  'function* stream()',
  'import { LLM } from "ai"',
  'const { data } = await fetch()',
  'export async function handler()',
  'const result = await chain.invoke()',
  'useEffect(() => { init() }, [])',
  'const schema = z.object({})',
  'return Response.json(data)',
  'const session = await create()',
  'class ToolRegistry {',
  'const memory = new Buffer()',
  'async function* generate()',
  'const embedding = await model()',
  'const { messages } = useChat()',
  'export const runtime = "edge"',
  'const vector = await search()',
  'const prompt = template.format()',
  'await db.insert(document)',
  'const stream = new ReadableStream()',
  'const token = await auth()',
  'const rate = new RateLimiter()',
  'const cache = new LRUCache()',
  'const queue = new PriorityQueue()',
  'const graph = new StateGraph()',
  'const node = graph.addNode()',
  'const edge = graph.addEdge()',
  'const config = { temperature: 0.7 }',
  'const tools = [search, calculator]',
];

interface CodeChar {
  id: number;
  text: string;
  x: number;
  y: number;
  opacity: number;
  fontSize: number;
  animationDelay: number;
  animationDuration: number;
}

function generateChars(count: number): CodeChar[] {
  const chars: CodeChar[] = [];
  for (let i = 0; i < count; i++) {
    chars.push({
      id: i,
      text: CODE_SNIPPETS[i % CODE_SNIPPETS.length],
      x: Math.random() * 100,
      y: Math.random() * 100,
      opacity: 0.03 + Math.random() * 0.05,
      fontSize: 9 + Math.random() * 4,
      animationDelay: Math.random() * 5,
      animationDuration: 8 + Math.random() * 12,
    });
  }
  return chars;
}

function CodeBackground() {
  const chars = useMemo(() => generateChars(30), []);

  return (
    <div
      className="dag-code-bg"
      style={{
        position: 'absolute',
        inset: 0,
        overflow: 'hidden',
        pointerEvents: 'none',
        zIndex: 0,
      }}
    >
      {chars.map((ch) => (
        <span
          key={ch.id}
          style={{
            position: 'absolute',
            left: `${ch.x}%`,
            top: `${ch.y}%`,
            opacity: ch.opacity,
            fontSize: `${ch.fontSize}px`,
            fontFamily: '"Fira Code", "Cascadia Code", "JetBrains Mono", monospace',
            color: '#4A6FA5',
            whiteSpace: 'nowrap',
            animation: `dag-float ${ch.animationDuration}s ease-in-out infinite`,
            animationDelay: `${ch.animationDelay}s`,
          }}
        >
          {ch.text}
        </span>
      ))}
    </div>
  );
}

export default memo(CodeBackground);