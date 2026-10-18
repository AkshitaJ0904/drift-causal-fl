# Project Specification: Drift-Causal Participation in Federated Learning
## From Locked Idea to Executable MVP

*This document turns the surviving core of Candidate #1 (validated across three hostile literature rounds — see `full_research_report.md`, `candidate1_adversarial_audit.md`, `candidate1_final_hostile_validation.md`) into a formal research spec and implementation plan. No new literature search was performed for this document, per instruction — everything here builds on FLOSS (2507.23115), FedIPW (2604.26604), and DFL-AA (2606.10774) as load-bearing prior art.*

---

## PART 1 — Formal problem specification

**Notation.**
- `i ∈ {1,...,N}` — clients
- `t ∈ {1,...,T}` — communication rounds
- `P_i(t)` — client `i`'s local data-generating distribution at round `t` (latent, possibly non-stationary — this non-stationarity is "drift")
- `θ_t` — global model parameters at round `t`
- `Y_{i,t}` — the local update client `i` *would* compute at round `t` (e.g. `Δθ_{i,t} = θ_{i,t}^{local} − θ_t`). **This is the missing quantity.**
- `D_{i,t}` — drift state: a scalar summary functional of `P_i(t)`'s current departure from a baseline. **This is the auxiliary/selection variable, not the missing outcome.**
- `R_{i,t} ∈ {0,1}` — participation indicator. `Y_{i,t}` is observed by the server iff `R_{i,t}=1`.

**The distinction the whole project rests on:** `Y_{i,t}` is missing when `R_{i,t}=0`. `D_{i,t}` is what *drives* `R_{i,t}` — it is not itself "the missing outcome." Do not conflate these in writing.

**A critical simulation-design point, not previously made explicit:** in a real deployed system, the server never observes `D_{i,t}` for a given round at all unless `R_{i,t}=1` for that exact round. In *simulation*, the researcher controls the whole generative process and therefore has "god-view" access to `D_{i,t}` for every `(i,t)` regardless of `R_{i,t}` — this god-view is used only for (a) generating `R_{i,t}` via the mechanism, and (b) evaluation (e.g. computing drifted-subpopulation accuracy requires knowing which clients/rounds were high-drift even if they never participated). **Any FL algorithm under test (FedIPW, FL-FDMS, SAPA if revived) must only be given `D_{i,t}` for rounds where `R_{i,t}=1`** — never leak god-view information into the algorithm itself. This is an implementation invariant to enforce with a unit test, not just a design note.

**Data-generating process (causal structure).** The correct DAG is not `D → Y`; it's a shared-cause structure:

```
P_i(t)  ──────────────►  Y_{i,t}   (local update — the missing quantity)
   │
   └────────────────►  D_{i,t}  ──────────►  R_{i,t}   (selection equation)
```

`Y_{i,t}` and `D_{i,t}` are correlated because they share a common generative root (`P_i(t)`), not because one causes the other. `R_{i,t}` depends on `D_{i,t}`, which is why participation ends up correlated with the update's informational content without `D` needing to "cause" `Y` directly.

**Global-model feedback loop (when `D` is model-relative):**

```
θ_t → D_{i,t} (computed relative to θ_t) → R_{i,t} → {which Y_{i,t} observed} → θ_{t+1} (aggregation) → D_{i,t+1} (now relative to θ_{t+1}) → ...
```

This loop is real and must be disclosed (Part 3 addresses mitigation).

**Target estimand — must not be left ambiguous.** Candidates: (a) the global objective over *all* clients' current, possibly-drifted distributions; (b) the objective over a "core" stable subpopulation only; (c) the full-participation oracle model (`R≡1`), used as a *reference*, not a target; (d) drifted-subpopulation-specific performance; (e) a standard fixed held-out test set.

**Decision: primary target = (a).** If we evaluated against (b) instead, MNAR dropout wouldn't be expected to hurt *by construction* (we'd have defined the drifted clients out of the objective), which would make H1b (Part 6) untestable rather than genuinely open. (c) is used as a secondary reference metric (distance-from-oracle), (d) is used to test H1a specifically, (e) is the practical instantiation of (a) via a held-out test set that includes drift-injected examples proportionally.

---

## PART 2 — Formalizing the three dropout mechanisms

**MCAR:** `P(R_{i,t}=0) = p` — a single constant, identical for every client and round.

**MAR:** `P(R_{i,t}=0 | X_i) = σ(α + γ·X_i)`, where `X_i` is a **fixed per-client covariate assigned once at setup** (e.g., a device-class label drawn from a Beta distribution to create realistic heterogeneous baseline availability), **independent of drift by construction**. Deliberately *not* time-varying (e.g., not "time since last participation") for the MVP — that would introduce a temporal-autocorrelation structure that confounds with MNAR's own temporal structure (Part 4), and is better isolated as a separate, explicit ablation axis rather than baked into the primary MAR condition.

**MNAR / drift-informative:** `P(R_{i,t}=0 | D_{i,t}) = σ(α + β·D_{i,t})`, with `D_{i,t}` standardized (zero-mean, unit-variance within each round) before applying the logistic, so `β` is comparably scaled across different `D` definitions and datasets.

**Critical evaluation, as required — do not just accept the formula:**

- **`α` calibration:** solve numerically (bisection) for `α` given `β`, using a Monte Carlo estimate of `D_{i,t}`'s realized distribution, so the marginal dropout rate matches the target `p` across mechanisms. **Recalibrate `α` per round** rather than once globally — `D`'s population distribution can itself drift over training, and a single fixed `α` would let the realized marginal rate wander over time, undermining the "matched rate" claim. This is a deliberate design choice with a stability/complexity tradeoff, and should be stated as such.
- **Positivity — a real risk, not a formality.** FedIPW's own Proposition 4.1 requires `p_{i,t}>0` strictly; if high-`β` conditions push some high-drift clients' participation probability near zero, IPW weights (`1/p`) explode. This would produce a confounded finding — "FedIPW degrades under high β" could mean *ignorability violation* (the thing we want to measure) or *IPW variance blowup from near-zero propensities* (a nuisance artifact). **Clip participation probability to `[0.05, 0.95]` by design** to keep these two effects separable, and report both with and without the clip as a robustness check if time allows.
- **Persistent/chronic dropout:** at high `β`, a client with sustained high drift will be near-permanently absent — realistic (a permanently-shifted sensor would rarely report), but track and report the fraction of client-rounds where participation probability falls below a near-exclusion threshold (e.g. `<0.1`) as an explicit diagnostic, not a hidden side effect.
- **Threshold robustness mechanism (required, not optional):** `R_{i,t}=0` if `D_{i,t}` exceeds a within-round percentile threshold `τ`, else `Bernoulli(p_base)` calibrated to hit the target marginal rate combined with the deterministic exclusion. Run this alongside MNAR-logistic specifically because functional form affects tail concentration even at matched correlation (established in the second hostile audit).

---

## PART 3 — Defining drift properly

**A. Model-relative drift:**
`D^{model}_{i,t} = ℓ(θ_t; local data_{i,t}) − EMA_τ(ℓ(θ_{t'}; local data_{i,t'}))` for `t'<t` — loss relative to the client's own recent running-average loss under recent global models. This directly mirrors FedDrift's own drift-detection test statistic, for direct literature comparability.

**Circularity, spelled out:** `θ_t → D^{model}_{i,t} → R_{i,t} → {which Y_{i,t} observed} → θ_{t+1} → D^{model}_{i,t+1} (now relative to the NEW θ_{t+1}, itself shaped by who dropped out at t) → ...`. This loop is real. It is **not fatal** — FedDrift has an identical structure and is accepted SOTA — but must be explicitly tested against, not assumed away. **Mitigation for the MVP implementation: use a lagged global model (`θ_{t-1}`) for the drift computation**, reducing (not eliminating) the loop's tightness; disclose this as a design choice, not a fix.

**B. Model-independent drift (required robustness check, per the finding survives-both-definitions requirement):**
Recommended for FEMNIST specifically: since FEMNIST is a writer-partitioned handwriting dataset, natural "drift" over a short FL simulation is essentially absent — **drift must be synthetically injected**, exactly as FedDrift/DPFL themselves do (a disclosed, standard practice, not a shortcut). Inject drift via a scripted transformation (e.g., rotation/corruption of a subset of clients' images, or a label-distribution rotation) at researcher-controlled times and magnitudes — this yields a **ground-truth `D^{true}_{i,t}`** by construction, useful for validating both drift-estimator variants.

`D^{model-independent}_{i,t}` = a **frozen-feature distributional-shift statistic**: embed client `i`'s current-round samples via a fixed, never-updated-during-FL feature extractor (a small randomly-initialized or pretrained-and-frozen CNN), and compute Maximum Mean Discrepancy (or Wasserstein distance) between the current-round embedding distribution and a fixed early-round reference window for that same client.

**Why this is the most defensible choice for FEMNIST:** no dependence on the evolving global model at all (fully breaks the circularity loop), computable purely from local data, and is a standard technique from continual-learning/domain-shift detection (not invented ad hoc for this paper). **Every headline MVP comparison must be run under both `D^{model}` and `D^{model-independent}`** — if the finding only appears under the model-relative definition, that is itself an important (if less exciting) result: a warning that the effect may be an artifact of the joint estimation loop (see Part 10, falsification mode #3).

---

## PART 4 — Matching dropout rates correctly

Marginal-rate matching (Part 2's `α`-calibration) is necessary but not sufficient. Three distinct things must be tracked separately, not collapsed into one "dropout rate" number:

1. **Marginal dropout rate** — matched across MCAR/MAR/MNAR by construction (Part 2).
2. **Per-client dropout frequency distribution** — under MNAR this will show more variance/skew (some clients almost always present, some almost always absent) than MCAR/MAR's flatter distribution. **Report this explicitly as a description of the mechanism, not something to eliminate** — it is the phenomenon under study.
3. **Temporal autocorrelation / burstiness** — under MNAR, `D_{i,t}` is autocorrelated over time (drift evolves gradually), so dropout will show *bursts* (consecutive missed rounds) beyond what MCAR's i.i.d. draws produce. **This is a genuine second confound**, separate from "informativeness of who is missing": a difference between MCAR and MNAR could be driven by *burstiness of the missingness pattern* rather than *which clients* are missing. Recommended strong-paper-tier ablation: an **"MAR-matched-burstiness"** condition, where the MAR-driving covariate `X_{i,t}` is given the same autocorrelation structure as `D_{i,t}` (e.g., an AR(1) process with matched autocorrelation) while remaining content-independent of drift. This isolates "who is missing" from "temporal pattern of missingness" as two separate causal stories — not required for MVP, mandatory for the strong-paper tier.
4. **Participating clients per round, non-IID severity, drift severity** — held fixed at one operating point for the primary MVP comparison; varied only in strong-paper secondary sweeps.

**Do not "control away" the compositional imbalance** (high-drift clients missing more often at matched rate) — that is the manipulation working as intended, not noise to eliminate.

---

## PART 5 — The coupling axis, decided

- **Primary, reported axis: realized point-biserial correlation** `ρ = corr(D_{i,t}, 1[R_{i,t}=0])`, computed post-hoc from simulation logs. Point-biserial is the textbook-correct statistic here (Pearson correlation specialized to one continuous, one binary variable) — no need to invent anything fancier.
- **Secondary, mechanism-invariant check: mutual information** `I(D;R)`, estimated via a standard binning or kNN estimator. Necessary specifically because two mechanisms (logistic vs. threshold) can share `ρ` while differing in dependence *shape* (tail concentration) — `I(D;R)` catches this where correlation alone can't.
- **Why `β` is not the comparison axis:** `β` is mechanism-specific (only defined for the logistic family; a threshold mechanism has no `β` at all) and not comparable across different `D` definitions/scalings without standardization — it belongs in the methods section as an implementation detail, never as a plotted x-axis for cross-mechanism claims.
- **Explicitly rejected:** selection odds ratio, standardized-logistic-coefficient-as-universal-axis — these add jargon without adding real statistical power for this specific need. Do not over-engineer.

---

## PART 6 — Final hypotheses, statistically formalized

**H1 (primary, direction-agnostic):** At matched marginal dropout rate `p`, the primary outcome metric differs systematically across mechanism ∈ {MCAR, MAR, MNAR}.

- Formal null: `H0: μ_MCAR = μ_MAR = μ_MNAR` (mechanism has no effect on the metric at matched `p`).
- **Primary statistical model:** a mixed-effects regression, `metric ~ mechanism + β + method + mechanism:β + mechanism:method + (1|seed)`, rather than a large family of pairwise tests — more statistically efficient and directly answers both "does mechanism matter" (main effect) and "is there a dose-response relationship" (`mechanism:β` interaction) in one model.
- Report: coefficient estimates, 95% CI (percentile bootstrap over seeds — 5 seeds is too thin for asymptotic normal CIs), and effect size (partial η² or Cohen's d) for the mechanism main effect.

**H1a (near-definitional, expected true, low scientific risk):** Drifted-subpopulation-specific test accuracy is lower under MNAR than MCAR/MAR at matched `p`, because that subpopulation's training signal is systematically underrepresented.

- One-sided test (Wilcoxon signed-rank, paired by seed), MNAR vs. MCAR/MAR on drifted-subpopulation accuracy specifically. This functions partly as a manipulation check — expect a large, robust effect here; if this *doesn't* show up, something is wrong with the harness, not the science.

**H1b (the genuinely open, primary scientific question):** The effect on *aggregate/global* accuracy is unsigned — may be negative, neutral, or positive depending on whether drifted-client signal is informative or noisy relative to the evaluation target (Part 7 of the second hostile audit constructed real counterexamples to "MNAR is worse").

- Two-sided test (Wilcoxon signed-rank or the mixed-effects regression's mechanism coefficient with a two-sided CI). Report effect size, direction, and CI without pre-committing to a sign.

**Interaction terms:**
- `mechanism × β` — dose-response check.
- `mechanism × method` — **the direct test of the FedIPW-boundary claim (Part 11).** Expect a significant interaction where FedIPW's advantage over FedAvg (present under MCAR/MAR) shrinks or vanishes specifically under MNAR. If this interaction is not significant, that's falsification mode #2 (Part 10) — handled explicitly, not ignored.

---

## PART 7 — MVP method audit

| Method | Why included | Assumption it represents | Question it answers | Implementation status |
|---|---|---|---|---|
| **FedAvg** | Canonical floor | No participation-awareness at all | Baseline: how bad is naive skip-and-average? | Trivial — widely reimplemented, ships natively in Flower |
| **FedIPW** | **Most important method — the one whose theoretical failure mode we're directly testing** | Mean Ignorability (participation depends only on observed covariates) | Does the field's best existing correction actually degrade specifically under MNAR, as Corollary 6.2 predicts? | **No confirmed official public code — must reimplement from the paper's equations.** Real, non-trivial implementation lift |
| **FL-FDMS** | Closest competing imputation-based method (the paper DCPA/SAPA had to be compared against and partly duplicated — see prior audits) | Similarity-based substitution helps regardless of *why* a client is missing | Does naive cross-client imputation, with no selection-awareness, help or hurt under MNAR? | No confirmed official public code — reimplement from paper (cosine-similarity friend-matching + EMA tracking + substitution); well-specified, moderate lift |
| **FedDrift** | Source of the drift-clustering technique; a natural "drift-aware but participation-naive" negative control | Drift matters for *aggregation structure*, but participation is assumed exogenous/full | Does drift-clustering alone (without any participation-correction) help under informative dropout, or is it irrelevant to this specific failure mode? | No confirmed official public code — reimplement drift-detection-test + hierarchical clustering equations; moderate-to-high lift |
| SCAFFOLD, FedProx, KPFL | Deferred to strong-paper tier | — | — | Not in MVP — see execution-audit rationale in the third hostile validation, Part 11 |

**Added refinement beyond the original plan:** implement **two FedIPW variants** — **oracle-IPW** (using the *true* generating probabilities `p_{i,t}`, which the simulation knows by construction — an upper-bound, best-case version) and **estimated-IPW** (fitting a propensity model from observed `(X_i, A_{i,r})` pairs exactly as the real system would). This cleanly decomposes "does the ignorability violation itself cause bias" (oracle-IPW test — isolates the theoretical mechanism) from "does propensity-estimation error compound it" (estimated-IPW test — the realistic case). This raises the method count from 4 to effectively 5 method-variants; worth the added implementation cost for the analytical clarity it buys.

**Single largest schedule risk:** FedIPW, FL-FDMS, and FedDrift all require from-paper reimplementation with no confirmed official code — this should dominate the first-week schedule (Part 15), sequenced one at a time with unit tests, not attempted simultaneously.

---

## PART 8 — Exact experiment matrix

### MVP

| Axis | Value |
|---|---|
| Dataset | FEMNIST (LEAF), subsampled to 100 clients |
| Model | Small CNN (2 conv + 2 FC — LEAF/FedDrift reference architecture) |
| Rounds `T` | 100 |
| Local epochs | 1 |
| Client sampling per round | All currently-available (`R_{i,t}=1`) clients — dropout *is* the sampling mechanism, no additional subsampling on top |
| Non-IID config | FEMNIST's natural per-writer partition (no additional synthetic Dirichlet partition needed) |
| Drift generation | Fixed, moderate severity — one scripted injection event (e.g. rotation/corruption) for ~30% of clients at a designated round window; ground-truth `D^{true}` labels retained |
| Marginal dropout rate `p` | Fixed at 30% |
| Mechanisms | MCAR (1) + MAR (1) + MNAR-logistic at 5 non-trivial β levels (`β ∈ {0.5, 1, 2, 4, 8}` in standardized-D units) = **7 conditions** |
| Methods | FedAvg, FedIPW-oracle, FedIPW-estimated, FL-FDMS, FedDrift = **5 method-variants** |
| Seeds | 5 |
| Drift definition | Model-relative (primary run) — **the full grid is re-run once more under model-independent drift as a required robustness pass** |
| Evaluation frequency | Every 5 rounds, on the standard LEAF FEMNIST held-out test split + a drift-injected held-out subset |

**MVP run count: 7 conditions × 5 method-variants × 5 seeds = 175 runs** (one pass). **Total including the required model-independent-drift robustness re-run: 350 runs.** This is the number to commit to first — smaller than the second audit's original 1,200–1,300 estimate, deliberately, per instruction #7.

### Strong paper (staged extension only after MVP result is in hand — do not pre-build this)

Add: 2nd dataset (Office-Caltech-10, or a second FEMNIST severity/rate operating point) · SCAFFOLD + KPFL (→ 7 methods) · threshold-mechanism family (+5 conditions) · burstiness-matched-MAR ablation (Part 4) · secondary severity sweeps (non-IID severity, drift severity, dropout rate `p`) on the 2–3 strongest methods only, 3 levels each. Rough total: 800–1,000 runs, built incrementally around whatever the MVP actually found — **do not commit to this grid before the MVP result exists.**

### Optional stretch (SAPA — gated, see Part 13)

Naive-composition ablation + (if gated criteria met) full SAPA + its bias-bound validation experiments — roughly +150–250 runs, attempted only after the MVP and strong-paper tiers are complete and SAPA's revival criteria are met.

---

## PART 9 — Metrics: one primary, no bloat

**Primary metric (the one number the headline H1/H1b claim rests on): global test accuracy** on the standard held-out FEMNIST test set. Most comparable to prior FL literature, cleanest single number.

**Secondary/diagnostic (reported in tables, never conflated with the primary hypothesis test):**
- Drifted-subpopulation test accuracy (H1a test)
- Worst-client accuracy (standard FL fairness proxy, matches Ditto's own metric choice)
- Accuracy variance/disparity across clients (fairness)
- Distance from full-participation oracle (`R≡1` reference run)
- Convergence speed (rounds-to-target-accuracy)
- Realized `ρ` and `I(D;R)` (mechanism diagnostics, not outcome metrics)

Avoid metric bloat: every plot and headline claim should be built around global test accuracy first; everything else is supporting/diagnostic evidence, not a second "primary" result competing for attention.

---

## PART 10 — Five ways this project can fail, made scientifically useful

| # | Failure mode | Kills the project? | Interpretation | What survives |
|---|---|---|---|---|
| 1 | MCAR/MAR/MNAR produce statistically indistinguishable results (H1 falsified) | No | Existing FL methods are more robust to informative dropout than the field assumed | The benchmark protocol itself + a clean negative/boundary finding — still precedented (Part 9 of the third audit lists 5 real FL papers built on exactly this kind of finding) |
| 2 | FedIPW remains robust under MNAR (`mechanism×method` interaction not significant) | No | Either the simulated coupling wasn't strong enough (widen the β range) or FedIPW is more robust in practice than the worst-case Corollary 6.2 bound suggests — the latter is itself a genuinely interesting, publishable finding (worst-case bounds are often loose) | H1/H1a can still hold independent of this; report honestly either way |
| 3 | Effect disappears under model-independent drift (only appears under model-relative `D`) | No, but forces reframing | Strong evidence the model-relative finding is a circularity artifact (Part 3) | A real methodological/cautionary contribution in itself — a warning applicable to FedDrift's own drift measure, not just ours |
| 4 | Effect is fully explained by temporal burstiness rather than informativeness (per the matched-burstiness MAR ablation) | No, but forces reframing | It's not *who* is missing that matters, it's the *temporal pattern* of missingness | Arguably a more actionable finding (burstiness is easier to detect operationally than latent-state dependence) — retitle the contribution around persistence-pattern rather than informativeness |
| 5 | Results reverse across datasets/severity levels (not robust) | No | The effect is condition-dependent | A "boundary conditions" characterization, matching NIID-Bench's own precedent ("no method dominates in all conditions" was itself the contribution) |

**None of these five outcomes is fatal to publishability**, consistent with rule #11: the hypothesis is not adjusted after seeing results — whichever of these occurs is reported as the finding, not massaged into a different claim.

---

## PART 11 — The FedIPW theoretical boundary, precisely (not repeated loosely)

1. **Assumptions, precisely:** Mean Ignorability — `E[Δ_{i,r}|Z_i,X_{i,r},A_{i,r}=1] = E[Δ_{i,r}|Z_i,X_{i,r}]` — plus positivity `p_{i,r}>0`.
2. **Which assumption our mechanism violates:** `D_{i,t} ∉ {Z_i, X_{i,r}}` — our MNAR mechanism makes participation depend on a variable outside FedIPW's own conditioning set, so the ignorability equality fails whenever `β≠0`.
3. **Relevance of the bias-floor result:** FedIPW's Corollary 6.2 treats an *omitted* selection-relevant factor as contributing a non-vanishing bias-floor term to the estimator. `D_{i,t}` is exactly such an omitted factor in our setting — this is a proof-level implication, not an inference from the paper's silence.
4. **What additional structure would be needed to correct this:** a proxy variable for `D_{i,t}` observed for non-participating rounds, an instrument, or an explicitly parameterized non-ignorable selection equation (Heckman-style) — FedIPW supplies none of these, and (per the third hostile audit's search) no FL paper currently does either.
5. **Exact permitted claim:**

> "Standard IPW conditioned only on the observed covariate set is not guaranteed to remain unbiased when participation depends on a current state outside that conditioning set."

**Do not generalize this to "IPW cannot solve MNAR"** — false in general (Heckman-type models, proxy-augmented propensity models, and exclusion-restriction IPW all handle various MNAR structures with additional assumptions FedIPW simply doesn't supply).

---

## PART 12 — FLOSS differentiation (mandatory)

| Dimension | FLOSS (2507.23115) | Our study |
|---|---|---|
| Missingness mechanism | Opt-out driven by client dissatisfaction | Dropout driven by the client's own temporally-evolving concept drift |
| Selection driver | Model-fit quality ("satisfaction") — a snapshot notion | Drift magnitude `D_{i,t}` — model-relative and model-independent operationalizations |
| Static vs. temporal | Static/per-round quality signal, no explicit temporal evolution model | Explicitly temporal — drift evolves across rounds; dose-response over coupling strength and persistence/burstiness studied directly |
| Drift | Not modeled at all | Central object of study |
| Matched dropout rate | Not controlled — compares presence vs. FLOSS's specific mechanism only | Core methodological contribution — MCAR/MAR/MNAR held at matched marginal rate to isolate informativeness from amount |
| Benchmark design | Single mechanism; oracle-vs-estimated propensity ablation only | Multi-mechanism (≥3 families), multi-coupling-level sweep, multi-method comparison |
| Methods evaluated | IPW correction only (their own) | FedAvg, FedIPW (oracle + estimated), FL-FDMS, FedDrift (MVP); SCAFFOLD/KPFL (strong-paper) |
| Research question | Does IPW correct for opt-out-driven MNAR? | Does drift-causal, temporally-evolving informative dropout produce systematically different outcomes than exogenous dropout at matched rate — and does FedIPW itself remain valid? |
| Correction method | Introduces and validates IPW as the contribution | Evaluates FedIPW (and FL-FDMS, FedDrift) as *existing* methods under a *new* mechanism — does not introduce IPW as novel |

**Exact differentiation paragraph, ready for a proposal:**

> "FLOSS (Goetze et al., PACMI 2025) was the first to formalize non-ignorable, MNAR-style client participation in federated learning, modeling opt-out as a function of a client's satisfaction with current model quality, and validating an IPW correction against it. Our work is complementary rather than duplicative: we study a distinct, temporally-evolving driver of non-ignorable participation — concept drift in the client's own local data distribution — and, unlike FLOSS, our central methodological contribution is a controlled benchmark that holds the marginal dropout rate fixed across mechanism families (MCAR, MAR, and drift-informative MNAR) to isolate the effect of missingness informativeness from missingness amount, a comparison FLOSS does not attempt. We also evaluate FLOSS's own dependency, FedIPW, and a further imputation-based method (FL-FDMS), as existing candidate solutions under this new mechanism, rather than proposing IPW as a novel contribution as FLOSS does."

**Is FLOSS closer than expected?** No — confirming, not escalating, the third hostile audit's assessment. FLOSS is genuinely load-bearing prior art (it must be cited prominently and the general "MNAR-in-FL" terminology claim is narrowed because of it), but its actual mechanism (static satisfaction, no temporal drift, no matched-rate benchmark) remains distinct from ours.

---

## PART 13 — SAPA go/no-go rule (restated precisely, not repeated loosely)

**We are not building SAPA now.** The comparison that matters:

- **DFL-AA** already proves *propensity-style weight × discount factor, combined* works, using **empirical-frequency propensity** (not a fitted model) and **self-fill** imputation (not cross-client).
- **FL-FDMS** already proves *cross-client friend-fill* works, with **no propensity weighting at all**.
- **FedIPW** already proves *fitted-selection-model propensity weighting* works, with **no imputation** — it only reweights observed contributions.
- **Naive composition** (a cheap, obvious thing to try *before* inventing SAPA): DFL-AA's empirical-frequency-style weight applied to FL-FDMS's friend-fill substitute, with no fitted model at all. This must be implemented and tested as a baseline regardless of whether SAPA is ever attempted.

**Exact threshold to revive SAPA — both required, neither optional:**

1. A **mathematically complete, written-out bias bound** for the cross-client-proxy substitution case, extending DFL-AA's Theorem 1 / FedIPW's Corollary 6.2 to account for the systematic distributional gap between a proxy client's update and the true missing value (DFL-AA's proof does not need to handle this, since its imputation source is the *same* node).
2. **Empirical outperformance of the naive-composition ablation** — the fitted-selection-model-weighted friend-fill must beat the empirical-frequency-weighted friend-fill at matched implementation/compute complexity.

**If either fails: drop SAPA entirely.** The empirical characterization plus the four-method comparison (Part 7) is already a complete, precedented, publishable contribution (Part 9 of the third hostile audit) — do not force an algorithmic contribution that doesn't clear its own bar.

---

## PART 14 — Implementation architecture

**Framework: Flower** (not FedML) — actively maintained, clean Python API for writing custom `Strategy` classes (needed for FedIPW/FL-FDMS/FedDrift/SAPA's non-standard aggregation logic), a built-in simulation mode (`VirtualClientEngine`) suited to single-machine undergrad compute, and a lower learning curve than FedML's more enterprise-oriented framework for this kind of research-custom harness.

**Python:** 3.10 or 3.11.

**Configuration system: Hydra** — composable configs across the combinatorial axes (dataset × mechanism × method × β × seed) beat raw argparse or manual YAML-loading at this scale.

**Repository structure:**

```
drift-causal-fl/
├── src/
│   ├── mechanisms/          # MCAR, MAR, MNAR-logistic, MNAR-threshold generators
│   │   ├── base.py
│   │   ├── mcar.py
│   │   ├── mar.py
│   │   └── mnar.py
│   ├── drift/
│   │   ├── model_relative.py
│   │   └── model_independent.py    # frozen-feature MMD/Wasserstein
│   ├── methods/                     # Flower Strategy implementations
│   │   ├── fedavg.py
│   │   ├── fedipw.py                # oracle + estimated variants
│   │   ├── fedfdms.py
│   │   ├── feddrift.py
│   │   └── sapa.py                  # STUB ONLY — do not implement until Part 13 criteria met
│   ├── models/                      # CNN architecture
│   ├── data/                        # FEMNIST loading, writer partitioning, drift injection
│   ├── simulation/                  # core round-loop harness, R_{i,t} generation, god-view D tracking
│   └── metrics/                     # accuracy, fairness, drifted-subpop eval, oracle-distance
├── configs/                          # Hydra configs
│   ├── mvp/
│   └── strong_paper/
├── experiments/                       # sweep-launching scripts
├── data_cache/                        # downloaded/preprocessed FEMNIST
├── results/                           # one directory per run: metrics.jsonl + checkpoint + config snapshot
├── plots/
├── analysis/                          # mixed-effects regression, bootstrap CIs — kept separate from simulation code
├── scripts/
├── tests/                             # unit tests, esp. mechanism calibration + god-view leakage check
└── paper/
```

**Random seed management:** one top-level seed per run controls data partitioning, model init, mechanism stochasticity, and drift injection — set via `random`/`numpy`/`torch` at run start, logged in run metadata.

**Logging:** structured JSON-lines per-round metrics, written incrementally (enables partial-run recovery, trivial pandas-based downstream analysis).

**Checkpointing:** global model state every 20 rounds + final round — sufficient for post-hoc oracle-distance computation; no need for full fault-tolerant resumption at this scale.

**Result storage:** flat-file, one run = one directory under `results/`; aggregate via a pandas script that globs the directory. No database needed.

**Plotting:** matplotlib/seaborn — static figures (convergence curves, degradation-vs-β plots, bootstrap-CI bar charts) are sufficient for a research paper.

**Statistical analysis:** Python `statsmodels` (`mixedlm` for the mixed-effects regression), `scipy.stats` (Wilcoxon), a bootstrap-CI helper. Kept in a dedicated `analysis/` directory, run only after sweep results are collected — never mixed into simulation code (this is the direct implementation of rule #12: separate empirical findings from the code that produces them).

**Reproducibility:** pinned dependency versions (`requirements.txt` or `poetry.lock`), hardware/OS logged in run metadata, all seeds fixed and logged.

---

## PART 15 — First 7 days

**Day 1 — Environment + trustworthy baseline (THE milestone, not the full benchmark).** Install Flower, PyTorch, Hydra. Download/preprocess LEAF FEMNIST, subsample to 100 clients. Implement and unit-test the small CNN architecture. Run a bare-bones FedAvg-FEMNIST loop with **full participation (`R≡1`), no dropout mechanism at all**. Compare the resulting accuracy curve against LEAF/FedDrift's published FedAvg-FEMNIST numbers as a sanity check.

**Day 2 — Drift harness.** Implement the god-view drift-injection schedule (scripted rotation/corruption for a subset of clients at a designated round window) with ground-truth `D^{true}` labels. Implement `D^{model}` (lagged-global-model loss-shift). Verify `D^{model}` correlates sensibly with `D^{true}` on drift-injected clients — a validation check, not a hypothesis test.

**Day 3 — MCAR + MAR.** Implement the simplest mechanism generators. Rerun FedAvg-FEMNIST under MCAR and MAR at the 30% target marginal rate. Confirm the harness correctly skips non-participants in aggregation and the realized rate matches target within tolerance.

**Day 4 — MNAR + calibration + positivity.** Implement MNAR-logistic with the per-round `α`-bisection calibration and the `[0.05, 0.95]` positivity clip. Compute and log realized `ρ`. Sanity-check that increasing `β` monotonically increases realized `ρ`. Rerun FedAvg-FEMNIST under one MNAR condition end-to-end.

**Day 5 — FedIPW (highest-risk method, budget the full day).** Implement both oracle-weight and estimated-propensity variants as a custom Flower `Strategy`. Unit-test the aggregation weighting logic in isolation on a small synthetic toy example with known expected output *before* running the full FEMNIST loop.

**Day 6 — FL-FDMS.** Implement cosine-similarity friend-matching, EMA score tracking, substitution logic. Same unit-test-first discipline as Day 5.

**Day 7 — FedDrift + first end-to-end smoke test.** Implement the loss-degradation drift-detection test and hierarchical clustering (the most involved of the three custom methods — allow slippage to Day 8/9 if needed, and say so honestly rather than compressing it). Run a **reduced smoke-test sweep** — all 3 mechanisms × ~3 β levels × all implemented methods × 2 seeds — to confirm the full pipeline runs end-to-end and produces sensible, loggable results *before* committing to the full 350-run MVP.

**Beyond Day 7:** full MVP sweep (350 runs) → mixed-effects regression + bootstrap CIs + headline figures → interpret against the five falsification modes (Part 10) → decide whether to proceed to the strong-paper tier or the SAPA gate (Part 13).

---

## PART 16 — Paper structure

| Section | Belongs here | Does NOT belong here | Evidence needed |
|---|---|---|---|
| 1. Introduction | Deployment motivation (sensor most-informative-when-drifted, least-likely-to-report), research question, direction-agnostic preview, contribution list | Literature detail, equations, result numbers | — |
| 2. Background | FL basics, concept drift generally, missing-data taxonomy (Rubin/Diggle-Kenward) at a non-specialist level | Related-work comparison table, our method's details | — |
| 3. Related Work | FedDrift, FedIPW, FL-FDMS, DFL-AA, FLOSS (differentiation paragraph goes here), CA-Fed, correlated-participation paper — by theme, ending in the explicit gap statement | Our own results, hedged future-work claims | — |
| 4. Problem Formulation | Part 1's formal spec (notation, DAG, estimand) | Implementation details, hyperparameters | — |
| 5. Drift-Causal Participation Model | Two `D` definitions, mechanism families with full equations, calibration procedure, positivity handling | Results | Part 2/3 design + Day 2 validation check |
| 6. Benchmark Methodology | Matched-rate design rationale, burstiness discussion, coupling-axis choice, estimand/metrics | Numeric results, dataset-specific hyperparameters | — |
| 7. Experimental Setup | Dataset, architecture, client count, rounds, methods with per-method rationale (Part 7's table), hyperparameters, hardware, seeds | Methodology rationale (already in §6), results | — |
| 8. Results | Headline figures/tables, H1/H1a/H1b statistical tests plainly reported (coefficients, CIs), `mechanism×method` interaction test, robustness checks (model-independent-D, threshold-mechanism, burstiness ablation) | Interpretation/speculation | Full mixed-effects regression output, bootstrap CIs |
| 9. Analysis | Interpretation tied back to Corollary 6.2, H1b direction discussion, H1a decomposition | New numbers not in Results, new post-hoc hypotheses (rule #11) | — |
| 10. Limitations | Synthetic drift (no verified real dataset — third audit Part 10), model-relative-D circularity risk (not fully eliminated even if tested), FEMNIST-only MVP scope, proxy-method failure modes if SAPA included, small-seed-count power caveat | New results, undermining hedges | — |
| 11. Discussion | Practitioner implications, connection to FLOSS/FedIPW/DFL-AA lineage, SAPA's practical impact if attempted | Literature re-review, new experiments | — |
| 12. Conclusion | 3–5 sentence summary of contribution + actual finding direction + one sentence future work | New unsubstantiated claims | — |

---

## PART 17 — Professor 60-second pitch

> "Federated learning trains a shared model across many devices without centralizing their data — but not every device participates every round. Almost all existing FL research assumes dropout is unrelated to what's happening on the device locally. In a lot of realistic settings, though — an industrial sensor, a health wearable — a device might be *more or less* likely to report exactly *because of* the unusual condition it's currently experiencing. A sensor might go offline right when it detects an anomaly. If that's true, the data the model never sees is exactly the data that mattered most.
>
> I searched hard for existing work on this. There's one paper, FLOSS, that studies a related idea — dropout driven by how satisfied a user is with the model — but nobody has studied dropout driven by a client's own data *drifting over time*, and nobody has run a controlled experiment that isolates 'how much data is missing' from 'how informative the missing data would have been.'
>
> My project builds that controlled experiment: simulate federated learning under three kinds of dropout — random, tied to an irrelevant factor, and tied to a client's own current drift — all calibrated to the *same* overall dropout rate, and measure whether existing methods, including one specifically built to correct for biased participation, actually behave differently. There's real math backing why that correction method *should* struggle here — it has a formal assumption this scenario directly violates.
>
> It's feasible in two semesters: it's a simulation study, no human subjects, no special hardware, standard open-source FL tools. And even if the effect is smaller than expected, that's still a real answer nobody currently has."

---

# FINAL OUTPUT

## A. FINAL LOCKED RESEARCH SPECIFICATION
Title: *When Absence Is Informative: Benchmarking Federated Learning Under Drift-Causal Client Participation.* Formal spec per Part 1: `Y_{i,t}` (update) is the missing quantity; `D_{i,t}` (drift) is the auxiliary selection variable driving `R_{i,t}`; primary estimand is the global objective over all clients including drifted ones. Load-bearing prior art: FLOSS (2507.23115), FedIPW (2604.26604), DFL-AA (2606.10774).

## B. FINAL MVP EXPERIMENT
FEMNIST, 100 clients, 100 rounds, small CNN, one moderate drift/non-IID/rate operating point. 3 mechanisms (MCAR/MAR/MNAR-logistic, 7 conditions total) × 5 method-variants (FedAvg, FedIPW-oracle, FedIPW-estimated, FL-FDMS, FedDrift) × 5 seeds, run under both model-relative and model-independent drift.

## C. EXACT EXPERIMENT MATRIX
**MVP: 175 runs × 2 drift-definitions = 350 runs.** Strong-paper: staged extension to ~800–1,000 runs, built after the MVP result exists, not before. Stretch (SAPA, gated): +150–250 runs.

## D. FINAL HYPOTHESES
**H1** (mechanism affects the primary metric at matched rate, direction-agnostic) · **H1a** (drifted-subpopulation accuracy is lower under MNAR — near-definitional) · **H1b** (aggregate accuracy effect is unsigned and is the real open question) · plus the `mechanism×method` interaction as the direct FedIPW-boundary test.

## E. FALSIFICATION CRITERIA
Five modes (Part 10), none fatal to publishability: indistinguishable mechanisms; FedIPW stays robust; effect vanishes under model-independent drift; effect is really about burstiness not informativeness; results don't replicate across datasets. Each has a stated, non-fatal reinterpretation.

## F. FLOSS DIFFERENTIATION
Table + paragraph in Part 12. FLOSS: static satisfaction-driven opt-out, no matched-rate benchmark. Ours: temporal drift-driven, matched-rate benchmark across mechanism families. FLOSS is real, load-bearing prior art — cited prominently, not treated as a threat once properly scoped.

## G. FEDIPW ASSUMPTION BOUNDARY
Exact permitted claim only: *"Standard IPW conditioned only on the observed covariate set is not guaranteed to remain unbiased when participation depends on a current state outside that conditioning set."* Never "IPW cannot solve MNAR."

## H. SAPA GO/NO-GO RULE
Not built now. Revival requires **both**: (1) a complete bias-bound proof for cross-client-proxy substitution, and (2) beating the naive-composition ablation (empirical-frequency weight × friend-fill) empirically. Either failing → drop SAPA, ship the empirical/method-comparison paper, which is already complete and precedented on its own.

## I. IMPLEMENTATION ARCHITECTURE
Flower + Hydra + PyTorch, Python 3.10/3.11. Repository structure in Part 14. Simulation code and statistical-analysis code kept strictly separate.

## J. FIRST 7 DAYS
Day 1: trustworthy full-participation FedAvg baseline (the actual first milestone). Day 2: drift harness. Day 3: MCAR/MAR. Day 4: MNAR + calibration + positivity. Day 5: FedIPW (highest risk). Day 6: FL-FDMS. Day 7: FedDrift + reduced smoke-test sweep before committing to the full 350-run MVP.

## K. PROFESSOR 60-SECOND PITCH
See Part 17 in full above.

## L. WHAT I SHOULD DO TOMORROW MORNING
1. Install Flower + PyTorch + Hydra; clone/set up the LEAF FEMNIST data pipeline.
2. Read FLOSS (arXiv:2507.23115) in full and draft the differentiation paragraph (Part 12) *before* writing anything else — it is the first objection any advisor will raise.
3. Get the bare-bones full-participation FedAvg-FEMNIST loop training and confirm its accuracy curve is in the right ballpark against published numbers. Do not touch any dropout mechanism, FedIPW, FL-FDMS, or FedDrift until this baseline is trustworthy.
