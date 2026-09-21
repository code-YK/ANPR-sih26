import { useEffect, useRef } from "react";
import gsap from "gsap";

/**
 * Staggered GSAP reveal for children of a container.
 * Animates from invisible/offset to visible, with a stagger delay.
 *
 * @param {string} childSelector - CSS selector for children to animate
 * @param {object} opts
 * @param {number} opts.stagger - delay between each child (default 0.04)
 * @param {number} opts.duration - animation duration (default 0.5)
 * @param {number} opts.y - starting y offset (default 20)
 * @param {string} opts.ease - GSAP easing (default "power3.out")
 * @param {boolean} opts.scale - whether to animate scale (default false)
 * @param {Array} deps - dependency array to re-trigger animation
 */
export function useGsapReveal(childSelector, opts = {}, deps = []) {
  const containerRef = useRef(null);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const prefersReducedMotion = window.matchMedia(
      "(prefers-reduced-motion: reduce)"
    ).matches;
    if (prefersReducedMotion) return;

    const children = el.querySelectorAll(childSelector);
    if (!children.length) return;

    const {
      stagger = 0.04,
      duration = 0.5,
      y = 20,
      ease = "power3.out",
      scale = false,
    } = opts;

    const fromVars = { opacity: 0, y };
    if (scale) fromVars.scale = 0.95;

    gsap.set(children, fromVars);

    const tween = gsap.to(children, {
      opacity: 1,
      y: 0,
      scale: scale ? 1 : undefined,
      duration,
      stagger,
      ease,
      clearProps: "transform",
    });

    return () => tween.kill();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return containerRef;
}

/**
 * Single-element GSAP reveal (fade + slide up).
 * Good for panels, modals, focused players.
 */
export function useGsapFadeIn(opts = {}, deps = []) {
  const ref = useRef(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    const prefersReducedMotion = window.matchMedia(
      "(prefers-reduced-motion: reduce)"
    ).matches;
    if (prefersReducedMotion) return;

    const { duration = 0.45, y = 16, ease = "power2.out", scale = false } = opts;

    const fromVars = { opacity: 0, y };
    if (scale) fromVars.scale = 0.97;

    gsap.set(el, fromVars);
    const tween = gsap.to(el, {
      opacity: 1,
      y: 0,
      scale: scale ? 1 : undefined,
      duration,
      ease,
      clearProps: "transform",
    });

    return () => tween.kill();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return ref;
}
