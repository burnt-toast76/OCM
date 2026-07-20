// SPDX-License-Identifier: AGPL-3.0-or-later
// Renders the engine's own refusal message and hint verbatim -- never
// paraphrased (spec/09 design principle #1: "render refusals, never
// interpret them").

import { useComposerStore } from "../store/store";

export function ToastHost() {
  const toasts = useComposerStore((s) => s.toasts);
  const dismissToast = useComposerStore((s) => s.dismissToast);

  return (
    <div className="toast-host" role="status" aria-live="polite">
      {toasts.map((t) => (
        <div key={t.id} className={`toast toast--${t.kind}`} data-testid="toast">
          <div className="toast__header">
            <span className="toast__title">{t.title}</span>
            <button type="button" className="toast__close" onClick={() => dismissToast(t.id)} aria-label="Dismiss">
              ×
            </button>
          </div>
          <p className="toast__message">{t.message}</p>
          {t.hint && <p className="toast__hint">{t.hint}</p>}
        </div>
      ))}
    </div>
  );
}
