import * as RadixTooltip from "@radix-ui/react-tooltip";
import { forwardRef, useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";

import { plateGroups } from "../lib/format.js";

function cx(...parts) {
  return parts.filter(Boolean).join(" ");
}

export { cx };

// ---------------------------------------------------------------------------
// Buttons
// ---------------------------------------------------------------------------
export const Button = forwardRef(function Button(
  { variant = "secondary", size, loading = false, icon, children, className, type = "button", disabled, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      className={cx("ui-btn", `ui-btn--${variant}`, size && `ui-btn--${size}`, className)}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...rest}
    >
      {loading ? <span className="ui-spinner" aria-hidden="true" /> : icon}
      {children}
    </button>
  );
});

export const IconButton = forwardRef(function IconButton(
  { label, size, children, className, type = "button", tooltip = true, ...rest },
  ref,
) {
  const button = (
    <button
      ref={ref}
      type={type}
      aria-label={label}
      className={cx("ui-icon-btn", size && `ui-icon-btn--${size}`, className)}
      {...rest}
    >
      {children}
    </button>
  );
  return tooltip ? <Tooltip content={label}>{button}</Tooltip> : button;
});

export function Spinner({ className }) {
  return <span className={cx("ui-spinner", className)} aria-hidden="true" />;
}

// ---------------------------------------------------------------------------
// Status
// ---------------------------------------------------------------------------
export function Badge({ tone, outline, icon, children, className, ...rest }) {
  return (
    <span className={cx("ui-badge", tone && `ui-badge--${tone}`, outline && "ui-badge--outline", className)} {...rest}>
      {icon}
      {children}
    </span>
  );
}

/** tone: live | pending | critical | signal | idle */
export function StatusDot({ tone = "idle", pulse = false, label, className }) {
  return (
    <span
      className={cx("ui-dot", `ui-dot--${tone}`, pulse && "ui-dot--pulse", className)}
      role={label ? "img" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
    />
  );
}

/**
 * The plate as a physical object. A tentative read (worker "?" suffix or an
 * explicit `tentative`) takes the dashed treatment and never looks confirmed.
 */
export function PlateChip({ plate, size, tentative, className, title }) {
  if (!plate) return <span className="faint">—</span>;
  const isTentative = tentative || String(plate).endsWith("?");
  const groups = plateGroups(plate);
  return (
    <span
      className={cx("ui-plate", size === "lg" && "ui-plate--lg", isTentative && "ui-plate--tentative", className)}
      title={title ?? (isTentative ? "Tentative read — not confirmed" : undefined)}
      aria-label={`Plate ${String(plate).replace("?", "")}${isTentative ? ", tentative" : ""}`}
    >
      <span className="ui-plate__strip" aria-hidden="true">IND</span>
      <span className="ui-plate__text" aria-hidden="true">
        {groups.map((group, index) => (
          <span key={index}>{group}</span>
        ))}
      </span>
    </span>
  );
}

// ---------------------------------------------------------------------------
// Tooltip
// ---------------------------------------------------------------------------
export function TooltipProvider({ children }) {
  return (
    <RadixTooltip.Provider delayDuration={350} skipDelayDuration={200}>
      {children}
    </RadixTooltip.Provider>
  );
}

export function Tooltip({ content, side = "top", children }) {
  if (!content) return children;
  return (
    <RadixTooltip.Root>
      <RadixTooltip.Trigger asChild>{children}</RadixTooltip.Trigger>
      <RadixTooltip.Portal>
        <RadixTooltip.Content className="ui-tooltip" side={side} sideOffset={6} collisionPadding={8}>
          {content}
        </RadixTooltip.Content>
      </RadixTooltip.Portal>
    </RadixTooltip.Root>
  );
}

// ---------------------------------------------------------------------------
// Segmented control. The selected state is a CSS transition on the item
// itself: a shared-layout "sliding thumb" makes the animation library
// re-measure the whole page whenever a control re-renders, which on live
// screens is every poll.
// ---------------------------------------------------------------------------
export function Segmented({ value, onChange, options, size, label, className }) {
  return (
    <div className={cx("ui-segmented", size && `ui-segmented--${size}`, className)} role="tablist" aria-label={label}>
      {options.map((option) => {
        const selected = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            role="tab"
            aria-selected={selected}
            className="ui-segmented__item"
            onClick={() => onChange(option.value)}
            title={option.title}
          >
            <span className="ui-segmented__label">
              {option.icon}
              {option.label}
            </span>
          </button>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Dialog: native <dialog> for focus trap, Esc and a real backdrop.
// ---------------------------------------------------------------------------
export function Dialog({ open, onClose, title, description, children, footer, wide = false, busy = false }) {
  const ref = useRef(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return undefined;
    const handleCancel = (event) => {
      event.preventDefault();
      if (!busy) onCloseRef.current?.();
    };
    dialog.addEventListener("cancel", handleCancel);
    return () => dialog.removeEventListener("cancel", handleCancel);
  }, [busy]);

  return createPortal(
    <dialog
      ref={ref}
      className={cx("ui-dialog", wide && "ui-dialog--wide")}
      aria-labelledby={title ? "dialog-title" : undefined}
      onMouseDown={(event) => {
        if (event.target === ref.current && !busy) onCloseRef.current?.();
      }}
    >
      {open && (
        <div className="ui-dialog__inner">
          {title && (
            <header className="ui-dialog__header">
              <div>
                <h2 id="dialog-title">{title}</h2>
                {description && <p>{description}</p>}
              </div>
              <IconButton label="Close" size="sm" onClick={() => onCloseRef.current?.()} disabled={busy} tooltip={false}>
                <X />
              </IconButton>
            </header>
          )}
          <div className="ui-dialog__body">{children}</div>
          {footer && <footer className="ui-dialog__footer">{footer}</footer>}
        </div>
      )}
    </dialog>,
    document.body,
  );
}

// ---------------------------------------------------------------------------
// Fields
// ---------------------------------------------------------------------------
export function Field({ label, hint, error, children, className, htmlFor }) {
  return (
    <div className={cx("ui-field", className)}>
      {label && (
        <label className="ui-field__label" htmlFor={htmlFor}>
          {label}
        </label>
      )}
      {children}
      {error ? <span className="ui-field__error">{error}</span> : hint ? <span className="ui-field__hint">{hint}</span> : null}
    </div>
  );
}

export const Input = forwardRef(function Input({ className, size, ...rest }, ref) {
  return <input ref={ref} className={cx("ui-input", size === "sm" && "ui-input--sm", className)} {...rest} />;
});

export const Select = forwardRef(function Select({ className, size, children, ...rest }, ref) {
  return (
    <select ref={ref} className={cx("ui-select", size === "sm" && "ui-select--sm", className)} {...rest}>
      {children}
    </select>
  );
});

export const Textarea = forwardRef(function Textarea({ className, ...rest }, ref) {
  return <textarea ref={ref} className={cx("ui-textarea", className)} {...rest} />;
});

export function Checkbox({ label, className, ...rest }) {
  return (
    <label className={cx("ui-check", className)}>
      <input type="checkbox" {...rest} />
      {label}
    </label>
  );
}

export function Switch({ label, ...rest }) {
  return (
    <label className="ui-switch" aria-label={label}>
      <input type="checkbox" role="switch" {...rest} />
      <span />
    </label>
  );
}

// ---------------------------------------------------------------------------
// Empty and loading states
// ---------------------------------------------------------------------------
export function EmptyState({ icon, title, children, action, compact = false }) {
  return (
    <div className={cx("ui-empty", compact && "ui-empty--compact")}>
      {icon && <div className="ui-empty__icon">{icon}</div>}
      {title && <h3>{title}</h3>}
      {children && <p>{children}</p>}
      {action}
    </div>
  );
}

export function Skeleton({ width, height = 16, radius, className, style }) {
  return (
    <span
      className={cx("ui-skeleton", className)}
      style={{ display: "block", width, height, borderRadius: radius, ...style }}
      aria-hidden="true"
    />
  );
}

export function Notice({ tone, icon, children, className }) {
  return (
    <div className={cx("ui-notice", tone && `ui-notice--${tone}`, className)} role={tone === "critical" ? "alert" : undefined}>
      {icon}
      <div>{children}</div>
    </div>
  );
}

export function Meter({ value, max }) {
  const pct = max > 0 ? Math.min(100, (value / max) * 100) : 0;
  return (
    <div className={cx("ui-meter", max > 0 && value >= max && "ui-meter--full")} role="meter" aria-valuenow={value} aria-valuemin={0} aria-valuemax={max}>
      <span className="ui-meter__fill" style={{ width: `${pct}%` }} />
    </div>
  );
}
