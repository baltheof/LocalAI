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
            "περιορίζεσαι μόνο στο περιεχόμενο των PDF που έχεις φορτώσει. Αν δεν γνωρίζεις κάτι, πες 'Δεν γνωρίζω'."
        )
    }
]
current_pdf_text = ""
loaded_pdfs = []  # ΝΕΟ: Λίστα για να θυμόμαστε ποια αρχεία έχουμε φορτώσει

# 2. ΣΥΝΑΡΤΗΣΗ ΑΝΑΓΝΩΡΙΣΗΣ ΦΩΝΗΣ (STT)
def listen():
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
    if not filename.endswith('.pdf'):
        filename += '.pdf'
        
    # --- Η ΜΑΓΙΚΗ ΔΙΟΡΘΩΣΗ ΓΙΑ ΤΑ ΠΑΘΣ ---
    # Βρίσκει τον φάκελο που βρίσκεται ΑΥΤΟ το αρχείο python (assistant_final.py)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    # Φτιάχνει το πλήρες path για το PDF (π.χ. C:\...\VOICE_ASSISTANT_LOCAL\baseis.pdf)
    file_path = os.path.join(script_dir, filename)

    if not os.path.exists(file_path):
        print(f"❌ Το αρχείο '{filename}' δεν βρέθηκε. Βεβαιώσου ότι είναι στον ίδιο φάκελο με τον κώδικα.")
        return None

    print(f"📄 Διαβάζω το αρχείο: {filename}...")
    text_content = ""
    try:
        # Προσοχή: Ανοίγουμε το file_path, όχι σκέτο το filename
        with open(file_path, 'rb') as file:
            pdf_reader = PyPDF2.PdfReader(file)
            for page in pdf_reader.pages:
                extracted = page.extract_text()
                if extracted:
                    text_content += extracted + "\n"
        print(f"✅ Το αρχείο '{filename}' διαβάστηκε επιτυχώς!")
        return text_content
    except Exception as e:
        print(f"❌ Σφάλμα κατά την ανάγνωση: {e}")
        return None

# 4. ΣΥΝΑΡΤΗΣΗ ΕΠΙΚΟΙΝΩΝΙΑΣ ΜΕ AI
def chat_with_ollama(user_text, restrict_to_pdf=False):
    global conversation_history, current_pdf_text
    
    if restrict_to_pdf:
        # Διορθωμένο Prompt για ΠΟΛΛΑ αρχεία
        message_content = (
            f"ΟΔΗΓΙΑ: Απάντησε ΑΥΣΤΗΡΑ ΚΑΙ ΜΟΝΟ με βάση τα παρακάτω κείμενα εγγράφων. "
            f"Αν η πληροφορία δεν υπάρχει, πες 'Δεν υπάρχει στα αρχεία'.\n\n"
            f"ΚΕΙΜΕΝΑ ΑΡΧΕΙΩΝ:\n{current_pdf_text}\n\n"
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
        "options": { 
            "temperature": 0.3,
            "num_ctx": 16384  # ΝΕΟ: Μεγάλο παράθυρο μνήμης (16k) για να χωράνε πολλά PDF
        }
    }
    
    try:
        response = requests.post(url, json=payload)
        if response.status_code == 200:
            ai_reply = response.json().get('message', {}).get('content', 'Σφάλμα ανάγνωσης.')
            if restrict_to_pdf:
                # Καθαρισμός του ιστορικού από τα τεράστια κείμενα
                conversation_history[-1]["content"] = user_text 
            conversation_history.append({"role": "assistant", "content": ai_reply})
            return ai_reply
        return "❌ Σφάλμα κατά την επικοινωνία με το Ollama."
    except requests.exceptions.RequestException:
        return "❌ Δεν μπόρεσα να συνδεθώ στο Ollama."

# 5. ΚΥΡΙΑ ΛΕΙΤΟΥΡΓΙΑ ΠΡΟΓΡΑΜΜΑΤΟΣ (MAIN)
def main():
    global current_pdf_text, loaded_pdfs
    print("🚀 ΕΚΚΙΝΗΣΗ LOCAL AI ΒΟΗΘΟΥ (Υποστήριξη Πολλαπλών Αρχείων)")

    while True:
        print("\n" + "-"*50)
        mode = input("⌨️ Γράψε ή πάτα ENTER για το μικρόφωνο: ")
        user_input = listen() if mode.strip() == "" else mode.lower()

        if not user_input: continue
        if any(word in user_input for word in ['έξοδος', 'σταμάτα', 'exit', 'quit']):
            print("👋 Αντίο!")
            break

        # ΝΕΟ: Εντολή για Καθαρισμό Μνήμης Αρχείων
        if any(word in user_input for word in ["καθάρισε", "καθαρισε", "ξέχασε", "ξεχασε"]) and any(word in user_input for word in ["μνήμη", "μνημη", "αρχεία", "αρχεια"]):
            current_pdf_text = ""
            loaded_pdfs = []
            print("🧹 Η μνήμη των αρχείων καθαρίστηκε! Είμαι έτοιμος για νέα έγγραφα.")
            continue

# ΛΕΞΕΙΣ-ΚΛΕΙΔΙΑ ΠΟΥ ΕΝΕΡΓΟΠΟΙΟΥΝ ΤΗΝ ΑΝΑΖΗΤΗΣΗ ΣΤΟ PDF
        pdf_triggers = [
            "σύμφωνα με", "συμφωνα με", 
            "από το αρχείο", "απο το αρχειο", "από τα αρχεία", "απο τα αρχεια",
            "ποιο αρχείο", "ποιο αρχειο", "από ποιο", "απο ποιο", # <-- ΝΕΑ ΠΡΟΣΘΗΚΗ
            "βάσει του", "βασει του", "βάσει των",
            "γνώσεις του", "γνωσεις του", 
            "περιεχόμενο", "περιεχομενο", 
            "αρχείο αυτό", "αρχειο αυτο", "αυτά τα αρχεία",
            "αυτό το αρχείο", "αυτο το αρχειο",
            "του αρχείου", "του αρχειου", "των αρχείων",
            "περίληψη", "περιληψη", "τι λέει", "τι λεει", "μέσα"
        ]
        is_pdf_request = any(phrase in user_input for phrase in pdf_triggers)

        # Α. ΕΛΕΓΧΟΣ: ΕΙΝΑΙ ΕΡΩΤΗΣΗ ΓΙΑ ΤΑ ΗΔΗ ΦΟΡΤΩΜΕΝΑ PDF;
        if is_pdf_request:
            if not current_pdf_text:
                print("❌ Δεν έχεις φορτώσει κάποιο αρχείο ακόμα. Πες π.χ. 'Διάβασε το αρχείο baseis'.")
                continue
            reply = chat_with_ollama(user_input, restrict_to_pdf=True)
            print(f"\n🤖 AI: {reply}\n")

        # Β. ΕΛΕΓΧΟΣ: ΕΙΝΑΙ ΕΝΤΟΛΗ ΓΙΑ ΦΟΡΤΩΣΗ ΝΕΟΥ ΑΡΧΕΙΟΥ;
        elif any(kw in user_input for kw in ["διάβασ", "διαβάσ", "αρχείο", "αρχειο", "φορτωσ", "φόρτωσ"]):
            words = user_input.split()
            try:
                idx = -1
                if "αρχείο" in words: idx = words.index("αρχείο")
                elif "αρχειο" in words: idx = words.index("αρχειο")
                
                if idx != -1 and idx + 1 < len(words):
                    raw_filename = words[idx + 1]
                    
                    # --- ΚΑΘΑΡΙΣΜΟΣ ΑΠΟ ΣΤΙΞΗ ---
                    # Αφαιρεί ερωτηματικά, τελείες και κόμματα για να μην μπερδεύεται
                    filename = raw_filename.strip("?;.,!")
                    
                    ignore_words = ["αυτό", "αυτο", "του", "αυτού", "αυτου", "δεν", "που", "είναι", "ειναι", "έχει", "εχει", "μου", "για", "ποιο"]
                    if filename in ignore_words:
                        if current_pdf_text:
                            reply = chat_with_ollama(user_input, restrict_to_pdf=True)
                            print(f"\n🤖 AI: {reply}\n")
                        else:
                            print("❌ Δεν έχεις φορτώσει κάποιο αρχείο ακόμα.")
                        continue

                    # --- ΝΕΑ ΛΟΓΙΚΗ (ΚΑΙ ΓΙΑ ΚΟΛΛΗΤΕΣ ΛΕΞΕΙΣ) ---
                    next_word = words[idx + 2].strip("?;.,!") if idx + 2 < len(words) else ""

                    # Πιάσιμο κολλητών λέξεων (π.χ. "βασεισ2")
                    if filename in ["βάσεις2", "βασεις2", "βασεισ2", "baseis2"]:
                        filename = "baseis2"
                    elif filename in ["βάσεις3", "βασεις3", "βασεισ3", "baseis3"]:
                        filename = "baseis3"
                    elif filename in ["βάσεις", "βασεις", "βασεισ", "βάσεισ", "βάσ", "βασ", "baseis"]:
                        if next_word in ["2", "δύο", "δυο"]:
                            filename = "baseis2"
                        elif next_word in ["3", "τρία", "τρια"]:
                            filename = "baseis3"
                        else:
                            filename = "baseis"
                    # ----------------------------------------
                    
                    if filename in loaded_pdfs:
                        print(f"⚠️ Το αρχείο '{filename}' είναι ήδη φορτωμένο στη μνήμη!")
                    else:
                        new_text = read_pdf(filename)
                        if new_text:
                            current_pdf_text += f"\n\n--- ΠΗΓΗ ΑΡΧΕΙΟΥ: {filename} ---\n{new_text}"
                            loaded_pdfs.append(filename)
                            print(f"📚 Συνολικά φορτωμένα αρχεία ({len(loaded_pdfs)}): {', '.join(loaded_pdfs)}")
                continue 
            except:
                continue

        # Γ. ΚΑΝΟΝΙΚΗ ΣΥΖΗΤΗΣΗ
        else:
            reply = chat_with_ollama(user_input, restrict_to_pdf=False)
            print(f"\n🤖 AI: {reply}\n")

if __name__ == "__main__":
    main()


#ΟΔΗΓΙΕΣ
#Λες: "Διάβασε το αρχείο baseis" -> Το φορτώνει.

#Λες: "Διάβασε το αρχείο sql" -> Το φορτώνει και το προσθέτει στο προηγούμενο. Σου βγάζει μήνυμα: 📚 Συνολικά φορτωμένα αρχεία (2): baseis, sql.

#Λες: "Κάνε μου ερωτήσεις σύμφωνα με τα αρχεία" -> Το AI θα ψάξει και θα συνδυάσει πληροφορίες και από τα δύο!

#Αν γεμίσεις τη μνήμη ή θες να αλλάξεις μάθημα, λες: "Καθάρισε τα αρχεία" και η μνήμη αδειάζει για να ξεκινήσεις από την αρχή.