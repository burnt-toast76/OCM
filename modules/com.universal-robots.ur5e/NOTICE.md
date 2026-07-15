# Third-party notice — vendored UR5e description

This module directory (`meshes/collision/`, `urdf/`) vendors data from
Universal Robots' own robot description package:

- **Source:** https://github.com/UniversalRobots/Universal_Robots_ROS2_Description
- **Commit:** `db618f289c4c49eaed19ebe57f79d7ba83459159` (`rolling` branch)
- **License:** BSD-3-Clause (see `LICENSE` in this directory, copied unmodified
  from the source repository)
- **Copyright:** the contributors of Universal_Robots_ROS2_Description
  (see that repository's git history; no single copyright line is stamped
  in its `LICENSE` file)

This is a permissive, non-share-alike license. It does **not** need to
become CC BY-SA 4.0 to live under `modules/` (see `../../LICENSING.md`) —
BSD-3-Clause content can be included as-is, under its own terms, inside a
CC BY-SA-licensed directory. Retain this notice and the `LICENSE` file with
any copy of this subtree.

## What was vendored, and how

Vendored directly, unmodified:

- `meshes/collision/*.stl` — the 7 per-link collision meshes for `ur5e`
  (`base`, `shoulder`, `upperarm`, `forearm`, `wrist1`, `wrist2`, `wrist3`).
- `urdf/config/*.yaml` — the 4 `ur5e`-specific parameter files
  (`default_kinematics.yaml`, `joint_limits.yaml`, `physical_parameters.yaml`,
  `visual_parameters.yaml`). These are the actual source of truth the
  upstream xacro macros read; they are not modified here.

Derived, not vendored verbatim:

- `urdf/ur5e.urdf.xacro` is **not** a copy of anything upstream. Upstream's
  real URDF is produced by a xacro macro (`urdf/ur_macro.xacro` +
  `urdf/inc/ur_common.xacro`) parameterized by the four YAML files above,
  which requires ROS's `xacro`/`ament_index` package-resolution machinery
  (`$(find ur_description)/...`) to expand — machinery this repo doesn't
  have and isn't taking on as a dependency just to flatten one file.
  `urdf/generate_flat_urdf.py` does the same substitution the macro does,
  reading the *same* vendored YAML values, and emits a flat URDF directly.
  The link/joint chain, names, and fixed-offset values it doesn't read
  from YAML (e.g. the `base_link_inertia`, `flange`, `tool0` frame
  definitions) are transcribed from `ur_macro.xacro` at the commit above.

**Not vendored:**

- Visual meshes (`meshes/ur5e/visual/*.dae`) — `ocm_generator.scene` only
  needs collision geometry; visual assets are `ocm-viewer`'s concern, not
  authored yet.
- `ros2_control`/transmission/Gazebo xacro (`ur_joint_control.xacro`,
  `ur_transmissions.xacro`, `ur_sensors.xacro`) — this project drives the
  arm over URScript / Modbus TCP (see `module.yaml`'s description), not
  `ros2_control`, so there is nothing here for those files to configure.
- Safety-limit / `tf_prefix` / mimic-joint xacro parameters — left at their
  upstream defaults (`safety_limits:=false`, no prefix) since this module
  is a single, unprefixed instance.

Re-run `python urdf/generate_flat_urdf.py > urdf/ur5e.urdf.xacro` after
updating `urdf/config/*.yaml` (e.g. with a per-unit kinematic calibration)
to regenerate the flattened fragment mechanically rather than by hand.
