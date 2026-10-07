# Inkling as Collaborator

Code and data behind the case study **Inkling as Collaborator** on [cristian-hernandez.live](https://cristian-hernandez.live) (AI systems › Model design).

I measured how collaborative Thinking Machines Lab's Inkling model is across 500 synthetic situations, with and without a system prompt that describes a good collaborator. Each answer was graded against a trait rubric, then every pair of answers was compared head to head. Head to head, the answer without the system prompt won 195 pairs, the system-prompt answer won 82, and 223 were ties.

The tooling, the synthetic prompts and the grading were produced by Claude (Anthropic) in Claude Code at my direction.

## What's here

| Path | What it is |
|---|---|
| `run_eval.py`, `eval_ui.html` | Local runner with a small web page. Sends each prompt alone, in a fresh conversation, to any OpenAI-compatible or Anthropic API. Standard library only. |
| `collaborator_eval_prompts.json` | The 500 prompts (C001 to C500), each with a category, a primary trait, secondary traits and a probe that describes the ideal answer. |
| `ink_collab_behavior_eval_outputs_NO_SYSTEM.json` | Inkling's answers with no system prompt, plus run settings and timestamps. |
| `ink_collab_behavior_eval_outputs_WITH_SYSTEM.json` | Inkling's answers with the collaborator system prompt (stored in `run_metadata.settings.system_prompt`). |
| `grading/RUBRIC.md` | The 1 to 5 scoring rubric and grading conventions. |
| `grading/grades.jsonl` | First-pass grades, blind A/B per prompt. The A/B key is `grading/.blind_map.json`. |
| `grading/pairs.jsonl` | Pairwise verdicts (A much better to B much better), with deciding traits and a one-sentence reason. The A/B key is `grading/.pair_map.json`. |
| `grading/pair_results.json` | Pairwise summary: overall, by category, by trait, position and length checks. |
| `grading/*.py` | Scripts used to show batches, save grades and analyze the pairwise pass. |
| `artifacts/` | Standalone copies of the case study and the two interactive run reports. |

## Run the eval

```sh
export TINKER_API_KEY=your-key   # or paste the key into the page
python3 run_eval.py
```

The page opens at http://127.0.0.1:8765. Choose `collaborator_eval_prompts.json` as the prompts file, type a new output file name, enter the model settings, and paste a system prompt (leave it empty for a baseline run). Answers are saved after every prompt, so a stopped run resumes where it left off. The API key is kept in memory only and is never written to the output file.

## Reproduce the pairwise summary

```sh
cd grading
python3 analyze_pairs.py
```

This unblinds `pairs.jsonl` with `.pair_map.json`, prints the summary, and rewrites `pair_results.json`.
