export type DeliveryTrafficLight = "green" | "yellow" | "red";

const DELIVERY_TRAFFIC_LIGHT_LABELS: Record<DeliveryTrafficLight, "Green" | "Amber" | "Red"> = {
  green: "Green",
  yellow: "Amber",
  red: "Red",
};

/** Convert the stable API value into client-facing presentation copy. */
export function getTrafficLightLabel(value: DeliveryTrafficLight): "Green" | "Amber" | "Red" {
  return DELIVERY_TRAFFIC_LIGHT_LABELS[value];
}
