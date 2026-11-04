# Source-to-mathematics ledger: embodiment, goals and minimal agency (2026-11-04)

**Status:** curated interpretations plus MoralityLabAI mathematics, following Levinverse's evidence/attribution policy. Timecodes below are approximate segment starts from transcripts supplied by the researcher; the first two interview titles, dates, and public publisher sources were cross-checked. This file **does not reproduce the interview transcripts**.

## Primary sources and claim provenance

1. **Michael Levin, "Professor Mike Levin: Agential Materials"**, Cheltenham and UK Philosophers, **2026-06-11**, approximately 69 minutes. Original catalog reference: [Levin's official audio/video index](https://drmichaellevin.org/presentations/audiovideo.html); independently indexed episode transcript at [CEOInterviews](https://ceointerviews.ai/interview/3082716/). Researcher transcript supplied 2026-11-04.
2. **Michael Levin and D. C. Schindler, "Exploring Platonic Morphospace"**, hosted by Mahon McCann, **2026-07-02**, approximately 59 minutes. [Publisher episode with chapters](https://www.mahonmccann.com/p/exploring-platonic-morphospace-wmichael); [episode transcript](https://podscan.fm/podcasts/mahon-mccann/episodes/exploring-platonic-morphospace-wmichael-levin-amp-dc-schindler). Researcher transcript supplied 2026-11-04.
3. **Michael Levin**, [Ingressing Minds](https://doi.org/10.3390/philosophies11050161), *Philosophies* 11(5), 161 (2026). Levin's own theoretical proposal, **not** the experimental validation of all its ontological implications.
4. **Pigozzi, Goldstein, Levin**, [Associative conditioning in gene regulatory network models](https://doi.org/10.1038/s42003-025-08411-2), *Communications Biology* 8, 1027 (2025; corrected 2026). Source for a specific network-based conditioning and causal-emergence study.
5. **Zhang, Goldstein, Levin**, [Classical sorting algorithms as a model of morphogenesis](https://arxiv.org/abs/2401.05375). Source for damaged/local sorting-agent experiments.

## Carefully attributed claims

| Source / time | Speaker's content | Class | What it licenses |
|---|---|---|---|
| Agential Materials, ~05:45–07:45 | Levin proposes that a structured space of possibilities is an investigable alternative to treating surprising emergence as an unexplained fact | **interpretive / research program** | Generate rival predictions and mechanistic baselines |
| Agential Materials, ~31:45–34:25 | Levin discusses associative conditioning in small gene-regulatory networks | **empirical/theoretical claim attributed to speaker** | Reproduce the linked paper's *declared* models before extrapolating |
| Agential Materials, ~51:20–56:20 | Levin asks who "paid" for competencies in new Anthrobot/Xenobot morphologies | **interpretive challenge** | Preregister computational-budget accounting and out-of-sample competence predictions |
| Agential Materials, ~64:20–68:10 | Levin describes MOMbot as a closed-loop morphology experimenter and communication interface | **research-platform description** | Study controlled active experimentation; physical capabilities need separate verification |
| Morphospace, ~04:45–06:30 | Levin prefers minimal transparent computational models for quantifying the gap between design inputs and observed competencies | **methodological proposal** | Build finite-state baselines and exact counterexamples |
| Morphospace, ~21:30–31:10 | Levin argues for nonphysical causation and links mathematical invariance to structured latent patterns | **metaphysical conjecture** | Compare explicit causal semantics; no theorem of nonphysical causation follows |
| Morphospace, ~37:40–44:20 | Levin discusses death and development in terms of changing collective coordination and enlarged goals | **conceptual/empirical interpretation** | Freeze operational goal and intervention metrics |
| Morphospace, ~44:25–48:20 | Schindler links organizing form to the classical philosophical concept of soul | **philosophical interpretation (Schindler)** | Study metaphysical interpretation separately from measurements |
| Morphospace, ~49:35–52:50 | Levin suggests a gradual measurable precursor to a higher-level coordinated individual | **prospective empirical hypothesis** | Seek early predictive signatures under held-out interventions |
| Morphospace, ~54:40–56:55 | Levin warns that naming a phase transition does not explain why a particular structure appears | **methodological criticism** | Test explanatory specificity and pre-registered predictive power |

The interviewer/scholar's words in the Schindler conversation must not be attributed to Levin. In particular, Schindler's traditional term "soul" and his Neoplatonic interpretation are not experimental conclusions of Levin's lab.

## Original mathematical extension LEV-M1: when does a macro agent exist as a dynamical quotient?

Let S be a finite microscopic state space and A a finite action set. Each action a has a deterministic micro-transition F_a:S→S. Let q:S→Z be a **surjective** proposed macro-description.

**Proposition (fibre consistency criterion).** There exists a family of maps G_a:Z→Z such that

    q(F_a(s))=G_a(q(s))   for every s∈S,a∈A                         (1)

**if and only if**

    q(s)=q(t)  =>  q(F_a(s))=q(F_a(t))
    for all s,t∈S and every a∈A.                                 (2)

When it exists, the macro family G_a is unique.

*Proof.* If G_a exists, apply it to q(s)=q(t), yielding (2). Conversely, for z∈Z choose a preimage s with q(s)=z and set G_a(z):=q(F_a(s)). Condition (2) makes this independent of the chosen preimage. Surjectivity provides a preimage for every z. Uniqueness follows because each z has one. QED.

This provides a sharp, implementable operational test: two cells/states assigned the same "organism" macrostate must respond compatibly to all permitted interventions. A failure refutes that **particular** macro-dynamical quotient, while leaving other coarser or richer descriptions possible. A single visible goal or convergent endpoint cannot establish (2).

The result is elementary quotient dynamics, **newly applied here** to Levin's interpretation; there is no assertion that it is a previously unknown mathematical theorem.

## Mathematical dispatch to ongoing projects

| Repository / artifact | Independent result or implementation | Boundary |
|---|---|---|
| [Compactification-Theory IDQ-01 PR #35](https://github.com/MoralityLabAI/Compactification-Theory/pull/35) | Exact semiconjugacy and finite-horizon stochastic coupling bound; rational toy | Depends on chosen q and intervention family |
| [EvalMath MP-01 PR #23](https://github.com/MoralityLabAI/EvalMath/pull/23) | Finite research-budget Bellman recurrence; exact information-gain/decision-value ranking reversal | Scientific validity is separately subject to adaptive-selection controls |
| [HybridTRMLDT FWC-01 PR #6](https://github.com/MoralityLabAI/HybridTRMLDT/pull/6) | Fixed-weight synthetic conditioning and one-bit mutable-state necessity; typed gate invariant | Does not reproduce the 29 GRNs |
| [XenobotBench MOP-01 PR #3](https://github.com/patrickdugan/XenobotBench/pull/3) | Finite future-observation quotient and shortest distinguishing interventions | Digital-only observational identity |
| [OntologicalProofs MOR-01 PR #6](https://github.com/patrickdugan/OntologicalProofs/pull/6) | Lean draft of finite action-history and target transport | Lean compilation pending; no theological theorem |

## Discriminating experiments before metaphysics

- **Observer specification:** record which interventions and readouts define individuality/agency; report sensitivity to replacing the interface.
- **Predictions before outcomes:** fit q, G, predictor thresholds and baseline costs on discovery split, then test on unrevealed substrates and interventions.
- **Mechanistic controls:** include latent state, inherited architecture, pretraining, evolutionary priors, and search costs rather than treating an untrained *specific morphology* as a system that acquired competence from nothing.
- **Calibration:** a surprising outcome relative to a weak theory diagnoses that theory. Strong claims about additional causal ontology need observations that rule out competing causal models.

**Open question LEV-M1/Q:** Is there a family of intervention-consistent quotients across different physical/digital substrates whose shared dynamical constraints predict *new* recovery behaviors on preregistered holdouts? If yes, which extra empirical observation, if any, separates ordinary structural invariance from Levin's Platonic interpretation?
