import Markdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

function markdownComponents(tabIndex: -1 | 0): Components {
  return {
    a: ({ children, href }) => <span className="chat-markdown__reference">
      {children}{href && !href.startsWith("#") && children !== href ? <span className="chat-markdown__address"> ({href})</span> : null}
    </span>,
    img: ({ alt }) => <span className="chat-markdown__image">[이미지{alt ? `: ${alt}` : ""}]</span>,
    pre: ({ children }) => <pre tabIndex={tabIndex} aria-label="코드 블록">{children}</pre>,
    table: ({ children }) => <div className="chat-markdown__table" role="region" aria-label="표" tabIndex={tabIndex}>
      <table>{children}</table>
    </div>,
  };
}

const expandedComponents = markdownComponents(0);
const previewComponents = markdownComponents(-1);

export function ChatMarkdown({ text, preview = false }: { text: string; preview?: boolean }) {
  return <div className="chat-markdown"><Markdown remarkPlugins={[remarkGfm]}
    components={preview ? previewComponents : expandedComponents}>{text}</Markdown></div>;
}
