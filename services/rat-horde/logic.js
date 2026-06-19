// Solo / client-only game — all simulation lives in the client (index.html + game.js).
// The platform still requires a root code module; this is the no-op rules stub.
export const meta = { game: "rat-horde", minPlayers: 1, maxPlayers: 1 };
export function setup() { return {}; }
export function validateAction() { return { ok: true }; }
export function applyAction(state) { return state; }
export function isGameOver() { return { over: false }; }
export function viewFor(state) { return state; }
