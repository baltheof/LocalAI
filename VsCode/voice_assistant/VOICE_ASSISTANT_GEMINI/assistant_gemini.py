import speech_recognition as sr
from google import genai
from gtts import gTTS
import pygame
import os
import time
import PyPDF2  # Η νέα βιβλιοθήκη για τα PDF

# --- ΡΥΘΜΙΣΕΙΣ ---
API_KEY = "AIzaSyC-MZZfwuYjimjOOfMQp5zziETnHCJVzWQ".strip() 
client = genai.Client(api_key=API_KEY)

# Δημιουργούμε μια "Συνεδρία" (Chat) που έχει ΜΝΗΜΗ
chat_session = client.chats.create(model='gemini-3-flash-preview')

# Αρχικοποίηση συστήματος ήχου
pygame.mixer.init()

def speak(text):
    """Μετατρέπει το κείμενο σε ομιλία και το αναπαράγει"""
    print(f"\n🤖 Gemini: {text}")
    try:
        clean_text = text.replace("*", "").replace("#", "")
        tts = gTTS(text=clean_text, lang='el')
        filename = "temp_voice.mp3"
        tts.save(filename)
        
        pygame.mixer.music.load(filename)
        pygame.mixer.music.play()
        
        while pygame.mixer.music.get_busy():
            time.sleep(0.1)
            
        pygame.mixer.music.unload()
        os.remove(filename)
    except Exception as e:
        print(f"❌ Σφάλμα ομιλίας: {e}")

def read_local_file(file_name):
    """Αναζητά και διαβάζει το περιεχόμενο αρχείων .pdf ή .txt στον σωστό φάκελο"""
    # Καθαρισμός του ονόματος από καταλήξεις και τελείες που ίσως πιάσει το μικρόφωνο
    file_name = file_name.strip().lower().replace(".", "").replace("pdf", "").replace("txt", "").strip()
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Φτιάχνουμε τα πιθανά μονοπάτια
    pdf_path = os.path.join(script_dir, file_name + '.pdf')
    txt_path = os.path.join(script_dir, file_name + '.txt')
        
    try:
        # Ψάχνει πρώτα για αρχείο PDF
        if os.path.exists(pdf_path):
            text_content = ""
            with open(pdf_path, 'rb') as f:
                reader = PyPDF2.PdfReader(f)
                for page in reader.pages:
                    extracted = page.extract_text()
                    if extracted:
                        text_content += extracted + "\n"
            print(f"📖 Το αρχείο PDF διαβάστηκε επιτυχώς από: {pdf_path}")
            return text_content
            
        # Αν δεν βρει PDF, ψάχνει για TXT
        elif os.path.exists(txt_path):
            with open(txt_path, 'r', encoding='utf-8') as f:
                content = f.read()
            print(f"📖 Το αρχείο TXT διαβάστηκε επιτυχώς από: {txt_path}")
            return content
            
        else:
            return None
            
    except Exception as e:
        print(f"❌ Σφάλμα κατά την ανάγνωση: {e}")
        return None

def listen():
    """Ακούει τον χρήστη χωρίς να βιάζεται να κλείσει το μικρόφωνο"""
    recognizer = sr.Recognizer()
    
    # 1η ΑΛΛΑΓΗ: Το αυξάνουμε στο 2.0 για να περιμένει λίγο παραπάνω σιωπή στο τέλος
    recognizer.pause_threshold = 2.0 
    
    with sr.Microphone() as source:
        print("\n🎤 Σε ακούω...")
        # 2η ΑΛΛΑΓΗ: Το επαναφέρουμε στο 1. Αργεί μισό δευτερόλεπτο παραπάνω να ανοίξει, 
        # αλλά ξεχωρίζει τέλεια τον θόρυβο από την κανονική σου φωνή!
        recognizer.adjust_for_ambient_noise(source, duration=1)
        audio = recognizer.listen(source)

    try:
        text = recognizer.recognize_google(audio, language='el-GR')
        print(f"👤 Εσύ: {text}")
        return text
    except:
        return None

def ask_gemini(question, file_context=None):
    """Στέλνει την ερώτηση στο Gemini χρησιμοποιώντας τη ΜΝΗΜΗ της συνεδρίας"""
    print("🧠 Σκέφτομαι...")
    
    if file_context:
        # Αν μόλις του δώσαμε ένα αρχείο, του λέμε να το βάλει στη μνήμη του
        full_prompt = (
            f"Σου δίνω το περιεχόμενο ενός αρχείου. Απομνημόνευσέ το για την υπόλοιπη συζήτηση:\n\n{file_context}\n\n"
            f"Με βάση αυτό, απάντησε στην εξής ερώτηση σύντομα, στα Ελληνικά και χωρίς αστερίσκους: {question}"
        )
    else:
        # Αλλιώς, συνεχίζει κανονικά τη συζήτηση
        full_prompt = f"Απάντησε σύντομα, στα Ελληνικά και χωρίς αστερίσκους: {question}"

    try:
        response = chat_session.send_message(full_prompt)
        return response.text
    except Exception as e:
        return f"Σφάλμα σύνδεσης με Gemini: {e}"

def main():
    print("🚀 Gemini Voice Assistant (Memory & PDF Enabled) Online!")
    speak("Γεια σου! Τι θα ήθελες σήμερα;")

    while True:
        user_input = listen()

        if not user_input:
            continue

        user_input_lower = user_input.lower()

        if user_input_lower in ['έξοδος', 'exit', 'κλείσε', 'σταμάτα']:
            speak("Αντίο! Κλείνω το σύστημα.")
            break

        file_content = None
        if "διάβασε" in user_input_lower or "αρχείο" in user_input_lower:
            words = user_input_lower.split()
            try:
                if "αρχείο" in words:
                    target = words[words.index("αρχείο") + 1]
                elif "το" in words:
                    target = words[words.index("το") + 1]
                else:
                    target = words[-1]
                
                file_content = read_local_file(target)
                
                if not file_content:
                    speak(f"Συγγνώμη, δεν βρήκα το αρχείο {target} στον φάκελό μου.")
                    continue
                else:
                    speak(f"Διάβασα το αρχείο {target}. Τι θα ήθελες να μάθεις για αυτό;")
                    user_input = listen()
                    if not user_input: continue
            except (IndexError, ValueError):
                speak("Ποιο αρχείο θέλεις να ανοίξω;")
                continue

        reply = ask_gemini(user_input, file_context=file_content)
        speak(reply)

if __name__ == "__main__":
    main()