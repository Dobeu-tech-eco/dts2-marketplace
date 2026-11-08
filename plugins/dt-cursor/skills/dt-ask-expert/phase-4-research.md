> Cursor edition: run scripts/dt_gate.py from this plugin for every gate. Do not read tokens or credential files. Do not merge, broadcast, install hooks, or spend a provider API. Carry out file work with Read, Edit, Grep, Glob, and git.

# ask-expert - phase 4, research

Two sizes. Save everything under `.harness/ask-expert/<repo>/research/`.

## 1. Light market snapshot (always, for a money or template goal)
Three sourced numbers about the market the project would sell into (for example size, a typical price, the count of paying competitors) and the template price range: what comparable templates or starter kits sell for. One worker, a handful of searches. Skip it for a passion or learning goal unless the template path needs a price, and then run only the template price.

## 2. Full research team (only when the head of council answered RESEARCH)
Dispatch five Sonnet workers in parallel, one message, each with the `## Research brief` and the code facts. The frontier model writes the synthesis from their reports.

| Seat | Method | Skills used when installed |
|---|---|---|
| Market sizer | Total, serviceable and obtainable market. Build bottom-up (customers times price) and cross-check top-down. A gap of more than 2x between the two is flagged. | startup-business-analyst `market-sizing-analysis`, `market-opportunity` |
| Competitor analyst | Direct and indirect competitors and substitutes. Pricing pages, funding and revenue (SEC filings are exact; funding databases give estimates). | marketing-skills `competitor-profiling`, `competitor-alternatives`; `competitive-landscape` |
| Money model | Pricing, unit economics (lifetime value, cost to win a customer, payback) and the effort to a first dollar. | marketing-skills `pricing-strategy`; `startup-financial-modeling` |
| Template market | Listings and prices on Gumroad, ThemeForest, Vercel templates, Webflow and Framer marketplaces and similar, sales where shown, and the cost of preparing the repo for sale. | `product-marketing-context` |
| Fact checker | Checks every number in the other reports. | none |

The skills are optional. The method above is enough on its own; the gtm skill's marketing-skills install is reused when present, and nothing is installed just for this.

## 3. Rules for every number
- Label it `sourced`, `estimated` or `assumed`.
- A sourced number carries a date and a link. It needs two independent sources, or it is downgraded to `estimated`.
- GitHub stars are a weak signal. Never use them as a market size or as evidence of paying demand.
- An assumed number says what it assumes. If a figure matters to the verdict and is only assumed, say so in "What would change the answer".

## 4. The study
Write a short venture-style study: market, competition, moat, traction, unit economics, why now, risks, and a thesis. Keep it plain; this feeds the memo and is not itself the deliverable. Return to `phase-3-panel.md` section 4 for the head's final decision, or to `phase-5-report.md` when the snapshot was all that was needed.
