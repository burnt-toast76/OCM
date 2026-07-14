# Measurements

**Publish the numbers.** Essentially nobody in open hardware does this, and it is enormously
credible.

## Wanted

| Measurement | Target | Status |
|---|---|---|
| Frame first natural frequency (modal hammer) | **> 60 Hz** | ⬜ |
| Robot mounting face deflection @ 100 N lateral | **< 35 µm** | ⬜ |
| Robot settling time after fast move-and-stop | < 100 ms | ⬜ |
| EtherCAT DC sync jitter, per drive | ≤ 2 µs | ⬜ |
| Gantry racking error vs. Y position (dual-drive X) | TBD | ⬜ |
| Achieved positional accuracy, C7 vs C5 screw | — | ⬜ |

## Why the frame test matters

The design criterion is **not "stout"** — it's first natural frequency. A soft base means the
arm rings after every fast move and you dwell before precision work. That dwell is cycle time,
every part, forever. Static deflection under process load is nearly a non-issue (screwdriving
at 2.4 N·m is nothing).

A $200 accelerometer and free FFT software gives you the first mode in an afternoon.

**And the mode shape tells you *which joint* is soft** — so you fix that one joint, rather
than welding the whole frame out of superstition.

Publish: the frame, its measured first mode, and **the procedure to verify yours.**
