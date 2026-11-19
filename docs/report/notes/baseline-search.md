# Baseline: what Odoo's own shop search misses (Task 2.5)

Notes for the "problem" section of the report. Every number here comes from the generated table
`results/summary/baseline-search.md`, run `baseline-search-20261115T022019Z` of `uv run shop eval baseline-search`
at commit `5bb9e2f`, on the shop database in the state of snapshot `baseline-catalog` (19,869 products, Task 2.4b).
If the table and these notes ever disagree, the table is right and these notes must be updated.

## How Odoo 19's shop search works

Read in the Odoo 19.0 source (`.odoo-src/odoo/addons`):

- **Every word must match.** The query is split on spaces; each word must appear, as a substring (`ilike`), in the
  product name, its internal reference, its plain description or its HTML description
  (`website/models/website.py::_search_build_domain`, `website_sale/controllers/main.py::_get_shop_domain`,
  `product_template.py::_get_website_sale_search_fields`). One word that the product's text does not contain, and the
  product is not shown.
- **No word forms, no synonyms, no brand field.** Matching is literal: "shoe" finds "shoes" (substring) but
  "batteries" never finds "battery"; "trainers" never finds "sneaker". The brand our module adds is not among the
  searched fields.
- **One fallback.** When nothing matches, Odoo looks for one similar word by trigram similarity and shows its
  results instead ("No results found for X. Showing results for Y", `website.py::_search_with_fuzzy`). It helps a
  one-word typo; it does not repair a word inside a longer query.
- **No relevance ranking.** Results are sorted by the shop's default order (`website_sale/controllers/main.py::
  _get_search_order`), not by how well they match: an exact product can sit anywhere among the results.

## Method

- Each query is sent to the real shop page `/shop?search=...` as an anonymous shopper (the protocol's `http` mode).
  From the page: the number of results, the word Odoo used instead (if any) and the products on page 1 (20).
- **Dev data only**: the 300 dev queries with their ESCI "Exact" products, and 20 hand-picked queries taken from
  dev queries or built from the names of dev products (`docs/report/notes/baseline-queries.toml`). The script
  refuses any test query or test-judged product, so the reported test set stays unseen (protocol §3).
- Each hand-picked query has a **control**: the same query without the problem under study (spelling fixed,
  singular, no brand word, no negation). When the query fails and the control finds the product, the failure is
  caused by that problem, not by a missing product.
- **Selection.** The 20 queries were chosen *after* measuring all 300 dev queries, to show each kind of failure
  clearly. They are illustrations, not a sample; how often failures happen is given by the 300-query measurement.

## What fails

**Typos.** "theottle cable", "goodthreada cardigan wool" and "mazada 5 drain plug" are real shopper queries (one
wrong letter each) and find nothing; corrected, they find the wanted product at rank 1–3. The fallback works only
for a one-word query: "squritle" is shown the results for "squirtle".

**Vocabulary.** The shopper's word is not the seller's: "moomoos for women" (the product says "Muu Muu"),
"skechers boys dyna-lite trainers" (it says "sneaker"), "hanes ... hooded sweatshirt" (it says "hoodie") find
nothing; "cellphone bike holder" finds other products, and only "cell phone" finds the right one (far down page 1).

**Singular and plural.** "royal blue bedspreads", "birthday candles sparklers", "koenders windmill parts" (real
queries) and "husqvarna dual knives" find nothing; in the singular each finds the product at rank 1.

**Brand names.** When the brand is only in the brand field (not in the name or description), adding it breaks the
search: "nintendo pokemon channel", "amscan voice changer" and "bantam tin can sailors" find nothing, while the same
query without the brand finds the product at rank 1–2.

**Long queries and negations.** The word "without" (or "not") must itself be in the product text, so "blood sugar
monitor without finger pricks", "women's sweatshirts without hoods", "110 laptop charger cable without brick" and
"+black +cardboard not foam" find nothing; without the negation, three of them find the product.

**How often.** Over all 300 dev queries, 73 (24 %) show no result at all, although every product they are looking
for is in the shop; Odoo's fallback changed the query only twice. The share of searches with no result grows with
length: 15 % for 1–2 words, 23 % for 3–4 words, 33 % for 5 words or more, and 46 % (11 of 24) for queries with a
negation word.

**Caution about the 63 %.** 188 dev queries (63 %) show an exact product on page 1. This flatters Odoo: our catalog
holds only the products judged for the evaluation queries, so a typical search returns few results (median 4),
and with few results the right one is often on page 1 even without relevance ranking. In a real shop with many
more similar products, the lack of ranking would cost more.

## What it means for the project

| Failure | Where the project addresses it |
|---|---|
| No result for a typo | Elasticsearch fuzzy matching (FR2, Task 3.5); test-typo set in the evaluation |
| Different word for the same product | Synonym management (FR2, Task 3.6); semantic search if built (FR13) |
| Singular / plural | Stemming in the product index analyzers (Task 3.1, 3.5) |
| Brand words | Brand indexed and boosted (Task 3.1) |
| Long and negation queries | Relevance scoring instead of "every word must match" (Task 3.3, 3.5) |
| No relevance order | BM25 ranking with tuned boosts (Task 3.5), measured by NDCG@10 (protocol §6) |
| Searches that find nothing | Recorded as lost demand: the zero-result signal (protocol §5.1, M6) |

## Screenshots to take (supervisor, browser, shop at http://127.0.0.1:8069)

1. `/shop?search=theottle cable` — no results; then `/shop?search=throttle cable` — results (typo).
2. `/shop?search=squritle` — the "Showing results for 'squirtle'" message (the fallback that works).
3. `/shop?search=royal blue bedspreads` and `/shop?search=royal blue bedspread` (plural).
4. `/shop?search=skechers boys dyna-lite trainers` and `... sneaker` (vocabulary).
5. `/shop?search=nintendo pokemon channel`, then the product "Pokemon Channel" in the backend with its Brand field
   "Nintendo" (brand not searched).
6. `/shop?search=women's sweatshirts without hoods` — no results (negation).

## Limits

- Hand-picked examples were chosen after the measurement (see Method); the 300-query rates are the evidence of
  frequency.
- English queries only (ESCI `us`); one Odoo version (19.0, image `19.0-20261015`); default shop settings (sort
  order, 20 products per page).
- "Exact" products come from Amazon's judges (ESCI); a query can have several, and finding any one counts.
