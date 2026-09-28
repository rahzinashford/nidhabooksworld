/**
 * As the shopper scrolls past the hero, the wooden shelf photo behind the
 * headline fades toward the background rather than hard-cutting away —
 * reinforcing the "stepping into the shop" feel.
 */
export function initHeroFade() {
  const hero = document.querySelector(".hero");
  const media = document.querySelector(".hero__media");
  if (!hero || !media) return;

  const prefersReducedMotion = window.matchMedia(
    "(prefers-reduced-motion: reduce)"
  ).matches;
  if (prefersReducedMotion) return;

  let ticking = false;

  const update = () => {
    const heroHeight = hero.offsetHeight || 1;
    const progress = Math.min(Math.max(window.scrollY / heroHeight, 0), 1);
    media.style.opacity = String(1 - progress * 0.85);
    media.style.transform = `translateY(${progress * 40}px) scale(${1 + progress * 0.04})`;
    ticking = false;
  };

  const onScroll = () => {
    if (ticking) return;
    ticking = true;
    window.requestAnimationFrame(update);
  };

  update();
  window.addEventListener("scroll", onScroll, { passive: true });
  window.addEventListener("resize", onScroll);
}
