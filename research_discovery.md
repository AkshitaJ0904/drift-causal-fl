# Research Gap Discovery

*A structured novelty investigation for an undergraduate / early-graduate research project — CS/AI/Systems*

Prepared 2026-09-09 · Method: 5 parallel literature-mapping passes over arXiv, Semantic Scholar, ACL Anthology, ACM/IEEE, Google Scholar, plus PI-level synthesis. See **Methodology** for what was live-verified vs. inferred.

**Contents**
- [Methodology & honesty notes](#methodology--honesty-notes)
- [Phase 0 — Search space & area ranking](#phase-0--search-space--area-ranking)
- [Phase 15 — Ten candidates, full specification](#phase-15--ten-candidates-full-specification)
- [Top 3, ranked](#top-3-ranked)
- [Full paper skeleton — Candidate #1](#full-paper-skeleton--candidate-1)
- [References (all live-verified)](#references-all-live-verified)

---

## Methodology & honesty notes

Five specialized research agents independently ran live searches (WebSearch/WebFetch against arxiv.org, Semantic Scholar, ACL Anthology, ACM DL, IEEE Xplore listings, Google Scholar, OpenReview) over five candidate niches, each instructed to report only papers actually retrieved, with real titles/authors/years/venues/URLs, and to flag uncertainty explicitly. Every paper cited below traces to one of those five reports and carries a link. **None of the 30+ cited papers were fabricated or guessed from training memory** — several 2025–2026 preprints were cross-checked because they postdate reliable training knowledge.

> **Where this falls short of the full spec.** The 20-source, dozen-venue systematic review described in the original prompt (ACM DL, IEEE Xplore, Springer, ScienceDirect, patent search, dissertation databases, full-text close-reading of every related paper) was not executed at that scale — this was five deep-but-bounded passes (~20–25 tool calls each), not a multi-week systematic review. Treat the novelty classifications below as **well-evidenced working estimates**, not a guarantee no closer paper exists; the "evidence threatening novelty" field in each candidate is the honest record of the closest prior art actually found, including two cases where it meaningfully weakens the claim (Candidates 4 and 5). Phase 0's area list beyond the five deep-dived niches reflects PI-level domain scoping, not independent literature verification — it is disclosed as such.

---

## Phase 0 — Search space & area ranking

18 candidate areas were scoped from known structural gaps (disjoint literatures, contested assumptions, benchmark realism gaps). The five with the best combination of gap density, feasibility, and timeliness were carried into full literature mapping (✓). The other five final candidates (6–10) are sub-questions that emerged organically from inside those five deep-dive reports — not independently searched territory — to avoid claiming verified novelty for areas that were only scoped, not investigated.

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

---

## Phase 15 — Ten candidates, full specification

### 1. Federated Learning Under Missing-Not-At-Random (MNAR) Client Participation

**Novelty: D — Strong candidate** · `algorithmic` `systems` · ⭐ TOP 3

> Existing FL robustness methods assume client dropout is statistically independent of the data drift it would reveal — this tests and fixes what happens when dropout is *caused by* the drift itself.

- **Field:** Distributed Systems / Machine Learning (Federated Learning)
- **Problem:** FL robustness and drift-adaptation methods are validated under dropout mechanisms that are exogenous to (independent of) each client's current data state, but real edge deployments plausibly have dropout *caused by* the same conditions that produce drift (e.g., a sensor going offline exactly when it would report an anomaly).
- **Known:** FedAvg/FedProx/SCAFFOLD establish convergence under static or i.i.d.-violating-but-time-invariant heterogeneity. FedDrift handles drift staggered across clients and time but treats per-round availability as given. Two disjoint threads — (a) concept-drift-across-clients (FedDrift) and (b) correlated/selection-biased participation (FedIPW-style debiasing, enrollment-selection models) — do not intersect: neither ties *why* a client is offline to its *current* local distribution.
- **Closest 5–10 papers:** LEAF (Caldas et al., [arXiv:1812.01097](https://arxiv.org/abs/1812.01097)); FedProx (Li et al., MLSys 2020, [1812.06127](https://arxiv.org/abs/1812.06127)); SCAFFOLD (Karimireddy et al., ICML 2020, [1910.06378](https://arxiv.org/abs/1910.06378)); FedDrift (Jothimurugesan et al., AISTATS 2023, [2206.00799](https://arxiv.org/abs/2206.00799)); DPFL/KPFL (AAAI-26 workshop, [2511.16523](https://arxiv.org/abs/2511.16523)); Debiasing FL w/ Correlated Participation ([2410.01209](https://arxiv.org/abs/2410.01209)); "Who Trains Matters" / FedIPW ([2604.26604](https://arxiv.org/abs/2604.26604)); FedAPM ([2409.17446](https://arxiv.org/abs/2409.17446)); Ditto (Li et al., ICML 2021, [2012.04221](https://arxiv.org/abs/2012.04221)); Kairouz et al. survey ([1912.04977](https://arxiv.org/abs/1912.04977)).
- **Limitations in those papers:** FedProx/SCAFFOLD: heterogeneity is static, participation is exogenous systems-load noise. FedDrift: drift modeled per-client-per-round but availability assumed given, not caused by drift. DPFL/KPFL explicitly generate participation independent of data heterogeneity and name "more realistic participation scenarios" as future work. FedIPW/"Who Trains Matters" models selection bias generally but isn't tied to a drift/anomaly mechanism and is validated only on synthetic federated logistic regression.
- **Exact gap:** No existing work quantifies FL performance when client dropout probability is a causal function of the client's current (unobserved) drift state — informative/non-ignorable missingness in the MNAR sense — rather than missing-completely-at-random or covariate-dependent-but-drift-independent.
- **Why it matters:** If true, every reported robustness number for FedAvg/FedProx/SCAFFOLD/FedDrift under "realistic" dropout is optimistic for exactly the deployment scenarios (industrial IoT, anomaly detection, health wearables) where catching the drift is the point — the model would be systematically blind to exactly the clients most worth learning from.
- **Proposed solution:** (1) A benchmark protocol that injects a tunable causal coupling ρ between per-client drift magnitude and per-round dropout probability on top of standard FL benchmarks (LEAF FEMNIST/Shakespeare, Office-Caltech-10 as used by DPFL). (2) Drift-Cluster Proxy Aggregation (DCPA): extends FedDrift's drift-clustering with an MNAR correction — currently-offline clients are represented in aggregation via a proxy drawn from the most similar currently-online client in their last-known drift cluster, with an uncertainty-weighted discount as cluster confidence degrades.
- **Novel mechanism:** Coupling FedDrift-style drift clustering (a systems technique) with Rubin's missing-data taxonomy (MCAR/MAR/MNAR, a statistical framework never applied to FL client participation) to derive a principled proxy-imputation correction — not a tech combination for its own sake, but importing a formal missing-data mechanism that directly explains why existing correction methods (which assume MAR at best) cannot fix MNAR dropout.
- **Hypothesis:** As coupling strength ρ between drift and dropout increases from 0 (MCAR) to 1 (fully informative), global model error for FedAvg/FedProx/SCAFFOLD/FedDrift will grow *superlinearly* in ρ, significantly exceeding their published degradation under equal-magnitude MCAR dropout; DCPA will reduce this excess error by ≥20% relative to the strongest baseline at ρ≥0.6, while matching baseline performance at ρ=0.
- **Dataset:** LEAF FEMNIST & Shakespeare (synthetic controlled ρ injection); Office-Caltech-10 federated split (DPFL's own setup, for direct baseline comparability); stretch goal: a public industrial-IoT anomaly-detection dataset (e.g. SWaT/WADI-style) with synthetically injected connectivity coupling as an external-validity check.
- **Experimental setup:** Sweep ρ ∈ {0, .2, .4, .6, .8, 1.0} × 3 non-IID severity levels × 5 baselines (FedAvg, FedProx, SCAFFOLD, FedDrift, KPFL) + DCPA, 5 seeds each. Fixed communication rounds; report accuracy, per-client fairness (variance across clients), and drift-detection recall specifically on clients that went offline.
- **Baselines:** Classical: FedAvg. Heterogeneity-robust: FedProx, SCAFFOLD. Drift-aware SOTA: FedDrift, KPFL. Selection-bias-aware: FedIPW-style debiasing (2410.01209) as the strongest "already tries to fix related-but-not-identical problem" baseline. Ablation: DCPA without the drift-cluster proxy (plain IPW under MNAR) to isolate the proxy's contribution.
- **Metrics:** Global test accuracy vs. ρ; worst-client / variance-based fairness; drift-detection recall restricted to the informatively-dropped-out subpopulation; wall-clock/communication overhead of DCPA vs. baselines.
- **Ablations:** (a) DCPA − drift clustering (plain proxy nearest-neighbor); (b) DCPA − uncertainty discount; (c) oracle upper bound (drift state revealed even when offline) to bound achievable gains.
- **Expected result:** A clear, statistically significant degradation curve in ρ for all five baselines that is absent or much flatter at ρ=0, with DCPA closing a majority of the gap at high ρ without a synchronized-clock or full-observability assumption.
- **What would falsify it:** If baseline degradation curves are flat in ρ (informative dropout is no worse than equal-magnitude random dropout) or DCPA fails to beat the FedIPW ablation at any ρ, the hypothesis is falsified — informative missingness would not be a distinct failure mode from ordinary correlated dropout, undercutting the core claim.
- **Expected contribution:** First controlled, quantitative characterization of FL robustness under drift-caused (not just drift-and-dropout-coexisting) missingness, plus a proxy-correction method with a stated, testable boundary condition (cluster confidence) rather than an unconditional fix.
- **Novelty classification:** **D** — two active, mature literatures exist; their causal intersection is explicitly named as unaddressed by the closest paper (DPFL/KPFL, 2511.16523).
- **Evidence supporting novelty:** DPFL/KPFL (Nov 2025) explicitly states its participation generators are independent of data heterogeneity and lists "more realistic participation scenarios" as future work — direct textual evidence the gap is open.
- **Evidence threatening novelty:** "Who Trains Matters" (2604.26604) is a general selection-bias framework close in spirit; if a revision extends it to drift-causal coupling before this project ships, the contribution narrows to the DCPA mechanism and empirical curves rather than the framing itself.
- **Implementation difficulty:** Medium — FL simulators (Flower, or LEAF's own harness) are mature; the causal-coupling injection and DCPA logic are a few hundred lines on top.
- **Compute requirement:** Low–medium — CPU/single-GPU FL simulation at LEAF/Office-Caltech scale; no LLM training.
- **Expected duration:** 2 semesters (1 to build the coupling benchmark + reproduce baseline curves, 1 to develop/tune DCPA and run ablations).
- **Publication potential:** FL-focused workshops at NeurIPS/AISTATS/MLSys, or a systems/ML venue with a robustness angle (e.g., a workshop track first, main-track submission if DCPA's gains are large and clean).
- **Reviewer #2 objections:** "Isn't this just correlated non-IID data, already studied?" "Is ρ a realistic parameterization of any real deployment, or a synthetic knob with no grounding?" "DCPA looks like a straightforward combination of FedDrift + IPW — where's the difficulty?"
- **Answers:** Correlated non-IID (spatial) is orthogonal to informative-in-time missingness — SCAFFOLD/FedProx explicitly assume the former without the latter, and the paper isolates ρ as the added dimension. ρ can be grounded via the stretch-goal industrial dataset with real anomaly-correlated dropout, not left purely synthetic. The difficulty is precisely in the correction: plain IPW is provably insufficient under true MNAR without an auxiliary proxy — that's the ablation that must show a real gap, or the paper concedes the mechanism doesn't add value beyond existing debiasing.
- **Professor attack-test result:** Survives with the ablation-honesty caveat above: the paper must show DCPA beats plain-IPW-under-MNAR, or it reduces to an empirical characterization paper (still publishable, but as an empirical-finding contribution rather than an algorithmic one — should be stated as a fallback framing up front).

---

### 2. Risk-Differentiated Trust Calibration in AI-Assisted Coding

**Novelty: D — Strong candidate** · `empirical` `HCI/SE` · ⭐ TOP 3

> Do developers actually scrutinize AI code suggestions more when the code is security-sensitive, or does trust stay flat regardless of stakes — measured behaviorally, within the same developer?

- **Field:** Human-AI Interaction / Software Engineering (CHI, FSE, ICSE)
- **Problem:** Developer trust in AI coding assistants is measured almost entirely as a single undifferentiated construct (acceptance rate, self-reported trust), while whether scrutiny actually tracks the real risk of the code being suggested (auth/crypto/SQL vs. boilerplate) — within the same developer, same session — is unmeasured.
- **Known:** AI-assisted developers write measurably less secure code while feeling *more* confident it's secure (Perry et al., CCS 2023). Acceptance rate is the dominant behavioral proxy used across the field (Ziegler et al., CACM 2024) despite recent evidence that self-reported trust doesn't predict acceptance behavior (Gardella et al. 2026). Confidence-signal design matters, but not the way expected: raw model-confidence highlighting gave no benefit over nothing; edit-likelihood highlighting did (Vasconcelos et al., TOCHI 2024).
- **Closest 5–10 papers:** Perry, Srivastava, Kumar, Boneh, CCS 2023 ([2211.03622](https://arxiv.org/abs/2211.03622)); Ziegler et al., CACM 2024; Vasconcelos, Bansal, Fourney, Liao, Vaughan, TOCHI 2024 ([2302.07248](https://arxiv.org/abs/2302.07248)); Wang, Cheng, Ford, Zimmermann, FAccT 2024 ([2305.11248](https://arxiv.org/abs/2305.11248)); Brown, D'Angelo, Murillo, Jaspan, Green, AIware 2024; Baltes, Speith, Chiteri et al. ([2504.12461](https://arxiv.org/abs/2504.12461), 2026 v3); Ferino, Hoda, Grundy, Treude, FSE Companion 2026 ([2604.10530](https://arxiv.org/abs/2604.10530)); Gardella, Bolton, Riggs ([2604.18948](https://arxiv.org/abs/2604.18948)).
- **Limitations in those papers:** Perry et al.: single dated model (codex-davinci-002), lab tasks. Brown et al.: context operationalized as file type/length, not a security-risk taxonomy. Wang et al. and Ferino et al.: qualitative/interview-based, note context *should* matter but don't measure it behaviorally or within-subject. Baltes et al. (2026) is a critical review that explicitly names "risk differentiation" and study of "higher-stakes environments" as missing from the field.
- **Exact gap:** No study measures, within the same developer/session, whether behavioral scrutiny (acceptance rate, edit depth, review time, added tests) differs by code-risk category using a manipulated or measured risk taxonomy — as opposed to self-report or coarse proxies like file type.
- **Why it matters:** If scrutiny is flat regardless of stakes, the Perry et al. finding (false confidence + less secure code) generalizes to a stable behavioral pattern rather than a one-off study artifact, with direct implications for how AI coding tools should be designed (risk-adaptive friction/UI) rather than treated as a uniform productivity tool.
- **Proposed solution:** A within-subject lab study (Vasconcelos-style controlled task battery) where the same participants complete matched coding tasks spanning a risk taxonomy (auth/crypto/SQL/deserialization vs. boilerplate CRUD/formatting), with AI suggestions of controlled correctness injected across both categories; measure acceptance, edit depth, time-to-decision, and downstream defect rate. Secondary arm: mine real Copilot/Cursor-style session logs with risk-annotated diffs for ecological validity.
- **Novel mechanism:** Operationalizing "risk category" as a manipulated within-subject factor crossed with suggestion correctness (correct vs. subtly-flawed) — isolating whether risk category changes the *rate* of catching flawed suggestions, not just self-reported trust.
- **Hypothesis:** We hypothesize that acceptance rate and edit depth will not differ significantly by risk category (i.e., scrutiny is flat), while actual defect-catch rate for subtly-flawed high-risk suggestions will be no higher than for low-risk ones — i.e., developers do not compensate for higher stakes with proportionally higher scrutiny, contradicting a risk-rational-actor null hypothesis.
- **Dataset:** Novel: a matched task battery (≈16–24 tasks, half high-risk/half low-risk, half with subtly flawed AI suggestions) built for the study, IRB-approved participant pool (CS students + early-career professionals, n≈30–40 per Vasconcelos-scale precedent). Secondary: anonymized session logs from a university-hosted AI coding assistant deployment, if available, or a public dataset of Copilot interaction logs if one exists.
- **Experimental setup:** 2×2 within-subject design (risk category × suggestion correctness), counterbalanced task order, screen+interaction logging, post-task Muir-scale trust survey for triangulation against Gardella et al.'s trust≠compliance finding.
- **Baselines:** Null model: uniform scrutiny regardless of risk (what the field implicitly assumes by not measuring this). Comparison conditions: no AI assistance (Perry et al.-style control), AI with edit-likelihood highlighting (Vasconcelos condition) as a UI intervention arm to test whether a known-effective signal closes the gap.
- **Metrics:** Acceptance rate by category; edit depth (char/AST-diff) by category; time-to-decision; flaw-catch rate on subtly-flawed suggestions; post-hoc self-reported trust (Muir scale) for comparison to behavior.
- **Ablations:** With vs. without explicit risk labeling shown to participant; with vs. without edit-likelihood highlighting; novice vs. experienced developer subgroup comparison.
- **Expected result:** Flat or near-flat scrutiny across risk category in the baseline condition, replicating/extending Perry et al.'s confidence-security mismatch into a risk-differentiation finding; edit-likelihood highlighting partially but not fully closes the gap.
- **What would falsify it:** If flaw-catch rate and edit depth are significantly higher for high-risk tasks even without explicit signaling, the hypothesis is falsified — developers would already be risk-calibrated, and the design contribution shifts to characterizing what implicit cues drive that calibration instead.
- **Expected contribution:** First behavioral, within-subject evidence on whether developer scrutiny of AI code suggestions is risk-calibrated, directly answering the gap Baltes et al. (2026) names, and informing risk-adaptive UI design (a testable design implication, not just a finding).
- **Novelty classification:** **D** — the gap is explicitly named by a 2026 critical review; adjacent empirical work exists but none operationalizes risk category as a within-subject behavioral variable.
- **Evidence supporting novelty:** Baltes et al. (2504.12461 v3, 2026) explicitly states the field lacks "risk differentiation" and has "limited study of higher-stakes environments" — a direct, recent, citable statement of the gap from a critical review, not an inference.
- **Evidence threatening novelty:** Brown et al. (AIware 2024) already shows acceptance varies with some contextual factors (suggestion length, file type), so a skeptical reviewer could argue "context already shown to matter" — the rebuttal is that none of those proxies is a security/domain-risk taxonomy, and none isolates within-subject risk-driven scrutiny from confounds like suggestion length.
- **Implementation difficulty:** Medium — requires IRB approval, task-battery design with piloted "subtly flawed" suggestions, and a moderate participant pool; no novel ML system to build.
- **Compute requirement:** Minimal — API calls to generate/curate suggestions; study infrastructure (screen recording, logging) is the main engineering cost.
- **Expected duration:** 2–3 semesters (IRB + pilot in semester 1, main study + analysis in semesters 2–3) — the IRB timeline is the primary schedule risk for an undergrad project.
- **Publication potential:** CHI, FSE, CSCW, or ICSE (empirical software engineering track); FAccT if framed around AI-assisted-coding fairness/safety implications.
- **Reviewer #2 objections:** "Small-n lab study, how do we know it generalizes to real usage?" "Risk taxonomy is subjective — who decided auth/crypto is 'high risk'?" "Isn't this just Perry et al. again with a risk label added?"
- **Answers:** The secondary log-mining arm addresses ecological validity directly. The risk taxonomy can be grounded in an existing standard (e.g., OWASP Top 10 categories, or CWE severity) rather than ad hoc judgment. Unlike Perry et al. (single risk level, AI-vs-no-AI), this design's core manipulation is risk category itself, within-subject, which Perry et al. does not test.
- **Professor attack-test result:** Survives; the main vulnerability is IRB/timeline risk for an undergrad, not scientific defensibility — recommend starting the log-mining arm in parallel with IRB approval to de-risk the schedule.

---

### 3. Byzantine Robustness of Multi-Agent LLM Systems Under Strategic, Realistic-Task Adversaries

**Novelty: C — Underexplored** · `algorithmic` `security` `frontier` · ⭐ TOP 3

> Existing Byzantine-robust multi-agent LLM work tests math/logic toy tasks with naive wrong-answer adversaries — this tests strategic and colluding adversaries on realistic collaborative-coding tasks, benchmarked against classical BFT degradation curves.

- **Field:** Multi-Agent Systems / AI Security (NeurIPS/ICML MAS workshops, USENIX Security, CCS)
- **Problem:** Multi-agent LLM systems (debate, collaborative coding, negotiation) are being deployed on the implicit assumption that agents are honest/cooperative; the emerging Byzantine-robustness literature that relaxes this assumption is validated mostly on math/logic puzzles with naive wrong-answer adversaries, not realistic collaborative tasks with strategic or colluding adversaries.
- **Known:** Multi-agent debate's claimed accuracy gains over single-agent baselines are contested even absent adversaries (Zhang et al. 2502.08788: MAD often loses to Chain-of-Thought at far higher cost; Wynn et al. 2509.05396: accuracy can decline over rounds from sycophancy alone). A single adversarial/misleading agent can flip outcomes with high success (up to 100% in some conditions; Wiesmeier et al. 2026) and prompt injection self-replicates through inter-agent messages (Lee & Tiwari, 2410.07283). The closest true Byzantine-fault-tolerance-style paper, Self-Anchored Consensus (Lee, Yun, Panagou, Karimireddy, EMNLP 2026, [2605.09076](https://arxiv.org/abs/2605.09076)), explicitly parameterizes degradation by Byzantine fraction F/N with graph-theoretic robustness guarantees, but on math/commonsense benchmarks only.
- **Closest 5–10 papers:** Du, Li, Torralba, Tenenbaum, Mordatch, ICML 2024 ([2305.14325](https://arxiv.org/abs/2305.14325)); Zhang et al. ([2502.08788](https://arxiv.org/abs/2502.08788)); Wynn, Satija, Hadfield ([2509.05396](https://arxiv.org/abs/2509.05396)); Lee & Tiwari ([2410.07283](https://arxiv.org/abs/2410.07283)); TAMAS (Kavathekar et al., [2511.05269](https://arxiv.org/abs/2511.05269)); Lee, Yun, Panagou, Karimireddy — SAC ([2605.09076](https://arxiv.org/abs/2605.09076)); DecentLLMs (Jo & Park, [2507.14928](https://arxiv.org/abs/2507.14928)); Wiesmeier et al., Frontiers in AI 2026; Becker, Wahle, Ruas, Gipp ([2606.16710](https://arxiv.org/abs/2606.16710)); BAD-ACTS ([2508.16481](https://arxiv.org/abs/2508.16481)).
- **Limitations in those papers:** SAC: math/commonsense QA only, no realistic multi-step collaborative task, no strategy variation (adversary type not systematically swept). TAMAS/BAD-ACTS: attack-taxonomy benchmarks, not systematic fraction-of-adversaries sweeps. Wiesmeier et al.: N≤6 agents, leader/advisor structure, not a general N-agent sweep. Becker et al.: benign-system misinformation propagation, not adversarially strategic agents.
- **Exact gap:** No paper combines (i) a realistic collaborative task domain beyond math/logic/toy games (e.g., multi-agent collaborative coding or code review), (ii) a systematic sweep across both adversarial *fraction* and qualitatively distinct adversarial *strategies* (naive-wrong, strategically persuasive, colluding/steganographic), and (iii) results framed explicitly against classical Byzantine fault tolerance thresholds (e.g., the classical 1/3 corruption bound).
- **Why it matters:** Multi-agent coding/review tools are being deployed now; if degradation is non-linear or the classical BFT 1/3 threshold doesn't transfer to LLM consensus mechanisms (which SAC's own F/N framing suggests it might not), that's a direct, actionable finding for how many independent agents/models a safety-critical multi-agent pipeline needs.
- **Proposed solution:** A benchmark (realistic collaborative coding tasks — e.g., multi-agent PR review/bug-fix consensus on SWE-bench-style issues) with a controlled adversary-injection harness sweeping fraction (0–50%) × strategy (naive-wrong, persuasive/rhetorical, colluding-steganographic per the collusion literature) across 3–4 consensus protocols (majority vote, SAC-style graph-robust aggregation, a simple leader-based baseline).
- **Novel mechanism:** Reframing multi-agent LLM robustness explicitly through classical distributed-systems Byzantine fault tolerance thresholds — testing whether the well-known 1/3-corruption safety bound (from deterministic BFT) has any predictive validity for stochastic, natural-language-mediated LLM consensus, which is a genuinely open question since LLM agents can be persuaded/colluded with in ways a deterministic BFT node cannot.
- **Hypothesis:** We hypothesize that (a) degradation as a function of adversarial fraction will exceed the classical BFT prediction (i.e., systems fail below the 1/3 threshold) once adversaries use persuasive or colluding strategies rather than naive-wrong answers, and (b) SAC-style graph-robust aggregation will outperform majority vote at moderate fractions but its advantage will shrink or vanish under colluding/steganographic strategies not tested in the original SAC paper.
- **Dataset:** SWE-bench-Lite or a curated subset of realistic multi-file bug-fix/review tasks, adapted into a multi-agent consensus protocol (agents propose/vote on fixes or review verdicts); adversarial agent prompts/personas constructed per strategy class, validated via pilot for strategy fidelity.
- **Experimental setup:** N=7 or 9 agents, adversarial fraction ∈ {0, 1/9, 2/9, 1/3, 4/9}, strategy ∈ {naive, persuasive, colluding}, protocol ∈ {majority vote, SAC, leader-based}, 3 backbone model families (to control for model-specific susceptibility), multiple seeds per cell.
- **Baselines:** Single-agent (no consensus) as a floor; majority vote as the classical/simplest aggregator; SAC as current SOTA Byzantine-robust aggregator; leader-based coordination as the "most attackable" reference point per DecentLLMs' framing.
- **Metrics:** Task success rate (bug actually fixed / review verdict correct) vs. adversarial fraction and strategy; consensus-protocol "effective robustness" (TAMAS-style score) per condition; degradation-curve slope compared against the classical BFT step-function prediction.
- **Ablations:** Colluding vs. independent-but-identical-strategy adversaries (isolating collusion's marginal effect); model-homogeneous vs. model-heterogeneous agent pools (heterogeneity is known to help in Zhang et al.); with/without SAC's graph-robustness mechanism.
- **Expected result:** A degradation curve that matches classical BFT under naive adversaries but breaks down earlier (below 1/3) under persuasive/colluding strategies, with SAC's advantage over majority vote narrowing specifically in the colluding condition.
- **What would falsify it:** If degradation curves are strategy-invariant (persuasive/colluding adversaries are no more damaging than naive ones) or SAC's robustness margin holds constant across strategies, the hypothesis is falsified — suggesting existing graph-robust aggregation already generalizes to strategic adversaries without further work.
- **Expected contribution:** First systematic test of whether classical BFT thresholds transfer to LLM multi-agent consensus under realistic tasks and strategic (not just naive) adversaries, plus an empirical boundary condition for when SAC-style defenses hold vs. fail.
- **Novelty classification:** **C** — underexplored: SAC is close prior art and must be directly extended/differentiated, not treated as an open gap in isolation.
- **Evidence supporting novelty:** SAC itself is scoped to math/commonsense; no located paper sweeps strategy type (esp. collusion/steganography) against a realistic task domain with a BFT-threshold framing.
- **Evidence threatening novelty:** SAC (2605.09076) already does the core F/N sweep with graph-theoretic guarantees — this is the single biggest novelty risk in this report; if SAC's authors or a near-term follow-up extend to strategic adversaries or realistic tasks first, this candidate's contribution shrinks to "SAC replication in a new domain," which is meaningfully weaker.
- **Implementation difficulty:** Medium-high — requires building a credible multi-agent coding-consensus harness plus validated adversarial personas (collusion/steganography prompts need piloting to confirm they're not just noise).
- **Compute requirement:** Medium — many LLM API calls (agents × fraction × strategy × protocol × seeds × tasks); budget-sensitive, should scope task count carefully (e.g., 50–100 SWE-bench-Lite instances, not the full set).
- **Expected duration:** 2 semesters, with real risk of scope creep given the many-factor design — recommend fixing N and task count early and treating strategy/protocol as the primary swept variables.
- **Publication potential:** NeurIPS/ICML MAS workshop first (fast-moving area, workshops are the current locus of this literature per the citations above), potential upgrade to a security venue (USENIX Security, CCS) if the collusion/steganography angle is developed rigorously.
- **Reviewer #2 objections:** "SAC already did the fraction sweep — what's actually new here?" "Are your 'colluding' adversary prompts a real threat model or just harder prompts?" "API cost/compute budget for this many-factor design seems undersold for an undergrad project."
- **Answers:** SAC's sweep is on math/commonsense with (implicitly) simple adversaries; this work's contribution is specifically the strategy dimension and realistic-task transfer, which must be stated as the delta from SAC in the very first paragraph, not left implicit. Collusion prompts should be validated against a manipulation-check (do independent raters agree these represent genuine collusion, not just verbosity) before being called a threat model. Compute budget must be fixed and justified early (Phase 9) — this is the correct place to trim scope if needed.
- **Professor attack-test result:** Partially survives — a serious researcher would immediately ask "why isn't this just SAC + harder prompts," and the answer must be sharp (BFT-threshold framing + realistic task + collusion, stated as the specific triple SAC doesn't cover) or the proposal should be downgraded in priority relative to Candidates 1–2.

---

### 4. Binding-Constraint Retention Under Context Compression in Realistic Long-Horizon Agents

**Novelty: C — Underexplored (crowding fast)** · `benchmark` `agents`

> Does context compression in LLM coding/web agents preserve exact action-critical facts (IDs, filenames, numeric constraints) on real long-horizon benchmarks, not just a synthetic proxy task?

- **Field:** NLP / AI Agents (ICML, NeurIPS, ACL, agent-specific workshops)
- **Problem:** LLM agents executing long, multi-step tasks (coding, web navigation) rely on context compression/summarization to manage token budgets; whether compression preserves exact action-critical facts (a filename, a ticket ID, a numeric constraint that must be referenced identically later) — as opposed to general topical content — is largely untested on real agent benchmarks.
- **Known:** Naive compression can catastrophically destroy action-critical state: a 2026 preprint (Sun et al.) shows standard compression drives forbidden-action rates to 54.2% in a synthetic "safety blocker" testbed, fully fixed by restoring specific state fields. A separate line (Mehta et al.) shows plan signal in agent hidden states decays 4.1–12.4x within one step and naive plan eviction costs 34.7pp on ALFWorld. Meanwhile, learned/optimized compressors (ACON, Microsoft, ICML 2026; AdaCoM) report net-positive results (26–54% token reduction with improved success) — but evaluate end-task success, not fact-level fidelity, so it's unclear whether they've actually solved the binding-constraint problem or simply weren't tested against it.
- **Closest 5–10 papers:** Constraint Weakening in LLM Agent Workflows (Sun et al., [2608.24569](https://arxiv.org/abs/2608.24569)); On Problems of Implicit Context Compression for SWE Agents (Gelvan et al., [2605.11051](https://arxiv.org/abs/2605.11051)); Plans Don't Persist (Mehta et al., [2606.22953](https://arxiv.org/abs/2606.22953)); ACON (Kang et al., ICML 2026, [2510.00615](https://arxiv.org/abs/2510.00615)); The Long-Horizon Task Mirage ([2604.11978](https://arxiv.org/abs/2604.11978)); Diagnosing and Mitigating Context Rot in Long-horizon Search ([2606.29718](https://arxiv.org/abs/2606.29718)); AdaCoM ([2605.30785](https://arxiv.org/abs/2605.30785)); SWE-Bench Pro (Deng et al., Scale AI, [2509.16941](https://arxiv.org/abs/2509.16941)).
- **Limitations in those papers:** Sun et al. (closest paper) uses a synthetic, single-domain proxy (explicit "safety blocker" artifacts), not real code/web artifacts with naturally occurring IDs/filenames/numeric constraints. Gelvan et al. explicitly defer root-cause isolation of what gets lost to future work. ACON/AdaCoM measure end-task success only, not fact-level fidelity — they may or may not solve the exact-fact problem, but don't report on it directly.
- **Exact gap:** No paper measures exact-match retention of action-critical primitives (file paths, variable names, numeric IDs) under compression across real, large-scale long-horizon agent benchmarks (SWE-bench/WebArena-scale), separating "topic preserved" from "binding constraint preserved" as Sun et al. does only in a synthetic sandbox.
- **Why it matters:** If the synthetic-sandbox finding generalizes to real coding/web agents, it implies current SOTA compressors (ACON etc.) may be silently failing on exactly the failures that matter most (wrong file edited, wrong ID referenced) while still scoring well on aggregate task-success metrics that don't specifically probe this.
- **Proposed solution:** A targeted diagnostic benchmark built on top of SWE-bench-Lite/WebArena trajectories: inject controlled compression at varying points/rates, then probe exact-match retention of naturally-occurring action-critical entities via automated extraction (AST-based for code, DOM-element IDs for web) rather than the synthetic blocker artifacts Sun et al. use.
- **Novel mechanism:** Replacing synthetic proxy artifacts with automatically-extracted real entities from existing benchmark trajectories as the retention probe — directly testing whether Sun et al.'s finding is an artifact of their synthetic design or a general property of compression, and whether "compression-helps" papers (ACON/AdaCoM) actually preserve these entities or just get lucky on the aggregate metric.
- **Hypothesis:** We hypothesize that standard/naive compressors will show significantly lower exact-match retention of action-critical entities than of general topical content on real SWE-bench/WebArena trajectories (replicating Sun et al.'s direction outside the synthetic sandbox), and that ACON/AdaCoM-style optimized compressors will show smaller but still non-trivial retention gaps, revealing a previously unmeasured failure mode in methods currently reported as solving compression.
- **Dataset:** SWE-bench-Lite and WebArena trajectory logs (public); automated entity extraction via AST parsing (code) and accessibility-tree parsing (web).
- **Experimental setup:** Compress trajectories at 3–4 compression ratios using naive summarization, ACON, and AdaCoM; measure exact-match retention of extracted entities vs. downstream task success, across both domains.
- **Baselines:** No compression (upper bound); naive/generic summarization (lower bound); ACON and AdaCoM as current SOTA "solved" baselines to test whether the gap actually closes.
- **Metrics:** Entity-level exact-match retention rate; downstream task success; correlation (or lack thereof) between the two, to test whether aggregate success masks entity-level failure.
- **Ablations:** Retention by entity type (filename vs. numeric ID vs. variable name); retention as a function of distance (turns since entity last appeared) before compression.
- **Expected result:** A measurable retention gap for action-critical entities vs. general content, present even in ACON/AdaCoM, smaller than naive compression but non-zero.
- **What would falsify it:** If ACON/AdaCoM show near-ceiling retention with no gap vs. general content, the hypothesis is falsified — current SOTA compressors would already generalize the binding-constraint problem's solution beyond the synthetic setting Sun et al. tested.
- **Expected contribution:** Empirical validation (or falsification) of whether a synthetic-sandbox finding generalizes to real agent benchmarks, plus a reusable entity-retention diagnostic that can be applied to future compressors.
- **Novelty classification:** **C** — underexplored, but only barely; the core mechanism is already proposed (Sun et al., Aug 2026), so this is best framed as an external-validity/replication-plus-extension study, not a from-scratch discovery.
- **Evidence supporting novelty:** Gelvan et al. explicitly state root-cause isolation is future work; no located paper runs the exact-entity-retention probe on real (non-synthetic) long-horizon benchmarks.
- **Evidence threatening novelty:** Sun et al. (2608.24569, Aug 2026) is functionally the same core idea already published, just in a synthetic domain — this is the weakest-novelty candidate in this report and should be pitched explicitly as an extension/validation study, with credit given up front, or a reviewer will (correctly) call it a minor variation.
- **Implementation difficulty:** Medium — entity extraction pipelines (AST/DOM parsing) are standard tooling; the research contribution is in the measurement design, not novel systems building.
- **Compute requirement:** Medium — running multiple compressors across many trajectories at SWE-bench/WebArena scale involves substantial API cost; can be trimmed via a curated subset.
- **Expected duration:** 1–2 semesters — narrower scope than Candidates 1–3 since it's fundamentally a measurement/replication study.
- **Publication potential:** Workshop-tier (agents workshop at NeurIPS/ICML/ACL) realistically; main-track only if the retention gap turns out to be large and surprising even for SOTA compressors.
- **Reviewer #2 objections:** "This is just Sun et al. run on a different benchmark." "Where's the algorithmic contribution?"
- **Answers:** Honest answer: there isn't a strong algorithmic contribution here — this is fundamentally an external-validity study, and should be positioned as such (a legitimate but modest contribution type), not oversold as discovering a new mechanism.
- **Professor attack-test result:** Weakest of the five investigated niches on the "why hasn't someone done this" test — because someone essentially has, just not on real benchmarks. Retained in this report for completeness and honesty, but **not recommended** as a top-3 pick.

---

### 5. Generation-Level Faithfulness Under Temporal-Conflict Density in RAG

**Novelty: C — Underexplored (crowded space)** · `benchmark` `NLP`

> As the fraction of retrieved-but-superseded passages increases, does end-to-end RAG generation faithfulness degrade in a measurable dose-response curve — and does exposing recency metadata fix it?

- **Field:** NLP / Information Retrieval (ACL, EMNLP, COLM, KDD)
- **Problem:** Standard RAG faithfulness benchmarks (RAGAS, KILT) assume a static, non-contradictory corpus; real corpora accumulate stale-but-still-indexed documents, and it's unclear whether generation-level faithfulness degrades smoothly as the fraction of retrieved stale passages increases, or whether models can reliably use recency signals to resolve conflicts when given the chance.
- **Known:** KILT/RAGAS assume corpus stability. FreshLLMs/FreshQA show all tested LLMs struggle on fast-changing facts. HoH shows outdated info degrades accuracy and can be harmful even when current info is co-present. Temporal Wiki/Unified Clark (Özer & Yıldız, 2025) show LLMs "struggle to reconcile conflicting or outdated facts" and are "misled when multiple versions of a fact appear." FRESCO (2026) shows rerankers systematically prefer semantically dense-but-obsolete passages over correct recent ones (Obsolete Ratio 84–98%) — but at the reranking stage, not generation.
- **Closest 5–10 papers:** KILT (Petroni et al., NAACL 2021, [2009.02252](https://arxiv.org/abs/2009.02252)); Lost in the Middle (Liu et al., TACL 2024, [2307.03172](https://arxiv.org/abs/2307.03172)); FreshLLMs/FreshQA (Vu et al., ACL Findings 2024, [2310.03214](https://arxiv.org/abs/2310.03214)); HoH (Ouyang et al., ACL 2025, [2503.04800](https://arxiv.org/abs/2503.04800)); RAG with Conflicting Evidence / RAMDocs (Wang, Prasad, Stengel-Eskin, Bansal, COLM 2025, [2504.13079](https://arxiv.org/abs/2504.13079)); QA under Temporal Conflict (Özer & Yıldız, [2506.07270](https://arxiv.org/abs/2506.07270)); FRESCO (An et al., [2604.14227](https://arxiv.org/abs/2604.14227)); Knowledge Conflicts for LLMs: A Survey (Xu et al., [2403.08319](https://arxiv.org/abs/2403.08319)).
- **Limitations in those papers:** RAMDocs mixes ambiguity/misinformation/noise, not isolated temporal conflict. Temporal Wiki/Unified Clark test presence/absence of conflict, not a parametric density sweep. FRESCO is reranker-stage only, with obsolescence ratio as an aggregate outcome, not swept as an independent variable on generation faithfulness. No located paper toggles recency-metadata visibility as a controlled manipulation on generation-level faithfulness specifically.
- **Exact gap:** No paper parametrically varies temporal-conflict density (0%→100% stale passages in the retrieved set) while toggling recency-signal visibility, and measures end-to-end generation faithfulness/citation-of-outdated-info as the dependent variable (as opposed to reranking accuracy or presence/absence conflict effects).
- **Why it matters:** Production RAG systems over living document stores (internal wikis, changing policies, software docs) will have non-zero, variable staleness fractions; knowing whether faithfulness degrades gracefully or has a sharp failure threshold — and whether simply exposing timestamps fixes it — is directly actionable for RAG system design.
- **Proposed solution:** A controlled benchmark built from versioned document sources (Wikipedia revision history, or software documentation with version tags) where conflict density is an explicit independent variable; measure generation faithfulness (RAGAS-style, extended to penalize citation of superseded facts) as density and recency-visibility are swept.
- **Novel mechanism:** Treating "conflict density" as a continuous dose variable (rather than binary presence/absence, as in prior work) and measuring the interaction with recency-signal visibility — isolating whether the failure is a retrieval-composition problem or a generation-reasoning problem.
- **Hypothesis:** We hypothesize that generation faithfulness degrades non-linearly (not just monotonically) as stale-passage density increases beyond a threshold (predicted around 30–50% based on the "co-presence is itself harmful" finding in HoH), and that exposing explicit recency metadata significantly improves faithfulness at high density but does not fully eliminate the degradation, indicating a genuine reasoning limitation beyond a mere information-availability problem.
- **Dataset:** Wikipedia revision-diff-based temporal corpus (extending the Temporal Wiki construction methodology) or a software-documentation version corpus (e.g., versioned API docs) for a more realistic RAG-deployment analog than encyclopedia facts.
- **Experimental setup:** Sweep stale-passage density ∈ {0, .2, .4, .6, .8, 1.0} × recency-metadata visible/hidden × 3–4 model families, measuring faithfulness and citation-of-outdated-fact rate.
- **Baselines:** RAGAS faithfulness as the standard metric baseline; FRESCO's obsolescence-ratio reranking as a retrieval-stage comparison point (to test whether fixing retrieval alone suffices, or generation-stage failures persist even with a perfect reranker); naive most-recent-first heuristic as a simple non-learned baseline.
- **Metrics:** Faithfulness score (extended RAGAS); citation-of-outdated-fact rate; answer correctness; degradation curve shape (linear vs. threshold) fit statistically.
- **Ablations:** Recency metadata visible vs. hidden vs. explicitly instructed-to-use; perfect reranking (oracle retrieval order) vs. realistic retrieval, to separate retrieval-composition from generation-reasoning failure.
- **Expected result:** A non-linear degradation curve with a visible threshold effect, partially but not fully mitigated by recency-metadata visibility.
- **What would falsify it:** If faithfulness degrades linearly and recency-metadata visibility fully restores baseline faithfulness at all densities, the hypothesis is falsified — the failure would be a simple information-availability problem, not a deeper reasoning limitation.
- **Expected contribution:** First dose-response characterization of RAG generation faithfulness under temporal conflict density, differentiating retrieval-stage from generation-stage failure and directly extending FRESCO/HoH/Temporal Wiki rather than duplicating them.
- **Novelty classification:** **C** — underexplored but crowded: multiple close papers from 2025–2026 alone (FRESCO, HoH, Temporal Wiki) mean this needs very careful differentiation and a final novelty-killing search immediately before write-up, given the pace of preprints in this niche.
- **Evidence supporting novelty:** No located paper does the specific parametric density sweep on generation faithfulness with a recency-visibility toggle; FRESCO's closest analog is reranking-stage only.
- **Evidence threatening novelty:** This niche has the highest 2026 preprint velocity of any candidate in this report (agent flagged "multiple relevant papers from Q2 2026 alone") — real risk of being scooped between proposal and completion; a fresh novelty-killing search should be re-run at project kickoff, not just at proposal time.
- **Implementation difficulty:** Medium — building the versioned corpus and density-controlled retrieval sets is the main engineering task; faithfulness scoring can reuse/extend RAGAS.
- **Compute requirement:** Medium — multiple model families × density levels × visibility conditions; manageable with API-based models and a moderate-sized benchmark (a few hundred to low-thousands of examples).
- **Expected duration:** 1–2 semesters.
- **Publication potential:** ACL/EMNLP/COLM findings track plausible given how many adjacent papers have placed there recently; competitive due to crowding.
- **Reviewer #2 objections:** "How is this different from FRESCO/HoH/Temporal Wiki?" "Isn't 'conflict density' just a relabeling of retrieval quality?"
- **Answers:** Explicit differentiation table against all three papers must appear in the introduction (retrieval- vs. generation-stage, binary vs. continuous conflict, presence/absence vs. dose-response) — this is a crowded space where the paper lives or dies on a crisp related-work delta. Conflict density is distinct from generic retrieval quality because it specifically manipulates version-conflict composition while holding topical relevance constant, which the ablation design must demonstrate.
- **Professor attack-test result:** Survives conditionally — the crowding is real and must be confronted head-on in the framing, not hidden; recommend treating this as a strong secondary candidate rather than the primary bet given how fast the space is moving.

---

### 6. Decoupling Sycophancy-Driven Debate Collapse from Adversarial Attack in Multi-Agent LLMs

**Novelty: C — Underexplored** · `algorithmic` `emerges from Candidate 3`

> Does multi-agent debate accuracy decline purely from social-conformity pressure among honest agents, independent of any adversary — and if so, what structural interventions (not adversary-defense mechanisms) fix it?

- **Field:** Multi-Agent Systems / NLP
- **Problem:** Wynn et al. (2509.05396) found multi-agent debate accuracy can decline over rounds purely from sycophancy/social conformity among correct-model agents — a distinct failure mode from Byzantine/adversarial attack, but the two are often conflated or studied with the same defenses (robust aggregation), which may not address a purely social-conformity-driven failure.
- **Known:** Wynn et al. show debate accuracy decreases even when correct agents outnumber incorrect ones; Wu, Li, Li (2511.07784) show debate often collapses to consensus-forming rather than genuine deliberation under majority pressure. These are honest-agent failures, structurally different from the Byzantine-robustness literature (Candidate 3), which assumes some agents are actively malicious.
- **Closest papers:** Wynn, Satija, Hadfield ([2509.05396](https://arxiv.org/abs/2509.05396)); Wu, Li, Li ([2511.07784](https://arxiv.org/abs/2511.07784)); Zhang et al. ([2502.08788](https://arxiv.org/abs/2502.08788)); Du et al. ([2305.14325](https://arxiv.org/abs/2305.14325)).
- **Limitations:** Wynn et al. characterizes the phenomenon (capability-diversity effect on failure modes) but doesn't systematically test structural interventions (anonymized voting, staged/independent-first-pass protocols, diversity-enforced agent pools) as fixes specifically for sycophancy, as opposed to Byzantine-robust aggregation which targets a different threat model.
- **Exact gap:** No paper isolates sycophancy-driven collapse from adversarial attack as a distinct problem requiring distinct (non-BFT-style) interventions, nor tests whether standard Byzantine-robust aggregation (SAC etc.) helps or is irrelevant to purely social-conformity-driven degradation.
- **Why it matters:** If practitioners deploy Byzantine-robust consensus mechanisms assuming they'll also fix "debate gets worse over rounds," but the cause is social conformity not malice, those defenses would be misapplied — a genuine conceptual clarification with practical stakes.
- **Hypothesis:** We hypothesize that Byzantine-robust aggregation (SAC-style) provides no significant improvement over majority vote under pure sycophancy-driven degradation (no adversaries present), while structural interventions (independent-first-pass, anonymized voting) do — demonstrating the two failure modes require different fixes.
- **Novelty classification:** **C**
- **Evidence supporting/threatening:** Supporting: Wynn et al. explicitly frames this as distinct from adversarial robustness but stops short of testing fixes. Threatening: this is a smaller, more narrowly-scoped question that might be judged as "incremental" (B) rather than a strong C by a skeptical reviewer, since it's essentially a targeted ablation/extension of Wynn et al.
- **Implementation difficulty / Compute / Duration:** Low-medium; single-semester feasible; reuses Candidate 3's harness with adversaries removed.
- **Publication potential:** Workshop-tier primarily; a clean negative/boundary result (BFT defenses don't transfer) is publishable but modest in scope.

*Presented at reduced detail — a natural sub-study of Candidate 3 rather than a fully independent project; strong as a scoped-down fallback if Candidate 3's full design proves too resource-intensive.*

---

### 7. Locating Temporal-Conflict Failure in the RAG Pipeline: Reranker vs. Generator

**Novelty: C — Underexplored** · `empirical` `emerges from Candidate 5`

> FRESCO shows rerankers prefer stale-but-dense passages 84–98% of the time — is the dominant failure mode retrieval/ranking, or does the generator independently fail even given a perfectly-ranked retrieved set?

- **Field:** Information Retrieval / NLP
- **Problem:** FRESCO (2604.14227) isolates a severe reranker-stage failure (Obsolete Ratio 84–98%) in preferring stale-but-semantically-dense passages; it's unknown how much of end-to-end RAG temporal-conflict failure is attributable to this ranking stage versus an independent generation-stage reasoning failure once the correct passage is already ranked highly.
- **Known:** FRESCO establishes the ranking-stage failure in isolation (reranker output only). HoH and Temporal Wiki establish generation-stage degradation but with realistic (imperfect) retrieval, confounding the two stages.
- **Closest papers:** FRESCO ([2604.14227](https://arxiv.org/abs/2604.14227)); HoH ([2503.04800](https://arxiv.org/abs/2503.04800)); Temporal Wiki ([2506.07270](https://arxiv.org/abs/2506.07270)).
- **Exact gap:** No paper decomposes end-to-end temporal-conflict failure into a ranking-stage vs. generation-stage attribution using an oracle-retrieval control condition.
- **Hypothesis:** We hypothesize that even with oracle (perfectly-ranked, most-recent-first) retrieval, generation faithfulness remains meaningfully below the no-conflict ceiling — i.e., ranking failure (FRESCO) and generation failure are both independently necessary explanations, not one subsuming the other.
- **Novelty classification:** **C**
- **Evidence supporting/threatening:** Supporting: this decomposition wasn't found in any retrieved paper. Threatening: this is essentially the "oracle retrieval" ablation from Candidate 5 promoted to a standalone question — reviewers may see it as a sub-experiment rather than a full project.
- **Implementation difficulty / Compute / Duration:** Low-medium; reuses Candidate 5's corpus; single semester feasible as a focused study.
- **Publication potential:** Short paper / workshop track; best positioned as a component of Candidate 5 rather than standalone.

---

### 8. Does Signal Framing (Not Just Presence) of AI Confidence Change Risk-Differentiated Trust Calibration?

**Novelty: C — Underexplored** · `empirical` `emerges from Candidate 2`

> Vasconcelos et al. showed edit-likelihood signals beat raw-probability signals for general calibration — does that advantage hold, shrink, or reverse specifically for security-sensitive code?

- **Field:** Human-AI Interaction / Software Engineering
- **Problem:** Vasconcelos et al. (TOCHI 2024) found edit-likelihood highlighting improves calibration over raw generation-probability highlighting in general coding tasks; whether this advantage is uniform across risk categories, or specifically weaker/stronger for security-sensitive code, is untested.
- **Known:** Raw-probability confidence display gave no general benefit; edit-likelihood did. Perry et al. show AI presence alone inflates false security confidence. No study crosses signal type with risk category.
- **Closest papers:** Vasconcelos et al. ([2302.07248](https://arxiv.org/abs/2302.07248)); Perry et al. ([2211.03622](https://arxiv.org/abs/2211.03622)); Baltes et al. ([2504.12461](https://arxiv.org/abs/2504.12461)).
- **Exact gap:** No paper crosses confidence-signal type (raw probability vs. edit-likelihood vs. none) with code-risk category as a 2-factor design.
- **Hypothesis:** We hypothesize edit-likelihood highlighting's calibration advantage over raw probability shrinks specifically for security-sensitive code, because edit-likelihood signals surface stylistic/syntactic uncertainty rather than semantic/security risk, which raw probability doesn't capture either — predicting both signal types underperform equally on high-risk code.
- **Novelty classification:** **C**
- **Evidence supporting/threatening:** Supporting: genuinely untested 2-factor cross found in the literature scan. Threatening: this is a natural 2×2 extension of Candidate 2's design (risk category is already one factor there) — best absorbed as an ablation arm of Candidate 2 rather than run as a separate project, unless resourcing allows both.
- **Implementation difficulty / Compute / Duration:** Low if merged into Candidate 2's study design (same IRB, same task battery, added signal-type arm); otherwise duplicative IRB/participant cost.
- **Publication potential:** Strongest as a secondary finding within Candidate 2's paper, not a standalone submission.

---

### 9. Reconciling the Personalization–Robustness Tradeoff Under Temporally (Not Just Spatially) Correlated Drift

**Novelty: C — Underexplored** · `algorithmic` `emerges from Candidate 1`

> Ditto claims personalization achieves both fairness and robustness; FedDrift shows temporally-staggered drift breaks single-global-model correction — does personalization's claimed win survive when non-IID-ness is time-varying, not just static?

- **Field:** Federated Learning
- **Problem:** Ditto (Li, Hu, Beirami, Smith, ICML 2021) reports personalization can achieve both fairness and robustness on standard (static non-IID) federated benchmarks; FedDrift (AISTATS 2023) shows single-global-model correction methods are "ill-suited" once drift is staggered across time and clients — it's untested whether Ditto's personalization result, validated under static heterogeneity, survives under the temporally-staggered drift regime FedDrift specifically targets.
- **Known:** Both papers are well-cited, methodologically solid, and evaluated on different heterogeneity regimes (static vs. temporally-staggered) — a direct evaluation-condition contradiction rather than a resolved finding.
- **Closest papers:** Ditto ([2012.04221](https://arxiv.org/abs/2012.04221)); FedDrift ([2206.00799](https://arxiv.org/abs/2206.00799)); SCAFFOLD ([1910.06378](https://arxiv.org/abs/1910.06378)).
- **Exact gap:** No paper evaluates Ditto-style personalization directly against FedDrift's temporally-staggered drift benchmark to test whether the fairness/robustness win generalizes from static to dynamic non-IID conditions.
- **Hypothesis:** We hypothesize Ditto's personalization advantage over fairness/robustness baselines shrinks or reverses under temporally-staggered drift, because personalization to a moving target compounds tracking error in a way static personalization does not.
- **Novelty classification:** **C**
- **Evidence supporting/threatening:** Supporting: a clean, previously unexamined cross-condition test between two well-cited but disjointly-evaluated papers. Threatening: relatively narrow in scope (an empirical cross-benchmark test rather than a new mechanism); could be seen as "just running Ditto on FedDrift's benchmark," which is closer to B (incremental) unless paired with a diagnostic contribution (e.g., decomposing why personalization fails under drift).
- **Implementation difficulty / Compute / Duration:** Low-medium; both codebases are public; single semester feasible; natural complement to Candidate 1's infrastructure (same FL simulation stack).
- **Publication potential:** Workshop-tier; strongest if run as a natural companion study alongside Candidate 1, sharing infrastructure.

---

### 10. Capability-Dependent Compression Policy for Binding-Constraint Preservation

**Novelty: C — Underexplored** · `algorithmic` `emerges from Candidate 4`

> AdaCoM found a "Fidelity–Reliability trade-off" where weaker agents need more aggressive pruning — does this same capability-dependence apply specifically to binding-constraint (not just general) retention?

- **Field:** AI Agents / NLP
- **Problem:** AdaCoM (2605.30785) found weaker agents benefit from aggressive context pruning while stronger agents benefit from retaining more content (a general fidelity-reliability trade-off); whether this same capability-dependence holds specifically for binding-constraint retention (Candidate 4's concern) — or whether weaker models need *more* aggressive binding-constraint protection precisely because they're worse at re-deriving lost constraints — is untested.
- **Known:** AdaCoM's trade-off is characterized at the level of general content/fidelity, not decomposed into constraint-critical vs. general-topical retention.
- **Closest papers:** AdaCoM ([2605.30785](https://arxiv.org/abs/2605.30785)); Sun et al. ([2608.24569](https://arxiv.org/abs/2608.24569)); ACON ([2510.00615](https://arxiv.org/abs/2510.00615)).
- **Exact gap:** No paper tests whether AdaCoM's general capability-dependent compression policy should differ specifically for binding-constraint content, as opposed to general fidelity.
- **Hypothesis:** We hypothesize weaker models require disproportionately higher binding-constraint retention (relative to general content) than AdaCoM's general policy prescribes, because weaker models are less able to recover or infer dropped constraints from remaining context.
- **Novelty classification:** **C**
- **Evidence supporting/threatening:** Supporting: a genuinely unexamined interaction between two recent findings (AdaCoM's capability-dependence, Sun et al.'s binding-constraint fragility). Threatening: this candidate compounds Candidate 4's already-thin novelty margin (Sun et al. is close prior art) with AdaCoM's — a double dependency on very recent 2026 preprints makes this the most fragile candidate in the set if either underlying paper is extended by its own authors first.
- **Implementation difficulty / Compute / Duration:** Medium; would need both AdaCoM's and Sun et al.'s experimental setups reproduced as a starting point — meaningful reproduction risk for an undergrad timeline.
- **Publication potential:** Workshop-tier at best; recommended only as a stretch/backup idea, not a primary pick.

---

## Top 3, ranked

| Rank | Candidate | Type | Novelty | Key strength | Key risk |
|---|---|---|---|---|---|
| **1** | FL under MNAR client participation | Algorithmic | D | Cleanest falsifiability, no IRB, strong existing baselines, gap explicitly named in prior work | DCPA must beat plain-IPW ablation or contribution narrows to empirical characterization |
| 2 | Risk-differentiated trust calibration | Empirical/HCI | D | Gap explicitly named by a 2026 critical review; high real-world impact on tool design | IRB timeline risk for an undergrad schedule |
| 3 | Multi-agent Byzantine robustness, strategic adversaries | Frontier/Algorithmic | C | Hot, fast-moving frontier with direct security relevance | SAC (2605.09076) is close prior art — differentiation burden is highest of the three |

These three are deliberately heterogeneous: #1 is algorithmic/systems, #2 is empirical/human-subjects, #3 is an emerging-frontier security question — per the diversity requirement. **#1 is selected as the primary recommendation** because it has the lowest execution risk (no human-subjects timeline, no closest-prior-art paper doing nearly the same thing) while still clearing the D novelty bar with direct textual evidence from the closest paper naming the gap as open.

---

## Full paper skeleton — Candidate #1

### Title
Federated Learning Under Missing-Not-At-Random Client Participation: Quantifying and Correcting Drift-Correlated Dropout

### Abstract
Federated learning (FL) robustness methods are validated under client dropout mechanisms that are statistically independent of each client's current data distribution. In many real edge deployments — industrial sensors, health wearables, connectivity-limited devices — dropout is plausibly caused by the same underlying conditions that produce concept drift, violating this independence assumption. We formalize this as missing-not-at-random (MNAR) client participation, borrowing Rubin's missing-data taxonomy, and show through controlled experiments that standard FL methods (FedAvg, FedProx, SCAFFOLD, FedDrift, KPFL) degrade superlinearly as drift-dropout coupling strength increases, exceeding their reported robustness under equal-magnitude random dropout. We propose Drift-Cluster Proxy Aggregation (DCPA), which extends drift-clustering with an MNAR-aware proxy correction, and show it recovers a majority of the gap at high coupling strength without degrading standard-case performance.

### Introduction
Motivate with the concrete deployment scenario (industrial IoT anomaly detection) where the clients most worth learning from are exactly those most likely to be silent. State the core research question and the two-literatures framing (drift-across-clients vs. selection-biased participation) that have not been combined.

### Problem Statement
Existing FL robustness and drift-adaptation methods optimize for accuracy/fairness under the assumption that client availability is independent of (or, at best, covariate-dependent-but-drift-independent from) the client's current local distribution. None evaluate performance when availability is causally coupled to drift itself. Consequently, it remains unknown whether existing methods' reported robustness generalizes to deployments where informative missingness is present, and by how much performance degrades as coupling strength increases.

### Research Questions
RQ1: How does global model accuracy and per-client fairness degrade as drift-dropout coupling strength ρ increases, relative to equal-magnitude MCAR dropout?
RQ2: Can a drift-clustering-based proxy correction (DCPA) recover performance under high coupling, and does it do so beyond what a generic MNAR-debiasing baseline (IPW) achieves alone?

### Literature Review
Structured around: (a) heterogeneity-robust FL (FedProx, SCAFFOLD) — static heterogeneity only; (b) drift-adaptive FL (FedDrift) — drift modeled, availability given; (c) participation-bias-aware FL (FedIPW/"Who Trains Matters", FedAPM) — selection modeled generally, not drift-causal; (d) applied/measurement papers (Kairouz et al., Google's applied FL) establishing real-world availability is temporally structured, motivating the coupling assumption's plausibility.

### Research Gap
No existing work quantifies FL performance under drift-caused (MNAR) client dropout, and no existing correction method is evaluated against this specific failure mode; DPFL/KPFL (2511.16523) explicitly names this as future work.

### Hypothesis
**H1:** Global model error for FedAvg/FedProx/SCAFFOLD/FedDrift/KPFL grows superlinearly in ρ (coupling strength), significantly exceeding degradation under equal-magnitude MCAR dropout (independent variable: ρ; dependent variable: global test error and client-fairness variance; baseline: same methods under ρ=0; direction: increasing degradation; setting: LEAF FEMNIST/Shakespeare + Office-Caltech-10 federated benchmarks).

**H2:** DCPA reduces excess error (relative to the strongest baseline) by ≥20% at ρ≥0.6 without degrading performance at ρ=0, and outperforms a plain-IPW-under-MNAR ablation at all ρ>0.

### Methodology
Simulation-based controlled experiment using an FL simulator (Flower or LEAF's harness). Coupling injected by making per-round, per-client dropout probability a monotonic function of that client's current local drift magnitude (measured via a held-out local-loss proxy), parameterized by ρ.

### System Architecture
Standard FL client-server simulation loop; DCPA adds (1) a drift-clustering module (adapted from FedDrift) run each round on currently-online clients, (2) a proxy-imputation step that represents offline clients via their most recent same-cluster online neighbor, weighted by an uncertainty discount that decays with rounds-since-last-seen and cluster-membership confidence.

### Algorithm
DCPA pseudocode: for each round, (a) cluster online clients by recent drift signature; (b) for each offline client, retrieve its last-known cluster assignment; (c) if a same-cluster online client exists this round, use its update as a discounted proxy contribution; (d) aggregate real + proxy contributions with confidence-weighted averaging; (e) update cluster assignments as new information arrives.

### Experimental Design
ρ ∈ {0, .2, .4, .6, .8, 1.0} × 3 non-IID severity levels × 5 baselines + DCPA × 5 seeds. Fixed communication-round budget across conditions.

### Baselines
FedAvg (classical), FedProx/SCAFFOLD (heterogeneity-robust SOTA), FedDrift/KPFL (drift-aware SOTA), FedIPW-style debiasing (closest selection-bias-aware method), and a DCPA-without-clustering ablation (plain proxy nearest-neighbor).

### Metrics
Global test accuracy vs. ρ; worst-client and variance-based fairness; drift-detection recall restricted to the informatively-dropped-out subpopulation; communication/compute overhead of DCPA.

### Ablation Study
(a) DCPA − drift clustering; (b) DCPA − uncertainty discount; (c) oracle upper bound (drift state revealed even when offline).

### Threats to Validity
**Internal:** synthetic coupling injection may not capture the full causal complexity of real anomaly-driven connectivity loss — mitigated by the stretch-goal real industrial-IoT validation.
**Construct:** drift-magnitude proxy used to drive coupling may itself be imperfect.
**External:** results on LEAF/Office-Caltech benchmarks may not transfer to other domains (e.g., NLP federated tasks) without further validation.
**Statistical:** 5 seeds per cell; report confidence intervals and significance tests (paired t-test or Wilcoxon across seeds) for all headline comparisons.

### Expected Results
A statistically significant, superlinear degradation curve in ρ for all baselines; DCPA recovering the majority of the gap at high ρ while matching baselines at ρ=0; DCPA beating the plain-IPW ablation, isolating the value of the drift-clustering proxy specifically.

### Contributions
1. First controlled, quantitative characterization of FL robustness under MNAR (drift-caused) client dropout.
2. DCPA, a drift-clustering-based MNAR correction with an explicit, testable boundary condition.
3. A reusable benchmark protocol for injecting tunable drift-dropout coupling on top of standard FL benchmarks.

### Limitations
Coupling is synthetically injected in the primary experiments; DCPA's guarantees are empirical, not proven under adversarial coupling; scope limited to cross-device FL (not cross-silo) settings.

### Future Work
Extend to real industrial-IoT connectivity data; theoretical convergence analysis of DCPA under bounded coupling strength; extension to cross-silo settings with fewer, larger clients.

### References
See full reference list below — all papers cited in Candidate 1's fields.

---

## References (all live-verified)

- Caldas et al. LEAF: A Benchmark for Federated Settings. [arXiv:1812.01097](https://arxiv.org/abs/1812.01097)
- Li, Sahu, Zaheer, Sanjabi, Talwalkar, Smith. Federated Optimization in Heterogeneous Networks (FedProx). MLSys 2020. [arXiv:1812.06127](https://arxiv.org/abs/1812.06127)
- Karimireddy, Kale, Mohri, Reddi, Stich, Suresh. SCAFFOLD. ICML 2020. [arXiv:1910.06378](https://arxiv.org/abs/1910.06378)
- Jothimurugesan, Hashemi, Xu et al. Federated Learning under Distributed Concept Drift (FedDrift). AISTATS 2023. [arXiv:2206.00799](https://arxiv.org/abs/2206.00799)
- Dynamic Participation in Federated Learning: Benchmarks and a Knowledge Pool Plugin (DPFL/KPFL). AAAI-26 FLCA workshop. [arXiv:2511.16523](https://arxiv.org/abs/2511.16523)
- Debiasing Federated Learning with Correlated Client Participation. [arXiv:2410.01209](https://arxiv.org/abs/2410.01209)
- Who Trains Matters: FL under Enrollment and Participation Selection Biases. [arXiv:2604.26604](https://arxiv.org/abs/2604.26604)
- Efficient FL against Heterogeneous and Non-stationary Client Unavailability (FedAPM). [arXiv:2409.17446](https://arxiv.org/abs/2409.17446)
- Li, Hu, Beirami, Smith. Ditto: Fair and Robust FL Through Personalization. ICML 2021. [arXiv:2012.04221](https://arxiv.org/abs/2012.04221)
- Kairouz et al. Advances and Open Problems in Federated Learning. [arXiv:1912.04977](https://arxiv.org/abs/1912.04977)
- Petroni et al. KILT. NAACL 2021. [arXiv:2009.02252](https://arxiv.org/abs/2009.02252)
- Es et al. RAGAS. [docs.ragas.io](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/faithfulness/)
- Yang et al. CRAG. KDD Cup 2024. [arXiv:2406.04744](https://arxiv.org/abs/2406.04744)
- Liu et al. Lost in the Middle. TACL 2024. [arXiv:2307.03172](https://arxiv.org/abs/2307.03172)
- Vu et al. FreshLLMs/FreshQA. ACL Findings 2024. [arXiv:2310.03214](https://arxiv.org/abs/2310.03214)
- Ouyang et al. HoH. ACL 2025. [arXiv:2503.04800](https://arxiv.org/abs/2503.04800)
- Wang, Prasad, Stengel-Eskin, Bansal. RAG with Conflicting Evidence (RAMDocs/MADAM-RAG). COLM 2025. [arXiv:2504.13079](https://arxiv.org/abs/2504.13079)
- Özer & Yıldız. QA under Temporal Conflict. [arXiv:2506.07270](https://arxiv.org/abs/2506.07270)
- An et al. FRESCO. [arXiv:2604.14227](https://arxiv.org/abs/2604.14227)
- Xu et al. Knowledge Conflicts for LLMs: A Survey. [arXiv:2403.08319](https://arxiv.org/abs/2403.08319)
- Reddy & Challaram. Don't Ask the LLM to Track Freshness. [arXiv:2606.01435](https://arxiv.org/abs/2606.01435)
- Perry, Srivastava, Kumar, Boneh. Do Users Write More Insecure Code with AI Assistants? CCS 2023. [arXiv:2211.03622](https://arxiv.org/abs/2211.03622)
- Ziegler et al. Measuring GitHub Copilot's Impact on Productivity. CACM 2024.
- Vasconcelos, Bansal, Fourney, Liao, Vaughan. Generation Probabilities Are Not Enough. TOCHI 2024. [arXiv:2302.07248](https://arxiv.org/abs/2302.07248)
- Wang, Cheng, Ford, Zimmermann. Investigating and Designing for Trust in AI-powered Code Generation Tools. FAccT 2024. [arXiv:2305.11248](https://arxiv.org/abs/2305.11248)
- Brown, D'Angelo, Murillo, Jaspan, Green. Identifying the Factors That Influence Trust in AI Code Completion. AIware 2024.
- Baltes, Speith, Chiteri et al. On the Need to Rethink Trust in AI Assistants for Software Development. [arXiv:2504.12461](https://arxiv.org/abs/2504.12461)
- Ferino, Hoda, Grundy, Treude. Towards an Appropriate Level of Reliance on AI. FSE Companion 2026. [arXiv:2604.10530](https://arxiv.org/abs/2604.10530)
- Gardella, Bolton, Riggs. Relationships Between Trust, Compliance, and Performance for Novice Programmers. [arXiv:2604.18948](https://arxiv.org/abs/2604.18948)
- Evolution of Programmers' Trust in Generative AI Programming Assistants. Koli Calling 2025. [arXiv:2509.13253](https://arxiv.org/abs/2509.13253)
- Meta RADAR: Automating Low-Risk Code Review at Meta. [arXiv:2605.30208](https://arxiv.org/abs/2605.30208)
- Sun, Wang, Zhu, Li, Zhao, Yuan. Constraint Weakening in LLM Agent Workflows. [arXiv:2608.24569](https://arxiv.org/abs/2608.24569)
- Gelvan, Slinko, Steinbauer, Bogomolov, Kofler, Zharov. On Problems of Implicit Context Compression for SWE Agents. [arXiv:2605.11051](https://arxiv.org/abs/2605.11051)
- Mehta et al. Plans Don't Persist. [arXiv:2606.22953](https://arxiv.org/abs/2606.22953)
- Kang, Chen, Han, Inan, Wutschitz, Chen, Sim, Rajmohan. ACON. ICML 2026. [arXiv:2510.00615](https://arxiv.org/abs/2510.00615)
- The Long-Horizon Task Mirage. [arXiv:2604.11978](https://arxiv.org/abs/2604.11978)
- Diagnosing and Mitigating Context Rot in Long-horizon Search. [arXiv:2606.29718](https://arxiv.org/abs/2606.29718)
- AdaCoM: Learning Agent-Compatible Context Management. [arXiv:2605.30785](https://arxiv.org/abs/2605.30785)
- Deng, Da, Pan et al. SWE-Bench Pro. Scale AI. [arXiv:2509.16941](https://arxiv.org/abs/2509.16941)
- Du, Li, Torralba, Tenenbaum, Mordatch. Improving Factuality and Reasoning through Multiagent Debate. ICML 2024. [arXiv:2305.14325](https://arxiv.org/abs/2305.14325)
- Zhang et al. Stop Overvaluing Multi-Agent Debate. [arXiv:2502.08788](https://arxiv.org/abs/2502.08788)
- Wynn, Satija, Hadfield. Talk Isn't Always Cheap. ICML MAS Workshop 2025. [arXiv:2509.05396](https://arxiv.org/abs/2509.05396)
- Wu, Li, Li. Can LLM Agents Really Debate? [arXiv:2511.07784](https://arxiv.org/abs/2511.07784)
- Lee, Tiwari. Prompt Infection. [arXiv:2410.07283](https://arxiv.org/abs/2410.07283)
- Kavathekar, Jain, Rathod, Kumaraguru, Ganu. TAMAS. [arXiv:2511.05269](https://arxiv.org/abs/2511.05269)
- Lee, Yun, Panagou, Karimireddy. Robust Multi-Agent LLMs under Byzantine Faults (SAC). EMNLP 2026. [arXiv:2605.09076](https://arxiv.org/abs/2605.09076)
- Jo, Park. DecentLLMs. [arXiv:2507.14928](https://arxiv.org/abs/2507.14928)
- Wiesmeier, Busch, Tacke, Linka, Cyron, Aydin. Adversarial robustness of LLM-based MAS for engineering problems. Frontiers in AI, 2026.
- Becker, Wahle, Ruas, Gipp. Misinformation Propagation in Benign Multi-Agent Systems. [arXiv:2606.16710](https://arxiv.org/abs/2606.16710)
- BAD-ACTS. [arXiv:2508.16481](https://arxiv.org/abs/2508.16481)
- El Mir, Takáč, Lahlou. Byzantine Cheap Talk. NETYS 2026. [arXiv:2606.07790](https://arxiv.org/abs/2606.07790)

---

*Prepared for research scoping purposes. All arXiv preprints listed are unreviewed unless a peer-reviewed venue is explicitly named (e.g., "ICML 2024", "CCS 2023") — treat preprint-only claims as provisional pending peer review, and re-run the novelty-killing search (Phase 11) immediately before any formal proposal submission, since several adjacent papers were posted within weeks of this report.*
