// FastAPI backend şemasını yansıtan TypeScript tipleri

export type EmailDraftStatus =
  | "IDLE"
  | "COLLECTING_INFO"
  | "DRAFT_CREATED"
  | "PENDING_APPROVAL"
  | "APPROVED"
  | "REJECTED"
  | "SENT"
  | "FAILED"
  | "CANCELLED";

export type ProcessingStatus =
  | "PENDING"
  | "PROCESSING"
  | "INDEXED"
  | "FAILED"
  | "DELETED";

export interface EmailDraft {
  id: string;
  conversation_id: string;
  status: EmailDraftStatus;
  intent_type: string;
  recipient_email: string | null;
  recipient_name: string | null;
  recipient_department: string | null;
  subject: string | null;
  body: string | null;
  admin_notes: string | null;
  rejection_reason: string | null;
  reviewed_by: string | null;
  reviewed_at: string | null;
  created_at: string;
  updated_at: string;
  send_attempts: number;
  last_error: string | null;
}

export interface KnowledgeDocument {
  id: string;
  original_filename: string;
  file_size_bytes: number;
  mime_type: string;
  status: ProcessingStatus;
  processing_error: string | null;
  uploaded_by: string;
  uploaded_at: string;
  indexed_at: string | null;
  description: string | null;
  tags_json: string;
  chunk_count: number;
}

export interface EmailLog {
  id: string;
  draft_id: string;
  recipient_display: string;
  subject: string;
  sent_at: string;
  smtp_message_id: string | null;
}

export type IncomingEmailStatus =
  | "RECEIVED"
  | "ANALYZING"
  | "REPLY_GENERATED"
  | "PENDING_REVIEW"
  | "APPROVED"
  | "REPLIED"
  | "FAILED"
  | "SKIPPED"
  | "ANALYSIS_FAILED";

export interface IncomingEmail {
  id: string;
  sender_email_hash: string;
  sender_name: string | null;
  subject: string | null;
  body_text: string | null;
  status: IncomingEmailStatus;
  intent_type: string | null;
  intent_confidence: number | null;
  rag_context_preview: string | null;
  rag_source_count: number;
  reply_subject: string | null;
  reply_body: string | null;
  admin_notes: string | null;
  reviewed_by: string | null;
  reviewed_at: string | null;
  send_attempts: number;
  last_error: string | null;
  has_attachments: boolean;
  attachment_names_json: string;
  received_at: string;
  fetched_at: string;
  updated_at: string;
  reply_sent_at: string | null;
  auto_approved: boolean;
}

// Pilot Modu / Co-Pilot Modu
export type SystemMode = "PILOT" | "CO_PILOT";

export interface SystemModeConfig {
  mode: SystemMode;
  updated_by: string | null;
  updated_at: string;
}

export interface UnifiedEmailItem {
  id: string;
  item_type: "draft" | "incoming_reply";
  status: string;
  subject: string | null;
  recipient_display: string | null;
  sender_display: string | null;
  intent_type: string | null;
  created_at: string;
  send_attempts: number;
  last_error: string | null;
}

export interface DashboardStats {
  active_sessions: number;
  pending_emails: number;
  sent_today: number;
  total_documents: number;
  pending_incoming: number;
  replied_today: number;
  intents_breakdown: Array<{
    intent_type: string;
    count: number;
  }>;
}

export interface ActivityEvent {
  type: string;
  conversation_id: string;
  intent_type: string;
  requires_email: boolean;
  ts: string;
}

// Öğrenci sohbet mesajı (client-side görüntüleme modeli)
export interface ChatMessage {
  role: "user" | "assistant" | "system";
  content: string;
  ts?: string;
  draftPreview?: { subject: string; body: string };
}

// WebSocket event tipleri
export interface WsEvent {
  type:
    | "message"
    | "state_change"
    | "draft_preview"
    | "draft_created"
    | "email_pending_approval"
    | "email_approved"
    | "email_rejected"
    | "email_sent"
    | "email_failed"
    | "draft_rejected"
    | "intent_detected"
    | "document_indexed"
    | "incoming_email_received"
    | "incoming_reply_ready"
    | "incoming_reply_sent"
    | "incoming_reply_failed"
    | "incoming_analysis_failed"
    | "incoming_email_auto_replied"
    | "system_mode_changed"
    | "ping"
    | "error";
  [key: string]: unknown;
}
