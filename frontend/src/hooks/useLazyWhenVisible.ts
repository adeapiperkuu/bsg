import { useEffect, useRef, useState } from "react";

type Options = {
  rootMargin?: string;
  once?: boolean;
};

export function useLazyWhenVisible(options: Options = {}) {
  const { rootMargin = "120px", once = true } = options;
  const ref = useRef<HTMLDivElement | null>(null);
  const [isVisible, setIsVisible] = useState(false);

  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    if (isVisible && once) return;

    const margin = Number.parseInt(rootMargin, 10) || 0;
    const markVisible = () => setIsVisible(true);

    const isInViewport = () => {
      const rect = node.getBoundingClientRect();
      return rect.top < window.innerHeight + margin && rect.bottom > -margin;
    };

    if (isInViewport()) {
      markVisible();
      if (once) return;
    }

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          markVisible();
          if (once) observer.disconnect();
        }
      },
      { rootMargin },
    );

    observer.observe(node);

    const raf = window.requestAnimationFrame(() => {
      if (isInViewport()) markVisible();
    });

    return () => {
      window.cancelAnimationFrame(raf);
      observer.disconnect();
    };
  }, [isVisible, once, rootMargin]);

  return { ref, isVisible };
}
