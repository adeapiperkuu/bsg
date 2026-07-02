import { useCallback, useEffect, useState } from "react";

type Options = {
  rootMargin?: string;
  once?: boolean;
};

export function useLazyWhenVisible(options: Options = {}) {
  const { rootMargin = "120px", once = true } = options;
  const [node, setNode] = useState<HTMLDivElement | null>(null);
  const [isVisible, setIsVisible] = useState(false);

  const ref = useCallback((element: HTMLDivElement | null) => {
    setNode(element);
  }, []);

  useEffect(() => {
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
  }, [isVisible, node, once, rootMargin]);

  return { ref, isVisible };
}
