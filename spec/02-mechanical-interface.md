# OCM Spec — Mechanical Interface v1.0

## 🔴 NOT FROZEN — see [ADR-0011](../docs/decisions/0011-mount-grid.md)

**This is the one Step-0 decision still open, and everything hangs off it.**

The schema currently uses `ocm-base-grid-50` as a placeholder. The real question is strategic,
not technical:

- Define our own 50 mm grid, or
- Ride 8020/item's hole pattern (free adoption), or
- Ride the welding-table grid (Siegmund/Demmeler — and commodity ground plates already exist
  in that pattern, which is the part we planned to sell anyway)

**Decide this before writing any CAD.**

## Already settled

- Robot tool flange: **ISO 9409-1** (A50 / A63 / A80)
- Datum: the frame carries load; a ground plate carries precision ([ADR-0006](../docs/decisions/0006-separate-datum-from-load-path.md))
- Frame: bolted tab-and-slot, not welded ([ADR-0005](../docs/decisions/0005-bolted-not-welded-frame.md))
- Acceptance test: **robot mounting face deflects < 35 µm under 100 N lateral**
