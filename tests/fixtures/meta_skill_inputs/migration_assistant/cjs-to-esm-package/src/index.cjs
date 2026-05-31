const path = require("path");

function formatReportName(name) {
  return path.basename(name).replace(/\s+/g, "-").toLowerCase();
}

module.exports = {
  formatReportName,
};
