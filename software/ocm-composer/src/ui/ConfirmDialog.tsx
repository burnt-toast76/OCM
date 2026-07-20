// SPDX-License-Identifier: AGPL-3.0-or-later
// spec/09: writes are unconditional, so this can't gate the mutation
// itself (it already happened) -- it's an acknowledgment of the
// server's own warnings[] text, quoted verbatim, that the user must
// dismiss.

import { useComposerStore } from "../store/store";

export function ConfirmDialog() {
  const pendingConfirm = useComposerStore((s) => s.pendingConfirm);
  const cancelConfirm = useComposerStore((s) => s.cancelConfirm);

  if (!pendingConfirm) return null;

  return (
    <div className="confirm-dialog__backdrop">
      <div className="confirm-dialog" role="alertdialog" aria-modal="true">
        <h2>Heads up</h2>
        <ul className="confirm-dialog__warnings">
          {pendingConfirm.warnings.map((w, i) => (
            <li key={i}>{w}</li>
          ))}
        </ul>
        <div className="confirm-dialog__actions">
          <button
            type="button"
            onClick={() => {
              pendingConfirm.onConfirm();
              cancelConfirm();
            }}
          >
            OK
          </button>
        </div>
      </div>
    </div>
  );
}
