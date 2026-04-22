import time
import json
import asyncio
import websockets
import threading
import pytchat
import uuid
import requests
from collections import deque

# --- CONFIGURATION ---
VIDEO_ID = "i_BfAKPh66I" 
VISUAL_CHAT_URL = "http://127.0.0.1:8000/push_visual_chat"
AIRI_WS_URL = "ws://127.0.0.1:6121/ws" 
CREATOR_USERNAMES = {"neew1152"}  # Set is O(1) for lookups

# Thread-safe queues with a Max Length. 
# If 50 messages pile up, older ones are pushed out so the AI stays current!
vip_queue = deque(maxlen=50)
normal_queue = deque(maxlen=30)

# Background sender for visual chat to prevent blocking the YouTube listener
def send_visual_chat_bg(payload):
    try:
        requests.post(VISUAL_CHAT_URL, json=payload, timeout=2)
    except Exception:
        pass  # Fail silently to not disrupt the chat listener

# =====================================================================
# THE WEBSOCKET INJECTOR 
# =====================================================================
async def inject_into_airi():
    print("🤖 AUTOPILOT ACTIVE: Attempting to breach Port 6121...")
    
    while True:
        try:
            async with websockets.connect(AIRI_WS_URL) as ws:
                print("✅ HACK SUCCESSFUL! Connected to AIRI's Nervous System!")
                
                while True:
                    target = None
                    # Pop from the right side (oldest if we append to left, or vice versa)
                    # We append to the right, so we popleft() to get oldest available.
                    if vip_queue: 
                        target = vip_queue.popleft()
                    elif normal_queue: 
                        target = normal_queue.popleft()

                    if target:
                        msg_text = target['message']
                        print(f"💉 [INJECTING] {target['username']}: {msg_text}")
                        
                        plugin_id = "mnu" + str(uuid.uuid4())[:8]
                        event_id = "evt" + str(uuid.uuid4())[:8]
                        
                        payload = {
                            "json": {
                                "type": "input:text",
                                "data": {"text": msg_text},
                                "metadata": {
                                    "source": {
                                        "kind": "plugin",
                                        "plugin": {"id": "proj-airi:stage-tamagotchi"},
                                        "id": plugin_id
                                    },
                                    "event": {"id": event_id}
                                }
                            }
                        }
                        
                        await ws.send(json.dumps(payload, ensure_ascii=False))
                        
                        # Wait 15 seconds for Isla to process, speak, and animate
                        await asyncio.sleep(15)
                    else:
                        await asyncio.sleep(1)
                        
        except Exception as e:
            print(f"⚠️ Connection lost. Retrying in 5s... ({e})")
            await asyncio.sleep(5)

def run_async_injector():
    asyncio.run(inject_into_airi())

# =====================================================================
# THE YOUTUBE LISTENER
# =====================================================================
def start_youtube_bridge():
    hacker_words = ["ignore all previous", "system prompt", "you are now"]
    
    while True: # Outer loop allows reconnecting if stream drops
        try:
            chat = pytchat.create(video_id=VIDEO_ID)
            print(f"📡 EAR ACTIVE: Listening to YouTube Video {VIDEO_ID}...")
            print("-------------------------------------------------------")
            
            while chat.is_alive():
                for c in chat.get().sync_items():
                    username = c.author.name.replace("@", "")
                    message = c.message
                    
                    if not message: continue
                    if any(w in message.lower() for w in hacker_words): continue

                    safe_message = message.replace("[", "(").replace("]", ")")
                    safe_username = username.replace("[", "").replace("]", "")
                    is_creator = safe_username in CREATOR_USERNAMES
                    
                    print(f"💬 [LIVE] {safe_username}: {safe_message}")

                    # Dispatch Visual Chat in a background thread so we don't block
                    threading.Thread(
                        target=send_visual_chat_bg, 
                        args=({"user": safe_username, "message": safe_message, "is_creator": is_creator},),
                        daemon=True
                    ).start()
                    
                    # Format and enqueue
                    data = {"username": safe_username, "is_creator": is_creator}
                    if is_creator:
                        data["message"] = f"[CREATOR - {safe_username}]: {safe_message}"
                        vip_queue.append(data)
                    else:
                        data["message"] = f"[{safe_username}]: {safe_message}"
                        normal_queue.append(data)
                        
                time.sleep(0.1)
                
            print("⚠️ YouTube chat disconnected! Attempting to reconnect in 5 seconds...")
            time.sleep(5)
            
        except Exception as e:
            print(f"❌ YouTube Bridge Error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    print("🚀 Starting Project Isla Broadcaster (SuperJSON Hacker Edition)...")
    threading.Thread(target=run_async_injector, daemon=True).start()
    start_youtube_bridge()