# Voice Assistant - Επαφές με AI μέσω τοπικού Agent
# Πρέπει να τρέχει με το τοπικό περιβάλλον AI

import speech_recognition as sr
import pyttsx3
import time
import sys

# Ρυθμίσεις TTS
engine = pyttsx3.init()
engine.setProperty('rate', 180)
engine.setProperty('volume', 0.9)

def speak(text, rate=180):
    """Μιλά με TTS"""
    print(f"🗣️: {text}")
    engine.setProperty('rate', rate)
    engine.say(text)
    engine.runAndWait()

def listen(prompt=""):
    """Ακούει φωνή"""
    recognizer = sr.Recognizer()
    recognizer.pause_threshold = 0.8

    with sr.Microphone() as source:
        if prompt:
            print(f"🎤 {prompt}...")
        else:
            print("🎤 Με τη φωνή μου...")
        recognizer.adjust_for_ambient_noise(source)
        audio = recognizer.listen(source)

    try:
        text = recognizer.recognize_google(audio, language='el-GR')
        print(f"❓ Ακούσατε: {text}")
        return text
    except sr.UnknownValueError:
        print("❌ Δεν κατάλαβα")
        return None
    except sr.RequestError:
        print("❌ Λάθος Google")
        return None

def ask_question(text):
    """Απευθύνει την ερώτηση στο AI"""
    # Εδώ θα στείλουμε την ερώτηση στο τοπικό AI
    # Για τώρα, απλώς επιστρέφουμε μια απάντηση
    answers = {
        "γεια": "Γεια! Πώς μπορώ να σε βοηθήσω σήμερα;",
        "πως εισαι": "Είμαι καλά και εσύ;",
        "τι κάνεις": "Κάνω τον ρόλο μου! Πες μου κάτι άλλο.",
        "ωραία": "Και εγώ! Τι άλλο θέλεις να κάνουμε;",
        "ευχαριστώ": "Όλο το καλό! Τι άλλο θέλεις;",
    }

    text_lower = text.lower()
    for key, value in answers.items():
        if key in text_lower:
            return value

    return f"Ακούσα: '{text}'. Πες μου κάτι άλλο!"

def main():
    print("🎤 Voice Assistant")
    print("Γράψτε 'quit' ή παύση για έξοδο\n")

    while True:
        text = listen()

        if not text:
            continue

        if text.strip() in ['quit', 'exit', 'παύση']:
            speak("αντίο!")
            print("\n👋 αντίο!")
            break

        answer = ask_question(text)
        speak(answer)

        time.sleep(0.5)  # Ελαφριά αναμονή

if __name__ == "__main__":
    main()
