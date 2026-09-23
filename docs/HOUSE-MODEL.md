## Executive summary (read this first)

The approved House model is `nvidia/nemotron-3-super-120b-a12b`, with the reported model and
tokenizer snapshot `rl-030326-fp8`. For an authorized House API submission, use the five-field
`models[]` row below. Runtime calls use the injected `MODEL_NAME`; the reported route alias is
`house`, which is separate from the model identity in the descriptor. Calls go to
`$MODEL_ENDPOINT/v1/chat/completions` with `Authorization: Bearer $MODEL_TOKEN` — see
[Calling the House route](#calling-the-house-route). The training cutoff is
unpublished. This guide records operator-reported metadata and does not change track permissions,
scoring, request limits, or participant tuning cutoffs.

## Calling the House route

Read this before you build an image that calls the House model. Every `network = "restricted"`
unit receives five environment variables. Use them exactly as injected:

| Variable | What it is | How to use it |
|---|---|---|
| `MODEL_ENDPOINT` | The **origin** of the House route (`scheme://host:port`, no path). | The OpenAI-compatible API is served **under `/v1`**. Chat completions are `POST $MODEL_ENDPOINT/v1/chat/completions`. A request to `$MODEL_ENDPOINT/chat/completions` (no `/v1`) is refused with HTTP 403. Use the injected scheme as given; do not rewrite it. |
| `MODEL_NAME` | The runtime alias of the approved House model. | The `model` field of every request. |
| `MODEL_TOKEN` | The per-unit bearer credential. | Send `Authorization: Bearer $MODEL_TOKEN` on every request. A request without it is refused with HTTP 401. |
| `http_proxy`, `https_proxy` (also `HTTP_PROXY`, `HTTPS_PROXY`) | The audited proxy, with the per-unit proxy login embedded. | Leave them untouched. Standard HTTP clients and SDKs read them automatically; the route is reachable only through this proxy. |

With the OpenAI Python client:

```python
import os
from openai import OpenAI

client = OpenAI(
    base_url=os.environ["MODEL_ENDPOINT"].rstrip("/") + "/v1",
    api_key=os.environ["MODEL_TOKEN"],
)
response = client.chat.completions.create(
    model=os.environ["MODEL_NAME"],
    messages=[{"role": "user", "content": "..."}],
    max_tokens=1024,
)
```

With raw HTTP (`urllib`, `requests`, `httpx`, `curl`): `POST` to `$MODEL_ENDPOINT/v1/chat/completions`
with `Content-Type: application/json` and `Authorization: Bearer $MODEL_TOKEN`; the proxy
variables carry the request. Only `POST /v1/chat/completions` is admitted; other paths and
methods are refused.

A request refused with 403 or 401 is refused before admission and does not consume any of the
unit's request allowance. Earlier versions of this guide and of the starter packs did
not state the `/v1` path or the `MODEL_TOKEN` variable; an agent built on `base_url=$MODEL_ENDPOINT`
alone was refused on every call. Both facts are now part of the published contract.

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
This disclosure grants no bring-your-own model or adapter permission — there is none in this competition. A model-free Track 3 simulator keeps
`category: "simulator"` and `models: []`; this guide grants it no House API permission.

## Development thinking controls

The selected House Development model uses **thinking by default**, with **low-effort reasoning
off by default**. These defaults were checked against the serving chat template and synthetic
request rendering on September 16, 2026. They do not announce participant access or establish
identical outputs from a different local serving stack.

To disable thinking for one request with the OpenAI Python client, pass:

```python
extra_body={"chat_template_kwargs": {"enable_thinking": False}}
```

For raw HTTP JSON, include `chat_template_kwargs` at the top level of the request body:

```json
{"chat_template_kwargs": {"enable_thinking": false}}
```

Use the supplied `MODEL_NAME` for the runtime alias. The selected model accepts this API option;
use it to control thinking instead of the older `detailed thinking on|off` system-prompt
instruction. Omitting the option keeps thinking enabled. This changes neither the approved
model/snapshot disclosure above nor the applicable per-unit request limit and per-request
output-token limit.

The corresponding public FP8 checkpoint is
[NVIDIA-Nemotron-3-Super-120B-A12B-FP8](https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-FP8).
Its model card documents the same thinking option. The checkpoint family and format do not
replace the selected snapshot identity or the unpublished training-cutoff disclosure above.

The House route also passes `low_effort` and `reasoning_budget` inside `chat_template_kwargs`, and
a top-level `reasoning_budget`, through to the model unchanged. We have not tested what setting
them does on the model we serve, so we make no promise about their effect.

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
version. Tokenizer maximum-length metadata is distinct from a serving context window and from the
per-request output-token limit; it does not establish an allowed request size.

## Serving container identity

The operator reported this complete serving-container reference:

```text
nvcr.io/nim/nvidia/nemotron-3-super-120b-a12b@sha256:0c0c4bc7749f1705cb626f2f7730001ee7b4f68231d6ceb3e68d7d1d8cc79bfb
```

This digest identifies the reported serving container separately from the snapshot label. It is
not a model-weight or tokenizer-file hash, and it does not replace the digest of your participant
image in `submission.json`.
