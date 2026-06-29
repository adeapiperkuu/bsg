import { useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";

type Props = {
  text: string;
  className?: string;
  onComplete?: () => void;
  onProgress?: () => void;
};

function typingInterval(textLength: number) {
  if (textLength > 600) return 6;
  if (textLength > 250) return 10;
  return 14;
}

function typingStep(textLength: number) {
  if (textLength > 600) return 3;
  if (textLength > 250) return 2;
  return 1;
}

export function TypewriterText({ text, className, onComplete, onProgress }: Props) {
  const [displayed, setDisplayed] = useState("");
  const [done, setDone] = useState(false);
  const onCompleteRef = useRef(onComplete);
  const onProgressRef = useRef(onProgress);

  useEffect(() => {
    onCompleteRef.current = onComplete;
    onProgressRef.current = onProgress;
  }, [onComplete, onProgress]);

  useEffect(() => {
    if (!text) {
      setDisplayed("");
      setDone(true);
      onCompleteRef.current?.();
      return;
    }

    setDisplayed("");
    setDone(false);

    let index = 0;
    const step = typingStep(text.length);
    const intervalMs = typingInterval(text.length);

    const timer = window.setInterval(() => {
      index = Math.min(index + step, text.length);
      setDisplayed(text.slice(0, index));
      onProgressRef.current?.();

      if (index >= text.length) {
        window.clearInterval(timer);
        setDone(true);
        onCompleteRef.current?.();
      }
    }, intervalMs);

    return () => window.clearInterval(timer);
  }, [text]);

  return (
    <p className={cn("leading-5", className)}>
      {displayed}
      {!done && (
        <span
          className="ml-0.5 inline-block h-3.5 w-0.5 translate-y-px animate-pulse bg-current opacity-70"
          aria-hidden="true"
        />
      )}
    </p>
  );
}
