// SPDX-License-Identifier: AGPL-3.0-or-later
// The required Components-page smoke test: create a draft, type a fact
// into chat (the SSE stream is mocked -- no real ANTHROPIC_API_KEY here),
// watch the form update from the resulting tool_call, then edit a field
// directly and watch the checklist shrink again. Runs against the same
// throwaway fixture backend every other e2e spec uses (setup-fixture.mjs),
// never the real working tree.
//
// The mock's own route handler performs a REAL update_component call
// against the backend before responding -- this is not just canned SSE
// text the frontend renders inertly; it's what makes "the form updates"
// a genuine, verifiable claim: the store's onToolCall handler reacts to
// the (fake) SSE event by re-fetching describe_component for real, and
// that refetch only shows the new vendor value because this route
// handler actually wrote it moments earlier.

import { test, expect } from "@playwright/test";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const BACKEND = `http://127.0.0.1:${process.env.OCM_TEST_BACKEND_PORT ?? "8000"}`;

test("create draft, chat sets a field (mocked SSE), then a direct field edit shrinks the checklist further", async ({ page }) => {
  const testId = `com.example.chat-test-${Date.now()}`;

  await page.goto("/composer/");
  await page.getByRole("button", { name: "Menu" }).click();
  await page.getByRole("menuitem", { name: "Components" }).click();

  // -- create draft --------------------------------------------------
  await page.getByPlaceholder("com.vendor.part.model").fill(testId);
  await page.getByLabel("New component kind").selectOption("vacuum_ejector");
  await page.getByRole("button", { name: "New draft" }).click();
  await expect(page.locator("h1", { hasText: testId })).toBeVisible();

  // A fresh draft is missing vendor + source (ADR-0014: never pre-filled).
  await expect(page.locator(".checklist-panel__item")).toHaveCount(2);

  // -- mock /agent/chat: the "agent" sets vendor for real, then tells the
  // frontend it did, over a canned SSE stream ------------------------
  const agentVendor = "Acme Pneumatics (via agent)";
  await page.route("**/agent/chat", async (route) => {
    const res = await fetch(`${BACKEND}/update_component`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ id: testId, patch: [{ op: "add", path: "/vendor", value: agentVendor }] }),
    });
    expect(res.ok).toBe(true);

    const sse =
      'event: text\ndata: {"delta":"Setting the vendor now."}\n\n' +
      `event: tool_call\ndata: {"name":"update_component","ok":true,"refusal_count":0,"envelope":{"ok":true,"refusals":[],"warnings":[],"data":{"id":"${testId}","revision":"0.1.0","draft":true}}}\n\n` +
      "event: done\ndata: {}\n\n";

    await route.fulfill({ status: 200, contentType: "text/event-stream", body: sse });
  });

  await page.getByPlaceholder("Transcribe this datasheet…").fill("This part's vendor is Acme Pneumatics.");
  await page.getByRole("button", { name: "Send" }).click();

  await expect(page.locator(".chat-turn--assistant").last()).toContainText("Setting the vendor now.");
  await expect(page.locator(".chat-tool-chip__label")).toContainText("update_component ✓");

  // -- form updates: the vendor field now shows what the "agent" set,
  // via a REAL describe_component refetch triggered by the tool_call
  // event, not just something painted onto the DOM directly -----------
  await expect(page.locator('[data-field="vendor"] input')).toHaveValue(agentVendor);

  // -- checklist shrinks (from chat): vendor's own refusal is gone,
  // source's is not (the agent never touched it) ----------------------
  await expect(page.locator(".checklist-panel__item")).toHaveCount(1);
  await expect(page.locator(".checklist-panel__item")).toContainText("source");

  // -- edit a field directly (no chat involved this time) --------------
  const sourceInputs = page.locator('[data-field="source"] input, [data-field="source"] textarea');
  await sourceInputs.nth(0).fill("datasheet");
  await sourceInputs.nth(0).blur();
  await sourceInputs.nth(1).fill("Fake datasheet, worked example only");
  await sourceInputs.nth(1).blur();

  // -- checklist shrinks again (from a direct field edit): nothing left --
  await expect(page.locator(".checklist-panel__item")).toHaveCount(0);
  await expect(page.getByText("Nothing outstanding -- ready to publish.")).toBeVisible();
});

test("the chat panel lets you choose which AI model to use, and sends that choice with the request", async ({ page }) => {
  const testId = `com.example.model-picker-test-${Date.now()}`;

  await page.goto("/composer/");
  await page.getByRole("button", { name: "Menu" }).click();
  await page.getByRole("menuitem", { name: "Components" }).click();

  await page.getByPlaceholder("com.vendor.part.model").fill(testId);
  await page.getByLabel("New component kind").selectOption("sensor");
  await page.getByRole("button", { name: "New draft" }).click();
  await expect(page.locator("h1", { hasText: testId })).toBeVisible();

  // Populated for real from GET /agent/models against the fixture
  // backend -- not mocked -- and defaults to whatever that response's own
  // `default` field says.
  const picker = page.getByLabel("AI model");
  await expect(picker).toHaveValue("claude-sonnet-5");
  await picker.selectOption("claude-haiku-4-5-20251001");

  let capturedModel: string | undefined;
  await page.route("**/agent/chat", async (route) => {
    capturedModel = route.request().postDataJSON().model;
    await route.fulfill({ status: 200, contentType: "text/event-stream", body: "event: done\ndata: {}\n\n" });
  });

  await page.getByPlaceholder("Transcribe this datasheet…").fill("hello");
  await page.getByRole("button", { name: "Send" }).click();

  await expect.poll(() => capturedModel).toBe("claude-haiku-4-5-20251001");
});

test("attaching a datasheet before creating uploads it to the new draft and auto-starts transcription", async ({ page }) => {
  const testId = `com.example.precreate-test-${Date.now()}`;
  const pdfPath = path.join(os.tmpdir(), `ocm-e2e-datasheet-${Date.now()}.pdf`);
  fs.writeFileSync(pdfPath, "%PDF-1.4 fake datasheet bytes for testing");

  await page.goto("/composer/");
  await page.getByRole("button", { name: "Menu" }).click();
  await page.getByRole("menuitem", { name: "Components" }).click();

  await page.getByPlaceholder("com.vendor.part.model").fill(testId);
  await page.getByLabel("New component kind").selectOption("sensor");

  // The file input is deliberately hidden (browse via the button instead)
  // -- setInputFiles still targets it directly, same as a real file
  // picker would populate it.
  await page.locator(".components-list__file-input").setInputFiles(pdfPath);
  await expect(page.locator(".components-list__staged-files li")).toContainText(path.basename(pdfPath));

  // The button label itself reflects that a file is staged.
  const createButton = page.getByRole("button", { name: /New draft/ });
  await expect(createButton).toHaveText("New draft & transcribe");
  await createButton.click();

  await expect(page.locator("h1", { hasText: testId })).toBeVisible();

  // Chat auto-fires a transcription request -- no manual send needed --
  // and (since this test doesn't mock /agent/chat) the real backend
  // degrades cleanly to AGENT_UNAVAILABLE with no key configured, proving
  // the request genuinely reached the server rather than silently no-op-ing.
  await expect(page.locator(".chat-turn--user")).toContainText("I've attached a datasheet");
  await expect(page.locator(".chat-panel__transcript")).toContainText("ANTHROPIC_API_KEY");

  // And the file itself is genuinely stored under the NEW draft's own
  // attachments directory, reachable via the real download route.
  const listRes = await fetch(`${BACKEND}/components/${encodeURIComponent(testId)}/attachments`);
  const files = (await listRes.json()).files as Array<{ filename: string; kind: string }>;
  expect(files).toHaveLength(1);
  expect(files[0].kind).toBe("pdf");

  fs.rmSync(pdfPath, { force: true });
});

test("deleting a component removes it from the list and the workspace, after a confirm", async ({ page }) => {
  const testId = `com.example.delete-test-${Date.now()}`;

  await page.goto("/composer/");
  await page.getByRole("button", { name: "Menu" }).click();
  await page.getByRole("menuitem", { name: "Components" }).click();

  await page.getByPlaceholder("com.vendor.part.model").fill(testId);
  await page.getByLabel("New component kind").selectOption("sensor");
  await page.getByRole("button", { name: "New draft" }).click();
  await expect(page.locator("h1", { hasText: testId })).toBeVisible();

  // Dismissing the confirm must leave the component untouched.
  page.once("dialog", (dialog) => dialog.dismiss());
  await page.getByRole("button", { name: "Delete", exact: true }).click();
  await expect(page.locator("h1", { hasText: testId })).toBeVisible();

  // Accepting it actually deletes -- back to the empty-selection state,
  // and the row is gone from the list.
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Delete", exact: true }).click();
  await expect(page.getByText("Select a component, or create a new draft, to begin.")).toBeVisible();
  await expect(page.locator(".components-list__id", { hasText: testId })).toHaveCount(0);

  const describeRes = await fetch(`${BACKEND}/describe_component?id=${encodeURIComponent(testId)}`);
  const describeEnv = await describeRes.json();
  expect(describeEnv.ok).toBe(false);
});
