# Крысиная орда (Rat Horde)

A top-down 3D rogue-like horde shooter — built as a single self-contained
WebGL game (Three.js, no build step). Survive escalating waves of bipedal
rats, grab an upgrade between waves, see how far you get.

Live build deployed to the Higgsfield marketplace.

## Deployment

- **Play:** https://glowing-pine-894.higgsfield.gg/
- Higgsfield `game_id`: `2b444410-2e00-4417-b483-baf034ee5c43`
  (pass this back to `deploy_game` to update the live game in place).
- Card art for the listing lives in `dist/` (`thumb.png` 16:9, `favicon.png` 1:1).


## Play

- **Move** — WASD / arrows (or left stick / left-screen touch)
- **Aim** — mouse (or right stick / right-screen touch)
- **Fire** — hold LMB / Space (auto-fires while aiming on stick/touch)
- Clear a wave → pick one of three upgrades → repeat. Permadeath.

Add `?dev=1` to the URL for an FPS / entity overlay.

## Tech

- `index.html` — page shell, HUD, menu / upgrade / game-over screens
- `game.js` — full simulation: fixed-timestep loop, seeded RNG, instanced
  rendering (the whole rat swarm draws in a handful of draw calls),
  pooled bullets / particles / score popups, twin-stick + gamepad input
- `strings.js` — all player-visible text (localization-ready)
- `logic.js` — solo rules stub required by the platform
- `vendor/three.module.min.js` — pinned Three.js r160

## Style

Neon-noir low-poly: flat-faceted meshes on a dark steel-blue arena, one
hot accent (toxic-green muzzle / score VFX) against cool steel-blue, glowing
red rat eyes, retro-arcade UI.
