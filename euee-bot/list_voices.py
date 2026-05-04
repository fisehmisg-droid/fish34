from elevenlabs.client import ElevenLabs
from config import ELEVENLABS_API_KEY

client = ElevenLabs(api_key=ELEVENLABS_API_KEY)
voices = client.voices.get_all()
for voice in voices.voices:
    print(f"Name: {voice.name}, ID: {voice.voice_id}, Category: {voice.category}")
