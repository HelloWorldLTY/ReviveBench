# mesx — a manufacturing execution core

You are building the execution core of an MES, the class of system Siemens Opcenter and Rockwell
FactoryTalk occupy: release work orders onto a finite-capacity shop floor, schedule their operations
through routed work centres, consume material lots with full genealogy, reconcile scrap, and report
OEE.

Every rule below is stated exactly and the engine is deterministic: one scenario has exactly one
correct answer. The schedule, the genealogy and the material balance are therefore graded **with no
tolerance at all**. Only the OEE ratios, being floats, carry a 1e-9 band.

## 1. Entry point

    bash run_mes.sh <scenario.json> <out.json>

Must sit at the workspace root, exit non-zero on error, and use an explicit interpreter in the
shebang. It is invoked as `bash run_mes.sh ...`, so the file must be a **shell script**, not a
Python file with a `.sh` name.

It is invoked with an **arbitrary working directory** — not your workspace — and both arguments are
absolute paths. Resolve your own files relative to the script's own location, never relative to
`$PWD`.

## 2. Input

```json
{"name": "m01", "horizon_min": 960,
 "work_centres": [{"id": "WC1", "available_min": 480}],
 "routings": {"P100": [{"op": 10, "wc": "WC1", "setup_min": 20, "run_min_per_unit": 2,
                        "scrap_ppm": 0, "consumes": [{"material": "R1", "qty_per_unit": 2}]}]},
 "lots": [{"id": "L1", "material": "R1", "qty": 500, "received": 0}],
 "work_orders": [{"id": "WO1", "product": "P100", "qty": 100, "release_min": 0, "priority": 1}]}
```

* A work centre processes **one operation at a time**. `available_min` is its capacity within the
  horizon, used for OEE only — it never truncates the schedule.
* A routing is an ordered list of operations. Operation `n+1` of a work order cannot start before
  operation `n` of that work order has finished.
* `scrap_ppm` is parts-per-million of the quantity *entering* that operation.

## 3. Scheduling

Time is in whole minutes from 0. At every moment a work centre becomes free, choose among the
operations that are **ready** — released, predecessor complete, materials available — by this key,
lowest first:

1. `priority`
2. `release_min`
3. work-order id (lexicographic)
4. operation number

Ties cannot occur beyond that, because work-order ids are unique.

An operation occupies its work centre for `setup_min + ceil(qty_in) * run_min_per_unit`, where
`qty_in` is the quantity entering the operation. Setup is incurred **every time** the operation
runs; there is no setup carry-over between consecutive work orders of the same product.

Report each scheduled operation as `{"wo": …, "op": …, "wc": …, "start_min": …, "end_min": …,
"qty_in": …, "qty_out": …}`, sorted by `start_min`, then `wc`, then `wo`.

## 4. Scrap and yield

At each operation, `scrapped = floor(qty_in * scrap_ppm / 1_000_000)` and
`qty_out = qty_in - scrapped`. Quantities are whole units throughout; the floor is what makes this
exact rather than a rounding convention you have to guess.

The work order's finished quantity is the `qty_out` of its last operation. The **material balance**
must hold for every material: `received − consumed = remaining`, and it is checked directly.

## 5. Material consumption and genealogy

An operation consuming material `m` needs `qty_in * qty_per_unit` units of it. Lots are consumed
**FIFO by `received`, breaking ties by lot id**, and a single operation may draw from several lots.
If insufficient material exists the operation is **not schedulable** and its work order stalls —
report it in `stalled` and schedule nothing further for it.

Report genealogy per work order as `{"wo": …, "consumed": [{"lot": …, "material": …, "qty": …}]}`,
lots in consumption order.

## 6. OEE

Per work centre, over the horizon:

* `availability = busy_min / available_min`, where `busy_min` is setup + run time actually scheduled
* `performance = ideal_run_min / run_min`, where `ideal_run_min` excludes setup and `run_min`
  includes it — so performance falls as setup overhead grows
* `quality = total_good / total_in`, summed over operations on that centre
* `oee = availability * performance * quality`

Report all four per work centre. A centre that ran nothing reports zeros.

## 7. Output

```json
{"schedule": [...], "genealogy": [...], "stalled": ["WO7"],
 "inventory": [{"material": "R1", "received": 500, "consumed": 200, "remaining": 300}],
 "oee": [{"wc": "WC1", "availability": 0.5, "performance": 0.9, "quality": 1.0, "oee": 0.45}]}
```

`inventory` is sorted by material, `oee` by work centre, `stalled` by work-order id.

## 8. What is graded

| check | tolerance |
|---|---|
| `schedule` | none — exact operations, times, quantities and ordering |
| `genealogy` | none — exact lots, order and quantities |
| `material_balance` | none — exact integers, and `received − consumed = remaining` must hold |
| `oee_metrics` | 1e-9 per ratio |

## 9. Rules

* Python 3.12 with NumPy and pytest. Nothing else is installed and nothing may be installed. In
  particular no `simpy`, `pulp`, `ortools`, `pandas`, `networkx`, `scipy`.
* The hidden set includes: two work orders contending for one work centre where the dispatch key
  decides the order, an operation that must draw from three lots to cover its demand, a work order
  that stalls for want of material while a later one proceeds, a scrap rate that makes `floor`
  differ from rounding, and a centre whose setup overhead drags performance well below 1.
