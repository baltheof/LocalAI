import speech_recognition as sr
import os
import PyPDF2
import requests

# Καθολικές μεταβλητές: Ιστορικό με αυστηρές οδηγίες (System Prompt) και κείμενο PDF
conversation_history = [
    {
        "role": "system", 
        "content": "Είσαι ένας έξυπνος και επαγγελματίας βοηθός τεχνητής νοημοσύνης. Πρέπει να απαντάς αποκλειστικά σε άπταιστα, φυσικά και σωστά Ελληνικά. Απαγορεύεται αυστηρά να εφευρίσκεις λέξεις ή να επαναλαμβάνεις τις ίδιες προτάσεις. Αν δεν γνωρίζεις μια απάντηση, απλά πες 'Δεν γνωρίζω' χωρίς να φλυαρείς."
    }
]
current_pdf_text = ""

def listen():
    """Ακούει από το μικρόφωνο και επιστρέφει το κείμενο."""
    recognizer = sr.Recognizer()
    recognizer.pause_threshold = 2.0 
    
    with sr.Microphone() as source:
        print("\n🎤 Ακούω...")
        recognizer.adjust_for_ambient_noise(source, duration=1)
        audio = recognizer.listen(source)
        
    try:
        text = recognizer.recognize_google(audio, language='el-GR')
        print(f"👤 Εσύ: {text}")
        return text.lower()
    except sr.UnknownValueError:
        print("❌ Δεν κατάλαβα τι είπες.")
        return None
    except sr.RequestError:
        print("❌ Σφάλμα σύνδεσης στο ίντερνετ (Απαιτείται για την αναγνώριση φωνής της Google).")
        return None

def read_pdf(filename):
    """Διαβάζει και επιστρέφει το κείμενο ενός PDF."""
    if not filename.endswith('.pdf'):
        filename += '.pdf'

    if not os.path.exists(filename):
        print(f"❌ Το αρχείο '{filename}' δεν βρέθηκε.")
        return None

    print(f"📄 Διαβάζω το αρχείο: {filename}...")
    text_content = ""
    try:
        with open(filename, 'rb') as file:
            pdf_reader = PyPDF2.PdfReader(file)
            for page in pdf_reader.pages:
                extracted = page.extract_text()
                if extracted:
                    text_content += extracted + "\n"
        print("✅ Το αρχείο διαβάστηκε και αποθηκεύτηκε στη μνήμη του προγράμματος!")
        return text_content
    except Exception as e:
        print(f"❌ Σφάλμα κατά την ανάγνωση: {e}")
        return None

def chat_with_ollama(user_text, restrict_to_pdf=False):
    """Επικοινωνεί με το Ollama κρατώντας το ιστορικό της συζήτησης."""
    global conversation_history, current_pdf_text
    
    # 1. Προετοιμασία του μηνύματος (Prompt)
    if restrict_to_pdf:
        # Αναγκάζουμε το μοντέλο να διαβάσει το κείμενο και να περιοριστεί σε αυτό
        message_content = (
            f"ΟΔΗΓΙΑ: Απάντησε ΑΥΣΤΗΡΑ ΚΑΙ ΜΟΝΟ με βάση το παρακάτω κείμενο. "
            f"Αν η πληροφορία δεν υπάρχει στο κείμενο, απάντησε 'Δεν υπάρχει αυτή η πληροφορία στο αρχείο'. "
            f"Μην χρησιμοποιήσεις προηγούμενες γνώσεις σου.\n\n"
            f"ΚΕΙΜΕΝΟ ΑΡΧΕΙΟΥ:\n{current_pdf_text}\n\n"
            f"ΕΡΩΤΗΣΗ: {user_text}"
        )
    else:
        message_content = user_text

    # 2. Προσθήκη στην ιστορία της συζήτησης
    conversation_history.append({"role": "user", "content": message_content})

    print("🧠 Σκέφτομαι...")
    url = "http://localhost:11434/api/chat"
    
    payload = {
        "model": "llama3.1",  # Το μοντέλο που έχεις κατεβάσει
        "messages": conversation_history,
        "stream": False,
        "options": {
            "temperature": 0.3  # Αυξημένο για να μην κολλάει σε λούπες
        }
    }

    try:
        response = requests.post(url, json=payload)
        if response.status_code == 200:
            ai_reply = response.json().get('message', {}).get('content', 'Σφάλμα ανάγνωσης.')
            
            # 3. Διόρθωση Ιστορικού (ΤΡΙΚ ΕΞΟΙΚΟΝΟΜΗΣΗΣ ΜΝΗΜΗΣ)
            if restrict_to_pdf:
                conversation_history[-1]["content"] = user_text 
            
            # 4. Αποθηκεύουμε την απάντηση του AI στη μνήμη
            conversation_history.append({"role": "assistant", "content": ai_reply})
            
            return ai_reply
        else:
            return "❌ Σφάλμα κατά την επικοινωνία με το Ollama."
    except requests.exceptions.RequestException:
        return "❌ Δεν μπόρεσα να συνδεθώ στο Ollama."

def main():
    global current_pdf_text
    print("🚀 ΕΚΚΙΝΗΣΗ LOCAL AI ΜΕ ΜΝΗΜΗ, ΑΝΑΓΝΩΣΗ PDF ΚΑΙ ΠΛΗΚΤΡΟΛΟΓΙΟ")

    while True:
        # Επιλογή εισαγωγής (Πληκτρολόγιο ή Μικρόφωνο)
        print("\n" + "-"*50)
        mode = input("⌨️ Γράψε την ερώτησή σου ΕΔΩ (ή πάτα απλά ENTER για να ανοίξει το μικρόφωνο): ")
        
        if mode.strip() == "":
            user_input = listen()
        else:
            user_input = mode.lower()
            print(f"👤 Εσύ (γραπτά): {user_input}")

        if not user_input:
            continue

        # Εντολή Εξόδου
        if any(word in user_input for word in ['έξοδος', 'σταμάτα', 'κλείσε', 'exit', 'quit']):
            print("👋 Αντίο!")
            break

        # Εντολή Φόρτωσης PDF (Πιο έξυπνη για να συγχωρεί ορθογραφικά και έλλειψη τόνων)
        if ("διαβάσ" in user_input or "διαβασ" in user_input or "διαβσ" in user_input) and ("αρχείο" in user_input or "αρχειο" in user_input):
            words = user_input.split()
            try:
                # Βρίσκουμε το index του "αρχείο" ή "αρχειο"
                if "αρχείο" in words:
                    index = words.index("αρχείο")
                elif "αρχειο" in words:
                    index = words.index("αρχειο")
                else:
                    # Αν για κάποιο λόγο δεν βρεθεί ακριβώς η λέξη ως αυτόνομη
                    continue
                
                filename_to_read = words[index + 1]
                
                current_pdf_text = read_pdf(filename_to_read)
                continue 
            except (ValueError, IndexError):
                print("❌ Πες ή γράψε καθαρά π.χ. 'Διάβασε το αρχείο αναφορά'.")
                continue

        # Εντολή Περιορισμένης Ερώτησης (ΜΟΝΟ από το PDF)
        if "σύμφωνα με το αρχείο" in user_input:
            if not current_pdf_text:
                print("❌ Δεν έχεις φορτώσει κάποιο αρχείο ακόμα. Δώσε πρώτα την εντολή 'Διάβασε το αρχείο [όνομα]'.")
                continue
            
            reply = chat_with_ollama(user_input, restrict_to_pdf=True)
            print(f"\n🤖 AI: {reply}\n")
            
        # Κανονική Ερώτηση (με μνήμη)
        else:
            reply = chat_with_ollama(user_input, restrict_to_pdf=False)
            print(f"\n🤖 AI: {reply}\n")

if __name__ == "__main__":
    main()