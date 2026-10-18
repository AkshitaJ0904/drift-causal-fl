# Final Hostile Validation — Candidate #1
## Drift-Informative Client Participation in Federated Learning

*Third and final adversarial pass, conducted 2026-09-09. Six additional live literature agents ran across this round (on top of the five from Phase I and three from the second audit — fourteen total live research passes against this single idea across three rounds). Nothing below is softened. This document supersedes the "YELLOW" verdict from the second audit wherever they conflict.*

---

## PART 1 — Killing the term "MNAR"

**1A. Is this actually MNAR under standard missing-data theory?**

Yes, but the cleanest lineage is not bare Rubin (1976) cross-sectional taxonomy — it's the **Diggle-Kenward (1994) selection model for informative dropout in longitudinal data**, a biostatistics framework built exactly for this structure: a repeated-measures outcome `Y_t`, where the probability of dropping out at time `t` depends on the value `Y_t` *would have taken*, whether or not it's observed. FL participation over rounds is a panel/longitudinal missing-data problem (repeated measurements per client, over rounds), not a single cross-sectional missing-data problem — Rubin's MCAR/MAR/MNAR was built for the latter. Anchor the formal citation to Diggle & Kenward and the broader "non-ignorable/informative dropout" literature it spawned; keep "MNAR" only as a parenthetical gloss, since it's still technically correct and recognizable but invites exactly the generic-textbook pushback this audit round produced.

**1B. What exactly is the missing variable?**

Most defensible formulation: **`Y_i,t` = the client's local update/statistic at round `t`** (the actual quantity FL aggregation needs — literally what's missing from the server's average when `R_i,t=0`). Drift magnitude `D_i,t` is best framed as an **auxiliary/selection variable** — a scalar summary of the client's evolving local state that (a) partially explains why `Y_i,t` would be informative or anomalous, and (b) governs the missingness mechanism. This is structurally identical to Diggle-Kenward's own setup, and to Heckman (1979) sample selection (wage `Y` observed only if employed `R=1`; a "reservation wage" auxiliary state drives `R`). Don't conflate "drift" with "the missing outcome" — it's the selection-equation variable, not the outcome itself. State this three-variable structure (`Y`, `D`, `R`) explicitly in any paper; it preempts the single sharpest incoming objection ("what exactly is missing?").

**1C. Does `D_i,t` being observable-when-online/unavailable-when-offline make this legitimate MNAR?**

Yes — this is precisely the standard "outcome-dependent missingness via a partially-observed auxiliary variable" structure from Diggle-Kenward and Heckman selection models. It is legitimate, provided the paper is careful never to claim `D_i,t` is *eternally* unobservable (it isn't — it's observable exactly for the participating rounds, which is what makes identification possible at all via a proxy from similar/nearby clients). This precision is load-bearing, not decorative.

**1D. Does concept drift itself qualify as "the missing outcome/state" required by Rubin-style MNAR?**

Not as the primary missing outcome (that's the update `Y_i,t`) — see 1B. Drift is the selection/auxiliary variable. Stating this distinction precisely is what separates a defensible formulation from a vague, easily-attacked one.

**1E. Better terminology?**

Recommend: lead with **"drift-causal informative dropout"** or **"non-ignorable dropout driven by temporal concept drift"** in prose (plain-English + precise), cite the Diggle-Kenward/Heckman lineage formally, and use "MNAR" only parenthetically. Reject "informative censoring" (implies right-censoring/event-time structure, a different data type). "Endogenous participation" (econometrics) is a legitimate secondary gloss, especially since Heckman-selection framing is directly relevant.

**1F. Search for alternative terminology covering the same phenomenon — RESULT: one real hit found, and it changes the terminology claim materially.**

A relaunched hostile search across ~25 phrasings (data-dependent participation, endogenous availability, loss/gradient/update-dependent participation, anomaly-dependent participation, state-dependent dropout, Diggle-Kenward + FL, Heckman + FL, etc.) found:

> **FLOSS: Federated Learning with Opt-Out and Straggler Support** (Goetze, Felten, Albrecht, Bhattacharya; [arXiv:2507.23115](https://arxiv.org/abs/2507.23115); **PACMI '25 workshop, ACM, Seoul, Oct 2025** — verified via full-text fetch). This paper **explicitly uses "MNAR" terminology in an FL context**, with a formal missingness DAG (`X→R`, `Y→R`) and an IPW correction with an oracle-vs-estimated propensity ablation. Their mechanism: opt-out probability depends on client (dis)satisfaction, itself a function of the model's current fit to the client's own data — i.e., genuinely state-dependent, genuinely MNAR by their own formalization.

**This kills the terminology-novelty claim outright.** "We are the first to formalize MNAR client participation in FL" is now **false** and must not be claimed. It does **not** kill the underlying mechanism claim: FLOSS's driver is static satisfaction/model-quality, never framed as temporal concept drift, and FLOSS runs no matched-marginal-rate benchmark. The correct move is citing FLOSS explicitly as the closest prior "MNAR-in-FL" paper and differentiating precisely on (a) drift as the specific temporal, evolving state variable (vs. static satisfaction) and (b) the controlled matched-rate benchmark design (which FLOSS does not attempt). This is a real, material correction from the second audit, which missed FLOSS entirely.

---

## PART 2 — Killing the central research gap

Full novelty-threat table across three rounds of searching (25+ phrasings each round, ~15 papers deep-audited at the methodology level total):

| Paper | Exact mechanism | Depends on current local state? | Depends on drift specifically? | MNAR/informative? | Correction? | Kills our gap? |
|---|---|---|---|---|---|---|
| **FLOSS** (2507.23115, PACMI '25) | Opt-out driven by satisfaction = f(current model fit to own data) | Yes | **No** — static quality, not temporal drift | Yes, explicit MNAR formalization | Yes — IPW | **Partially** — kills the terminology-novelty claim, does not kill the drift-causal mechanism or matched-rate-benchmark claims |
| FedIPW / Who Trains Matters (2604.26604) | Two-stage selection on observed covariates only | No — explicit Mean Ignorability | No | No — explicitly ignorable/MAR-type | Yes — IPW | No — the MAR analogue of our problem; useful ammunition, not a threat |
| CA-Fed (2301.04632, INFOCOM 2023, peer-reviewed) | Availability correlated with **static** per-client data heterogeneity | Partial — correlated with a fixed attribute, not an evolving state | No — no temporal drift framing | No | Yes — CA-Fed reweighting | No — correlation with a *fixed* label distribution, not a *dynamic* drift-causing-its-own-reporting mechanism |
| Debiasing FL w/ Correlated Participation (2410.01209) | Markov-chain, purely temporal cooldown (min re-participation gap) | No — scheduling artifact | No | No | Yes | No — different phenomenon entirely |
| CAFE — Drift-Aware FL, Causal Perspective (2503.09116) | **Reversed causal arrow**: participation frequency → drift in global model | No | Drift is the effect, not the cause | No | No | No — opposite causal direction |
| Adaption via Selection (ESOCC 2025, Springer, peer-reviewed) | **Server-side** active selection biased toward high-loss clients to counter drift | N/A — active intervention, not passive dropout | Yes, drift-adjacent, but as a control lever | No | It IS the intervention | No — different problem class (active control vs. uncontrolled self-selection) |
| HeteRo-Select (2508.06692) | Server-side informativeness-based selection | No — server-side, not client self-selection | No | No | N/A | No |
| FL-FDMS (2205.13222) | Friend-substitution imputation for exogenous dropout | No — dropout exogenous in their framing | No | No | Yes — proxy substitution | No, but its *fix* is what DCPA copied (§ prior audit round) |
| Diggle-Kenward / Heckman × FL | No FL adaptation found anywhere | — | — | The classical MNAR/selection frameworks, confirmed un-ported to FL | — | No — confirms an *opportunity*, not a gap-closer |

**Verdict: GREEN for the narrowed drift-causal mechanism and the matched-rate benchmark design; the general "MNAR-in-FL" terminology claim is now explicitly NOT ours to make (FLOSS precedes it).** Every dropout mechanism found across ~15 methodology-audited papers and three full search rounds is either exogenous, statically-correlated, causally-reversed, or actively-controlled by the server — none is a client's own temporally-evolving drift state causing its own passive dropout.

---

## PART 3 — The precise, non-overclaiming FedIPW boundary statement

A full mathematical read of FedIPW (arXiv:2604.26604) — not the abstract, the actual propositions and proofs:

1. **Selection model:** two-stage — enrollment `π_i^enroll = P(E_i=1|Z_i)`, participation `π_{i,r}^part = P(A_{i,r}=1|E_i=1,Z_i,X_{i,r})`, where `Z_i` (device/OS/region) and `X_{i,r}` (battery, network, local time) are treated as exogenous and knowable even for non-participating rounds.
2. **Mean Ignorability, precisely:** `E[Δ_{i,r}|Z_i,X_{i,r},A_{i,r}=1] = E[Δ_{i,r}|Z_i,X_{i,r}]`, plus positivity `p_{i,r}>0`. The paper never names "MAR" or "MNAR" — it uses only "ignorability," borrowed from Rosenbaum-Rubin.
3. **Where it breaks, mathematically:** Proposition 4.1 (oracle unbiasedness) and 4.2 (plug-in consistency) both have Mean Ignorability as load-bearing, not decorative — it's exactly the step that lets `E[Δ_{i,r}·A_{i,r}/p_{i,r}] = E[Δ_{i,r}]` go through. **Corollary 6.2 proves that an omitted selection-relevant factor contributes a non-vanishing term to a provable bias floor** — and an unobserved-current-drift-state driver of participation is structurally identical to their "omitted enrollment factor" case. This is a proof-level result, not an inference from silence.

**The precise, defensible statement (use this, not the stronger version):**

> **WRONG (overclaim, do not use):** "IPW is mathematically impossible under MNAR." — False in general; Heckman-type selection models, proxy-augmented propensity models, and IPW with exclusion restrictions all handle various MNAR structures with additional assumptions.
>
> **CORRECT (use this):** "Standard IPW conditioned only on the observed covariate set `(Z_i, X_{i,r})` is provably inconsistent when participation depends on a current local state outside that conditioning set — this follows directly from FedIPW's own Corollary 6.2 treatment of omitted selection factors as structural weighting error, not from a general theorem about MNAR being unfixable. Extending FedIPW to cover a drift-dependent state would require additional structure (a proxy variable, an instrument, or an explicitly parameterized non-ignorable selection equation) that the paper does not supply and, per a fresh 2026 search, no FL paper currently supplies either."

This is now a stronger and more precise citation than the second audit had — grounded in a specific corollary, not a general inference.

---

## PART 4 — Benchmark novelty

Searched explicitly for FL studies comparing dropout mechanisms (exogenous vs. correlated vs. state-dependent) **at a controlled, matched marginal participation rate** — the exact design that isolates informativeness from amount of missingness. **No hit found.** The closest adjacent work (FjORD, Invariant Dropout) uses "dropout" to mean weight/subnet pruning — an unrelated concept. CA-Fed and FLOSS both compare "no missingness" vs. "their specific missingness," never sweeping mechanism at fixed rate. **This specific controlled-ablation design appears genuinely absent from the literature — the benchmark novelty claim survives independently of the mechanism-novelty claim.**

**Additional controls needed beyond matched marginal rate** (the second audit only specified marginal rate; this round adds a real gap):
- **Same per-client missingness autocorrelation/burstiness** where feasible — MNAR mechanistically tends to make the *same* high-drift clients chronically missing round after round, while MCAR spreads absence independently across all clients each round. This is a **second, distinct confound** (chronic vs. intermittent absence pattern) layered on top of "informativeness," and must be reported/discussed explicitly, not silently controlled away — because chronic-vs-intermittent absence is arguably *part of* the phenomenon under study, not noise to eliminate. State this explicitly as a limitation/discussion point rather than pretending it's fully separable.
- Same non-IID severity and same drift severity across mechanism conditions (already specified in the prior round's design).

---

## PART 5 — Attacking the synthetic generation mechanism

`P(R_i,t=0) = σ(α + β·D_i,t)` — attacked point by point:

1. **Is this a meaningful causal/data-generating mechanism, or an arbitrary knob?** Meaningful *as a generative model for simulation*, provided `D_i,t` is defined precisely (see below) and `α` is recalibrated at every `β` to hold marginal rate fixed (already specified). It is a stylized mechanism, not a claim about any specific real system — state this plainly.

2. **Circularity risk (the sharpest new objection this round surfaces):** if `D_i,t` is defined *relative to the current global model* (e.g., local loss increase vs. the current global model, or gradient/update distance from the current global weights — matching how FedDrift itself operationalizes drift), then `D_i,t` is not a purely client-intrinsic quantity — it's partly an artifact of the global model's own trajectory. This creates a feedback loop: global model → `D_i,t` → dropout → aggregation → next global model → next `D_i,t`. **This is a real, non-trivial validity threat**, not fully addressed by the prior round. Fix: run **two distinct `D_i,t` definitions** — (a) model-relative (local loss increase vs. current global model — directly comparable to FedDrift's own drift-detection test, for literature comparability) and (b) **model-independent** (e.g., a fixed-embedding feature-distribution shift computed via a frozen extractor, or a raw label/feature moment-shift relative to the client's own earlier-round baseline — no dependence on the current global model at all). Show the qualitative finding holds under both. This is now a required robustness check, not optional.

3. **Which definition is least vulnerable?** Loss-increase-vs.-global-model is most literature-comparable (matches FedDrift exactly) but carries the circularity risk above. A model-independent distributional-shift measure is cleanest for avoiding circularity but less directly tied to "will this be useful to the global model." Run both; report both.

4. **Is "more high-drift clients missing at matched rate" the phenomenon we want, or a confound?** **It is the phenomenon, not a confound** — that compositional imbalance (*who* is missing, not just *how many*) is exactly what "informativeness of missingness" means. The matched-marginal-rate control isolates informativeness from raw amount; it does not and should not eliminate the compositional effect, which is the manipulation working as intended. (See Part 4 for the *separate*, genuine confound: chronic-vs-intermittent absence pattern, which does need explicit handling.)

---

## PART 6 — The coupling parameter

Recommendation, deliberately not over-engineered:

- **Primary, reported/plotted axis:** realized point-biserial correlation `ρ = corr(D_i,t, 1−R_i,t)`, computed post-hoc from the simulated trace. Standard, interpretable, comparable across mechanism families.
- **Secondary, mechanism-invariant robustness check:** mutual information `I(D;R)`, since correlation alone can match across mechanisms (logistic vs. threshold) while masking real differences in dependence *shape* — a threshold mechanism can share a Pearson `ρ` with a smooth logistic while having a qualitatively different tail-censoring pattern. Report `I(D;R)` at minimum in an appendix to catch this.
- **Do not use:** selection odds ratio or a standardized logistic coefficient as the primary cross-mechanism comparison axis — the logistic coefficient `β` is mechanism-specific (only defined for the logistic family) and not comparable to a threshold or rank mechanism; inventing a more elaborate unified statistic adds jargon without adding real statistical power for this specific need. `β` should still be reported as a methods-section detail (it's what actually generates the logistic condition), just not used as the comparison x-axis.

---

## PART 7 — Killing "MNAR must be worse"

This is the single most important correction from this round. **Directional superiority of MCAR over MNAR is not necessarily true, and asserting it as a hypothesis without qualification is a real vulnerability.** Constructed counterexamples:

- **If high-drift clients' updates are dominated by noise, not signal** (e.g., a genuinely faulty sensor producing garbage during a fault, not just "differently distributed" data), a mechanism that systematically excludes exactly those contributions could act as an *implicit denoiser*, **improving** global model quality relative to MCAR (which would occasionally include the noise).
- **If drift correlates with rare, non-representative one-off events** not present in the eventual test distribution, exclusion could **improve generalization** to the stable "core" population — an overfitting-avoidance effect, not a failure.
- **If the evaluation target is explicitly the "typical"/non-drifted population** (a legitimate scope decision, not a bug), MNAR dropout removing atypical clients is *aligned with the objective*, and no degradation should even be expected — the direction of the effect depends entirely on what the evaluation target population is, which the proposal must state explicitly up front.
- **If proxy correction genuinely recovers most of the missing signal**, MNAR-with-good-correction could match or beat MCAR-with-no-correction — though this compares corrected-vs-uncorrected conditions, not the raw phenomenon.

**Revised, direction-agnostic hypothesis (replaces both the original "superlinear" claim and the second audit's still-directional "MNAR is worse" framing):**

> **H1 (revised):** For a fixed marginal dropout rate, drift-informative dropout produces global-model error and per-client fairness outcomes that are **systematically different** (not necessarily worse) from exogenous (MCAR/MAR) dropout of equal rate, when evaluated against a test distribution that includes drifted clients' data.
>
> **H1a (near-definitional, low-risk, expected true almost by construction):** Performance **on the drifted subpopulation specifically** will be lower under MNAR than under MCAR/MAR at matched rate, since that subpopulation's signal is systematically underrepresented in training.
>
> **H1b (genuinely uncertain, the actual interesting empirical question):** Whether **aggregate/global** performance also degrades depends on whether drift signal is informative or noisy relative to the eventual evaluation target — this is not guaranteed to go in either direction and is the paper's real contribution to test.

This reframing is strictly better science than the version audited previously: it separates the part that's true by construction (H1a) from the part that's a genuine, falsifiable open question (H1b), which directly defuses professor objection #14 ("why should MNAR necessarily hurt performance") — the honest answer is *it doesn't necessarily*, and that ambiguity is exactly what makes this real research rather than a foregone conclusion.

---

## PART 8 — Killing SAPA

A dedicated hostile search for the specific 2026 paper hinted at was successful and materially changes SAPA's status:

> **DFL-AA — "Asynchronous Decentralized Federated Learning over Lossy Wireless Links via Reception- and Age-Aware Aggregation"** ([arXiv:2606.10774](https://arxiv.org/abs/2606.10774), June 2026). Verified via full-text fetch. Aggregation weight: `a_ij(t) = (1/q̂_ij) · exp(−AoI_ij(t)/τ)` — **an inverse-inclusion-probability term multiplied by a staleness-decay term, applied together, in a partial-reception FL setting.** This is mathematically the same skeleton SAPA proposes.

**Precisely how SAPA differs (and how much that difference is worth):**
1. DFL-AA's `q̂_ij` is a **pure empirical/EWMA frequency** of reception success — not a fitted, covariate-dependent selection/propensity model. SAPA's proposed use of a fitted selection model (regressing dropout on last-observed drift signature) is a genuine, if narrow, upgrade.
2. DFL-AA fills missing chunks via **local-fill imputation** — the *receiver's own current model* — not a cross-client "friend"/proxy substitute (FL-FDMS's mechanism). SAPA's proposed cross-client friend-fill is a genuine, if narrow, upgrade.
3. DFL-AA assumes **iid Bernoulli link loss** — not state-dependent/informative — i.e., it explicitly avoids the MNAR-style case SAPA targets.

**Verdict: B — probably novel but narrow, not D.** DFL-AA proves the *general recipe* (propensity-style weight × substitute-discount, combined) already works and has a bias-controllability proof; it just does it with the *simpler* primitives on each axis (empirical frequency instead of fitted model; self-fill instead of friend-fill). SAPA's genuine remaining contribution is narrow: swap in the fitted-model propensity and the cross-client-friend imputation, and — critically — **prove a bias bound for the friend-substitute case analogous to DFL-AA's Theorem 1**, since DFL-AA's proof leans on the imputed value coming from the *same node* (so its bias term never has to account for a systematic distributional gap between a proxy and the true missing value — SAPA's does, and that gap is the actual open mathematical question).

**A hostile reviewer's sharpest available line:** "Why not just compose DFL-AA's propensity weighting with FL-FDMS's friend substitution directly, without inventing a new name?" **This must be pre-empted, not avoided.** SAPA is only defensible as a contribution if the proposal (a) derives the bias bound for the cross-client-proxy case explicitly, and (b) benchmarks against exactly this "naive composition" ablation (DFL-AA-style empirical-frequency propensity + FL-FDMS-style friend-fill, with no fitted model) to show the fitted-selection-model addition earns its complexity. If the student cannot complete the bias-bound proof, **SAPA should be dropped entirely**, not shipped as an unproven heuristic.

---

## PART 9 — Is an algorithm even necessary?

**No — and there is now strong, specific, in-field precedent for a benchmark-only contribution.** A dedicated search for FL (not generic-ML) precedent found five real, mostly peer-reviewed examples of exactly this contribution type:

| Paper | Venue | Contribution type |
|---|---|---|
| FedScale (Lai et al.) | **ICML 2022**, peer-reviewed main track | Real device-availability traces + benchmark; shows existing FL algorithms look "overly optimistic" without realistic system heterogeneity — no new algorithm as the headline |
| FLamby (du Terrail et al.) | **NeurIPS 2022 Datasets & Benchmarks**, peer-reviewed | Seven real cross-silo healthcare splits; shows SOTA behaves inconsistently across them — measurement paper |
| NIID-Bench (Li, Diao, Chen, He) | **ICDE 2022**, peer-reviewed | Systematically varies non-IID partitioning; shows no SOTA method dominates across all partitions — explicitly self-described as an "experimental study" |
| pFL-Bench (Chen et al.) | **NeurIPS 2022 Datasets & Benchmarks**, peer-reviewed | Personalized-FL benchmark across 12+ datasets; shows method rankings shift by scenario |
| FedLLM-Bench (Ye et al.) | **NeurIPS 2024 Datasets & Benchmarks**, peer-reviewed | Real user-partitioned LLM data; shows existing methods validated only on artificial splits |

All five were accepted at strong peer-reviewed venues specifically *because* they exposed an unexamined assumption and showed SOTA rankings/behavior aren't robust to it — establishing that "benchmark + failure characterization, no new algorithm" is a legitimate, not a lesser, FL research trajectory. **Do not treat "no new algorithm = weak project."** This directly supports making the empirical characterization the primary contribution and SAPA a strictly optional stretch goal.

---

## PART 10 — Real-world plausibility, attacked directly

**The malaria/COVID wearable dataset does not survive scrutiny.** A dedicated agent read the full associated paper (npj Digital Medicine, PMC13043753, Kenya cohort, n=300/290 usable, Garmin Vivosmart 5, plus a 3318-participant COVID cohort). Findings:

1. **No engineered "drift" or "coverage" variable exists in the dataset** — coverage must be inferred from raw timestamp gaps; infection state is a binary clinical label attached at the cohort level, not a continuous per-timestamp drift signal.
2. **No quantitative correlation test appears anywhere in the paper.** The evidence is a handful of individual case vignettes (e.g., "Participant 305," "Participant 279") plus one unrelated aggregate statistic (50% coverage, an imputation-performance number for the COVID cohort, not a coverage-vs-infection correlation).
3. **Evidence is pure observational co-occurrence, not correlation or causation** — the strongest sentence in the paper is a single-subject anecdote ("the first anomaly alert coincided with the participant ceasing device use").
4. **The paper's own default explanation for dropout is a direct competing confound**: "sensor non-adherence, battery limitations, and unreliable connectivity — issues especially acute in LMICs," with devices synced by study staff only every 5–7 days (a batch-logistics cadence, not continuous transmission). This confound is never disentangled from the "illness causes dropout" story — it's the paper's own stated default, undermined rather than supported.
5. **Temporal granularity (5–7 day sync batches) is too coarse to compute a real correlation even if a student tried** — the dataset does not let anyone independently verify the phenomenon; it would be taking the paper's anecdotes on faith.

**Verdict: drop this dataset as a "plausibility anchor" entirely, or cite it only as an explicitly-flagged, unverified anecdote — never as evidence.** No better real dataset was found either (FedScale/MobiPerf traces have real availability but no paired data-distribution signal; SWaT/WADI's missingness is attacker-injected spoofing, not natural connectivity loss, and no quantitative missingness-anomaly correlation analysis exists for it). **State plainly in the proposal: no public dataset currently supports a verified real-world drift-dropout correlation claim.** This is a real, stated limitation of the project, not something to paper over.

---

## PART 11 — Execution audit, challenged

The second audit's ~1,200–1,300-run estimate is real but should not be the committed plan for a first pass. Revised:

**Minimum viable experiment (commit to this first):**
- 1 dataset (FEMNIST — best literature comparability, smallest engineering lift)
- 3 mechanisms: MCAR, MAR, MNAR-logistic (drop threshold/rank initially)
- 4 methods: FedAvg, FedIPW, FL-FDMS, FedDrift (drop SCAFFOLD/KPFL/FedProx initially — SCAFFOLD is redundant with FedProx per the earlier audit, KPFL and FedProx are second-priority)
- 6 coupling levels × 3 mechanisms (≈13 cells, MCAR contributes 1) × 4 methods × 5 seeds ≈ **260 runs**. At LEAF-scale (minutes per run, CPU/single-GPU, embarrassingly parallel), this is genuinely completable in **3–4 weeks** of compute, not months — a realistic semester-1 milestone.

**Strong-paper experiment (only after MVP is clean):**
- Add: 2nd dataset (Office-Caltech-10), SCAFFOLD/KPFL, threshold-mechanism robustness check, secondary sweeps (drift severity, non-IID severity — 2-3 strongest methods only, not full factorial), and — only if the MVP shows a clear, real effect worth explaining — the SAPA bias-bound-and-ablation stretch goal (Part 8).
- This brings the total toward the ~1,000-run range, but staged as an *extension* of a working MVP, not a monolithic upfront commitment. **Do not build the full matrix before the MVP result is in hand — if H1b (aggregate degradation) turns out null or reversed, the strong-paper design should pivot around that finding, not around a pre-committed grid.**

---

## PART 12 — Professor attack test (20 objections)

| # | Objection | Severity | Fatal? | Strongest answer |
|---|---|---|---|---|
| 1 | "Isn't this just correlated participation?" | High | No | Correlated-participation papers (2410.01209, CA-Fed) are provably MAR/static; ours depends on a temporally-evolving current state |
| 2 | "Why call it MNAR?" | **High (upgraded this round)** | No, if reframed | FLOSS (2507.23115) already used "MNAR" in FL — concede this immediately, cite it, and pivot the novelty claim to the drift-causal + matched-rate-benchmark specifics (Part 1) |
| 3 | "Why is drift the missing variable?" | Medium | No | It isn't — the update `Y_i,t` is the missing variable; drift `D_i,t` is the auxiliary selection variable (Part 1B) |
| 4 | "Why should dropout depend on drift in a real system?" | **High** | No, but must be conceded plainly | No dataset currently proves this (Part 10) — state it as a plausible, motivated, but unverified mechanism, not an established fact |
| 5 | "Aren't you just synthetically creating a problem?" | High | No | The benchmark studies a stylized generative mechanism explicitly, like FedDrift's own synthetic drift injection — legitimate methodology when disclosed as such |
| 6 | "Why isn't this MAR with a sufficiently rich proxy?" | Medium | No | Because the proxy (`D_i,t`) is itself unobserved exactly when needed (offline); a sufficiently rich *observed* proxy would make it MAR by definition, but no such proxy is assumed available |
| 7 | "Why doesn't FedIPW solve it?" | High | No | Corollary 6.2's bias-floor argument, precisely (Part 3) |
| 8 | "Why doesn't FL-FDMS solve it?" | High | No | FL-FDMS's substitution never uses the causal-coupling structure at all — it would behave identically under exogenous or drift-caused dropout |
| 9 | "Isn't SAPA just IPW + friend substitution?" | **Very High** | Partially | Yes, structurally close to DFL-AA's already-published recipe; only defensible with a proven bias bound for the cross-client-proxy case, or should be dropped (Part 8) |
| 10 | "Why do you need an algorithm at all?" | High | No | You don't — the empirical characterization is a complete, precedented contribution on its own (Part 9) |
| 11 | "Why should missing clients be replaced at all?" | Medium | No | Only relevant to the SAPA stretch goal, not the core empirical study, which doesn't impute anything |
| 12 | "Isn't the proxy assumption unjustified?" | Medium | No, if SAPA pursued | It's the standard MNAR-identification move (a proxy from similar/nearby clients) — legitimate but must be stated as an assumption, not a fact |
| 13 | "What happens when no similar client exists?" | High | Partially fatal for that client, not the paper | A real, admitted limitation of any proxy method — measure and report the failure rate explicitly |
| 14 | "Why should MNAR necessarily hurt performance?" | **High** | **No longer applicable — directly resolved** | It doesn't necessarily (Part 7) — this is now the genuine research question (H1b), not an assumed conclusion |
| 15 | "Why is matched dropout rate sufficient [as a control]?" | Medium | No, but must be extended | It isolates amount from informativeness, but a second confound (chronic-vs-intermittent absence pattern) also needs explicit discussion (Part 4) |
| 16 | "Why is your drift metric valid?" | High | No, if both variants tested | Run both a model-relative and a model-independent `D_i,t` definition to defuse the circularity concern (Part 5) |
| 17 | "Why is beta/rho meaningful?" | Medium | No | Report realized correlation `ρ` as primary and mutual information as a mechanism-invariant check (Part 6); don't over-engineer |
| 18 | "Isn't the benchmark artificial?" | Medium | No | Concede the synthetic nature explicitly; state that no real dataset currently validates the mechanism (Part 10) rather than overclaiming |
| 19 | "Why is this publishable?" | High | No | Five real FL precedent papers (Part 9) establish the bar for a benchmark-only contribution |
| 20 | "Why hasn't anyone done it already?" | High | No | Because the field's two relevant threads (drift-adaptive FL and participation-selection-bias FL) developed independently and never combined the causal direction being tested here — confirmed absent across three full search rounds |

**Objection #9 (SAPA) remains the single sharpest unresolved threat.** Objection #2 (MNAR terminology) is newly upgraded to High severity but is fully resolved by the Part 1 reframe. Objections #4 and #18 (real-world grounding) require the project to explicitly concede a real limitation rather than paper over it — this is now non-negotiable given Part 10's finding.

---

## PART 13 — Comparing Candidate #1 against #2 and #3, today

Neither Candidate #2 (risk-differentiated trust calibration) nor Candidate #3 (multi-agent Byzantine robustness) has received this level of hostile scrutiny — they carry only their original Phase-I novelty assessment, untested by adversarial search. **This asymmetry itself is informative**: a novelty claim that has survived three rounds of dedicated hostile search (Candidate #1's narrowed claim) is stronger evidence than an equally-graded claim that has never been attacked (Candidates #2/#3), even if the nominal letter grade (D vs. D vs. C) looks similar on paper.

Scored on the criteria that matter for a 2-semester commitment made today:

| Criterion | #1 (revised) | #2 (trust calibration) | #3 (Byzantine robustness) |
|---|---|---|---|
| Genuine research gap | Confirmed, narrowed, robust to 3 hostile rounds | Plausible, untested by hostile search | Plausible, but SAC (2605.09076) is unusually close prior art |
| Novelty defensibility | High — survived repeated adversarial search | Unknown — never attacked | Medium-low — differentiation burden already flagged as the highest of the original top 3 |
| IRB dependency | **None** | High — explicit 2–3 semester schedule risk | None |
| Compute cost | Low-medium, CPU/single-GPU | Minimal (API calls) | Medium-high, many LLM API calls across a multi-factor design |
| Baseline availability | Excellent — FedAvg/SCAFFOLD/FedDrift/KPFL/FL-FDMS/FedIPW all public and reproducible | Good, but requires building a novel task battery | Good — SAC, majority vote, leader-based all specified |
| Evaluation clarity | Clear, quantitative, no human-subjects measurement ambiguity | Requires validated "subtly flawed" suggestions and behavioral coding | Clear but many-factor design risks scope creep |
| Publication precedent for the fallback | **Excellent** — 5 real peer-reviewed FL benchmark-only precedents found | Plausible (CHI/FSE precedent exists generally) but not specifically searched | Workshop-tier precedent exists, but SAC crowds the space |
| Scoop risk | Low — searched three times, nothing found | Unknown | **Real** — fast-moving multi-agent-security space, SAC already close |
| Result if the "interesting" part fails | **Still a complete, precedented, publishable paper** (Part 9) | Weaker fallback — a null risk-calibration result is still informative but the study *design itself* depends on IRB clearance succeeding at all | Weaker fallback — if degradation curves don't show the hypothesized strategy effect, the paper leans hard on being "SAC + harder prompts" |

**Verdict: Candidate #1 should remain #1**, specifically *because* of its resilience under adversarial testing and its zero-IRB, low-compute, precedented-fallback profile — not because its underlying idea is more exciting than #2 or #3. If a professor pushes back with "why not #3, it's a hotter topic," the honest answer is that #3's closest prior art (SAC) is uncomfortably close and untested by the same rigor applied here, making its actual risk profile unknown rather than low. If the student specifically wants a human-subjects/HCI project instead, #2 remains a legitimate second choice, but should receive this same three-round hostile-audit treatment before being committed to, not assumed safe on the strength of the original Phase-I pass alone.

---

## PART 14 — FINAL GO/NO-GO DECISION

# YELLOW — COMMIT ONLY AFTER SPECIFIC CHANGES

Not RED: the core empirical mechanism (drift-causal participation, distinct from every prior-art variant found across three hostile search rounds) and the matched-rate benchmark design both survive. Not GREEN: the original framing (DCPA, "superlinear," "MNAR is worse," "we introduce MNAR-in-FL," SAPA-as-given) contains multiple claims that must be corrected or dropped before this is safe to commit to.

**1. Final research title:**
*"When Absence Is Informative: Benchmarking Federated Learning Under Drift-Causal Client Participation"*

**2. Final research question:**
Does client participation that is causally driven by the client's own current, temporally-evolving concept-drift state produce systematically different federated learning outcomes than exogenous dropout of equal marginal rate — and does existing participation-bias correction (FedIPW's ignorable-selection debiasing) remain valid under this regime?

**3. Final research gap (1–2 sentences):**
No existing FL study models client participation as causally driven by the client's own *temporally-evolving* concept-drift state — as opposed to FLOSS's static satisfaction/quality driver, or every other found paper's exogenous/statically-correlated/reversed-causal-direction/actively-controlled mechanisms — and no existing benchmark isolates missingness-informativeness from missingness-amount via a matched-marginal-rate design across mechanism families.

**4. Final novelty claim:**
We are not the first to use MNAR/informative-missingness terminology in FL (FLOSS precedes us); our claim is narrower and precise: we are the first to study participation driven specifically by temporal concept drift, and the first to run a matched-marginal-rate benchmark isolating informativeness from amount, across FedAvg, FedIPW, FL-FDMS, FedDrift, SCAFFOLD, and KPFL.

**5. What we absolutely MUST NOT claim:**
- MUST NOT claim to have coined or discovered "MNAR" or "informative missingness" in FL (FLOSS, 2507.23115, precedes this)
- MUST NOT claim "IPW is mathematically impossible under MNAR" — only the Corollary-6.2-grounded, narrower statement (Part 3)
- MUST NOT claim drift-informative dropout is necessarily worse in aggregate — only that the drifted subpopulation's own representation is necessarily worse (H1a), while aggregate direction (H1b) is a genuine open question
- MUST NOT claim SAPA as a novel algorithm without a completed bias-bound proof and a DFL-AA-style naive-composition ablation beaten (Part 8) — if incomplete, drop it
- MUST NOT claim the malaria wearable dataset (or any dataset) as validated real-world evidence of drift-dropout correlation — no such dataset currently exists publicly (Part 10)
- MUST NOT claim to be first to study FL participation depending on local state broadly — CA-Fed, FedIPW, and FLOSS all touch adjacent versions; the claim must stay scoped to the temporal-drift-causal mechanism specifically

**6. Minimum viable experiment:**
FEMNIST only; MCAR/MAR/MNAR-logistic (3 mechanisms, 6 coupling levels); FedAvg/FedIPW/FL-FDMS/FedDrift (4 methods); 5 seeds ≈ 260 runs, ~3–4 weeks compute. No SAPA. This alone is a complete, precedented, publishable contribution (Part 9).

**7. Strong-paper experiment:**
MVP + Office-Caltech-10 (2nd dataset) + SCAFFOLD/KPFL + threshold-mechanism robustness check + both model-relative and model-independent drift-metric definitions (Part 5) + secondary severity sweeps on the 2–3 strongest methods only + (gated) SAPA with a completed bias-bound proof and a beaten DFL-AA-style ablation.

**8. Should SAPA exist at all?**
Conditionally. Gate it explicitly behind two deliverables: (a) a bias-bound derivation for the cross-client-proxy case, analogous to DFL-AA's Theorem 1 and FedIPW's Corollary 6.2, and (b) a demonstrated improvement over the "naive composition" ablation (empirical-frequency propensity + friend-fill, no fitted model — Part 8). If the student cannot complete (a) in reasonable time, drop SAPA entirely; the paper does not need it.

**9. Three strongest baselines:**
FL-FDMS (closest imputation-based competitor), FedIPW (closest reweighting-based competitor, with the precise Corollary-6.2 boundary claim), and a DFL-AA-style naive-composition ablation (empirical-frequency propensity + friend-fill, no fitted selection model) — this third one is now mandatory specifically to defend SAPA if attempted.

**10. Three strongest falsification tests:**
(a) If MCAR/MAR/MNAR degradation curves are statistically indistinguishable at matched marginal rate, the core informativeness claim is falsified. (b) If FedIPW's degradation under MNAR is no worse than under MAR, the empirically-realized bias from Corollary 6.2 fails to manifest and the FedIPW-boundary claim must be softened. (c) If SAPA (if attempted) fails to beat the naive-composition ablation, the algorithmic contribution is falsified and the paper reverts cleanly to the empirical-only framing.

**11. Expected contribution if the hypothesis is supported:**
First controlled empirical demonstration that drift-causal client participation produces a distinct failure mode from exogenous dropout at matched rates, with FedIPW's theoretical bias-floor argument empirically confirmed — a benchmark-and-characterization contribution with direct FL-specific precedent (Part 9), plus possibly a narrow, proven algorithmic extension (SAPA) if the gated stretch goal succeeds.

**12. Expected contribution if the hypothesis is NOT supported:**
Still legitimate and publishable: "informativeness of dropout, once amount is controlled for, does not meaningfully affect FL performance across the tested methods and mechanisms" is itself a real, non-obvious finding, in the same spirit as "Stop Overvaluing Multi-Agent Debate"-style negative results already surfaced in this research process. A falsifiable hypothesis that produces a real result either way is exactly what makes this legitimate research rather than a foregone conclusion dressed up as one.

**13. Exact next step for the student:**
(a) Read FLOSS ([arXiv:2507.23115](https://arxiv.org/abs/2507.23115)) in full and draft the precise differentiation paragraph *before writing anything else else* — this is now the single most likely first objection any reviewer or professor will raise. (b) Implement the matched-marginal-rate benchmark harness (MCAR/MAR/MNAR-logistic) on an existing FL simulator (Flower recommended), starting with FEMNIST; reproduce published FedAvg baseline numbers as a sanity check before running the full sweep. Do not touch SAPA until the minimum viable empirical characterization (item 6) is running cleanly end-to-end.

---

*This document is the third of three escalating hostile-validation passes against Candidate #1 (see `candidate1_adversarial_audit.md` for round two and `full_research_report.md` for the original ten-candidate discovery). Fourteen live literature-search agents have now run against this single idea across all three rounds. Re-run a fresh novelty-killing search on FLOSS's citation trail specifically before final submission — a PACMI workshop paper from Oct 2025 in a fast-moving space may already have follow-ups by the time this project starts.*
