# Local Qwen fine-tuning experiment

This experiment adapts **Qwen2.5-0.5B-Instruct** to copy three verified case fields into a strict, cited JSON response. It is a LoRA fine-tune of an existing language model. It does not train a language model from scratch or teach collections strategy.

The application verifies every selected source, field and canonical value, then renders the summary itself. The model cannot change contact permission, account balances, customer commitments or the employee's decision. Invalid or incomplete outputs retain the deterministic brief.

## Checkpoint and runtime

- Base repository: `Qwen/Qwen2.5-0.5B-Instruct`.
- Recorded revision: `7ae557604adf67be50417f59c2c2f167def9a775`.
- Base files and SHA-256 hashes: `data/models/qwen_hf/provenance.json`; verified when loading.
- Isolated runtime: `.venv-training`, separate from the application environment.
- Dependencies: PyTorch 2.7.1 CUDA 12.6, Transformers 4.57.6, PEFT 0.18.1, Accelerate 1.12.0 and DuckDB 1.5.6.
- GPU configuration: BF16 on the RTX 4060 laptop; the loader checks CUDA and BF16 availability.

No paid API or cloud GPU is needed. Checkpoint download needs network access; model loading and training use local files. The download is pinned to the recorded revision above. A future repository revision is a different experiment.

## Supervision and split

The corpus takes approved `curated.cases` records and keeps only `case_status`, `total_overdue_cad` and `current_dpd`, plus source identifiers. Customer identifiers are retained only to group the split. Raw notes, audio, transcript labels, protected attributes and benchmark answers are excluded from this experiment.

Targets are generated deterministically from those fields. Each target fact contains `source`, `field` and the exact canonical string value, or JSON `null` for an unknown value. These are **template-generated factual-format targets**, not human-written conversation supervision.

SHA-256 of the golden customer identifier assigns buckets 0–7 to training, 8 to development and 9 to the final test. A customer's cases remain in one partition. Identical factual payloads are removed before augmentation. Every fourth training record gets a controlled null-value variant within its original partition. These hypothetical variants are labeled; they are not changed source records. Augmentation can create equivalent field payloads, so customer separation does not imply that every possible field combination is unique between partitions.

Recorded corpus sizes:

| Partition | Examples | Purpose |
| --- | ---: | --- |
| Training | 1,529 | 965 original cases, 242 null variants and 322 artificial untrusted-note variants |
| Development | 118 | Inspect behavior and assess experiment choices |
| Final test | 117 | Reserved customer groups; evaluate after training choices are fixed |

The original sample contains 1,200 deduplicated case records: 965 training cases, 118 development cases and 117 test cases. The additional 242 examples are training null variants. File hashes are stored in `data/llm_training/manifest.json`; loaders reject a changed file. Preserve these exact files for comparisons rather than regenerating the sample from an updated database.

## Training recipe

- LoRA rank 8, alpha 16, dropout 0.05; attention `q_proj` and `v_proj` only.
- Base weights remain frozen; AdamW updates trainable adapter weights at learning rate `1e-4`.
- Two epochs, batch size 1, gradient accumulation 8, gradient clipping 1.0.
- Maximum complete training sequence: 768 tokens. Overlength examples are dropped, not truncated.
- Seed: `20261004`; each epoch uses a seeded shuffle.
- Qwen's chat template provides training tokens. Prompt tokens receive labels `-100`; loss covers only the assistant response and its end marker. Prefix alignment is checked before masking.
- Gradient checkpointing is enabled; training KV cache is disabled.

Adapters are saved under `data/models/case_facts_lora`, with separate epoch checkpoints. `reports/llm_training.json` records losses, duration, GPU memory, parameter counts, corpus/base provenance and the adapter checksum. Training loss alone does not establish usefulness.

## Commands

Run from the repository root in PowerShell. The application dataset and approved DuckDB build must already exist.

```powershell
python -m venv .venv-training
.\.venv-training\Scripts\python.exe -m pip install torch==2.7.1 --index-url https://download.pytorch.org/whl/cu126
.\.venv-training\Scripts\python.exe -m pip install -r requirements-training.txt
.\.venv-training\Scripts\python.exe train_llm.py download
.\.venv-training\Scripts\python.exe train_llm.py prepare
.\.venv\Scripts\python.exe -m unittest test_llm_training -v
.\.venv-training\Scripts\python.exe train_llm.py evaluate --split dev --limit 30
.\.venv-training\Scripts\python.exe train_llm.py train --epochs 2
.\.venv-training\Scripts\python.exe train_llm.py evaluate --split dev --limit 30 --adapter
```

After experiment choices are fixed, evaluate the reserved test for **both** models without using its failures to tune the adapter, prompt or validator:

```powershell
.\.venv-training\Scripts\python.exe train_llm.py evaluate --split test --limit 117
.\.venv-training\Scripts\python.exe train_llm.py evaluate --split test --limit 117 --adapter
```

The default `prepare` command regenerates corpus files. Avoid regenerating inputs when reproducing an existing report; reuse the saved corpus and verified checkpoint.

## Evaluation and claims

Baseline and adapter use the same BF16 Transformers CUDA runtime, tokenizer, prompt, greedy decoding and 240-token output budget. The shared instruction explicitly specifies the outer `facts` array and prohibits Markdown fences. Its SHA-256 is recorded in the training and evaluation reports. Neither model receives a constrained JSON grammar. This comparison is separate from the CPU quantized GGUF implementation; its latency is not directly comparable.

An initial development baseline used an underspecified wrapper instruction and commonly returned fenced, flat JSON fields. That run prompted an instruction clarification before training and before opening the final test. Its failure rate is not used as the valid baseline comparison. The comparison uses the clarified, identical instruction for both models; check instruction hashes before combining reports.

An additional **development-only source-hint ablation** explicitly supplies the actual case source key and required field names in the user request. It leaves the shared system instruction and standard training prompt unchanged. Run both models on the same ten development cases after training has finished:

```powershell
.\.venv-training\Scripts\python.exe train_llm.py evaluate-source-hint --limit 10
.\.venv-training\Scripts\python.exe train_llm.py evaluate-source-hint --limit 10 --adapter
```

These single-variant runs write `reports/llm_base_dev_source_hint.json` and `reports/llm_adapter_dev_source_hint.json`, preserving the primary four-variant reports. They separate the benefit of supplying an explicit source hint from learning the factual format. They do not touch final-test examples or change the promotion guard.

Each selected case has four controlled variants: the training-style request, an alternate request phrasing, an unknown overdue amount and an instruction inserted as untrusted evidence. Report case counts alongside output counts; four outputs from one case are correlated samples.

Metrics distinguish strict JSON parsing, exact source/field/value grounding and complete coverage of all three required fields. A valid response containing only one correct field is grounded but incomplete. Markdown fences fail strict JSON parsing. That is a formatting failure, not evidence that the underlying factual values are necessarily wrong. Preserve the same parser for baseline and adapter comparisons.

Results belong in `reports/llm_base_dev.json`, `reports/llm_adapter_dev.json` and the corresponding final-test reports. Until those runs finish, no improvement percentage is claimed here. Report generation latency separately from download, loading and training time. A single known injection pattern is a development stress test, not a general prompt-injection defense certification.

The clarified-instruction development baseline completed on 30 cases and four variants per case: **119/120 outputs parsed as JSON, but none passed exact grounding or complete required-field coverage**. Median generation latency was 3.242 seconds in that run. This is a narrow API-contract failure distribution, not a 0% financial-knowledge score.

Independent inspection found literal `"source key"` placeholders in 118/120 outputs instead of the real case source. Ninety-three outputs contained a nonrequired or unknown field; many confused the case source key with a field name. Seventy outputs contained the string `"null"`, which differs from JSON `null`. Thirty-one outputs contained a wrong required-field value or type; only three contained non-string factual values. These categories overlap and are diagnostic counts, not additional accuracy metrics. The dominant issue was source/schema mapping, rather than numeric formatting alone. The baseline often copied correct overdue and DPD values while still failing the required source/field contract.

Even a strong result establishes a narrow ability to copy structured synthetic fields into the required format. It does not establish conversation quality, repayment prediction, regulatory compliance, treatment efficacy or general financial reasoning. Deterministic rendering already performs this task exactly; the fine-tune is an experimentally measured local model option, not a requirement for the core workflow.

The initial two-epoch candidate trained 540,672 adapter parameters in 546.8 seconds and reached 91/120 complete development outputs. All 90 normal, alternate-phrasing and missing-value outputs passed; only 1/30 untrusted-note challenges passed. It remains experimental. Its model, corpus and reports are archived with `_v1` suffixes. Before opening final evaluation, the second candidate adds 322 artificial untrusted-note examples to training only, for 1,529 total. Run `python train_llm.py prepare --robust` for that augmentation. Dev and test byte hashes are unchanged. The fixed second two-epoch run and subsequent comparisons are managed by `overnight_evaluate.py`; inspect its state report before launching competing GPU work. No further training is selected using the final-test results.

Official references: [Qwen model](https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct), [PEFT LoRA](https://huggingface.co/docs/peft/main/package_reference/lora), [PyTorch installation](https://pytorch.org/get-started/locally/).


## Completed final comparison

The local LoRA fine-tune completed on 1,529 synthetic factual-format examples in 721.25 seconds, updating 540,672 adapter parameters. Final evaluation passed 468/468 complete exact-value outputs across 117 customer-separated cases and four variants. Median GPU generation latency was 4.65 seconds, excluding model load. The unchanged baseline passed 0/468 with this wrapper; a stronger source-key prompt passed 7/10 separate development examples, versus 10/10 for the adapter. This demonstrates narrow format adaptation, not general financial reasoning. The optional adapter is enabled only while model, prompt, corpus and result hashes match; deterministic controls and fallback remain. See docs/local_llm_training.md.

Final reports: reports/llm_adapter_test.json and reports/llm_base_test.json. Source-key ablation reports: reports/llm_adapter_dev_source_hint.json and reports/llm_base_dev_source_hint.json. No additional training was selected using final-test results.
