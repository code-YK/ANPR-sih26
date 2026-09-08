import { useEffect } from "react";

// `field.labels` only populates when a <label> is associated by `for`/`id`
// or wraps the control. This app's forms mostly write `<label>Name</label>`
// as a plain sibling inside a `.field`, which associates nothing -- so the
// message would otherwise read "Please fill out this field" with no clue
// which of five fields is meant.
function labelFor(field) {
  const associated = field.labels?.[0]?.textContent;
  const sibling = associated ? null : field.closest(".field, .grant-row, .toolbar")?.querySelector("label");
  const text = associated ?? sibling?.textContent;
  return text ? text.trim().replace(/\s+/g, " ").replace(/[:*]$/, "") : "";
}

/**
 * Replaces the browser's native validation bubbles with themed feedback.
 *
 * Chrome/Safari/Firefox each draw their own light-mode popup on a failed
 * constraint (`required`, `type="email"`, `minLength`, …). On a near-black
 * console those arrive as a bright, differently-typeset box from another
 * design system entirely, and they vanish on the next click.
 *
 * `invalid` does not bubble, so this listens in the capture phase at the
 * document, which reaches every form in the app without any of them needing
 * to opt in. Calling preventDefault suppresses the native bubble only -- it
 * does not suppress the validation itself, so the form is still blocked from
 * submitting and the browser's own localised message is reused rather than
 * reinvented.
 *
 * The first invalid field is focused and marked; the message goes to the
 * existing toast, which is already themed and already how this app reports
 * everything else that went wrong.
 */
export function useFormValidationTheme(showToast) {
  useEffect(() => {
    let queued = null;

    function onInvalid(event) {
      const field = event.target;
      if (!(field instanceof HTMLElement)) return;
      event.preventDefault();
      field.setAttribute("aria-invalid", "true");
      field.classList.add("field-invalid");

      // A submit fires `invalid` once per failing field. Batch to the end of
      // the task so the *first* one wins focus and only one toast appears,
      // rather than one per field with the last stealing focus.
      if (queued) return;
      queued = setTimeout(() => {
        queued = null;
        field.focus({ preventScroll: false });
        const message = field.validationMessage || "Check this field and try again.";
        showToast(labelFor(field) ? `${labelFor(field)}: ${message}` : message);
      }, 0);
    }

    // Clear the mark as soon as the field becomes valid again, so the red
    // edge tracks reality instead of persisting until the next submit.
    function onInput(event) {
      const field = event.target;
      if (!(field instanceof HTMLElement) || !field.classList.contains("field-invalid")) return;
      if (typeof field.checkValidity === "function" && field.checkValidity()) {
        field.removeAttribute("aria-invalid");
        field.classList.remove("field-invalid");
      }
    }

    document.addEventListener("invalid", onInvalid, true);
    document.addEventListener("input", onInput, true);
    return () => {
      if (queued) clearTimeout(queued);
      document.removeEventListener("invalid", onInvalid, true);
      document.removeEventListener("input", onInput, true);
    };
  }, [showToast]);
}
