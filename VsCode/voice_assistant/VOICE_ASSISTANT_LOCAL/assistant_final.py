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

conversation_history   = [system_prompt]  # Μνήμη συνομιλίας
loaded_pdfs            = {}               # { όνομα_αρχείου: κείμενο } — αρχεία στη μνήμη
last_target_file       = None             # Τελευταίο ενεργό αρχείο
awaiting_fallback      = False            # Αναμένουμε "ναι/όχι" για fallback αναζήτηση
last_fallback_question = ""               # Η ερώτηση που έμεινε αναπάντητη

MAX_HISTORY_PAIRS = 10                    # Μέγιστο ιστορικό (10 ζεύγη = 20 μηνύματα)


# ==========================================
# 2. ΒΟΗΘΗΤΙΚΕΣ ΣΥΝΑΡΤΗΣΕΙΣ
# ==========================================

def trim_history():
    """Κρατάει το system prompt + τα τελευταία MAX_HISTORY_PAIRS ζεύγη."""
    global conversation_history
    system = [m for m in conversation_history if m["role"] == "system"]
    rest   = [m for m in conversation_history if m["role"] != "system"]
    if len(rest) > MAX_HISTORY_PAIRS * 2:
        rest = rest[-(MAX_HISTORY_PAIRS * 2):]
    conversation_history = system + rest


def get_database_path():
    """Επιστρέφει το απόλυτο path του φακέλου database/."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(script_dir, "database")


def read_pdf(filename):
    """
    Διαβάζει ένα PDF από τον φάκελο database/ και επιστρέφει το κείμενό του.
    Δέχεται όνομα με ή χωρίς .pdf.
    """
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
    """
    Φορτώνει ΟΛΑ τα PDF από τον φάκελο database/ στη μνήμη (loaded_pdfs).
    Επιστρέφει τον αριθμό νέων αρχείων που φορτώθηκαν.
    """
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
    """Εντοπίζει όνομα αρχείου μέσα στο κείμενο του χρήστη."""
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
    """Αποστέλλει αίτημα στο Ollama και επιστρέφει το κείμενο της απάντησης."""
    url     = "http://localhost:11434/api/chat"
    payload = {
        "model":    "llama3.1",
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

def answer_from_pdf(user_question, context_files: dict):
    """
    Ρωτάει το LLM αποκλειστικά με βάση τα context_files.
    context_files: { όνομα_αρχείου: κείμενο }
    Επιστρέφει: (reply_text | None, found: bool)

    Το LLM υποχρεούται να γράφει 'Πηγή: ...' στο τέλος κάθε απάντησης,
    ή 'NOT_FOUND' αν η πληροφορία δεν υπάρχει στα αρχεία.
    """
    combined  = "\n\n".join(
        f"=== ΑΡΧΕΙΟ: {name} ===\n{text}"
        for name, text in context_files.items()
    )
    file_list = ", ".join(context_files.keys())

    system_content = (
        f"Είσαι αυστηρός αναλυτής εγγράφων. "
        f"Απαντάς ΑΠΟΚΛΕΙΣΤΙΚΑ με βάση τα παρακάτω αρχεία: {file_list}.\n\n"
        f"ΚΑΝΟΝΕΣ:\n"
        f"1. Αν βρεις την πληροφορία, απάντησε πλήρως και στο ΤΕΛΟΣ γράψε ΥΠΟΧΡΕΩΤΙΚΑ:\n"
        f"   'Πηγή: [ονόματα αρχείων από τα οποία αντλήθηκε η πληροφορία]'\n"
        f"2. ΑΠΑΓΟΡΕΥΕΤΑΙ η χρήση εξωτερικής γνώσης.\n"
        f"3. Αν η πληροφορία ΔΕΝ ΥΠΑΡΧΕΙ σε κανένα αρχείο, γράψε ΜΟΝΟ: NOT_FOUND\n"
        f"4. 'Ασθενής τύπος οντοτήτων' = Weak Entity (ΟΧΙ ιατρικό).\n"
        f"5. Για αριθμούς σελίδων χρησιμοποίησε τις ετικέτες '--- ΣΕΛΙΔΑ Χ ---'.\n\n"
        f"ΚΕΙΜΕΝΑ ΑΡΧΕΙΩΝ:\n\"\"\"\n{combined}\n\"\"\""
    )

    # System με context + ιστορικό συνομιλίας (χωρίς το παλιό system prompt)
    messages_to_send = [{"role": "system", "content": system_content}]
    for msg in conversation_history:
        if msg["role"] != "system":
            messages_to_send.append(msg)

    raw = call_ollama(messages_to_send)

    if "not_found" in raw.strip().lower():
        return None, False

    return raw, True


def chat_general(user_text):
    """Ελεύθερη συνομιλία χωρίς PDF context."""
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

    # ── Είσοδος (φωνή ή κείμενο) ──
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

    # Προσθήκη στο ιστορικό + κλάδεμα
    conversation_history.append({"role": "user", "content": user_input})
    trim_history()

    reply = ""

    # ══════════════════════════════════════════════════════
    # ΠΕΡΙΠΤΩΣΗ Α: Αναμένουμε ναι/όχι για fallback
    # Αν πει "ναι" → φορτώνουμε ΟΛΑ τα PDF του database/
    # και ψάχνουμε σε όσα ΔΕΝ έχουμε ήδη ψάξει
    # ══════════════════════════════════════════════════════
    if awaiting_fallback:
        positive = ["ναι", "αμε", "ψάξε", "ψαξε", "οκ", "κάντο", "καντο", "βεβαιως", "βεβαίως"]
        if any(w in user_input for w in positive):
            awaiting_fallback = False

            # Φορτώνουμε όσα PDF του database/ δεν είναι ακόμα στη μνήμη
            load_all_database_pdfs()

            # Ψάχνουμε σε ΟΛΑ τα αρχεία εκτός από αυτό που ήδη δεν βρήκε
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

    # ══════════════════════════════════════════════════════
    # ΠΕΡΙΠΤΩΣΗ Β: Διαχείριση αρχείων
    # ══════════════════════════════════════════════════════
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
        reply = f"Φορτώθηκαν {count} νέα αρχεία. (Σύνολο στη μνήμη: {len(loaded_pdfs)})"

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

    # ══════════════════════════════════════════════════════
    # ΠΕΡΙΠΤΩΣΗ Γ: Ερώτηση με ρητή αναφορά σε αρχείο
    # ══════════════════════════════════════════════════════
    elif any(phrase in user_input for phrase in [
        "σύμφωνα με", "συμφωνα με", "από το αρχείο", "απο το αρχειο",
        "από τα αρχεία", "απο τα αρχεια", "βάσει", "βασει",
        "τι λέει", "τι λεει", "περίληψη", "περιληψη"
    ]):
        if not loaded_pdfs:
            reply = "Δεν έχεις φορτώσει κάποιο αρχείο ακόμα. Πες π.χ. 'Διάβασε το αρχείο baseis4'."
        else:
            fname = get_filename_from_input(user_input)
            if fname and fname in loaded_pdfs:
                # Ερώτηση για συγκεκριμένο αρχείο
                last_target_file = fname
                answer, found = answer_from_pdf(user_input, {fname: loaded_pdfs[fname]})
                if found:
                    reply = answer
                else:
                    last_fallback_question = user_input
                    awaiting_fallback      = True
                    reply = (
                        f"Δεν βρέθηκε πληροφορία σχετικά με αυτό στο αρχείο '{fname}'. "
                        f"Αν θέλετε να ψάξω στα υπόλοιπα αρχεία του database, πείτε 'ναι'."
                    )
            else:
                # Δεν προσδιορίστηκε αρχείο → ψάχνουμε σε όλα τα φορτωμένα
                answer, found = answer_from_pdf(user_input, loaded_pdfs)
                reply = answer if found else \
                    "Δεν βρέθηκε πληροφορία σχετικά με αυτό σε κανένα από τα φορτωμένα αρχεία."

    # ══════════════════════════════════════════════════════
    # ΠΕΡΙΠΤΩΣΗ Δ: Follow-up ή ελεύθερη ερώτηση
    # ══════════════════════════════════════════════════════
    else:
        if last_target_file and last_target_file in loaded_pdfs:
            # Υπάρχει ενεργό αρχείο → απαντάμε από εκεί πρώτα
            answer, found = answer_from_pdf(user_input, {last_target_file: loaded_pdfs[last_target_file]})
            if found:
                reply = answer
            else:
                last_fallback_question = user_input
                awaiting_fallback      = True
                reply = (
                    f"Δεν βρέθηκε πληροφορία σχετικά με αυτό στο αρχείο '{last_target_file}'. "
                    f"Αν θέλετε να ψάξω στα υπόλοιπα αρχεία του database, πείτε 'ναι'."
                )
        else:
            # Δεν υπάρχει ενεργό αρχείο → ελεύθερη συνομιλία
            reply = chat_general(user_input)

    # Αποθήκευση απάντησης στο ιστορικό
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