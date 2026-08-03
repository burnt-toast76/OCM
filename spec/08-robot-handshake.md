# OCM Spec — Robot ↔ Coordinator Handshake v1.0

**Status: FROZEN** (protocol semantics). Transport bindings are extensible.

## The problem this solves

The robot program and the cell coordinator execute in parallel and must synchronize at
process points: the robot must not descend to contact before the screw is fed; the
coordinator must not start the driver before the robot is holding still. The generated
URScript's `# TODO PLC handshake` comments are exactly these points.

## Design rule: no coordination wiring

The handshake runs over the network connection the robot already has. Discrete I/O is a
supported *alternate binding* (below), never a requirement. **Safety is excluded from this
spec entirely** — e-stop and STO stay hardwired per spec/06; no handshake message is ever a
safety function.

## The contract (transport-independent)

Four semantic signals. This is the whole ABI:

| Signal | Direction | Type | Meaning |
|---|---|---|---|
| `hs_at_step` | robot → coordinator | int | "I have arrived at step N and am holding position" |
| `hs_done_step` | coordinator → robot | int | "everything step N was waiting on is complete; proceed" |
| `hs_abort` | coordinator → robot | int | nonzero: halt motion where you are |
| `hs_heartbeat` | robot → coordinator | int | increments continuously while the program runs |

### Step-counter protocol

Steps are numbered monotonically from 1 in plan execution order. The exchange is
**level-based, not edge-based**: the robot waits for `hs_done_step >= N`, never for a pulse.
This makes the protocol immune to missed edges, polling jitter, and restarts mid-sequence.

```
robot:        arrive at step N  ->  hs_at_step = N  ->  WAIT until hs_done_step >= N
coordinator:  see hs_at_step = N  ->  do step N's work  ->  hs_done_step = N
```

The coordinator MUST treat `hs_at_step = N` as implying the robot is stationary at step N's
declared pose (the emitter guarantees the write happens after the motion command completes).

### Interlocks become motion gates

A capability's `preconditions` (e.g. `drive_screw` requires `screw_present == true`) are
enforced by the coordinator **before** it writes `hs_done_step` for the standoff step. The
robot is therefore physically unable to descend to contact until the precondition holds.
Manifest preconditions compile to real gates on real motion — not comments (ADR-0023,
spec/00 item 7).

A precondition may name a signal on a **peer** instance, not only the acting module's own:
`drive_screw` requires `workpiece_secured`, which the cell binds to `nest1.clamped` (ADR-0023
Decision 4). The read path is instance-qualified; the expression grammar is not — binding
resolves to a concrete `(instance, signal)` pair before any condition is evaluated. This is
how the dogfood cell declares its single most important interlock — do not apply torque to an
unheld part — with no wait syntax in the plan at all.

Symmetrically, a capability's `postconditions` are verified **after** the module reports PackML
Complete and **before** the step advances (ADR-0023 Decision 2). PackML Complete is necessary,
not sufficient: a module reporting Complete while one of its own declared postconditions reads
false against the live bus is faulted, not believed.

### Abort

`hs_abort != 0` commands the robot to halt in place (URScript: `halt`). Recovery is
coordinator-side and governed by the module's declared `abort_safe`. v1 defines only the
halt; Held/resume choreography is deliberately out of scope until a real cell needs it.

### Timeouts and liveness

- Robot side: no timeout on `hs_done_step` waits by default — a cell legitimately pauses
  (operator door, feeder empty). The coordinator owns timing policy.
- Coordinator side: `hs_heartbeat` static for > 2 s while a program should be running =
  robot program dead or connection lost -> coordinator faults the cell.

### Timeout disposition

Every capability declares a `timeout_s` alongside `nominal_duration_s`, and an `on_timeout` of
`hold` or `abort` (ADR-0023 Decision 6). The coordinator bounds each per-op wait — for a
capability's preconditions to hold, and for it to report Complete — by that capability's own
`timeout_s`. This is distinct from `hs_heartbeat` liveness above: the heartbeat watches the
robot *program*, `timeout_s` watches a single *operation*.

On expiry the part is disposed by the capability's own declaration, never the plan's:

- `on_timeout: hold` → PackML **Held**. Nothing is damaged and the part is where it was; an
  operator clears the cause and resumes. `on_timeout: hold` on a module that is not
  `abort_safe` is incoherent and refuses at validate (`TIMEOUT_DISPOSITION_CONFLICT`).
- `on_timeout: abort` → **Abort** (`hs_abort`); the part is compromised and surfaces for the
  plan's `on_fail` routing.

`timeout_s` is a module fact — how long before this operation is wrong — and a plan may not
override it. It composes with the plan's `on_fail` (the disposition of *this part*): the
timeout fires, the module goes Held or Aborted per `on_timeout`, and `on_fail` decides eject
and reject.

## Transport bindings

A robot module manifest binds each semantic signal to a transport address in its `signals:`
block, using `role: handshake_at_step | handshake_done_step | handshake_abort |
handshake_heartbeat`. The generated coordinator logic is identical across all bindings; only
the I/O driver differs (same move as ADR-0009: spec the profile, not the vendor).

### Binding: `ur-rtde` (reference)

Universal Robots RTDE, TCP port 30004, documented and versioned by UR. General-purpose
integer registers, readable/writable from URScript and from an external RTDE client.

| Signal | RTDE register | URScript access |
|---|---|---|
| `hs_at_step` | output int register 0 | `write_output_integer_register(0, N)` |
| `hs_heartbeat` | output int register 1 | `write_output_integer_register(1, k)` |
| `hs_done_step` | input int register 0 | `read_input_integer_register(0)` |
| `hs_abort` | input int register 1 | `read_input_integer_register(1)` |

Registers 0–1 in each direction are reserved by this spec; 2–23 are free for cell-specific
use. Latency is ~10–30 ms per exchange — negligible against process durations (1.8 s drive,
0.9 s feed), and irrelevant to safety, which is not on this channel.

### Binding: `discrete-io` (alternate)

For shops that want a meter-debuggable handshake: `hs_at_step`/`hs_done_step` degrade to
one bit each (level semantics: "at current step" / "current step done"), `hs_abort` one bit,
heartbeat one toggling bit. Loses step *numbers* (the coordinator must track the counter
itself) — acceptable, documented, not the default.

### Future bindings

Fanuc: SNPX numeric registers. ABB: RWS RAPID persistent variables. Same four signals, same
protocol, new driver. A binding is conformant if it provides all four signals with integer
range >= 16 bits and level semantics.
