"use client";

import { VegaEmbed } from "react-vega";
import type { VisualizationSpec } from "vega-embed";

/** Split into its own module so next/dynamic's ssr:false import boundary
 * (in ChartBlock.tsx) covers exactly the ~500KB Vega dependency, not any
 * of ChartBlock's own lighter-weight logic.
 *
 * react-vega 8's public API is `VegaEmbed`/`useVegaEmbed` (a thin wrapper
 * around vega-embed), not the older per-mark `VegaLite` class component --
 * verified against the installed package, not assumed from memory. */
export default function VegaChart({ spec }: { spec: VisualizationSpec }) {
  return (
    <VegaEmbed
      spec={spec}
      options={{ actions: false, renderer: "svg" }}
      className="[&_.vega-embed]:w-full [&_canvas]:w-full [&_svg]:w-full"
    />
  );
}
