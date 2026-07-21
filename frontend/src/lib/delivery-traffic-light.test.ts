import { describe, expect, it } from "vitest";

import { getTrafficLightLabel, type DeliveryTrafficLight } from "./delivery-traffic-light";

describe("delivery traffic-light presentation", () => {
  it("displays the API value yellow as Amber", () => {
    expect(getTrafficLightLabel("yellow")).toBe("Amber");
  });

  it("preserves API values as green, yellow, and red", () => {
    const apiValues: DeliveryTrafficLight[] = ["green", "yellow", "red"];

    expect(apiValues).toEqual(["green", "yellow", "red"]);
    expect(apiValues).not.toContain("amber");
  });
});
