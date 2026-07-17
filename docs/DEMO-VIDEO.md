# OCM Demo Video — Script & Production Plan

**Target: 3–4 minutes.** Screen recording + voiceover. Every command below runs today
against `main` — nothing staged, nothing mocked beyond the simulated hardware the tests use.

**The one-sentence thesis the video must land:**
> Modules declare themselves in a manifest; a cell composes them in YAML; the tool
> generates the robot program and the coordinator — and refuses anything that doesn't add up.

**The emotional arc:** not "look what I built" but "watch the tool say NO five times,
correctly, before it says yes." The refusals are the product. Lead with them.

---

## Pre-production: stage the sabotage as files, don't live-edit

Live-editing YAML on camera invites typos and dead air. Create these once, commit to a
`demo/` branch (not main):

```
cells/demo-bad-torque/      cell.yaml with torque_nm: 6.0
cells/demo-bad-op/          cell.yaml with op: drive_screww
cells/demo-low-camera/      cell.yaml with cam1 z: 420   (the original layout bug!)
cells/demo-out-of-bounds/   cell.yaml with feed1 x: 1150
cells/bracket-asm-01/       the good one (unchanged, on main)
```

Terminal: 16–18 pt font, dark theme, window sized so refusal messages don't wrap.
Record terminal and browser in separate takes; cut together. OBS or even a phone
pointed at the screen for v1 — done beats polished.

---

## Shot list

### Shot 1 — The manifest (0:00–0:35)

Open `modules/com.accelsolutions.screwdriver.sd50/module.yaml`, scroll slowly through
`capabilities.drive_screw`: the torque bounds, the approach vector, `preconditions:
screw_present == true`.

> *"This is a screwdriver describing itself. Its torque limits. How a robot must approach
> it. And this line — it will not drive without a screw confirmed present. Keep that line
> in mind; you'll see it stop a robot at the end of this video."*

### Shot 2 — The cell (0:35–0:55)

Open `cells/bracket-asm-01/cell.yaml`. Point at what's NOT there.

> *"A cell is a YAML file: which modules, where they sit, what to build. No waypoints. No
> ladder logic. No I/O map. Nobody opens a CAD package. Everything downstream is generated."*

### Shot 3 — The scene (0:55–1:20)

```
ocm scene cells/bracket-asm-01/cell.yaml --modules modules --view cell.html
```

Open the HTML. Orbit slowly through the glass walls: deck, feeder, nest, UR5e folded at
home, screwdriver on the flange, TCP marker.

> *"One command. The 3D cell, composed from each module's own geometry. The kinematics are
> verified — that tool center point is 186.5 millimeters off the flange because the
> manifest says so. The glass walls aren't decoration; they're collision geometry."*

### Shot 4 — The refusal montage (1:20–2:10) ← the heart of the video

Rapid fire, one command per beat, let each red message breathe for 2 seconds:

```
ocm resolve cells/demo-bad-torque/cell.yaml --modules modules
```
> *"Ask for 6 newton-meters from a 5 newton-meter tool — refused, citing the module's own limit."*

```
ocm resolve cells/demo-bad-op/cell.yaml --modules modules
```
> *"Typo an operation — refused, and it tells you what the module CAN do."*

```
ocm scene cells/demo-out-of-bounds/cell.yaml --modules modules
```
> *"Put a feeder outside the guarding — refused, by 30 millimeters, in the +X direction."*

```
ocm plan cells/demo-low-camera/cell.yaml --modules modules --emit-urscript /tmp/x.script
```
> *"And this one's real: our first camera position was 420 millimeters over the nest. The
> planner refused — the robot's wrist sweeps through the camera halfway along the path.
> That's a crash we found in YAML instead of at commissioning. This exact refusal caught a
> genuine mistake WE made designing this cell."*

### Shot 5 — The payoff (2:10–2:50)

```
ocm plan cells/bracket-asm-01/cell.yaml --modules modules --emit-urscript bracket.script
```

Scroll the emitted URScript, then hold on the cycle-time table.

> *"Fix the camera — one line of YAML — and out comes a program a real UR5e executes.
> Every motion collision-checked. And a cycle estimate: 11 seconds for the three-screw
> sequence — including the screw-feed overlapping robot motion, because the feeder's
> manifest says it doesn't need the robot to be anywhere. The tool found that overlap
> itself. Nobody choreographed it."*

### Shot 6 — Both halves, closed loop (2:50–3:30)

```
cd software/ocm-generator && python -m pytest tests/ -k loopback -v
```

> *"The other half: a generated coordinator that speaks to the robot over a step-counter
> handshake — no wiring, it rides the network the robot already has. In this test, both
> generated programs run against each other. Watch the middle one: the coordinator
> withholds permission while no screw is present — and the robot provably holds at
> standoff. That precondition from shot one just physically stopped a robot. And if the
> robot dies mid-sequence, the coordinator notices its heartbeat go stale and faults the
> cell in bounded time."*

### Shot 7 — Close (3:30–3:50)

Repo README on screen.

> *"Open spec. Open hardware — the frame is a DXF any laser shop on earth can cut. Open
> software, end to end: AGPL, CERN-OHL-S. It's called OCM. Build it yourself from the
> files, buy a kit, or have us build it complete. Link below."*

---

## Production notes

- **Thumbnail:** the camera-collision refusal message, big red text. A tool saying "no"
  is the most clickable frame you have.
- **Honesty beats polish.** Say "simulated hardware" out loud in shot 6. The automation
  audience will respect it; hiding it would cost you them forever.
- **Do NOT show:** installation, code internals, test counts. Nobody cares yet.
- **Length discipline:** if a take pushes past 4:00, cut shot 2 to one sentence before
  touching the refusal montage. The montage is untouchable.
- **One inaccuracy to avoid:** don't say "no PLC programming" — say "the coordinator is
  generated." The PLCopen/hardware transport is future work and the video shouldn't claim it.

## Where it goes

1. **Repo README, top** — embedded, first thing anyone sees
2. **LinkedIn** — your controls/integrator network is exactly the audience; post with the
   camera-refusal story as the hook text
3. **r/PLC, r/robotics, r/AutomationEngineers** — lead with the refusal montage framing
4. **Hacker News "Show HN"** — title shaped like: *"Show HN: Open-source assembly cells —
   modules self-describe, the toolchain generates robot + coordinator programs and refuses
   bad plans"*
5. Clip shot 4 alone as a 60-second vertical cut for the short-form feeds

## After it ships

Expect two reactions: "this is just [vendor tool]" (answer: those are closed, per-seat,
single-vendor — this is a spec anyone can implement, MIT-to-AGPL stack, and the DXF is the
deliverable) and "it's all simulation" (answer: correct, and the roadmap is public —
transports are drivers, the logic is what's proven). Both answers are already in the ADRs;
link them rather than arguing.
