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
from contextlib import asynccontextmanager
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

_WORD_OVERRIDES =[(re.compile(r'\b' + re.escape(eng) + r'\b', re.IGNORECASE), thai) for eng, thai in {
        "Minecraft": "มายคราฟ", "Roblox": "โรบล็อกซ์", "League of Legends": "ลีกออฟเลเจนด์", 
        "Valorant": "วาโลแรนต์", "Genshin": "เก็นชิน", "Impact": "อิมแพกต์", 
        "Facebook": "เฟซบุ๊ก", "YouTube": "ยูทูบ", "TikTok": "ติ๊กต็อก", "Discord": "ดิสคอร์ด", 
        "Isla": "ไอซ่า", "Gemma": "เจมม่า", "Gemini": "เจมิไน"
}.items()]
_ALPHABET = {'A':'เอ','B':'บี','C':'ซี','D':'ดี','E':'อี','F':'เอฟ','G':'จี','H':'เอช','I':'ไอ','J':'เจ','K':'เค','L':'แอล','M':'เอ็ม','N':'เอ็น','O':'โอ','P':'พี','Q':'คิว','R':'อาร์','S':'เอส','T':'ที','U':'ยู','V':'วี','W':'ดับเบิลยู','X':'เอกซ์','Y':'วาย','Z':'แซด'}

# =====================================================================
# CORE ENGINES & STATE
# =====================================================================
rvc_lock = asyncio.Lock()
print("⏳ Loading Tsukuyomi-chan Filter...")
rvc = RVCInference(device="cpu")
rvc.load_model(RVC_MODEL_PATH)
rvc.set_params(f0method="pm", f0up_key=5, index_rate=0)
print("✅ Voice Engine Ready!")

thread_pool = ThreadPoolExecutor(max_workers=CPU_WORKERS)

CONSECUTIVE_LAUGHS = 0
SUPPRESSION_LEFT = 0
LIVE_CHAT_HISTORY = deque(maxlen=15)
_AUDIO_QUEUE = deque()
_AUDIO_COND = asyncio.Condition()

CURRENT_DISPLAY_USER = "Isla System"
CURRENT_DISPLAY_MSG = "Waiting for the stream to start..."
YOUTUBE_CHAT_QUEUE = deque()

# Used to prevent Garbage Collection of running tasks
bg_tasks_ref = set()
# Used to abort old audio processing if a new message arrives
CURRENT_PIPELINE_ID = ""

# 🧹 DISK CLEANUP ON STARTUP 🧹
@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- STARTUP LOGIC ---
    print("🧹 Sweeping orphaned WAV files...")
    for file in glob.glob("isla_final_*.wav") + glob.glob("temp_raw_*.wav"):
        try: os.remove(file)
        except: pass
        
    yield  # The server runs while yielded here
    
    # --- SHUTDOWN LOGIC (Optional) ---
    print("🛑 Server shutting down...")

# Pass the lifespan function into the FastAPI app
app = FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

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

@app.post("/inject_chat")
async def inject_chat(req: ChatInjectRequest):
    text = f"[CREATOR - {req.username}]: {req.message}" if req.is_creator else f"[{req.username}]: {req.message}"
    YOUTUBE_CHAT_QUEUE.append(text)
    return {"status": "success"}

@app.post("/v1/audio/transcriptions")
async def phantom_microphone(request: Request):
    if YOUTUBE_CHAT_QUEUE:
        text = YOUTUBE_CHAT_QUEUE.popleft()
        print(f"🎤 PHANTOM MIC: Injected '{text}' into AIRI!")
        return {"text": text}
    return {"text": ""}

# =====================================================================
# TEXT & AUDIO PROCESSING
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

async def process_single_chunk(phrase: str, index: int, results: list, ready_events: list, pipeline_id: str):
    global CURRENT_PIPELINE_ID
    
    # Abort if a newer message has taken over the pipeline!
    if CURRENT_PIPELINE_ID != pipeline_id:
        return

    safe_text = clean_for_vachana(phrase)
    if not safe_text.strip():
        results[index] = SILENCE_AUDIO
        ready_events[index].set()
        return

    uid = str(uuid.uuid4())[:8]
    loop = asyncio.get_event_loop()
    temp_raw, final = f"temp_raw_{uid}.wav", f"isla_final_{uid}.wav"
    print(f"🎙️  [TTS  {index}] {phrase}")

    try:
        await loop.run_in_executor(thread_pool, _tts_worker, safe_text, temp_raw)
        
        # Double check abort flag before RVC lock!
        if CURRENT_PIPELINE_ID != pipeline_id: raise Exception("Pipeline Aborted")
        
        async with rvc_lock:
            print(f"🔊  [RVC  {index}] converting...")
            await loop.run_in_executor(thread_pool, rvc.infer_file, temp_raw, final)
    except Exception as e:
        if str(e) != "Pipeline Aborted":
            print(f"⚠️  Error {index}: {e}")
        results[index] = SILENCE_AUDIO
    finally:
        if os.path.exists(temp_raw): os.remove(temp_raw)

    results[index] = final if os.path.exists(final) else SILENCE_AUDIO
    ready_events[index].set()

async def ordered_pusher(results: list, ready_events: list, pipeline_id: str):
    global CURRENT_PIPELINE_ID
    for i in range(len(results)):
        await ready_events[i].wait()
        
        if CURRENT_PIPELINE_ID != pipeline_id:
            break # Stop pushing if pipeline was aborted
            
        async with _AUDIO_COND:
            _AUDIO_QUEUE.append(results[i])
            _AUDIO_COND.notify_all()

# =====================================================================
# API ENDPOINTS
# =====================================================================
@app.get("/v1/models")
async def dummy_models():
    return {"object": "list", "data":[{"id": "gemma", "object": "model", "owned_by": "kobold"}]}

@app.post("/v1/chat/completions")
async def proxy_llm(request: Request):
    global CURRENT_DISPLAY_USER, CURRENT_DISPLAY_MSG, CURRENT_PIPELINE_ID
    body = await request.json()
    
    body.pop("tools", None); body.pop("tool_choice", None); body.pop("functions", None)
    body["stream"] = False

    # Extract UI details
    if body.get("messages"):
        prompt = body["messages"][-1]["content"]
        if prompt.startswith("[CREATOR -"):
            match = re.search(r'\[CREATOR - (.*?)\]:\s*(.*)', prompt)
            if match: 
                CURRENT_DISPLAY_USER, CURRENT_DISPLAY_MSG = f"👑 {match.group(1)}", match.group(2)
        elif prompt.startswith("["):
            match = re.search(r'\[(.*?)\]:\s*(.*)', prompt)
            if match:
                CURRENT_DISPLAY_USER, CURRENT_DISPLAY_MSG = match.group(1), match.group(2)
        else:
            CURRENT_DISPLAY_USER, CURRENT_DISPLAY_MSG = "Director", prompt

    # Purge dirty instructions
    clean_messages = []
    for msg in body.get("messages",[]):
        content = msg.get("content", "")
        if "airi:system:datetime" in content: continue
        if msg.get("role") == "system":
            content = re.sub(r'- For any programming code block.*?\n', '', content, flags=re.IGNORECASE)
            content = re.sub(r'- For any programming code block.*$', '', content, flags=re.IGNORECASE)
            content = re.sub(r'- For any math equation.*?\n', '', content, flags=re.IGNORECASE)
            content = re.sub(r'- For any math equation.*$', '', content, flags=re.IGNORECASE)
            msg["content"] = content
        clean_messages.append(msg)
        
    body["messages"] = clean_messages
    body["stop"] =["```", "User:", "ผู้ใช้:", "<|im_end|>"]

    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(KOBOLD_URL, json=body)
    
    data = response.json()
    full_text = apply_laughter_control(data["choices"][0]["message"]["content"])
    print(f"\n💡 Output: {full_text}")

    raw_phrases = re.split(r'(?<=[!\?~\n])\s*', full_text)
    phrases, temp_phrase =[], ""
    for p in raw_phrases:
        p = p.strip()
        if not p: continue
        temp_phrase += p + " "
        if len(temp_phrase) >= 30:
            phrases.append(temp_phrase.strip())
            temp_phrase = ""
    if temp_phrase.strip():
        phrases.append(temp_phrase.strip())

    # Generate a new unique ID for this generation
    CURRENT_PIPELINE_ID = str(uuid.uuid4())
    my_pipeline_id = CURRENT_PIPELINE_ID
    
    n = len(phrases)
    results, ready_events = [None]*n,[asyncio.Event() for _ in range(n)]
    
    async with _AUDIO_COND: 
        _AUDIO_QUEUE.clear()

    async def run_pipeline():
        tasks =[process_single_chunk(p, i, results, ready_events, my_pipeline_id) for i, p in enumerate(phrases)]
        tasks.append(ordered_pusher(results, ready_events, my_pipeline_id))
        await asyncio.gather(*tasks)

    # SECURE TASK CREATION: Save reference to prevent GC!
    task = asyncio.create_task(run_pipeline())
    bg_tasks_ref.add(task)
    task.add_done_callback(bg_tasks_ref.discard)

    async def fake_stream():
        for i, p in enumerate(phrases):
            # If aborted, kill the stream sequence
            if CURRENT_PIPELINE_ID != my_pipeline_id: break 
            
            await ready_events[i].wait()
            chunk = {
                "id": "chat", "object": "chat.completion.chunk", "model": "gemma", 
                "choices":[{"index": 0, "delta": {"content": p + " "}, "finish_reason": None}]
            }
            yield f"data: {json.dumps(chunk)}\n\n"
            await asyncio.sleep(0.05) 
            
        yield f"data: {json.dumps({'choices':[{'delta': {}, 'finish_reason': 'stop'}]})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(fake_stream(), media_type="text/event-stream")

@app.post("/v1/audio/speech")
async def generate_speech(req: SpeechRequest, background_tasks: BackgroundTasks):
    try:
        async with _AUDIO_COND:
            await asyncio.wait_for(_AUDIO_COND.wait_for(lambda: len(_AUDIO_QUEUE) > 0), timeout=30.0)
            file_path = _AUDIO_QUEUE.popleft()
            
        # Don't try to delete the permanent silence asset!
        if file_path != SILENCE_AUDIO and os.path.exists(file_path): 
            background_tasks.add_task(os.remove, file_path)
            
        return FileResponse(file_path, media_type="audio/wav")
    except Exception as e: 
        return FileResponse(SILENCE_AUDIO, media_type="audio/wav")

# =====================================================================
# OBS OVERLAYS ENDPOINTS
# =====================================================================
@app.post("/push_visual_chat")
async def push_visual_chat(req: VisualChatRequest):
    # FIX: maxlen=15 deque handles discarding automatically. No pop() required!
    LIVE_CHAT_HISTORY.append({"user": req.user, "message": req.message, "is_creator": req.is_creator})
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