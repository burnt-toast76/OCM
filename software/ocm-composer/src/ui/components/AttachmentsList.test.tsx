// SPDX-License-Identifier: AGPL-3.0-or-later
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { AttachmentsList } from "./AttachmentsList";
import { useComponentsStore } from "../../store/componentsStore";

afterEach(cleanup);

beforeEach(() => {
  useComponentsStore.setState({ selectedComponentId: "com.example.test-part", attachments: [] });
});

describe("AttachmentsList", () => {
  it("renders nothing when no component is selected or nothing has ever been attached", () => {
    const { container } = render(<AttachmentsList />);
    expect(container).toBeEmptyDOMElement();
  });

  it("lists every previously uploaded file, not just ones staged this session, with a link to download/view it", () => {
    useComponentsStore.setState({
      attachments: [
        { filename: "cutsheet.pdf", kind: "pdf", glb: null },
        { filename: "body.step", kind: "step", glb: "body.glb" },
      ],
    });

    render(<AttachmentsList />);

    const pdfLink = screen.getByRole("link", { name: "cutsheet.pdf" });
    expect(pdfLink).toHaveAttribute("href", "/components/com.example.test-part/attachments/cutsheet.pdf");
    expect(pdfLink).toHaveAttribute("target", "_blank");

    const stepLink = screen.getByRole("link", { name: "body.step" });
    expect(stepLink).toHaveAttribute("href", "/components/com.example.test-part/attachments/body.step");

    expect(screen.getByText("PDF")).toBeInTheDocument();
    expect(screen.getByText("STEP")).toBeInTheDocument();
  });
});
