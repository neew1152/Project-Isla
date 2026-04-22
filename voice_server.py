import os
import re
import json
import time
import requests
import torch
import numpy as np
import soundfile as sf
import random
import asyncio
import uuid

# --- 1. PYTORCH SECURITY BYPASS ---
_original_load = torch.load
def _patched_load(*args, **kwargs):
    kwargs['weights_only'] = False
    return _original_load(*args, **kwargs)
torch.load = _patched_load

# --- 2. RVC TURBO PATCH (RAM LOCK) ---
import rvc_python.modules.vc.utils as rvc_utils
_orig_load_hubert = rvc_utils.load_hubert
_cached_hubert = None

def _fast_load_hubert(config, lib_dir):
    global _cached_hubert
    if _cached_hubert is None:
        print("🚀 Loading Hubert into RAM permanently...")
        _cached_hubert = _orig_load_hubert(config, lib_dir)
    return _cached_hubert
rvc_utils.load_hubert = _fast_load_hubert

from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from vachanatts import TTS  
from rvc_python.infer import RVCInference
from pythainlp.util import num_to_thaiword

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# --- 3. CONFIGURATION ---
SILENCE_AUDIO = "silence.wav"
RVC_MODEL_PATH = "./Models/RVC/tsukuyomi_v2_40k.pth" 
RVC_INDEX_PATH = "./Models/RVC/added_IVF7852_Flat_nprobe_1_v2.index.bin"
KOBOLD_URL = "http://127.0.0.1:5001/v1/chat/completions"

if not os.path.exists(SILENCE_AUDIO):
    sf.write(SILENCE_AUDIO, np.zeros(16000, dtype=np.float32), 16000)

# 🌟 NEW: CPU Traffic Controller (Prevents crashing if multiple chunks arrive)
tts_lock = asyncio.Lock()

# --- 4. LOAD VOICE MODELS ---
print("⏳ Loading Tsukuyomi-chan Filter...")
rvc = RVCInference(device="cpu") 
rvc.load_model(RVC_MODEL_PATH, index_path=RVC_INDEX_PATH)
rvc.set_params(f0method="pm", f0up_key=5, index_rate=0.75) 
print("✅ Voice Engine Ready & Locked into RAM!")

class SpeechRequest(BaseModel):
    input: str
    voice: str = "nova"
    model: str = "tts-1"

# =====================================================================
# THE LAUGHTER CONTROLLER
# =====================================================================
CONSECUTIVE_LAUGHS = 0
SUPPRESSION_LEFT = 0

def apply_laughter_control(text):
    global CONSECUTIVE_LAUGHS, SUPPRESSION_LEFT
    laugh_pattern = r'\s*(5{2,}|ฮ่า(ๆ)+)\s*'
    has_laugh = bool(re.search(laugh_pattern, text))
    
    if SUPPRESSION_LEFT > 0:
        text = re.sub(laugh_pattern, ' ', text).replace('  ', ' ').strip()
        SUPPRESSION_LEFT -= 1
        if SUPPRESSION_LEFT <= 0: CONSECUTIVE_LAUGHS = 0 
        return text
        
    if has_laugh:
        CONSECUTIVE_LAUGHS += 1
        if CONSECUTIVE_LAUGHS >= random.randint(2, 3):
            SUPPRESSION_LEFT = random.randint(1, 3)
            print(f"🛑 [LAUGHTER TIMEOUT] Suppressing for {SUPPRESSION_LEFT} turns.")
            text = re.sub(laugh_pattern, ' ', text).replace('  ', ' ').strip()
    else:
        CONSECUTIVE_LAUGHS = 0
    return text

# =====================================================================
# THE PIPELINE PROXY (YOUR GENIUS IDEA!)
# =====================================================================
@app.get("/v1/models")
async def dummy_models():
    return {"object": "list", "data":[{"id": "gemma", "object": "model", "owned_by": "kobold"}]}

from collections import deque
THOUGHT_QUEUE = deque()
LAST_THOUGHT_TIME = 0

@app.post("/v1/chat/completions")
async def proxy_llm(request: Request):
    global LAST_THOUGHT_TIME
    body = await request.json()
    body["stream"] = False 
    if "tools" in body: del body["tools"]
    
    # Nuke AIRI's hidden rules
    for msg in body.get("messages",[]):
        if msg.get("role") == "system":
            content = msg["content"]
            content = re.sub(r'- For any programming code block.*?\n', '', content, flags=re.IGNORECASE)
            content = re.sub(r'- For any math equation.*?\n', '', content, flags=re.IGNORECASE)
            msg["content"] = content

    print("🧠 Proxying to Koboldcpp... (Waiting for full text)")
    body["stop"] =["```", "User:", "ผู้ใช้:", "<|im_end|>"]
    
    response = requests.post(KOBOLD_URL, json=body)
    data = response.json()
    full_text = data["choices"][0]["message"]["content"]
    full_text = apply_laughter_control(full_text)
    
    print(f"\n💡 Koboldcpp Output: {full_text}")

    # 🌟 NEW: THE SMART SENTENCE SPLITTER
    raw_phrases = re.split(r'(?<=[!\?~\n])\s*', full_text)
    phrases =[]
    temp_phrase = ""
    
    for p in raw_phrases:
        p = p.strip()
        if not p: continue
        temp_phrase += p + " "
        # If the chunk is too short (under 30 characters), glue it to the next one!
        # This prevents awkward "dead air" between tiny sentences.
        if len(temp_phrase) >= 30 or p == raw_phrases[-1].strip():
            phrases.append(temp_phrase.strip())
            temp_phrase = ""

    THOUGHT_QUEUE.clear()
    for p in phrases:
        THOUGHT_QUEUE.append(p)
    LAST_THOUGHT_TIME = time.time()

    async def fake_stream():
        for phrase in phrases:
            print(f"📦 Streaming Chunk to AIRI: {phrase}")
            chunk = {"id": "chat", "object": "chat.completion.chunk", "model": "gemma", "choices":[{"index": 0, "delta": {"content": phrase}, "finish_reason": None}]}
            yield f"data: {json.dumps(chunk)}\n\n"
            await asyncio.sleep(0.1) 
            
        finish_chunk = {"id": "chat", "object": "chat.completion.chunk", "model": "gemma", "choices":[{"index": 0, "delta": {}, "finish_reason": "stop"}]}
        yield f"data: {json.dumps(finish_chunk)}\n\n"
        yield "data:[DONE]\n\n"
        
    return StreamingResponse(fake_stream(), media_type="text/event-stream")

# =====================================================================
# THE TEXT CLEANER & PIPELINED VOICE ENGINE
# =====================================================================
def clean_for_vachana(text):
    text = text.replace("<3", "")
    overrides = {
        "Minecraft": "มายคราฟ", "Roblox": "โรบล็อกซ์", "League of Legends": "ลีกออฟเลเจนด์",
        "Valorant": "วาโลแรนต์", "Genshin": "เก็นชิน","Impact": "อิมแพกต์", "Angel": "แองเจิล", "Beats": "บีทส์",
        "Facebook": "เฟซบุ๊ก", "YouTube": "ยูทูบ", "TikTok": "ติ๊กต็อก",
        "Discord": "ดิสคอร์ด", "Google": "กูเกิล", "Twitch": "ทวิตช์",
        "RAM": "แรม", "VTuber": "วีทูเบอร์", "Isla": "ไอซ่า",
        "Plastic": "พลาสติก", "Memories": "เมมโมรี่", "Memory": "เมมโมรี่", "Loop": "ลูป",
        "Gemma": "เจมม่า", "Gemini": "เจมิไน", "Typhoon": "ไทฟูน", "Qwen": "ควิ้น", "Chat": "แชต"
    }
    for eng, thai in overrides.items():
        reg = re.compile(r'\b' + re.escape(eng) + r'\b', re.IGNORECASE)
        text = reg.sub(thai, text)

    alphabet = {'A':'เอ','B':'บี','':'ซี','D':'ดี','E':'อี','F':'เอฟ','G':'จี','H':'เอช','I':'ไอ','J':'เจ','K':'เค','L':'แอล','M':'เอ็ม','N':'เอ็น','O':'โอ','P':'พี','Q':'คิว','R':'อาร์','S':'เอส','T':'ที','U':'ยู','V':'วี','W':'ดับเบิลยู','X':'เอกซ์','Y':'วาย','Z':'แซด'}
    def read_english_letters(match): return " " + alphabet.get(match.group(0).upper(), "") + " "
    text = re.sub(r'[a-zA-Z]', read_english_letters, text)

    text = re.sub(r'\(.*?\)', '', text) 
    text = re.sub(r'\[.*?\]', '', text) 
    text = re.sub(r'5{2,}', ' ฮ่าๆๆ ', text)
    text = text.replace("=", " เท่ากับ ").replace("+", " บวก ").replace("-", " ลบ ")
    text = re.sub(r'\d+', lambda x: num_to_thaiword(int(x.group())), text)
    text = re.sub(r'[^\u0E00-\u0E7F\s,]', '', text) 
    text = re.sub(r',+', ',', text) 
    text = re.sub(r'^\s*,\s*', '', text) 
    text = re.sub(r'\s+', ' ', text).strip()
    return text if text else ""

# Helper to delete audio files after sending them
def cleanup_files(f1, f2):
    try:
        if os.path.exists(f1): os.remove(f1)
        if os.path.exists(f2): os.remove(f2)
    except: pass

@app.post("/v1/audio/speech")
async def generate_speech(request: SpeechRequest, background_tasks: BackgroundTasks):
    global LAST_THOUGHT_TIME
    
    # 🌟 TELEPATHIC QUEUE OVERRIDE
    if THOUGHT_QUEUE:
        text_to_speak = THOUGHT_QUEUE.popleft()
        print(f"🌟 TELEPATHIC RESCUE: Ignored AIRI's garbage. Pulled from queue!")
    else:
        if time.time() - LAST_THOUGHT_TIME < 30:
            print(f"👻 Queue empty. Ignoring phantom chunk.")
            return FileResponse(SILENCE_AUDIO, media_type="audio/wav")
        else:
            text_to_speak = request.input

    safe_text = clean_for_vachana(text_to_speak)
    print(f"🗣️ Pipelining Audio: {safe_text}")
    
    if not safe_text.strip():
        return FileResponse(SILENCE_AUDIO, media_type="audio/wav")
    
    uid = str(uuid.uuid4())[:8]
    temp_raw = f"temp_raw_{uid}.wav"
    final_audio = f"isla_final_{uid}.wav"

    async with tts_lock:
        # 1. Generate Base Thai
        TTS(text=safe_text, voice="th_f_1", output=temp_raw, volume=1.0, speed=1.0)
        
        # 🌟 RESTORE THE CUTE VOWEL TAIL (Silence Padding) 🌟
        # Read the raw audio, add 0.2 seconds of silence, and save it back.
        # This prevents RVC from abruptly chopping off the end of her sentences!
        audio_data, sr = sf.read(temp_raw)
        silence = np.zeros(int(sr * 0.2), dtype=audio_data.dtype)
        padded_audio = np.concatenate((audio_data, silence))
        sf.write(temp_raw, padded_audio, sr)

        # 2. Apply Anime Filter to the padded audio
        rvc.infer_file(temp_raw, final_audio)
    
    background_tasks.add_task(cleanup_files, temp_raw, final_audio)
    return FileResponse(final_audio, media_type="audio/wav")

if __name__ == "__main__":
    import uvicorn
    print("\n🔊 Isla's Pipeline Fortress is LIVE on http://127.0.0.1:8000")
    uvicorn.run(app, host="127.0.0.1", port=8000)