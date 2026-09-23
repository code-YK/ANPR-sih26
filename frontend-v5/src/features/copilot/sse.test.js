import { describe, expect, it } from "vitest";

import { createSseParser, navigationPath } from "./sse.js";

/**
 * A network chunk can split a frame anywhere, so the risk these cover is
 * the parser emitting half an event or dropping one at a boundary.
 */
describe("createSseParser", () => {
  it("parses a single complete frame", () => {
    const parser = createSseParser();
    expect(parser.push('data: {"type":"token","text":"hi"}\n\n')).toEqual([
      { type: "token", text: "hi" },
    ]);
  });

  it("parses several frames in one chunk", () => {
    const parser = createSseParser();
    const events = parser.push('data: {"type":"token","text":"a"}\n\ndata: {"type":"done"}\n\n');
    expect(events.map((e) => e.type)).toEqual(["token", "done"]);
  });

  it("buffers a frame split across chunks", () => {
    const parser = createSseParser();
    expect(parser.push('data: {"type":"tok')).toEqual([]);
    expect(parser.push('en","text":"split"}\n\n')).toEqual([
      { type: "token", text: "split" },
    ]);
  });

  it("buffers a frame split exactly at the blank-line separator", () => {
    const parser = createSseParser();
    expect(parser.push('data: {"type":"done"}\n')).toEqual([]);
    expect(parser.push("\n")).toEqual([{ type: "done" }]);
  });

  it("reassembles a stream delivered one character at a time", () => {
    const parser = createSseParser();
    const raw = 'data: {"type":"token","text":"abc"}\n\ndata: {"type":"done"}\n\n';
    const events = [];
    for (const char of raw) events.push(...parser.push(char));
    expect(events).toEqual([{ type: "token", text: "abc" }, { type: "done" }]);
  });

  it("skips a malformed frame without killing the stream", () => {
    const parser = createSseParser();
    const events = parser.push('data: {not json}\n\ndata: {"type":"done"}\n\n');
    expect(events).toEqual([{ type: "done" }]);
  });

  it("ignores comment and empty lines", () => {
    const parser = createSseParser();
    const events = parser.push(': keepalive\ndata: {"type":"done"}\n\n');
    expect(events).toEqual([{ type: "done" }]);
  });

  it("handles a payload containing a blank line inside a JSON string", () => {
    const parser = createSseParser();
    const events = parser.push('data: {"type":"token","text":"line1\\n\\nline2"}\n\n');
    expect(events[0].text).toBe("line1\n\nline2");
  });
});

describe("navigationPath", () => {
  it("accepts an absolute in-app path", () => {
    expect(navigationPath({ data: { path: "/journeys/GJ01AB1234" } })).toBe("/journeys/GJ01AB1234");
  });

  it.each([
    ["an external URL", { data: { path: "https://evil.example/steal" } }],
    ["a protocol-relative URL", { data: { path: "//evil.example" } }],
    ["a missing path", { data: {} }],
    ["a non-string path", { data: { path: 42 } }],
    ["a null result", null],
  ])("rejects %s", (_label, result) => {
    expect(navigationPath(result)).toBeNull();
  });
});
