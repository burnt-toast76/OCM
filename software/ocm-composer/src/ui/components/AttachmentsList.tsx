// SPDX-License-Identifier: AGPL-3.0-or-later
// Every file previously uploaded for this component (datasheets, manuals,
// STEP models -- whatever was ever attached, not just what's staged THIS
// session) so a human can come back later and re-check the source a value
// was transcribed from. Read-only: uploading/removing happens through
// ComponentsList's pre-creation dropzone or ChatPanel's own attach button.

import { attachmentDownloadUrl } from "../../api/client";
import { useComponentsStore } from "../../store/componentsStore";

const KIND_LABELS: Record<string, string> = { pdf: "PDF", text: "Text", step: "STEP", other: "File" };

export function AttachmentsList() {
  const selectedComponentId = useComponentsStore((s) => s.selectedComponentId);
  const attachments = useComponentsStore((s) => s.attachments);

  if (!selectedComponentId || attachments.length === 0) return null;

  return (
    <div className="attachments-list">
      <h2>Attachments</h2>
      <ul className="attachments-list__items">
        {attachments.map((a) => (
          <li key={a.filename} className="attachments-list__row">
            <a
              href={attachmentDownloadUrl(selectedComponentId, a.filename)}
              target="_blank"
              rel="noreferrer"
              className="attachments-list__link"
            >
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
