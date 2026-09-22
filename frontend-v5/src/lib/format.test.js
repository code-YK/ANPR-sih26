import { describe, expect, it } from "vitest";

import { plateGroups } from "./format.js";

describe("plateGroups", () => {
  it("groups a standard plate as state, district, series, number", () => {
    expect(plateGroups("GJ01AB1234")).toEqual(["GJ", "01", "AB", "1234"]);
    expect(plateGroups("GJ21W3884")).toEqual(["GJ", "21", "W", "3884"]);
  });

  it("keeps Delhi's category letter with the district, as stamped", () => {
    expect(plateGroups("DL2CBB4791")).toEqual(["DL", "2CBB", "4791"]);
    expect(plateGroups("DL10CN7685")).toEqual(["DL", "10CN", "7685"]);
    expect(plateGroups("DL7CZ1908")).toEqual(["DL", "7CZ", "1908"]);
  });

  it("groups a Bharat-series plate", () => {
    expect(plateGroups("22BH1234AA")).toEqual(["22", "BH", "1234", "AA"]);
    expect(plateGroups("21bh0001a")).toEqual(["21", "BH", "0001", "A"]);
  });

  it("keeps the tentative marker on the last group", () => {
    expect(plateGroups("UP14FS3664?")).toEqual(["UP", "14", "FS", "3664?"]);
    expect(plateGroups("DL2CBB4791?")).toEqual(["DL", "2CBB", "4791?"]);
    expect(plateGroups("22BH1234AA?")).toEqual(["22", "BH", "1234", "AA?"]);
  });

  it("shows anything else exactly as read", () => {
    expect(plateGroups("KHODIYAR")).toEqual(["KHODIYAR"]);
    expect(plateGroups("gj 01-ab 1234")).toEqual(["GJ", "01", "AB", "1234"]);
    expect(plateGroups("")).toEqual([]);
    expect(plateGroups(null)).toEqual([]);
  });
});
