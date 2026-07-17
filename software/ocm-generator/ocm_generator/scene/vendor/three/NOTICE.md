# Third-party notice — vendored three.js

This directory vendors, unmodified, three files from the three.js project:

- **Source:** https://github.com/mrdoob/three.js (distributed via unpkg.com)
- **Version:** r160 (`three@0.160.0`) — matches the CDN version the plain
  (non-animated) debug viewer (`../../viewer.py`) still loads via an
  import map, so both viewers render against the same three.js release.
- **License:** MIT (see `LICENSE` in this directory, copied unmodified)
- **Copyright:** © 2010-2023 Three.js Authors

Files:
- `three.module.min.js` — the core library's minified ES module build
  (`build/three.module.min.js`).
- `OrbitControls.js` — `examples/jsm/controls/OrbitControls.js`, unminified
  (the addons aren't published as separate minified builds).
- `CSS2DRenderer.js` — `examples/jsm/renderers/CSS2DRenderer.js`.

## Why vendored here, and not loaded from a CDN

`ocm_generator.scene.animation`'s `--view-animation` output is meant to be
a genuinely self-contained artifact -- openable and re-openable with no
network access at all, unlike the plain `--view` debug viewer (unchanged,
still CDN-based). These three files are read at HTML-generation time and
embedded as `data:` URIs in the generated page's own `<script
type="importmap">`, so the emitted HTML has no runtime dependency on
unpkg.com or any other external host. See `animation.py`'s own module
docstring for how.

## Updating

Re-download the same three files from a newer `three@x.y.z` release (they
have no build step -- copy straight from `unpkg.com/three@x.y.z/...`), and
update the version note above. `OrbitControls.js`/`CSS2DRenderer.js` both
import from the bare specifier `'three'`, resolved via the generated
page's own import map -- not a relative path -- so no import rewriting is
needed when updating.
