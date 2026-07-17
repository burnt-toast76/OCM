# SPDX-License-Identifier: AGPL-3.0-or-later
"""ocm_generator.coordinator -- a generated Python coordinator program for
a resolved cell's fastening for_each sequence, executing spec/08's
robot<->coordinator handshake against the exact URScript
`ocm_generator.emitters.urscript` emits.

Not PLCopen yet (ROADMAP Step 1's `emitters/plcopen.py` is still future
work) -- a plain asyncio program, proven correct in loopback against
simulated peers before any real transport exists:

- `.signals.SignalBus` stubs the EtherCAT/SOEM layer (ADR-0002) a module's
  own signals live behind.
- `.robot_link.RobotLink` binds spec/08's four handshake signals to a
  robot module BY ROLE, from its own manifest -- never a hardcoded
  register number.
- `.packml` evaluates a capability's declared preconditions against live
  signals, and defines this v0's (frankly, placeholder) PackML command/
  state numeric encoding -- see that module's own docstring on why.
- `.program.Coordinator` is the generated program itself.
- `.urscript_sim.SimulatedRobot` and `.simulated_module.SimulatedPackMLModule`
  are the loopback proof's simulated peers -- a URScript-parsing stand-in
  for the physical robot, and a PackML-simulating stand-in for a real
  EtherCAT slave's firmware, respectively. Real RTDE/SOEM transports are
  drivers to add later, behind the same two interfaces.
"""

from .errors import CoordinatorError, HandshakeBindingError, HeartbeatStaleError, PreconditionError
from .packml import PackMLCommand, PackMLState
from .program import Coordinator, CoordinatorResult, TraceEntry, write_trace_log
from .robot_link import RobotLink
from .signals import SignalBus, SimulatedSignalBus
from .simulated_module import SimulatedPackMLModule, default_load_screw_recipe, make_drive_screw_recipe
from .urscript_sim import RobotAborted, RobotEvent, SimulatedRobot

__all__ = [
    "Coordinator",
    "CoordinatorError",
    "CoordinatorResult",
    "HandshakeBindingError",
    "HeartbeatStaleError",
    "PackMLCommand",
    "PackMLState",
    "PreconditionError",
    "RobotAborted",
    "RobotEvent",
    "RobotLink",
    "SignalBus",
    "SimulatedPackMLModule",
    "SimulatedRobot",
    "SimulatedSignalBus",
    "TraceEntry",
    "default_load_screw_recipe",
    "make_drive_screw_recipe",
    "write_trace_log",
]
