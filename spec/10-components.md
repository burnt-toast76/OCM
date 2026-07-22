# OCM Spec — Component Definitions v1.0 (draft)

A **component** is a purchasable part described by transcribed catalog facts: an ejector, an
IO-Link master, a valve island, a camera body. Components live in `components/<id>/` and are
referenced by modules. **See ADR-0014 for the transcription-vs-design boundary — it is the
governing rule of this spec.**

## What a component definition contains

Only questions a datasheet answers:

- identity: id, vendor, part number, datasheet reference (url or filename)
- `electrical` — supplies (peak/nominal *as stated*), connectors
- `pneumatic` — pressure as a **range** if the source gives one (`pressure_min/max` plus a
  verbatim `units` field -- never converted), ports, flow
- `signals` — the device's own I/O as documented, device-perspective directions
  (`direction_device: output` for a PNP part-present), protocol incl. `x-` customs, IODD/ESI
  references as *citations* (a note naming the file, never an invented path)
- `geometry` — envelope dims and mass as stated; mesh/step paths only when files exist
- `hazards` — intrinsic ones the source states (a heated tip is `burn_hot` at the component)
- `notes` — verbatim-ish cautions and requirements from the source

## What it must NOT contain

TCP or working frames, capabilities, preconditions, PackML, performance levels, guarding,
safe-state behavior, mount interface, operating setpoints. All of these are assembly-level
judgment → module layer.

## How modules consume components

```yaml
# module.yaml (additive, optional)
components:
  - refdes: VG1
    ref: com.smc.ejector.zk2-agh@1.0.0
  - refdes: IO1
    ref: com.beckhoff.io.ep6224@1.0.0
comms:
  signals:
    - name: part_present
      direction: input          # coordinator perspective, as today
      type: bool
      source: VG1.part_present  # provenance into the component's signal list
```

Derivable from the list: module power budget, air consumption, and **the purchasable BOM**
(the kit tier's parts list). Aggregation rules land with the implementation.

## Draft/publish and the human handoff

Component drafts always-write, publish gates on validity — same lifecycle as modules. An
AI-transcribed component with gaps **stays a draft**; its validation refusals are the
completion list a human works through. That refusal-list-as-TODO is the intended workflow,
not a failure mode.

## Open (deliberately, for v1)

- Component `kind` taxonomy: start with a small open set + `x-` extension, resist a deep
  ontology until the registry has twenty real entries.
- Whether signal aggregation surfaces automatically or is always hand-picked at the module
  boundary (current lean: always hand-picked; auto-surfacing is magic that will guess wrong).
