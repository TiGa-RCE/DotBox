# DotBox

Play DOS games with Dot using an independent DOSBox-X session framework.
The original graphical game remains authoritative.

This development cut extracts the working transport, input validation, screenshot
handling and immutable learned controls from fDisBull. It does not import or
require an installed fDisBull package, analysis database, disassembler or proof
engine. A compatible DOSBox-X native build is a separate explicit runtime input.

Start with [standalone installation](docs/STANDALONE.md), the
[native source/build recipe](docs/STANDALONE_NATIVE.md), and
[persistent controls](docs/PERSISTENT_CONTROLS.md).

The first milestone is the engine and its ownership boundary: one guest survives
client calls, frames can be observed, and stale agent input is refused after
explicit human handoff in diagnostic mode. Normal input stays on the desktop
harness path, with direct agent input RPCs disabled. Codex's **Take over / Return control** buttons belong to
the outer WebRTC harness. The optional [ownership bridge](docs/OWNERSHIP_BRIDGE.md)
uses fresh viewer observations to coordinate cooperating agent turns. Native
ownership stays separate. A coordination-only receiver can run without an
emulator. The real viewer-to-local-receiver path is verified; delivery to Dot's
headless environment remains unqualified. The saved operations environment now
starts; its current private TCP connection times out before SSH authentication.

Additional AGI readers, walking, game-specific routes and HUD experiments remain
preserved in the original development checkout. They are deferred from this
standalone cut. Audio transport is also deferred. There is no published release
or qualified Dot cloud installation yet.

[Verification](docs/evidence/standalone-engine-2026-11-16.json) · [Extraction boundary](docs/EXTRACTION.md) · [Product brief](docs/PRODUCT.md) · [Repositories](docs/REPOSITORIES.md)

See the [Codex viewer code investigation](docs/CODEX_VIEWER_CODE_ANALYSIS.md) for
ownership signals, actual-source offline checks, live viewer results and remaining
bridge boundaries. Audio and game work remain deferred.
