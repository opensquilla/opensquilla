const assert = require("assert");
const { formatReportName } = require("../src/index.cjs");

assert.strictEqual(formatReportName("Router Eval Report.md"), "router-eval-report.md");
console.log("ok");
