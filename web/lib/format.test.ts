import { describe, expect, it } from "vitest";
import {
  confidenceLevel,
  formatCell,
  formatConfidence,
  formatMetricValue,
  humanizeMetricName,
} from "@/lib/format";

describe("formatMetricValue", () => {
  it("renders an em dash for null or undefined", () => {
    expect(formatMetricValue(null)).toBe("—");
    expect(formatMetricValue(undefined)).toBe("—");
  });

  it("passes non-numeric values through as strings", () => {
    expect(formatMetricValue("N/A")).toBe("N/A");
  });

  it("formats an integer with no decimals when there is no format hint", () => {
    expect(formatMetricValue(225)).toBe("225");
  });

  it("formats a non-integer with two decimals when there is no format hint", () => {
    expect(formatMetricValue(225.5)).toBe("225.5");
  });

  it("formats currency using the declared precision and currency code", () => {
    const out = formatMetricValue(1234.5, { type: "currency", precision: 2, currency: "USD" });
    expect(out).toBe("$1,234.50");
  });

  it("formats percent using the declared precision", () => {
    const out = formatMetricValue(0.3333, { type: "percent", precision: 1 });
    expect(out).toBe("33.3%");
  });

  it("formats a plain number using the declared precision", () => {
    const out = formatMetricValue(6, { type: "number", precision: 0 });
    expect(out).toBe("6");
  });
});

describe("confidenceLevel", () => {
  it("classifies >= 0.85 as high", () => {
    expect(confidenceLevel(0.85)).toBe("high");
    expect(confidenceLevel(1)).toBe("high");
  });

  it("classifies 0.6-0.849 as medium", () => {
    expect(confidenceLevel(0.6)).toBe("medium");
    expect(confidenceLevel(0.849)).toBe("medium");
  });

  it("classifies below 0.6 as low", () => {
    expect(confidenceLevel(0.59)).toBe("low");
    expect(confidenceLevel(0)).toBe("low");
  });
});

describe("formatConfidence", () => {
  it("renders as a rounded percent", () => {
    expect(formatConfidence(0.923)).toBe("92%");
  });
});

describe("formatCell", () => {
  it("renders an em dash for null or undefined", () => {
    expect(formatCell(null)).toBe("—");
    expect(formatCell(undefined)).toBe("—");
  });

  it("formats booleans as literal strings", () => {
    expect(formatCell(true)).toBe("true");
    expect(formatCell(false)).toBe("false");
  });

  it("formats numbers with the same integer/decimal rule as metric values", () => {
    expect(formatCell(3)).toBe("3");
    expect(formatCell(3.5)).toBe("3.5");
  });

  it("passes strings through unchanged", () => {
    expect(formatCell("US")).toBe("US");
  });
});

describe("humanizeMetricName", () => {
  it("title-cases a simple snake_case metric name", () => {
    expect(humanizeMetricName("gross_revenue")).toBe("Gross Revenue");
  });

  it("uses only the part after the last compiled join alias separator", () => {
    expect(humanizeMetricName("customers__country")).toBe("Country");
  });

  it("passes a single word through with just a capitalized first letter", () => {
    expect(humanizeMetricName("customers")).toBe("Customers");
  });
});
