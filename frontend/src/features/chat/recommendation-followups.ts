import type { LocalChatMessage, StoredToolCallInfo, ToolCallInfo } from "@/types"

export type FollowUpQuestionOption = {
  id: string
  question: string
  reason: string
  metadata: Record<string, unknown>
  bookTitle: string
  toolCallId: string
  toolName: string
  requestId: string | null
  messageId: string
}

export type FollowUpSendContext = {
  followUpQuestion?: FollowUpQuestionOption
  parentMessageId?: string | null
  parentRequestId?: string | null
}

export type FollowUpMatch = {
  question: FollowUpQuestionOption
  similarity: number
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null
  }
  return value as Record<string, unknown>
}

function cleanText(value: unknown): string {
  return String(value ?? "").trim()
}

function parseJsonRecord(value: unknown): Record<string, unknown> | null {
  if (typeof value !== "string" || !value.trim()) {
    return null
  }

  try {
    return asRecord(JSON.parse(value))
  } catch {
    return null
  }
}

function normalizeQuestion(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^\p{L}\p{N}\u4e00-\u9fff]+/gu, "")
    .trim()
}

function tokenize(value: string): string[] {
  const normalized = value
    .toLowerCase()
    .replace(/[^\p{L}\p{N}\u4e00-\u9fff]+/gu, " ")
    .trim()

  if (!normalized) {
    return []
  }

  const words = normalized.split(/\s+/).filter(Boolean)
  if (words.length > 1) {
    return words
  }

  const compact = normalized.replace(/\s+/g, "")
  if (compact.length <= 2) {
    return compact ? [compact] : []
  }

  const grams: string[] = []
  for (let index = 0; index < compact.length - 1; index += 1) {
    grams.push(compact.slice(index, index + 2))
  }
  return grams
}

function jaccardSimilarity(left: string[], right: string[]): number {
  if (left.length === 0 || right.length === 0) {
    return 0
  }

  const leftSet = new Set(left)
  const rightSet = new Set(right)
  let intersection = 0

  for (const item of leftSet) {
    if (rightSet.has(item)) {
      intersection += 1
    }
  }

  const union = leftSet.size + rightSet.size - intersection
  return union > 0 ? intersection / union : 0
}

export function getQuestionSimilarity(input: string, question: string): number {
  const normalizedInput = normalizeQuestion(input)
  const normalizedQuestion = normalizeQuestion(question)
  if (!normalizedInput || !normalizedQuestion) {
    return 0
  }

  if (normalizedInput === normalizedQuestion) {
    return 1
  }

  const shorterLength = Math.min(normalizedInput.length, normalizedQuestion.length)
  if (
    shorterLength >= 8 &&
    (normalizedInput.includes(normalizedQuestion) ||
      normalizedQuestion.includes(normalizedInput))
  ) {
    return 0.9
  }

  return jaccardSimilarity(tokenize(input), tokenize(question))
}

function storedToolsFromMessage(message: LocalChatMessage): ToolCallInfo[] {
  const toolInfo = message.custom_data?.tool_info
  if (!Array.isArray(toolInfo)) {
    return []
  }

  return toolInfo.map((item, index): ToolCallInfo => {
    const stored = item as Partial<StoredToolCallInfo>
    return {
      name: cleanText(stored.name) || "unknown",
      id: cleanText(stored.id) || `stored-tool-${index}`,
      args:
        stored.args && typeof stored.args === "object"
          ? stored.args
          : {},
      output: typeof stored.output === "string" ? stored.output : undefined,
      status: "completed",
    }
  })
}

function questionFromRecord(
  record: Record<string, unknown>,
  index: number,
  tool: ToolCallInfo,
  message: LocalChatMessage,
): FollowUpQuestionOption | null {
  const question = cleanText(record.question)
  if (!question) {
    return null
  }

  const metadata = asRecord(record.metadata) ?? {}
  const bookTitle = cleanText(metadata.book_title ?? metadata.parent_book_title)

  return {
    id: cleanText(record.id) || `${tool.id}-followup-${index}`,
    question,
    reason: cleanText(record.reason),
    metadata,
    bookTitle,
    toolCallId: tool.id,
    toolName: tool.name,
    requestId: message.request_id ?? null,
    messageId: message.local_id,
  }
}

function extractFromTools(
  tools: ToolCallInfo[],
  message: LocalChatMessage,
): FollowUpQuestionOption[] {
  const questions: FollowUpQuestionOption[] = []

  for (const tool of tools) {
    const payload = parseJsonRecord(tool.output)
    const rawQuestions = payload?.follow_up_questions
    if (!Array.isArray(rawQuestions)) {
      continue
    }

    rawQuestions.forEach((item, index) => {
      const record = asRecord(item)
      if (!record) {
        return
      }
      const question = questionFromRecord(record, index, tool, message)
      if (question) {
        questions.push(question)
      }
    })
  }

  return questions
}

export function extractFollowUpQuestions(
  message: LocalChatMessage,
  liveTools: ToolCallInfo[] = [],
): FollowUpQuestionOption[] {
  const directQuestions = message.custom_data?.follow_up_questions
  const directPayload: ToolCallInfo[] = Array.isArray(directQuestions)
    ? [
      {
        name: "message_follow_up_questions",
        id: `${message.local_id}-direct-followups`,
        args: {},
        output: JSON.stringify({ follow_up_questions: directQuestions }),
        status: "completed",
      },
    ]
    : []

  const tools = liveTools.length > 0
    ? liveTools
    : [...directPayload, ...storedToolsFromMessage(message)]

  const seen = new Set<string>()
  return extractFromTools(tools, message).filter((question) => {
    const key = normalizeQuestion(question.question)
    if (!key || seen.has(key)) {
      return false
    }
    seen.add(key)
    return true
  }).slice(0, 3)
}

export function findRecentFollowUpMatch(
  input: string,
  messages: LocalChatMessage[],
  liveTools: ToolCallInfo[],
): FollowUpMatch | null {
  let bestMatch: FollowUpMatch | null = null

  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index]
    if (message.type !== "ai") {
      continue
    }

    const isLatestMessage = index === messages.length - 1
    const options = extractFollowUpQuestions(
      message,
      isLatestMessage ? liveTools : [],
    )

    for (const option of options) {
      const similarity = getQuestionSimilarity(input, option.question)
      if (!bestMatch || similarity > bestMatch.similarity) {
        bestMatch = { question: option, similarity }
      }
    }

    if (options.length > 0) {
      break
    }
  }

  if (!bestMatch || bestMatch.similarity < 0.55) {
    return null
  }

  return bestMatch
}

function isDetailRequest(input: string): boolean {
  const normalized = normalizeQuestion(input)
  if (!normalized) {
    return false
  }

  const detailSignals = [
    "继续讲",
    "继续说",
    "讲讲",
    "详细",
    "展开",
    "为什么适合",
    "说说",
    "tellmemore",
    "moredetail",
    "details",
    "continue",
    "goon",
  ]

  return detailSignals.some((signal) => normalized.includes(signal))
}

export function findRecentDetailRequestTarget(
  input: string,
  messages: LocalChatMessage[],
  liveTools: ToolCallInfo[],
): FollowUpQuestionOption | null {
  if (!isDetailRequest(input)) {
    return null
  }

  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index]
    if (message.type !== "ai") {
      continue
    }

    const isLatestMessage = index === messages.length - 1
    const options = extractFollowUpQuestions(
      message,
      isLatestMessage ? liveTools : [],
    )
    if (options.length === 0) {
      continue
    }

    return (
      options.find((option) => option.bookTitle) ??
      options.find((option) => option.id.includes("detail")) ??
      options[0]
    )
  }

  return null
}
