import speech_recognition as sr
import os
import PyPDF2
import requests

# 1. ΚΑΘΟΛΙΚΕΣ ΜΕΤΑΒΛΗΤΕΣ & ΣΥΣΤΗΜΑ ΟΔΗΓΙΩΝ
conversation_history = [
    {
        "role": "system", 
        "content": (
            "Είσαι ένας έξυπνος βοηθός. Έχεις τη δυνατότητα να διαβάζεις αρχεία PDF. "
            "Πρέπει να απαντάς σε άπταιστα Ελληνικά. Αν ο χρήστης σε ρωτάει από πού απαντάς, "
            "εξήγησέ του ότι όταν χρησιμοποιείς φράσεις όπως 'σύμφωνα με το αρχείο', "
            "περιορίζεσαι μόνο στο περιεχόμενο του PDF. Αν δεν γνωρίζεις κάτι, πες 'Δεν γνωρίζω'."
        )
    }
]
current_pdf_text = ""

# 2. ΣΥΝΑΡΤΗΣΗ ΑΝΑΓΝΩΡΙΣΗΣ ΦΩΝΗΣ (STT)
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
        print("❌ Σφάλμα σύνδεσης στο ίντερνετ.")
        return None

# 3. ΣΥΝΑΡΤΗΣΗ ΑΝΑΓΝΩΣΗΣ PDF
def read_pdf(filename):
    """Διαβάζει και επιστρέφει το κείμενο ενός PDF."""
    if not filename.endswith('.pdf'):
        filename += '.pdf'
    if not os.path.exists(filename):
        print(f"❌ Το αρχείο '{filename}' δεν βρέθηκε. Βεβαιώσου ότι είσαι στον σωστό φάκελο.")
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
        print("✅ Το αρχείο διαβάστηκε επιτυχώς!")
        return text_content
    except Exception as e:
        print(f"❌ Σφάλμα κατά την ανάγνωση: {e}")
        return None

# 4. ΣΥΝΑΡΤΗΣΗ ΕΠΙΚΟΙΝΩΝΙΑΣ ΜΕ OLLAMA (AI)
def chat_with_ollama(user_text, restrict_to_pdf=False):
    """Επικοινωνεί με το Ollama κρατώντας το ιστορικό της συζήτησης."""
    global conversation_history, current_pdf_text
    
    if restrict_to_pdf:
        message_content = (
            f"ΟΔΗΓΙΑ: Απάντησε ΑΥΣΤΗΡΑ ΚΑΙ ΜΟΝΟ με βάση το παρακάτω κείμενο. "
            f"Αν η πληροφορία δεν υπάρχει, πες 'Δεν υπάρχει στο αρχείο'.\n\n"
            f"ΚΕΙΜΕΝΟ ΑΡΧΕΙΟΥ:\n{current_pdf_text}\n\n"
            f"ΕΡΩΤΗΣΗ: {user_text}"
        )
    else:
        message_content = user_text

    conversation_history.append({"role": "user", "content": message_content})
    print("🧠 Σκέφτομαι...")
    url = "http://localhost:11434/api/chat"
    
    payload = {
        "model": "llama3.1", 
        "messages": conversation_history,
        "stream": False,
        "options": { "temperature": 0.3 }
    }

    try:
        response = requests.post(url, json=payload)
        if response.status_code == 200:
            ai_reply = response.json().get('message', {}).get('content', 'Σφάλμα ανάγνωσης.')
            if restrict_to_pdf:
                # Καθαρισμός του ιστορικού από το τεράστιο κείμενο για οικονομία μνήμης
                conversation_history[-1]["content"] = user_text 
            conversation_history.append({"role": "assistant", "content": ai_reply})
            return ai_reply
        return "❌ Σφάλμα κατά την επικοινωνία με το Ollama."
    except requests.exceptions.RequestException:
        return "❌ Δεν μπόρεσα να συνδεθώ στο Ollama."

# 5. ΚΥΡΙΑ ΛΕΙΤΟΥΡΓΙΑ ΠΡΟΓΡΑΜΜΑΤΟΣ
def main():
    global current_pdf_text
    print("🚀 ΕΚΚΙΝΗΣΗ LOCAL AI ΒΟΗΘΟΥ")

    while True:
        print("\n" + "-"*50)
        mode = input("⌨️ Γράψε ή πάτα ENTER για το μικρόφωνο: ")
        user_input = listen() if mode.strip() == "" else mode.lower()

        if not user_input: continue
        if any(word in user_input for word in ['έξοδος', 'σταμάτα', 'exit', 'quit']):
            print("👋 Αντίο!")
            break

        # ΛΕΞΕΙΣ-ΚΛΕΙΔΙΑ ΠΟΥ ΕΝΕΡΓΟΠΟΙΟΥΝ ΤΗΝ ΑΝΑΖΗΤΗΣΗ ΣΤΟ PDF (ΜΕ ΚΑΙ ΧΩΡΙΣ ΤΟΝΟΥΣ)
        pdf_triggers = [
            "σύμφωνα με", "συμφωνα με", 
            "από το αρχείο", "απο το αρχειο", 
            "βάσει του", "βασει του", 
            "γνώσεις του", "γνωσεις του", 
            "περιεχόμενο", "περιεχομενο", 
            "αρχείο αυτό", "αρχειο αυτο", 
            "αυτό το αρχείο", "αυτο το αρχειο",
            "του αρχείου", "του αρχειου"
        ]
        is_pdf_request = any(phrase in user_input for phrase in pdf_triggers)

        # Α. ΕΛΕΓΧΟΣ: ΕΙΝΑΙ ΕΡΩΤΗΣΗ ΓΙΑ ΤΟ ΗΔΗ ΦΟΡΤΩΜΕΝΟ PDF;
        if is_pdf_request:
            if not current_pdf_text:
                print("❌ Δεν έχεις φορτώσει κάποιο αρχείο ακόμα. Πες π.χ. 'Διάβασε το αρχείο βάσεις'.")
                continue
            reply = chat_with_ollama(user_input, restrict_to_pdf=True)
            print(f"\n🤖 AI: {reply}\n")

        # Β. ΕΛΕΓΧΟΣ: ΕΙΝΑΙ ΕΝΤΟΛΗ ΓΙΑ ΦΟΡΤΩΣΗ ΝΕΟΥ ΑΡΧΕΙΟΥ;
        elif any(kw in user_input for kw in ["διάβασ", "διαβάσ", "αρχείο", "αρχειο"]):
            words = user_input.split()
            try:
                idx = -1
                if "αρχείο" in words: idx = words.index("αρχείο")
                elif "αρχειο" in words: idx = words.index("αρχειο")
                
                if idx != -1 and idx + 1 < len(words):
                    filename = words[idx + 1]
                    
                    # ΑΠΟΦΥΓΗ ΛΑΘΟΥΣ: Αν η επόμενη λέξη είναι "αυτό" ή "του", χρησιμοποίησε τη μνήμη
                    if filename in ["αυτό", "αυτο", "του", "του.", "αυτού", "αυτου"]:
                        if current_pdf_text:
                            reply = chat_with_ollama(user_input, restrict_to_pdf=True)
                            print(f"\n🤖 AI: {reply}\n")
                        else:
                            print("❌ Δεν έχεις φορτώσει κάποιο αρχείο ακόμα.")
                        continue

                    # Μετατροπή ελληνικών ονομάτων στα αγγλικά ονόματα των αρχείων σου
                    if filename in ["βάσεις", "βασεις", "βασεισ", "βάσεισ", "βάσ", "βασ"]:
                        filename = "baseis"
                    
                    current_pdf_text = read_pdf(filename)
                continue 
            except:
                continue

        # Γ. ΚΑΝΟΝΙΚΗ ΣΥΖΗΤΗΣΗ
        else:
            reply = chat_with_ollama(user_input, restrict_to_pdf=False)
            print(f"\n🤖 AI: {reply}\n")

if __name__ == "__main__":
    main()