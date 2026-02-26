import { marked } from "marked";
import type * as React from "react";
import { isValidElement, memo, useEffect, useMemo, useState } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import rehypeRaw from "rehype-raw";
import remarkGfm from "remark-gfm";
import { CheckIcon, CopyIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const DEFAULT_PRE_BLOCK_CLASS =
	"my-4 w-full max-w-full overflow-x-auto rounded-xl border border-border bg-zinc-950 p-4 text-zinc-50 dark:bg-zinc-900";

const extractTextContent = (node: React.ReactNode): string => {
	if (typeof node === "string") {
		return node;
	}
	if (Array.isArray(node)) {
		return node.map(extractTextContent).join("");
	}
	if (isValidElement(node)) {
		// @ts-expect-error
		return extractTextContent(node.props.children);
	}
	return "";
};

interface HighlightedPreProps extends React.HTMLAttributes<HTMLPreElement> {
	language: string;
}

type HighlightedLine = Array<{
	content: string;
	style: React.CSSProperties | undefined;
}>;

const HighlightedPre = memo(({
	children,
	className,
	language,
	...props
}: HighlightedPreProps) => {
	const code = useMemo(() => extractTextContent(children), [children]);
	const [lines, setLines] = useState<HighlightedLine[] | null>(null);

	useEffect(() => {
		let cancelled = false;

		const highlight = async () => {
			try {
				const { codeToTokens, bundledLanguages } = await import("shiki");
				if (!(language in bundledLanguages)) {
					if (!cancelled) {
						setLines([]);
					}
					return;
				}

				const { tokens } = await codeToTokens(code, {
					lang: language as keyof typeof bundledLanguages,
					themes: {
						light: "github-dark",
						dark: "github-dark",
					},
				});

				if (cancelled) {
					return;
				}

				setLines(tokens.map((line) => line.map((token) => ({
					content: token.content,
					style: typeof token.htmlStyle === "string" ? undefined : token.htmlStyle,
				}))));
			} catch {
				if (!cancelled) {
					setLines([]);
				}
			}
		};

		setLines(null);
		void highlight();

		return () => {
			cancelled = true;
		};
	}, [code, language]);

	if (!lines || lines.length === 0) {
		return (
			<pre
				{...props}
				className={cn(DEFAULT_PRE_BLOCK_CLASS, className)}
			>
				<code className="whitespace-pre-wrap">{children}</code>
			</pre>
		);
	}

	return (
		<pre {...props} className={cn(DEFAULT_PRE_BLOCK_CLASS, className)}>
			<code className="whitespace-pre-wrap break-all">
				{lines.map((line, lineIndex) => (
					<span
						key={`line-${
							// biome-ignore lint/suspicious/noArrayIndexKey: Needed for react key
							lineIndex
							}`}
					>
						{line.map((token, tokenIndex) => (
							<span
								key={`token-${
									// biome-ignore lint/suspicious/noArrayIndexKey: Needed for react key
									tokenIndex
									}`}
								style={token.style}
							>
								{token.content}
							</span>
						))}
						{lineIndex !== lines.length - 1 && "\n"}
					</span>
				))}
			</code>
		</pre>
	);
});

HighlightedPre.displayName = "HighlightedPre";

interface CodeBlockProps extends React.HTMLAttributes<HTMLPreElement> {
	language: string;
}

function CopyCodeButton({ code }: { code: string }) {
	const [copied, setCopied] = useState(false);

	useEffect(() => {
		if (!copied) {
			return;
		}

		const timer = window.setTimeout(() => setCopied(false), 1500);
		return () => window.clearTimeout(timer);
	}, [copied]);

	const handleCopy = async () => {
		try {
			await navigator.clipboard.writeText(code);
			setCopied(true);
		} catch {
			// Ignore clipboard failures in unsupported environments.
		}
	};

	return (
		<Button
			type="button"
			variant="secondary"
			size="sm"
			className="absolute right-2 top-2 z-10 h-7 gap-1 px-2 text-xs"
			onClick={handleCopy}
		>
			{copied ? <CheckIcon className="size-3.5" /> : <CopyIcon className="size-3.5" />}
			{copied ? "Copied" : "Copy"}
		</Button>
	);
}

const CodeBlock = ({
	children,
	language,
	className,
	...props
}: CodeBlockProps) => {
	const code = extractTextContent(children);

	return (
		<div className="relative w-full max-w-full">
			<CopyCodeButton code={code} />
			<HighlightedPre language={language} className={className} {...props}>
				{children}
			</HighlightedPre>
		</div>
	);
};

CodeBlock.displayName = "CodeBlock";

const components: Partial<Components> = {
	h1: ({ children, ...props }: React.HTMLAttributes<HTMLHeadingElement>) => (
		<h1 className="mt-2 scroll-m-20 text-4xl font-bold" {...props}>
			{children}
		</h1>
	),
	h2: ({ children, ...props }: React.HTMLAttributes<HTMLHeadingElement>) => (
		<h2
			className="mt-8 scroll-m-20 border-b pb-2 text-2xl font-semibold tracking-tight first:mt-0"
			{...props}
		>
			{children}
		</h2>
	),
	h3: ({ children, ...props }: React.HTMLAttributes<HTMLHeadingElement>) => (
		<h3
			className="mt-4 scroll-m-20 text-xl font-semibold tracking-tight"
			{...props}
		>
			{children}
		</h3>
	),
	h4: ({ children, ...props }: React.HTMLAttributes<HTMLHeadingElement>) => (
		<h4
			className="mt-4 scroll-m-20 text-lg font-semibold tracking-tight"
			{...props}
		>
			{children}
		</h4>
	),
	h5: ({ children, ...props }: React.HTMLAttributes<HTMLHeadingElement>) => (
		<h5
			className="mt-4 scroll-m-20 text-lg font-semibold tracking-tight"
			{...props}
		>
			{children}
		</h5>
	),
	h6: ({ children, ...props }: React.HTMLAttributes<HTMLHeadingElement>) => (
		<h6
			className="mt-4 scroll-m-20 text-base font-semibold tracking-tight"
			{...props}
		>
			{children}
		</h6>
	),
	p: ({ children, ...props }: React.HTMLAttributes<HTMLParagraphElement>) => (
		<p className="leading-6 not-first:mt-4 break-all" {...props}>
			{children}
		</p>
	),
	strong: ({ children, ...props }: React.HTMLAttributes<HTMLElement>) => (
		<span className="font-semibold" {...props}>
			{children}
		</span>
	),
	span: ({
		children,
		className,
		...props
	}: {
		"data-type"?: string;
		"data-id"?: string;
		"data-label"?: string;
	} & React.HTMLAttributes<HTMLSpanElement>) => {
		const dataType = props["data-type"];
		const dataId = props["data-id"];
		const dataLabel = props["data-label"];

		if (className?.includes("mention")) {
			return (
				<span
					className={cn(
						"bg-primary text-primary-foreground rounded-sm px-2 py-0.5",
						className,
					)}
					data-type={dataType}
					data-id={dataId}
					data-label={dataLabel}
					title={dataLabel}
					{...props}
				>
					{children}
				</span>
			);
		}

		return (
			<span className={className} {...props}>
				{children}
			</span>
		);
	},
	a: ({
		children,
		...props
	}: React.AnchorHTMLAttributes<HTMLAnchorElement>) => (
		<a
			className="font-medium underline underline-offset-4 whitespace-pre-wrap break-all"
			target="_blank"
			rel="noreferrer"
			{...props}
		>
			{children}
		</a>
	),
	ol: ({ children, ...props }: React.HTMLAttributes<HTMLOListElement>) => (
		<ol className="my-4 ml-6 list-decimal" {...props}>
			{children}
		</ol>
	),
	ul: ({ children, ...props }: React.HTMLAttributes<HTMLUListElement>) => (
		<ul className="my-4 ml-6 list-disc" {...props}>
			{children}
		</ul>
	),
	li: ({ children, ...props }: React.LiHTMLAttributes<HTMLLIElement>) => (
		<li className="mt-2 break-all" {...props}>
			{children}
		</li>
	),
	blockquote: ({
		children,
		...props
	}: React.HTMLAttributes<HTMLQuoteElement>) => (
		<blockquote className="mt-4 border-l-2 pl-6 italic" {...props}>
			{children}
		</blockquote>
	),
	hr: (props: React.HTMLAttributes<HTMLHRElement>) => (
		<hr className="my-4 md:my-8" {...props} />
	),
	table: ({ children, ...props }: React.HTMLAttributes<HTMLTableElement>) => (
		<div className="my-6 w-full overflow-y-auto">
			<table
				className="relative w-full overflow-hidden border-none text-sm"
				{...props}
			>
				{children}
			</table>
		</div>
	),
	tr: ({ children, ...props }: React.HTMLAttributes<HTMLTableRowElement>) => (
		<tr className="last:border-b-none m-0 border-b" {...props}>
			{children}
		</tr>
	),
	th: ({
		children,
		...props
	}: React.HTMLAttributes<HTMLTableCellElement>) => (
		<th
			className="px-4 py-2 text-left font-bold [[align=center]]:text-center [[align=right]]:text-right"
			{...props}
		>
			{children}
		</th>
	),
	td: ({
		children,
		...props
	}: React.HTMLAttributes<HTMLTableCellElement>) => (
		<td
			className="px-4 py-2 text-left [[align=center]]:text-center [[align=right]]:text-right"
			{...props}
		>
			{children}
		</td>
	),
	img: ({ alt, ...props }: React.ImgHTMLAttributes<HTMLImageElement>) => (
		// biome-ignore lint/performance/noImgElement: Required for image
		<img className="rounded-md" alt={alt} {...props} />
	),
	code: ({
		children,
		className,
		inline,
		...props
	}: React.HTMLAttributes<HTMLElement> & { inline?: boolean }) => {
		const match = /language-(\w+)/.exec(className || "");
		const code = extractTextContent(children);
		const isBlock = inline === false || Boolean(match) || code.includes("\n");
		if (isBlock) {
			return (
				<CodeBlock language={match?.[1] ?? "text"} className={className}>
					{children}
				</CodeBlock>
			);
		}
		return (
			<code
				className={cn(
					"rounded bg-muted px-[0.3rem] py-[0.2rem] font-mono text-sm break-all",
					className,
				)}
				{...props}
			>
				{children}
			</code>
		);
	},
	pre: ({ children }) => <>{children}</>,
};

function parseMarkdownIntoBlocks(markdown: string): string[] {
	if (!markdown) {
		return [];
	}
	const tokens = marked.lexer(markdown);
	return tokens.map((token) => token.raw);
}

interface MarkdownBlockProps {
	content: string;
	className?: string;
}

const MemoizedMarkdownBlock = memo(
	({ content, className }: MarkdownBlockProps) => {
		return (
			<div className={className}>
				<ReactMarkdown
					remarkPlugins={[remarkGfm]}
					rehypePlugins={[rehypeRaw]}
					components={components}
				>
					{content}
				</ReactMarkdown>
			</div>
		);
	},
	(prevProps, nextProps) => {
		if (prevProps.content !== nextProps.content) {
			return false;
		}
		return true;
	},
);

MemoizedMarkdownBlock.displayName = "MemoizedMarkdownBlock";

interface MarkdownContentProps {
	content: string;
	className?: string;
}

export const MarkdownContent = memo(
	({ content, className }: MarkdownContentProps) => {
		const blocks = useMemo(
			() => parseMarkdownIntoBlocks(content || ""),
			[content],
		);

		return blocks.map((block, index) => (
			<MemoizedMarkdownBlock
				content={block}
				className={className}
				key={`block_${
					// biome-ignore lint/suspicious/noArrayIndexKey: Needed for react key
					index
					}`}
			/>
		));
	},
);

MarkdownContent.displayName = "MarkdownContent";
