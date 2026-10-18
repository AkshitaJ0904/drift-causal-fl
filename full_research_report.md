# Full Research Report: Discovery + Adversarial Audit

*Consolidated record of the entire research-scoping process: (I) the structured novelty investigation across five literature-mapped niches and ten candidate projects, and (II) the hostile-reviewer kill-attempt run specifically against the #1-ranked candidate. Prepared 2026-09-09.*

**How to read this document:** Part I is the discovery pass — broad, literature-grounded, optimistic-but-honest. Part II is the adversarial pass — narrow, hostile, written specifically to try to kill Part I's top pick. Part II's verdict (YELLOW, reframe required) supersedes Part I's framing of Candidate #1 wherever they conflict; Part I is kept intact below rather than edited, so the full reasoning trail — including what didn't survive scrutiny — stays visible.

---

# PART I — Research Gap Discovery

*A structured novelty investigation for an undergraduate / early-graduate research project — CS/AI/Systems*

Method: 5 parallel literature-mapping passes over arXiv, Semantic Scholar, ACL Anthology, ACM/IEEE, Google Scholar, plus PI-level synthesis.

## Methodology & honesty notes

Five specialized research agents independently ran live searches (WebSearch/WebFetch against arxiv.org, Semantic Scholar, ACL Anthology, ACM DL, IEEE Xplore listings, Google Scholar, OpenReview) over five candidate niches, each instructed to report only papers actually retrieved, with real titles/authors/years/venues/URLs, and to flag uncertainty explicitly. Every paper cited below traces to one of those five reports and carries a link. **None of the 30+ cited papers were fabricated or guessed from training memory** — several 2025–2026 preprints were cross-checked because they postdate reliable training knowledge.

> **Where this falls short of a full systematic review.** The 20-source, dozen-venue systematic review implied by a full research-methodology spec (ACM DL, IEEE Xplore, Springer, ScienceDirect, patent search, dissertation databases, full-text close-reading of every related paper) was not executed at that scale — this was five deep-but-bounded passes (~20–25 tool calls each), not a multi-week systematic review. Treat the novelty classifications below as **well-evidenced working estimates**, not a guarantee no closer paper exists; the "evidence threatening novelty" field in each candidate is the honest record of the closest prior art actually found, including two cases where it meaningfully weakens the claim (Candidates 4 and 5). Phase 0's area list beyond the five deep-dived niches reflects PI-level domain scoping, not independent literature verification — it is disclosed as such.

## Phase 0 — Search space & area ranking

18 candidate areas were scoped from known structural gaps (disjoint literatures, contested assumptions, benchmark realism gaps). The five with the best combination of gap density, feasibility, and timeliness were carried into full literature mapping (✓). The other five final candidates (6–10) are sub-questions that emerged organically from inside those five deep-dive reports — not independently searched territory.

| Area | Gap density | Feasibility | Status |
|---|---|---|---|
| Federated/edge learning realism gaps (informative dropout, non-stationary drift) | High | High | ✓ investigated |
| Multi-agent LLM systems trust/security under adversarial agents | High | Med | ✓ investigated |
| Human-AI trust calibration in AI-assisted software engineering | High | Med | ✓ investigated |
| LLM agent long-horizon memory & context management | Med (crowding fast) | Med | ✓ investigated |
| RAG faithfulness under non-stationary/temporal-conflict corpora | Med (crowding fast) | High | ✓ investigated |
| LLM watermarking robustness under paraphrase/translation attack | Med | Med | scoped only |
| Continual learning / catastrophic forgetting in deployed edge vision | Med | Med | scoped only |
| Benchmark contamination/memorization detection in code LLMs | Med | Med | scoped only |
| LLM-as-judge robustness under adversarial prompt gaming | Med | High | scoped only |
| Sim-to-real transfer failures in learned manipulation policies | Med | Low (hardware) | scoped only |
| Cross-modal hallucination under conflicting modalities | Med | Med | scoped only |
| Privacy leakage via membership inference on RAG corpora | Med | Med | scoped only |
| Fairness–robustness tradeoffs in adversarial training | Low (mature) | High | scoped only |
| Reproducibility failures from undocumented LLM API drift | Med | High | scoped only |
| Long-tail perception failures in autonomous driving | Low (well-funded already) | Low | scoped only |

## Phase 15 — Ten candidates, full specification

### 1. Federated Learning Under Missing-Not-At-Random (MNAR) Client Participation

**Novelty: D — Strong candidate** · `algorithmic` `systems` · ⭐ TOP 3 · **See Part II for full adversarial audit — verdict YELLOW, reframing required**

> Existing FL robustness methods assume client dropout is statistically independent of the data drift it would reveal — this tests and fixes what happens when dropout is *caused by* the drift itself.

- **Field:** Distributed Systems / Machine Learning (Federated Learning)
- **Problem:** FL robustness and drift-adaptation methods are validated under dropout mechanisms that are exogenous to (independent of) each client's current data state, but real edge deployments plausibly have dropout *caused by* the same conditions that produce drift (e.g., a sensor going offline exactly when it would report an anomaly).
- **Known:** FedAvg/FedProx/SCAFFOLD establish convergence under static or i.i.d.-violating-but-time-invariant heterogeneity. FedDrift handles drift staggered across clients and time but treats per-round availability as given. Two disjoint threads — (a) concept-drift-across-clients (FedDrift) and (b) correlated/selection-biased participation (FedIPW-style debiasing, enrollment-selection models) — do not intersect: neither ties *why* a client is offline to its *current* local distribution.
- **Closest 5–10 papers:** LEAF (Caldas et al., [arXiv:1812.01097](https://arxiv.org/abs/1812.01097)); FedProx (Li et al., MLSys 2020, [1812.06127](https://arxiv.org/abs/1812.06127)); SCAFFOLD (Karimireddy et al., ICML 2020, [1910.06378](https://arxiv.org/abs/1910.06378)); FedDrift (Jothimurugesan et al., AISTATS 2023, [2206.00799](https://arxiv.org/abs/2206.00799)); DPFL/KPFL (AAAI-26 workshop, [2511.16523](https://arxiv.org/abs/2511.16523)); Debiasing FL w/ Correlated Participation ([2410.01209](https://arxiv.org/abs/2410.01209)); "Who Trains Matters" / FedIPW ([2604.26604](https://arxiv.org/abs/2604.26604)); FedAPM ([2409.17446](https://arxiv.org/abs/2409.17446)); Ditto (Li et al., ICML 2021, [2012.04221](https://arxiv.org/abs/2012.04221)); Kairouz et al. survey ([1912.04977](https://arxiv.org/abs/1912.04977)).
- **Limitations in those papers:** FedProx/SCAFFOLD: heterogeneity is static, participation is exogenous systems-load noise. FedDrift: drift modeled per-client-per-round but availability assumed given, not caused by drift. DPFL/KPFL explicitly generate participation independent of data heterogeneity and name "more realistic participation scenarios" as future work. FedIPW/"Who Trains Matters" models selection bias generally but isn't tied to a drift/anomaly mechanism and is validated only on synthetic federated logistic regression.
- **Exact gap:** No existing work quantifies FL performance when client dropout probability is a causal function of the client's current (unobserved) drift state — informative/non-ignorable missingness in the MNAR sense — rather than missing-completely-at-random or covariate-dependent-but-drift-independent.
- **Why it matters:** If true, every reported robustness number for FedAvg/FedProx/SCAFFOLD/FedDrift under "realistic" dropout is optimistic for exactly the deployment scenarios (industrial IoT, anomaly detection, health wearables) where catching the drift is the point — the model would be systematically blind to exactly the clients most worth learning from.
- **Proposed solution (original, pre-audit):** (1) A benchmark protocol that injects a tunable causal coupling ρ between per-client drift magnitude and per-round dropout probability on top of standard FL benchmarks (LEAF FEMNIST/Shakespeare, Office-Caltech-10 as used by DPFL). (2) Drift-Cluster Proxy Aggregation (DCPA): extends FedDrift's drift-clustering with an MNAR correction — currently-offline clients are represented in aggregation via a proxy drawn from the most similar currently-online client in their last-known drift cluster, with an uncertainty-weighted discount as cluster confidence degrades. **[Part II found this proposed algorithm is not novel as specified — see Part II §5. Revised algorithm (SAPA) is in Part II §12.]**
- **Novel mechanism (original):** Coupling FedDrift-style drift clustering (a systems technique) with Rubin's missing-data taxonomy (MCAR/MAR/MNAR, a statistical framework never applied to FL client participation) to derive a principled proxy-imputation correction.
- **Hypothesis (original — revised in Part II §6 and §12):** As coupling strength ρ between drift and dropout increases from 0 (MCAR) to 1 (fully informative), global model error for FedAvg/FedProx/SCAFFOLD/FedDrift will grow *superlinearly* in ρ, significantly exceeding their published degradation under equal-magnitude MCAR dropout; DCPA will reduce this excess error by ≥20% relative to the strongest baseline at ρ≥0.6, while matching baseline performance at ρ=0.
- **Dataset:** LEAF FEMNIST & Shakespeare (synthetic controlled ρ injection); Office-Caltech-10 federated split (DPFL's own setup, for direct baseline comparability); stretch goal: a public industrial-IoT anomaly-detection dataset with synthetically injected connectivity coupling as an external-validity check. **[Part II §9 found a stronger real-data candidate — see below.]**
- **Experimental setup:** Sweep ρ ∈ {0, .2, .4, .6, .8, 1.0} × 3 non-IID severity levels × 5 baselines (FedAvg, FedProx, SCAFFOLD, FedDrift, KPFL) + DCPA, 5 seeds each. **[Part II §7–8 substantially revises this design — missing baseline added, mechanism families expanded.]**
- **Baselines:** Classical: FedAvg. Heterogeneity-robust: FedProx, SCAFFOLD. Drift-aware SOTA: FedDrift, KPFL. Selection-bias-aware: FedIPW-style debiasing (2410.01209). Ablation: DCPA without the drift-cluster proxy (plain IPW under MNAR). **[Part II found this list was missing the single closest prior algorithm, FL-FDMS — corrected list in Part II §8.]**
- **Metrics:** Global test accuracy vs. ρ; worst-client / variance-based fairness; drift-detection recall restricted to the informatively-dropped-out subpopulation; wall-clock/communication overhead of DCPA vs. baselines.
- **Ablations:** (a) DCPA − drift clustering (plain proxy nearest-neighbor); (b) DCPA − uncertainty discount; (c) oracle upper bound (drift state revealed even when offline) to bound achievable gains.
- **Expected result (original):** A clear, statistically significant degradation curve in ρ for all five baselines that is absent or much flatter at ρ=0, with DCPA closing a majority of the gap at high ρ.
- **What would falsify it:** If baseline degradation curves are flat in ρ, or DCPA fails to beat the FedIPW ablation at any ρ, the hypothesis is falsified.
- **Expected contribution:** First controlled, quantitative characterization of FL robustness under drift-caused (not just drift-and-dropout-coexisting) missingness, plus a proxy-correction method with a stated, testable boundary condition.
- **Novelty classification:** **D** for the empirical gap (CONFIRMED by Part II's hostile audit); the DCPA algorithm itself was found NOT to independently clear this bar (Part II §5).
- **Evidence supporting novelty:** DPFL/KPFL (Nov 2025) explicitly states its participation generators are independent of data heterogeneity and lists "more realistic participation scenarios" as future work.
- **Evidence threatening novelty:** "Who Trains Matters" (2604.26604) is a general selection-bias framework close in spirit. **Confirmed in Part II to be the closest paper overall, but its own stated Mean Ignorability (MAR) assumption is what preserves — not threatens — the core empirical gap.** The real threat, found only in Part II, was to DCPA specifically (FL-FDMS, arXiv:2205.13222).
- **Implementation difficulty:** Medium. **Compute requirement:** Low–medium. **Expected duration:** 2 semesters (Part II §10 gives a detailed, pruned experiment-matrix estimate: ~1,200–1,300 runs).
- **Publication potential:** FL-focused workshops at NeurIPS/AISTATS/MLSys, or a systems/ML venue with a robustness angle.
- **Reviewer #2 objections / Professor attack-test:** See Part II §11 for the full 15-objection hostile pass — this supersedes the abbreviated version originally drafted here.

---

### 2. Risk-Differentiated Trust Calibration in AI-Assisted Coding

**Novelty: D — Strong candidate** · `empirical` `HCI/SE` · ⭐ TOP 3 *(not adversarially audited — see note at end of document)*

> Do developers actually scrutinize AI code suggestions more when the code is security-sensitive, or does trust stay flat regardless of stakes — measured behaviorally, within the same developer?

- **Field:** Human-AI Interaction / Software Engineering (CHI, FSE, ICSE)
- **Problem:** Developer trust in AI coding assistants is measured almost entirely as a single undifferentiated construct (acceptance rate, self-reported trust), while whether scrutiny actually tracks the real risk of the code being suggested (auth/crypto/SQL vs. boilerplate) — within the same developer, same session — is unmeasured.
- **Known:** AI-assisted developers write measurably less secure code while feeling *more* confident it's secure (Perry et al., CCS 2023). Acceptance rate is the dominant behavioral proxy used across the field (Ziegler et al., CACM 2024) despite recent evidence that self-reported trust doesn't predict acceptance behavior (Gardella et al. 2026). Confidence-signal design matters, but not the way expected: raw model-confidence highlighting gave no benefit over nothing; edit-likelihood highlighting did (Vasconcelos et al., TOCHI 2024).
- **Closest 5–10 papers:** Perry, Srivastava, Kumar, Boneh, CCS 2023 ([2211.03622](https://arxiv.org/abs/2211.03622)); Ziegler et al., CACM 2024; Vasconcelos, Bansal, Fourney, Liao, Vaughan, TOCHI 2024 ([2302.07248](https://arxiv.org/abs/2302.07248)); Wang, Cheng, Ford, Zimmermann, FAccT 2024 ([2305.11248](https://arxiv.org/abs/2305.11248)); Brown, D'Angelo, Murillo, Jaspan, Green, AIware 2024; Baltes, Speith, Chiteri et al. ([2504.12461](https://arxiv.org/abs/2504.12461), 2026 v3); Ferino, Hoda, Grundy, Treude, FSE Companion 2026 ([2604.10530](https://arxiv.org/abs/2604.10530)); Gardella, Bolton, Riggs ([2604.18948](https://arxiv.org/abs/2604.18948)).
- **Limitations in those papers:** Perry et al.: single dated model, lab tasks. Brown et al.: context operationalized as file type/length, not a security-risk taxonomy. Wang et al. and Ferino et al.: qualitative, note context *should* matter but don't measure it behaviorally. Baltes et al. (2026) explicitly names "risk differentiation" as missing from the field.
- **Exact gap:** No study measures, within the same developer/session, whether behavioral scrutiny differs by code-risk category using a manipulated or measured risk taxonomy.
- **Why it matters:** If scrutiny is flat regardless of stakes, the Perry et al. finding generalizes to a stable behavioral pattern with direct implications for risk-adaptive tool design.
- **Proposed solution:** A within-subject lab study (Vasconcelos-style controlled task battery) crossing risk category (auth/crypto/SQL vs. boilerplate) with suggestion correctness. Secondary arm: mine real Copilot/Cursor-style session logs.
- **Novel mechanism:** Operationalizing "risk category" as a manipulated within-subject factor crossed with suggestion correctness.
- **Hypothesis:** Acceptance rate and edit depth will not differ significantly by risk category, while defect-catch rate for subtly-flawed high-risk suggestions will be no higher than for low-risk ones — developers do not compensate for higher stakes with proportionally higher scrutiny.
- **Dataset:** Novel matched task battery (~16–24 tasks), IRB-approved participant pool (n≈30–40); secondary anonymized session logs.
- **Experimental setup:** 2×2 within-subject design (risk category × suggestion correctness), counterbalanced, screen+interaction logging, Muir-scale trust survey.
- **Baselines:** Null model (uniform scrutiny); no-AI control; edit-likelihood-highlighting arm.
- **Metrics:** Acceptance rate, edit depth, time-to-decision, flaw-catch rate by category; self-reported trust.
- **Ablations:** Explicit risk labeling on/off; edit-likelihood highlighting on/off; novice vs. experienced subgroup.
- **Expected result:** Flat or near-flat scrutiny across risk category at baseline.
- **What would falsify it:** Significantly higher flaw-catch rate/edit depth for high-risk tasks even without signaling.
- **Expected contribution:** First behavioral, within-subject evidence on risk-calibrated scrutiny of AI code suggestions.
- **Novelty classification:** **D** — gap explicitly named by a 2026 critical review.
- **Evidence supporting novelty:** Baltes et al. (2504.12461 v3, 2026) explicitly states the field lacks "risk differentiation."
- **Evidence threatening novelty:** Brown et al. (AIware 2024) shows acceptance varies with some contextual proxies (not a risk taxonomy).
- **Implementation difficulty:** Medium (IRB-bound). **Compute requirement:** Minimal. **Expected duration:** 2–3 semesters (IRB timeline is the main schedule risk).
- **Publication potential:** CHI, FSE, CSCW, ICSE, or FAccT.
- **Reviewer #2 objections:** Small-n generalizability; risk-taxonomy subjectivity; "isn't this just Perry et al. with a label added." **Answers:** secondary log-mining arm for ecological validity; ground taxonomy in OWASP/CWE categories; core manipulation (risk category, within-subject) is genuinely untested by Perry et al.
- **Professor attack-test result:** Survives; main vulnerability is IRB/timeline risk, not scientific defensibility.

---

### 3. Byzantine Robustness of Multi-Agent LLM Systems Under Strategic, Realistic-Task Adversaries

**Novelty: C — Underexplored** · `algorithmic` `security` `frontier` · ⭐ TOP 3 *(not adversarially audited)*

> Existing Byzantine-robust multi-agent LLM work tests math/logic toy tasks with naive wrong-answer adversaries — this tests strategic and colluding adversaries on realistic collaborative-coding tasks, benchmarked against classical BFT degradation curves.

- **Field:** Multi-Agent Systems / AI Security (NeurIPS/ICML MAS workshops, USENIX Security, CCS)
- **Problem:** Multi-agent LLM systems are deployed on an implicit honest-agent assumption; the emerging Byzantine-robustness literature relaxing this is validated mostly on math/logic puzzles with naive adversaries, not realistic tasks with strategic/colluding ones.
- **Known:** MAD's claimed accuracy gains are contested even absent adversaries (Zhang et al. 2502.08788; Wynn et al. 2509.05396 — sycophancy alone causes decline). A single adversarial/misleading agent can flip outcomes with high success (Wiesmeier et al. 2026), and prompt injection self-replicates through inter-agent messages (Lee & Tiwari, 2410.07283). SAC (Lee, Yun, Panagou, Karimireddy, EMNLP 2026, [2605.09076](https://arxiv.org/abs/2605.09076)) explicitly parameterizes degradation by Byzantine fraction F/N with graph-theoretic guarantees, but on math/commonsense only.
- **Closest 5–10 papers:** Du, Li, Torralba, Tenenbaum, Mordatch, ICML 2024 ([2305.14325](https://arxiv.org/abs/2305.14325)); Zhang et al. ([2502.08788](https://arxiv.org/abs/2502.08788)); Wynn, Satija, Hadfield ([2509.05396](https://arxiv.org/abs/2509.05396)); Lee & Tiwari ([2410.07283](https://arxiv.org/abs/2410.07283)); TAMAS (Kavathekar et al., [2511.05269](https://arxiv.org/abs/2511.05269)); SAC ([2605.09076](https://arxiv.org/abs/2605.09076)); DecentLLMs (Jo & Park, [2507.14928](https://arxiv.org/abs/2507.14928)); Wiesmeier et al., Frontiers in AI 2026; Becker, Wahle, Ruas, Gipp ([2606.16710](https://arxiv.org/abs/2606.16710)); BAD-ACTS ([2508.16481](https://arxiv.org/abs/2508.16481)).
- **Limitations in those papers:** SAC: math/commonsense only, no strategy variation. TAMAS/BAD-ACTS: attack-taxonomy, not fraction sweeps. Wiesmeier et al.: N≤6, leader/advisor structure. Becker et al.: benign propagation, not strategic adversaries.
- **Exact gap:** No paper combines (i) realistic collaborative task, (ii) fraction-and-strategy sweep (naive/persuasive/colluding), (iii) framing against classical BFT thresholds.
- **Why it matters:** Multi-agent coding/review tools deployed now; degradation below the classical 1/3 threshold under strategic adversaries is directly actionable.
- **Proposed solution:** Multi-agent PR review/bug-fix consensus on SWE-bench-style issues, sweeping adversarial fraction × strategy × consensus protocol (majority vote, SAC, leader-based).
- **Novel mechanism:** Testing whether the classical BFT 1/3-corruption bound transfers to stochastic, natural-language-mediated LLM consensus.
- **Hypothesis:** Degradation exceeds the classical BFT prediction under persuasive/colluding strategies; SAC's advantage over majority vote narrows under collusion.
- **Dataset:** SWE-bench-Lite subset, adapted into multi-agent consensus protocol; validated adversarial personas per strategy class.
- **Experimental setup:** N=7 or 9 agents, fraction ∈ {0, 1/9, 2/9, 1/3, 4/9}, strategy ∈ {naive, persuasive, colluding}, protocol ∈ {majority, SAC, leader}, 3 model families.
- **Baselines:** Single-agent floor; majority vote; SAC; leader-based coordination.
- **Metrics:** Task success rate vs. fraction/strategy; effective robustness score; degradation-curve slope vs. classical BFT step function.
- **Ablations:** Colluding vs. independent-identical-strategy; homogeneous vs. heterogeneous model pools; with/without SAC's graph mechanism.
- **Expected result:** BFT-matching curve under naive adversaries, earlier breakdown under persuasive/colluding.
- **What would falsify it:** Strategy-invariant degradation, or SAC's margin holding constant across strategies.
- **Expected contribution:** First test of BFT-threshold transfer to LLM multi-agent consensus under realistic tasks and strategic adversaries.
- **Novelty classification:** **C** — SAC is close prior art, must be directly differentiated.
- **Evidence supporting novelty:** SAC scoped to math/commonsense only.
- **Evidence threatening novelty:** SAC already does the core F/N sweep with formal guarantees — the single biggest novelty risk in the original ten-candidate set.
- **Implementation difficulty:** Medium-high. **Compute requirement:** Medium (many API calls). **Expected duration:** 2 semesters, real scope-creep risk.
- **Publication potential:** NeurIPS/ICML MAS workshop first; potential USENIX Security/CCS upgrade.
- **Reviewer #2 objections:** "SAC already did the sweep"; "are colluding prompts a real threat model"; compute-budget skepticism. **Answers:** state the SAC delta explicitly up front (strategy dimension + realistic task); validate collusion prompts via manipulation-check; fix compute budget early.
- **Professor attack-test result:** Partially survives — the "why isn't this just SAC + harder prompts" objection must be answered sharply or the project should be downgraded relative to Candidates 1–2.

---

### 4. Binding-Constraint Retention Under Context Compression in Realistic Long-Horizon Agents

**Novelty: C — Underexplored (crowding fast)** · `benchmark` `agents` *(not adversarially audited)*

> Does context compression in LLM coding/web agents preserve exact action-critical facts (IDs, filenames, numeric constraints) on real long-horizon benchmarks, not just a synthetic proxy task?

- **Field:** NLP / AI Agents
- **Problem:** LLM agents rely on context compression to manage token budgets; whether compression preserves exact action-critical facts vs. general topical content is largely untested on real agent benchmarks.
- **Known:** A 2026 preprint (Sun et al.) shows standard compression drives forbidden-action rates to 54.2% in a **synthetic "safety blocker" testbed**. Mehta et al. show plan signal decays 4.1–12.4x within one step, costing 34.7pp on ALFWorld. ACON/AdaCoM report net-positive compression results but measure end-task success, not fact-level fidelity.
- **Closest 5–10 papers:** Sun et al. ([2608.24569](https://arxiv.org/abs/2608.24569)); Gelvan et al. ([2605.11051](https://arxiv.org/abs/2605.11051)); Mehta et al. ([2606.22953](https://arxiv.org/abs/2606.22953)); ACON ([2510.00615](https://arxiv.org/abs/2510.00615)); Long-Horizon Task Mirage ([2604.11978](https://arxiv.org/abs/2604.11978)); Context Rot in Long-horizon Search ([2606.29718](https://arxiv.org/abs/2606.29718)); AdaCoM ([2605.30785](https://arxiv.org/abs/2605.30785)); SWE-Bench Pro ([2509.16941](https://arxiv.org/abs/2509.16941)).
- **Limitations in those papers:** Sun et al. uses a synthetic single-domain proxy, not real code/web artifacts. Gelvan et al. explicitly defer root-cause isolation. ACON/AdaCoM don't report fact-level fidelity.
- **Exact gap:** No paper measures exact-match retention of action-critical primitives on real SWE-bench/WebArena-scale trajectories.
- **Why it matters:** If the synthetic finding generalizes, current SOTA compressors may silently fail on exactly the failures that matter most.
- **Proposed solution:** Diagnostic benchmark on SWE-bench-Lite/WebArena trajectories with automated entity extraction (AST/DOM-based) as the retention probe.
- **Novelty classification:** **C — weakest of the ten candidates.** Sun et al. (Aug 2026) is functionally the same core idea already published, just in a synthetic domain. **Not recommended as a top-3 pick.**
- **Professor attack-test result:** Weakest on the "why hasn't someone done this" test, because someone essentially has.

*(Full field-by-field detail preserved from the original discovery pass; abbreviated here since this candidate was explicitly not recommended.)*

---

### 5. Generation-Level Faithfulness Under Temporal-Conflict Density in RAG

**Novelty: C — Underexplored (crowded space)** · `benchmark` `NLP` *(not adversarially audited)*

> As the fraction of retrieved-but-superseded passages increases, does end-to-end RAG generation faithfulness degrade in a measurable dose-response curve — and does exposing recency metadata fix it?

- **Field:** NLP / Information Retrieval
- **Problem:** Standard RAG faithfulness benchmarks assume static, non-contradictory corpora; real corpora accumulate stale-but-indexed documents.
- **Known:** FreshLLMs/FreshQA show all tested LLMs struggle on fast-changing facts. HoH shows outdated info degrades accuracy even when current info is co-present. Temporal Wiki/Unified Clark show LLMs are misled by multiple fact-versions. FRESCO (2026) shows rerankers prefer stale-but-dense passages 84–98% of the time — but at the reranking stage only.
- **Closest 5–10 papers:** KILT ([2009.02252](https://arxiv.org/abs/2009.02252)); Lost in the Middle ([2307.03172](https://arxiv.org/abs/2307.03172)); FreshLLMs/FreshQA ([2310.03214](https://arxiv.org/abs/2310.03214)); HoH ([2503.04800](https://arxiv.org/abs/2503.04800)); RAMDocs/MADAM-RAG ([2504.13079](https://arxiv.org/abs/2504.13079)); Temporal Wiki ([2506.07270](https://arxiv.org/abs/2506.07270)); FRESCO ([2604.14227](https://arxiv.org/abs/2604.14227)); Knowledge Conflicts Survey ([2403.08319](https://arxiv.org/abs/2403.08319)).
- **Exact gap:** No paper parametrically varies temporal-conflict density while toggling recency-signal visibility, measuring end-to-end generation faithfulness.
- **Novelty classification:** **C** — underexplored but crowded; highest 2026 preprint velocity of any candidate in the set, real risk of being scooped between proposal and completion.
- **Professor attack-test result:** Survives conditionally; recommend as a strong secondary candidate, not the primary bet, given how fast the space is moving.

*(Full field-by-field detail preserved from the original discovery pass.)*

---

### 6–10. Derivative candidates (emerged from within the five deep-dive reports, not independently searched)

| # | Candidate | Emerges from | Novelty | One-line gap |
|---|---|---|---|---|
| 6 | Decoupling sycophancy-driven debate collapse from adversarial attack | Candidate 3 | C | Does BFT-robust aggregation help at all against pure social-conformity collapse (no adversaries), or only against real Byzantine agents? |
| 7 | Locating temporal-conflict failure: reranker vs. generator | Candidate 5 | C | With oracle (perfectly-ranked) retrieval, does generation faithfulness still fail — i.e., is FRESCO's reranker-stage failure the whole story or only half of it? |
| 8 | Does confidence-signal *framing* (not just presence) change risk-differentiated trust calibration? | Candidate 2 | C | Does edit-likelihood highlighting's known calibration advantage hold, shrink, or reverse specifically for security-sensitive code? |
| 9 | Reconciling personalization–robustness tradeoff under temporally correlated drift | Candidate 1 | C | Does Ditto's fairness/robustness win (static non-IID) survive under FedDrift's temporally-staggered drift regime? |
| 10 | Capability-dependent compression policy for binding-constraint preservation | Candidate 4 | C | Does AdaCoM's general fidelity-reliability tradeoff apply specifically to binding-constraint retention, or do weaker models need disproportionately more protection? |

*(Full specification for each — problem, hypothesis, novelty evidence, implementation/compute/duration estimates, reviewer objections — preserved from the original discovery pass; each is explicitly framed as a natural sub-study of its parent candidate rather than a fully independent project.)*

---

## Top 3, ranked (as originally selected)

| Rank | Candidate | Type | Novelty | Key strength | Key risk |
|---|---|---|---|---|---|
| **1** | FL under MNAR client participation | Algorithmic | D | Cleanest falsifiability, no IRB, strong existing baselines | **Confirmed in Part II: DCPA-as-specified is not novel; empirical gap survives, algorithm needs reframing** |
| 2 | Risk-differentiated trust calibration | Empirical/HCI | D | Gap explicitly named by a 2026 critical review | IRB timeline risk |
| 3 | Multi-agent Byzantine robustness, strategic adversaries | Frontier/Algorithmic | C | Hot, fast-moving frontier | SAC is close prior art — differentiation burden is highest |

These three were deliberately heterogeneous (algorithmic / empirical-human-subjects / emerging-frontier). Candidate 1 was selected as the primary recommendation for its execution-risk profile — which Part II confirms as correct for the *empirical* half of the project, while correcting the *algorithmic* half.

---

# PART II — Adversarial Novelty Audit: Candidate #1

*Hostile-reviewer pass, conducted against Candidate #1 only, immediately after Part I. Three additional live literature agents ran deep methodology audits (fetching actual paper text, not abstracts) specifically trying to kill this idea. Their findings are integrated below; nothing here was softened for narrative convenience.*

## 1. Definitional audit (is our use of "MNAR" defensible?)

**Formal definitions (Rubin, 1976; Little & Rubin, 2002).** Let `Y` = the outcome/state of interest, `R` = observation indicator (1 = observed), `X` = observed covariates.

- **MCAR** — `P(R | Y, X) = P(R)`. Missingness independent of everything.
- **MAR** — `P(R | Y, X) = P(R | X)`. Missingness depends only on *observed* covariates, not on the unobserved value of `Y` itself once you condition on `X`.
- **MNAR / non-ignorable missingness** — `P(R | Y, X)` depends on the unobserved value of `Y` even after conditioning on `X`. This is the Heckman-selection regime: identification requires an auxiliary structure (an instrument, a proxy variable observed for the missing cases, or a parametric assumption on the selection mechanism) — **MNAR is not identifiable from the observed data alone.**

**Mapped to FL:**

| Term | FL meaning |
|---|---|
| Client participation bias | Umbrella term: `R_i,t` (participation) not independent of client/round characteristics — could be MAR or MNAR |
| Correlated participation | `R_i,t` autocorrelated over time/clients (e.g., a Markov chain on *time-since-last-participation*) — orthogonal axis to MCAR/MAR/MNAR; autocorrelation driven only by schedule/time is still MAR |
| Concept drift | `P(local data \| client)` changes over time for a given client |
| Drift-correlated / informative dropout | `R_i,t` depends on the client's **current, round-t** drift magnitude — the MNAR case |
| Informative missingness | Synonym for MNAR/non-ignorable missingness |

**Verdict: conditionally defensible, with one required fix.** The proposal's phrase "the client's current **(unobserved)** drift state" was doing too much work as written. Classical MNAR (Heckman 1979) requires the outcome *is* observed for the selected (participating) cases — that's how the selection mechanism gets identified at all. If "drift is literally never measurable by the server, even when the client participates," the problem is not just MNAR but **unidentifiable without an auxiliary structure**, and no correction method can fix it without inventing that structure from nowhere.

**The fix:** operationalize "drift state" as a quantity that *is* observable/computable when the client is online (e.g., local validation loss delta vs. last global model, or an update-similarity signature) and is only unobserved *while offline*. This is standard panel-attrition framing and makes the proxy-based correction mechanism legible as exactly the auxiliary structure MNAR identification requires — same-cluster online neighbors serve as the proxy for the missing client's current `Y`. **This reframing is load-bearing, not cosmetic** — it justifies both the statistical validity of the MNAR label and the theoretical correctness of proxy-based correction, rather than leaving it an arbitrary heuristic. State it explicitly in any resulting paper.

With that fix, **the MNAR label is legitimate and precise** — it correctly distinguishes this setting from every "correlated participation" paper found (2410.01209, CA-Fed 2301.04632, DPFL/KPFL 2511.16523), all of which are provably MAR (Part 2).

## 0. Verdict up front

Two claims were bundled in the original proposal. They survive very differently.

1. **The empirical research gap** (no one studies FL robustness when dropout is a causal function of the client's current unobserved drift state) — **SURVIVES.** Genuinely not found in the literature. Novelty class holds at **D**.
2. **The proposed algorithmic contribution, DCPA, as originally specified** — **DOES NOT SURVIVE AS WRITTEN.** A near-identical mechanism already exists ([FL-FDMS, arXiv:2205.13222](https://arxiv.org/abs/2205.13222)), and DCPA's one nominally-new piece (staleness/uncertainty discounting) is standard practice from a separate mature literature (async-FL staleness compensation). Worse: DCPA's mechanism doesn't actually *use* the causal drift-dropout coupling — it would behave identically whether dropout were exogenous or drift-caused. The causal premise currently lives only in the motivating narrative, not in the algorithm.

**Result: YELLOW, not GREEN, not RED.**

## 2. Novelty-killing search results

**A. FL + MNAR / informative missingness.** No paper uses MNAR/Rubin's-taxonomy language for *client-round participation*. One paper, [FL with Incomplete Data (arXiv:2605.20125)](https://arxiv.org/abs/2605.20125), uses rigorous MCAR/MAR/MNAR language in FL — but for missing **records/covariates within a client's local dataset**, a different unit of missingness entirely.

**B. FL + drift-dependent participation.** No hit. Every dropout/availability mechanism found (FedProx, SCAFFOLD, FedAPM, CA-Fed, DPFL/KPFL's three generators, the correlated-participation Markov model) is exogenous. One near-miss: [CAFE, "Drift-Aware Federated Learning: A Causal Perspective" (arXiv:2503.09116)](https://arxiv.org/abs/2503.09116) — but the causal arrow is **reversed** (participation frequency causes drift in the global model, not the other way around).

**C. Statistical missing-data correction transplanted into FL.** [FedIPW / "Who Trains Matters" (arXiv:2604.26604)](https://arxiv.org/abs/2604.26604) is the only real hit — and the single most important citation in this audit, for two reasons: it's the closest prior art, *and* its own stated assumptions prove the gap is real. Its correction requires explicit **Mean Ignorability** ("after conditioning on the observed covariates used in the selection model, inclusion does not change the conditional mean update") — provably valid only under MAR, never relaxed, no MNAR discussion, no hidden-confounding sensitivity analysis. **This is the theoretical boundary condition to name and exploit**: IPW-style correction is mathematically inapplicable once dropout depends on the client's own current unobserved state.

**D. Broader adjacent literature.** Nothing beyond the FL literature was needed.

## 3. Closest prior-art table (methodology-level, not abstract-level)

| Paper | What it models | What causes dropout/selection | Related to current drift? | MNAR-capable? | Uses correction? | Closeness |
|---|---|---|---|---|---|---|
| FedAvg | Uniform random sampling | N/A — exogenous | No | No | No | None |
| FedProx (1812.06127) | Straggler tolerance | Device/network resources | No | No | No | None |
| SCAFFOLD (1910.06378) | Client-drift *correction*, not dropout | Uniform sampling | No | No | No | None |
| FedDrift (2206.00799) | Concept drift across clients/time | **N/A — full participation assumed every round** | Can't be, by construction | No | No | Adjacent only; source of DCPA's clustering step |
| DPFL/KPFL (2511.16523) | Configurable dynamic participation | 3 generators, all "data-agnostic... exogenous to client heterogeneity" | No, explicitly excluded | No | KPFL: self-stale-reuse, no clustering, no cross-client proxy | Names our exact gap as future work |
| Debiasing FL Correlated Participation (2410.01209) | Markov-chain participation | "Exclusively time-based... independent of current local data" | No | MAR only | Yes, but MAR-only debiasing | Structurally similar-sounding, substantively different |
| FedIPW / Who Trains Matters (2604.26604) | Two-stage selection | Observed covariates only | **Explicitly assumed no** (Mean Ignorability) | No — MAR by assumption | Yes — IPW | **Closest paper overall**; its limitation is the opening |
| FedAPM (2409.17446) | Non-stationary unavailability | Schedule/hardware, independent across rounds | No | No | Compensation, not MNAR-aware | None |
| Ditto (2012.04221) | Personalization for static heterogeneity | Exogenous/random | No | No | No | None |
| **FL-FDMS (2205.13222)** | **Friend-substitution for dropped clients** | Exogenous, but the *fix* is structurally what DCPA proposes | No (dropout exogenous in their framing) | No | **Yes — near-identical to DCPA's core mechanism** | **The real threat — see §5** |

## 4. Auditing the central claim

> "No existing work quantifies FL performance when client dropout probability is a causal function of the client's current (unobserved) drift state."

**Verdict: (A) Clearly true, with the §1 definitional fix applied.** Every dropout mechanism found across 20+ papers audited at the methodology level is exogenous.

**Strongest defensible rewording:**

> "Existing FL robustness and drift-adaptation methods (FedProx, SCAFFOLD, FedDrift, KPFL) validate against dropout mechanisms that are exogenous to the client's current local state, and existing participation-bias corrections (FedIPW) are provably valid only when dropout depends on observed covariates (MAR), not on the client's current unobserved drift/loss state itself (MNAR). Consequently, it is unknown how much FL performance degrades — and whether IPW-style correction remains valid — when dropout is causally coupled to the client's current, otherwise-unobserved drift state, a condition with real (if unproven) plausibility in low-resource IoT/wearable deployments (§9)."

## 5. Killing DCPA

**DCPA is not a new mechanism as originally specified.** [FL-FDMS (arXiv:2205.13222)](https://arxiv.org/abs/2205.13222), "Combating Client Dropout in Federated Learning via Friend Model Substitution," already does almost exactly this, verified via full-text read:

| DCPA step | FL-FDMS equivalent |
|---|---|
| (1) Cluster online clients by drift signature | Pairwise "friend" discovery via cosine similarity of uploaded model updates |
| (2) Remember offline client's last-known cluster | Persistent exponential-moving-average similarity scores across rounds |
| (3) Use online same-cluster peer's update as proxy | "Uses the local model update Δ^{φ_t(k)}_t as a substitute for Δ^k_t" — literally the same operation |
| (4) Discount by uncertainty/staleness | **Absent in FL-FDMS** — DCPA's one addition |
| (5) Aggregate real + proxy | Done identically in FL-FDMS |

Step (4), DCPA's only nominally new piece, is not novel either: staleness/confidence discounting is standard, mature practice in asynchronous FL (FedStaleWeight, arXiv:2406.02877; FedRevive, arXiv:2511.00655), just applied there to a client's *own* delayed update.

**The more damaging finding:** DCPA's five steps would execute identically whether dropout is exogenous (FL-FDMS's setting) or drift-caused (our setting). **Nothing in the algorithm actually consumes the causal-coupling assumption.** That's the "you didn't need the assumption you spent three pages justifying" failure mode.

**What would fix this:** exploit the informativeness of *who* is currently missing — e.g., a Heckman-style joint model where a selection equation (estimated from observed participation patterns and each client's last-known drift signature) directly determines the discount/correction weight, rather than a generic staleness clock. See §12 for the reframed algorithm (SAPA).

## 6. Attacking the "superlinear degradation" hypothesis

1. **Why superlinear?** No derivation was given — chosen because it "sounds interesting."
2. **Theoretically justified?** Partially arguable by analogy to Heckman selection bias (nonlinear inverse-Mills-ratio term), but that analogy predicts convex/accelerating in some regimes, not a clean superlinear curve everywhere.
3. **Could it be linear?** Yes — small-coupling Taylor expansion of the selection-bias term is approximately linear, so superlinearity is *least* likely at the low end of the range.
4. **Could it saturate?** Yes, arguably more plausible — once dropout probability for high-drift clients approaches 1, further coupling can't censor more signal, predicting an S-shaped, not superlinear, response.
5. **Depends entirely on the dropout function?** Yes — logistic vs. threshold vs. rank-based dropout at matched correlation differ in tail concentration and curve shape.
6. **Does ρ have a principled definition?** Not currently. Fix: report both the structural parameter swept (e.g., logistic slope β) and the realized correlation ρ = corr(drift, dropout), used as the cross-mechanism x-axis.
7. **Can two mechanisms share ρ but differ radically?** Yes, confirmed above — hence needing ≥2–3 mechanisms tested.
8. **Would reviewers call ρ synthetic?** Yes, almost certainly, unless anchored to something real.
9. **Can ρ be derived from a real causal/selection model?** Partially — fit a logistic selection model on the malaria-wearable or PurpleAir data (§9) to obtain an empirically-plausible β range as the anchor operating point.

**Verdict: superlinear is not justified. Replace with a weaker, more defensible hypothesis (§12).**

## 7. Strongest defensible benchmark design

**Dropout-mechanism families (≥3 required, mathematically specified):**

1. **MCAR:** `P(dropout_i,t = 1) = p₀` (constant), marginal rate matched across all conditions.
2. **MAR:** `P(dropout_i,t = 1) = σ(α + γ·X_i)`, `X_i` an observable covariate independent of current drift; α calibrated to match marginal rate.
3. **MNAR-logistic (primary):** `P(dropout_i,t = 1) = σ(α + β·drift_i,t)`. **β is the structural coupling parameter swept**; α re-calibrated at each β to hold marginal dropout rate constant — this isolates *informativeness* of missingness from *amount* of missingness, directly defusing the "you just increased dropout" objection. Realized ρ = corr(drift, dropout) reported as the comparable x-axis.
4. **MNAR-threshold (robustness check):** `dropout_i,t = 1` if `drift_i,t` exceeds a percentile threshold τ, else Bernoulli(p_base).
5. **MNAR-rank (stretch):** dropout probability set by within-round rank of drift magnitude across clients.

**Design pruning:** run the full mechanism × β sweep at one fixed moderate drift-severity/non-IID-severity/availability-rate operating point for the headline result; treat drift severity, non-IID severity, and availability-rate as reduced secondary sweeps (3 levels each, 2–3 strongest methods only), not a full factorial.

## 8. Baseline and ablation matrix (corrected)

**The original baseline list had a critical omission: FL-FDMS was missing entirely.** Corrected list:

| Baseline | Necessary? | Why |
|---|---|---|
| FedAvg | Yes | Canonical floor |
| FedProx | Optional | Largely dominated by SCAFFOLD; keep only if compute allows |
| SCAFFOLD | Yes | Canonical heterogeneity-robust baseline |
| FedDrift | Yes | Source of the clustering step; direct drift-aware SOTA |
| DPFL/KPFL | Yes | Closest existing dynamic-participation solution |
| **FL-FDMS** | **Yes — mandatory, was missing** | The actual closest algorithm; must be shown to be beaten, not just beat FedAvg |
| FedIPW-style debiasing | Yes | The MAR-correction boundary-condition comparator |
| Naive imputation | Yes, cheap | Floor distinct from "skip" and from similarity-based substitution |
| Oracle (drift revealed even offline) | Yes | Upper bound |
| DCPA/SAPA (reframed, §12) | The proposed method | — |

**Ablations that isolate the actual source of any gain:**
- Reframed method vs. **FL-FDMS unmodified** — isolates whether the selection-aware discount adds anything
- vs. **FedIPW-only** — isolates whether imputation adds anything beyond reweighting
- vs. **generic-staleness-discount variant** — isolates whether *selection-model-derived* discount specifically matters, not just "any discount"
- vs. **self-stale-reuse** (KPFL-style) — isolates whether cross-client information is needed at all
- Oracle upper bound

If the reframed method can't beat FL-FDMS and FedIPW-only on this ladder, **the algorithmic claim collapses to an empirical-characterization paper** — a stated fallback, not a failure condition to hide.

## 9. Real-data feasibility (honest accounting)

**No dataset offers a rigorously published, quantitative, publicly-downloadable proof that dropout and drift are causally entangled at the client level.**

| Dataset | Drift signal | Dropout signal | Entanglement evidence | Access | Undergrad-feasible? |
|---|---|---|---|---|---|
| **Malaria/COVID wearable HR study (Kenya cohort)** | Real — infection onset is a genuine physiological regime change | Real — ~50% coverage during infection window | **Best available**: documented co-occurrence, not rigorously isolated causally | **Public, CC BY 4.0, Figshare** (DOI 10.6084/m9.figshare.31444399), no DUA | **Yes — best overall pick** |
| PurpleAir + wildfire smoke | Real, well-labeled | Real, anecdotal but no peer-reviewed quantitative analysis | None published — student would compute it themselves | Public API (bulk pull cost) | Yes, but becomes an original student contribution, not a citable fact |
| SWaT / WADI | Excellent (labeled attacks) | Real missingness present | Evidence suggests missingness is from testbed network artifacts, **independent** of attacks | Public via request form | Yes, but only as synthetic-injection substrate |
| Diabetes CGM/Fitbit study | Real, rigorously MNAR-analyzed | Real, statistically confirmed MNAR (night/adherence-driven) | Real but weak — daily/weekly rhythm, not acute events | **Not publicly available** | No |
| FedScale device-availability traces | None | Real, large-scale (180M events) | Indirect: diurnal/timezone correlation, documented elsewhere | Fully public | Yes, mechanics-only, needs pairing with a separate drift dataset |

**Recommended framing:** use the malaria wearable dataset as the empirical plausibility anchor, described honestly as observed co-occurrence, not proven causation. All controlled coupling-strength experiments remain synthetic by necessity — state this plainly.

## 10. Execution audit (2-semester undergrad reality check)

**Experiment matrix (pruned per §7):**
- Core sweep: 3 mechanisms × 6 coupling levels (≈13 cells) × 6 methods (FedAvg, SCAFFOLD, FedDrift, KPFL, FL-FDMS, FedIPW) × 5 seeds × 2 datasets ≈ **780 runs**
- Ablation ladder: 5 variants × 6 MNAR coupling levels × 5 seeds × 2 datasets ≈ **300 runs**
- Secondary robustness sweeps (drift severity, non-IID severity, availability rate), 2–3 strongest methods only, 3 levels each ≈ **~180 runs**
- **Total: ~1,200–1,300 individual FL simulation runs**

At LEAF-scale, each run is plausibly minutes to ~30 minutes on CPU/single-GPU; embarrassingly parallel. With 8–16 concurrent jobs, wall-clock ≈ 1–2 weeks of continuous compute — feasible in 2 semesters **only if scope is actively pruned**.

| Risk factor | Assessment |
|---|---|
| Implementation difficulty | Medium |
| Compute cost | Low–medium, CPU/single-GPU sufficient |
| Debugging risk | Real — holding marginal dropout rate fixed while varying β is fiddly |
| Statistical analysis burden | Moderate — 5 seeds/cell is thin for curve-shape claims; budget for bootstrap CIs |
| **P(reframed method beats FL-FDMS/FedIPW cleanly)** | **~40–50%** — the real risk in the project |
| P(clean empirical characterization result regardless) | High (~85%+) |

**Minimum viable version:** the empirical characterization alone — publishable even if the algorithm fails outright.
**Stretch version:** the reframed algorithm (§12) beating the ablation ladder, upgrading to a main-track submission.

## 11. Professor attack test (15 objections)

| # | Objection | Severity | Fatal? | Strongest answer |
|---|---|---|---|---|
| 1 | "This is just correlated client participation." | High | No | Correlated-participation papers are provably MAR (methodology-confirmed); ours depends on current unobserved state — a different regime |
| 2 | "MNAR is a statistical label, not a new FL problem." | Medium | No | The contribution is showing FL's *existing* correction (IPW) is provably invalid here, quantified |
| 3 | "FedIPW already solves selection bias." | High | No | Only under its own stated Mean Ignorability assumption — quote it, show empirically it breaks under drift-coupled dropout |
| 4 | "Why do you need DCPA?" | **Very High** | **Partially, as originally specified** | Weak as originally specified (≈FL-FDMS + generic staleness); must reframe (§12) |
| 5 | "Why is proxy imputation valid?" | High | No | Cluster membership is the auxiliary proxy structure MNAR identification requires, not an ad hoc heuristic |
| 6 | "You cannot observe the missing client's drift." | High | No | Correct — that's exactly why a proxy is required, the standard MNAR-identification move |
| 7 | "Your ρ is synthetic." | Medium-High | No | Mitigate by anchoring β to an empirically-fit selection model on real data |
| 8 | "Your result is benchmark-specific." | Medium | No | Mitigate with ≥2 datasets, ≥2 dropout-mechanism families |
| 9 | "The superlinear hypothesis is arbitrary." | High | No (conceded) | Replace with weaker monotonicity hypothesis (§12) |
| 10 | "This is just FedDrift + IPW." | **Very High** | **No, but close** | Wrong pairing — actually FL-FDMS + staleness-weighting. Must cite/differentiate from FL-FDMS explicitly upfront |
| 11 | "What if the drift cluster itself becomes stale?" | Medium | No | Real, admitted limitation; the uncertainty discount is meant to handle this — test via ablation |
| 12 | "Why should an offline client be represented by another client?" | Medium | No | Least-biased available estimator given the auxiliary structure, not assumed correct |
| 13 | "What if the missing client is systematically different from every online client?" | **High** | **Partially fatal for that client, not the paper** | Proxy methods fail here by construction — a real, stated limitation; report failure-mode analysis rather than hide it |
| 14 | "What exactly is the theoretical contribution?" | High | No, if reframed | Applying selection-correction theory (Heckman-style, MNAR-identification-via-proxy) to FL aggregation is a genuine, modest theoretical contribution |
| 15 | "What makes this publication-worthy rather than just a class project?" | High | No | The empirical characterization alone clears a workshop bar on its own |

**Two objections (#4, #10) are the real threats — both stem from the FL-FDMS finding.** Everything else survives with the fixes incorporated above.

## 12. GO / NO-GO DECISION

# YELLOW — pursue only after narrowing/reframing

The empirical research gap is real and well-evidenced (D novelty, survives hostile search). The originally-proposed algorithmic contribution (DCPA as specified) does not survive — it is a recombination of FL-FDMS's friend-substitution mechanism with standard async-FL staleness discounting, and critically, its steps don't actually use the causal drift-coupling premise the paper is built around. Fixable, not fatal.

**Revised research question:** *Does client dropout that is causally coupled to the client's own current (otherwise-latent) concept drift degrade federated learning beyond what equal-magnitude exogenous dropout produces — and does existing state-of-the-art participation-bias correction (IPW-style debiasing, friend-substitution imputation) remain valid under this coupling, or does it require explicitly selection-aware correction?*

**Revised, defensible novelty claim (one sentence):** *No existing federated learning method models or corrects for client participation that depends on the client's own current, unobserved concept-drift state — the field's best available correction (FedIPW) is provably valid only under the weaker missing-at-random assumption it never relaxes, and the field's best available imputation method (FL-FDMS) borrows a peer's update without ever using drift-informativeness to weight that substitution.*

**Minimum viable experimental design (pursue this, not the original scope):**

1. Build the MCAR/MAR/MNAR-logistic/MNAR-threshold benchmark (§7), holding marginal dropout rate fixed across conditions.
2. Run FedAvg, SCAFFOLD, FedDrift, KPFL, **FL-FDMS**, FedIPW across all conditions (§8's corrected baseline list).
3. **Headline result (low-risk, near-certain to be publishable):** show all six existing methods degrade significantly more under MNAR than under MCAR/MAR at matched dropout rate, and FedIPW's advantage over naive skipping vanishes or reverses specifically in the MNAR condition — directly validating the Mean Ignorability boundary.
4. **Stretch algorithmic contribution:** reframe DCPA as **Selection-Aware Proxy Aggregation (SAPA)** — replace the generic staleness discount with a weight derived from a fitted selection/propensity model (dropout ~ each client's last-observed drift signature), applied on top of FL-FDMS-style friend substitution. This is the one piece of design space not already occupied by FL-FDMS or FedIPW alone. Test via the ablation ladder (§8); if it doesn't clearly beat FL-FDMS and FedIPW-only, the paper still stands on step 3 alone.
5. Anchor the coupling-strength range to an empirically-fit selection model on the malaria-wearable dataset (§9) rather than an arbitrary sweep.
6. State up front, in the paper's own limitations section, the two conceded weaknesses from this audit: (a) primary experiments are synthetic, real-data component is a plausibility anchor only; (b) proxy-based correction fails by construction when a dropped-out client has no valid online analogue — measure and report this failure rate rather than hide it.

This version is smaller, more honest, and survives the two objections (#4, #10) that killed the original design, because the empirical half doesn't need the algorithm to succeed at all, and the algorithmic half (SAPA) is explicitly positioned as *extending* FL-FDMS and FedIPW rather than reinventing them from scratch.

---

## Note on scope

Only Candidate #1 received the Part II hostile-audit treatment, per the specific request that initiated it. Candidates 2–10 carry only the Part I discovery-pass novelty assessment (D/C classifications as originally assigned) — they have **not** been subjected to the same live-methodology-reading, kill-attempt process, and their novelty claims should be treated as less rigorously stress-tested than Candidate #1's revised claim above. If either Candidate 2 (trust calibration) or Candidate 3 (multi-agent Byzantine robustness) becomes the actual pick, the same adversarial-audit process run here should be repeated against it before committing further time.

---

## Consolidated reference list (all live-verified, both parts)

- Caldas et al. LEAF. [arXiv:1812.01097](https://arxiv.org/abs/1812.01097)
- Li et al. FedProx. MLSys 2020. [arXiv:1812.06127](https://arxiv.org/abs/1812.06127)
- Karimireddy et al. SCAFFOLD. ICML 2020. [arXiv:1910.06378](https://arxiv.org/abs/1910.06378)
- Jothimurugesan et al. FedDrift. AISTATS 2023. [arXiv:2206.00799](https://arxiv.org/abs/2206.00799)
- DPFL/KPFL. AAAI-26 FLCA workshop. [arXiv:2511.16523](https://arxiv.org/abs/2511.16523)
- Debiasing FL with Correlated Client Participation. [arXiv:2410.01209](https://arxiv.org/abs/2410.01209)
- Who Trains Matters / FedIPW. [arXiv:2604.26604](https://arxiv.org/abs/2604.26604)
- FedAPM. [arXiv:2409.17446](https://arxiv.org/abs/2409.17446)
- Li, Hu, Beirami, Smith. Ditto. ICML 2021. [arXiv:2012.04221](https://arxiv.org/abs/2012.04221)
- Kairouz et al. Advances and Open Problems in FL. [arXiv:1912.04977](https://arxiv.org/abs/1912.04977)
- **FL-FDMS: Combating Client Dropout via Friend Model Substitution.** [arXiv:2205.13222](https://arxiv.org/abs/2205.13222) *(found in Part II — the critical citation)*
- CA-Fed: FL under Heterogeneous and Correlated Client Availability. [arXiv:2301.04632](https://arxiv.org/abs/2301.04632) *(Part II)*
- CAFE: Drift-Aware FL, A Causal Perspective. [arXiv:2503.09116](https://arxiv.org/abs/2503.09116) *(Part II)*
- FedCausal-Dyn. [arXiv:2607.09695](https://arxiv.org/abs/2607.09695) *(Part II)*
- FedStaleWeight. [arXiv:2406.02877](https://arxiv.org/abs/2406.02877) *(Part II)*
- FedRevive. [arXiv:2511.00655](https://arxiv.org/abs/2511.00655) *(Part II)*
- Adaptive Client Selection for Network Anomaly Detection. [arXiv:2501.15038](https://arxiv.org/abs/2501.15038) *(Part II)*
- FL with Incomplete Data: Complete Cases vs. Weighting. [arXiv:2605.20125](https://arxiv.org/abs/2605.20125) *(Part II)*
- Petroni et al. KILT. NAACL 2021. [arXiv:2009.02252](https://arxiv.org/abs/2009.02252)
- Es et al. RAGAS. [docs.ragas.io](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/faithfulness/)
- Yang et al. CRAG. KDD Cup 2024. [arXiv:2406.04744](https://arxiv.org/abs/2406.04744)
- Liu et al. Lost in the Middle. TACL 2024. [arXiv:2307.03172](https://arxiv.org/abs/2307.03172)
- Vu et al. FreshLLMs/FreshQA. ACL Findings 2024. [arXiv:2310.03214](https://arxiv.org/abs/2310.03214)
- Ouyang et al. HoH. ACL 2025. [arXiv:2503.04800](https://arxiv.org/abs/2503.04800)
- Wang, Prasad, Stengel-Eskin, Bansal. RAMDocs/MADAM-RAG. COLM 2025. [arXiv:2504.13079](https://arxiv.org/abs/2504.13079)
- Özer & Yıldız. QA under Temporal Conflict. [arXiv:2506.07270](https://arxiv.org/abs/2506.07270)
- An et al. FRESCO. [arXiv:2604.14227](https://arxiv.org/abs/2604.14227)
- Xu et al. Knowledge Conflicts for LLMs: A Survey. [arXiv:2403.08319](https://arxiv.org/abs/2403.08319)
- Reddy & Challaram. Don't Ask the LLM to Track Freshness. [arXiv:2606.01435](https://arxiv.org/abs/2606.01435)
- Perry, Srivastava, Kumar, Boneh. CCS 2023. [arXiv:2211.03622](https://arxiv.org/abs/2211.03622)
- Ziegler et al. Measuring GitHub Copilot's Impact on Productivity. CACM 2024.
- Vasconcelos, Bansal, Fourney, Liao, Vaughan. TOCHI 2024. [arXiv:2302.07248](https://arxiv.org/abs/2302.07248)
- Wang, Cheng, Ford, Zimmermann. FAccT 2024. [arXiv:2305.11248](https://arxiv.org/abs/2305.11248)
- Brown, D'Angelo, Murillo, Jaspan, Green. AIware 2024.
- Baltes, Speith, Chiteri et al. [arXiv:2504.12461](https://arxiv.org/abs/2504.12461)
- Ferino, Hoda, Grundy, Treude. FSE Companion 2026. [arXiv:2604.10530](https://arxiv.org/abs/2604.10530)
- Gardella, Bolton, Riggs. [arXiv:2604.18948](https://arxiv.org/abs/2604.18948)
- Evolution of Programmers' Trust in Generative AI Programming Assistants. Koli Calling 2025. [arXiv:2509.13253](https://arxiv.org/abs/2509.13253)
- Meta RADAR. [arXiv:2605.30208](https://arxiv.org/abs/2605.30208)
- Sun et al. Constraint Weakening in LLM Agent Workflows. [arXiv:2608.24569](https://arxiv.org/abs/2608.24569)
- Gelvan et al. Implicit Context Compression for SWE Agents. [arXiv:2605.11051](https://arxiv.org/abs/2605.11051)
- Mehta et al. Plans Don't Persist. [arXiv:2606.22953](https://arxiv.org/abs/2606.22953)
- Kang et al. ACON. ICML 2026. [arXiv:2510.00615](https://arxiv.org/abs/2510.00615)
- The Long-Horizon Task Mirage. [arXiv:2604.11978](https://arxiv.org/abs/2604.11978)
- Diagnosing and Mitigating Context Rot in Long-horizon Search. [arXiv:2606.29718](https://arxiv.org/abs/2606.29718)
- AdaCoM. [arXiv:2605.30785](https://arxiv.org/abs/2605.30785)
- Deng et al. SWE-Bench Pro. Scale AI. [arXiv:2509.16941](https://arxiv.org/abs/2509.16941)
- Du, Li, Torralba, Tenenbaum, Mordatch. Multiagent Debate. ICML 2024. [arXiv:2305.14325](https://arxiv.org/abs/2305.14325)
- Zhang et al. Stop Overvaluing Multi-Agent Debate. [arXiv:2502.08788](https://arxiv.org/abs/2502.08788)
- Wynn, Satija, Hadfield. Talk Isn't Always Cheap. ICML MAS Workshop 2025. [arXiv:2509.05396](https://arxiv.org/abs/2509.05396)
- Wu, Li, Li. Can LLM Agents Really Debate? [arXiv:2511.07784](https://arxiv.org/abs/2511.07784)
- Lee, Tiwari. Prompt Infection. [arXiv:2410.07283](https://arxiv.org/abs/2410.07283)
- Kavathekar, Jain, Rathod, Kumaraguru, Ganu. TAMAS. [arXiv:2511.05269](https://arxiv.org/abs/2511.05269)
- Lee, Yun, Panagou, Karimireddy. SAC. EMNLP 2026. [arXiv:2605.09076](https://arxiv.org/abs/2605.09076)
- Jo, Park. DecentLLMs. [arXiv:2507.14928](https://arxiv.org/abs/2507.14928)
- Wiesmeier, Busch, Tacke, Linka, Cyron, Aydin. Frontiers in AI, 2026.
- Becker, Wahle, Ruas, Gipp. Misinformation Propagation in Benign MAS. [arXiv:2606.16710](https://arxiv.org/abs/2606.16710)
- BAD-ACTS. [arXiv:2508.16481](https://arxiv.org/abs/2508.16481)
- El Mir, Takáč, Lahlou. Byzantine Cheap Talk. NETYS 2026. [arXiv:2606.07790](https://arxiv.org/abs/2606.07790)

---

*All arXiv preprints are unreviewed unless a peer-reviewed venue is explicitly named. This document should be treated as current as of 2026-09-09 — re-run a fresh novelty-killing search immediately before any formal proposal submission, since several candidates (especially #1, #5) sit in fast-moving 2026 preprint spaces where new close papers could appear within weeks.*
