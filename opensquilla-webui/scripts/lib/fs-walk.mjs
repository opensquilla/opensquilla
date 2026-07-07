import { readdirSync, statSync, existsSync } from 'node:fs'
import { join } from 'node:path'

// Shared recursive file walker for the guard scripts. Before this existed each
// guard carried its own copy with its own exclusion rules, and they drifted —
// use this one and pass what differs.

/**
 * Recursively collect files under `root` whose BASENAME matches `match`.
 * A missing root returns [] (some guards scan optional directories).
 *
 * @param {string} root
 * @param {RegExp} match      tested against the file's basename
 * @param {object} [opts]
 * @param {string[]} [opts.excludeDirs]  directory names pruned wholesale
 * @param {(name: string) => boolean} [opts.skipFile]  drop individual files by basename
 * @returns {string[]} absolute paths
 */
export function walkFiles(root, match, { excludeDirs = ['node_modules', 'dist'], skipFile } = {}) {
  const out = []
  if (!existsSync(root)) return out
  const visit = (path) => {
    if (statSync(path).isDirectory()) {
      for (const entry of readdirSync(path)) {
        if (excludeDirs.includes(entry)) continue
        visit(join(path, entry))
      }
      return
    }
    const name = path.slice(path.lastIndexOf('/') + 1)
    if (match.test(name) && !(skipFile && skipFile(name))) out.push(path)
  }
  visit(root)
  return out
}
