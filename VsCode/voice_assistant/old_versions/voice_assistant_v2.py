import speech_recognition as sr
import pyttsx3
import requests
import threading
import json
from flask import Flask, request

# Flask για να τρέχει το AI ως API
app = Flask(__name__)

# Ρυθμίσεις TTS
engine = pyttsx3.init()
engine.setProperty('rate', 180)

def speak(text):
    """Μιλά με TTS"""
    print(f"🗣️: {text}")
    engine.say(text)
    engine.runAndWait()

def listen():
    """Ακούει φωνή"""
    recognizer = sr.Recognizer()
    recognizer.pause_threshold = 1.0

    with sr.Microphone() as source:
        print("🎤 Με τη φωνή μου...")
        recognizer.adjust_for_ambient_noise(source)
        audio = recognizer.listen(source)

    try:
        text = recognizer.recognize_google(audio, language='el-GR')
        return text.lower()
    except sr.UnknownValueError:
        return None
    except sr.RequestError:
        return None

def ask_ai(question):
    """Στέλνει την ερώτηση στο AI για απάντηση"""
    try:
        # Αυτό θα πρέπει να συνδέεται με το τοπικό AI
        # Για τώρα, απλώς επιστρέφουμε μια απάντηση
        answer = f"Ακούσα: '{question}'. Πώς μπορώ να σας βοηθήσω;"
        return answer
    except Exception as e:
        return f"❌ Λάθος σύνδεσης: {e}"

@app.route('/ask', methods=['POST'])
def ask():
    """API endpoint για το AI να απαντά"""
    data = request.json
    question = data.get('question', '')
    if question:
        answer = ask_ai(question)
        return json.dumps({'answer': answer})
    return json.dumps({'answer': 'Τί θα πω;'})

if __name__ == '__main__':
    print("🎤 Voice Assistant με AI")
    print("Γράψτε 'quit' για έξοδο")

    while True:
        question = listen()

        if not question:
            continue

        # Κλείνει ο παράγοντας TTS και περιμένει response
        speak("Ακούω")

        # Απευθύνει την ερώτηση στο AI
        answer = ask_ai(question)

        # Μιλά την απάντηση
        speak(answer)

        if 'quit' in question:
            print("👋 Ας φύγουμε!")
            break
