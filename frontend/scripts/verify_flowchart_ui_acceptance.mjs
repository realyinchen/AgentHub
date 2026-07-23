import path from "node:path"
import { fileURLToPath } from "node:url"

import React from "react"
import { renderToString } from "react-dom/server"
import { createServer } from "vite"

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)
const frontendRoot = path.resolve(__dirname, "..")

function assertIncludes(html, needle) {
  if (!html.includes(needle)) {
    throw new Error(`Expected rendered UI to include: ${needle}`)
  }
}

const server = await createServer({
  root: frontendRoot,
  logLevel: "error",
  appType: "custom",
  server: { middlewareMode: true },
})

try {
  const { FlowchartUiAcceptanceApp } = await server.ssrLoadModule(
    "/src/dev/flowchart-ui-acceptance.tsx",
  )
  const html = renderToString(React.createElement(FlowchartUiAcceptanceApp))

  assertIncludes(html, "Flowchart route panels")
  assertIncludes(html, "Book turn orchestration")
  assertIncludes(html, "book-turn-orchestration-v1")
  assertIncludes(html, "search_books")
  assertIncludes(html, "Suppression explanation")
  assertIncludes(html, "history only")
  assertIncludes(html, "Dune")
  assertIncludes(html, "Already read in a previous session.")
  assertIncludes(html, "Research report")
  assertIncludes(html, "Verified findings")
  assertIncludes(html, "Research final answer")
  assertIncludes(html, "Verified facts used")
  assertIncludes(html, "Recommendation research report")
  assertIncludes(html, "Recommended with verified research")
  assertIncludes(html, "Suppressed candidates")
  assertIncludes(html, "Flowchart Fresh Novel")

  console.log("verify_flowchart_ui_acceptance: ok")
} finally {
  await server.close()
}
