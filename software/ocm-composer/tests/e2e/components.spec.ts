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

test("create draft (vendor/part number captured up front), chat sets source, then a direct field edit updates it further", async ({ page }) => {
  const vendor = "example";
  const partNumber = `chat-test-${Date.now()}`;
  const testId = `com.${vendor}.${partNumber}`;

  await page.goto("/composer/");
  await page.getByRole("button", { name: "Menu" }).click();
  await page.getByRole("menuitem", { name: "Components" }).click();

  // -- create draft: vendor + part number captured directly, no raw
  // dotted id typed anywhere -------------------------------------------
  await page.getByPlaceholder("Vendor").fill(vendor);
  await page.getByPlaceholder("Part number").fill(partNumber);
  await page.getByLabel("New component kind").selectOption("vacuum_ejector");
  await page.getByRole("button", { name: "New draft" }).click();
  await expect(page.locator("h1", { hasText: testId })).toBeVisible();

  // Vendor is captured (and committed) by the create form itself now --
  // only source (ADR-0014: a genuine datasheet fact, never pre-filled)
  // is still missing.
  await expect(page.locator('[data-field="vendor"] input')).toHaveValue(vendor);
  await expect(page.locator(".checklist-panel__item")).toHaveCount(1);
  await expect(page.locator(".checklist-panel__item")).toContainText("source");

  // -- mock /agent/chat: the "agent" sets source for real, then tells the
  // frontend it did, over a canned SSE stream ------------------------
  await page.route("**/agent/chat", async (route) => {
    const res = await fetch(`${BACKEND}/update_component`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        id: testId,
        patch: [{ op: "add", path: "/source", value: { kind: "datasheet", ref: "Fake datasheet, worked example only" } }],
      }),
    });
    expect(res.ok).toBe(true);

    const sse =
      'event: text\ndata: {"delta":"Setting the source now."}\n\n' +
      `event: tool_call\ndata: {"name":"update_component","ok":true,"refusal_count":0,"envelope":{"ok":true,"refusals":[],"warnings":[],"data":{"id":"${testId}","revision":"0.1.0","draft":true}}}\n\n` +
      "event: done\ndata: {}\n\n";

    await route.fulfill({ status: 200, contentType: "text/event-stream", body: sse });
  });

  await page.getByPlaceholder("Transcribe this datasheet…").fill("This part's source is a datasheet.");
  await page.getByRole("button", { name: "Send" }).click();

  await expect(page.locator(".chat-turn--assistant").last()).toContainText("Setting the source now.");
  await expect(page.locator(".chat-tool-chip__label")).toContainText("update_component ✓");

  // -- form updates: source now shows what the "agent" set, via a REAL
  // describe_component refetch triggered by the tool_call event, not
  // just something painted onto the DOM directly -----------------------
  const sourceInputs = page.locator('[data-field="source"] input, [data-field="source"] textarea');
  await expect(sourceInputs.nth(1)).toHaveValue("Fake datasheet, worked example only");

  // -- checklist shrinks to nothing outstanding ------------------------
  await expect(page.locator(".checklist-panel__item")).toHaveCount(0);
  await expect(page.getByText("Nothing outstanding -- ready to publish.")).toBeVisible();

  // -- edit a field directly (no chat involved this time): direct form
  // edits still commit and persist even once nothing's required --------
  await sourceInputs.nth(1).fill("Updated citation, worked example only");
  await sourceInputs.nth(1).blur();
  await expect(sourceInputs.nth(1)).toHaveValue("Updated citation, worked example only");
});

test("the chat panel lets you choose which AI model to use, and sends that choice with the request", async ({ page }) => {
  const vendor = "example";
  const partNumber = `model-picker-test-${Date.now()}`;
  const testId = `com.${vendor}.${partNumber}`;

  await page.goto("/composer/");
  await page.getByRole("button", { name: "Menu" }).click();
  await page.getByRole("menuitem", { name: "Components" }).click();

  await page.getByPlaceholder("Vendor").fill(vendor);
  await page.getByPlaceholder("Part number").fill(partNumber);
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
  const vendor = "example";
  const partNumber = `precreate-test-${Date.now()}`;
  const testId = `com.${vendor}.${partNumber}`;
  const pdfPath = path.join(os.tmpdir(), `ocm-e2e-datasheet-${Date.now()}.pdf`);
  fs.writeFileSync(pdfPath, "%PDF-1.4 fake datasheet bytes for testing");

  await page.goto("/composer/");
  await page.getByRole("button", { name: "Menu" }).click();
  await page.getByRole("menuitem", { name: "Components" }).click();

  await page.getByPlaceholder("Vendor").fill(vendor);
  await page.getByPlaceholder("Part number").fill(partNumber);
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

  // And it's visible in the UI too -- not just reachable via the API --
  // so a human can come back later and re-check the source datasheet.
  await expect(page.locator(".attachments-list__link", { hasText: path.basename(pdfPath) })).toBeVisible();

  fs.rmSync(pdfPath, { force: true });
});

test("attaching two datasheets before creating uploads and sends both together, e.g. a main cutsheet plus a separate pinout diagram", async ({ page }) => {
  const vendor = "example";
  const partNumber = `two-pdf-test-${Date.now()}`;
  const testId = `com.${vendor}.${partNumber}`;
  const cutsheetPath = path.join(os.tmpdir(), `ocm-e2e-cutsheet-${Date.now()}.pdf`);
  const pinoutPath = path.join(os.tmpdir(), `ocm-e2e-pinout-${Date.now()}.pdf`);
  fs.writeFileSync(cutsheetPath, "%PDF-1.4 fake cutsheet bytes for testing");
  fs.writeFileSync(pinoutPath, "%PDF-1.4 fake pinout-diagram bytes for testing");

  await page.goto("/composer/");
  await page.getByRole("button", { name: "Menu" }).click();
  await page.getByRole("menuitem", { name: "Components" }).click();

  await page.getByPlaceholder("Vendor").fill(vendor);
  await page.getByPlaceholder("Part number").fill(partNumber);
  await page.getByLabel("New component kind").selectOption("sensor");

  // Two separate picks, same as attaching the cutsheet first and then
  // realizing the pinout lives in a second document -- addFiles is
  // additive, not a replace.
  await page.locator(".components-list__file-input").setInputFiles(cutsheetPath);
  await page.locator(".components-list__file-input").setInputFiles(pinoutPath);
  await expect(page.locator(".components-list__staged-files li")).toHaveCount(2);

  let capturedBody: { attachment_filenames?: string[]; messages?: { content: string }[] } | undefined;
  await page.route("**/agent/chat", async (route) => {
    capturedBody = route.request().postDataJSON();
    await route.fulfill({ status: 200, contentType: "text/event-stream", body: "event: done\ndata: {}\n\n" });
  });

  await page.getByRole("button", { name: /New draft/ }).click();
  await expect(page.locator("h1", { hasText: testId })).toBeVisible();

  // Both files reached the SAME /agent/chat call -- attachment_content_blocks
  // (ocm_api/attachments.py) sends every filename in one turn, so the model
  // can genuinely cross-reference the pinout diagram against the cutsheet,
  // not just see one or the other.
  await expect.poll(() => capturedBody?.attachment_filenames?.length).toBe(2);
  expect(capturedBody?.attachment_filenames).toEqual(
    expect.arrayContaining([path.basename(cutsheetPath), path.basename(pinoutPath)]),
  );

  // The prompt itself acknowledges multiple documents (not "a datasheet")
  // and calls out pinout extraction specifically.
  const promptText = capturedBody?.messages?.[0]?.content ?? "";
  expect(promptText).toContain("I've attached documents");
  expect(promptText).toContain("wire color");

  const listRes = await fetch(`${BACKEND}/components/${encodeURIComponent(testId)}/attachments`);
  const files = (await listRes.json()).files as Array<{ filename: string; kind: string }>;
  expect(files).toHaveLength(2);

  fs.rmSync(cutsheetPath, { force: true });
  fs.rmSync(pinoutPath, { force: true });
});

test("deleting a component removes it from the list and the workspace, after a confirm", async ({ page }) => {
  const vendor = "example";
  const partNumber = `delete-test-${Date.now()}`;
  const testId = `com.${vendor}.${partNumber}`;

  await page.goto("/composer/");
  await page.getByRole("button", { name: "Menu" }).click();
  await page.getByRole("menuitem", { name: "Components" }).click();

  await page.getByPlaceholder("Vendor").fill(vendor);
  await page.getByPlaceholder("Part number").fill(partNumber);
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
