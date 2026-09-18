import { describe, expect, it } from "vitest";

import {
  GROUP_WINDOW_MS,
  MAX_ITEMS,
  SOUND_GAP_MS,
  addNotification,
  shouldPlaySound,
  soundFor,
  splitVisible,
} from "./rules.js";

const NOW = 1_000_000;

function sighting(id, cameraId = "cam11", plate = `GJ01AB${1000 + id}`) {
  return { kind: "sighting", key: `sighting:${id}`, cameraId, cameraName: cameraId, plate };
}

describe("addNotification", () => {
  it("appends newest last with a lifetime", () => {
    const items = addNotification([], sighting(1), NOW);
    expect(items).toHaveLength(1);
    expect(items[0]).toMatchObject({ kind: "sighting", createdAt: NOW, ttl: expect.any(Number) });
  });

  it("ignores a duplicate key", () => {
    let items = addNotification([], sighting(1), NOW);
    items = addNotification(items, sighting(1), NOW + 10);
    expect(items).toHaveLength(1);
  });

  it("groups a burst of sightings from one camera into a single card", () => {
    let items = addNotification([], sighting(1), NOW);
    items = addNotification(items, sighting(2), NOW + 500);
    items = addNotification(items, sighting(3), NOW + 900);
    expect(items).toHaveLength(1);
    expect(items[0]).toMatchObject({ kind: "sighting-group", count: 3 });
    expect(items[0].plates[0]).toBe("GJ01AB1003");
    expect(items[0].sightingKeys).toEqual(expect.arrayContaining(["sighting:1", "sighting:2", "sighting:3"]));
  });

  it("keeps growing an existing group", () => {
    let items = [];
    for (let i = 1; i <= 5; i += 1) items = addNotification(items, sighting(i), NOW + i * 100);
    expect(items).toHaveLength(1);
    expect(items[0].count).toBe(5);
  });

  it("does not group sightings from different cameras", () => {
    let items = addNotification([], sighting(1, "cam11"), NOW);
    items = addNotification(items, sighting(2, "cam12"), NOW + 100);
    items = addNotification(items, sighting(3, "cam13"), NOW + 200);
    expect(items.map((item) => item.kind)).toEqual(["sighting", "sighting", "sighting"]);
  });

  it("does not group sightings outside the window", () => {
    let items = addNotification([], sighting(1), NOW);
    items = addNotification(items, sighting(2), NOW + GROUP_WINDOW_MS + 1);
    items = addNotification(items, sighting(3), NOW + 2 * GROUP_WINDOW_MS + 2);
    expect(items).toHaveLength(3);
  });

  it("lets a watchlist alert replace the card for the sighting that raised it", () => {
    let items = addNotification([], sighting(7), NOW);
    items = addNotification(items, { kind: "watchlist", key: "alert:1", replaces: "sighting:7" }, NOW + 100);
    expect(items.map((item) => item.kind)).toEqual(["watchlist"]);
  });

  it("removes a replaced sighting from a group", () => {
    let items = [];
    for (let i = 1; i <= 3; i += 1) items = addNotification(items, sighting(i), NOW + i);
    items = addNotification(items, { kind: "watchlist", key: "alert:9", replaces: "sighting:2" }, NOW + 10);
    const group = items.find((item) => item.kind === "sighting-group");
    expect(group.count).toBe(2);
    expect(group.sightingKeys).not.toContain("sighting:2");
  });

  it("caps the retained history", () => {
    let items = [];
    for (let i = 0; i < MAX_ITEMS + 10; i += 1) {
      items = addNotification(items, { kind: "system", title: `n${i}` }, NOW + i * GROUP_WINDOW_MS);
    }
    expect(items).toHaveLength(MAX_ITEMS);
  });
});

describe("splitVisible", () => {
  it("shows the newest three and counts the rest", () => {
    const items = [1, 2, 3, 4, 5].map((n) => ({ id: n }));
    const { visible, overflow } = splitVisible(items);
    expect(visible.map((item) => item.id)).toEqual([3, 4, 5]);
    expect(overflow).toBe(2);
  });
});

describe("sound", () => {
  it("maps kinds to sounds", () => {
    expect(soundFor("watchlist")).toBe("alert");
    expect(soundFor("suspicious")).toBe("alert");
    expect(soundFor("sighting")).toBe("sighting");
    expect(soundFor("system")).toBeNull();
  });

  it("rate-limits each sound independently", () => {
    const last = { sighting: NOW };
    expect(shouldPlaySound("sighting", last, NOW + SOUND_GAP_MS.sighting - 1)).toBe(false);
    expect(shouldPlaySound("sighting", last, NOW + SOUND_GAP_MS.sighting)).toBe(true);
    expect(shouldPlaySound("alert", last, NOW + 1)).toBe(true);
  });
});
