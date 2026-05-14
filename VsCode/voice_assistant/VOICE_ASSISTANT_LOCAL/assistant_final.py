import speech_recognition as sr
import os
import fitz  # PyMuPDF
import requests
import re

# 1. ΚΑΘΟΛΙΚΕΣ ΜΕΤΑΒΛΗΤΕΣ & ΣΥΣΤΗΜΑ ΟΔΗΓΙΩΝ
conversation_history = [
    {
        "role": "system", 
        "content": (
            "Είσαι ένας έξυπνος βοηθός. Έχεις τη δυνατότητα να διαβάζεις αρχεία PDF. "
            "Πρέπει να απαντάς σε άπταιστα Ελληνικά. Αν δεν γνωρίζεις κάτι, πες 'Δεν γνωρίζω'."
        )
    }
]
loaded_pdfs = {}  # Λεξικό με ΟΛΑ τα αρχεία

# ΜΕΤΑΒΛΗΤΕΣ ΓΙΑ ΤΗΝ "ΕΞΥΠΝΗ ΜΝΗΜΗ"
awaiting_global_search = False
last_pdf_question = ""

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

# 3. ΣΥΝΑΡΤΗΣΗ ΑΝΑΓΝΩΣΗΣ PDF (FITZ)
def read_pdf(filename):
    if not filename.endswith('.pdf'):
        filename += '.pdf'
    script_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(script_dir, "database", filename)
    if not os.path.exists(file_path):
        print(f"❌ Το αρχείο '{filename}' δεν βρέθηκε.")
        return None
    print(f"📄 Διαβάζω το αρχείο: {filename}...")
    text_content = ""
    try:
        doc = fitz.open(file_path)
        for page in doc:
            text_content += page.get_text()
        doc.close()
        if not text_content.strip():
            return None
        print(f"✅ Το αρχείο '{filename}' διαβάστηκε επιτυχώς!")
        return text_content
    except Exception as e:
        print(f"❌ Σφάλμα κατά την ανάγνωση: {e}")
        return None

# 4. ΣΥΝΑΡΤΗΣΗ ΕΠΙΚΟΙΝΩΝΙΑΣ ΜΕ AI (ΔΙΟΡΘΩΜΕΝΗ ΓΙΑ ΑΠΟΛΥΤΗ ΑΚΡΙΒΕΙΑ)
def chat_with_ollama(user_text, restrict_to_pdf=False, custom_context="", target_file_name=None):
    global conversation_history
    
    if restrict_to_pdf:
        if target_file_name:
            # ΟΔΗΓΙΑ ΓΙΑ ΣΥΓΚΕΚΡΙΜΕΝΟ ΑΡΧΕΙΟ - ΠΟΛΥ ΑΥΣΤΗΡΗ
            message_content = (
                f"ΕΙΣΑΙ ΕΝΑ ΡΟΜΠΟΤ ΧΩΡΙΣ ΔΙΚΗ ΤΟΥ ΜΝΗΜΗ. Απάντησε ΑΥΣΤΗΡΑ ΚΑΙ ΜΟΝΟ με βάση το κείμενο του αρχείου {target_file_name} που ακολουθεί.\n"
                f"Στην ΑΡΧΗ της απάντησής σου, γράψε ΠΑΝΤΑ: 'Βάσει του αρχείου {target_file_name}:'.\n"
                f"ΚΑΝΟΝΑΣ: Αν το κείμενο δεν περιέχει ΕΤΟΙΜΟ ΠΑΡΑΔΕΙΓΜΑ ΚΩΔΙΚΑ, ΑΠΑΓΟΡΕΥΕΤΑΙ να επινοήσεις δικό σου.\n"
                f"Αν η πληροφορία ΔΕΝ υπάρχει μέσα, πες ΑΚΡΙΒΩΣ: "
                f"'Στο αρχείο {target_file_name} δεν βρέθηκαν πληροφορίες για αυτό, αλλά μπορώ να ψάξω στα υπόλοιπα αρχεία του database για να σου δώσω απάντηση. Θέλεις να το κάνω;'\n\n"
                f"ΚΕΙΜΕΝΟ ΑΡΧΕΙΟΥ:\n{custom_context}\n\n"
                f"ΕΡΩΤΗΣΗ: {user_text}"
            )
        else:
            # ΟΔΗΓΙΑ ΓΙΑ ΓΕΝΙΚΗ ΑΝΑΖΗΤΗΣΗ ΣΕ ΟΛΑ ΤΑ ΑΡΧΕΙΑ
            message_content = (
                f"Απάντησε χρησιμοποιώντας ΑΠΟΚΛΕΙΣΤΙΚΑ τα παρακάτω κείμενα εγγράφων. Μην χρησιμοποιείς εξωτερικές γνώσεις.\n"
                f"Στο ΤΕΛΟΣ της απάντησής σου, γράψε ΟΠΩΣΔΗΠΟΤΕ: 'Πηγές: [ονόματα αρχείων]'.\n\n"
                f"ΚΕΙΜΕΝΑ ΑΡΧΕΙΩΝ:\n{custom_context}\n\n"
                f"ΕΡΩΤΗΣΗ: {user_text}"
            )
        
        # ΑΠΟΜΟΝΩΣΗ: Στέλνουμε μόνο το System Prompt και την τρέχουσα ερώτηση (Χωρίς ιστορικό)
        messages_to_send = [conversation_history[0], {"role": "user", "content": message_content}]
    else:
        conversation_history.append({"role": "user", "content": user_text})
        messages_to_send = conversation_history

    print("🧠 Σκέφτομαι...")
    url = "http://localhost:11434/api/chat"
    
    payload = {
        "model": "llama3.1", 
        "messages": messages_to_send,
        "stream": False,
        "options": { 
            "temperature": 0.0,  # Μηδενική δημιουργικότητα για αποφυγή ψευδαισθήσεων
            "num_ctx": 16384
        }
    }
    
    try:
        response = requests.post(url, json=payload)
        if response.status_code == 200:
            ai_reply = response.json().get('message', {}).get('content', 'Σφάλμα ανάγνωσης.')
            
            # Αν είναι γενική κουβέντα, κρατάμε το ιστορικό.
            # Αν είναι PDF search, ΔΕΝ το αποθηκεύουμε στο ιστορικό για να μην επηρεάσει την επόμενη ερώτηση.
            if not restrict_to_pdf:
                conversation_history.append({"role": "assistant", "content": ai_reply})
            return ai_reply
        return "❌ Σφάλμα κατά την επικοινωνία με το Ollama."
    except requests.exceptions.RequestException:
        return "❌ Δεν μπόρεσα να συνδεθώ στο Ollama."

# --- ΒΟΗΘΗΤΙΚΗ ΣΥΝΑΡΤΗΣΗ ΕΥΡΕΣΗΣ ΑΡΧΕΙΟΥ ---
def get_filename_from_input(user_input):
    if "βασ" in user_input or "bas" in user_input:
        match = re.search(r'\d+', user_input)
        if match: return f"baseis{match.group()}"
        
        word_to_num = {
            "ένα": "1", "ενα": "1", "δύο": "2", "δυο": "2", "τρία": "3", "τρια": "3",
            "τέσσερα": "4", "τεσσερα": "4", "πέντε": "5", "πεντε": "5", "έξι": "6", "εξι": "6",
            "επτά": "7", "επτα": "7", "οκτώ": "8", "οκτω": "8", "εννέα": "9", "εννεα": "9",
            "δέκα": "10", "δεκα": "10", "έντεκα": "11", "εντεκα": "11", "δώδεκα": "12", "δωδεκα": "12"
        }
        for word, num in word_to_num.items():
            if word in user_input.split():
                return f"baseis{num}"
        return "baseis"
    
    words = user_input.split()
    idx = -1
    if "αρχείο" in words: idx = words.index("αρχείο")
    elif "αρχειο" in words: idx = words.index("αρχειο")
    
    if idx != -1 and idx + 1 < len(words): return words[idx + 1].strip("?;.,!")
    return None

# 5. ΚΥΡΙΑ ΛΕΙΤΟΥΡΓΙΑ ΠΡΟΓΡΑΜΜΑΤΟΣ (MAIN)
def main():
    global loaded_pdfs
    global awaiting_global_search, last_pdf_question
    print("🚀 ΕΚΚΙΝΗΣΗ LOCAL AI ΒΟΗΘΟΥ (V4 - Final Accuracy)")

    while True:
        print("\n" + "-"*50)
        mode = input("⌨️ Γράψε ή πάτα ENTER για το μικρόφωνο: ")
        user_input = listen() if mode.strip() == "" else mode.lower()

        if not user_input: continue
        if any(word in user_input for word in ['έξοδος', 'σταμάτα', 'exit', 'quit']):
            print("👋 Αντίο!")
            break

        # ΛΟΓΙΚΗ ΓΙΑ ΤΟ "ΝΑΙ, ΨΑΞΕ"
        if awaiting_global_search:
            if any(w in user_input for w in ["ναι", "αμε", "ψάξε", "ψαξε", "καντο", "κάντο", "οκ", "νι"]):
                print("🔍 Ψάχνω αυτόματα σε ΟΛΑ τα φορτωμένα αρχεία...")
                awaiting_global_search = False
                
                context_to_send = ""
                for k, v in loaded_pdfs.items():
                    context_to_send += f"\n\n--- ΠΗΓΗ ΑΡΧΕΙΟΥ: {k} ---\n{v}"
                    
                reply = chat_with_ollama(last_pdf_question, restrict_to_pdf=True, custom_context=context_to_send, target_file_name=None)
                print(f"\n🤖 AI: {reply}\n")
                continue
            else:
                awaiting_global_search = False

        # ΕΛΕΓΧΟΣ ΜΝΗΜΗΣ
        if any(w in user_input for w in ["ποια", "τι", "πού", "που"]) and any(w in user_input for w in ["αρχεία", "pdf", "βρήκες", "βρηκες", "μνήμη", "μνημη"]):
            if loaded_pdfs:
                print(f"\n🤖 AI: Έχω φορτωμένα {len(loaded_pdfs)} αρχεία: {', '.join(loaded_pdfs.keys())}\n")
            else:
                print("\n🤖 AI: Η μνήμη μου είναι άδεια.\n")
            continue

        # ΚΑΘΑΡΙΣΜΟΣ
        if any(w in user_input for w in ["καθάρισε", "καθαρισε", "άδειασε", "αδειασε"]) and any(w in user_input for w in ["μνήμη", "μνημη", "όλα", "ολα"]):
            loaded_pdfs.clear(); print("🧹 Μνήμη καθαρή."); continue

        # ΑΦΑΙΡΕΣΗ
        if any(w in user_input for w in ["βγάλε", "βγαλε", "σβήσε", "σβησε", "διέγραψε", "διεγραψε"]):
            fname = get_filename_from_input(user_input)
            if fname and fname in loaded_pdfs:
                del loaded_pdfs[fname]
                print(f"🗑️ Αφαιρέθηκε το '{fname}'. Απομένουν ({len(loaded_pdfs)}): {', '.join(loaded_pdfs.keys())}")
                continue

        # ΦΟΡΤΩΣΗ ΟΛΩΝ
        if any(kw in user_input for kw in ["όλα", "ολα"]) and any(kw in user_input for kw in ["διάβασ", "διαβασ"]):
            script_dir = os.path.dirname(os.path.abspath(__file__))
            db_path = os.path.join(script_dir, "database")
            if os.path.exists(db_path):
                all_files = [f for f in os.listdir(db_path) if f.endswith('.pdf')]
                count = 0
                for f in all_files:
                    name = f.replace('.pdf', '')
                    if name not in loaded_pdfs:
                        content = read_pdf(name)
                        if content:
                            loaded_pdfs[name] = content
                            count += 1
                print(f"📚 Φορτώθηκαν επιτυχώς {count} νέα αρχεία! (Συνολικά: {len(loaded_pdfs)})")
            continue

        # ΕΡΩΤΗΣΗ ΓΙΑ ΤΑ PDF
        pdf_triggers = ["σύμφωνα με", "συμφωνα με", "από το αρχείο", "απο το αρχειο", "βάσει", "βασει", "τι λέει", "τι λεει", "περίληψη", "περιληψη"]
        if any(phrase in user_input for phrase in pdf_triggers):
            if not loaded_pdfs:
                print("❌ Φόρτωσε πρώτα ένα αρχείο."); continue
                
            target_file = get_filename_from_input(user_input)
            if target_file and target_file in loaded_pdfs:
                print(f"🎯 Ψάχνω ΑΠΟΚΛΕΙΣΤΙΚΑ στο '{target_file}'...")
                context = f"--- ΠΗΓΗ ΑΡΧΕΙΟΥ: {target_file} ---\n{loaded_pdfs[target_file]}"
                reply = chat_with_ollama(user_input, restrict_to_pdf=True, custom_context=context, target_file_name=target_file)
                
                if "στα υπόλοιπα αρχεία" in reply:
                    awaiting_global_search = True
                    last_pdf_question = user_input.replace(target_file, "").replace("από το αρχείο", "").replace("απο το αρχειο", "")
                    last_pdf_question = f"Σύμφωνα με τα αρχεία, {last_pdf_question}"
                print(f"\n🤖 AI: {reply}\n")
            else:
                print("🔍 Ψάχνω σε όλη τη βάση δεδομένων...")
                context = "\n\n".join([f"--- ΠΗΓΗ: {k} ---\n{v}" for k, v in loaded_pdfs.items()])
                reply = chat_with_ollama(user_input, restrict_to_pdf=True, custom_context=context)
                print(f"\n🤖 AI: {reply}\n")

        # ΦΟΡΤΩΣΗ ΕΝΟΣ ΑΡΧΕΙΟΥ
        elif any(kw in user_input for kw in ["διάβασ", "διαβασ", "αρχείο", "αρχειο"]):
            fname = get_filename_from_input(user_input)
            if fname:
                if fname in loaded_pdfs:
                    print(f"⚠️ Το αρχείο '{fname}' είναι ήδη φορτωμένο.")
                else:
                    content = read_pdf(fname)
                    if content:
                        loaded_pdfs[fname] = content
                        print(f"📚 Συνολικά φορτωμένα αρχεία ({len(loaded_pdfs)}): {', '.join(loaded_pdfs.keys())}")
            continue

        else:
            reply = chat_with_ollama(user_input, restrict_to_pdf=False)
            print(f"\n🤖 AI: {reply}\n")

if __name__ == "__main__":
    main()
    
# ΟΔΗΓΙΕΣ ΧΡΗΣΗΣ
# 🔹 ΦΟΡΤΩΣΗ 1: "Διάβασε το αρχείο βάσεις 4" -> Θα φορτώσει το baseis4.pdf
# 🔹 ΦΟΡΤΩΣΗ ΟΛΩΝ: "Διάβασε όλα τα αρχεία" -> Φορτώνει αυτόματα ΟΛΑ τα PDF από τον φάκελο database.
# 🔹 ΑΦΑΙΡΕΣΗ 1: "Βγάλε από τη μνήμη σου το βάσεις 2" -> Το διαγράφει από τη μνήμη, τα υπόλοιπα παραμένουν!
# 🔹 ΚΑΘΑΡΙΣΜΟΣ: "Άδειασε όλα τα αρχεία" (ή "Καθάρισε τη μνήμη") -> Σβήνει τα πάντα.
# 🔹 ΕΡΩΤΗΣΗ: "Κάνε μου μια περίληψη σύμφωνα με το αρχείο" -> Απαντάει βάσει όσων αρχείων έχουν μείνει στη μνήμη.
# 🔹 ΠΗΓΕΣ: Αν ρωτήσεις "Από ποιο αρχείο βρήκες τις πληροφορίες;", θα σου δώσει απευθείας τη λίστα!