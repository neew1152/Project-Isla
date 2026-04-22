# 🌸 Project Isla: Open-Source Thai AI VTuber Framework

**Version:** 1.0.0 (Hello World)  
**License:** MIT  

**Project Isla** is a lightweight, ultra-low-latency, multi-threaded backend architecture designed to bring a fully autonomous, self-aware Thai AI VTuber to life. 

Originally conceptualized and developed by a group of Thai middle schoolers, this project bridges the gap between state-of-the-art Large Language Models, voice conversion, and interactive 3D avatars. It is engineered from the ground up to run entirely locally on consumer hardware.

---

## ✨ Core Capabilities

*   **Asynchronous Audio Pipelining:** Isla does not suffer from "dead air." Text generation and voice synthesis run in overlapping, asynchronous background threads. She processes her next thought while her current sentence is still speaking, dropping latency to ~2-5 seconds.
*   **Quality of Service (QoS) Chat Bridge:** A multi-threaded YouTube Live listener that sorts incoming chat into priority queues. Creator/Admin messages bypass the public queue and are fed to the AI immediately.
*   **Artificial Self-Control (Mode Collapse Prevention):** A custom Python state machine actively monitors her output for repetitive laughter (e.g., `555`, `ฮ่าๆๆ`). If she laughs too many times consecutively, the system triggers a randomized "Timeout," silently suppressing laughter for several turns to ensure natural conversational pacing.
*   **Advanced Thai Transliteration & Sanitization:** A ruthless regex-based "Guillotine" that intercepts LLM hallucinations. It strips out internal English monologues, converts A-Z acronyms into phonetic Thai syllables (e.g., "FPS" -> "เอฟ พี เอส"), expands decimals/math properly, and shields the TTS engine from crashing on emojis or markdown.
*   **Prompt-Injection Immunity:** User chats are securely sandboxed, and delimiters are sanitized before hitting the LLM. Isla is programmed to actively roast anyone who attempts to override her system prompt.
*   **Custom Local OBS Overlays:** FastAPI serves lightweight, CSS-styled HTML endpoints (`/overlay` and `/scrolling_chat`) directly to OBS, visually displaying her current thought process and the live chat queue.

---

## ⚙️ System Architecture & Tech Stack

This repository contains the "Nervous System" that orchestrates the following heavy-lifting engines:

### 1. The Brain (Logic & Reasoning)
*   **Model:** Google `Gemma-4` (26B-A4B-it).
*   **Engine:** `Koboldcpp` (Optimized via Vulkan).
*   **Memory:** Context-locked to prevent KV-Cache RAM explosions, utilizing ContextShift for near-instant prompt processing (`CtxLimit:463/16384, Amt:40/512, Init:0.15s, Process:0.20s (2158.16T/s), Generate:2.24s (17.84T/s), Total:2.44s`).

### 2. The Voice (Speech Synthesis)
*   **Base Rhythm:** `VachanaTTS` (ONNX/Piper-based). Generates native, highly accurate Thai pronunciation and spacing.
*   **Vocal Cords:** `RVC v2` (Retrieval-based Voice Conversion) running the open-source *Tsukuyomi-chan* voice model. 
*   **Optimization:** RVC Indexing is disabled, and PyTorch threads are dynamically managed to achieve 1:1 real-time factor processing entirely on the CPU.

### 3. The Body (Visuals & Lip-Sync)
*   **Frontend:** `Project AIRI` (Stage Tamagotchi).
*   **Integration:** FastAPI mimics OpenAI-compatible endpoints (`/v1/chat/completions` and `/v1/audio/speech`). AIRI handles VRM 3D rendering and utilizes the Web Audio API to calculate FFT lip-syncing natively from the intercepted audio stream.