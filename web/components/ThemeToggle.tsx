"use client";

import { useEffect, useState } from "react";
import { Monitor, Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";

const OPTIONS = [
  { value: "light", label: "Light", icon: Sun },
  { value: "dark", label: "Dark", icon: Moon },
  { value: "system", label: "System", icon: Monitor },
] as const;

export function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);

  // Avoid rendering theme-dependent icon state before hydration -- the
  // resolved theme isn't known on the server, so anything but a neutral
  // placeholder here would mismatch and flash.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => setMounted(true), []);

  const current = OPTIONS.find((o) => o.value === theme) ?? OPTIONS[2];

  return (
    <div className="flex items-center gap-0.5 rounded-full border border-border bg-surface p-0.5">
      {OPTIONS.map((option) => {
        const Icon = option.icon;
        const active = mounted && current.value === option.value;
        return (
          <Tooltip key={option.value}>
            <TooltipTrigger
              render={
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label={`${option.label} theme`}
                  aria-pressed={active}
                  onClick={() => setTheme(option.value)}
                  className={
                    active
                      ? "rounded-full bg-background text-foreground shadow-sm"
                      : "rounded-full text-text-tertiary"
                  }
                >
                  <Icon className="size-3.5" />
                </Button>
              }
            />
            <TooltipContent>{option.label}</TooltipContent>
          </Tooltip>
        );
      })}
    </div>
  );
}
