const fs = require('fs');
const path = require('path');

const file = path.join(__dirname, '..', 'src', 'index.css');
let c = fs.readFileSync(file, 'utf8');

const lightInsert = `  /* ReactFlow-specific colors */
  --dag-rf-background: #EEF2F6;
  --dag-rf-grid: #CBD5E1;
  --dag-rf-controls-bg: #FFFFFF;
  --dag-rf-controls-border: #E2E8F0;
  --dag-rf-controls-text: #64748B;
  --dag-rf-controls-hover-bg: #F1F5F9;
  --dag-rf-controls-hover-text: #1E293B;
  --dag-rf-minimap-bg: #F8FAFC;
  --dag-rf-minimap-mask: rgba(238, 242, 246, 0.7);
  --dag-rf-node-label: #1A1A1A;
  --dag-rf-node-subtitle: #666666;

  /* Node glow colors */
  --dag-node-human-glow: rgba(148, 163, 184, 0.4);
  --dag-node-ai-glow: rgba(59, 130, 246, 0.4);
  --dag-node-final-glow: rgba(34, 197, 94, 0.4);
  --dag-node-tool-glow: rgba(168, 85, 247, 0.4);`;

const darkInsert = `  /* ReactFlow-specific colors */
  --dag-rf-background: #0A0E17;
  --dag-rf-grid: #1E293B;
  --dag-rf-controls-bg: #1A2332;
  --dag-rf-controls-border: #334155;
  --dag-rf-controls-text: #94A3B8;
  --dag-rf-controls-hover-bg: #1E293B;
  --dag-rf-controls-hover-text: #E6EDF3;
  --dag-rf-minimap-bg: #0F172A;
  --dag-rf-minimap-mask: rgba(10, 14, 23, 0.8);
  --dag-rf-node-label: #E6EDF3;
  --dag-rf-node-subtitle: #9FB0C3;

  /* Node glow colors */
  --dag-node-human-glow: rgba(148, 163, 184, 0.5);
  --dag-node-ai-glow: rgba(96, 165, 250, 0.5);
  --dag-node-final-glow: rgba(74, 222, 128, 0.5);
  --dag-node-tool-glow: rgba(192, 132, 252, 0.5);`;

// Insert after light theme DAG variables (before .dark)
c = c.replace(
  '  --dag-edge: rgba(0, 0, 0, 0.25);\r\n}\r\n\r\n.dark {',
  '  --dag-edge: rgba(0, 0, 0, 0.25);\r\n\r\n' + lightInsert + '\r\n}\r\n\r\n.dark {'
);

// Insert after dark theme DAG variables (before @theme inline)
c = c.replace(
  '  --dag-edge: rgba(255, 255, 255, 0.25);\r\n}\r\n\r\n@theme inline {',
  '  --dag-edge: rgba(255, 255, 255, 0.25);\r\n\r\n' + darkInsert + '\r\n}\r\n\r\n@theme inline {'
);

fs.writeFileSync(file, c);
console.log('Done - added CSS variables to index.css');