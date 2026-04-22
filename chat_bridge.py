import time
import requests
import threading
from collections import deque
from pytchat import LiveChat

# --- CONFIGURATION ---
VIDEO_ID = "YOUR_LIVE_VIDEO_ID" 
ISLA_PROXY_URL = "http://127.0.0.1:8000/v1/chat/completions"

# Put your exact YouTube Username here!
CREATOR_USERNAMES =["neew1152"]

# --- THE QOS QUEUES ---
vip_queue = deque()
normal_queue = deque()

# ---------------------------------------------------------
# THREAD 1: THE LISTENER (Sorts the incoming traffic)
# ---------------------------------------------------------
def listen_to_youtube():
    chat = LiveChat(video_id=VIDEO_ID)
    print(f"📡 EAR THREAD: Listening to YouTube Video {VIDEO_ID}...")
    
    while chat.is_alive():
        for c in chat.get().sync_items():
            username = c.author.name
            message = c.message
            
            # Basic Anti-Hacker Filter
            hacker_words =["ignore all previous", "system prompt"]
            if any(w in message.lower() for w in hacker_words):
                print(f"🛡️ Blocked injection from {username}")
                continue
                
            # QoS SORTING LOGIC
            if username in CREATOR_USERNAMES:
                print(f"🚨 [QoS VIP] {username} bypassed the line!")
                vip_queue.append({"user": username, "msg": message})
            else:
                normal_queue.append({"user": username, "msg": message})
                
        time.sleep(1) # Check for new messages every second

# ---------------------------------------------------------
# THREAD 2: THE WORKER (Sends traffic to Isla's Brain)
# ---------------------------------------------------------
def process_messages():
    print("⚙️ WORKER THREAD: Ready to route messages to Isla...")
    
    while True:
        target_msg = None
        
        # QoS PRIORITY CHECK: Always check VIP first!
        if len(vip_queue) > 0:
            target_msg = vip_queue.popleft()
            prompt_text = f"[CREATOR - {target_msg['user']}]: {target_msg['msg']}"
        
        # If no VIPs are waiting, pull from the normal queue
        elif len(normal_queue) > 0:
            target_msg = normal_queue.popleft()
            prompt_text = f"[{target_msg['user']}]: {target_msg['msg']}"
            
        # If we found a message, send it to the AI
        if target_msg:
            print(f"\n📤 ROUTING TO ISLA: {prompt_text}")
            payload = {
                "model": "gemma",
                "messages": [{"role": "user", "content": prompt_text}],
                "stream": False
            }
            try:
                requests.post(ISLA_PROXY_URL, json=payload, timeout=60)
            except Exception as e:
                print(f"❌ API Error: {e}")
                
            # Wait 15 seconds for Isla to finish talking before pulling the next message!
            time.sleep(15) 
        else:
            # If both queues are empty, just rest for a second and check again
            time.sleep(1)

# ---------------------------------------------------------
# MAIN LAUNCHER
# ---------------------------------------------------------
if __name__ == "__main__":
    print("🚀 Starting Isla's QoS Chat Bridge...")
    
    # Start the Ear in the background
    ear_thread = threading.Thread(target=listen_to_youtube, daemon=True)
    ear_thread.start()
    
    # Start the Mouth in the foreground
    process_messages()