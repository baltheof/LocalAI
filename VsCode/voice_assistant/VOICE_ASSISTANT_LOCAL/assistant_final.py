import speech_recognition as sr
import requests
from gtts import gTTS
import pygame
import os
import time

# Αρχικοποίηση του συστήματος ήχου
pygame.mixer.init()

def speak(text):
    """Εκφωνεί το κείμενο με τη σταθερή και φυσιολογική φωνή της Google"""
    print(f"\n🤖 AI: {text}")
    try:
        # Χρησιμοποιούμε το gTTS για να μην σπάει ποτέ
        tts = gTTS(text=text, lang='el')
        filename = "temp_response.mp3"
        tts.save(filename)
        
        # Παίζει το αρχείο
        pygame.mixer.music.load(filename)
        pygame.mixer.music.play()
        
        while pygame.mixer.music.get_busy():
            time.sleep(0.1)
            
        pygame.mixer.music.unload()
        os.remove(filename)
    except Exception as e:
        print(f"❌ Σφάλμα στην ομιλία: {e}")

def listen():
    """Ακούει από το μικρόφωνο με μεγαλύτερη υπομονή"""
    recognizer = sr.Recognizer()
    
    # ΛΥΣΗ ΓΙΑ ΤΟ ΚΟΨΙΜΟ: Περιμένει 2.5 δευτερόλεπτα σιωπής πριν κλείσει το μικρόφωνο!
    recognizer.pause_threshold = 2.5 

    with sr.Microphone() as source:
        print("\n🎤 Ακούω... (Πες κάτι ή πες 'Έξοδος')")
        # Προσαρμογή στον θόρυβο του δωματίου
        recognizer.adjust_for_ambient_noise(source, duration=1)
        audio = recognizer.listen(source)

    try:
        text = recognizer.recognize_google(audio, language='el-GR')
        print(f"👤 Εσύ: {text}")
        return text
    except sr.UnknownValueError:
        print("❌ Δεν κατάλαβα τι είπες.")
        return None
    except sr.RequestError:
        print("❌ Σφάλμα σύνδεσης στο ίντερνετ.")
        return None

def ask_local_ai(question):
    """Στέλνει την ερώτηση στο τοπικό Ollama (Qwen)"""
    print("🧠 Σκέφτομαι...")
    url = "http://localhost:11434/api/generate"
    
    payload = {
        "model": "qwen2.5:3b",
        "prompt": f"Απάντησε ΑΠΛΑ και ΚΑΤΑΝΟΗΤΑ στα Ελληνικά. Χρησιμοποίησε 1-2 προτάσεις το πολύ. Ερώτηση: {question}",
        "stream": False,
        "options": {
            "temperature": 0.1  # Πολύ χαμηλά για να μιλάει σοβαρά και όχι εξωγήινα
        }
    }

    try:
        response = requests.post(url, json=payload)
        if response.status_code == 200:
            return response.json().get('response', 'Δεν έλαβα απάντηση.')
        else:
            return "Σφάλμα κατά την επικοινωνία με το AI."
    except requests.exceptions.RequestException:
        return "Δεν μπόρεσα να συνδεθώ στο Ollama. Είναι ανοιχτό;"

def main():
    print("🚀 Εκκίνηση Local Voice Assistant...")
    speak("Γεια σου! Είμαι έτοιμος. Τι θα ήθελες να συζητήσουμε;")

    while True:
        user_input = listen()

        if not user_input:
            continue

        if user_input.lower() in ['quit', 'exit', 'έξοδος', 'παύση', 'σταμάτα', 'κλείσε']:
            speak("Αντίο! Τα λέμε την επόμενη φορά.")
            break

        ai_reply = ask_local_ai(user_input)
        speak(ai_reply)

if __name__ == "__main__":
    main()