// SPDX-License-Identifier: AGPL-3.0-or-later
import { useMemo } from "react";
import { attachmentDownloadUrl } from "../../api/client";
import { useComponentsStore } from "../../store/componentsStore";
import { ComponentForm } from "./ComponentForm";
import { ChecklistPanel } from "./ChecklistPanel";
import { ChatPanel } from "./ChatPanel";
import { GlbViewer } from "./GlbViewer";
import { AttachmentsList } from "./AttachmentsList";
import { ConnectorSymbols } from "./ConnectorSymbols";

export function ComponentDetail() {
  const selectedComponentId = useComponentsStore((s) => s.selectedComponentId);
  const detail = useComponentsStore((s) => s.detail);
  const attachments = useComponentsStore((s) => s.attachments);
  const deleteComponent = useComponentsStore((s) => s.deleteComponent);

  // Any attachment with a converted GLB sibling -- typically the one STEP
  // file a draft has, but this doesn't assume there's exactly one.
  const glbFilename = useMemo(() => attachments.find((a) => a.glb)?.glb ?? null, [attachments]);

  if (!selectedComponentId) {
    return (
      <div className="component-detail component-detail--empty">
        <p>Select a component, or create a new draft, to begin.</p>
      </div>
    );
  }

  return (
    <div className="component-detail">
      <header className="component-detail__header">
        <h1>{selectedComponentId}</h1>
        {detail && (
          <span className={`component-detail__badge ${detail.draft ? "component-detail__badge--draft" : ""}`}>
            {detail.draft ? "draft" : detail.revision}
          </span>
        )}
        <button
          type="button"
          className="component-detail__delete"
          onClick={() => {
            if (window.confirm(`Delete ${selectedComponentId}? This removes its manifest and attachments permanently.`)) {
              void deleteComponent(selectedComponentId);
            }
          }}
        >
          Delete
        </button>
      </header>

      {glbFilename && <GlbViewer url={attachmentDownloadUrl(selectedComponentId, glbFilename)} />}
      <ConnectorSymbols />

      <div className="component-detail__body">
        <ComponentForm />
        <div className="component-detail__side">
          <ChecklistPanel />
          <AttachmentsList attachments={attachments} downloadUrl={(filename) => attachmentDownloadUrl(selectedComponentId, filename)} />
          <ChatPanel />
        </div>
      </div>
    </div>
  );
}
