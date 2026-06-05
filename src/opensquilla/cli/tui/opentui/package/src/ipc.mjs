import fs from "node:fs";
import readline from "node:readline";

export function createIpc({ fromFd, toFd }) {
  function send(message) { fs.writeSync(toFd, `${JSON.stringify(message)}\n`, "utf8"); }
  function start(onMessage, onClose) {
    const input = fs.createReadStream(null, { fd: fromFd, encoding: "utf8", autoClose: false });
    const lines = readline.createInterface({ input, crlfDelay: Infinity });
    lines.on("line", (line) => { if (line.trim()) { try { onMessage(JSON.parse(line)); } catch (e) { send({ type: "error", message: e instanceof Error ? e.message : String(e) }); } } });
    lines.on("close", onClose);
  }
  return { send, start };
}

// Build a dispatcher that routes block.* + turn.* + composer/router to handlers.
export function createDispatcher(h) {
  return (m) => {
    switch (m.type) {
      case "turn.begin": return h.turnBegin(m);
      case "turn.end": return h.turnEnd(m);
      case "turn.status": return h.turnStatus(m);
      case "composer.set": return h.composerSet(m);
      case "completion.context": return h.completionContext?.(m);
      case "completion.response": return h.completionResponse?.(m);
      case "router.update": return h.routerUpdate(m);
      case "block.begin": return h.blockBegin(m);
      case "block.append": return h.blockAppend(m);
      case "block.update": return h.blockUpdate(m);
      case "block.end": return h.blockEnd(m);
      case "prompt.echo": return h.promptEcho?.(m);
      case "model.text": return h.modelText?.(m);
      case "scrollback.write": return h.scrollback?.(m);
      case "shutdown": return h.shutdown(m);
      default: return h.unknown(m);
    }
  };
}
