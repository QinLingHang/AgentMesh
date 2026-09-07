import { useRef } from "react";
import type { ConversationAttachment, MessageAttachmentMetadata } from "../../types";
import { Icon } from "../../components/common/Icon";

export type ComposerAttachment = {
  localId: string;
  file: File;
  progress: number;
  status: "uploading" | "ready" | "error";
  error?: string;
  server?: ConversationAttachment;
  previewUrl?: string;
};

export const ATTACHMENT_ACCEPT = ".png,.jpg,.jpeg,.webp,.pdf,.docx,.txt,.md,.markdown,.csv,.json";

export function formatAttachmentSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function messageAttachmentList(metadata: unknown): MessageAttachmentMetadata[] {
  if (!metadata || typeof metadata !== "object") return [];
  const value = (metadata as { attachments?: unknown }).attachments;
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is MessageAttachmentMetadata => {
    if (!item || typeof item !== "object") return false;
    const candidate = item as Partial<MessageAttachmentMetadata>;
    return typeof candidate.id === "number" && typeof candidate.name === "string";
  });
}

export function AttachmentStrip({
  items,
  disabled,
  onFiles,
  onRemove,
}: {
  items: ComposerAttachment[];
  disabled?: boolean;
  onFiles: (files: File[]) => void;
  onRemove: (localId: string) => void;
}) {
  const inputRef = useRef<HTMLInputElement | null>(null);

  return (
    <div className="attachment-composer-row">
      <input
        ref={inputRef}
        className="attachment-file-input"
        type="file"
        multiple
        accept={ATTACHMENT_ACCEPT}
        disabled={disabled}
        onChange={(event) => {
          const files = Array.from(event.target.files ?? []);
          if (files.length) onFiles(files);
          event.currentTarget.value = "";
        }}
      />

      <button
        type="button"
        className="attachment-add-button"
        disabled={disabled}
        onClick={() => inputRef.current?.click()}
        data-testid="workspace-attachment-add"
      >
        <Icon name="file" size={15} />
        <span>添加图片或文件</span>
      </button>

      <span className="attachment-drop-hint">支持拖拽，或直接粘贴截图</span>

      {items.length > 0 && (
        <div className="attachment-preview-list" data-testid="workspace-attachment-list">
          {items.map((item) => {
            const image = item.file.type.startsWith("image/");
            return (
              <article className={`attachment-preview-card status-${item.status}`} key={item.localId}>
                {image && item.previewUrl ? (
                  <img src={item.previewUrl} alt="" className="attachment-preview-image" />
                ) : (
                  <span className="attachment-file-mark"><Icon name="file" size={16} /></span>
                )}
                <div className="attachment-preview-copy">
                  <strong title={item.file.name}>{item.file.name}</strong>
                  <small>
                    {formatAttachmentSize(item.file.size)}
                    {item.status === "uploading" && ` · 上传 ${item.progress}%`}
                    {item.status === "ready" && " · 已准备"}
                    {item.status === "error" && ` · ${item.error || "上传失败"}`}
                  </small>
                  {item.status === "uploading" && (
                    <span className="attachment-progress"><i style={{ width: `${item.progress}%` }} /></span>
                  )}
                </div>
                <button
                  type="button"
                  className="attachment-remove-button"
                  aria-label={`移除 ${item.file.name}`}
                  disabled={disabled || item.status === "uploading"}
                  title={item.status === "uploading" ? "上传完成后可移除" : "移除附件"}
                  onClick={() => onRemove(item.localId)}
                >
                  <Icon name="close" size={13} />
                </button>
              </article>
            );
          })}
        </div>
      )}
    </div>
  );
}
