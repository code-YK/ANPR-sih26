import { useCallback, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { API } from "../../lib/api/client.js";
import { useUiStore } from "../../lib/uiStore.js";
import { createSseParser, navigationPath } from "./sse.js";

/**
 * Drives one conversation against POST /api/copilot/chat.
 *
 * The transcript lives in the UI store (deliberately not persisted), and is
 * replayed to the server on every request -- the backend keeps no session
 * state, so the conversation genuinely ends with the page load.
 */
export function useCopilotStream() {
  const navigate = useNavigate();
  const turns = useUiStore((state) => state.copilotTurns);
  const appendTurn = useUiStore((state) => state.appendCopilotTurn);
  const updateLastTurn = useUiStore((state) => state.updateLastCopilotTurn);

  const [busy, setBusy] = useState(false);
  const [activeTool, setActiveTool] = useState(null);
  const abortRef = useRef(null);

  const cancel = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setBusy(false);
    setActiveTool(null);
  }, []);

  const send = useCallback(
    async (message) => {
      const text = message.trim();
      if (!text || busy) return;

      const history = useUiStore
        .getState()
        .copilotTurns.filter((turn) => turn.content)
        // The server caps this too; trimming here keeps request size and
        // time-to-first-token down on a long conversation.
        .slice(-20)
        .map((turn) => ({ role: turn.role, content: turn.content }));

      appendTurn({ role: "user", content: text });
      appendTurn({ role: "assistant", content: "", toolResults: [], pending: true });
      setBusy(true);

      const controller = new AbortController();
      abortRef.current = controller;

      try {
        const response = await fetch(`${API}/copilot/chat`, {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message: text, transcript: history }),
          signal: controller.signal,
        });

        if (!response.ok) {
          let detail = `Request failed (${response.status})`;
          try {
            detail = (await response.json())?.detail ?? detail;
          } catch {
            // non-JSON error body
          }
          updateLastTurn({ error: detail, pending: false });
          return;
        }

        const parser = createSseParser();
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let answer = "";
        const toolResults = [];

        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          for (const event of parser.push(decoder.decode(value, { stream: true }))) {
            if (event.type === "token") {
              answer += event.text;
              updateLastTurn({ content: answer, pending: true });
            } else if (event.type === "tool_start") {
              setActiveTool(event.tool);
            } else if (event.type === "tool_result") {
              setActiveTool(null);
              toolResults.push(event);
              updateLastTurn({ toolResults: [...toolResults] });
              // Navigation is applied as it arrives so the page is already
              // moving while the model is still writing its sentence.
              if (event.tool === "navigate_to" && event.result?.ok) {
                const path = navigationPath(event.result);
                if (path) navigate(path);
              }
            } else if (event.type === "error") {
              updateLastTurn({ error: event.message });
            }
          }
        }
        updateLastTurn({ pending: false });
      } catch (error) {
        if (error?.name !== "AbortError") {
          updateLastTurn({ error: "Lost connection to the assistant.", pending: false });
        }
      } finally {
        abortRef.current = null;
        setBusy(false);
        setActiveTool(null);
      }
    },
    [appendTurn, busy, navigate, updateLastTurn],
  );

  return { turns, send, cancel, busy, activeTool };
}
