// SPDX-License-Identifier: AGPL-3.0-or-later
// The schema-driven component form -- one section per top-level property
// describe_schema returns (spec/10's own sections: electrical, pneumatic,
// comms, geometry, hazards, notes, ...), in the schema's own property
// order. Identity fields (ocm_version, id, revision) are server-managed,
// not part of this editable body -- they're shown by ComponentDetail
// itself, above the form.

import { useComponentsStore } from "../../store/componentsStore";
import { SchemaField } from "./SchemaField";

const IDENTITY_FIELDS = new Set(["ocm_version", "id", "revision"]);

export function ComponentForm() {
  const schema = useComponentsStore((s) => s.schema);
  const detail = useComponentsStore((s) => s.detail);
  const fieldErrors = useComponentsStore((s) => s.fieldErrors);
  const agentFilledFields = useComponentsStore((s) => s.agentFilledFields);
  const saveField = useComponentsStore((s) => s.saveField);

  if (!schema || !detail) {
    return (
      <div className="component-form">
        <p className="component-form__empty">Loading…</p>
      </div>
    );
  }

  const sections = Object.entries(schema.properties ?? {}).filter(([key]) => !IDENTITY_FIELDS.has(key));

  return (
    <div className="component-form">
      {sections.map(([key, fieldSchema]) => {
        const errors = fieldErrors[key] ?? [];
        const agentFilled = agentFilledFields.has(key);
        return (
          <section key={key} className={`component-form__section ${errors.length > 0 ? "component-form__section--error" : ""}`} data-field={key}>
            <h3 className="component-form__heading">
              {key}
              {agentFilled && (
                <span className="component-form__agent-marker" title="Filled by the agent this session">
                  ✦
                </span>
              )}
            </h3>
            {fieldSchema.description && <p className="component-form__description">{fieldSchema.description}</p>}
            <SchemaField schema={fieldSchema} path={[key]} value={detail.component[key]} onCommit={(path, value) => void saveField(path, value)} />
            {errors.length > 0 && (
              <ul className="component-form__errors">
                {errors.map((r, i) => (
                  <li key={i}>
                    <span className="component-form__error-message">{r.message}</span>
                    {r.hint && <span className="component-form__error-hint"> {r.hint}</span>}
                  </li>
                ))}
              </ul>
            )}
          </section>
        );
      })}
    </div>
  );
}
