"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Upload, Trash2, RefreshCw, FileText, Tag, X } from "lucide-react";
import { api } from "@/lib/api";
import type { KnowledgeDocument } from "@/types";
import { formatDistanceToNow } from "date-fns";
import { tr } from "date-fns/locale";
import { useWsContext } from "@/contexts/WsContext";

const STATUS_LABELS: Record<string, { label: string; class: string }> = {
  PENDING: { label: "Bekliyor", class: "bg-yellow-100 text-yellow-700" },
  PROCESSING: { label: "İşleniyor", class: "bg-blue-100 text-blue-700" },
  INDEXED: { label: "İndekslendi", class: "bg-green-100 text-green-700" },
  FAILED: { label: "Hata", class: "bg-red-100 text-red-700" },
  DELETED: { label: "Silindi", class: "bg-gray-100 text-gray-500" },
};

const INTENT_OPTIONS: { value: string; label: string }[] = [
  { value: "transcript_request", label: "Transkript" },
  { value: "certificate_request", label: "Sertifika" },
  { value: "enrollment_letter", label: "Kayıt Belgesi" },
  { value: "leave_of_absence", label: "İzin / Kayıt Dondurma" },
  { value: "complaint", label: "Şikayet" },
  { value: "grade_objection", label: "Not İtirazı" },
  { value: "general_question", label: "Genel Soru" },
];

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

interface UploadModalProps {
  files: File[];
  onConfirm: (description: string, tags: string[]) => void;
  onCancel: () => void;
}

function UploadModal({ files, onConfirm, onCancel }: UploadModalProps) {
  const [description, setDescription] = useState("");
  const [selectedTags, setSelectedTags] = useState<string[]>([]);

  const toggleTag = (value: string) => {
    setSelectedTags((prev) =>
      prev.includes(value) ? prev.filter((t) => t !== value) : [...prev, value]
    );
  };

  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-md">
        <div className="flex items-center justify-between p-5 border-b border-slate-100">
          <h2 className="font-semibold text-gray-900">Belge Yükleme</h2>
          <button onClick={onCancel} className="text-gray-400 hover:text-gray-600">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-5 space-y-4">
          {/* Seçilen dosyalar */}
          <div className="text-sm text-gray-600">
            <span className="font-medium">{files.length}</span> dosya seçildi:
            <ul className="mt-1 space-y-0.5">
              {files.map((f, i) => (
                <li key={i} className="flex items-center gap-1.5 text-gray-500">
                  <FileText className="w-3.5 h-3.5 flex-shrink-0" />
                  <span className="truncate">{f.name}</span>
                  <span className="text-gray-300 flex-shrink-0">({formatBytes(f.size)})</span>
                </li>
              ))}
            </ul>
          </div>

          {/* Açıklama */}
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">
              Açıklama <span className="text-gray-400">(opsiyonel)</span>
            </label>
            <input
              type="text"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Örn: 2024-2025 Transkript Yönetmeliği"
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
            />
          </div>

          {/* Etiketler */}
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-2">
              <span className="flex items-center gap-1">
                <Tag className="w-3.5 h-3.5" />
                Talep Kategorileri <span className="text-gray-400">(bu belge hangi konuları kapsar?)</span>
              </span>
            </label>
            <div className="flex flex-wrap gap-2">
              {INTENT_OPTIONS.map(({ value, label }) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => toggleTag(value)}
                  className={`rounded-full px-3 py-1 text-xs font-medium transition-colors ${
                    selectedTags.includes(value)
                      ? "bg-primary-600 text-white"
                      : "bg-slate-100 text-slate-600 hover:bg-slate-200"
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
            {selectedTags.length === 0 && (
              <p className="text-xs text-gray-400 mt-1.5">
                Kategori seçilmezse belge tüm sorular için kullanılır.
              </p>
            )}
          </div>
        </div>

        <div className="flex justify-end gap-2 p-5 border-t border-slate-100">
          <button
            onClick={onCancel}
            className="px-4 py-2 text-sm text-gray-600 hover:text-gray-800"
          >
            İptal
          </button>
          <button
            onClick={() => onConfirm(description, selectedTags)}
            className="flex items-center gap-2 rounded-lg bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700"
          >
            <Upload className="w-4 h-4" />
            Yükle
          </button>
        </div>
      </div>
    </div>
  );
}

export default function KnowledgeBasePage() {
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [pendingFiles, setPendingFiles] = useState<File[] | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const { subscribe } = useWsContext();

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const docs = await api.listDocuments();
      setDocuments(docs);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    return subscribe((event) => {
      if (event.type === "document_indexed") {
        refresh();
      }
    });
  }, [subscribe, refresh]);

  const handleFilesSelected = (files: FileList | null) => {
    if (!files || files.length === 0) return;
    setPendingFiles(Array.from(files));
    // input'u sıfırla (aynı dosya tekrar seçilebilsin)
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  const handleUploadConfirm = async (description: string, tags: string[]) => {
    if (!pendingFiles) return;
    setPendingFiles(null);
    setUploading(true);
    try {
      for (const file of pendingFiles) {
        const fd = new FormData();
        fd.append("file", file);
        if (description) fd.append("description", description);
        fd.append("tags", JSON.stringify(tags));
        await api.uploadDocument(fd);
      }
      await refresh();
    } catch (e) {
      alert(e instanceof Error ? e.message : "Yükleme hatası");
    } finally {
      setUploading(false);
    }
  };

  const handleDelete = async (id: string, name: string) => {
    if (!confirm(`"${name}" silinecek. Emin misiniz?`)) return;
    await api.deleteDocument(id);
    await refresh();
  };

  const handleReindex = async (id: string) => {
    await api.reindexDocument(id);
    await refresh();
  };

  return (
    <div>
      {pendingFiles && (
        <UploadModal
          files={pendingFiles}
          onConfirm={handleUploadConfirm}
          onCancel={() => setPendingFiles(null)}
        />
      )}

      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold text-primary-900">Bilgi Tabanı</h1>
          <p className="text-slate-500 mt-1 text-sm">RAG için indekslenecek belgeler</p>
        </div>
        <button onClick={refresh} className="flex items-center gap-2 text-sm text-slate-500 hover:text-primary-700 transition-colors">
          <RefreshCw className="w-4 h-4" />
          Yenile
        </button>
      </div>

      {/* Dropzone */}
      <div
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => { e.preventDefault(); setDragging(false); handleFilesSelected(e.dataTransfer.files); }}
        onClick={() => fileInputRef.current?.click()}
        className={`cursor-pointer rounded-xl border-2 border-dashed p-8 text-center mb-6 transition-colors ${
          dragging ? "border-primary-500 bg-primary-50" : "border-slate-300 hover:border-primary-400 hover:bg-primary-50/50"
        }`}
      >
        <Upload className="mx-auto w-8 h-8 text-gray-400 mb-2" />
        <p className="text-sm font-medium text-gray-700">
          {uploading ? "Yükleniyor..." : "Buraya sürükleyin veya tıklayın"}
        </p>
        <p className="text-xs text-gray-400 mt-1">PDF, DOCX, TXT, MD — Maks. 20 MB</p>
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept=".pdf,.docx,.txt,.md"
          className="hidden"
          onChange={(e) => handleFilesSelected(e.target.files)}
        />
      </div>

      {/* Tablo */}
      {loading ? (
        <div className="flex justify-center py-16">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600" />
        </div>
      ) : documents.length === 0 ? (
        <div className="text-center py-16 text-gray-400">Henüz belge yüklenmedi.</div>
      ) : (
        <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-100 bg-slate-50">
                <th className="text-left px-4 py-3 font-medium text-slate-500">Belge</th>
                <th className="text-left px-4 py-3 font-medium text-slate-500">Etiketler</th>
                <th className="text-left px-4 py-3 font-medium text-slate-500">Durum</th>
                <th className="text-left px-4 py-3 font-medium text-slate-500">Boyut</th>
                <th className="text-left px-4 py-3 font-medium text-slate-500">Tarih</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {documents.map((doc) => {
                const st = STATUS_LABELS[doc.status] ?? STATUS_LABELS.PENDING;
                let tags: string[] = [];
                try { tags = JSON.parse(doc.tags_json || "[]"); } catch { tags = []; }
                return (
                  <tr key={doc.id} className="hover:bg-slate-50 transition-colors">
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <FileText className="w-4 h-4 text-gray-400 flex-shrink-0" />
                        <div>
                          <span className="truncate max-w-xs font-medium text-gray-800 block">
                            {doc.description || doc.original_filename}
                          </span>
                          {doc.description && (
                            <span className="text-xs text-gray-400 truncate block max-w-xs">
                              {doc.original_filename}
                            </span>
                          )}
                        </div>
                      </div>
                      {doc.processing_error && (
                        <p className="text-xs text-red-500 mt-0.5 truncate">{doc.processing_error}</p>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      {tags.length === 0 ? (
                        <span className="text-xs text-gray-300">Tüm sorgular</span>
                      ) : (
                        <div className="flex flex-wrap gap-1">
                          {tags.map((t) => {
                            const opt = INTENT_OPTIONS.find((o) => o.value === t);
                            return (
                              <span key={t} className="inline-flex rounded-full bg-primary-50 px-2 py-0.5 text-xs text-primary-700">
                                {opt?.label ?? t}
                              </span>
                            );
                          })}
                        </div>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${st.class}`}>
                        {st.label}
                      </span>
                      {doc.chunk_count > 0 && (
                        <span className="text-xs text-gray-400 ml-1.5">{doc.chunk_count} chunk</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-gray-500">{formatBytes(doc.file_size_bytes)}</td>
                    <td className="px-4 py-3 text-gray-400 text-xs">
                      {formatDistanceToNow(new Date(doc.uploaded_at), { addSuffix: true, locale: tr })}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-1 justify-end">
                        {doc.status === "FAILED" && (
                          <button
                            onClick={() => handleReindex(doc.id)}
                            className="p-1.5 text-gray-400 hover:text-primary-600 rounded"
                            title="Yeniden indeksle"
                          >
                            <RefreshCw className="w-4 h-4" />
                          </button>
                        )}
                        <button
                          onClick={() => handleDelete(doc.id, doc.original_filename)}
                          className="p-1.5 text-gray-400 hover:text-red-600 rounded"
                          title="Sil"
                        >
                          <Trash2 className="w-4 h-4" />
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
