import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

if (!HTMLElement.prototype.scrollTo) {
  HTMLElement.prototype.scrollTo = vi.fn();
}

afterEach(() => {
  cleanup();
});
