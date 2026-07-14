# modules

The manifest registry. One directory per module:

```
com.vendor.kind.model/
  module.yaml     <- the manifest
  meshes/         <- visual (GLB) + collision (convex STL)
  urdf/           <- urdf_fragment  ** the load-bearing field **
  esi/            <- EtherCAT device description
```

Worked examples: `com.accelsolutions.screwdriver.sd50` (hold-still op) and
`com.accelsolutions.dispense.dh200` (along-a-path op).
