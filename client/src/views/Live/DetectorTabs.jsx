import { useEffect, useRef, useState } from "react";
import { Check, ChevronDown } from "lucide-react";

import StatusDot from "../../components/StatusDot.jsx";
import { ANPR_MODELS, TABS, modeForTab } from "./detectorLegend.js";

/**
 * Which detector the view is showing, and for ANPR, which checkpoint runs it.
 *
 * ANPR is one tab, not two, because an operator thinks "read the plates on this
 * camera" -- the choice between the fine-tuned veh5 checkpoint and the stock
 * baseline is a property of that one job, and only one of them can run per
 * camera anyway. So the model lives in a menu on the tab rather than as a
 * second tab that looks like a second capability.
 *
 * The menu opens three ways: the caret, a double-click on the tab (as asked
 * for), and ArrowDown or Alt+ArrowDown with the tab focused. A double-click is
 * neither discoverable nor keyboard-reachable on its own, so it is one
 * affordance of three, never the only one.
 *
 * A dot appears on a tab only once that mode has a worker: idle tabs stay
 * plain, so the dots read as "these are running" rather than decoration.
 */
export default function DetectorTabs({
  activeTab,
  anprMode,
  states,
  onSelectTab,
  onSelectModel,
  modelDisabledReason,
}) {
  const [menuOpen, setMenuOpen] = useState(false);
  const rootRef = useRef(null);
  const anprTabRef = useRef(null);
  const menuRef = useRef(null);

  useEffect(() => {
    if (!menuOpen) return undefined;
    function onDown(event) {
      if (!rootRef.current?.contains(event.target)) setMenuOpen(false);
    }
    function onKey(event) {
      if (event.key === "Escape") {
        event.stopPropagation(); // Esc closes the menu, not the layout
        setMenuOpen(false);
        anprTabRef.current?.focus();
      }
    }
    document.addEventListener("pointerdown", onDown, true);
    document.addEventListener("keydown", onKey, true);
    const first = menuRef.current?.querySelector('[role="menuitemradio"]');
    first?.focus();
    return () => {
      document.removeEventListener("pointerdown", onDown, true);
      document.removeEventListener("keydown", onKey, true);
    };
  }, [menuOpen]);

  function pickModel(mode) {
    setMenuOpen(false);
    anprTabRef.current?.focus();
    onSelectModel(mode);
  }

  return (
    <div className="detector-tabs" ref={rootRef} role="tablist" aria-label="Detector modes">
      {TABS.map((tab) => {
        const mode = modeForTab(tab.id, anprMode);
        const state = states?.[mode];
        const on = state && ["running", "starting", "queued"].includes(state);
        const selected = activeTab === tab.id;
        const isAnpr = tab.id === "anpr";
        return (
          <span key={tab.id} className="detector-tab-group" data-anpr={isAnpr || undefined}>
            <button
              type="button"
              role="tab"
              ref={isAnpr ? anprTabRef : undefined}
              aria-selected={selected}
              className={`detector-tab${selected ? " is-active" : ""}`}
              onClick={() => onSelectTab(tab.id)}
              onDoubleClick={isAnpr ? () => setMenuOpen((open) => !open) : undefined}
              onKeyDown={
                isAnpr
                  ? (event) => {
                      if (event.key === "ArrowDown") {
                        event.preventDefault();
                        setMenuOpen(true);
                      }
                    }
                  : undefined
              }
              title={
                isAnpr
                  ? "Number plate recognition. Double-click, or use the caret, to choose the model."
                  : undefined
              }
            >
              {on && <StatusDot state={state} title={state} />}
              {tab.label}
              {isAnpr && (
                <span className="detector-tab-model">
                  {ANPR_MODELS.find((model) => model.mode === anprMode)?.label ?? anprMode}
                </span>
              )}
            </button>

            {isAnpr && (
              <>
                <button
                  type="button"
                  className={`detector-tab-caret${menuOpen ? " is-open" : ""}`}
                  aria-haspopup="menu"
                  aria-expanded={menuOpen}
                  aria-label="Choose ANPR model"
                  onClick={() => setMenuOpen((open) => !open)}
                >
                  <ChevronDown size={14} strokeWidth={2.25} />
                </button>

                {menuOpen && (
                  <div className="detector-model-menu" role="menu" aria-label="ANPR model" ref={menuRef}>
                    <p className="detector-model-menu-head">
                      ANPR model
                      <span>one per camera — starting one stops the other</span>
                    </p>
                    {ANPR_MODELS.map((model) => {
                      const modelState = states?.[model.mode];
                      const modelOn =
                        modelState && ["running", "starting", "queued"].includes(modelState);
                      const chosen = model.mode === anprMode;
                      return (
                        <button
                          key={model.mode}
                          type="button"
                          role="menuitemradio"
                          aria-checked={chosen}
                          className="detector-model-item"
                          disabled={Boolean(modelDisabledReason)}
                          title={modelDisabledReason ?? undefined}
                          onClick={() => pickModel(model.mode)}
                        >
                          <span className="detector-model-check" aria-hidden="true">
                            {chosen && <Check size={13} strokeWidth={2.5} />}
                          </span>
                          <span className="detector-model-body">
                            <span className="detector-model-label">
                              {model.label}
                              {model.isDefault && <em>default</em>}
                            </span>
                            <span className="detector-model-detail">{model.detail}</span>
                          </span>
                          {modelOn && <StatusDot state={modelState} title={modelState} />}
                        </button>
                      );
                    })}
                    {modelDisabledReason && (
                      <p className="detector-model-menu-note">{modelDisabledReason}</p>
                    )}
                  </div>
                )}
              </>
            )}
          </span>
        );
      })}
    </div>
  );
}
