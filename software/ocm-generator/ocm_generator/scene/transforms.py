# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pure rigid-transform composition along a joint chain -- no numpy, no
tesseract_robotics, just enough linear algebra to walk a URDF and know
where each link ended up in the world.

URDF's `<origin xyz="x y z" rpy="r p y"/>` is a fixed-axis (extrinsic)
roll (X), then pitch (Y), then yaw (Z) rotation: R = Rz(yaw) @ Ry(pitch) @
Rx(roll). That's the same convention ocm-module-1.0.schema.json's Frame
$def documents ("Matches URDF convention"). Getting this composition order
and sign convention wrong here would silently corrupt every downstream
consumer of a computed world pose -- this debug viewer today, the planner
tomorrow -- which is why it's split out and unit-tested on its own,
independent of URDF parsing or Tesseract. See tests/test_transforms.py.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

Vec3 = tuple[float, float, float]
Mat3 = tuple[Vec3, Vec3, Vec3]
Quat = tuple[float, float, float, float]  # (x, y, z, w) -- three.js's THREE.Quaternion order

_IDENTITY_ROTATION: Mat3 = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))


@dataclass(frozen=True)
class Pose:
    """A rigid transform: p_parent = rotation @ p_local + translation."""

    translation: Vec3
    rotation: Mat3 = _IDENTITY_ROTATION

    @classmethod
    def identity(cls) -> "Pose":
        return cls((0.0, 0.0, 0.0), _IDENTITY_ROTATION)

    @classmethod
    def from_xyz_rpy(cls, xyz: Vec3, rpy: Vec3) -> "Pose":
        return cls(tuple(xyz), _rotation_from_rpy(tuple(rpy)))

    @classmethod
    def from_axis_angle(cls, axis: Vec3, angle: float) -> "Pose":
        """A pure rotation of `angle` radians about `axis` (need not be unit
        length; normalized here) -- URDF's <joint><axis>/revolute-joint
        convention, via Rodrigues' rotation formula.
        """
        return cls((0.0, 0.0, 0.0), _rotation_from_axis_angle(axis, angle))

    def transform_point(self, point: Vec3) -> Vec3:
        """p_parent = rotation @ point + translation."""
        rotated = _mat3_vec(self.rotation, point)
        return (
            rotated[0] + self.translation[0],
            rotated[1] + self.translation[1],
            rotated[2] + self.translation[2],
        )

    def compose(self, local: "Pose") -> "Pose":
        """`local` is expressed in this pose's own frame; return the
        equivalent pose one frame up (e.g. self=world_T_parent,
        local=parent_T_child -> result=world_T_child).
        """
        rotation = _mat3_mul(self.rotation, local.rotation)
        rotated = _mat3_vec(self.rotation, local.translation)
        translation = (
            rotated[0] + self.translation[0],
            rotated[1] + self.translation[1],
            rotated[2] + self.translation[2],
        )
        return Pose(translation, rotation)

    def quaternion_xyzw(self) -> Quat:
        return _quaternion_from_matrix(self.rotation)


def _rotation_from_rpy(rpy: Vec3) -> Mat3:
    roll, pitch, yaw = rpy
    return _mat3_mul(_mat3_mul(_rot_z(yaw), _rot_y(pitch)), _rot_x(roll))


def _rot_x(a: float) -> Mat3:
    c, s = math.cos(a), math.sin(a)
    return ((1.0, 0.0, 0.0), (0.0, c, -s), (0.0, s, c))


def _rot_y(a: float) -> Mat3:
    c, s = math.cos(a), math.sin(a)
    return ((c, 0.0, s), (0.0, 1.0, 0.0), (-s, 0.0, c))


def _rot_z(a: float) -> Mat3:
    c, s = math.cos(a), math.sin(a)
    return ((c, -s, 0.0), (s, c, 0.0), (0.0, 0.0, 1.0))


def _rotation_from_axis_angle(axis: Vec3, angle: float) -> Mat3:
    length = math.sqrt(axis[0] ** 2 + axis[1] ** 2 + axis[2] ** 2)
    if length == 0.0:
        raise ValueError("rotation axis must not be the zero vector")
    ux, uy, uz = (axis[0] / length, axis[1] / length, axis[2] / length)
    c, s = math.cos(angle), math.sin(angle)
    t = 1.0 - c
    return (
        (t * ux * ux + c, t * ux * uy - s * uz, t * ux * uz + s * uy),
        (t * ux * uy + s * uz, t * uy * uy + c, t * uy * uz - s * ux),
        (t * ux * uz - s * uy, t * uy * uz + s * ux, t * uz * uz + c),
    )


def _mat3_mul(a: Mat3, b: Mat3) -> Mat3:
    return tuple(
        tuple(sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)) for i in range(3)
    )  # type: ignore[return-value]


def _mat3_vec(m: Mat3, v: Vec3) -> Vec3:
    return tuple(sum(m[i][k] * v[k] for k in range(3)) for i in range(3))  # type: ignore[return-value]


def _quaternion_from_matrix(m: Mat3) -> Quat:
    """Shepperd's method: numerically stable for any proper rotation matrix."""
    m00, m01, m02 = m[0]
    m10, m11, m12 = m[1]
    m20, m21, m22 = m[2]
    trace = m00 + m11 + m22

    if trace > 0:
        s = 0.5 / math.sqrt(trace + 1.0)
        return ((m21 - m12) * s, (m02 - m20) * s, (m10 - m01) * s, 0.25 / s)
    if m00 > m11 and m00 > m22:
        s = 2.0 * math.sqrt(1.0 + m00 - m11 - m22)
        return (0.25 * s, (m01 + m10) / s, (m02 + m20) / s, (m21 - m12) / s)
    if m11 > m22:
        s = 2.0 * math.sqrt(1.0 + m11 - m00 - m22)
        return ((m01 + m10) / s, 0.25 * s, (m12 + m21) / s, (m02 - m20) / s)
    s = 2.0 * math.sqrt(1.0 + m22 - m00 - m11)
    return ((m02 + m20) / s, (m12 + m21) / s, 0.25 * s, (m10 - m01) / s)
