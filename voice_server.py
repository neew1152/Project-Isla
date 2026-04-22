import os
import re
import glob
import json
import asyncio
import uuid
import numpy as np
import soundfile as sf
import random
import httpx
import torch
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse, HTMLResponse
from pydantic import BaseModel
from vachanatts import TTS
from rvc_python.infer import RVCInference
from pythainlp.util import num_to_thaiword

# =====================================================================
# PYTORCH & HUBERT RAM LOCK
# =====================================================================
_original_load = torch.load
def _patched_load(*args, **kwargs):
    kwargs['weights_only'] = False
    return _original_load(*args, **kwargs)
torch.load = _patched_load

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

# =====================================================================
# CONFIG & REGEX
# =====================================================================
SILENCE_AUDIO = "silence.wav"
RVC_MODEL_PATH  = "./Models/RVC/tsukuyomi_v2_40k.pth"
RVC_INDEX_PATH  = "./Models/RVC/added_IVF7852_Flat_nprobe_1_v2.index.bin"
KOBOLD_URL      = "http://127.0.0.1:5001/v1/chat/completions"
CPU_WORKERS     = max(1, os.cpu_count() - 2)

if not os.path.exists(SILENCE_AUDIO):
    sf.write(SILENCE_AUDIO, np.zeros(16000, dtype=np.float32), 16000)

_LAUGH_PATTERN = re.compile(r'\s*(5{2,}|ฮ่า(ๆ)+)\s*')
_DIGITS_PATTERN = re.compile(r'\d+')
_PARENS_PATTERN = re.compile(r'\(.*?\)')
_SQUARE_PATTERN = re.compile(r'\[.*?\]')
_MULTI55_PATTERN = re.compile(r'5{2,}')
_NON_THAI_PATTERN = re.compile(r'[^\u0E00-\u0E7F\s,!\?\.]')
_MULTI_SPACE_PATTERN = re.compile(r'\s+')
_SINGLE_LETTER_PATTERN = re.compile(r'[a-zA-Z]')

_WORD_OVERRIDES = [(re.compile(r'\b' + re.escape(eng) + r'\b', re.IGNORECASE), thai) for eng, thai in {
        "Minecraft": "มายคราฟ", "Roblox": "โรบล็อกซ์",
        "League of Legends": "ลีกออฟเลเจนด์", "Valorant": "วาโลแรนต์",
        "Genshin": "เก็นชิน", "Impact": "อิมแพกต์", "Angel": "แองเจิล",
        "Beats": "บีทส์", "Facebook": "เฟซบุ๊ก", "YouTube": "ยูทูบ",
        "TikTok": "ติ๊กต็อก", "Discord": "ดิสคอร์ด", "Google": "กูเกิล",
        "Twitch": "ทวิตช์", "RAM": "แรม", "VTuber": "วีทูเบอร์",
        "Isla": "ไอซ่า", "Plastic": "พลาสติก", "Memories": "เมมโมรี่",
        "Memory": "เมมโมรี่", "Loop": "ลูป", "Gemma": "เจมม่า",
        "Gemini": "เจมิไน", "Typhoon": "ไทฟูน", "Qwen": "ควิ้น",
        "Chat": "แชต",
}.items()]

_ALPHABET = {'A':'เอ','B':'บี','C':'ซี','D':'ดี','E':'อี','F':'เอฟ','G':'จี','H':'เอช','I':'ไอ','J':'เจ','K':'เค','L':'แอล','M':'เอ็ม','N':'เอ็น','O':'โอ','P':'พี','Q':'คิว','R':'อาร์','S':'เอส','T':'ที','U':'ยู','V':'วี','W':'ดับเบิลยู','X':'เอกซ์','Y':'วาย','Z':'แซด'}

# =====================================================================
# CORE ENGINES
# =====================================================================
rvc_lock = asyncio.Lock()
print("⏳ Loading Tsukuyomi-chan Filter...")
rvc = RVCInference(device="cpu")
rvc.load_model(RVC_MODEL_PATH, index_path=RVC_INDEX_PATH)
rvc.set_params(f0method="pm", f0up_key=5, index_rate=0.75)
print("✅ Voice Engine Ready!")

thread_pool = ThreadPoolExecutor(max_workers=CPU_WORKERS)
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# =====================================================================
# GLOBALS & MODELS
# =====================================================================
CONSECUTIVE_LAUGHS = 0
SUPPRESSION_LEFT = 0
LIVE_CHAT_HISTORY = deque(maxlen=15)
_AUDIO_QUEUE = deque()
_AUDIO_COND = asyncio.Condition()

CURRENT_DISPLAY_USER = "Isla System"
CURRENT_DISPLAY_MSG = "Waiting for the stream to start..."

class SpeechRequest(BaseModel):
    input: str
    voice: str = "nova"
    model: str = "tts-1"

class VisualChatRequest(BaseModel):
    user: str
    message: str
    is_creator: bool = False

class ChatInjectRequest(BaseModel):
    username: str
    message: str
    is_creator: bool = False

YOUTUBE_CHAT_QUEUE = deque()

# 1. Endpoint to receive the chat from our bridge
@app.post("/inject_chat")
async def inject_chat(req: ChatInjectRequest):
    if req.is_creator:
        text = f"[CREATOR - {req.username}]: {req.message}"
    else:
        text = f"[{req.username}]: {req.message}"
    YOUTUBE_CHAT_QUEUE.append(text)
    return {"status": "success"}

# 2. AIRI's Hearing Module will constantly ping this!
@app.post("/v1/audio/transcriptions")
async def phantom_microphone(request: Request):
    # AIRI sends your real microphone audio here, but WE IGNORE IT!
    # We only return the YouTube text waiting in our queue.
    if YOUTUBE_CHAT_QUEUE:
        text = YOUTUBE_CHAT_QUEUE.popleft()
        print(f"🎤 PHANTOM MIC: Injected '{text}' into AIRI!")
        return {"text": text}
    
    # If the queue is empty, return silence so AIRI does nothing.
    return {"text": ""}

# =====================================================================
# TEXT PROCESSING
# =====================================================================
def apply_laughter_control(text: str) -> str:
    global CONSECUTIVE_LAUGHS, SUPPRESSION_LEFT
    has_laugh = bool(_LAUGH_PATTERN.search(text))
    if SUPPRESSION_LEFT > 0:
        text = _LAUGH_PATTERN.sub(' ', text).replace('  ', ' ').strip()
        SUPPRESSION_LEFT -= 1
        if SUPPRESSION_LEFT <= 0: CONSECUTIVE_LAUGHS = 0
        return text
    if has_laugh:
        CONSECUTIVE_LAUGHS += 1
        if CONSECUTIVE_LAUGHS >= random.randint(2, 3):
            SUPPRESSION_LEFT = random.randint(1, 3)
            text = _LAUGH_PATTERN.sub(' ', text).replace('  ', ' ').strip()
    else: CONSECUTIVE_LAUGHS = 0
    return text

def clean_for_vachana(text: str) -> str:
    text = text.replace("<3", "")
    for pattern, thai in _WORD_OVERRIDES: text = pattern.sub(thai, text)
    text = _SINGLE_LETTER_PATTERN.sub(lambda m: " " + _ALPHABET.get(m.group(0).upper(), "") + " ", text)
    text = _PARENS_PATTERN.sub('', text)
    text = _SQUARE_PATTERN.sub('', text)
    text = _MULTI55_PATTERN.sub(' ฮ่าๆๆ ', text)
    text = re.sub(r'(\d+)\.(\d+)', r'\1 จุด \2', text)
    text = text.replace("=", " เท่ากับ ").replace("+", " บวก ").replace("-", " ลบ ")
    text = _DIGITS_PATTERN.sub(lambda x: num_to_thaiword(int(x.group())), text)
    text = _NON_THAI_PATTERN.sub('', text)
    return _MULTI_SPACE_PATTERN.sub(' ', text).strip()

def _tts_worker(safe_text: str, temp_raw: str):
    TTS(text=safe_text, voice="th_f_1", output=temp_raw, volume=1.0, speed=1.0)
    audio_data, sr = sf.read(temp_raw)
    silence = np.zeros(int(sr * 0.2), dtype=audio_data.dtype)
    sf.write(temp_raw, np.concatenate((audio_data, silence)), sr)

# =====================================================================
# PARALLEL PIPELINE
# =====================================================================
async def process_single_chunk(phrase: str, index: int, results: list, ready_events: list):
    safe_text = clean_for_vachana(phrase)
    if not safe_text.strip():
        results[index] = SILENCE_AUDIO
        ready_events[index].set()
        return

    uid, loop = str(uuid.uuid4())[:8], asyncio.get_event_loop()
    temp_raw, final = f"temp_raw_{uid}.wav", f"isla_final_{uid}.wav"
    print(f"🎙️  [TTS  {index}] {phrase}")

    try:
        await loop.run_in_executor(thread_pool, _tts_worker, safe_text, temp_raw)
        async with rvc_lock:
            print(f"🔊  [RVC  {index}] converting...")
            await loop.run_in_executor(thread_pool, rvc.infer_file, temp_raw, final)
    except Exception as e:
        print(f"⚠️  Error {index}: {e}")
        results[index] = SILENCE_AUDIO
    finally:
        if os.path.exists(temp_raw): os.remove(temp_raw)

    results[index] = final if os.path.exists(final) else SILENCE_AUDIO
    ready_events[index].set()

async def ordered_pusher(results: list, ready_events: list):
    for i in range(len(results)):
        await ready_events[i].wait()
        async with _AUDIO_COND:
            _AUDIO_QUEUE.append(results[i])
            _AUDIO_COND.notify_all()

# =====================================================================
# API ENDPOINTS
# =====================================================================
@app.get("/v1/models")
async def dummy_models():
    return {"object": "list", "data": [{"id": "gemma", "object": "model", "owned_by": "kobold"}]}

@app.post("/v1/chat/completions")
async def proxy_llm(request: Request):
    global CURRENT_DISPLAY_USER, CURRENT_DISPLAY_MSG
    body = await request.json()
    
    # 1. Aggressively remove tool-related keys
    body.pop("tools", None)
    body.pop("tool_choice", None)
    body.pop("functions", None)

    body["stream"] = False

    # 🌟 2. CATCH MESSAGE FOR TOP-LEFT OVERLAY 🌟
    if body.get("messages"):
        prompt = body["messages"][-1]["content"]
        
        # Check if it's the Creator!
        if prompt.startswith("[CREATOR -"):
            match = re.search(r'\[CREATOR - (.*?)\]:\s*(.*)', prompt)
            if match: 
                CURRENT_DISPLAY_USER = f"👑 {match.group(1)}"
                CURRENT_DISPLAY_MSG = match.group(2)
        # Check if it's a normal viewer!
        elif prompt.startswith("["):
            match = re.search(r'\[(.*?)\]:\s*(.*)', prompt)
            if match:
                CURRENT_DISPLAY_USER = match.group(1)
                CURRENT_DISPLAY_MSG = match.group(2)
        # If typed manually in AIRI
        else:
            CURRENT_DISPLAY_USER = "Director"
            CURRENT_DISPLAY_MSG = prompt

    # 🌟 3. THE PURGE: Clean the messages array!
    clean_messages = []
    
    for msg in body.get("messages",[]):
        content = msg.get("content", "")
        
        # 🔪 THE CLOCK ASSASSIN: If it's the datetime plugin, skip it completely!
        if "airi:system:datetime" in content:
            continue
            
        # 🔪 THE RULE ASSASSIN: Nuke AIRI's hidden Python/Math instructions
        if msg.get("role") == "system":
            content = re.sub(r'- For any programming code block.*?\n', '', content, flags=re.IGNORECASE)
            content = re.sub(r'- For any programming code block.*$', '', content, flags=re.IGNORECASE)
            content = re.sub(r'- For any math equation.*?\n', '', content, flags=re.IGNORECASE)
            content = re.sub(r'- For any math equation.*$', '', content, flags=re.IGNORECASE)
            msg["content"] = content
            
        # If the message survived the assassins, add it to the clean list!
        clean_messages.append(msg)
        
    # Replace the dirty messages with our clean list
    body["messages"] = clean_messages
    
    body["stop"] =["```", "User:", "ผู้ใช้:", "<|im_end|>"]

    # 4. Proxy to Koboldcpp
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(KOBOLD_URL, json=body)
    
    # 5. Extract and Process Text
    data = response.json()
    full_text = data["choices"][0]["message"]["content"]
    full_text = apply_laughter_control(full_text)
    print(f"\n💡 Output: {full_text}")

    # 6. Smart Sentence Splitting
    raw_phrases = re.split(r'(?<=[!\?~\n])\s*', full_text)
    phrases, temp_phrase =[], ""
    
    for p in raw_phrases:
        p = p.strip()
        if not p: continue
        temp_phrase += p + " "
        
        # If it hits 30 characters, push it to the queue
        if len(temp_phrase) >= 30:
            phrases.append(temp_phrase.strip())
            temp_phrase = ""

    # 🌟 THE FIX: Flush the Leftover Buffer! 🌟
    # If the loop finishes but a short sentence is still sitting in temp_phrase, add it!
    if temp_phrase.strip():
        phrases.append(temp_phrase.strip())

    # 7. Audio Pipeline Management
    n = len(phrases)
    results, ready_events = [None]*n, [asyncio.Event() for _ in range(n)]
    async with _AUDIO_COND: 
        _AUDIO_QUEUE.clear()

    # Create the task properly (as a coroutine wrapper)
    async def run_pipeline():
        tasks = [process_single_chunk(p, i, results, ready_events) for i, p in enumerate(phrases)]
        tasks.append(ordered_pusher(results, ready_events))
        await asyncio.gather(*tasks)

    asyncio.create_task(run_pipeline())

    # 8. Stream phrases back to the frontend immediately
    async def fake_stream():
        for i, p in enumerate(phrases):
            await ready_events[i].wait() # Wait for the audio to be ready/started for this chunk
            chunk = {
                "id": "chat", 
                "object": "chat.completion.chunk", 
                "model": "gemma", 
                "choices": [{"index": 0, "delta": {"content": p + " "}, "finish_reason": None}]
            }
            yield f"data: {json.dumps(chunk)}\n\n"
            await asyncio.sleep(0.05) 
            
        yield f"data: {json.dumps({'choices': [{'delta': {}, 'finish_reason': 'stop'}]})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(fake_stream(), media_type="text/event-stream")

@app.post("/v1/audio/speech")
async def generate_speech(req: SpeechRequest, background_tasks: BackgroundTasks):
    try:
        async with _AUDIO_COND:
            await asyncio.wait_for(_AUDIO_COND.wait_for(lambda: len(_AUDIO_QUEUE) > 0), timeout=30.0)
            file_path = _AUDIO_QUEUE.popleft()
        if file_path != SILENCE_AUDIO: background_tasks.add_task(os.remove, file_path)
        return FileResponse(file_path, media_type="audio/wav")
    except: return FileResponse(SILENCE_AUDIO, media_type="audio/wav")

# =====================================================================
# OBS OVERLAYS ENDPOINTS
# =====================================================================
@app.post("/push_visual_chat")
async def push_visual_chat(req: VisualChatRequest):
    LIVE_CHAT_HISTORY.append({"user": req.user, "message": req.message, "is_creator": req.is_creator})
    if len(LIVE_CHAT_HISTORY) > 15: LIVE_CHAT_HISTORY.pop(0)
    return {"status": "success"}

@app.get("/current_msg_data")
def get_msg_data(): return {"user": CURRENT_DISPLAY_USER, "msg": CURRENT_DISPLAY_MSG}

@app.get("/visual_chat_data")
def get_visual_chat_data(): return {"chats": list(LIVE_CHAT_HISTORY)}

@app.get("/overlay")
def get_overlay():
    return HTMLResponse("""
    <html><head><link href="https://fonts.googleapis.com/css2?family=Kanit:wght@400;600&display=swap" rel="stylesheet">
    <style>
    body{background:transparent;font-family:'Kanit',sans-serif;overflow:hidden}
    .box{background-color:#FDF6E3;border:4px solid #D4C4A8;border-radius:20px;padding:20px;width:400px;box-shadow:5px 5px 15px rgba(0,0,0,0.2)}
    .title{font-size:22px;font-weight:600;color:#6D597A;margin-bottom:10px}
    .msg{font-size:20px;color:#4A3E3D;word-wrap:break-word}
    </style>
    <script>
    async function update(){
        try {
            let r = await fetch('/current_msg_data');
            let d = await r.json();
            document.getElementById('u').innerText = "From: " + d.user;
            document.getElementById('m').innerText = d.msg;
        } catch(e) {}
    }
    setInterval(update, 1000);
    </script>
    </head><body>
    <div class="box"><div class="title" id="u">From: Isla System</div><div class="msg" id="m">Ready...</div></div>
    </body></html>
    """)

@app.get("/scrolling_chat")
def scrolling_chat():
    return HTMLResponse("""
    <html><head><link href="https://fonts.googleapis.com/css2?family=Kanit:wght@400;600&display=swap" rel="stylesheet">
    <style>
    body{background:transparent;font-family:'Kanit',sans-serif;overflow:hidden;margin:0;padding:15px;display:flex;flex-direction:column;justify-content:flex-end;height:100vh}
    .chat-msg{background:rgba(0,0,0,0.6);color:white;padding:10px 15px;border-radius:12px;font-size:18px;width:fit-content;max-width:90%;margin-bottom:8px;animation:in 0.3s ease-out}
    .creator{border:2px solid #FFD700;background:rgba(50,0,0,0.8)}
    .username{font-weight:600;color:#FF94A2;margin-right:8px}
    .creator-name{color:#FFD700}
    @keyframes in{from{opacity:0;transform:translateX(20px)}to{opacity:1;transform:translateX(0)}}
    </style>
    <script>
    let last=0;
    async function up(){
        try {
            let r = await fetch('/visual_chat_data');
            let d = await r.json();
            if(d.chats.length !== last){
                let h = '';
                for(let c of d.chats){
                    let isC = c.is_creator;
                    h += `<div class="chat-msg ${isC ? 'creator' : ''}"><span class="username ${isC ? 'creator-name' : ''}">${isC ? '👑 ' : ''}${c.user}</span><span>${c.message}</span></div>`;
                }
                document.getElementById('b').innerHTML = h;
                window.scrollTo(0, document.body.scrollHeight);
                last = d.chats.length;
            }
        } catch(e) {}
    }
    setInterval(up, 500);
    </script>
    </head><body><div id="b"></div></body></html>
    """)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)