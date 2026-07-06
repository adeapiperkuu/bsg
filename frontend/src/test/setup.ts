import "@testing-library/jest-dom/vitest";
import { vi } from "vitest";

if (!HTMLElement.prototype.scrollTo) {
  HTMLElement.prototype.scrollTo = vi.fn();
}
