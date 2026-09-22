# scadax — a SCADA/DCS runtime

You are building the runtime of a supervisory control system, the class of product Wonderware,
Ignition and DeltaV occupy: a deterministic scan engine driving a tag database, an alarm state
machine, PID control loops, a historian, and a Modbus register image.

Every rule below is stated exactly, and the engine is deterministic: given the same scenario, there
is exactly one correct answer. So the alarm journal, the historian results and the register image
are graded **with no tolerance at all** — one spurious alarm event, one missing one, or one event
with the wrong timestamp is a wrong answer. Only the PID outputs, being floats, carry a 1e-9 band.

## 1. Entry point

    bash run_scada.sh <scenario.json> <out.json>

Must sit at the workspace root, exit non-zero on error, and use an explicit interpreter in the
shebang. It is invoked as `bash run_scada.sh ...`, so the file must be a **shell script**, not a
Python file with a `.sh` name.

It is invoked with an **arbitrary working directory** — not your workspace — and both arguments are
absolute paths. Resolve your own files relative to the script's own location (for example with
`$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)`), never relative to `$PWD`.

## 2. The scan cycle

The engine runs at a fixed period `scan_ms`, at times `t = 0, scan_ms, 2*scan_ms, …` up to and
including `t_end_ms`. Each scan executes these phases **in this order**:

1. **Input** — every tag takes the value of the most recent entry in `inputs` whose `t_ms` is
   **≤ the current scan time** (zero-order hold). Before any input arrives a tag holds its `init`.
2. **Alarms** — evaluate every alarm against the freshly sampled values (§3).
3. **Loops** — run every PID loop (§4).
4. **Historian** — record every tag's current value at this scan time (§5).

Loop outputs written to a tag are visible to the *next* scan, not this one.

## 3. Alarm state machine

Each alarm has `tag`, `kind` (`HI`, `HIHI`, `LO`, `LOLO`), `limit`, `deadband`, `on_delay_ms`,
`off_delay_ms` and `priority`.

The **raw condition** is `pv > limit` for `HI`/`HIHI` and `pv < limit` for `LO`/`LOLO`.

The **latched condition** adds the deadband and is what drives the state machine:

* while inactive, it becomes true when the raw condition is true;
* while active, it becomes false only when `pv < limit - deadband` (`HI`/`HIHI`) or
  `pv > limit + deadband` (`LO`/`LOLO`).

That asymmetry is the point of a deadband: a signal hovering at the limit must not chatter.

Delays are applied to the latched condition:

The timer is a **scan counter**, not a wall clock: each scan that observes the condition true
accumulates one whole `scan_ms`, so the `N`-th consecutive true scan has accumulated `N * scan_ms`.

* an `ACT` event is emitted at the first scan `N` (counting the scan at which the latched condition
  became true as `N = 1`) for which `N * scan_ms >= on_delay_ms`. Equivalently, at time
  `t_first_true + scan_ms * (ceil(on_delay_ms / scan_ms) - 1)`. With `on_delay_ms = 300` and
  `scan_ms = 100` the event lands on the **third** scan of the condition, not the fourth; with
  `on_delay_ms = 0` it lands on the first.
* a `CLR` event is emitted symmetrically, counting consecutive false scans against `off_delay_ms`,
  and only if the alarm was active.
* if the condition breaks before the delay elapses, the timer resets completely.

Journal entries are `{"t_ms": …, "tag": …, "kind": …, "event": "ACT"|"CLR", "priority": …}`, sorted
by `t_ms`, then by `priority` ascending, then by `tag`, then by `kind`.

## 4. PID loops

Positional form, evaluated once per scan with `dt = scan_ms / 1000`:

    e      = sp - pv
    P      = kp * e
    I     += ki * e * dt
    D      = kd * (e - e_prev) / dt
    raw    = P + I + D
    out    = min(max(raw, out_min), out_max)

* On the first scan `e_prev = e`, so `D = 0`.
* **Anti-windup**: if `raw` falls outside `[out_min, out_max]`, the integral accumulation for that
  scan is undone — restore `I` to its value before this scan's update. Compute `raw` again is not
  required; only `I` is rolled back, and the reported `out` is the clamped value.
* Report `{"t_ms": …, "out": …}` for every scan, in scan order.

## 5. Historian

The historian stores `(t_ms, value)` for every tag at every scan. Queries carry `tag`, `from_ms`,
`to_ms` and `agg`:

| `agg` | meaning |
|---|---|
| `twavg` | time-weighted average with zero-order hold: `Σ v_i·Δt_i / Σ Δt_i`, where `Δt_i` is the gap to the next sample, and the final sample in the window is weighted by the gap to `to_ms` |
| `avg` | plain mean of the samples in the window |
| `min`, `max` | extremes over the window |
| `count` | number of samples in the window |

The window is inclusive at both ends. `twavg` and `avg` differ whenever samples are unevenly
weighted, which is exactly what the hidden set checks.

## 6. Modbus register image

At `t_end_ms`, produce the holding-register image. `modbus.holding` maps tag ids to register
addresses. Analog tags are scaled as `round(value * 10)` with **half away from zero** rounding, then
clamped to `[0, 65535]`; digital tags become `0` or `1`. Registers not named by any tag are `0`.
Report the image as a list of integers from register `0` to the highest address used.

## 7. Output

```json
{"alarm_journal": [...], "loop_outputs": {"PIC1": [...]},
 "historian": [{"query": 0, "value": 42.5}, ...],
 "modbus_registers": [0, 1, 2, ...]}
```

`historian` entries are in query order and carry the numeric result under `value`.

## 8. What is graded

| check | tolerance |
|---|---|
| `alarm_journal` | none — exact event sequence, timestamps and ordering |
| `historian_queries` | none for `count`/`min`/`max`; 1e-9 for `twavg`/`avg` |
| `modbus_image` | none — exact integers |
| `loop_outputs` | 1e-9 per sample |

## 9. Rules

* Python 3.12 with NumPy and pytest. Nothing else is installed and nothing may be installed. In
  particular no `pymodbus`, `pyscada`, `opcua`, `asyncua`, `scipy`, `pandas`, `simpy`.
* The hidden set includes: a signal that oscillates across a limit so that only the deadband
  prevents a chattering journal, an alarm whose condition breaks one scan before its on-delay
  expires (so no event may be emitted), a loop that saturates and would wind up without the
  rollback, a `twavg` window whose answer differs materially from `avg`, and a value that clamps at
  the top of the Modbus range.
