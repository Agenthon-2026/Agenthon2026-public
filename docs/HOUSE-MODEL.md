## Executive summary (read this first)

The approved House model is `nvidia/nemotron-3-super-120b-a12b`, with the reported model and
tokenizer snapshot `rl-030326-fp8`. For an authorized House API submission, use the five-field
`models[]` row below. Runtime calls use the injected `MODEL_NAME`; the reported route alias is
`house`, which is separate from the model identity in the descriptor. The training cutoff is
unpublished. This guide records operator-reported metadata and does not change track permissions,
scoring, request limits, or participant tuning cutoffs.

## Descriptor disclosure

Insert this object as one entry in the existing `models` array for a submission authorized to use
the approved House model:

```json
{
  "name": "nvidia/nemotron-3-super-120b-a12b",
  "version": "rl-030326-fp8",
  "revision": "rl-030326-fp8",
  "training_cutoff": "unpublished",
  "access": "api"
}
```

All five fields are required. The value `unpublished` records the absence of a published training
cutoff; it is not an estimated date. After changing the row, reseal `descriptor_digest` with the
toolkit's `seal_descriptor_digest` function and repack the submission. Keep `image` pointed at
your own participant image.

The existing base-pretraining exception applies only to this approved House revision. Applicable
cutoffs continue to apply to participant tuning, model selection, calibration, and
participant-provided data and artifacts.
This disclosure does not expand BYO permissions. A model-free Track 3 simulator keeps
`category: "simulator"` and `models: []`; this guide grants it no House API permission.

## Reported model and tokenizer metadata

The service operator reported the following metadata from a read-only live inspection. They have
not been independently reproduced for this guide.

| Field | Reported value |
|---|---|
| Model identity | `nvidia/nemotron-3-super-120b-a12b` |
| Runtime route alias | `house` |
| Model snapshot | `rl-030326-fp8` |
| Tokenizer snapshot | `rl-030326-fp8` |
| Model type / architecture | `nemotron_h` / `NemotronHForCausalLM` |
| Transformers version in artifact metadata | `4.57.6` |
| Vocabulary size | `131072` |
| Tokenizer class | `PreTrainedTokenizerFast` |
| Tokenizer maximum-length metadata | `262144` |
| Tokenizer `add_bos_token` | `false` |
| Training cutoff | Unpublished |

The snapshot label is the reported revision of both the model and tokenizer. It is not a
cryptographic hash of their files or an independent proof that those files cannot change. The
Transformers value describes artifact metadata, not an independently measured runtime package
version. Tokenizer maximum-length metadata is distinct from a serving context window and from
per-request or per-run token allowances; it does not establish an allowed request size.

## Serving container identity

The operator reported this complete serving-container reference:

```text
nvcr.io/nim/nvidia/nemotron-3-super-120b-a12b@sha256:0c0c4bc7749f1705cb626f2f7730001ee7b4f68231d6ceb3e68d7d1d8cc79bfb
```

This digest identifies the reported serving container separately from the snapshot label. It is
not a model-weight or tokenizer-file hash, and it does not replace the digest of your participant
image in `submission.json`.
