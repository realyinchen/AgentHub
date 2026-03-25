import { marked } from "marked";
import type * as React from "react";
import { isValidElement, memo, useEffect, useMemo, useState } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import rehypeRaw from "rehype-raw";
import remarkGfm from "remark-gfm";
import { CheckIcon, CopyIcon, ExternalLinkIcon, XIcon, ZoomInIcon, ZoomOutIcon, RotateCcwIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
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
	disableHighlight?: boolean;
}

type HighlightedLine = Array<{
	content: string;
	style: React.CSSProperties | undefined;
}>;

const HighlightedPre = memo(({
	children,
	className,
	language,
	disableHighlight = false,
	...props
}: HighlightedPreProps) => {
	const code = useMemo(() => extractTextContent(children), [children]);
	const [lines, setLines] = useState<HighlightedLine[] | null>(null);

	useEffect(() => {
		if (disableHighlight) {
			return;
		}

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

		void highlight();

		return () => {
			cancelled = true;
		};
	}, [code, disableHighlight, language]);

	if (disableHighlight || !lines || lines.length === 0) {
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
	disableHighlight?: boolean;
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
			className="absolute cursor-pointer right-2 top-2 z-10 h-7 gap-1 px-2 text-xs"
			onClick={handleCopy}
		>
			{copied ? <CheckIcon className="size-3.5" /> : <CopyIcon className="size-3.5" />}

		</Button>
	);
}

const CodeBlock = ({
	children,
	language,
	disableHighlight = false,
	className,
	...props
}: CodeBlockProps) => {
	const code = extractTextContent(children);

	return (
		<div className="relative w-full max-w-full">
			<CopyCodeButton code={code} />
			<HighlightedPre
				language={language}
				disableHighlight={disableHighlight}
				className={className}
				{...props}
			>
				{children}
			</HighlightedPre>
		</div>
	);
};

CodeBlock.displayName = "CodeBlock";

// Image component with zoom modal
const ImageWithZoom = ({ alt, src, ...props }: React.ImgHTMLAttributes<HTMLImageElement>) => {
	const [isDialogOpen, setIsDialogOpen] = useState(false);
	const [scale, setScale] = useState(1);
	const [position, setPosition] = useState({ x: 0, y: 0 });
	const [isDragging, setIsDragging] = useState(false);
	const [dragStart, setDragStart] = useState({ x: 0, y: 0 });

	const handleZoomIn = () => {
		setScale((prev) => Math.min(prev + 0.5, 5));
	};

	const handleZoomOut = () => {
		setScale((prev) => {
			const newScale = Math.max(prev - 0.5, 0.5);
			// Reset position when zooming out to 1x or less
			if (newScale <= 1) {
				setPosition({ x: 0, y: 0 });
			}
			return newScale;
		});
	};

	const handleReset = () => {
		setScale(1);
		setPosition({ x: 0, y: 0 });
	};

	const handleOpenChange = (open: boolean) => {
		setIsDialogOpen(open);
		if (!open) {
			// Reset scale and position when closing
			setScale(1);
			setPosition({ x: 0, y: 0 });
		}
	};

	// Mouse drag handlers
	const handleMouseDown = (e: React.MouseEvent) => {
		if (scale > 1) {
			setIsDragging(true);
			setDragStart({ x: e.clientX - position.x, y: e.clientY - position.y });
		}
	};

	const handleMouseMove = (e: React.MouseEvent) => {
		if (isDragging && scale > 1) {
			setPosition({
				x: e.clientX - dragStart.x,
				y: e.clientY - dragStart.y,
			});
		}
	};

	const handleMouseUp = () => {
		setIsDragging(false);
	};

	const handleMouseLeave = () => {
		setIsDragging(false);
	};

	return (
		<>
			{/* biome-ignore lint/performance/noImgElement: Required for image */}
			<img
				className="rounded-md cursor-pointer hover:opacity-90 transition-opacity max-w-full h-auto"
				alt={alt}
				src={src}
				onClick={() => setIsDialogOpen(true)}
				{...props}
			/>
			<Dialog open={isDialogOpen} onOpenChange={handleOpenChange}>
				<DialogContent className="max-w-[95vw] max-h-[95vh] p-0 overflow-hidden bg-black/90 border-none shadow-none">
					<DialogTitle className="sr-only">{alt || "图片预览"}</DialogTitle>
					<div className="relative w-full h-full flex flex-col items-center justify-center">
						{/* Image container with overflow scroll for zoomed images */}
						<div 
							className="flex-1 overflow-hidden flex items-center justify-center p-4 w-full"
							onMouseMove={handleMouseMove}
							onMouseUp={handleMouseUp}
							onMouseLeave={handleMouseLeave}
						>
							{/* biome-ignore lint/performance/noImgElement: Required for image */}
							<img
								src={src}
								alt={alt}
								className={cn(
									"max-w-full max-h-[75vh] object-contain rounded-lg transition-transform duration-200",
									scale > 1 ? "cursor-grab" : "cursor-default",
									isDragging && "cursor-grabbing"
								)}
								style={{ 
									transform: `scale(${scale}) translate(${position.x / scale}px, ${position.y / scale}px)`,
								}}
								onMouseDown={handleMouseDown}
								draggable={false}
							/>
						</div>
						
						{/* Control bar */}
						<div className="absolute bottom-4 left-1/2 -translate-x-1/2 flex items-center gap-2 bg-black/70 rounded-full px-4 py-2">
							<Button
								variant="ghost"
								size="icon"
								className="text-white hover:bg-white/20"
								onClick={handleZoomOut}
								disabled={scale <= 0.5}
							>
								<ZoomOutIcon className="size-5" />
							</Button>
							<span className="text-white text-sm min-w-[60px] text-center">
								{Math.round(scale * 100)}%
							</span>
							<Button
								variant="ghost"
								size="icon"
								className="text-white hover:bg-white/20"
								onClick={handleZoomIn}
								disabled={scale >= 5}
							>
								<ZoomInIcon className="size-5" />
							</Button>
							<div className="w-px h-5 bg-white/30 mx-1" />
							<Button
								variant="ghost"
								size="icon"
								className="text-white hover:bg-white/20"
								onClick={handleReset}
							>
								<RotateCcwIcon className="size-5" />
							</Button>
						</div>
						
						{/* Close button */}
						<Button
							variant="ghost"
							size="icon"
							className="absolute top-2 right-2 bg-black/50 hover:bg-black/70 text-white"
							onClick={() => handleOpenChange(false)}
						>
							<XIcon className="size-5" />
						</Button>
					</div>
				</DialogContent>
			</Dialog>
		</>
	);
};

ImageWithZoom.displayName = "ImageWithZoom";

const createMarkdownComponents = (
	disableCodeHighlight: boolean,
): Partial<Components> => ({
	h1: ({ children, ...props }: React.HTMLAttributes<HTMLHeadingElement>) => (
		<h1 className="scroll-m-20 text-2xl font-bold" {...props}>
			{children}
		</h1>
	),
	h2: ({ children, ...props }: React.HTMLAttributes<HTMLHeadingElement>) => (
		<h2
			className="scroll-m-20 border-b pb-1 text-xl font-semibold tracking-tight"
			{...props}
		>
			{children}
		</h2>
	),
	h3: ({ children, ...props }: React.HTMLAttributes<HTMLHeadingElement>) => (
		<h3
			className="scroll-m-20 text-lg font-semibold tracking-tight"
			{...props}
		>
			{children}
		</h3>
	),
	h4: ({ children, ...props }: React.HTMLAttributes<HTMLHeadingElement>) => (
		<h4
			className="scroll-m-20 text-base font-semibold tracking-tight"
			{...props}
		>
			{children}
		</h4>
	),
	h5: ({ children, ...props }: React.HTMLAttributes<HTMLHeadingElement>) => (
		<h5
			className="scroll-m-20 text-base font-semibold tracking-tight"
			{...props}
		>
			{children}
		</h5>
	),
	h6: ({ children, ...props }: React.HTMLAttributes<HTMLHeadingElement>) => (
		<h6
			className="scroll-m-20 text-sm font-semibold tracking-tight"
			{...props}
		>
			{children}
		</h6>
	),
	p: ({ children, ...props }: React.HTMLAttributes<HTMLParagraphElement>) => (
		<p className="leading-7 break-words" {...props}>
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
		href,
		...props
	}: React.AnchorHTMLAttributes<HTMLAnchorElement>) => (
		<a
			className="inline-flex items-center gap-1.5 px-3 py-1.5 my-1 text-sm font-medium text-white bg-green-600 hover:bg-green-700 rounded-lg transition-colors no-underline"
			target="_blank"
			rel="noreferrer"
			href={href}
			{...props}
		>
			<ExternalLinkIcon className="size-3.5" />
			{children}
		</a>
	),
	ol: ({ children, ...props }: React.HTMLAttributes<HTMLOListElement>) => (
		<ol className="ml-6 list-decimal [&>li]:mt-0" {...props}>
			{children}
		</ol>
	),
	ul: ({ children, ...props }: React.HTMLAttributes<HTMLUListElement>) => (
		<ul className="ml-6 list-disc [&>li]:mt-0" {...props}>
			{children}
		</ul>
	),
	li: ({ children, ...props }: React.LiHTMLAttributes<HTMLLIElement>) => (
		<li className="break-words" {...props}>
			{children}
		</li>
	),
	blockquote: ({
		children,
		...props
	}: React.HTMLAttributes<HTMLQuoteElement>) => (
		<blockquote className="border-l-2 pl-4 italic" {...props}>
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
	img: ImageWithZoom,
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
				<CodeBlock
					language={match?.[1] ?? "text"}
					disableHighlight={disableCodeHighlight}
					className={className}
				>
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
});

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
	components: Partial<Components>;
}

const MemoizedMarkdownBlock = memo(
	({ content, className, components }: MarkdownBlockProps) => {
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
		if (prevProps.components !== nextProps.components) {
			return false;
		}
		return true;
	},
);

MemoizedMarkdownBlock.displayName = "MemoizedMarkdownBlock";

interface MarkdownContentProps {
	content: string;
	className?: string;
	isStreaming?: boolean;
}

export const MarkdownContent = memo(
	({ content, className, isStreaming = false }: MarkdownContentProps) => {
		const blocks = useMemo(
			() => parseMarkdownIntoBlocks(content || ""),
			[content],
		);
		const components = useMemo(
			() => createMarkdownComponents(isStreaming),
			[isStreaming],
		);

		return blocks.map((block, index) => (
			<MemoizedMarkdownBlock
				content={block}
				className={className}
				components={components}
				key={`block_${
					// biome-ignore lint/suspicious/noArrayIndexKey: Needed for react key
					index
					}`}
			/>
		));
	},
);

MarkdownContent.displayName = "MarkdownContent";
