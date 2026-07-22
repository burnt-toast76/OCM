// SPDX-License-Identifier: AGPL-3.0-or-later
// The chat panel: message input, drag-drop/browse attachments, streamed
// transcript, tool calls as compact chips (spec/09: "update_component ✓ /
// 2 refusals") that expand to the full envelope on click. Renders exactly
// what the SSE stream sent -- no interpretation of what a tool call
// means, same "render, don't re-derive" rule the rest of this app follows.

import { useRef, useState } from "react";
import type { DragEvent, FormEvent } from "react";
import { useComponentsStore } from "../../store/componentsStore";
import type { ChatTurnToolCall } from "../../store/componentsStore";

const ACCEPTED_EXTENSIONS = [".pdf", ".txt", ".step", ".stp"];

function ToolCallChip({ call }: { call: ChatTurnToolCall }) {
  const [expanded, setExpanded] = useState(false);
  const label = call.ok ? `${call.name} ✓` : `${call.name} ✗ ${call.refusalCount} refusal${call.refusalCount === 1 ? "" : "s"}`;
  return (
    <div className={`chat-tool-chip ${call.ok ? "chat-tool-chip--ok" : "chat-tool-chip--refused"}`}>
      <button type="button" className="chat-tool-chip__label" onClick={() => setExpanded((v) => !v)} aria-expanded={expanded}>
        {label}
      </button>
      {expanded && <pre className="chat-tool-chip__envelope">{JSON.stringify(call.envelope, null, 2)}</pre>}
    </div>
  );
}

export function ChatPanel() {
  const chatTurns = useComponentsStore((s) => s.chatTurns);
  const chatStreaming = useComponentsStore((s) => s.chatStreaming);
  const stagedAttachments = useComponentsStore((s) => s.stagedAttachments);
  const sendChatMessage = useComponentsStore((s) => s.sendChatMessage);
  const uploadAttachment = useComponentsStore((s) => s.uploadAttachment);
  const removeStagedAttachment = useComponentsStore((s) => s.removeStagedAttachment);
  const selectedComponentId = useComponentsStore((s) => s.selectedComponentId);
  const agentModels = useComponentsStore((s) => s.agentModels);
  const selectedModel = useComponentsStore((s) => s.selectedModel);
  const setSelectedModel = useComponentsStore((s) => s.setSelectedModel);

  const [draft, setDraft] = useState("");
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleSend = (e: FormEvent) => {
    e.preventDefault();
    const text = draft.trim();
    if (!text || chatStreaming) return;
    sendChatMessage(text);
    setDraft("");
  };

  const handleFiles = (files: FileList | null) => {
    if (!files) return;
    for (const file of Array.from(files)) void uploadAttachment(file);
  };

  const handleDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragOver(false);
    handleFiles(e.dataTransfer.files);
  };

  if (!selectedComponentId) {
    return (
      <div className="chat-panel">
        <p className="chat-panel__empty">Select or create a component to start a transcription chat.</p>
      </div>
    );
  }

  return (
    <div
      className={`chat-panel ${dragOver ? "chat-panel--drag-over" : ""}`}
      onDragOver={(e) => {
        e.preventDefault();
        setDragOver(true);
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={handleDrop}
    >
      <div className="chat-panel__header">
        <h2>Chat</h2>
        {agentModels.length > 0 && (
          <select
            className="chat-panel__model"
            aria-label="AI model"
            value={selectedModel ?? ""}
            onChange={(e) => setSelectedModel(e.target.value)}
            disabled={chatStreaming}
          >
            {agentModels.map((m) => (
              <option key={m.id} value={m.id}>
                {m.label}
              </option>
            ))}
          </select>
        )}
      </div>
      <div className="chat-panel__transcript">
        {chatTurns.length === 0 && <p className="chat-panel__empty">Describe what you're transcribing, or drop a datasheet below.</p>}
        {chatTurns.map((turn) => (
          <div key={turn.id} className={`chat-turn chat-turn--${turn.role}`}>
            <div className="chat-turn__text">
              {turn.text}
              {turn.streaming && <span className="chat-turn__cursor">▌</span>}
            </div>
            {turn.toolCalls.length > 0 && (
              <div className="chat-turn__tool-calls">
                {turn.toolCalls.map((call, i) => (
                  <ToolCallChip key={i} call={call} />
                ))}
              </div>
            )}
          </div>
        ))}
      </div>

      {stagedAttachments.length > 0 && (
        <ul className="chat-panel__staged" aria-label="Attachments for the next message">
          {stagedAttachments.map((a) => (
            <li key={a.filename}>
              <span>{a.filename}</span>
              {a.measured_envelope_mm && <span className="chat-panel__envelope-note"> ({a.measured_envelope_mm.join("×")} mm)</span>}
              <button type="button" onClick={() => removeStagedAttachment(a.filename)} aria-label={`Remove ${a.filename}`}>
                ×
              </button>
            </li>
          ))}
        </ul>
      )}

      <form className="chat-panel__composer" onSubmit={handleSend}>
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept={ACCEPTED_EXTENSIONS.join(",")}
          className="chat-panel__file-input"
          onChange={(e) => {
            handleFiles(e.target.files);
            e.target.value = "";
          }}
        />
        <button
          type="button"
          className="chat-panel__attach"
          onClick={() => fileInputRef.current?.click()}
          title="Attach a datasheet (pdf, txt, step) -- add more than one if, e.g., the pinout is in a separate document"
        >
          📎
        </button>
        <textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) handleSend(e);
          }}
          placeholder="Transcribe this datasheet…"
          rows={2}
          disabled={chatStreaming}
        />
        <button type="submit" disabled={chatStreaming || !draft.trim()}>
          Send
        </button>
      </form>
    </div>
  );
}
