// SPDX-License-Identifier: AGPL-3.0-or-later
// Renders ONE field from the component JSON Schema (describe_schema's own
// output), recursively -- objects nest a fieldset per property, arrays of
// enum-strings become checkboxes, arrays of objects become repeatable
// rows. Nothing here decides whether a value is VALID; the schema only
// decides what CONTROL to show, and every commit still goes through
// update_component -- the server's refusal is what actually gates
// correctness (rendered by the caller, via `errors`).

import type { JsonSchemaNode } from "../../api/types";

export interface SchemaFieldProps {
  schema: JsonSchemaNode;
  path: string[];
  value: unknown;
  onCommit: (path: string[], value: unknown) => void;
  disabled?: boolean;
}

function enumValues(schema: JsonSchemaNode): string[] | null {
  if (schema.enum) return schema.enum.map(String);
  if (schema.anyOf) {
    for (const branch of schema.anyOf) {
      if (branch.enum) return branch.enum.map(String);
    }
  }
  return null;
}

function fieldId(path: string[]): string {
  return `field-${path.join("-")}`;
}

export function SchemaField({ schema, path, value, onCommit, disabled }: SchemaFieldProps) {
  const id = fieldId(path);
  const values = enumValues(schema);

  if (schema.type === "object" || (schema.properties && !schema.type)) {
    const obj = (value ?? {}) as Record<string, unknown>;
    const entries = Object.entries(schema.properties ?? {});
    return (
      <div className="schema-object" role="group" aria-labelledby={id}>
        {entries.map(([key, childSchema]) => (
          <SchemaFieldRow key={key} label={key} schema={childSchema} path={[...path, key]} value={obj[key]} onCommit={onCommit} disabled={disabled} />
        ))}
      </div>
    );
  }

  if (schema.type === "array") {
    const items = schema.items ?? {};
    const itemEnum = enumValues(items);
    if (itemEnum) {
      // Array of enum strings (e.g. hazards) -- a set of checkboxes.
      const current = new Set(((value ?? []) as unknown[]).map(String));
      return (
        <div className="schema-checklist" role="group" aria-labelledby={id}>
          {itemEnum.map((option) => (
            <label key={option} className="schema-checklist__option">
              <input
                type="checkbox"
                checked={current.has(option)}
                disabled={disabled}
                onChange={(e) => {
                  const next = new Set(current);
                  if (e.target.checked) next.add(option);
                  else next.delete(option);
                  onCommit(path, [...next]);
                }}
              />
              {option}
            </label>
          ))}
        </div>
      );
    }

    // Array of objects (e.g. electrical.supplies, comms.signals) --
    // repeatable rows, each its own nested object form. `value` is
    // whatever's genuinely on disk for an ADR-0014 draft, which can be
    // malformed (a past bug wrote one of these as an object keyed by
    // stringified index instead of a real array) -- guard with
    // Array.isArray rather than trusting the schema's own claim, so a
    // bad shape renders as an empty, fixable list instead of crashing the
    // whole page on `rows.map`.
    const rows = Array.isArray(value) ? (value as Record<string, unknown>[]) : [];
    return (
      <div className="schema-array">
        {rows.map((row, i) => (
          <div key={i} className="schema-array__row">
            <SchemaField schema={{ ...items, type: items.type ?? "object" }} path={[...path, String(i)]} value={row} onCommit={onCommit} disabled={disabled} />
            <button
              type="button"
              className="schema-array__remove"
              disabled={disabled}
              onClick={() => onCommit(path, rows.filter((_, j) => j !== i))}
            >
              Remove
            </button>
          </div>
        ))}
        <button type="button" className="schema-array__add" disabled={disabled} onClick={() => onCommit(path, [...rows, {}])}>
          + Add
        </button>
      </div>
    );
  }

  if (values) {
    return (
      <>
        <input id={id} list={`${id}-options`} defaultValue={value ? String(value) : ""} disabled={disabled} onBlur={(e) => onCommit(path, e.target.value || undefined)} />
        <datalist id={`${id}-options`}>
          {values.map((v) => (
            <option key={v} value={v} />
          ))}
        </datalist>
      </>
    );
  }

  if (schema.type === "number") {
    return (
      <input
        id={id}
        type="number"
        defaultValue={typeof value === "number" ? value : ""}
        disabled={disabled}
        onBlur={(e) => onCommit(path, e.target.value === "" ? undefined : Number(e.target.value))}
      />
    );
  }

  // Plain string, and the fallback for anything this form doesn't have a
  // more specific control for -- still schema-driven (the field exists
  // because the schema named it), just rendered as free text.
  const multiline = schema.description && schema.description.length > 60;
  const commonProps = {
    id,
    defaultValue: value ? String(value) : "",
    disabled,
    onBlur: (e: React.FocusEvent<HTMLInputElement | HTMLTextAreaElement>) => onCommit(path, e.target.value || undefined),
  };
  return multiline ? <textarea rows={3} {...commonProps} /> : <input type="text" {...commonProps} />;
}

interface SchemaFieldRowProps extends SchemaFieldProps {
  label: string;
}

function SchemaFieldRow({ label, schema, path, value, onCommit, disabled }: SchemaFieldRowProps) {
  const id = fieldId(path);
  const isContainer = schema.type === "object" || schema.type === "array" || (schema.properties && !schema.type);
  return (
    <div className={`schema-field ${isContainer ? "schema-field--container" : ""}`}>
      <label id={id} htmlFor={isContainer ? undefined : id}>
        {label}
      </label>
      <SchemaField schema={schema} path={path} value={value} onCommit={onCommit} disabled={disabled} />
    </div>
  );
}
