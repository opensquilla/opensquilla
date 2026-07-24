import { spawnSync } from "node:child_process";
import { readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";

const packageRoot = fileURLToPath(new URL("../", import.meta.url));
// Bun 1.3.14 can crash on Linux when these renderer-heavy files share a
// process with the full native OpenTUI suite. Keep the shared suite together
// for its theme state, but give the changed overlay files fresh processes.
const isolatedTestFiles = new Set([
  "src/approval-overlay.bun.test.mjs",
  "src/theme-picker.bun.test.mjs",
]);
const testFiles = readdirSync(new URL("../src/", import.meta.url), {
  withFileTypes: true,
})
  .filter((entry) => entry.isFile() && entry.name.endsWith(".bun.test.mjs"))
  .map((entry) => `src/${entry.name}`)
  .sort();

if (testFiles.length === 0) {
  throw new Error("No Bun test files found");
}
for (const isolatedTestFile of isolatedTestFiles) {
  if (!testFiles.includes(isolatedTestFile)) {
    throw new Error(`Missing isolated Bun test file: ${isolatedTestFile}`);
  }
}

const bunExecutable = process.platform === "win32" ? "bun.exe" : "bun";
const sharedTestFiles = testFiles.filter((testFile) => !isolatedTestFiles.has(testFile));
const testRuns = [
  {
    label: "shared Bun suite",
    args: ["test", ...sharedTestFiles],
  },
  ...[...isolatedTestFiles].map((testFile) => ({
    label: testFile,
    args: ["test", "--max-concurrency=1", testFile],
  })),
];

for (const testRun of testRuns) {
  console.log(`\n=== ${testRun.label} ===`);
  const result = spawnSync(
    bunExecutable,
    testRun.args,
    {
      cwd: packageRoot,
      stdio: "inherit",
    },
  );
  if (result.error) {
    throw result.error;
  }
  if (result.status !== 0) {
    process.exit(result.status ?? 1);
  }
}
