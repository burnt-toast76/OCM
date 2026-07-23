// SPDX-License-Identifier: AGPL-3.0-or-later
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { AttachmentsList } from "./AttachmentsList";

afterEach(cleanup);

const downloadUrl = (filename: string) => `/components/com.example.test-part/attachments/${filename}`;

describe("AttachmentsList", () => {
  it("renders nothing when nothing has ever been attached", () => {
    const { container } = render(<AttachmentsList attachments={[]} downloadUrl={downloadUrl} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("lists every previously uploaded file, not just ones staged this session, with a link to download/view it", () => {
    render(
      <AttachmentsList
        attachments={[
          { filename: "cutsheet.pdf", kind: "pdf", glb: null, glb_status: null, measured_envelope_mm: null },
          { filename: "body.step", kind: "step", glb: "body.glb", glb_status: "ready", measured_envelope_mm: [30, 40, 12] },
        ]}
        downloadUrl={downloadUrl}
      />,
    );

    const pdfLink = screen.getByRole("link", { name: "cutsheet.pdf" });
    expect(pdfLink).toHaveAttribute("href", "/components/com.example.test-part/attachments/cutsheet.pdf");
    expect(pdfLink).toHaveAttribute("target", "_blank");

    const stepLink = screen.getByRole("link", { name: "body.step" });
    expect(stepLink).toHaveAttribute("href", "/components/com.example.test-part/attachments/body.step");

    expect(screen.getByText("PDF")).toBeInTheDocument();
    expect(screen.getByText("STEP")).toBeInTheDocument();
  });

  it("shows a converting indicator for a STEP file whose geometry conversion hasn't finished yet, and a failure indicator if it errored", () => {
    render(
      <AttachmentsList
        attachments={[
          { filename: "pending.step", kind: "step", glb: null, glb_status: "pending", measured_envelope_mm: null },
          { filename: "broken.step", kind: "step", glb: null, glb_status: "failed", measured_envelope_mm: null },
        ]}
        downloadUrl={downloadUrl}
      />,
    );

    expect(screen.getByText("Converting geometry…")).toBeInTheDocument();
    expect(screen.getByText("Conversion failed")).toBeInTheDocument();
  });
});
