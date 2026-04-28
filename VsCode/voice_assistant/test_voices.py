import pyttsx3

engine = pyttsx3.init()
voices = engine.getProperty('voices')

print("--- ΦΩΝΕΣ ΠΟΥ ΒΛΕΠΕΙ Η PYTHON ---")
for index, voice in enumerate(voices):
    print(f"[{index}] Όνομα: {voice.name}")