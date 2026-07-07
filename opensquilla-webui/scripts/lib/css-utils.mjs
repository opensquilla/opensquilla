// Shared CSS/color parsing helpers for the guard scripts. Each of these used
// to exist as a per-script copy (with per-script gaps — e.g. one hex parser
// missing 4/8-digit forms, one token regex missing a block-final declaration
// without a trailing semicolon). Fix bugs here, once.

/** Strip CSS block comments. */
export function stripCssComments(css) {
  return css.replace(/\/\*[\s\S]*?\*\//g, '')
}

/** Strip HTML, CSS and JS line comments from a mixed html/ts/css source.
 *  Line comments keep the char before `//` and never eat `://` (URLs). */
export function stripAllComments(text) {
  return stripCssComments(
    text.replace(/<!--[\s\S]*?-->/g, ''),
  ).replace(/(^|[^:])\/\/[^\n]*/g, '$1')
}

/** #rgb / #rgba / #rrggbb / #rrggbbaa → [r, g, b] (alpha ignored). */
export function hexToRgb(hex) {
  let h = hex.replace('#', '')
  if (h.length === 3 || h.length === 4) h = h.split('').map((c) => c + c).join('')
  return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16))
}

/** Every custom-property definition in a css source, as Map(name → value).
 *  Names are bare (no leading `--`). Handles a block-final declaration with no
 *  trailing semicolon (values stop at `;` or `}`). Later definitions win, so
 *  feeding foundation.css then a theme's tokens.css yields the theme's view. */
export function parseTokenDefinitions(css, map = new Map()) {
  const re = /(?:^|[\s;{])--([\w-]+)\s*:\s*([^;{}]+)/g
  for (const m of stripCssComments(css).matchAll(re)) map.set(m[1], m[2].trim())
  return map
}
