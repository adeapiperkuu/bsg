let generation = 0;

export function nextAuthGeneration(): number {
  return ++generation;
}

export function currentAuthGeneration(): number {
  return generation;
}

type SessionInvalidatedHandler = (generation: number) => void;

let handler: SessionInvalidatedHandler | null = null;

export function setSessionInvalidatedHandler(fn: SessionInvalidatedHandler | null) {
  handler = fn;
}

export function notifySessionInvalidated(generation: number) {
  handler?.(generation);
}
