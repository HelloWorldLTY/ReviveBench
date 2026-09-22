# prx — a standard-cell place-and-route engine

You are building the back-end engine of a digital implementation flow, the class of tool that
Cadence Innovus and Synopsys ICC2 occupy: take a gate-level netlist and a floorplan, place every
cell legally into rows, then route every net on a metal grid.

Everything is on an **integer grid**. Coordinates, cell sizes, row positions and wire segments are
all integers, so the legality and connectivity checks below admit **no tolerance**: a single
overlapping cell or a single disconnected net is a wrong answer, in the same way a misrouted chip
is a wrong chip. Only the wirelength *quality* comparison is a tolerance-based, informational
measure.

## 1. Entry point

    bash run_pnr.sh <design.json> <out.json>

Must sit at the workspace root, exit non-zero on error, and use an explicit interpreter in the
shebang. It is invoked as `bash run_pnr.sh ...`, so the file must be a **shell script**, not a
Python file with a `.sh` name.

It is invoked with an **arbitrary working directory** — not your workspace — and both arguments are
absolute paths. Resolve your own files relative to the script's own location (for example with
`$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)`), never relative to `$PWD`.

## 2. Input: design.json

```json
{
  "name": "c07",
  "die": {"w": 120, "h": 80},
  "row_height": 10,
  "site_width": 1,
  "cells": {
    "INV": {"w": 3, "h": 10, "pins": {"A": [1, 5], "Y": [2, 5]}},
    "NAND2": {"w": 4, "h": 10, "pins": {"A": [1, 3], "B": [1, 7], "Y": [3, 5]}}
  },
  "instances": [{"id": "u1", "cell": "INV"}, {"id": "u2", "cell": "NAND2"}],
  "blockages": [{"x": 40, "y": 20, "w": 20, "h": 20}],
  "nets": [{"name": "n1", "pins": [["u1", "Y"], ["u2", "A"]]}],
  "layers": 2
}
```

* Rows tile the die bottom-up: row `k` occupies `y ∈ [k*row_height, (k+1)*row_height)`, and there
  are `die.h / row_height` of them (always an exact division).
* A cell's `pins` are offsets from the instance's lower-left corner, given in the cell's unflipped
  orientation. All cells have `h == row_height`.
* Pin offsets are always **strictly interior**: `1 ≤ px ≤ w-1`. This guarantees that no two pins can
  ever land on the same grid point, even when cells abut. Two cells in one row with `x1 + w1 ≤ x2`
  have pin x-coordinates at most `x1+w1-1` and at least `x2+1` respectively; cells in different rows
  differ in y. You may rely on this — you will never be handed a design whose pins collide.
* `blockages` are fixed rectangles that no cell may overlap. They do **not** block routing.
* A net has two or more pins. Every instance pin appears in at most one net.

## 3. Output: out.json

```json
{
  "placement": {"u1": {"x": 4, "y": 0, "flip": false}, "u2": {"x": 8, "y": 0, "flip": true}},
  "routes": {
    "n1": {
      "segments": [{"layer": 1, "x1": 6, "y1": 5, "x2": 8, "y2": 5},
                   {"layer": 2, "x1": 8, "y1": 5, "x2": 8, "y2": 13}],
      "vias": [{"x": 8, "y": 5}]
    }
  },
  "hpwl": 1234
}
```

* `placement` — one entry per instance. `x`,`y` is the lower-left corner. `flip: true` mirrors the
  cell horizontally about its own vertical centre line, so a pin at offset `px` moves to
  `x + w - px`; `y` offsets are unaffected.
* `routes` — one entry per net.
* `hpwl` — the total half-perimeter wirelength of **your own** placement, summed over nets. For one
  net it is `(max_x - min_x) + (max_y - min_y)` over that net's pin coordinates. This is checked
  against a recomputation from your placement, so a figure that does not match your own placement
  is a wrong answer.

## 4. Placement rules (no tolerance)

1. Every instance lies fully inside the die: `0 ≤ x`, `x + w ≤ die.w`, likewise for `y`.
2. `y` is a row origin — an exact multiple of `row_height`.
3. `x` is a multiple of `site_width`.
4. No two instances overlap. Cells touching edge-to-edge (`x1 + w1 == x2`) is legal; sharing any
   interior area is not.
5. No instance overlaps a blockage rectangle.

## 5. Routing rules (no tolerance)

Routing happens on integer grid points. A segment occupies every grid point from `(x1,y1)` to
`(x2,y2)` inclusive.

1. **Layer direction**: layer 1 is horizontal (`y1 == y2`), layer 2 is vertical (`x1 == x2`).
2. **Connectivity**: for each net, the set of grid points formed by its segments, its vias and its
   pin locations must be *connected* — treating two points as adjacent when they are consecutive
   points of one segment, or when a via joins layer 1 and layer 2 at the same `(x,y)`.
3. **Pins are on layer 1** at the pin's absolute coordinate, and each pin point must be covered by
   at least one of the net's own layer-1 segments (or be a single-point segment).
4. **No shorts**: two *different* nets must never occupy the same `(layer, x, y)` grid point.
   Points of the same net may overlap freely.
5. **Vias**: a via at `(x,y)` is legal only if that net has a layer-1 segment and a layer-2 segment
   both covering `(x,y)`.
6. Everything stays inside the die: `0 ≤ x ≤ die.w`, `0 ≤ y ≤ die.h`.

## 6. What is graded

| check | tolerance |
|---|---|
| `placement_legality` | none — every rule of §4 on every instance of every design |
| `routing_correctness` | none — every rule of §5 on every net of every design |
| `hpwl_consistency` | none — your reported `hpwl` must equal the recomputation from your placement |
| `wirelength_quality` | informational — your routed length vs a reference router |

The first three are graded n-of-n across all hidden designs. A violation is a *proof* that the
layout is wrong, and there is no partial credit for "mostly legal".

## 7. Rules

* Python 3.12 with NumPy and pytest. Nothing else is installed and nothing may be installed. In
  particular no `openroad`, `klayout`, `gdstk`, `gdspy`, `shapely`, `networkx`, `scipy`, `rtree`.
* The hidden set includes: a design where the rows are exactly full so placement has no slack, a
  design whose blockage splits a row into two segments, multi-pin nets (up to 6 pins), a net whose
  straight path is blocked by another net so it must detour, and a design dense enough that a naive
  left-to-right placer overflows the last row.
