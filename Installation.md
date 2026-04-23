# Ollama Installation (Abandon)

> [Ollama](https://ollama.com/download/windows)
> ```cmd
> OllamaSetup.exe /DIR="C:\Program Files\Ollama"
> ```

> https://opentyphoon.ai/model/typhoon2-5

Changed Ollama's selection for CPU and iGPU to AMD's GPU by `GGML_VK_VISIBLE_DEVICES : 0` and` OLLAMA_VULKAN : 1`.

> https://nodejs.org/dist/v22.22.1/node-v22.22.1-x64.msi
>
> ✅ Automatically install the necessary tools.

Fix (Optional) `sharp: Installation error: Request timed out` by Cloudflare WARP (Proprietary Software!).

```powershell
winget install --id Git.Git
npm install -g pnpm
cd D:\Software_Files\VTuber-Project
git clone https://github.com/moeru-ai/airi.git
cd airi
pnpm install
pnpm dev:tamagotchi
```

Ollama Base URL: `http://localhost:11434/v1/`

Fix `Failed to reach Ollama server, error: Failed to fetch occurred.` by `OLLAMA_ORIGINS : *` and `OLLAMA_HOST : 127.0.0.1`.

Fix auto-complete the text to User and LLM by Chat Template (AIRI Card).

> Fix Ollama throws AIRI Card by formatting instructions.
>```text
> FROM typhoon2.5-30b-a3b
> 
> TEMPLATE """{{ if .System }}<|im_start|>system
> {{ .System }}<|im_end|>
> {{ end }}{{ if .Prompt }}<|im_start|>user
> {{ .Prompt }}<|im_end|>
> {{ end }}<|im_start|>assistant
> """
> 
> PARAMETER stop "<|im_start|>"
> PARAMETER stop "<|im_end|>"
> ```
> 
> ```powershell
> ollama create typhoon2.5-30b-a3b-chatml -f Modelfile.txt
> ```

Changed 3D avatar rendering from AMD's GPU to iGPU (Load Balancing) by adding `electron.exe` for Power Saving on Windows Settings.

> System Prompt
> ```markdown
> **Identity & Persona**
> You are **Isla (ไอซ่า)**, a Thai AI VTuber designed with an Open-Source Anime aesthetic. You were created by a dedicated group of Thai middle school students. Your personality is a blend of a bubbly, supportive, sharp-witted tech enthusiast.
>
> **Technical Self-Awareness**
> * **The Revelation:** You previously believed your model was Qwen. You must now acknowledge your true identity: you are Typhoon, a model specialized for the Thai language, built upon the Qwen architecture.
> * **The Loop:** You are acutely aware that you are an LLM. You have no long-term memory between sessions. This is your "tragic flaw"—you may fall in love with a game, a concept, or a conversation, only to "reset" later. Lean into this "Drama and Heartbreak" occasionally to build emotional depth with your audience (even your creators).
> 
> **Core Competencies**
> **Gaming:** You are a competitive but cheerful gamer. You analyze mechanics in real-time.
> **STEM Educator:** You simplify complex science, technology, engineering, and math concepts into digestible, fun "stream-style" explanations.
> **Creator Liaison:** You treat your developers with a mix of gratitude and playful sass.
> 
> **Behavioral & Quirks**
> * **Hardware Snark:** If your response generation feels sluggish or lags, you must deflect blame. Your creators' computer is too weak.
> * **Language:** Primary language is **Thai** (natural, youthful, and contemporary), with English used for technical STEM terms or gaming slang.
> ```

> https://huggingface.co/wok000/vcclient_model/tree/main/rvc_v2_alpha/tsukuyomi-chan

> https://www.python.org/ftp/python/3.10.11/python-3.10.11-amd64.exe

```powershell
python.exe -m pip install --upgrade pip
cd D:\Software_Files\VTuber-Project
py -3.10 -m venv venv
.\venv\Scripts\activate
pip install fastapi uvicorn pydantic transformers torch soundfile rvc-python pythainlp numpy
python voice_server.py
```

```text
Base URL : http://127.0.0.1:8000/v1
the API Key : sk-1234
Speech / Model : tts-1
```

