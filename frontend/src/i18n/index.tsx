import {
  createContext,
  type PropsWithChildren,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react"

const STORAGE_KEY = "agenthub_locale"

const en = {
  "app.titlePrompt":
    "Generate a concise title under 50 characters for this conversation. First user message: {{input}}. First AI response: {{response}}. Output the text directly, without Markdown formatting.",
  "chat.chooseAgent": "Choose an agent to start",
  "chat.startChatting": "Start chatting with your selected agent.",
  "chat.suggestion.1": "Who are you? What can you do?",
  "chat.suggestion.2": "Help me build a LangChain toolchain",
  "chat.suggestion.3": "Tell me a joke",
  "chat.suggestion.4": "What is Agentic-RAG?",
  "chat.defaultAssistant": "Default assistant",
  "chat.noDescription": "No description provided.",
  "chat.requestFailed": "Request failed",
  "chat.status.chatbot": "Chatbot",
  "chat.status.rag": "RAG Agent",
  "chat.selectAgent": "Select agent",
  "agent.noDescription": "No description provided.",
  "agent.shuffle": "Shuffle",
  "common.cancel": "Cancel",
  "common.save": "Save",
  "common.saving": "Saving",
  "common.delete": "Delete",
  "common.rename": "Rename",
  "common.close": "Close",
  "common.copy": "Copy",
  "common.copied": "Copied",
  "common.retry": "Retry",
  "common.send": "Send",
  "common.edit": "Edit",
  "common.scrollToBottom": "Scroll to bottom",
  "common.stop": "Stop",
  "common.loading": "Loading",
  "common.submit": "Submit",
  "common.unknown": "unknown",
  "common.of": "of",
  "conversation.defaultTitle": "New conversation",
  "conversation.untitled": "Untitled",
  "conversation.new": "New conversation",
  "conversation.recent": "Recent",
  "conversation.none": "No saved conversations yet.",
  "conversation.actions": "Conversation actions",
  "conversation.editTitle": "Edit conversation title",
  "conversation.editDescription":
    "Update the selected conversation title (max 64 characters).",
  "conversation.titlePlaceholder": "Conversation title",
  "conversation.deleteTitle": "Delete this conversation?",
  "conversation.deleteDescriptionWithTitle":
    "This action marks \"{{title}}\" as deleted and removes it from your recent list.",
  "conversation.deleteDescriptionWithoutTitle":
    "This action marks the conversation as deleted and removes it from your recent list.",
  "error.unexpected": "Unexpected error",
  "error.loadConversation": "Failed to load conversation: {{details}}",
  "error.generateResponse": "Failed to generate response: {{details}}",
  "error.updateTitle": "Failed to update title: {{details}}",
  "error.deleteConversation": "Failed to delete conversation: {{details}}",
  "error.initApp": "Failed to initialize app: {{details}}",
  "error.titleEmpty": "Title cannot be empty",
  "error.streamPrefix": "Error: {{details}}",
  "prompt.addFiles": "Add photos or files",
  "prompt.image": "Image",
  "prompt.attachment": "Attachment",
  "prompt.removeAttachment": "Remove attachment",
  "prompt.remove": "Remove",
  "prompt.attachmentAlt": "attachment",
  "prompt.attachmentPreviewAlt": "attachment preview",
  "prompt.uploadFiles": "Upload files",
  "prompt.placeholder": "What would you like to know?",
  "prompt.acceptError": "No files match the accepted types.",
  "prompt.maxSizeError": "All files exceed the maximum size.",
  "prompt.maxFilesError": "Too many files. Some were not added.",
  "prompt.speechError": "Speech recognition error:",
  "language.toggleLabel": "中",
  "language.switch": "Switch language",
  "theme.switch": "Toggle theme",
  "share.button": "Share chat",
  "share.title": "Link Copied",
  "share.description": "The current chat link has been copied to your clipboard.",
  "share.privacyWarning": "Please be careful when sharing. The chat content may contain sensitive or private information.",
  "message.sources": "Sources ({{count}})",
  "message.reasoning": "Reasoning",
  "message.noOutput": "No visible output.",
  "message.tool": "Tool",
  "message.toolCallId": "tool call id: {{id}}",
  "message.thinking": "Thinking...",
  "message.processing": "Processing...",
  "message.callingTool": "Calling {{tool}}...",
  "message.toolsUsed": "Tools used",
  "message.toolsUsedCount": "Tools used ({{count}})",
  "message.showTools": "Show tool calls",
  "message.hideTools": "Hide tool calls",
  "message.thinkingProcess": "Thinking process",
  "message.showThinkingProcess": "Show thinking process",
  "message.hideThinkingProcess": "Hide thinking process",
  "message.toolCallsCount": "Tool calls ({{count}})",
  "message.toolCalls": "Tool calls",
  "message.showToolCalls": "Show tool calls",
  "message.hideToolCalls": "Hide tool calls",
  "message.toolInput": "Input",
  "message.toolOutput": "Output",
  "message.copyResponse": "Copy response",
  "message.copiedResponse": "Copied response",
  "message.retryResponse": "Retry response",
  "message.copyMessage": "Copy message",
  "message.copiedMessage": "Copied message",
  "message.editMessage": "Edit message",
  "message.editPlaceholder": "Edit your message...",
  "message.sendEdit": "Send",
  "message.previousBranch": "Previous branch",
  "message.nextBranch": "Next branch",
  "message.branchIndex": "{{current}} {{of}} {{total}}",
  "message.demo.question1": "Can you explain how React hooks work?",
  "message.demo.answer1":
    "React hooks are functions that let you use state and lifecycle features in function components.",
  "message.demo.question2": "Yes please, show me a useState example!",
  "branch.previous": "Previous version",
  "branch.next": "Next version",
  "branch.version": "{{current}} / {{total}}",
  "branch.versionLabel": "Version {{number}}",
  "branch.switchTo": "Switch to this version",
  "message.quote": "Quote message",
  "message.quotePlaceholder": "Add your question or comment...",
  "message.addYourMessage": "Add your message...",
  "message.quoteDialog": "Quote Message",
  "message.quoteDescription": "Reply with reference to this message:",
  "message.jumpToOriginal": "Jump to original message",
  "thinking.enabled": "Thinking mode enabled - using reasoning model",
  "thinking.disabled": "Enable thinking mode for deeper reasoning",
  "sidebar.logoAlt": "AgentHub",
  "sidebar.toggle": "Toggle Sidebar",
  "sidebar.title": "Sidebar",
  "sidebar.description": "Displays the mobile sidebar.",
  "command.title": "Command Palette",
  "command.description": "Search for a command to run...",
  "command.noResults": "No results found",
  "chatInput.typeMessage": "Type a message...",
  "chatInput.addMention": "Add Mention",
  "loader.title": "Loader",
  "loader.demo.default": "Default (16px)",
  "loader.demo.medium": "Medium (24px)",
  "loader.demo.large": "Large (32px)",
  "actions.demo.message":
    "Here's a quick example of how to use React hooks with common message actions.",
  "actions.demo.copyTooltip": "Copy to clipboard",
  "actions.demo.regenerateTooltip": "Regenerate response",
  "actions.demo.goodTooltip": "Good response",
  "actions.demo.badTooltip": "Bad response",
  "actions.demo.copiedLog": "Copied!",
  "actions.demo.regeneratingLog": "Regenerating...",
  "actions.demo.thumbsUpLog": "Thumbs up!",
  "actions.demo.thumbsDownLog": "Thumbs down!",
} as const

type TranslationKey = keyof typeof en
type TranslationDictionary = Record<TranslationKey, string>

const zh: TranslationDictionary = {
  "app.titlePrompt":
    "请为本次对话生成一个不超过10个汉字的简洁标题。第一条用户消息：{{input}}。第一条AI回复：{{response}}。直接输出文本，不要markdown格式。",
  "chat.chooseAgent": "请选择一个智能体开始对话",
  "chat.startChatting": "开始与当前选中的智能体聊天吧。",
  "chat.suggestion.1": "你是谁？你能做些什么？",
  "chat.suggestion.2": "帮我写一个 LangChain 工具链",
  "chat.suggestion.3": "给我讲一个笑话",
  "chat.suggestion.4": "Agentic-RAG 是什么？",
  "chat.defaultAssistant": "默认助手",
  "chat.noDescription": "暂无描述。",
  "chat.requestFailed": "请求失败",
  "chat.status.chatbot": "聊天助手",
  "chat.status.rag": "RAG 智能体",
  "chat.selectAgent": "选择智能体",
  "agent.noDescription": "暂无描述。",
  "agent.shuffle": "换一换",
  "common.cancel": "取消",
  "common.save": "保存",
  "common.saving": "保存中",
  "common.delete": "删除",
  "common.rename": "重命名",
  "common.close": "关闭",
  "common.copy": "复制",
  "common.copied": "已复制",
  "common.retry": "重试",
  "common.send": "发送",
  "common.edit": "编辑",
  "common.scrollToBottom": "滚动到底部",
  "common.stop": "停止",
  "common.loading": "加载中",
  "common.submit": "提交",
  "common.unknown": "未知",
  "common.of": "/",
  "conversation.defaultTitle": "新会话",
  "conversation.untitled": "未命名",
  "conversation.new": "新会话",
  "conversation.recent": "最近会话",
  "conversation.none": "暂无已保存会话。",
  "conversation.actions": "会话操作",
  "conversation.editTitle": "编辑会话标题",
  "conversation.editDescription": "更新当前会话标题（最多64个字符）。",
  "conversation.titlePlaceholder": "会话标题",
  "conversation.deleteTitle": "确认删除该会话吗？",
  "conversation.deleteDescriptionWithTitle":
    "该操作会将“{{title}}”标记为已删除，并从最近列表中移除。",
  "conversation.deleteDescriptionWithoutTitle":
    "该操作会将当前会话标记为已删除，并从最近列表中移除。",
  "error.unexpected": "发生未知错误",
  "error.loadConversation": "加载会话失败：{{details}}",
  "error.generateResponse": "生成回复失败：{{details}}",
  "error.updateTitle": "更新标题失败：{{details}}",
  "error.deleteConversation": "删除会话失败：{{details}}",
  "error.initApp": "初始化应用失败：{{details}}",
  "error.titleEmpty": "标题不能为空",
  "error.streamPrefix": "错误：{{details}}",
  "prompt.addFiles": "添加图片或文件",
  "prompt.image": "图片",
  "prompt.attachment": "附件",
  "prompt.removeAttachment": "移除附件",
  "prompt.remove": "移除",
  "prompt.attachmentAlt": "附件",
  "prompt.attachmentPreviewAlt": "附件预览",
  "prompt.uploadFiles": "上传文件",
  "prompt.placeholder": "你想了解什么？",
  "prompt.acceptError": "没有文件符合允许的类型。",
  "prompt.maxSizeError": "所有文件都超过了大小限制。",
  "prompt.maxFilesError": "文件数量过多，部分文件未添加。",
  "prompt.speechError": "语音识别错误：",
  "language.toggleLabel": "EN",
  "language.switch": "切换语言",
  "theme.switch": "切换主题",
  "share.button": "分享聊天",
  "share.title": "链接已复制",
  "share.description": "当前聊天链接已复制到剪贴板。",
  "share.privacyWarning": "分享时请注意保护隐私，聊天内容可能包含敏感信息。",
  "message.sources": "参考来源（{{count}}）",
  "message.reasoning": "推理过程",
  "message.noOutput": "暂无可展示内容。",
  "message.tool": "工具",
  "message.toolCallId": "工具调用 ID：{{id}}",
  "message.thinking": "正在思考...",
  "message.processing": "正在处理...",
  "message.callingTool": "正在调用 {{tool}}...",
  "message.toolsUsed": "使用的工具",
  "message.toolsUsedCount": "使用的工具（{{count}}）",
  "message.showTools": "显示工具调用",
  "message.hideTools": "隐藏工具调用",
  "message.thinkingProcess": "思考过程",
  "message.showThinkingProcess": "显示思考过程",
  "message.hideThinkingProcess": "隐藏思考过程",
  "message.toolCallsCount": "工具调用（{{count}}）",
  "message.toolCalls": "工具调用",
  "message.showToolCalls": "显示工具调用",
  "message.hideToolCalls": "隐藏工具调用",
  "message.toolInput": "输入",
  "message.toolOutput": "输出",
  "message.copyResponse": "复制回复",
  "message.copiedResponse": "已复制回复",
  "message.retryResponse": "重试回复",
  "message.copyMessage": "复制消息",
  "message.copiedMessage": "已复制消息",
  "message.editMessage": "编辑消息",
  "message.editPlaceholder": "编辑您的消息...",
  "message.sendEdit": "发送",
  "message.previousBranch": "上一分支",
  "message.nextBranch": "下一分支",
  "message.branchIndex": "{{current}} {{of}} {{total}}",
  "message.demo.question1": "你可以解释一下 React Hooks 是怎么工作的吗？",
  "message.demo.answer1": "React Hooks 可以让函数组件使用状态和生命周期能力。",
  "message.demo.question2": "好的，请给我一个 useState 示例！",
  "branch.previous": "上一版本",
  "branch.next": "下一版本",
  "branch.version": "{{current}} / {{total}}",
  "branch.versionLabel": "版本 {{number}}",
  "branch.switchTo": "切换到此版本",
  "message.quote": "引用消息",
  "message.quotePlaceholder": "添加您的问题或评论...",
  "message.addYourMessage": "添加您的消息...",
  "message.quoteDialog": "引用消息",
  "message.quoteDescription": "引用此消息回复：",
  "message.jumpToOriginal": "跳转到原消息",
  "thinking.enabled": "思考模式已开启 - 使用推理模型",
  "thinking.disabled": "开启思考模式以获得更深度的推理",
  "sidebar.logoAlt": "AgentHub",
  "sidebar.toggle": "切换侧边栏",
  "sidebar.title": "侧边栏",
  "sidebar.description": "显示移动端侧边栏。",
  "command.title": "命令面板",
  "command.description": "搜索要执行的命令…",
  "command.noResults": "未找到结果",
  "chatInput.typeMessage": "输入消息…",
  "chatInput.addMention": "添加提及",
  "loader.title": "加载中",
  "loader.demo.default": "默认（16px）",
  "loader.demo.medium": "中等（24px）",
  "loader.demo.large": "较大（32px）",
  "actions.demo.message": "这是一个展示 React Hooks 与常见消息操作的简短示例。",
  "actions.demo.copyTooltip": "复制到剪贴板",
  "actions.demo.regenerateTooltip": "重新生成回复",
  "actions.demo.goodTooltip": "好的回复",
  "actions.demo.badTooltip": "不理想的回复",
  "actions.demo.copiedLog": "已复制！",
  "actions.demo.regeneratingLog": "重新生成中...",
  "actions.demo.thumbsUpLog": "点赞！",
  "actions.demo.thumbsDownLog": "点踩！",
}

const dictionaries = {
  en,
  zh,
}

export type Locale = keyof typeof dictionaries

type TranslationParams = Record<string, string | number>

type I18nContextValue = {
  locale: Locale
  setLocale: (nextLocale: Locale) => void
  toggleLocale: () => void
  t: (key: TranslationKey | string, params?: TranslationParams) => string
}

function interpolate(template: string, params?: TranslationParams): string {
  if (!params) {
    return template
  }

  return template.replace(/\{\{(\w+)\}\}/g, (_match, key: string) => {
    const value = params[key]
    return value === undefined ? "" : String(value)
  })
}

function resolveInitialLocale(): Locale {
  if (typeof window === "undefined") {
    return "zh"
  }

  const stored = window.localStorage.getItem(STORAGE_KEY)
  if (stored === "zh" || stored === "en") {
    return stored
  }

  return window.navigator.language.toLowerCase().startsWith("zh") ? "zh" : "en"
}

function translate(locale: Locale, key: string, params?: TranslationParams): string {
  const dictionary = dictionaries[locale]
  const template = dictionary[key as TranslationKey] ?? en[key as TranslationKey] ?? key
  return interpolate(template, params)
}

const I18nContext = createContext<I18nContextValue>({
  locale: "zh",
  setLocale: () => {},
  toggleLocale: () => {},
  t: (key, params) => translate("zh", key, params),
})

export function I18nProvider({ children }: PropsWithChildren) {
  const [locale, setLocale] = useState<Locale>(resolveInitialLocale)

  const t = useCallback(
    (key: TranslationKey | string, params?: TranslationParams) =>
      translate(locale, key, params),
    [locale],
  )

  const toggleLocale = useCallback(() => {
    setLocale((previous) => (previous === "zh" ? "en" : "zh"))
  }, [])

  const value = useMemo(
    () => ({
      locale,
      setLocale,
      toggleLocale,
      t,
    }),
    [locale, t, toggleLocale],
  )

  useEffect(() => {
    document.documentElement.lang = locale === "zh" ? "zh-CN" : "en"
    window.localStorage.setItem(STORAGE_KEY, locale)
  }, [locale])

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>
}

export function useI18n() {
  return useContext(I18nContext)
}
