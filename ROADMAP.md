# Roadmap

The order here is deliberate and counterintuitive. **The mechanical design comes fourth.**

## Why not build the frame first

Because we already know how to build a frame. It carries no information. Six months of
mechanical design would tell us nothing we didn't already know, cost real money in steel and
servos, and leave the actual risk completely untouched.

The question that decides whether this project is real:

> **Can the generator go from `cell.yaml` + `plan.yaml` to a collision-checked robot program
> and a PLC sequence, with no human writing waypoints?**

That is testable on a laptop in two or three weeks with zero hardware. If it's false, we
found out cheap. If it's true, we have the demo that makes everything else credible.

---

## Step 0 — Freeze the interface spec ⬅ *do this now*

**One page of decisions, not a CAD model.** Everything hangs off it, and it costs an afternoon.

- [ ] Bolt grid: 50 mm own pattern, or ride 8020's for free adoption? *(open question)*
- [x] Connector pinout: M12 A-coded, 5-pin, PNP, IO-Link-capable (`spec/03-electrical-interface.md`)
- [x] Bus + power: EtherCAT daisy chain + 24 V, one cable each (`spec/04-fieldbus.md`)
- [x] State machine: PackML, mandatory (`spec/05-state-machine.md`)

## Step 1 — Build the generator ⬅ *the thesis*

```
cell.yaml + plan.yaml
     ↓  load URDF fragments → Tesseract scene
     ↓  plan the sequence, collision-checked
     ↓  emit URScript + PLCopen XML
     ↓  REFUSE when torque_nm = 6.0 on a 5.0 N·m tool
```

Everything in that chain exists and is free. Nothing needs to be invented.

- [x] `ocm-core` — manifest load + validate
- [x] `scene/` — cell.yaml → Tesseract environment
- [x] `planner/` — Tesseract + Ruckig (IK/collision need the Tesseract extra)
- [x] `emitters/urscript.py`
- [ ] `emitters/plcopen.py` — *not built yet*
- [x] **`validate/`** — the refusal logic, now in `ocm-resolve` + `ocm-api` (ADR-0012,
  ADR-0016). *The most valuable output of this tool is "no."*

**Status (as of this commit):** the chain runs on a laptop — `ocm-core` + `ocm-resolve` +
`ocm-api` + `ocm-generator` take a resolved cell to a Tesseract scene, a collision-checked
plan, URScript, a cycle-time estimate, and a PackML coordinator on **simulated** I/O, with
the refusal engine live. Remaining before the exit criterion is met: the PLCopen-XML emitter
and the demo video. Nothing has run on real fieldbus I/O yet.

**Exit criterion:** a video of a cell being generated from a YAML file, collision-checked,
with the tool refusing an out-of-spec torque. That video is the marketing artifact.

## Step 2 — Dogfood on a paying job ⬅ *free schema validation*

We build custom cells anyway. On the next one: write OCM manifests for the modules we're
already specifying, run the generator, and compare its output to the logic we were going to
hand-write.

- Zero speculative time — the job is happening regardless
- Real modules, real part, real deadline, real customer
- **Every gap the schema can't express is a finding**

This is the only honest way to correct the spec. A toy demo cell we built to convince
ourselves proves nothing.

## Step 3 — Publish

Spec + generator + the dogfood results. This is what turns the project into inbound.

## Step 4 — Mechanical design

**Now.** Because now we know what the frame has to do.

- [ ] Bolted tab-and-slot frame (ADR-0005) — *not welded*
- [ ] Mic-6 datum plate, one machined reference edge (ADR-0006)
- [ ] **Modal hammer test. Publish the number.** Target: first mode > 60 Hz.

## Step 5 — Reference build

Gantry, drives, panel, one real module.

## Step 6 — Agent layer

**Last, not first.** The agent is a thin tool-calling wrapper over a generator that already
works. Building it before the generator is building a UI for nothing.

## Step 7 — HMI placement

An hour's work on one physical machine. It is not a platform concern.
*(If this ever feels urgent, we've drifted from building a standard to building a cell.)*
