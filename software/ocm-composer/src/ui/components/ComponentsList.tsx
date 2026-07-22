// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useRef, useState } from "react";
import type { DragEvent, FormEvent } from "react";
import { useComponentsStore } from "../../store/componentsStore";

// spec/10's own small, open kind set (plus x- extension, typed freely below).
const KNOWN_KINDS = [
  "vacuum_ejector",
  "io_link_master",
  "valve_island",
  "sensor",
  "camera",
  "actuator",
  "drive",
  "gripper_body",
  "dispenser",
  "feeder_body",
  "bracket",
  "other",
];

const ACCEPTED_EXTENSIONS = [".pdf", ".txt", ".step", ".stp"];

// The id is still `com.<vendor>.<part_number>` underneath (every verb,
// storage path, and cross-reference still keys off it) -- the user just
// never has to type or see that dotted form anymore. Lowercased and
// stripped to the id schema's own charset (`^[a-z0-9]+(\.[a-z0-9_-]+)+$`
// per segment); the vendor/part_number FIELDS still get the human's exact
// text, unmodified -- this only affects the derived identifier.
function slugify(s: string): string {
  return s.trim().toLowerCase().replace(/[^a-z0-9_-]+/g, "-").replace(/^-+|-+$/g, "") || "x";
}

const TRANSCRIBE_PROMPT =
  "I've attached a datasheet for this part. Please transcribe it into the component definition -- " +
  "zero assumption: only include what it actually states, restate/convert units freely, and tell me " +
  "what's left for me to fill in.";

export function ComponentsList() {
  const components = useComponentsStore((s) => s.components);
  const selectedComponentId = useComponentsStore((s) => s.selectedComponentId);
  const loading = useComponentsStore((s) => s.loading);
  const loadComponents = useComponentsStore((s) => s.loadComponents);
  const selectComponent = useComponentsStore((s) => s.selectComponent);
  const createDraft = useComponentsStore((s) => s.createDraft);
  const uploadAttachment = useComponentsStore((s) => s.uploadAttachment);
  const sendChatMessage = useComponentsStore((s) => s.sendChatMessage);

  const [newVendor, setNewVendor] = useState("");
  const [newPartNumber, setNewPartNumber] = useState("");
  const [newDescription, setNewDescription] = useState("");
  const [newKind, setNewKind] = useState(KNOWN_KINDS[0]);
  // Staged client-side only, until a draft exists to attach them to --
  // uploadComponentAttachment needs a component id, which doesn't exist
  // until create_component_draft has actually run.
  const [stagedFiles, setStagedFiles] = useState<File[]>([]);
  const [dragOver, setDragOver] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    void loadComponents();
  }, [loadComponents]);

  const addFiles = (files: FileList | null) => {
    if (!files) return;
    // Array.from RIGHT HERE, synchronously -- e.target.files is a LIVE
    // FileList tied to the DOM element, and the caller resets
    // e.target.value immediately after calling this (so the same file can
    // be re-picked later), which empties that same live list in place.
    // Reading it lazily inside the setState updater closure -- which React
    // doesn't necessarily run synchronously -- would see it already empty.
    const snapshot = Array.from(files);
    setStagedFiles((prev) => [...prev, ...snapshot]);
  };

  const handleCreate = async (e: FormEvent) => {
    e.preventDefault();
    const vendor = newVendor.trim();
    const partNumber = newPartNumber.trim();
    const description = newDescription.trim();
    if (!vendor || !partNumber || submitting) return;
    const id = `com.${slugify(vendor)}.${slugify(partNumber)}`;

    // Authored directly by the human at creation time, not transcribed --
    // unlike vendor/source's usual "leave blank until the datasheet says
    // so" rule (ADR-0014), these are known right now, before any datasheet
    // is even attached: they're WHY this draft is being created at all.
    const initialFields: Record<string, unknown> = { vendor, part_number: partNumber };
    if (description) initialFields.name = description;

    setSubmitting(true);
    try {
      await createDraft(id, newKind, initialFields);
      // createDraft only reaches selectComponent(id) on success (e.g. NOT
      // if the id already exists) -- checking selection is how the caller
      // tells success from refusal without createDraft needing its own
      // boolean return.
      if (useComponentsStore.getState().selectedComponentId !== id) return;

      const files = stagedFiles;
      setNewVendor("");
      setNewPartNumber("");
      setNewDescription("");
      setStagedFiles([]);

      for (const file of files) {
        await uploadAttachment(file);
      }
      if (files.length > 0) {
        // Reuses the exact same chat path a manual upload+message would --
        // sendChatMessage picks up whatever uploadAttachment just staged
        // in the store, same as if the user had dropped these files onto
        // the chat panel themselves and typed this prompt.
        sendChatMessage(TRANSCRIBE_PROMPT);
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="components-list">
      <h2>Components</h2>
      {components.length === 0 && !loading && <p className="components-list__empty">No components yet.</p>}
      <ul className="components-list__items">
        {components.map((c) => (
          <li key={c.id} className={c.id === selectedComponentId ? "components-list__row components-list__row--selected" : "components-list__row"}>
            <button type="button" className="components-list__name" onClick={() => void selectComponent(c.id)}>
              <span className="components-list__id">{c.id}</span>
              <span className="components-list__meta">
                {c.vendor ?? "—"} · {c.kind ?? "—"}
              </span>
            </button>
            {c.draft && <span className="components-list__badge">draft</span>}
          </li>
        ))}
      </ul>

      <form className="components-list__new" onSubmit={(e) => void handleCreate(e)}>
        <input type="text" value={newVendor} onChange={(e) => setNewVendor(e.target.value)} placeholder="Vendor" aria-label="New component vendor" />
        <input
          type="text"
          value={newPartNumber}
          onChange={(e) => setNewPartNumber(e.target.value)}
          placeholder="Part number"
          aria-label="New component part number"
        />
        <input
          type="text"
          value={newDescription}
          onChange={(e) => setNewDescription(e.target.value)}
          placeholder="Description (optional)"
          aria-label="New component description"
        />
        <select value={newKind} onChange={(e) => setNewKind(e.target.value)} aria-label="New component kind">
          {KNOWN_KINDS.map((k) => (
            <option key={k} value={k}>
              {k}
            </option>
          ))}
        </select>

        <div
          className={`components-list__dropzone ${dragOver ? "components-list__dropzone--drag-over" : ""}`}
          onDragOver={(e: DragEvent<HTMLDivElement>) => {
            e.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e: DragEvent<HTMLDivElement>) => {
            e.preventDefault();
            setDragOver(false);
            addFiles(e.dataTransfer.files);
          }}
        >
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept={ACCEPTED_EXTENSIONS.join(",")}
            className="components-list__file-input"
            onChange={(e) => {
              addFiles(e.target.files);
              e.target.value = "";
            }}
          />
          <button type="button" className="components-list__attach" onClick={() => fileInputRef.current?.click()}>
            📎 Attach datasheet (optional -- pdf, txt, step)
          </button>
          {stagedFiles.length > 0 && (
            <ul className="components-list__staged-files">
              {stagedFiles.map((f, i) => (
                <li key={i}>
                  <span>{f.name}</span>
                  <button
                    type="button"
                    onClick={() => setStagedFiles((prev) => prev.filter((_, j) => j !== i))}
                    aria-label={`Remove ${f.name}`}
                  >
                    ×
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        <button type="submit" disabled={!newVendor.trim() || !newPartNumber.trim() || submitting}>
          {stagedFiles.length > 0 ? "New draft & transcribe" : "New draft"}
        </button>
      </form>
    </div>
  );
}
