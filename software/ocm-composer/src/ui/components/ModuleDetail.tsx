// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { moduleAttachmentDownloadUrl } from "../../api/client";
import { useModulesStore } from "../../store/modulesStore";
import { AttachmentsList } from "./AttachmentsList";
import { WiringCanvas } from "./WiringCanvas";
import { ModuleSceneCanvas } from "../../scene/ModuleSceneCanvas";

const ACCEPTED_EXTENSIONS = [".step", ".stp"];

type Tab = "assembly" | "electrical" | "pneumatic" | "communication";

const TABS: { id: Tab; label: string }[] = [
  { id: "assembly", label: "Assembly" },
  { id: "electrical", label: "Electrical" },
  { id: "pneumatic", label: "Pneumatic" },
  { id: "communication", label: "Communication" },
];

// Non-3D shell first (list/detail wired to the store, publish flow, placed-
// components table, attachments panel) -- the scene canvas and placement
// picker land in later passes on top of this same component, per the
// approved plan's own sequencing (each is its own checkpoint).
export function ModuleDetail() {
  const [activeTab, setActiveTab] = useState<Tab>("assembly");
  const selectedModuleId = useModulesStore((s) => s.selectedModuleId);
  const detail = useModulesStore((s) => s.detail);
  const attachments = useModulesStore((s) => s.attachments);
  const componentOptions = useModulesStore((s) => s.componentOptions);
  const placementError = useModulesStore((s) => s.placementError);
  const clearPlacementError = useModulesStore((s) => s.clearPlacementError);
  const publish = useModulesStore((s) => s.publish);
  const removeComponentInstance = useModulesStore((s) => s.removeComponentInstance);
  const uploadStepAttachment = useModulesStore((s) => s.uploadStepAttachment);
  const placeComponentInstance = useModulesStore((s) => s.placeComponentInstance);
  const moveComponentInstance = useModulesStore((s) => s.moveComponentInstance);
  const selectedRefdes = useModulesStore((s) => s.selectedRefdes);
  const selectComponentInstance = useModulesStore((s) => s.selectComponentInstance);

  const [revision, setRevision] = useState("1.0.0");
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [placeComponentId, setPlaceComponentId] = useState("");
  const [placeRefdes, setPlaceRefdes] = useState("");
  const [placing, setPlacing] = useState(false);

  const components = detail?.manifest.components ?? [];
  const placedRefdes = new Set(components.map((c) => c.refdes));

  // Rotation is authored via these numeric side-panel inputs (Decisions
  // locked in: no 3D rotate gizmo -- nothing else in the composer has a
  // rotate-drag precedent). Position (xyz) is editable here too, for
  // precise placement without needing to drag. Uncontrolled-ish: synced
  // FROM the server-confirmed pose whenever selection changes or that
  // pose itself changes (e.g. an XY drag commits while this panel is
  // open) -- never fights the user's in-progress typing otherwise.
  const [poseFields, setPoseFields] = useState({ x: "0", y: "0", z: "0", roll: "0", pitch: "0", yaw: "0" });
  const selected = components.find((c) => c.refdes === selectedRefdes) ?? null;
  const poseKey = selected?.pose ? `${selected.pose.xyz_mm.join(",")}|${selected.pose.rpy_deg.join(",")}` : "";
  useEffect(() => {
    if (!selected?.pose) return;
    const [x, y, z] = selected.pose.xyz_mm;
    const [roll, pitch, yaw] = selected.pose.rpy_deg;
    setPoseFields({ x: String(x), y: String(y), z: String(z), roll: String(roll), pitch: String(pitch), yaw: String(yaw) });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedRefdes, poseKey]);

  if (!selectedModuleId) {
    return (
      <div className="module-detail module-detail--empty">
        <p>Select a module, or create a new draft, to begin.</p>
      </div>
    );
  }

  const handleApplyPose = () => {
    if (!selected) return;
    const nums = Object.fromEntries(Object.entries(poseFields).map(([k, v]) => [k, Number(v)]));
    if (Object.values(nums).some((n) => Number.isNaN(n))) return;
    void moveComponentInstance(selected.refdes, {
      xyz_mm: [nums.x, nums.y, nums.z],
      rpy_deg: [nums.roll, nums.pitch, nums.yaw],
    });
  };

  const handlePlace = async (e: FormEvent) => {
    e.preventDefault();
    const componentId = placeComponentId;
    const refdes = placeRefdes.trim();
    const chosen = componentOptions.find((c) => c.id === componentId);
    if (!chosen || !refdes || placedRefdes.has(refdes) || placing) return;
    setPlacing(true);
    try {
      await placeComponentInstance(refdes, `${chosen.id}@${chosen.revision}`, { xyz_mm: [0, 0, 0], rpy_deg: [0, 0, 0] });
      if (useModulesStore.getState().placementError) return;
      setPlaceRefdes("");
    } finally {
      setPlacing(false);
    }
  };

  return (
    <div className="module-detail">
      <header className="module-detail__header">
        <h1>{selectedModuleId}</h1>
        {detail && (
          <span className={`module-detail__badge ${detail.draft ? "module-detail__badge--draft" : ""}`}>
            {detail.draft ? "draft" : detail.revision}
          </span>
        )}
        <div className="module-detail__publish">
          <input
            type="text"
            value={revision}
            onChange={(e) => setRevision(e.target.value)}
            placeholder="1.0.0"
            aria-label="Publish revision"
          />
          <button type="button" disabled={!detail} onClick={() => void publish(revision)}>
            Publish
          </button>
        </div>
      </header>

      {placementError && (
        <div className="module-detail__placement-error" role="alert">
          <span>{placementError}</span>
          <button type="button" onClick={clearPlacementError} aria-label="Dismiss">
            ×
          </button>
        </div>
      )}

      <div className="module-detail__tabs" role="tablist">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={activeTab === tab.id}
            className={
              activeTab === tab.id ? "module-detail__tab module-detail__tab--active" : "module-detail__tab"
            }
            onClick={() => setActiveTab(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {activeTab === "assembly" && (
        <>
          <ModuleSceneCanvas />

          {selected && (
            <div className="module-detail__pose-panel">
              <h2>
                {selected.refdes} <span className="module-detail__pose-panel-ref">{selected.ref}</span>
                <button type="button" className="module-detail__pose-panel-close" onClick={() => selectComponentInstance(null)} aria-label="Deselect">
                  ×
                </button>
              </h2>
              <div className="module-detail__pose-panel-fields">
                {(["x", "y", "z"] as const).map((axis) => (
                  <label key={axis}>
                    {axis} (mm)
                    <input
                      type="number"
                      value={poseFields[axis]}
                      onChange={(e) => setPoseFields((prev) => ({ ...prev, [axis]: e.target.value }))}
                    />
                  </label>
                ))}
                {(["roll", "pitch", "yaw"] as const).map((axis) => (
                  <label key={axis}>
                    {axis} (deg)
                    <input
                      type="number"
                      value={poseFields[axis]}
                      onChange={(e) => setPoseFields((prev) => ({ ...prev, [axis]: e.target.value }))}
                    />
                  </label>
                ))}
              </div>
              <button type="button" onClick={handleApplyPose}>
                Apply
              </button>
            </div>
          )}

          <div className="module-detail__body">
            <div className="module-detail__backdrop-upload">
              <input
                ref={fileInputRef}
                type="file"
                accept={ACCEPTED_EXTENSIONS.join(",")}
                className="module-detail__file-input"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  e.target.value = "";
                  if (file) void uploadStepAttachment(file);
                }}
              />
              <button type="button" className="module-detail__attach" onClick={() => fileInputRef.current?.click()}>
                📎 Upload STEP file (optional visual backdrop -- not sliced or clickable, just a reference)
              </button>
            </div>

            <AttachmentsList
              attachments={attachments}
              downloadUrl={(filename) => moduleAttachmentDownloadUrl(selectedModuleId, filename)}
            />

            <div className="module-detail__components">
              <h2>Placed components</h2>

              <form className="module-detail__place-form" onSubmit={(e) => void handlePlace(e)}>
                <select
                  value={placeComponentId}
                  onChange={(e) => setPlaceComponentId(e.target.value)}
                  aria-label="Component to place"
                >
                  <option value="">Choose a published component…</option>
                  {componentOptions.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.id} ({c.vendor ?? "—"})
                    </option>
                  ))}
                </select>
                <input
                  type="text"
                  value={placeRefdes}
                  onChange={(e) => setPlaceRefdes(e.target.value)}
                  placeholder="Refdes, e.g. VG1"
                  aria-label="New instance reference designator"
                />
                <button type="submit" disabled={!placeComponentId || !placeRefdes.trim() || placing}>
                  Place
                </button>
              </form>

              {components.length === 0 ? (
                <p className="module-detail__components-empty">No components placed yet.</p>
              ) : (
                <ul className="module-detail__components-list">
                  {components.map((c) => (
                    <li
                      key={c.refdes}
                      className={
                        c.refdes === selectedRefdes
                          ? "module-detail__components-row module-detail__components-row--selected"
                          : "module-detail__components-row"
                      }
                    >
                      <button
                        type="button"
                        className="module-detail__components-refdes"
                        disabled={!c.pose}
                        onClick={() => selectComponentInstance(c.refdes)}
                      >
                        {c.refdes}
                      </button>
                      <span className="module-detail__components-ref">{c.ref}</span>
                      <span className="module-detail__components-pose">
                        {c.pose ? c.pose.xyz_mm.map((v) => v.toFixed(1)).join(", ") + " mm" : "unplaced"}
                      </span>
                      <button
                        type="button"
                        className="module-detail__components-remove"
                        onClick={() => void removeComponentInstance(c.refdes)}
                        aria-label={`Remove ${c.refdes}`}
                      >
                        Remove
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </>
      )}

      {activeTab === "electrical" && <WiringCanvas domain="electrical" />}
      {activeTab === "pneumatic" && <WiringCanvas domain="pneumatic" />}
      {activeTab === "communication" && <WiringCanvas domain="communication" />}
    </div>
  );
}
