import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import Home from "../page";

describe("Home", () => {
  it("renders ExpertSeat heading", () => {
    render(<Home />);
    expect(screen.getByRole("heading", { name: /expertseat/i })).toBeDefined();
  });
  it("shows foundation development label", () => {
    render(<Home />);
    expect(screen.getByText(/foundation development/i)).toBeDefined();
  });
});
