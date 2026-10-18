# Adversarial Novelty Audit — Candidate #1
## Federated Learning Under Missing-Not-At-Random Client Participation

*Hostile-reviewer pass, conducted 2026-09-09. Goal: kill this idea if it deserves to die. Three live literature agents ran deep methodology audits (not abstract-only) against arXiv/Semantic Scholar/Google Scholar; findings below trace directly to their reports with links.*

---

## PART 1 — Definitional audit (is our use of "MNAR" defensible?)

**Formal definitions (Rubin, 1976; Little & Rubin, 2002).** Let `Y` = the outcome/state of interest, `R` = observation indicator (1 = observed), `X` = observed covariates.

- **MCAR** — `P(R | Y, X) = P(R)`. Missingness independent of everything.
- **MAR** — `P(R | Y, X) = P(R | X)`. Missingness depends only on *observed* covariates, not on the unobserved value of `Y` itself once you condition on `X`.
- **MNAR / non-ignorable missingness** — `P(R | Y, X)` depends on the unobserved value of `Y` even after conditioning on `X`. This is the Heckman-selection regime: identification requires an auxiliary structure (an instrument, a proxy variable observed for the missing cases, or a parametric assumption on the selection mechanism) — **MNAR is not identifiable from the observed data alone.**

**Mapped to FL:**

| Term | FL meaning |
|---|---|
| Client participation bias | Umbrella term: `R_i,t` (participation) not independent of client/round characteristics — could be MAR or MNAR |
| Correlated participation | `R_i,t` autocorrelated over time/clients (e.g., a Markov chain on *time-since-last-participation*) — this is an orthogonal axis to the MCAR/MAR/MNAR taxonomy. Autocorrelation driven only by schedule/time is still MAR. |
| Concept drift | `P(local data \| client)` changes over time for a given client |
| Drift-correlated / informative dropout | `R_i,t` depends on the client's **current, round-t** drift magnitude — this is the MNAR case, since drift state is the very thing the server would want to estimate |
| Informative missingness | Synonym for MNAR/non-ignorable missingness |

**Verdict on our own terminology: conditionally defensible, with one required fix.**

The proposal's phrase "the client's current **(unobserved)** drift state" is doing too much work as written. Classical MNAR (Heckman 1979) requires that the outcome *is* observed for the selected (participating) cases — that's how the selection mechanism gets identified at all; the problem is that it's missing precisely for the unselected cases. If we mean "drift is literally never measurable by the server, even in principle, even when the client participates," the problem is not just MNAR — it's **unidentifiable without an auxiliary structure**, full stop, and no correction method (IPW, DCPA, anything) can fix it without inventing that structure from nowhere.

**The fix:** operationalize "drift state" as a quantity that *is* observable/computable when the client is online (e.g., local validation loss delta vs. last global model, or an update-similarity signature) and is only unobserved *while the client is offline*. This is standard panel-attrition framing (`Y` observed for `R=1`, missing for `R=0`, selection depends on `Y`) and makes DCPA's clustering step legible as exactly the auxiliary proxy structure MNAR identification requires — same-cluster online neighbors serve as the proxy for the missing client's current `Y`. **This reframing is not cosmetic — it is load-bearing for both the statistical validity of the MNAR label and for justifying why DCPA's mechanism (borrowing information from a proxy) is the theoretically correct move rather than an arbitrary heuristic.** State this explicitly in the paper; don't leave "unobserved" ambiguous.

With that fix, **the MNAR label is legitimate and precise** — it correctly distinguishes our setting from every "correlated participation" paper found (2410.01209, CA-Fed 2301.04632, DPFL/KPFL 2511.16523), all of which are provably MAR (dependence on time/schedule/observable covariates only, confirmed in Part 2).

---

## PART 0 (VERDICT UP FRONT — before the supporting detail)

**Two separate claims were bundled in the original proposal. They survive the audit very differently.**

1. **The empirical research gap** (no one studies FL robustness when dropout is a causal function of the client's current unobserved drift state) — **SURVIVES.** Genuinely not found in the literature. Novelty class holds at **D**.
2. **The proposed algorithmic contribution, DCPA, as originally specified** — **DOES NOT SURVIVE AS WRITTEN.** A near-identical mechanism already exists ([FL-FDMS, arXiv:2205.13222](https://arxiv.org/abs/2205.13222)), and DCPA's one nominally-new piece (staleness/uncertainty discounting) is a standard technique lifted from a separate mature literature (async-FL staleness compensation). Worse: the audit found that **DCPA's mechanism doesn't actually use the causal drift-dropout coupling at all** — it would behave identically whether dropout were exogenous or drift-caused. The causal premise is currently only in the motivating narrative, not in the algorithm.

**This is a YELLOW, not a GREEN, not a RED.** Full reasoning and the reframed design are below (Part 11 for verdict detail, Part 12 for the numbered final deliverable).

---

## PART 2 — Novelty-killing search results

### A. FL + MNAR / informative missingness
No paper uses MNAR/Rubin's-taxonomy language for **client-round participation**. One paper, [Federated Learning with Incomplete Data: When to Use Complete Cases and When to Weight (arXiv:2605.20125)](https://arxiv.org/abs/2605.20125), does use rigorous MCAR/MAR/MNAR language in FL — but for missing **records/covariates within a client's local dataset**, a different unit of missingness entirely. It's citable to show the taxonomy has FL precedent, but doesn't touch our claim.

### B. FL + drift-dependent participation
No hit. Every dropout/availability mechanism found (FedProx, SCAFFOLD, FedAPM, CA-Fed, DPFL/KPFL's three generators, the correlated-participation Markov model) is exogenous — driven by time, battery, network, or fixed/Markovian schedules, explicitly independent of local data content. One near-miss: [CAFE, "Drift-Aware Federated Learning: A Causal Perspective" (arXiv:2503.09116)](https://arxiv.org/abs/2503.09116) sounds like a direct hit but the causal arrow is **reversed** — it studies how participation frequency causes drift in the global model, not how drift causes dropout.

### C. Statistical missing-data correction methods transplanted into FL
[FedIPW / "Who Trains Matters" (arXiv:2604.26604)](https://arxiv.org/abs/2604.26604) is the only real hit — and it's the single most important citation in this whole audit, for two reasons at once: (1) it's the closest prior art, and (2) its own stated assumptions prove the gap is real. Its correction is IPW-based and requires an explicit **Mean Ignorability** assumption ("after conditioning on the observed covariates used in the selection model, inclusion does not change the conditional mean update") — i.e., it is provably valid only under MAR. The paper does not relax this, has no MNAR discussion, no hidden-confounding sensitivity analysis. **This is exactly the theoretical boundary condition our project needs to name and exploit**: IPW-style correction (the field's current best answer to participation bias) is mathematically inapplicable once dropout depends on the client's own current unobserved state.

### D. Broader adjacent literature
Nothing beyond the FL literature was needed — the gap is confined to how FL papers model participation, not a missing broader-ML technique.

---

## PART 3 — Closest-prior-art table (methodology-level, not abstract-level)

| Paper | What it models | What causes dropout/selection | Dropout related to current drift? | MNAR-capable? | Uses correction? | How close to our idea? |
|---|---|---|---|---|---|---|
| FedAvg | Uniform random sampling | N/A — exogenous by design | No | No | No | None |
| FedProx (1812.06127) | Straggler tolerance | Device/network resources | No (explicit quote: heterogeneity from "hardware, network connectivity, power") | No | No | None |
| SCAFFOLD (1910.06378) | Client-drift *correction*, not client dropout | Uniform sampling | No | No | No | None |
| FedDrift (2206.00799) | Concept drift across clients/time | **N/A — full participation assumed every round** ("clients... stateful and participating at each round") | Can't be, by construction | No | No (drift-clustering, not missingness) | Adjacent topic only; DCPA borrows its clustering step |
| DPFL/KPFL (2511.16523) | Configurable dynamic participation benchmark | 3 generators: Timed-Random, Markovian, Programmed — all "data-agnostic, treating participation as exogenous to client heterogeneity" | No, explicitly excluded | No (MAR/MCAR only) | KPFL plugin: **self**-stale-reuse with age/data-bias weighting, no cross-client proxy, no clustering | Explicitly names our exact gap as future work |
| Debiasing FL w/ Correlated Participation (2410.01209) | Markov-chain participation, min re-participation gap R | "Exclusively... time-based quantities... independent of current local data" (quote from agent's direct read) | No | MAR only | Yes, debiasing for correlated-but-MAR participation | Structurally similar-sounding, substantively different |
| FedIPW / Who Trains Matters (2604.26604) | Two-stage enrollment + participation selection | Observed covariates `Z_i, X_i,r` | **Explicitly assumed no** (Mean Ignorability) | No — MAR by assumption, not relaxed | Yes — IPW | **Closest paper overall**; its limitation is our opening |
| FedAPM (2409.17446) | Non-stationary unavailability | Schedule/hardware, assumed independent across rounds | No | No | Compensation, not MNAR-aware | None |
| Ditto (2012.04221) | Personalization for static heterogeneity | Exogenous/random | No | No | No | None |
| **FL-FDMS (2205.13222)** | **Friend-substitution for dropped clients** | Exogenous ("external events... rather than a decision of the FL algorithm") | No — dropout is exogenous in their framing, but their *fix* is structurally what DCPA proposes | No | **Yes — near-identical to DCPA's core mechanism** | **This is the real threat, see Part 5** |

---

## PART 4 — Auditing the central claim

> "No existing work quantifies FL performance when client dropout probability is a causal function of the client's current (unobserved) drift state."

**Verdict: (A) Clearly true, with the Part-1 definitional fix applied.** Every dropout mechanism found across 20+ papers audited at the methodology level is exogenous. FedDrift, the one paper modeling drift explicitly, sidesteps participation by assuming full participation. No paper's dropout-generating process takes the client's own current data/loss/drift as an input.

**Strongest defensible rewording** (tightened, with the identifiability caveat baked in so a statistician can't easily dismantle it):

> "Existing FL robustness and drift-adaptation methods (FedProx, SCAFFOLD, FedDrift, KPFL) validate against dropout mechanisms that are exogenous to the client's current local state, and existing participation-bias corrections (FedIPW) are provably valid only when dropout depends on observed covariates (MAR), not on the client's current unobserved drift/loss state itself (MNAR). Consequently, it is unknown how much FL performance degrades — and whether IPW-style correction remains valid — when dropout is causally coupled to the client's current, otherwise-unobserved drift state, a condition with real (if unproven) plausibility in low-resource IoT/wearable deployments (Part 9)."

---

## PART 5 — Killing DCPA

**DCPA is not a new mechanism as originally specified.** [FL-FDMS (arXiv:2205.13222)](https://arxiv.org/abs/2205.13222), "Combating Client Dropout in Federated Learning via Friend Model Substitution," already does almost exactly this, verified via full-text read:

| DCPA step | FL-FDMS equivalent |
|---|---|
| (1) Cluster online clients by drift signature | Pairwise "friend" discovery via cosine similarity of uploaded model updates, `r^{i,j}_t` |
| (2) Remember offline client's last-known cluster | Persistent exponential-moving-average similarity scores `R^{i,j}_t`, maintained across rounds |
| (3) Use online same-cluster peer's update as proxy | "Uses the local model update Δ^{φ_t(k)}_t as a substitute for Δ^k_t" — literally the same operation |
| (4) Discount by uncertainty/staleness | **Absent in FL-FDMS** — DCPA's one addition |
| (5) Aggregate real + proxy | Done identically in FL-FDMS |

Step (4) — DCPA's only genuinely new-relative-to-FL-FDMS piece — is not novel either: staleness/confidence discounting is standard, mature practice in asynchronous FL (FedStaleWeight, arXiv:2406.02877; FedRevive, arXiv:2511.00655; IEEE staleness-compensation literature), just applied there to a client's *own* delayed update rather than a borrowed peer's.

**The more damaging finding:** DCPA's five steps would execute identically whether dropout is exogenous (FL-FDMS's own setting) or drift-caused (our proposed setting). **Nothing in the algorithm actually consumes the causal-coupling assumption.** The MNAR premise currently lives only in the paper's motivating story, not in the method. That is precisely the "you didn't need the assumption you spent three pages justifying" failure mode a hostile reviewer is trained to spot.

**What would fix this:** DCPA needs to actually exploit the informativeness of *who* is currently missing — e.g., a Heckman-style joint model where a selection equation (estimated from observed participation patterns and each client's last-known drift signature) directly determines the discount/correction weight applied to a substitute, rather than a generic staleness clock. This borrows from econometric selection-correction (inverse-Mills-ratio-style weighting) rather than from clustering-plus-substitution, and it would be the first FL paper to build a missingness-*aware* (not just missingness-*tolerant*) aggregation correction. See Part 12 for the concrete reframed algorithm.

---

## PART 6 — Attacking the "superlinear degradation" hypothesis

1. **Why superlinear?** No derivation was ever given — it was chosen because it "sounds interesting," not because it follows from a model. This is a real weakness.
2. **Theoretically justified?** Partially arguable by analogy to Heckman selection bias (whose bias term involves a nonlinear inverse-Mills-ratio function of the selection correlation), but that analogy predicts a *convex/accelerating* shape in some regimes, not a clean "superlinear" (faster-than-linear, technically `f'' > 0` globally) curve everywhere.
3. **Could it be linear?** Yes — at small coupling strength, a first-order Taylor expansion of the selection-bias term is approximately linear. If anything, superlinearity is *least* likely at the low end of the range, which undercuts a blanket superlinear claim.
4. **Could it saturate?** Yes, and arguably more plausible: once dropout probability for high-drift clients approaches 1, further increases in coupling can't censor more signal — the curve should flatten. This predicts an S-shaped (sigmoid), not superlinear, response.
5. **Depends entirely on the dropout function?** Yes, confirmed. Logistic vs. threshold vs. rank-based dropout at *matched correlation* will differ in tail concentration and therefore in curve shape. Any curve-shape claim tested with only one functional form is not credible.
6. **Does ρ have a principled definition?** Not currently. Fix: report two quantities — the **structural parameter** actually swept in the generative model (e.g., logistic slope β) and the **realized correlation** ρ = corr(drift, dropout) computed post-hoc from the simulated trace, used as the cross-mechanism x-axis.
7. **Can two mechanisms share ρ but differ radically in effect?** Yes — established above. This is exactly why the benchmark (Part 7) must run ≥2–3 distinct mechanisms at matched realized ρ.
8. **Would reviewers call ρ synthetic?** Yes, almost certainly, unless anchored to something real.
9. **Can ρ be derived from a real causal/selection model?** Partially — fit a logistic selection model (dropout ~ lagged local-loss/anomaly signal) on the malaria-wearable or PurpleAir data (Part 9) to obtain an empirically-plausible β range, and use that as the anchor operating point in the synthetic sweep rather than an arbitrary range.

**Verdict: superlinear is not justified. Replace with a weaker, more defensible hypothesis** (see Part 12).

---

## PART 7 — Strongest defensible benchmark design

**Independent variables:** dropout mechanism, coupling strength, drift severity, non-IID severity, average client availability rate (held fixed as a control, not a free variable, across the core comparison).

**Dropout-mechanism families (mathematically specified, ≥3 required, not one):**

1. **MCAR:** `P(dropout_i,t = 1) = p₀` (constant), matched marginal rate across all conditions.
2. **MAR:** `P(dropout_i,t = 1) = σ(α + γ·X_i)`, where `X_i` is an *observable* covariate independent of current drift (e.g., a fixed device-class label, or time-since-last-participation as in 2410.01209). α calibrated so marginal rate matches MCAR.
3. **MNAR-logistic (primary):** `P(dropout_i,t = 1) = σ(α + β·drift_i,t)`, where `drift_i,t` is the client's current-round drift magnitude (e.g., KL divergence or loss-jump vs. last-communicated round). **β is the structural coupling parameter swept**; α re-calibrated at each β to hold the marginal dropout rate constant (critical — this isolates *informativeness* of missingness from *amount* of missingness, directly defusing the "you just increased dropout and of course performance dropped" objection). Realized ρ = corr(drift, dropout) reported as the comparable x-axis across mechanisms.
4. **MNAR-threshold (robustness check):** `dropout_i,t = 1` if `drift_i,t` exceeds a percentile threshold τ, else Bernoulli(p_base) — tests whether findings survive a non-sigmoid, harder-censoring mechanism.
5. **MNAR-rank (stretch):** dropout probability set by within-round rank of drift magnitude across clients, rather than absolute magnitude — models relative/competitive deprioritization (e.g., bandwidth contention), a plausible real mechanism distinct from absolute-threshold censoring.

**Design pruning (this is not a full cross-product — see Part 10 for why):** run the full mechanism × β sweep at one fixed moderate drift-severity / non-IID-severity / availability-rate operating point for the headline result; treat drift severity, non-IID severity, and availability-rate as **reduced secondary sweeps** (3 levels each, on the 2–3 strongest methods only), not a full factorial.

---

## PART 8 — Baseline and ablation matrix (revised to include FL-FDMS)

**The original baseline list had a critical omission: FL-FDMS was missing entirely**, despite being the closest existing method. Corrected list:

| Baseline | Necessary? | Why |
|---|---|---|
| FedAvg | Yes | Canonical floor |
| FedProx | Optional/droppable for scope | Largely dominated by SCAFFOLD in the literature; keep only if compute allows |
| SCAFFOLD | Yes | Canonical heterogeneity-robust baseline |
| FedDrift | Yes | Source of the clustering step; direct drift-aware SOTA |
| DPFL/KPFL | Yes | Closest existing "dynamic participation" solution; self-stale-reuse comparator |
| **FL-FDMS** | **Yes — mandatory, was missing** | The actual closest algorithm; DCPA must be shown to beat it, not just beat FedAvg |
| FedIPW-style debiasing | Yes | The MAR-correction boundary-condition comparator — must show it fails specifically under true MNAR |
| Naive imputation (mean/global-average substitute) | Yes, cheap | Naive floor distinct from "skip" (FedAvg) and from FL-FDMS's similarity-based substitute |
| Oracle (drift revealed even offline) | Yes | Upper bound |
| DCPA (reframed, Part 12) | The proposed method | — |

**Ablations that isolate the actual source of any gain** (critical — without these, the paper only shows "our method has more moving parts"):

- DCPA (full, reframed) vs. **FL-FDMS unmodified** — isolates whether the selection-aware discount adds anything beyond existing friend-substitution
- DCPA vs. **FedIPW-only** (reweight observed, no imputation) — isolates whether imputation adds anything beyond reweighting
- DCPA vs. **DCPA with generic staleness discount** (rounds-since-last-seen, no selection model) — isolates whether the *selection-model-derived* discount specifically (not just "any discount") is what matters
- DCPA vs. **self-stale-reuse** (KPFL-style, own last update, no cross-client borrowing) — isolates whether cross-client information is needed at all
- Oracle upper bound — bounds achievable gain

If DCPA-reframed can't beat FL-FDMS and FedIPW-only on this ablation ladder, **the algorithmic claim collapses to an empirical-characterization paper** — which is still fine, but must be stated as the fallback up front (see Part 12).

---

## PART 9 — Real-data feasibility (honest accounting)

**No dataset offers a rigorously published, quantitative, publicly-downloadable proof that dropout and drift are causally entangled at the client level.** Closest candidates, ranked honestly:

| Dataset | Drift signal | Dropout signal | Entanglement evidence | Access | Undergrad-feasible? |
|---|---|---|---|---|---|
| **Malaria/COVID wearable HR study (Kenya cohort)** | Real — infection onset is a genuine physiological regime change | Real — ~50% coverage during infection window, explicitly flagged in the paper | **Best available**: documented co-occurrence of connectivity loss and the infection window, though not rigorously isolated from generic low-resource connectivity issues | **Public, CC BY 4.0, Figshare** (DOI 10.6084/m9.figshare.31444399), no DUA | **Yes — best overall pick** |
| PurpleAir + wildfire smoke events | Real, well-labeled (CalFire event dates) | Real, anecdotally documented (sensors lose power in wildfires) but **no peer-reviewed quantitative analysis exists** | None published — student would have to compute it themselves from the public API | Public API (some cost for bulk historical pulls) | Yes, but the correlation becomes an *original contribution the student produces*, not a citable fact |
| SWaT / WADI (industrial control) | Excellent (labeled attack windows) | Real missingness present | Evidence suggests missingness is from **testbed network artifacts, independent of the attacks** — using this for the story requires synthetic imposition | Public via request form | Yes, but honestly only as a synthetic-injection substrate, not real validation |
| Diabetes CGM/Fitbit study | Real, rigorously MNAR-analyzed | Real, statistically confirmed MNAR (night/adherence-driven) | Real but weak — mechanism is daily/weekly rhythm, not acute glucose events | **Not publicly available** (ongoing recruitment, METC-restricted) | No |
| FedScale device-availability traces | None (no data-content signal) | Real, large-scale (180M events, 136K devices) | Indirect: diurnal/timezone correlation with language/culture, documented in CA-Fed and Bonawitz et al. — real but not "drift" in the anomaly sense | Fully public (GitHub) | Yes, for the FL-mechanics side only, needs pairing with a separate drift dataset |

**Recommended framing for the write-up:** use the malaria wearable dataset as the *empirical plausibility anchor*, described honestly as observed co-occurrence, not proven causation. All controlled coupling-strength experiments (the actual hypothesis tests) remain synthetic by necessity — state this plainly rather than presenting synthetic ρ-sweeps as if they were validated against real entanglement.

---

## PART 10 — Execution audit (2-semester undergrad reality check)

**Experiment matrix (pruned per Part 7's recommendation):**

- Core sweep: 3 mechanisms × 6 coupling levels (≈13 mechanism-coupling cells, since MCAR contributes one) × 6 methods (FedAvg, SCAFFOLD, FedDrift, KPFL, FL-FDMS, FedIPW) × 5 seeds × 2 datasets (FEMNIST, Office-Caltech) ≈ **780 runs**
- Ablation ladder: 5 DCPA variants × 6 MNAR coupling levels × 5 seeds × 2 datasets ≈ **300 runs**
- Secondary robustness sweeps (drift severity, non-IID severity, availability rate) on DCPA + 2 strongest baselines only, 3 levels each ≈ **~180 runs**
- **Total: ~1,200–1,300 individual FL simulation runs**

At LEAF-scale (small CNN/LSTM, ~100–300 rounds), each run is plausibly minutes to ~30 minutes on CPU/single-GPU; embarrassingly parallel across seeds/conditions. With modest parallel compute (8–16 concurrent jobs), wall-clock is on the order of 1–2 weeks of continuous compute — feasible in 2 semesters **only if scope is actively pruned**, not run as originally specified.

| Risk factor | Assessment |
|---|---|
| Implementation difficulty | Medium — FL simulators mature (Flower/LEAF); mechanism-injection and ablation logic is the real engineering lift |
| Compute cost | Low–medium, CPU/single-GPU sufficient |
| Debugging risk | Real — dropout-mechanism calibration (holding marginal rate fixed while varying β) is fiddly and easy to get subtly wrong |
| Statistical analysis burden | Moderate — 5 seeds/cell is thin for curve-shape claims; budget for bootstrap CIs, not just point estimates |
| **P(DCPA-as-reframed beats FL-FDMS/FedIPW cleanly)** | **~40–50%** — genuinely uncertain; this is the real risk in the project |
| P(clean empirical characterization result, regardless of DCPA) | High (~85%+) — the MCAR/MAR/MNAR comparison itself is low-risk and almost certain to show *something* |

**Minimum viable version:** the empirical characterization alone (mechanism comparison at matched dropout rate, using FL-FDMS/FedIPW/KPFL as existing methods that all fail to close the MNAR gap) — publishable as a workshop empirical-finding paper even if DCPA fails outright.

**Stretch version:** the full reframed DCPA (Part 12) beating the ablation ladder, upgrading to a main-track submission.

---

## PART 11 — Professor attack test (15 objections)

| # | Objection | Severity | Fatal? | Strongest answer | Experiment needed |
|---|---|---|---|---|---|
| 1 | "This is just correlated client participation." | High | No | Correlated-participation papers (2410.01209, CA-Fed) are provably MAR (dependence on time/schedule only, confirmed by direct methodology read); ours depends on the *current unobserved* state — a different regime entirely, per Part 1's formal distinction | Show the two mechanisms produce different degradation curves at matched marginal rate |
| 2 | "MNAR is a statistical label, not a new FL problem." | Medium | No | True that the label alone isn't the contribution — the contribution is showing FL's *existing* correction tools (IPW) are provably invalid here, and quantifying the resulting damage | The FedIPW-under-MNAR ablation must show real degradation vs. its MAR-regime performance |
| 3 | "FedIPW already solves selection bias." | High | No | Only under its own stated Mean Ignorability assumption — quote it directly, show empirically it breaks under drift-coupled dropout | Run FedIPW inside the MNAR condition, show it underperforms relative to MCAR/MAR |
| 4 | "Why do you need DCPA?" | **Very High** | **Partially, as originally specified** | As originally specified: weak answer, since DCPA ≈ FL-FDMS + generic staleness. Must reframe (Part 12) to a selection-aware discount that FL-FDMS/KPFL don't have | Ablation ladder (Part 8) is the whole answer here — must show real, isolated gain |
| 5 | "Why is proxy imputation valid?" | High | No | Because in the Part-1-corrected framing, cluster membership is the auxiliary proxy structure MNAR identification requires — not an ad hoc heuristic | State the identifiability argument explicitly in the methods section |
| 6 | "You cannot observe the missing client's drift." | High | No | Correct, and that's exactly why a *proxy* (same-cluster online neighbor, or a fitted selection model) is required rather than direct estimation — this is the standard MNAR-identification move | Same as above |
| 7 | "Your ρ is synthetic." | Medium-High | No | Partially conceded — mitigate by anchoring β to an empirically-fit selection model on the malaria/PurpleAir data (Part 6, Q9) | Fit and report the empirically-plausible β range before the synthetic sweep |
| 8 | "Your result is benchmark-specific." | Medium | No | Mitigate with ≥2 datasets (FEMNIST, Office-Caltech) and ≥2 dropout-mechanism families (logistic, threshold) | Already built into Part 7's design |
| 9 | "The superlinear hypothesis is arbitrary." | High | No (already conceded) | Replace with the weaker, mechanism-robust monotonicity hypothesis (Part 12) | N/A — hypothesis already revised |
| 10 | "This is just FedDrift + IPW." | **Very High** | **No, but close** | Wrong pairing — it's actually FL-FDMS + staleness-weighting, which is worse for us since FL-FDMS already does the imputation FedDrift doesn't. Must cite and differentiate from FL-FDMS explicitly in the first paragraph, or a reviewer who knows the literature will flag this immediately | Ablation vs. FL-FDMS directly |
| 11 | "What happens if the drift cluster itself becomes stale?" | Medium | No | Real, admitted limitation — the uncertainty discount is supposed to handle exactly this by decaying confidence; test explicitly via the "DCPA − uncertainty discount" ablation | Already in the ablation ladder |
| 12 | "Why should an offline client be represented by another client?" | Medium | No | Because under the MNAR proxy-identification argument, same-cluster similarity is the best available estimator of an unobservable quantity — not because it's assumed to be *correct*, but because it's the least-biased available estimator given the auxiliary structure | Compare against naive imputation and oracle to show where proxy-based estimation sits between the two |
| 13 | "What if the missing client is systematically different from every online client?" | **High** | **Partially fatal for that client, not for the paper** | Honest answer: DCPA (and any proxy method) fails here by construction — this is a real, stated limitation, not a solved case. The paper should report failure-mode analysis (how often does this occur, how much does it hurt) rather than pretend it away | Explicitly measure performance on clients with no valid same-cluster online neighbor at time of dropout |
| 14 | "What exactly is the theoretical contribution?" | High | No, if reframed | As originally specified: weak (an engineering recombination). Reframed (Part 12): applying selection-correction theory (Heckman-style, MNAR-identification-via-proxy) to FL aggregation is a genuine, if modest, theoretical contribution | N/A |
| 15 | "What makes this publication-worthy rather than just a class project?" | High | No | The empirical characterization alone (first controlled MNAR-vs-MAR-vs-MCAR comparison in FL, with the FedIPW-boundary-condition finding) clears a workshop bar on its own; the reframed algorithm is the upside case for a stronger venue | N/A |

**Two objections (#4, #10) are the real threats** — both stem from the same finding (FL-FDMS). Everything else survives with the fixes already incorporated above.

---

## PART 12 — GO / NO-GO DECISION

# **YELLOW — pursue only after narrowing/reframing**

The empirical research gap is real and well-evidenced (D novelty, survives hostile search). The originally-proposed algorithmic contribution (DCPA as specified) does not survive — it is a recombination of FL-FDMS's friend-substitution mechanism with standard async-FL staleness discounting, and critically, its steps don't actually use the causal drift-coupling premise the paper is built around. This is fixable, not fatal, but the project as originally scoped should not proceed unmodified.

### Revised research question
*Does client dropout that is causally coupled to the client's own current (otherwise-latent) concept drift degrade federated learning beyond what equal-magnitude exogenous dropout produces — and does existing state-of-the-art participation-bias correction (IPW-style debiasing, friend-substitution imputation) remain valid under this coupling, or does it require explicitly selection-aware correction?*

### Revised, defensible novelty claim (one sentence)
*No existing federated learning method models or corrects for client participation that depends on the client's own current, unobserved concept-drift state — the field's best available correction (FedIPW) is provably valid only under the weaker missing-at-random assumption it never relaxes, and the field's best available imputation method (FL-FDMS) borrows a peer's update without ever using drift-informativeness to weight that substitution.*

### Minimum viable experimental design (this is the actual project — pursue this, not the original scope)
1. Build the MCAR/MAR/MNAR-logistic/MNAR-threshold benchmark (Part 7), holding marginal dropout rate fixed across conditions.
2. Run FedAvg, SCAFFOLD, FedDrift, KPFL, **FL-FDMS**, FedIPW across all conditions (Part 8's corrected baseline list).
3. **Headline result (low-risk, near-certain to produce something publishable):** show that all six existing methods degrade significantly more under MNAR than under MCAR/MAR at matched dropout rate, and that FedIPW's advantage over naive skipping vanishes or reverses specifically in the MNAR condition (validating the Mean Ignorability boundary directly).
4. **Stretch algorithmic contribution (the upside case):** reframe DCPA as **Selection-Aware Proxy Aggregation (SAPA)** — replace DCPA's generic staleness discount with a discount weight derived from a fitted selection/propensity model (dropout ~ each client's last-observed drift signature), applied on top of FL-FDMS-style friend substitution. This is the one piece of design space not already occupied by FL-FDMS or FedIPW alone. Test via the ablation ladder in Part 8; if it doesn't clearly beat FL-FDMS and FedIPW-only, the paper still stands on step 3 alone.
5. Anchor the coupling-strength range to an empirically-fit selection model on the malaria-wearable dataset (Part 9) rather than an arbitrary sweep.
6. State up front, in the paper's own limitations section, the two conceded weaknesses from this audit: (a) primary experiments are synthetic, real-data component is a plausibility anchor only; (b) proxy-based correction fails by construction when a dropped-out client has no valid online analogue — measure and report this failure rate rather than hiding it.

This version is smaller, more honest, and — critically — survives the two objections (#4, #10) that killed the original design, because the empirical half doesn't need DCPA to succeed at all, and the algorithmic half (SAPA) is explicitly positioned as *extending* FL-FDMS and FedIPW rather than reinventing them from scratch.
