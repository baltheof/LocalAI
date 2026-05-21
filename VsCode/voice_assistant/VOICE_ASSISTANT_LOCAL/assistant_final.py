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
# 1. ΚΑΘΟΛΙΚΕΣ ΜΕΤΑΒΛΗΤΕΣ
# ==========================================
system_prompt = {
    "role": "system",
    "content": (
        "Είσαι ένας έξυπνος βοηθός. Έχεις τη δυνατότητα να διαβάζεις αρχεία PDF. "
        "Πρέπει να απαντάς σε άπταιστα Ελληνικά. Αν δεν γνωρίζεις κάτι, πες 'Δεν γνωρίζω'."
    )
}

conversation_history   = [system_prompt]
loaded_pdfs            = {}
last_target_file       = None
awaiting_fallback      = False
last_fallback_question = ""

MAX_HISTORY_PAIRS = 10


# ==========================================
# 2. ΒΟΗΘΗΤΙΚΕΣ ΣΥΝΑΡΤΗΣΕΙΣ
# ==========================================

def trim_history():
    global conversation_history
    system = [m for m in conversation_history if m["role"] == "system"]
    rest   = [m for m in conversation_history if m["role"] != "system"]
    if len(rest) > MAX_HISTORY_PAIRS * 2:
        rest = rest[-(MAX_HISTORY_PAIRS * 2):]
    conversation_history = system + rest


def get_database_path():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(script_dir, "database")


def read_pdf(filename):
    if not filename.endswith('.pdf'):
        filename += '.pdf'
    file_path = os.path.join(get_database_path(), filename)
    if not os.path.exists(file_path):
        return None
    try:
        doc  = fitz.open(file_path)
        text = ""
        for page in doc:
            text += f"\n--- ΣΕΛΙΔΑ {page.number + 1} ---\n"
            text += page.get_text()
        doc.close()
        return text.strip() or None
    except Exception as e:
        print(f"Σφάλμα ανάγνωσης PDF '{filename}': {e}")
        return None


def load_all_database_pdfs():
    db_path = get_database_path()
    count   = 0
    if os.path.exists(db_path):
        for f in sorted(os.listdir(db_path)):
            if f.endswith('.pdf'):
                name = f.replace('.pdf', '')
                if name not in loaded_pdfs:
                    content = read_pdf(name)
                    if content:
                        loaded_pdfs[name] = content
                        count += 1
    return count


def get_filename_from_input(user_input):
    if "βασ" in user_input or "bas" in user_input:
        match = re.search(r'\d+', user_input)
        if match:
            return f"baseis{match.group()}"
        word_to_num = {
            "ένα": "1", "ενα": "1", "δύο": "2", "δυο": "2",
            "τρία": "3", "τρια": "3", "τέσσερα": "4", "τεσσερα": "4",
            "πέντε": "5", "πεντε": "5", "έξι": "6", "εξι": "6",
            "επτά": "7", "επτα": "7", "οκτώ": "8", "οκτω": "8",
            "εννέα": "9", "εννεα": "9", "δέκα": "10", "δεκα": "10"
        }
        for word, num in word_to_num.items():
            if word in user_input.split():
                return f"baseis{num}"
        return "baseis"
    words = user_input.split()
    for kw in ["αρχείο", "αρχειο"]:
        if kw in words:
            idx = words.index(kw)
            if idx + 1 < len(words):
                return words[idx + 1].strip("?;.,!")
    return None


def call_ollama(messages):
    url     = "http://localhost:11434/api/chat"
    payload = {
        "model": "llama3.1:8b",
        "messages": messages,
        "stream":   False,
        "options":  {"temperature": 0.0, "num_ctx": 16384}
    }
    try:
        r = requests.post(url, json=payload)
        if r.status_code == 200:
            return r.json().get("message", {}).get("content", "Σφάλμα ανάγνωσης.")
        return "Σφάλμα κατά την επικοινωνία με το Ollama."
    except requests.exceptions.RequestException:
        return "Δεν μπόρεσα να συνδεθώ στο Ollama."


# ==========================================
# 3. ΚΕΝΤΡΙΚΗ ΛΟΓΙΚΗ ΑΠΑΝΤΗΣΗΣ ΑΠΟ PDF
# ==========================================

def check_topic_in_single_file(question: str, filename: str, text: str) -> bool:
    system_content = (
        "Είσαι ένας ελεγκτής κειμένου. "
        "Απάντησε ΜΟΝΟ με YES ή NO — τίποτα άλλο.\n"
        "YES = η έννοια ή η λέξη υπάρχει στο κείμενο με οποιαδήποτε μορφή "
        "(κεφαλαία, πεζά, συνώνυμο, ή σχετική αναφορά).\n"
        "NO  = δεν υπάρχει καμία σχετική αναφορά πουθενά στο κείμενο.\n\n"
        f"ΚΕΙΜΕΝΟ ({filename}):\n\"\"\"\n{text}\n\"\"\""
    )
    messages = [
        {"role": "system", "content": system_content},
        {"role": "user",   "content": f"Υπάρχει στο κείμενο κάτι σχετικό με το θέμα της ερώτησης; Ερώτηση: {question}"}
    ]
    raw = call_ollama(messages).strip().lower()
    print(f"  [CHECK] {filename} → '{raw}'")
    return raw.startswith("yes")


def answer_from_single_file(question: str, filename: str, text: str) -> str:

    system_content = (
        f"Είσαι αναλυτής εγγράφων. Χρησιμοποιείς ΑΠΟΚΛΕΙΣΤΙΚΑ το αρχείο: {filename}.\n\n"
        f"ΚΑΝΟΝΕΣ:\n"
        f"1. Απάντησε με δικά σου λόγια — σύντομα, καθαρά, οργανωμένα.\n"
        f"2. Τα παραδείγματα κώδικα πρέπει να είναι ΑΚΡΙΒΩΣ αυτά που υπάρχουν στο κείμενο.\n"
        f"   Αν το κείμενο έχει 'ΕΡΓΑΖΟΜΕΝΟΙ' και 'Μισθός', γράψε ΑΥΤΑ — όχι δικά σου.\n"
        f"3. Παραδείγματα: markdown code block (```sql ... ```) με κάθε clause σε νέα γραμμή.\n"
        f"4. ΑΠΑΓΟΡΕΥΕΤΑΙ η εφεύρεση πινάκων, πεδίων ή τιμών που δεν υπάρχουν στο κείμενο.\n"
        f"   ΑΠΑΓΟΡΕΥΕΤΑΙ να αναφέρεις οποιοδήποτε άλλο αρχείο εκτός του {filename}.\n"
        f"   Η πηγή στο τέλος πρέπει να είναι ΜΟΝΟ: 'Πηγή: {filename}'\n"
        f"5. ΓΡΑΨΕ ΜΟΝΟ ΟΣΑ ΠΑΡΑΔΕΙΓΜΑΤΑ ΥΠΑΡΧΟΥΝ ΣΤΟ ΚΕΙΜΕΝΟ — μην προσθέτεις επιπλέον.\n"
        f"6. Αν ζητηθεί θεωρία, γράψε ΜΟΝΟ τη θεωρία που αφορά το ερώτημα, όχι γενική θεωρία.\n"
        f"7. Στο ΤΕΛΟΣ γράψε ΥΠΟΧΡΕΩΤΙΚΑ: 'Πηγή: {filename}'\n\n"
        f"ΚΕΙΜΕΝΟ:\n\"\"\"\n{text}\n\"\"\""
    )

    messages = [{"role": "system", "content": system_content}]
    recent = [m for m in conversation_history if m["role"] != "system"][-4:]
    messages.extend(recent)
    return call_ollama(messages)


def answer_from_pdf(question: str, context_files: dict):
    """
    Ψάχνει ΟΛΑ τα αρχεία.
    Συλλέγει όλα τα αρχεία που έχουν σχετικό θέμα (YES)
    και επιστρέφει συνδυασμένη απάντηση από όλα.
    """
    matched_files = {}

    for filename, text in context_files.items():
        print(f"[SEARCH] Ψάχνω στο: {filename}")
        if check_topic_in_single_file(question, filename, text):
            print(f"[FOUND]  Βρέθηκε στο: {filename}")
            matched_files[filename] = text

    if not matched_files:
        return None, False

    if len(matched_files) == 1:
        # Ένα μόνο αρχείο → απλή απάντηση
        filename, text = next(iter(matched_files.items()))
        answer = answer_from_single_file(question, filename, text)
        return answer, True

    # Πολλά αρχεία → συνδυασμένη απάντηση
    combined_context = "\n\n".join(
        f"=== ΑΡΧΕΙΟ: {fn} ===\n{txt}"
        for fn, txt in matched_files.items()
    )
    sources = ", ".join(matched_files.keys())

    system_content = (
        f"Είσαι αναλυτής εγγράφων. Χρησιμοποιείς ΑΠΟΚΛΕΙΣΤΙΚΑ τα παρακάτω αρχεία: {sources}.\n\n"
        f"ΚΑΝΟΝΕΣ:\n"
        f"1. Απάντησε οργανωμένα — ξεχώρισε τι λέει κάθε αρχείο.\n"
        f"2. Τα παραδείγματα κώδικα να είναι ΑΚΡΙΒΩΣ αυτά που υπάρχουν στο κείμενο.\n"
        f"3. ΑΠΑΓΟΡΕΥΕΤΑΙ η εφεύρεση πινάκων, πεδίων ή τιμών που δεν υπάρχουν στο κείμενο.\n"
        f"4. ΓΡΑΨΕ ΜΟΝΟ ΟΣΑ ΠΑΡΑΔΕΙΓΜΑΤΑ ΥΠΑΡΧΟΥΝ ΣΤΟ ΚΕΙΜΕΝΟ.\n"
        f"5. Στο ΤΕΛΟΣ γράψε ΥΠΟΧΡΕΩΤΙΚΑ: 'Πηγή: {sources}'\n\n"
        f"ΚΕΙΜΕΝΟ:\n\"\"\"\n{combined_context}\n\"\"\""
    )
    messages = [{"role": "system", "content": system_content}]
    recent = [m for m in conversation_history if m["role"] != "system"][-4:]
    messages.extend(recent)
    answer = call_ollama(messages)
    return answer, True


def chat_general(user_text):
    return call_ollama(list(conversation_history))


# ==========================================
# 4. FLASK ROUTES
# ==========================================

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/pdf/<filename>')
def serve_pdf(filename):
    if not filename.endswith('.pdf'):
        filename += '.pdf'
    return send_from_directory(get_database_path(), filename)


@app.route('/new_chat', methods=['POST'])
def new_chat():
    global conversation_history, last_target_file, awaiting_fallback, last_fallback_question
    conversation_history   = [system_prompt]
    last_target_file       = None
    awaiting_fallback      = False
    last_fallback_question = ""
    return jsonify({"status": "ok"})


@app.route('/chat', methods=['POST'])
def process_request():
    global loaded_pdfs, last_target_file
    global awaiting_fallback, last_fallback_question

    data              = request.json
    is_voice          = data.get('is_voice', False)
    voice_text_for_ui = None

    if is_voice:
        user_input = listen()
        if not user_input:
            return jsonify({
                "reply":                "Δεν μπόρεσα να ακούσω τι είπες. Δοκίμασε ξανά.",
                "loaded_files":         sorted(loaded_pdfs.keys()),
                "user_text_from_voice": None
            })
        voice_text_for_ui = user_input
    else:
        user_input = data.get('text', '').strip().lower()

    if not user_input:
        return jsonify({"reply": "", "loaded_files": sorted(loaded_pdfs.keys()), "user_text_from_voice": None})

    conversation_history.append({"role": "user", "content": user_input})
    trim_history()

    reply = ""

   # ── Α: Fallback αναμονή ──
    print(f"[DEBUG] awaiting_fallback={awaiting_fallback}, input='{user_input}'")
    if awaiting_fallback:
        positive = ["ναι", "αμε", "ψάξε", "ψαξε", "οκ", "κάντο", "καντο", "βεβαιως", "βεβαίως"]
        if any(w in user_input for w in positive):
            awaiting_fallback = False
            # Φορτώνουμε όσα PDF δεν είναι ακόμα στη μνήμη
            load_all_database_pdfs()
            # Ψάχνουμε ένα-ένα, παραλείποντας το αρχείο που ήδη απέτυχε
            fallback_files = {k: v for k, v in loaded_pdfs.items() if k != last_target_file}
            if not fallback_files:
                reply = "Δεν υπάρχουν άλλα αρχεία στο database για αναζήτηση."
            else:
                answer, found = answer_from_pdf(last_fallback_question, fallback_files)
                reply = answer if found else \
                    "Δεν βρέθηκε πληροφορία σχετικά με αυτό σε κανένα αρχείο του database."
        else:
            awaiting_fallback = False
            reply = "Εντάξει, ακυρώθηκε η αναζήτηση στα υπόλοιπα αρχεία."

    # ── Β: Διαχείριση αρχείων ──
    elif any(kw in user_input for kw in ["καθάρισε", "καθαρισε", "άδειασε", "αδειασε"]) and \
         any(kw in user_input for kw in ["μνήμη", "μνημη", "όλα", "ολα"]):
        loaded_pdfs.clear()
        last_target_file = None
        reply = "Η μνήμη καθαρίστηκε. Έβγαλα όλα τα αρχεία."

    elif any(w in user_input for w in ["βγάλε", "βγαλε", "αφαίρεσε", "αφαιρεσε",
                                        "διέγραψε", "διεγραψε", "σβήσε", "σβησε",
                                        "διάγραψε", "διαγραψε"]):
        fname = get_filename_from_input(user_input)
        if fname and fname in loaded_pdfs:
            del loaded_pdfs[fname]
            if fname == last_target_file:
                last_target_file = None
            reply = f"Το αρχείο '{fname}' αφαιρέθηκε από τη μνήμη. Απομένουν {len(loaded_pdfs)}."
        else:
            reply = "Το αρχείο δεν βρέθηκε στη μνήμη."

    elif any(kw in user_input for kw in ["όλα", "ολα"]) and \
         any(kw in user_input for kw in ["διάβασ", "διαβασ"]):
        count = load_all_database_pdfs()
        reply = f"Φορτώθηκαν {count} νέα αρχεία. (Σύνολο: {len(loaded_pdfs)})"

    elif any(kw in user_input for kw in ["διάβασ", "διαβασ", "φορτωσ", "φόρτωσ"]):
        fname = get_filename_from_input(user_input)
        if fname:
            if fname in loaded_pdfs:
                reply = f"Το αρχείο '{fname}' είναι ήδη φορτωμένο."
            else:
                content = read_pdf(fname)
                if content:
                    loaded_pdfs[fname] = content
                    last_target_file   = fname
                    reply = f"Το αρχείο '{fname}' φορτώθηκε επιτυχώς!"
                else:
                    reply = f"Δεν βρέθηκε το αρχείο '{fname}' στον φάκελο database."
        else:
            reply = "Δεν κατάλαβα ποιο αρχείο να φορτώσω. Πες π.χ. 'Διάβασε το αρχείο baseis4'."

    elif any(w in user_input for w in ["ποια", "τι", "ποιο", "πού", "που"]) and \
         any(w in user_input for w in ["αρχεία", "αρχεια", "pdf", "βρήκες", "βρηκες", "φορτωμεν"]):
        if loaded_pdfs:
            reply = f"Έχω φορτωμένα {len(loaded_pdfs)} αρχεία: {', '.join(sorted(loaded_pdfs.keys()))}"
        else:
            reply = "Δεν έχω κανένα αρχείο φορτωμένο αυτή τη στιγμή."

    # ── Ε: Meta-εντολές (quiz, πολλαπλής, περίληψη, flashcards) ──
    elif any(kw in user_input for kw in [
        "πολλαπλής", "πολλαπλης", "quiz", "τεστ", "test",
        "ερωτήσεις", "ερωτησεις", "εξέταση", "εξεταση",
        "flashcard", "flashcards", "σύνοψη", "συνοψη",
        "κάνε μου", "κανε μου", "φτιάξε", "φτιαξε",
        "δημιούργησε", "δημιουργησε", 
    ]):
        if not loaded_pdfs:
            reply = "Δεν έχεις φορτώσει κάποιο αρχείο. Πες π.χ. 'Διάβασε το αρχείο baseis4'."
        else:
            fname = get_filename_from_input(user_input)
            if fname and fname in loaded_pdfs:
                context_files = {fname: loaded_pdfs[fname]}
            elif last_target_file and last_target_file in loaded_pdfs:
                context_files = {last_target_file: loaded_pdfs[last_target_file]}
            else:
                context_files = loaded_pdfs

            combined_context = "\n\n".join(
                f"=== ΑΡΧΕΙΟ: {fn} ===\n{txt}"
                for fn, txt in context_files.items()
            )

            system_content = (
                "Είσαι εκπαιδευτικός βοηθός. Χρησιμοποιείς ΑΠΟΚΛΕΙΣΤΙΚΑ το παρακάτω υλικό.\n"
                "ΚΑΝΟΝΕΣ:\n"
                "1. Χρησιμοποίησε ΜΟΝΟ πληροφορίες που υπάρχουν ΡΗΤΑ στο ΥΛΙΚΟ παρακάτω.\n"
                "2. ΜΗΝ αναφέρεις αρχεία που δεν υπάρχουν στο ΥΛΙΚΟ.\n"
                "3. Για πολλαπλής επιλογής: φτιάξε ΑΚΡΙΒΩΣ 4 ΔΙΑΦΟΡΕΤΙΚΕΣ ερωτήσεις.\n"
                "   ΑΠΑΓΟΡΕΥΕΤΑΙ να επαναλαμβάνεις την ίδια ερώτηση.\n"
                "   Κάθε ερώτηση να έχει 4 επιλογές (Α-Δ), μία σωστή.\n"
                "   Μετά από κάθε ερώτηση γράψε: ✅ Σωστή: [γράμμα] — [εξήγηση] (Πηγή: [αρχείο])\n"
                "4. Απάντησε στα Ελληνικά.\n"
                "5. ΜΗΝ εφευρίσκεις ερωτήσεις ή αρχεία εκτός του ΥΛΙΚΟΥ.\n"
                "6. Στο ΤΕΛΟΣ γράψε ΜΟΝΟ τα αρχεία που υπάρχουν στο ΥΛΙΚΟ.\n\n"
                f"ΥΛΙΚΟ:\n\"\"\"\n{combined_context}\n\"\"\""
            ) 

            messages = [{"role": "system", "content": system_content}]
            for msg in conversation_history:
                if msg["role"] != "system":
                    messages.append(msg)
            reply = call_ollama(messages)        

    # ── Γ: Ερώτηση με ρητή αναφορά σε αρχείο ──
    elif any(phrase in user_input for phrase in [
        "σύμφωνα με", "συμφωνα με", "από το αρχείο", "απο το αρχειο",
        "από τα αρχεία", "απο τα αρχεια", "βάσει", "βασει",
        "τι λέει", "τι λεει", "περίληψη", "περιληψη",
        "βάση των αρχείων", "βαση των αρχειων", "βάση αρχείων", "βαση αρχειων",
        "βάση του αρχείου", "βαση του αρχειου", "με βάση", "με βαση",
        "από τα pdf", "απο τα pdf", "στα αρχεία", "στα αρχεια"
    ]):
        
        if not loaded_pdfs:
            reply = "Δεν έχεις φορτώσει κάποιο αρχείο ακόμα. Πες π.χ. 'Διάβασε το αρχείο baseis4'."
        else:
            fname = get_filename_from_input(user_input)
            if fname and fname in loaded_pdfs:
                last_target_file = fname
                answer, found = answer_from_pdf(user_input, {fname: loaded_pdfs[fname]})
                if found:
                    reply = answer
                else:
                    last_fallback_question = user_input
                    awaiting_fallback      = True
                    reply = (
                        f"Δεν βρέθηκε πληροφορία για αυτό στο αρχείο '{fname}'. "
                        f"Να ψάξω στα υπόλοιπα αρχεία του database; (πείτε 'ναι')"
                    )
            else:
                answer, found = answer_from_pdf(user_input, loaded_pdfs)
                reply = answer if found else \
                    "Δεν βρέθηκε πληροφορία σχετικά με αυτό σε κανένα από τα φορτωμένα αρχεία."
                
                

    # ── Δ: Follow-up ή ελεύθερη ερώτηση ──
    else:
        if loaded_pdfs:
            answer, found = answer_from_pdf(user_input, loaded_pdfs)
            reply = answer if found else chat_general(user_input)
        else:
            reply = chat_general(user_input)

    conversation_history.append({"role": "assistant", "content": reply})

    return jsonify({
        "reply":                reply,
        "loaded_files":         sorted(loaded_pdfs.keys()),
        "user_text_from_voice": voice_text_for_ui
    })


# ==========================================
# 5. ΦΩΝΗΤΙΚΗ ΕΙΣΟΔΟΣ
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
        return None
    except sr.RequestError:
        return None


# ==========================================
# 6. ΕΚΚΙΝΗΣΗ
# ==========================================
if __name__ == "__main__":
    print("=" * 50)
    print("ΚΑΛΩΣ ΗΡΘΕΣ ΣΤΟΝ ΠΡΟΣΩΠΙΚΟ ΣΟΥ AI ΒΟΗΘΟ!")
    print("=" * 50)
    Timer(1.5, lambda: webbrowser.open("http://127.0.0.1:5000/")).start()
    app.run(debug=False, port=5000)

# ==========================================
# ΟΔΗΓΙΕΣ ΧΡΗΣΗΣ
# ==========================================
# ΦΟΡΤΩΣΗ:       "Διάβασε το αρχείο baseis4"
# ΦΟΡΤΩΣΗ ΟΛΩΝ:  "Διάβασε όλα τα αρχεία"        → φορτώνει όλα τα PDF από το database/
# ΕΡΩΤΗΣΗ:       "Σύμφωνα με το αρχείο baseis4, τι είναι το ER μοντέλο;"
# FOLLOW-UP:     Η επόμενη ερώτηση ψάχνει αυτόματα στο ίδιο αρχείο
# FALLBACK:      Αν δεν βρεθεί → "ναι" → φορτώνει ΟΛΑ τα PDF του database/ και ψάχνει
# ΑΦΑΙΡΕΣΗ:      "Βγάλε το αρχείο baseis4"
# ΚΑΘΑΡΙΣΜΟΣ:    "Άδειασε όλα τα αρχεία"