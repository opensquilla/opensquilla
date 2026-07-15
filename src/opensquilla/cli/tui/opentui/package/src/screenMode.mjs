export const ALTERNATE_SCREEN = "alternate-screen";
// The production host owns one terminal lifecycle: a full-screen alternate
// buffer with mouse interaction. Keep this option factory centralized so
// construction and handshake tests assert the same fixed product contract.
export function rendererOptions() {
  return {
    screenMode: ALTERNATE_SCREEN,
    useMouse: true,
  };
}

export function assertRendererScreenMode(renderer) {
  if (renderer?.screenMode !== ALTERNATE_SCREEN) {
    throw new Error(
      `OpenTUI screen mode mismatch: expected=${ALTERNATE_SCREEN} actual=${renderer?.screenMode ?? "unknown"}`,
    );
  }
}

export function rendererLayoutHeight(renderer) {
  return Math.max(1, Number(renderer?.height ?? renderer?.terminalHeight) || 1);
}
