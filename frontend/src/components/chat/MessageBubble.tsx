import type { ChatMessage } from "@/types";
import { DraftPreviewCard } from "./DraftPreviewCard";

interface MessageBubbleProps {
  message: ChatMessage;
  onApproveDraft?: () => void;
  onCancelDraft?: () => void;
  draftActionsDisabled?: boolean;
}

export function MessageBubble({
  message,
  onApproveDraft,
  onCancelDraft,
  draftActionsDisabled,
}: MessageBubbleProps) {
  if (message.role === "system") {
    return (
      <div className="flex justify-center my-2">
        <span className="text-xs text-slate-500 bg-slate-200/70 rounded-full px-3 py-1">
          {message.content}
        </span>
      </div>
    );
  }

  const isUser = message.role === "user";

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"} mb-3`}>
      <div className={`max-w-[80%] ${isUser ? "items-end" : "items-start"} flex flex-col gap-2`}>
        <div
          className={`rounded-2xl px-4 py-2.5 text-sm whitespace-pre-wrap break-words shadow-sm ${
            isUser
              ? "bg-primary-600 text-white rounded-br-sm"
              : "bg-white text-gray-900 rounded-bl-sm ring-1 ring-slate-200"
          }`}
        >
          {message.content}
        </div>
        {message.draftPreview && onApproveDraft && onCancelDraft && (
          <DraftPreviewCard
            subject={message.draftPreview.subject}
            body={message.draftPreview.body}
            onApprove={onApproveDraft}
            onCancel={onCancelDraft}
            disabled={!!draftActionsDisabled}
          />
        )}
      </div>
    </div>
  );
}
