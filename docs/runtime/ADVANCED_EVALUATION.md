# Advanced Evaluation

## Existing scorecard compatibility

The deterministic run scorecard remains the default runtime scorecard contract so existing persisted tasks and frontend contracts stay compatible.

The evaluation layer adds the following scorecard dimensions:

- correctness
- groundedness
- citation quality
- task completion

The existing tool reliability, RAG quality, memory contribution, budget compliance, latency, token, and model-cost signals remain available.

## Judge abstraction

`app.eval.judge` defines a structured Judge contract.

### DeterministicMockJudge

Used for automatic regression. It is network-free and deterministic. It returns:

- overall score
- dimension scores
- reason
- pass/fail
- evaluator metadata

### ModelJudge

Uses the current Model Gateway for optional semantic evaluation. The model must return structured JSON. A ModelJudge failure is evaluation failure only; it is not a reason to invalidate an already successful Agent run.

## Dataset and regression comparison

`app.eval.dataset` provides:

- `EvaluationCase`
- dataset loader for JSONL
- evaluation runner
- per-case result
- run summary
- baseline/candidate comparison
- regression/improvement detection

The repository contains the synthetic dataset:

```text
runtime-python/evals/v2_intelligence_cases.jsonl
```

It covers text RAG, image knowledge, PDF text/visual behavior, visual and hybrid queries, citations, Memory/Tool interaction, routing, and failure fallback. It contains no user data.

## Evaluation CLI

The synthetic evaluation dataset can be executed without starting the whole Runtime:

```powershell
cd runtime-python
python scripts/run_v2_eval.py --judge deterministic
```

The deterministic path is the mandatory offline regression gate. A configured real provider can be used explicitly with:

```powershell
python scripts/run_v2_eval.py --judge model
```

The model path is environment-dependent and may incur provider cost. It is never required to make an already successful Agent run succeed.
