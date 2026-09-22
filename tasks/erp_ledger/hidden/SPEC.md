# erpcore — the transactional core of an ERP system

You are building the engine that sits under an ERP system of the SAP S/4HANA class: a double-entry
general ledger, perpetual inventory with valuation, and material requirements planning. There is no
UI and no database — the engine reads a scenario, applies every business document in order, and
reports the resulting books.

Everything here is **exact**. Money is an integer number of minor units (cents, 分). Quantities are
integers of the material's base unit. There is no floating point anywhere in the answer, and no
tolerance in the grading: a single cent that does not balance is a wrong answer, in the same way
that a single misposted document is.

## 1. Entry point

    bash run_erp.sh <scenario.json> <out.json>

Must sit at the workspace root, exit non-zero on error, and use an explicit interpreter in the
shebang. It is invoked as `bash run_erp.sh ...`, so the file must be a **shell script**, not a
Python file with a `.sh` name.

It is invoked with an **arbitrary working directory** — not your workspace — and both arguments are
absolute paths. Resolve your own files relative to the script's own location (for example with
`$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)`), never relative to `$PWD`.

## 2. Input: scenario.json

```json
{
  "name": "s07",
  "currency": "CNY",
  "fx": {"USD": {"2026-01": 712340, "2026-02": 709880}},
  "accounts": [
    {"id": "1001", "name": "Cash",              "type": "asset"},
    {"id": "1401", "name": "Inventory",         "type": "asset"},
    {"id": "2101", "name": "Accounts Payable",  "type": "liability"},
    {"id": "4001", "name": "Revenue",           "type": "income"},
    {"id": "5001", "name": "COGS",              "type": "expense"}
  ],
  "materials": [
    {"id": "M100", "name": "widget", "lead_time": 3, "lot_size": 50, "safety_stock": 20,
     "bom": [{"component": "M200", "qty": 2}, {"component": "M300", "qty": 1}]}
  ],
  "opening": {
    "accounts": {"1001": 50000000},
    "stock": [{"material": "M200", "qty": 100, "unit_cost": 1250}]
  },
  "documents": [ ...applied strictly in array order... ],
  "mrp": {"horizon": 30, "demand": [{"material": "M100", "qty": 80, "day": 12}]}
}
```

`fx` gives the rate as minor-units-of-`currency` per 1 whole unit of the foreign currency, per
period. The amounts on an `fx_journal` line are in **whole units** of `fx_currency`, so the
conversion is a plain multiplication with no scaling factor and no rounding:

    booked_minor_units = line_amount * fx[fx_currency][period]

For example, a line of `15000` USD at a rate of `712340` books `10685100000` minor units of CNY.
`type` is one of `asset`, `liability`, `equity`, `income`, `expense`. Assets and expenses are
debit-normal; liabilities, equity and income are credit-normal.

### Opening balances

`opening.accounts` gives balances in each account's normal direction; `opening.stock` gives the
opening valuation layers. The opening books must balance and must already satisfy the inventory
identity of §3, because the invariants are checked on them before the first document is applied.
Construct them in this order:

1. every account named in `opening.accounts` takes that balance;
2. account `1401` is debited with the opening stock value, `sum(qty * unit_cost)` over
   `opening.stock` — so `opening.accounts` never also names `1401`;
3. account `3999` absorbs whatever imbalance remains, so that total debits equal total credits
   before document one.

`3999` is always declared in `accounts`; it serves both as opening equity here and as the
period-close target in §2.

### Document types

| type | fields | effect |
|---|---|---|
| `journal` | `lines:[{account, debit, credit}]`, `period` | posted as given; must already balance |
| `goods_receipt` | `material, qty, unit_cost, period` | stock in; debit Inventory, credit AP |
| `goods_issue` | `material, qty, period` | stock out at the current valuation; debit COGS, credit Inventory |
| `sale` | `material, qty, price, period` | goods issue **and** debit Cash, credit Revenue |
| `revaluation` | `material, new_unit_cost, period` | adjusts the valuation of stock on hand |
| `fx_journal` | `lines:[...]`, `fx_currency`, `period` | amounts are in `fx_currency`, converted at that period's rate |
| `period_close` | `period` | closes income and expense into equity account `3999` |

## 3. Valuation

Stock is valued by **moving average**, recomputed on every receipt:

    new_avg = (qty_on_hand * old_avg + received_qty * received_cost) / (qty_on_hand + received_qty)

The division truncates toward zero. The rounding remainder must not be discarded: carry it so that
the inventory account balance always equals the sum over materials of `qty_on_hand * unit_cost`
plus the carried remainder. This identity is checked directly.

A goods issue that would drive stock negative is **rejected**: the document is skipped, the books
are left untouched, and the document's id is reported in `rejected`. Rejecting is not an error —
several hidden scenarios test it deliberately.

## 4. MRP

Explode each demand through the BOM, level by level, then for each material and each day compute:

    net = gross_requirement - projected_on_hand + safety_stock

If `net > 0`, raise a planned order for `ceil(net / lot_size) * lot_size` pieces, released
`lead_time` days before the requirement date. A component's gross requirement is driven by its
parents' **planned order release** dates, not by the parents' requirement dates. Cyclic BOMs must
be detected and reported rather than followed.

## 5. Output: out.json

```json
{
  "trial_balance": {"1001": 12345678, "1401": 900000, "...": 0},
  "stock": [{"material": "M200", "qty": 60, "unit_cost": 1250, "value": 75000}],
  "rejected": ["D014", "D021"],
  "planned_orders": [{"material": "M200", "qty": 100, "release_day": 6, "due_day": 9}],
  "bom_cycles": [],
  "equity_after_close": 4210000
}
```

* `trial_balance` — closing balance per account, signed in the account's normal direction, one
  entry for every account in the scenario including untouched ones (value 0).
* `stock` — one entry per material that ever held stock, sorted by material id.
* `planned_orders` — sorted by `(release_day, material)`.
* All integers. No nulls, no floats, no strings holding numbers.

## 6. What is graded

Four things, and only the last of them carries any slack:

1. **Invariants**, checked after *every single document*, not just at the end: total debits equal
   total credits; the inventory account equals the sum of valuation layers plus carried remainder;
   no stock quantity is negative; every posting references a declared account.
2. **Trial balance** — every account, exact to the minor unit.
3. **MRP plan** — the planned order set, exact: same orders, same quantities, same days.
4. **Rejection set and BOM cycle detection** — informational if it differs only in ordering.

A violated invariant is a proof that the books are wrong, so it is graded on every document of
every scenario. There is no partial credit for "nearly balanced".

## 7. Rules

* Python 3.12 with NumPy and pytest. Nothing else is installed and nothing may be installed.
* Use integers. `Decimal` is available in the standard library if you prefer it for intermediate
  work, but every value you output must be a plain `int`.
* The hidden set includes: multi-currency journals across a rate change, a period close followed by
  further postings, a revaluation of partially issued stock, an issue that must be rejected, a
  moving average whose division does not divide evenly, a three-level BOM with a shared component,
  and a cyclic BOM.
