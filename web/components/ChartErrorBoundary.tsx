"use client";

import { Component, type ReactNode } from "react";

/** A malformed spec (an encoding field the backend's charts.py changes
 * shape on, a vega-embed parse error) degrades to a fallback rather than
 * blanking the whole answer card -- charts are enhancement, not the
 * primary content. */
export class ChartErrorBoundary extends Component<
  { children: ReactNode; fallback: ReactNode },
  { hasError: boolean }
> {
  override state = { hasError: false };

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  override render() {
    return this.state.hasError ? this.props.fallback : this.props.children;
  }
}
