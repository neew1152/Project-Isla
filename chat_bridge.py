import time
import json
import asyncio
import websockets
import threading
import pytchat
import uuid
import requests

# --- CONFIGURATION ---
VIDEO_ID = "i_BfAKPh66I" 
VISUAL_CHAT_URL = "http://127.0.0.1:8000/push_visual_chat"

# THE MASTER KEY FOUND!
AIRI_WS_URL = "ws://127.0.0.1:6121/ws" 

CREATOR_USERNAMES = ["neew1152"]

vip_queue =[]
normal_queue =[]

# =====================================================================
# THE WEBSOCKET INJECTOR (Port 6121 Hacker)
# =====================================================================
async def inject_into_airi():
    print("🤖 AUTOPILOT ACTIVE: Attempting to breach Port 6121...")
    
    while True:
        try:
            # Connect directly to AIRI's internal event bus
            async with websockets.connect(AIRI_WS_URL) as ws:
                print("✅ HACK SUCCESSFUL! Connected to AIRI's Nervous System!")
                
                while True:
                    target = None
                    if vip_queue: target = vip_queue.pop(0)
                    elif normal_queue: target = normal_queue.pop(0)

                    if target:
                        msg_text = target['message']
                        print(f"💉 [INJECTING] {target['username']}: {msg_text}")
                        
                        # Generate fake IDs to trick the SuperJSON event bus
                        plugin_id = "mnu" + str(uuid.uuid4())[:8]
                        event_id = "evt" + str(uuid.uuid4())[:8]
                        
                        # THE EXACT PAYLOAD YREVERSE-ENGINEERED
                        payload = {
                            "json": {
                                "type": "input:text",
                                "data": {
                                    "text": msg_text
                                },
                                "metadata": {
                                    "source": {
                                        "kind": "plugin",
                                        "plugin": {"id": "proj-airi:stage-tamagotchi"},
                                        "id": plugin_id
                                    },
                                    "event": {
                                        "id": event_id
                                    }
                                }
                            }
                        }
                        
                        # THE FIX: ensure_ascii=False prevents Thai characters from turning into alien text!
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
# THE YOUTUBE LISTENER (The Ears)
# =====================================================================
def start_youtube_bridge():
    try:
        chat = pytchat.create(video_id=VIDEO_ID)
        print(f"📡 EAR ACTIVE: Listening to YouTube Video {VIDEO_ID}...")
        print("-------------------------------------------------------")
        inject_into_airi
        while chat.is_alive():
            for c in chat.get().sync_items():
                # Strip the @ symbol immediately!
                username = c.author.name.replace("@", "")
                message = c.message
                if len(message) < 1: continue

                hacker_words =["ignore all previous", "system prompt", "you are now"]
                if any(w in message.lower() for w in hacker_words): continue

                safe_message = message.replace("[", "(").replace("]", ")")
                safe_username = username.replace("[", "").replace("]", "")
                is_creator = safe_username in CREATOR_USERNAMES
                
                print(f"💬 [LIVE] {safe_username}: {safe_message}")

                try: requests.post(VISUAL_CHAT_URL, json={"user": safe_username, "message": safe_message, "is_creator": is_creator}, timeout=2)
                except: pass
                
                # Format perfectly without doubling the name!
                data = {"username": safe_username, "is_creator": is_creator}
                if is_creator:
                    data["message"] = f"[CREATOR - {safe_username}]: {safe_message}"
                    vip_queue.append(data)
                else:
                    data["message"] = f"[{safe_username}]: {safe_message}"
                    normal_queue.append(data)
                    
            time.sleep(0.1)
    except Exception as e:
        print(f"❌ YouTube Bridge Error: {e}")

if __name__ == "__main__":
    print("🚀 Starting Project Isla Broadcaster (SuperJSON Hacker Edition)...")
    threading.Thread(target=run_async_injector, daemon=True).start()
    start_youtube_bridge()