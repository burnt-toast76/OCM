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

const BACKEND = `http://127.0.0.1:${process.env.OCM_TEST_BACKEND_PORT ?? "8000"}`;

test("create draft, chat sets a field (mocked SSE), then a direct field edit shrinks the checklist further", async ({ page }) => {
  const testId = `com.example.chat-test-${Date.now()}`;

  await page.goto("/composer/");
  await page.getByRole("button", { name: "Components" }).click();

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
