#!/usr/bin/env python3
"""Deterministic stimulus generation for each hidden program + reference traces (cycle 10 ms)."""
import pathlib, random, subprocess, sys
HERE = pathlib.Path(__file__).resolve().parent; CYCLE = "10"
random.seed(7)
def sq(n, period, duty=0.5, phase=0): return [1 if ((k + phase) % period) < period * duty else 0 for k in range(n)]
def rnd_bool(n, p): return [1 if random.random() < p else 0 for _ in range(n)]
S = {}
n = 400
S["motor_latch"] = (["StartPB", "StopPB", "EStop"], list(zip(sq(n, 60, 0.05), sq(n, 150, 0.03, 40), [1 if 250 <= k < 270 else 0 for k in range(n)])))
S["conveyor_count"] = (["Run", "Sensor", "Reset"], list(zip([1 if 5 <= k < 300 else 0 for k in range(n)], sq(n, 17, 0.3), [1 if k in (200, 201) else 0 for k in range(n)])))
S["traffic_light"] = (["Enable", "Pedestrian"], list(zip([1 if 3 <= k < 900 else 0 for k in range(1000)], [1 if k in (120, 121, 640) else 0 for k in range(1000)])))
S["pulse_shaping"] = (["Trig"], [(v,) for v in [1 if (10 <= k < 15) or (60 <= k < 120) or (200 <= k < 205) or (210 <= k < 260) else 0 for k in range(n)]])
lv = 20.0; rows = []
for k in range(n):
    inflow = 3.0 if k < 150 else 0.5; auto = 1 if 20 <= k < 350 else 0
    rows.append((round(lv, 3), inflow, auto)); lv = max(0.0, min(120.0, lv + inflow - (0.9 if lv > 55 else 0.0) + (0.4 if auto else 0.0)))
S["tank_control"] = (["Level", "Inflow", "Auto"], rows)
S["debounce_fb"] = (["BtnA", "BtnB"], list(zip([1 if (20 <= k < 23) or (30 <= k < 80) or (90 <= k < 92) or (100 <= k < 200) else 0 for k in range(n)], [1 if (110 <= k < 190) or (250 <= k < 258) else 0 for k in range(n)])))
S["loops_math"] = (["N", "X"], [(k % 14, round(2.0 + k * 0.37, 2)) for k in range(60)])
S["countdown_sr"] = (["Tick", "Load", "Arm", "Disarm"], list(zip(sq(n, 10, 0.5), [1 if k in (5, 120, 300) else 0 for k in range(n)], [1 if k in (8, 9, 130, 310) else 0 for k in range(n)], [1 if k in (60, 61) else 0 for k in range(n)])))
S["blinker"] = (["On", "Fast"], list(zip([1 if 5 <= k < 350 else 0 for k in range(n)], [1 if 150 <= k < 260 else 0 for k in range(n)])))
temps = [70 + 25 * (1 if 40 <= k < 120 else 0) + 15 * (1 if 200 <= k < 230 else 0) + (k % 7) * 0.5 for k in range(n)]
S["alarm_ack"] = (["Temp", "Ack", "Silence"], list(zip([round(t, 2) for t in temps], [1 if k in (70, 71, 215) else 0 for k in range(n)], [1 if 100 <= k < 110 else 0 for k in range(n)])))
for name, (hdr, rows) in S.items():
    st = HERE / "programs" / f"{name}.csv"; st.write_text(",".join(hdr) + "\n" + "\n".join(",".join(str(v) for v in r) for r in rows) + "\n")
    tr = HERE / "ref" / f"{name}.csv"
    p = subprocess.run([sys.executable, str(HERE / "reference_plc.py"), str(HERE / "programs" / f"{name}.st"), str(st), str(tr), CYCLE], capture_output=True, text=True)
    lines = tr.read_text().splitlines() if tr.exists() else []
    print(name, "rows", len(lines) - 1, "| last:", lines[-1] if lines else p.stderr[-300:])
