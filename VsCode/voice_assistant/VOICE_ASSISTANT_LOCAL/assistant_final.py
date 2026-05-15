from flask import Flask, request, jsonify, render_template, send_from_directory
import speech_recognition as sr
import os
import fitz  # PyMuPDF
import requests
import re
import webbrowser
from threading import Timer

app = Flask(__name__)

# ==========================================
# 1. ΚΑΘΟΛΙΚΕΣ ΜΕΤΑΒΛΗΤΕΣ & ΟΔΗΓΙΕΣ
# ==========================================
system_prompt = {
    "role": "system", 
    "content": (
        "Είσαι ένας έξυπνος βοηθός. Έχεις τη δυνατότητα να διαβάζεις αρχεία PDF. "
        "Πρέπει να απαντάς σε άπταιστα Ελληνικά. Αν δεν γνωρίζεις κάτι, πες 'Δεν γνωρίζω'."
    )
}
conversation_history = [system_prompt]
loaded_pdfs = {}  # Λεξικό με ΟΛΑ τα αρχεία
awaiting_global_search = False
last_pdf_question = ""
last_target_file = None  # Κρατάει στη μνήμη το τελευταίο ενεργό αρχείο για follow-up ερωτήσεις

# ==========================================
# 2. ΒΑΣΙΚΕΣ ΣΥΝΑΡΤΗΣΕΙΣ
# ==========================================
def listen():
    recognizer = sr.Recognizer()
    recognizer.pause_threshold = 2.0 
    with sr.Microphone() as source:
        print("\n🎤 Ακούω...")
        recognizer.adjust_for_ambient_noise(source, duration=1)
        audio = recognizer.listen(source)
    try:
        text = recognizer.recognize_google(audio, language='el-GR')
        print(f"Εσύ: {text}")
        return text.lower()
    except sr.UnknownValueError:
        print("Δεν κατάλαβα τι είπες.")
        return None
    except sr.RequestError:
        print("Σφάλμα σύνδεσης στο ίντερνετ.")
        return None

def read_pdf(filename):
    if not filename.endswith('.pdf'):
        filename += '.pdf'
    script_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(script_dir, "database", filename)
    if not os.path.exists(file_path):
        print(f"Το αρχείο '{filename}' δεν βρέθηκε.")
        return None
    print(f"Διαβάζω το αρχείο: {filename}...")
    text_content = ""
    try:
        doc = fitz.open(file_path)
        for page in doc:
            # Εισάγουμε ετικέτα σελίδας για να γνωρίζει το AI τους αριθμούς σελίδων
            text_content += f"\n--- ΣΕΛΙΔΑ {page.number + 1} ---\n"
            text_content += page.get_text()
        doc.close()
        if not text_content.strip():
            return None
        print(f"Το αρχείο '{filename}' διαβάστηκε επιτυχώς!")
        return text_content
    except Exception as e:
        print(f"Σφάλμα κατά την ανάγνωση: {e}")
        return None

def chat_with_ollama(user_text, restrict_to_pdf=False, custom_context="", target_file_name=None):
    global conversation_history
    
    # Κρατάμε καθαρό το ιστορικό συνομιλίας
    conversation_history.append({"role": "user", "content": user_text})
    
    if restrict_to_pdf:
        if target_file_name:
            # Προσθήκη ειδικών φίλτρων για αποφυγή ορων ιατρικής φύσεως και σωστή ανάγνωση σελίδων
            system_content = (
                f"Είσαι ένας αυστηρός αναλυτής εγγράφων και βοηθός μελέτης.\n"
                f"Απαντάς στις ερωτήσεις του χρήστη ΑΠΟΚΛΕΙΣΤΙΚΑ ΚΑΙ ΜΟΝΟ με βάση το παρακάτω κείμενο του αρχείου {target_file_name}.\n"
                f"1. Αν βρεις την πληροφορία, ξεκίνα την απάντησή σου ΠΑΝΤΑ με τη φράση: 'Βάσει του αρχείου {target_file_name}:'.\n"
                f"2. ΑΠΑΓΟΡΕΥΕΤΑΙ να χρησιμοποιήσεις οποιαδήποτε εξωτερική γνώση.\n"
                f"3. ΠΡΟΣΟΧΗ ΣΤΙΣ ΟΜΩΝΥΜΙΕΣ: Ο όρος 'ασθενής τύπος οντοτήτων' αναφέρεται αποκλειστικά σε Weak Entity (Βάσεις Δεδομένων). ΑΠΑΓΟΡΕΥΕΤΑΙ αυστηρά να επινοήσεις ιατρικούς όρους (γιατρούς, φάρμακα, δόσεις) αν δεν αναγράφονται ρητά στο κείμενο!\n"
                f"4. Όταν ο χρήστης σε ρωτάει για σελίδες, εντόπισε στο κείμενο την πλησιέστερη ετικέτα '--- ΣΕΛΙΔΑ Χ ---' και ανάφερε αυτόν τον αριθμό.\n"
                f"5. ΑΝ Η ΠΛΗΡΟΦΟΡΙΑ ΔΕΝ ΥΠΑΡΧΕΙ ΜΕΣΑ ΣΤΟ ΚΕΙΜΕΝΟ, ΑΠΑΝΤΗΣΕ ΥΠΟΧΡΕΩΤΙΚΑ ΜΟΝΟ ΜΕ ΤΗ ΛΕΞΗ: NOT_FOUND\n\n"
                f"ΚΕΙΜΕΝΟ ΑΡΧΕΙΟΥ {target_file_name}:\n\"\"\"\n{custom_context}\n\"\"\""
            )
        else:
            system_content = (
                f"Είσαι ένας αυστηρός αναλυτής εγγράφων και βοηθός μελέτης.\n"
                f"Απαντάς χρησιμοποιώντας ΑΠΟΚΛΕΙΣΤΙΚΑ πληροφορίες που είναι γραμμένες στα παρακάτω κείμενα της βάσης δεδομένων.\n"
                f"1. ΑΠΑΓΟΡΕΥΕΤΑΙ να χρησιμοποιήσεις εξωτερικές γνώσεις.\n"
                f"2. Αν η πληροφορία δεν υπάρχει σε κανένα αρχείο, απάντα ακριβώς: 'Δεν βρέθηκαν πληροφορίες στα φορτωμένα αρχεία'.\n"
                f"3. Στο ΤΕΛΟΣ της απάντησής σου, γράψε υποχρεωτικά τις πηγές με τη μορφή: 'Πηγές: [ονόματα αρχείων]'.\n\n"
                f"ΚΕΙΜΕΝΑ ΑΡΧΕΙΩΝ DATABASE:\n\"\"\"\n{custom_context}\n\"\"\""
            )
            
        messages_to_send = [{"role": "system", "content": system_content}]
        for msg in conversation_history:
            if msg["role"] != "system":
                messages_to_send.append(msg)
    else:
        messages_to_send = conversation_history

    print("Σκέφτομαι...")
    url = "http://localhost:11434/api/chat"
    payload = {
        "model": "llama3.1", 
        "messages": messages_to_send,
        "stream": False,
        "options": { "temperature": 0.0, "num_ctx": 16384 }
    }
    
    try:
        response = requests.post(url, json=payload)
        if response.status_code == 200:
            ai_reply = response.json().get('message', {}).get('content', 'Σφάλμα ανάγνωσης.')
            
            if restrict_to_pdf and target_file_name and "not_found" in ai_reply.lower():
                fallback_msg = f"Στο αρχείο {target_file_name} δεν βρέθηκαν πληροφορίες για αυτό, αλλά μπορώ να ψάξω στα υπόλοιπα αρχεία του database για να σου δώσω απάντηση. Θέλεις να το κάνω;"
                conversation_history.append({"role": "assistant", "content": fallback_msg})
                return fallback_msg
                
            conversation_history.append({"role": "assistant", "content": ai_reply})
            return ai_reply
        conversation_history.pop()
        return "Σφάλμα κατά την επικοινωνία με το Ollama."
    except requests.exceptions.RequestException:
        conversation_history.pop()
        return "Δεν μπόρεσα να συνδεθώ στο Ollama."

def get_filename_from_input(user_input):
    if "βασ" in user_input or "bas" in user_input:
        match = re.search(r'\d+', user_input)
        if match: return f"baseis{match.group()}"
        word_to_num = {"ένα": "1", "ενα": "1", "δύο": "2", "δυο": "2", "τρία": "3", "τρια": "3", "τέσσερα": "4", "τεσσερα": "4", "πέντε": "5", "πεντε": "5", "έξι": "6", "εξι": "6", "επτά": "7", "επτα": "7", "οκτώ": "8", "οκτω": "8", "εννέα": "9", "εννεα": "9", "δέκα": "10", "δεκα": "10"}
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

# ==========================================
# 3. ΛΕΙΤΟΥΡΓΙΑ WEB UI (FLASK ROUTES)
# ==========================================
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/pdf/<filename>')
def serve_pdf(filename):
    if not filename.endswith('.pdf'): filename += '.pdf'
    script_dir = os.path.dirname(os.path.abspath(__file__))
    return send_from_directory(os.path.join(script_dir, "database"), filename)

@app.route('/new_chat', methods=['POST'])
def new_chat():
    global conversation_history, awaiting_global_search, last_target_file
    conversation_history = [system_prompt]
    awaiting_global_search = False
    last_target_file = None
    return jsonify({"status": "ok"})

@app.route('/chat', methods=['POST'])
def process_request():
    global loaded_pdfs, awaiting_global_search, last_pdf_question, last_target_file
    
    data = request.json
    is_voice = data.get('is_voice', False)
    
    if is_voice:
        user_input = listen()
        if not user_input:
            return jsonify({"reply": "Δεν μπόρεσα να ακούσω τι είπες. Δοκίμασε ξανά.", "loaded_files": sorted(list(loaded_pdfs.keys()))})
    else:
        user_input = data.get('text', '').lower()

    reply = ""

    if awaiting_global_search:
        if any(w in user_input for w in ["ναι", "αμε", "ψάξε", "ψαξε", "καντο", "κάντο", "οκ", "νι"]):
            awaiting_global_search = False
            context = "\n\n".join([f"--- ΠΗΓΗ ΑΡΧΕΙΟΥ: {k} ---\n{v}" for k, v in loaded_pdfs.items()])
            reply = chat_with_ollama(last_pdf_question, restrict_to_pdf=True, custom_context=context)
        else:
            awaiting_global_search = False
            reply = "ΟΚ, ακυρώθηκε η αναζήτηση στα άλλα αρχεία."

    elif any(phrase in user_input for phrase in ["σύμφωνα με", "συμφωνα με", "από το αρχείο", "απο το αρχειο", "από τα αρχεία", "απο τα αρχεια", "βάσει", "βασει", "τι λέει", "τι λεει", "περίληψη", "περιληψη"]):
        if not loaded_pdfs:
            reply = "Δεν έχεις φορτώσει κάποιο αρχείο ακόμα. Πες π.χ. 'Διάβασε το αρχείο baseis'."
        else:
            target_file = get_filename_from_input(user_input)
            if target_file and target_file in loaded_pdfs:
                last_target_file = target_file
                context = f"--- ΠΗΓΗ ΑΡΧΕΙΟΥ: {target_file} ---\n{loaded_pdfs[target_file]}"
                reply = chat_with_ollama(user_input, restrict_to_pdf=True, custom_context=context, target_file_name=target_file)
                
                if "στα υπόλοιπα αρχεία" in reply:
                    awaiting_global_search = True
                    clean_q = user_input
                    for phrase in ["σύμφωνα με", "συμφωνα με", "από το αρχείο", "απο το αρχειο", "βάσει", "βασει", "τι λέει", "τι λεει", "περίληψη", "περιληψη"]:
                        clean_q = clean_q.replace(phrase, "")
                    if target_file:
                        clean_q = clean_q.replace(target_file, "")
                    clean_q = clean_q.strip()
                    last_pdf_question = f"Σύμφωνα με τα αρχεία, {clean_q}"
            else:
                context = "\n\n".join([f"--- ΠΗΓΗ ΑΡΧΕΙΟΥ: {k} ---\n{v}" for k, v in loaded_pdfs.items()])
                reply = chat_with_ollama(user_input, restrict_to_pdf=True, custom_context=context)

    elif any(w in user_input for w in ["ποια", "τι", "ποιο", "πού", "που"]) and any(w in user_input for w in ["αρχεία", "αρχεια", "pdf", "βρήκες", "βρηκες"]):
        if loaded_pdfs:
            reply = f"Έχω φορτωμένα {len(loaded_pdfs)} αρχεία: {', '.join(loaded_pdfs.keys())}"
        else:
            reply = "Δεν έχω κανένα αρχείο φορτωμένο στη μνήμη μου αυτή τη στιγμή."

    elif any(w in user_input for w in ["καθάρισε", "καθαρισε", "άδειασε", "αδειασε"]) and any(w in user_input for w in ["μνήμη", "μνημη", "όλα", "ολα"]):
        loaded_pdfs.clear()
        last_target_file = None
        reply = "Η μνήμη καθαρίστηκε πλήρως! Έβγαλα όλα τα αρχεία."

    elif any(w in user_input for w in ["βγάλε", "βγαλε", "αφαίρεσε", "αφαιρεσε", "διέγραψε", "διεγραψε", "σβήσε", "σβησε", "διάγραψε", "διαγραψε"]):
        fname = get_filename_from_input(user_input)
        if fname and fname in loaded_pdfs:
            del loaded_pdfs[fname]
            if fname == last_target_file:
                last_target_file = None
            reply = f"🗑️ Το αρχείο '{fname}' αφαίρεθηκε από τη μνήμη. Απομένουν ({len(loaded_pdfs)})."
        else:
            reply = f"Το αρχείο δεν βρέθηκε στη μνήμη."

    elif any(kw in user_input for kw in ["όλα", "ολα"]) and any(kw in user_input for kw in ["διάβασ", "διαβασ"]):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        db_path = os.path.join(script_dir, "database")
        count = 0
        if os.path.exists(db_path):
            for f in [x for x in os.listdir(db_path) if x.endswith('.pdf')]:
                name = f.replace('.pdf', '')
                if name not in loaded_pdfs:
                    content = read_pdf(name)
                    if content:
                        loaded_pdfs[name] = content
                        count += 1
        reply = f"Φορτώθηκαν επιτυχώς {count} νέα αρχεία! (Συνολικά: {len(loaded_pdfs)})"

    elif any(kw in user_input for kw in ["διάβασ", "διαβασ", "αρχείο", "αρχειο", "φορτωσ", "φόρτωσ"]):
        fname = get_filename_from_input(user_input)
        if fname:
            if fname in loaded_pdfs:
                reply = f"Το αρχείο '{fname}' είναι ήδη φορτωμένο."
            else:
                content = read_pdf(fname)
                if content:
                    loaded_pdfs[fname] = content
                    reply = f"Το αρχείο {fname} διαβάστηκε και φορτώθηκε επιτυχώς!"
                else:
                    reply = f"Δεν βρέθηκε το αρχείο {fname}."
        else:
            reply = chat_with_ollama(user_input, restrict_to_pdf=False)
            
    else:
        if last_target_file and last_target_file in loaded_pdfs:
            context = f"--- ΠΗΓΗ ΑΡΧΕΙΟΥ: {last_target_file} ---\n{loaded_pdfs[last_target_file]}"
            reply = chat_with_ollama(user_input, restrict_to_pdf=True, custom_context=context, target_file_name=last_target_file)
        else:
            reply = chat_with_ollama(user_input, restrict_to_pdf=False)

    return jsonify({"reply": reply, "loaded_files": sorted(list(loaded_pdfs.keys()))})

# ==========================================
# 4. ΕΚΚΙΝΗΣΗ
# ==========================================
if __name__ == "__main__":
    print("==================================================")
    print("ΚΑΛΩΣ ΗΡΘΕΣ ΣΤΟΝ ΠΡΟΣΩΠΙΚΟ ΣΟΥ AI ΒΟΗΘΟ!")
    print("==================================================")
    print("\n🌐 Ξεκινάει ο Web Server! Ανοίγει αυτόματα ο browser σου...")
    Timer(1.5, lambda: webbrowser.open("http://127.0.0.1:5000/")).start()
    app.run(debug=False, port=5000)

# ΟΔΗΓΙΕΣ ΧΡΗΣΗΣ
# 🔹 ΦΟΡΤΩΣΗ 1: "Διάβασε το αρχείο βάσεις 4" -> Θα φορτώσει το baseis4.pdf
# 🔹 ΦΟΡΤΩΣΗ ΟΛΩΝ: "Διάβασε όλα τα αρχεία" -> Φορτώνει αυτόματα ΟΛΑ τα PDF από τον φάκελο database.
# 🔹 ΑΦΑΙΡΕΣΗ 1: "Βγάλε από τη μνήμη σου το βάσεις 2" -> Το διαγράφει από τη μνήμη, τα υπόλοιπα παραμένουν!
# 🔹 ΚΑΘΑΡΙΣΜΟΣ: "Άδειασε όλα τα αρχεία" (ή "Καθάρισε τη μνήμη") -> Σβήνει τα πάντα.
# 🔹 ΕΡΩΤΗΣΗ: "Κάνε μου μια περίληψη σύμφωνα με το αρχείο" -> Απαντάει βάσει όσων αρχείων έχουν μείνει στη μνήμη.
# 🔹 ΠΗΓΕΣ: Αν ρωτήσεις "Από ποιο αρχείο βρήκες τις πληροφορίες;", θα σου δώσει απευθείας τη λίστα!