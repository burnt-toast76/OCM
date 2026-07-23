// SPDX-License-Identifier: AGPL-3.0-or-later
// Every file previously uploaded for a component OR module (datasheets,
// manuals, STEP models -- whatever was ever attached, not just what's
// staged THIS session) so a human can come back later and re-check the
// source a value was transcribed from. Read-only: uploading/removing
// happens through each page's own upload UI (ComponentsList's pre-creation
// dropzone, ChatPanel's attach button, or ModuleDetail's STEP-upload
// button). Takes its data as props rather than reading a specific store
// directly, so both pages can share this one component.

import type { AttachmentRow } from "../../api/types";

const KIND_LABELS: Record<string, string> = { pdf: "PDF", text: "Text", step: "STEP", other: "File" };

export interface AttachmentsListProps {
  attachments: AttachmentRow[];
  downloadUrl: (filename: string) => string;
}

export function AttachmentsList({ attachments, downloadUrl }: AttachmentsListProps) {
  if (attachments.length === 0) return null;

  return (
    <div className="attachments-list">
      <h2>Attachments</h2>
      <ul className="attachments-list__items">
        {attachments.map((a) => (
          <li key={a.filename} className="attachments-list__row">
            <a href={downloadUrl(a.filename)} target="_blank" rel="noreferrer" className="attachments-list__link">
              {a.filename}
            </a>
            <span className="attachments-list__badges">
              <span className="attachments-list__kind">{KIND_LABELS[a.kind] ?? a.kind}</span>
              {a.glb_status === "pending" && (
                <span className="attachments-list__status attachments-list__status--pending">Converting geometry…</span>
              )}
              {a.glb_status === "failed" && (
                <span
                  className="attachments-list__status attachments-list__status--failed"
                  title="Geometry conversion failed -- the file itself is still stored and downloadable"
                >
                  Conversion failed
                </span>
              )}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
