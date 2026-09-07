import { useRef, type ChangeEvent } from "react";
import { Icon } from "../../components/common/Icon";

type TaskAttachment = {
  id: number | string;
  kind: "image" | "file";
  name: string;
  sizeBytes: number;
};

export type ComposerAttachment = TaskAttachment & { previewUrl?: string; uploading?: boolean };

export function ComposerAttachments({ items, disabled, onPick, onRemove }: {
  items: ComposerAttachment[]; disabled: boolean; onPick: (files: File[]) => void; onRemove: (item: ComposerAttachment) => void;
}) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  return <div className="composer-attachment-shell" data-testid="task-attachments">
    {items.length > 0 && <div className="composer-attachment-list">{items.map(item => (
      <div className="composer-attachment-chip" key={item.id}>
        {item.kind === "image" && item.previewUrl ? <img src={item.previewUrl} alt="" /> : <span className="composer-attachment-icon"><Icon name="file" size={15} /></span>}
        <span className="composer-attachment-copy"><strong>{item.name}</strong><small>{formatBytes(item.sizeBytes)} · {item.kind === "image" ? "图片" : "文件"}</small></span>
        <button type="button" aria-label={`移除 ${item.name}`} disabled={disabled} onClick={() => onRemove(item)}>×</button>
      </div>
    ))}</div>}
    <button type="button" className="composer-attach-button" disabled={disabled || items.length >= 6} onClick={() => inputRef.current?.click()}>
      <Icon name="file" size={14} /><span>添加图片或文件</span>
    </button>
    <input ref={inputRef} hidden type="file" multiple accept="image/png,image/jpeg,image/webp,.pdf,.docx,.txt,.md,.markdown,.csv,.json" onChange={(e: ChangeEvent<HTMLInputElement>) => { const files=Array.from(e.target.files ?? []) as File[]; e.currentTarget.value=""; if(files.length) onPick(files); }} />
  </div>;
}

function formatBytes(bytes: number) { if(bytes < 1024) return `${bytes} B`; if(bytes < 1024*1024) return `${(bytes/1024).toFixed(1)} KB`; return `${(bytes/1024/1024).toFixed(1)} MB`; }
