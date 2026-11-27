# Relevance tuning experiments (Task 3.5, FR2–FR3)

Pre-registered on 2026-11-27, **before any experiment ran** (commit of this file and of stage 1 in
`tools/shoptools/eval/tuning.toml`). Plan accepted by the supervisor the same day ("go as the recommendations",
decisions D1–D5). Dev data only: the test sets stay untouched until the freeze (protocol §3, §8).

This file holds the method, the hypotheses and the interpretation. **It holds no numbers**: every number is in
the generated table `results/summary/tuning-dev.md` (written by `uv run shop eval tune`, from run folders
`results/tune-<variant>-<time>/`), so nothing here can drift from a recorded run.

## What is tuned

The `es_tuned` query of the module (`addons/website_sale_lost_demand/services/query_builder.py`), described by a
`TunedConfig`: fields and weights, `multi_match` type, typo tolerance (`fuzziness`, `prefix_length`),
`tie_breaker`, how many query words must match (`minimum_should_match`), a phrase bonus on the name, an exact
internal-reference match, and the stock rule of `es_tuned_stock`. The starting point is `TUNED_V0` (Task 3.3).
`es_plain` is not tuned: it represents Elasticsearch out of the box. Synonyms come with Task 3.6 (the set is
empty during these experiments).

## How one experiment is measured

`uv run shop eval tune <variant>` runs the variant **and its parent** through Elasticsearch directly, with the
module's own query code (protocol §6.2 `direct` mode), on:

- **dev** — the 300 dev queries with their ESCI judgments;
- **dev-typo** — the same queries with one seeded typo each, made at run time with the protocol's typo model
  (`shoptools/data/typos.py`, seed stream `dev-typos`, words of at least 4 letters; a query without such a word
  stays unchanged), so typo tolerance (FR2) is judged without the test sets (plan D1).

Recorded: NDCG@10 (one shop page of 21, ESCI gains) with a 95 % bootstrap interval; the paired difference
variant − parent with its interval and randomization p; the difference on each half of dev (odd and even query
ids); queries with no result; mean hits per query (capped at 1,000: the weak tail of Task 3.3); the share of
in-stock products in the top 10; Elasticsearch's `took` p95; and reference@1 (50 seeded products searched by
their internal reference, stream `ref-check`).

## The decision rule (computed by `tuning.decide`, never chosen by hand)

Stages 1 and 2 (plan D2), with Δ = variant − parent mean NDCG@10:

1. **Drop** if Δ dev < −0.005, or if Δ dev-typo < −0.005 (unless the goal is typos): nothing may cost more
   than 0.005, and typo tolerance (FR2) is protected.
2. **Keep** if Δ dev ≥ +0.005 and Δ is not negative on either half of dev (a gain that holds on both halves,
   not one carried by a few queries).
3. **Keep** if the variant meets its stated goal within the limits of 1: `typo` — Δ dev-typo ≥ +0.005;
   `tail` — mean hits down by at least 25 %; `reference` — reference@1 reaches 90 % from below.
4. Otherwise **drop**.

Stage 3, the stock rule (plan D4): rule (b) "boosted" is only a **candidate** if it gains at least +0.02 on dev
over rule (a) "tiered" with at least 95 % in-stock products in the top 10; otherwise rule (a) stays. Either way
the supervisor decides; by the protocol (04 §6) rule (a) is the default.

Budget: at most **15** variants (plan D3); a re-run of the same variant (after a crash) does not count. The
final `uv run shop eval ndcg --engine all --mode both` run of the chosen configuration is not an experiment.

Threats, said before the results: 300 queries cannot separate effects of a few thousandths (the intervals will
show it); the kept changes are chosen on dev, so dev numbers of the result are optimistic — the honest number is
the test-set run after the freeze (Task 8.2); experiments interact, which is why stage 2 measures the combination
as one variant.

## Stage 1 — one change at a time, each against v0

| Variant | Change | Goal | Hypothesis |
|---|---|---|---|
| `e01-exact-words` | typo tolerance off | none | near-miss words add noise on dev, which has few typos; expected to lose on dev-typo |
| `e02-prefix-0` | first letter may be wrong too | typo | finds first-letter typos, which the typo model makes |
| `e03-prefix-2` | first two letters exact | none | fewer accidental near-miss matches |
| `e04-most-fields` | sum of all fields' scores | none | rewards products whose name, brand and description all match |
| `e05-tie-breaker` | best field + 30 % of the others | none | a middle way between best_fields and most_fields |
| `e06-cross-fields` | one field across name, brand, description (no typo tolerance: Elasticsearch refuses it) | none | words may match in different fields |
| `e07-most-words` | all of 1–2 words, 75 % beyond (`2<75%`) | tail | removes the long tail of weak matches (Task 3.3 finding) |
| `e08-name-phrase` | bonus when the words appear together in the name | none | lifts exact products |
| `e09-less-description` | description weight 0.5 | none | long descriptions cause off-topic matches |
| `e10-name-exact-words` | bonus for the name's unstemmed words | none | favours the shopper's exact word form |
| `e11-reference` | exact, case-insensitive internal-reference match | reference | closes a gap with Odoo's own search at no cost |

## Stage 2 — the combination (defined after stage 1, by this rule)

`c01-combined`: v0 with every change kept in stage 1. Two kept changes that cannot go together (for example
`cross_fields` with typo tolerance, or two field lists) are resolved by keeping the one with the larger Δ dev;
two field lists are merged when they change different fields. The combination is measured against v0 like any
variant and must pass the same rule; if it fails, the best single kept change is measured as the alternative
(one more run, within the budget).

## Stage 3 — the stock rule (defined after stage 2)

On the chosen stage-2 configuration with engine `es_tuned_stock`: rule (b) with in-stock scores multiplied by
1.2 (`s01`) and by 2.0 (`s02`), each against rule (a). Multiplying keeps the rule independent of the score scale,
which varies by query.

## Results and interpretation (2026-11-27)

All numbers: `results/summary/tuning-dev.md`, generated from the 14 run folders (11 + 1 + 2 of the budget of
15; every run from a clean commit: stage 1 at `6d6c3c4`, stage 2 at `acc8e29`, stage 3 at `0e59ad4`). The stage 2
and 3 variants were added to `tuning.toml` after the stage before them, exactly as defined above.

**Stage 1.** Two changes passed the rule: the **tie-breaker** (a gain on dev that holds on both halves and whose
interval excludes zero) and the **internal-reference match** (its goal met: every sampled product found first by
its reference, with identical dev rankings). Turning typo tolerance off, or `cross_fields` (which requires it off),
confirmed the hypothesis of `e01`: a large loss on the typo set — typo tolerance is what FR2 is about. Letting the
first letter be wrong lost on dev; two exact first letters lost on the typo set. **"Most words must match"**
(`e07`) did what Task 3.3 needed — it cut the weak tail of matches by a large factor — but lost on the typo set,
because a typo can make a required word miss; the rule protects typos, so it was dropped and the weak tail stays
an open point. `most_fields` lost on dev; the phrase bonus and a lighter description changed little. The unstemmed
name (`name.std`) changed nothing at all: with `best_fields` the higher-weighted stemmed name always wins, so a
lower-weighted copy of the same field never decides the score — a lesson about `best_fields`, not about stemming.

**Stage 2.** The combination of the two kept changes (`c01-combined`) passed the rule against v0, with the same
gain as the tie-breaker alone (the reference match does not change the rankings of word queries). It becomes
`TUNED_V1` (ADR-020).

**Stage 3.** On `TUNED_V1`, rule (b) with in-stock scores ×1.2 gained clearly over rule (a), but its top 10 held
slightly fewer in-stock products than the pre-registered 95 % (the table shows two decimals because the margin is
that small); ×2.0 kept almost every top-10 product in stock but gained too little. By the rule, **rule (a) stays**.
Rule (b) ×1.2 is the supervisor's alternative: about half the relevance cost of in-stock first, at the price of a
few sold-out products in the top 10.

**What this does and does not show.** The tuned query is better than v0 on the dev queries, with an interval that
excludes zero — a modest gain. The kept changes were chosen on these queries, so the dev gain is optimistic; the
reported comparison of `odoo`, `es_plain` and `es_tuned` is the test-set run after the freeze (Task 8.2). Negative
results are kept in the table on purpose.

## Task 3.6 — the starting synonym list (pre-registered 2026-11-27, before the measurement)

The list (`addons/website_sale_lost_demand/data/lost_demand_synonym_data.xml`, 20 rules) is general shop
vocabulary written without looking at the dev or test queries (protocol §3). Ambiguous words are one-way.
Each term is sent with its simple singular or plural form (the search analyzer applies synonyms before stemming;
see `services/synonyms.py`). The shop's query is `TUNED_V2` = `TUNED_V1` + the literal-word bonus (products
matching the typed words rank before synonym-only matches); with an empty synonyms set it gives the same page 1
as `TUNED_V1` on all 300 dev and 300 dev-typo queries, for both tuned engines (checked 2026-11-27 before this
section was written).

Measurement: `uv run shop eval ndcg --mode direct --engine es_tuned,es_tuned_stock`, on `--set dev` and
`--set dev-typo`, once with the empty set (before), then after the list is loaded and sent, with
`--compare-to <before run>` (paired difference, same queries; the runs are minutes apart, so only the synonyms
differ). **Rule:** the list is kept if `es_tuned` loses no more than 0.005 NDCG@10 on dev and on dev-typo;
otherwise it is reported and the supervisor decides. This is not a tuning experiment (no keep/drop of rules
one by one, the Task 3.5 budget is not used); the list's real effect is reported on the test set after the
freeze (Task 8.2), including the vocabulary-mismatch subset (protocol §6.4).

**Result (2026-11-27).** Before: runs `ndcg-dev-direct-20261127T045354Z` and `ndcg-dev-typo-direct-20261127T045452Z`
(empty set, commit `1a43662`); after loading and sending the 20 rules: runs `ndcg-dev-direct-20261127T045735Z` and
`ndcg-dev-typo-direct-20261127T045843Z`, each compared with its "before" run. The numbers are in the comparison
sections of `results/summary/ndcg-dev-direct.md` and `results/summary/ndcg-dev-typo-direct.md`: on both sets the
change of `es_tuned` is far inside the pre-registered limit, so **the list is kept**. As expected for general
vocabulary, few dev queries contain a rule's words; the list's effect is for shoppers who use these words, and
the vocabulary-mismatch subset of the test set (Task 8.2) will measure it on real queries.
