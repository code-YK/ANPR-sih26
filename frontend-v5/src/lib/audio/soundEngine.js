/**
 * Interface sounds, synthesised with Web Audio -- no files to load, nothing to
 * fail on an offline demo machine.
 *
 * Browsers keep an AudioContext suspended until the page has had a user
 * gesture. One shared context is created lazily and resumed on the first
 * pointer or key press anywhere (sign-in counts). A sound requested before
 * that is reported as blocked so the UI can say so, instead of failing
 * silently.
 */

let context = null;
let master = null;
const blockedListeners = new Set();

function ensureContext() {
  if (context) return context;
  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  if (!AudioContextClass) return null;
  context = new AudioContextClass({ latencyHint: "interactive" });
  const compressor = context.createDynamicsCompressor();
  compressor.threshold.value = -18;
  compressor.ratio.value = 6;
  master = context.createGain();
  master.gain.value = 0.9;
  master.connect(compressor).connect(context.destination);
  return context;
}

export function installAudioUnlock() {
  const unlock = () => {
    const ctx = ensureContext();
    if (!ctx) return;
    if (ctx.state === "suspended") ctx.resume().catch(() => {});
    if (ctx.state === "running") {
      setBlocked(false);
      window.removeEventListener("pointerdown", unlock, true);
      window.removeEventListener("keydown", unlock, true);
    }
  };
  window.addEventListener("pointerdown", unlock, true);
  window.addEventListener("keydown", unlock, true);
  return () => {
    window.removeEventListener("pointerdown", unlock, true);
    window.removeEventListener("keydown", unlock, true);
  };
}

function setBlocked(value) {
  for (const listener of blockedListeners) listener(value);
}

export function onAudioBlockedChange(listener) {
  blockedListeners.add(listener);
  return () => blockedListeners.delete(listener);
}

function tone(ctx, { frequency, start, duration, peak, type = "sine" }) {
  const osc = ctx.createOscillator();
  const gain = ctx.createGain();
  osc.type = type;
  osc.frequency.setValueAtTime(frequency, start);
  gain.gain.setValueAtTime(0.0001, start);
  gain.gain.exponentialRampToValueAtTime(peak, start + 0.012);
  gain.gain.exponentialRampToValueAtTime(0.0001, start + duration);
  osc.connect(gain).connect(master);
  osc.start(start);
  osc.stop(start + duration + 0.02);
}

const SOUNDS = {
  // Two soft rising notes: something was read, nothing is wrong.
  sighting(ctx, t) {
    tone(ctx, { frequency: 987.77, start: t, duration: 0.12, peak: 0.07, type: "triangle" });
    tone(ctx, { frequency: 1318.51, start: t + 0.085, duration: 0.2, peak: 0.06, type: "sine" });
  },
  // Three firmer notes, lower register: look at this now.
  alert(ctx, t) {
    const notes = [659.25, 880, 659.25];
    notes.forEach((frequency, index) => {
      const start = t + index * 0.14;
      tone(ctx, { frequency, start, duration: 0.16, peak: 0.13, type: "triangle" });
      tone(ctx, { frequency: frequency * 2, start, duration: 0.1, peak: 0.025, type: "sine" });
    });
  },
};

/** Returns true if the sound was scheduled. */
export function playSound(name) {
  const ctx = ensureContext();
  const sound = SOUNDS[name];
  if (!ctx || !sound) return false;
  if (ctx.state !== "running") {
    ctx.resume().catch(() => {});
    if (ctx.state !== "running") {
      setBlocked(true);
      return false;
    }
  }
  sound(ctx, ctx.currentTime + 0.01);
  return true;
}
