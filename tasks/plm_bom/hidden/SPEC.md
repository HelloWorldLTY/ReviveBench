# plmx — a product lifecycle management core

You are building the data core of a PLM system, the class of product Teamcenter, Windchill and
ENOVIA occupy: revision-controlled parts, bills of material with date effectivity and variant
conditions, BOM explosion with quantity roll-up, where-used analysis, and engineering change impact.

Every answer is either a set or an integer quantity, fixed exactly by the rules below. **Nothing in
this task carries a tolerance.** A part missing from an explosion, a quantity off by one, or an
assembly missing from a change's impact set is a wrong answer — in a real plant it is the wrong
thing built or the wrong customer notified.

## 1. Entry point

    bash run_plm.sh <query.json> <out.json>

Must sit at the workspace root, exit non-zero on error, and use an explicit interpreter in the
shebang. It is invoked as `bash run_plm.sh ...`, so the file must be a **shell script**, not a
Python file with a `.sh` name.

It is invoked with an **arbitrary working directory** — not your workspace — and both arguments are
absolute paths. Resolve your own files relative to the script's own location, never relative to
`$PWD`.

## 2. Input

```json
{"name": "q01",
 "parts": [{"id": "P100", "rev": "B", "eff_from": "2026-01-01", "eff_to": "2026-12-31"}],
 "bom": [{"parent": "P100", "child": "S200", "qty": 2,
          "eff_from": "2026-01-01", "eff_to": "2026-06-30", "when": null}],
 "ecos": [{"id": "ECO7", "effective": "2026-07-01",
           "changes": [{"op": "qty", "parent": "P100", "child": "S200", "qty": 3}]}],
 "queries": [{"kind": "explode", "part": "P100", "date": "2026-03-15",
              "options": ["EU"]}]}
```

Dates are ISO `YYYY-MM-DD` strings and compare lexicographically, which is why that format is used.

* A **part revision** is effective when `eff_from <= date <= eff_to`. `eff_to` may be `null`,
  meaning open-ended. A part may have several revisions; **at most one is effective on any date**,
  and you may rely on that.
* A **BOM line** is effective under the same inclusive rule.
* `when` is a **variant condition**: `null` means unconditional, otherwise it is an option code and
  the line applies only when that code is present in the query's `options`.
* A part with no BOM lines effective on the date is a **leaf**.

## 3. Queries

### `explode`
Expand `part` on `date` under `options`, multiplying quantities down each level, and return the
**flat leaf quantities**: `[{"part": …, "qty": …}]`, sorted by part id.

A leaf reached by several paths accumulates the sum of those paths' quantities — this is the single
most common place to go wrong, and the hidden set checks it directly.

If `part` is itself a leaf on that date, the result is `[{"part": part, "qty": 1}]` — a part with no
structure explodes to one of itself, not to nothing.

If the structure contains a cycle effective on that date, return `{"error": "cycle"}` for that query
instead of exploding, and name the parts involved in `cycle_parts`, sorted.

### `where_used`
Return every part that contains `part`, directly or transitively, effective on `date` under
`options`, sorted by part id. The part itself is never included.

### `effective_rev`
Return the revision of `part` effective on `date`, or `null` when none is.

## 4. Engineering change orders

An ECO carries an `effective` date and a list of changes, each one of:

| `op` | meaning |
|---|---|
| `add` | add a BOM line `parent → child` with `qty`, effective from the ECO date, open-ended |
| `remove` | set the existing line's `eff_to` to the day **before** the ECO date |
| `qty` | as `remove` on the old line, plus `add` of the same pair at the new `qty` |

ECOs are applied in ascending `effective` order, ties broken by ECO id, **before any query runs**.
"The day before" means calendar-correct date arithmetic; a change effective `2026-03-01` closes the
old line on `2026-02-28`, and on `2026-03-01` in a leap year it closes on `2026-02-29`.

### `eco_impact`
Given `eco`, return every part that is an ancestor — directly or transitively — of any `parent` or
`child` named in its changes, evaluated on the ECO's own effective date with the query's `options`,
sorted by part id. Include the named parents themselves; do not include named children unless they
are also ancestors of something else in the set.

## 5. Output

```json
{"results": [{"query": 0, "kind": "explode", "leaves": [{"part": "R1", "qty": 6}]},
             {"query": 1, "kind": "where_used", "parts": ["P100"]},
             {"query": 2, "kind": "effective_rev", "rev": "B"},
             {"query": 3, "kind": "eco_impact", "parts": ["P100", "S200"]}]}
```

Results appear in query order, each carrying its `kind` and the field named above.

## 6. What is graded

| check | tolerance |
|---|---|
| `explode` | none — exact leaf set and exact integer quantities |
| `where_used` | none — exact set |
| `effective_rev` | none — exact revision or null |
| `eco_impact` | none — exact set |
| `cycle_detection` | none — the right queries error, with the right part set |

## 7. Rules

* Python 3.12 with NumPy and pytest. Nothing else is installed and nothing may be installed. In
  particular no `networkx`, `pandas`, `scipy`, `sqlalchemy`, `python-dateutil`, `arrow`, `pendulum`.
  Date arithmetic is yours to get right; the standard library's `datetime` is available.
* The hidden set includes: a leaf reachable by two paths whose quantities must sum, a line that
  expires the day before the query date, an ECO closing a line on the last day of February in a leap
  year, a variant option that switches between two alternative children, a part whose revision has
  lapsed so `effective_rev` is null, and a cycle that is effective only under one option set.
