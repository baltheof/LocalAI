import speech_recognition as sr
from google import genai  # Η νέα βιβλιοθήκη
from gtts import gTTS
import pygame
import os
import time

# --- ΡΥΘΜΙΣΕΙΣ ---
API_KEY = "AIzaSyC-MZZfwuYjimjOOfMQp5zziETnHCJVzWQ".strip() 

# Σύνδεση με το νέο σύστημα της Google
client = genai.Client(api_key=API_KEY)

# Αρχικοποίηση ήχου
pygame.mixer.init()

def speak(text):
    """Εκφωνεί το κείμενο καθαρά"""
    print(f"\n🤖 Gemini: {text}")
    try:
        clean_text = text.replace("*", "")
        tts = gTTS(text=clean_text, lang='el')
        filename = "gemini_voice.mp3"
        tts.save(filename)
        
        pygame.mixer.music.load(filename)
        pygame.mixer.music.play()
        
        while pygame.mixer.music.get_busy():
            time.sleep(0.1)
            
        pygame.mixer.music.unload()
        os.remove(filename)
    except Exception as e:
        print(f"❌ Σφάλμα ομιλίας: {e}")

def listen():
    """Ακούει χωρίς να σε διακόπτει"""
    recognizer = sr.Recognizer()
    recognizer.pause_threshold = 2.5 
    
    with sr.Microphone() as source:
        print("\n🎤 Σε ακούω...")
        recognizer.adjust_for_ambient_noise(source, duration=1)
        audio = recognizer.listen(source)

    try:
        text = recognizer.recognize_google(audio, language='el-GR')
        print(f"👤 Εσύ: {text}")
        return text
    except:
        return None

def ask_gemini(question):
    """Στέλνει την ερώτηση στο Gemini 3 Flash"""
    print("🧠 Σκέφτομαι...")
    try:
        # ΑΥΤΗ ΕΙΝΑΙ Η ΑΛΛΑΓΗ: Βάζουμε το όνομα που είδαμε στο AI Studio
        response = client.models.generate_content(
            model='gemini-3-flash-preview', 
            contents=f"Απάντησε στα Ελληνικά, σύντομα, χωρίς αστερίσκους. Ερώτηση: {question}"
        )
        return response.text
    except Exception as e:
        return f"Σφάλμα σύνδεσης: {e}"

def main():
    print("🚀 Gemini Voice Assistant (New SDK) Online!")
    speak("Γεια! Είμαι ο Gemini. Τώρα είμαι σωστά συνδεδεμένος. Τι θέλεις να μάθεις;")

    while True:
        user_input = listen()

        if not user_input:
            continue

        if user_input.lower() in ['έξοδος', 'exit', 'κλείσε', 'σταμάτα']:
            speak("Αντίο!")
            break

        reply = ask_gemini(user_input)
        speak(reply)

if __name__ == "__main__":
    main()