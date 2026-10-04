# Model choices and rubric adaptation

The working default requires no paid API key. Deterministic policies and employee review control actions. Local model outputs provide review evidence or summary wording.

| Component | Current implementation | What the team trained | Evaluation and limits |
| --- | --- | --- | --- |
| Financial hardship | Word/bigram naive Bayes plus existing rules | The classifier, on 678 approved examples | 181 grouped development examples; pure hardship classifier 98.61% precision/recall, live combination 94.74% precision and 100% recall. See reports/classifier_evaluation.json for support counts. This is development evaluation, not a blind or hidden benchmark. |
| Other text signals | Shared rules, with rare model outputs shown as evidence | Rare classifiers were fitted but did not outperform rules | Low support and weak precision prevent using those predictions as verified status. |
| Speech transcription | Local faster-whisper CPU int8 | No speech training or fine-tuning | Pretrained tiny.en, base.en and small.en evaluated on synthetic English TTS. Speaker attribution remains employee-reviewed. |
| Language drafting | Local Qwen2.5-0.5B-Instruct Q4_K_M baseline; separate LoRA experiment | The baseline is pretrained; the team fine-tuned 540,672 LoRA parameters on 1,529 factual-format examples. | Current drafting selects typed evidence fields with exact source/value checks and deterministic rendering. Factual extraction checks do not establish usefulness, general writing quality or policy understanding. See reports/local_llm_evaluation.json for the current prompt and scope. |
| Optional paid drafting | OpenAI adapter, explicitly configured by the user | Nothing | Not called or verified against a paid account. No application API charge has been incurred. |

On the earlier paired 20-recording sample, base.en measured 17.07% WER and small.en 12.31%. Summed inference times were 105.8 and 150.1 seconds respectively; the first small.en run included model download/load. After stricter provenance approval, the refreshed small.en check measured 11.22% WER on 100 approved recordings in 966.4 seconds total, including 960.5 seconds summed inference. These are synthetic development samples ordered by voice ID, not representative real calls or a paired 100-call comparison with base.en. small.en is the CLI default. All 1,803 approved recordings have been transcribed and evaluated: 11.02% aggregate WER in 13,699.9 seconds (3.81 hours), using pretrained small.en. These remain synthetic English recordings without automatic speaker attribution.

## Source approval and development splits

Notes exclude resolved account/customer ownership contradictions. Transcripts come from curated.transcripts, which checks case/customer identity and rejects resolved contradictory or quarantined contact metadata. A missing contact link is explicitly unknown rather than treated as a validated join.

The classifier groups rows connected by the same golden customer, identical normalized/redacted text or identical complete token inputs. This catches templates that differ only in numeric values the classifier ignores. The earlier split left 18 of 170 evaluation rows with token inputs also found in training. Its earlier 98.63% hardship precision/recall should not be used as the current validated score.

The refreshed run contains 859 approved examples across 756 connected groups. It excludes 141 public label rows, including 25 mentioning protected content and 116 missing or unapproved source rows. The hardship evaluation has 72 positive examples and 109 negatives. The live combination detects all 72 positives with 4 false positives.

This split prevents those direct overlaps. It does not establish independence of synthetic writing templates, remove correlations across similar phrases, or make a public development result a hidden-test score. Short customer utterances remain a different input distribution from full notes and calls. Rare-class support counts must accompany any precision/recall claim.

The LoRA experiment should split factual customer evidence before generating targets, remove duplicate factual payloads after dropping case identifiers, and reserve separate unseen prompt formats and missing-value or injection examples. Training on generated field-extraction targets teaches a narrow format and mapping. It is not independent evidence of conversational skill or policy reasoning.

## When the rubric arrives

Keep the free local path for an offline or no-paid-API requirement. Do not claim the pretrained Whisper or Qwen models were trained by the team. The locally trained classifier is a separate, reproducible artifact with a model contract, checksum and grouped evaluation.

If independent classifier or speech benchmarks are provided, evaluate without using their labels for training or rule tuning. Save their scope separately from development reports. Compare rare-class precision, recall and support rather than averaging away misses. Change the contact workflow only if the required policy evidence remains available.

If paid generation is permitted and useful, the user can authorize costs and configure ignored .env credentials. Compare identical approved evidence and human-reviewed factual correctness against the local path. Structural validation alone does not determine quality. Paid generation must preserve the deterministic gate and employee control.

If the rubric rewards one deep use case, prioritize Agent Assist and retain the other five as demonstrations. If it rewards breadth, improve each prototype against its explicit benchmark rather than presenting descriptive channel cost or keyword QA as optimized production decisions.

The requested language-model experiment adapts a pretrained model with LoRA; it is not language-model training from scratch. Keep the unchanged baseline and deterministic extraction available for comparison. Deploy an adapted model only after an independent factual and safeguard evaluation shows a useful improvement. It must not replace financial controls or manufacture a benchmark score.


The local LoRA fine-tune completed on 1,529 synthetic factual-format examples in 721.25 seconds, updating 540,672 adapter parameters. Final evaluation passed 468/468 complete exact-value outputs across 117 customer-separated cases and four variants. Median GPU generation latency was 4.65 seconds, excluding model load. The unchanged baseline passed 0/468 with this wrapper; a stronger source-key prompt passed 7/10 separate development examples, versus 10/10 for the adapter. This demonstrates narrow format adaptation, not general financial reasoning. The optional adapter is enabled only while model, prompt, corpus and result hashes match; deterministic controls and fallback remain. See docs/local_llm_training.md.
