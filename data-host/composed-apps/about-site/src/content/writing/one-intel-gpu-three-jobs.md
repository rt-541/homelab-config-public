---
title: "One Intel GPU, three jobs"
date: 2026-09-26
dek: "An Intel Arc Pro B70 in a RHEL VM serves a local language model, transcodes for Plex and, when both are quiet, lends itself to an image model, with a small arbiter deciding who holds the card."
tags: ["homelab", "gpu", "llm", "intel", "vllm", "plex"]
---

The card is an Intel Arc Pro B70: Battlemage, 32 GB, passed through to a RHEL VM called devastator. It was bought for one job, serving a local language model to the agents on the NanoClaw fleet. It ended up with three: the language model, Plex hardware transcodes (plus a batch campaign that re-encodes 4K remuxes over VAAPI to win back disk), and, since today, turning 3D renders into photographs.

## Getting the card to show up

The driver that knows this card is `xe`, and the device ID has to be in it. RHEL 10.0's kernel did not have it. The in-place upgrade from 9.6 had pinned the subscription release to 10.0, so `dnf update` never moved the kernel forward. Setting the release to 10.2 and updating brought in a Red Hat signed kernel with the ID backported, and after a reboot the card appeared:

```
Kernel driver in use: xe
```

along with a render node and the GuC and HuC firmware loaded from `linux-firmware`. The Plex container, which already mounted `/dev/dri`, saw the new render node without changes.

## Serving a model with vLLM

vLLM runs from Intel's llm-scaler image (`intel/llm-scaler-vllm:0.14.0-b8.3.1`), which talks to the card through its own oneAPI and Level Zero stack, separate from the media driver Plex uses. The served model moved up in steps: Qwen2.5-7B, then Qwen3-14B as AWQ, then a trial of Qwen3-30B-A3B.

The 30B is a mixture of experts with about 3.3B parameters active per token, so it decodes like a small model. Intel's recipes only show it split across two or more cards, because they run it at FP16 (about 61 GB) or quantize it on the fly, which first loads the full model into host RAM. A checkpoint that is already quantized to INT4 is about 17 GB and fits one B70. It has to be GPTQ: in this image, only GPTQ checkpoints get a quantized method for the MoE layers.

Two settings mattered for the agents. The first was context. The agent harness alone sends about 16k tokens of prompt and tool schemas, so the window went to 32k, then to 64k with static YaRN on the 7B (a factor of 2 over its 32k base, the method Qwen documents). The second was tool calls. Without a parser the model returned its tool invocations as plain text; with the Hermes parser enabled they come back as real calls:

```
- --enable-auto-tool-choice
- --tool-call-parser
- hermes
```

## Leaving room for Plex

vLLM claims a fixed share of the card at start. That share went from 0.75 to 0.80 to 0.92 and settled at 0.85, which leaves about 4.8 GB for Plex: two 4K HDR transcodes at about 2 GB each plus driver headroom. A third stream falls back to the CPU. The model barely noticed; the KV cache still had room for many concurrent requests.

## Lending the card out

Image generation needs most of the card, and vLLM cannot resize its memory while it runs. It reserves at start and does not shrink. So the design swaps owners instead of splitting the pool.

**A recorder.** Once a minute, a root timer reads every process's DRM fdinfo, where the `xe` driver reports per-client VRAM and engine busy time. Clients are named by their container, or by command name, so every Plex Transcoder process counts as `plex`. It writes a current snapshot and a monthly history file. The history also answers an open question: Plex has hardware acceleration on this card and plenty of plays, but there was no record of how often it actually transcodes.

**An arbiter.** A small service keeps a queue of photo requests and a mode: `llm`, `swapping` or `image`. It swaps to `image` only when the queue is not empty, vLLM has had no running, waiting or finished request for 60 seconds, and the recorder shows no other client on the card. Then it stops vLLM, starts ComfyUI with FLUX.1 Kontext, works the queue, and hands the card back as soon as the queue is empty or 15 minutes have passed. It declares `llm` only after vLLM answers its health check.

**A patient proxy.** The NanoClaw agents reach vLLM through a small proxy. It reads the arbiter's mode and holds requests while the mode is anything other than `llm`, and it retries refused connections. An agent that speaks during a swap waits instead of failing.

Measured on the first day: the swap to `image` plus the first photo took 85 seconds, each photo after that 52 to 62 seconds at 1328x800 and 24 steps, and vLLM was healthy again 56 seconds after handback.

## What did not work

- **A mainline kernel.** ELRepo's kernel-ml knows the card, but it is unsigned, and the VM boots with Secure Boot on. The firmware rejected it before userspace. Signing it with a self-enrolled machine owner key still did not boot. It was removed; this VM runs Red Hat signed kernels only.
- **Qwen3-32B.** It restarted 252 times with what looked like a VRAM problem. The kernel log said otherwise: a memory cgroup kill at 8.3 GB of RSS, which was the compose file's `memory: 8G` limit. The cap went to 16G for the next attempt.
- **Resizing in place.** There is no way to ask a running vLLM for memory back, which is the whole reason the arbiter exists.

## What carries forward

The plan is a second B70. The two cards would form a tensor-parallel pool (TP=2, 64 GB) in a second machine, because the current host is a Mini-ITX board with one PCIe slot. Plex and the transcode campaign would then move to Arc A380 cards. Until then, the pattern holds for any shared accelerator: measure who is on it before deciding anything, and when a workload cannot shrink, trade the whole card rather than carve it.
