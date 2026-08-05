"use client";

import { useEffect, useRef } from "react";

/** Scrolls a container to the bottom whenever `dep` changes (a new turn, a
 * pending question appearing), unless the user has deliberately scrolled up
 * to read earlier history -- a chat that yanks you back down mid-read is
 * worse than one that doesn't auto-scroll at all. */
export function useAutoScroll<T>(dep: T) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const userScrolledUpRef = useRef(false);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const handleScroll = () => {
      const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
      userScrolledUpRef.current = distanceFromBottom > 80;
    };

    el.addEventListener("scroll", handleScroll, { passive: true });
    return () => el.removeEventListener("scroll", handleScroll);
  }, []);

  useEffect(() => {
    const el = containerRef.current;
    if (!el || userScrolledUpRef.current) return;
    el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, [dep]);

  return containerRef;
}
