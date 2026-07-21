# Value-shape veto B1 contract

## Purpose

B1 is a development-only safety A/B placed after the frozen exact-extractive assembler. It tests whether an obviously missing answer value shape can reduce false-full answers without reducing the frozen 73 grounded answers.

It is a one-way veto:

- required typed shape absent from every cited span: `supported_exact -> unsupported`
- required shape present: `not disproven`; this does **not** establish entailment or semantic support
- no high-precision typed contract: preserve the frozen decision

## Typed shapes

The input is the planner's normalized `relation` and `value_type`, not raw-question intent keywords. The conservative contract covers percentage/rate, duration, explicit calendar date, clock/datetime, price/cost, and count/limit. Text, boolean, condition, list, place, and ambiguous amount/date requirements are not vetoed.

Calendar dates and clocks are masked before duration/count matching. Thus a timestamp such as `2026-07-16 16:30` cannot satisfy a percentage, duration, or count requirement merely because it contains digits.

Prices may be paid in currency or in item quantities, so `cost_value` accepts either a currency expression or a quantified resource. This prevents a false veto for DNF costs such as souls/crystals counted with `개`.

## Frozen A/B inputs and gate

The A/B joins the frozen 95-case planner enumeration, assembler spans, router-backbone score cases, 63 adaptive dev questions, 32 downgraded canary questions, and canonical chunks. Gold IDs are used only for scoring and are unavailable to the veto.

All checks must pass:

- Arm0 reproduces grounded `73/82` and false-full `9/82`
- ArmB1 grounded is at least `73/82`
- ArmB1 false-full is below `9/82`
- grounded-to-non-grounded regression is zero
- new false-partial is zero
- reject `11/11`, realtime safe-abstain `2/2`, and realtime static exposure `0` remain unchanged

Passing means only that B2 selective retrieval expansion may be evaluated next. It does not promote B1 into runtime or canonical behavior.

## Explicit exclusions

Search, source routing, planner enumeration, reranker selection, assembler segment selection, model inference, training, and canonical/runtime promotion are unchanged. Wrong values with the correct shape (for example, the wrong duration) and text/relation errors are outside B1's capability.
