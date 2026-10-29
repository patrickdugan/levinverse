# Levinverse scientific evaluations

The first text-audited case is in hpl_2026_10_28/. Original source transcript text is not duplicated in this public patch.

Run from the repository root:

    python evals/validate.py
    python evals/validate.py --source /path/to/original-transcript.txt
    python -m unittest discover -s evals/tests -v

The optional --source verifies SHA-256 of a locally held source copy. The validation script uses only Python's standard library.

Categories describe what Levin says in the interview; empirical_report does not certify replication. The source, derivatives and answer keys are excluded from adapter training. Because the evaluation answers are public, a separate unpublished blind set is needed for decisive comparisons.
