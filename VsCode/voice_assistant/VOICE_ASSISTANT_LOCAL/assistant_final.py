import random
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
last_target_file       = None   # Αρχείο που ζήτησε ο χρήστης
last_found_file        = None   # Αρχείο όπου βρέθηκε ΠΡΑΓΜΑΤΙΚΑ η απάντηση ← ΝΕΟ
awaiting_fallback      = False
last_fallback_question = ""

MAX_HISTORY_PAIRS = 10

TASK_KEYWORDS = [
    "πολλαπλής", "πολλαπλης", "πολλαπλη", "πολλαπλη",
    "quiz", "τεστ", "test",
    "ερωτήσεις", "ερωτησεις", "ερώτηση μελέτης", "ερωτηση μελετης",
    "εξέταση", "εξεταση", "εξετάσεις", "εξετασεις",
    "flashcard", "flashcards",
    "σύνοψη", "συνοψη", "σύνοψε", "συνοψε",
    "κάνε μου", "κανε μου",
    "φτιάξε", "φτιαξε",
    "δημιούργησε", "δημιουργησε",
    "δοκιμασία", "δοκιμασια",
    "επανάληψη", "επαναληψη",
]


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
    # Πρώτα: ακριβές match με φορτωμένα αρχεία
    greek_to_latin = {"βάσεις": "baseis", "βασεις": "baseis", "βάση": "baseis", "βαση": "baseis"}
    
    for greek, latin in greek_to_latin.items():
        if greek in user_input.lower():
            user_input = user_input.lower().replace(greek, latin)
            break

    for fname in sorted(loaded_pdfs.keys(), key=len, reverse=True):
        if fname.lower() in user_input.lower():
            return fname

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
        # Χωρίς αριθμό → ψάχνουμε αν υπάρχει "baseis" (χωρίς αριθμό) στα φορτωμένα
        if "baseis" in loaded_pdfs:
            return "baseis"
        return None

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
        "model":    "llama3.1:8b",
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
# 3. ΣΥΝΑΡΤΗΣΕΙΣ ΑΠΑΝΤΗΣΗΣ
# ==========================================

def check_topic_in_single_file(question: str, filename: str, text: str) -> bool:
    system_content = (
        "You are a text checker. Reply with ONLY the word YES or NO. Nothing else.\n"
        "YES = the topic exists in the text.\n"
        "NO = the topic does not exist in the text.\n"
        "Do not write anything else. Do not explain. Just YES or NO.\n\n"
        f"TEXT ({filename}):\n\"\"\"\n{text}\n\"\"\""
    )
    messages = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": f"Does the text contain information about: {question}? Answer YES or NO only."}
    ]
    raw = call_ollama(messages).strip().lower()
    print(f"  [CHECK] {filename} → '{raw[:10]}'")
    return raw.startswith("yes")


def answer_from_single_file(question: str, filename: str, text: str) -> str:
    system_content = (
        f"You are a document analyst. Use ONLY the file: {filename}.\n\n"
        f"ANSWER FORMAT (follow EXACTLY, in Greek):\n"
        f"1. THEORY: 2-4 lines explaining the topic in your own words.\n"
        f"2. CODE EXAMPLE: ONLY if one exists in the text below — copy it EXACTLY in a ```sql``` block.\n"
        f"   If no code exists in the text, skip this step entirely.\n"
        f"3. EXPLANATION: One short sentence explaining the example (or the theory if no code).\n"
        f"4. SOURCE: Last line must be exactly: Πηγή: {filename}\n\n"
        f"STRICT RULES:\n"
        f"- Do NOT repeat the answer.\n"
        f"- Do NOT invent code or examples.\n"
        f"- Do NOT use external knowledge.\n"
        f"- Answer ONCE, in Greek.\n\n"
        f"TEXT FROM {filename}:\n\"\"\"\n{text}\n\"\"\""
    )
    recent = [m for m in conversation_history if m["role"] != "system"][-4:]
    messages = [{"role": "system", "content": system_content}]
    messages.extend(recent)
    messages.append({"role": "user", "content": question})
    return call_ollama(messages)


def answer_from_pdf(question: str, context_files: dict):
    """
    Ψάχνει ΟΛΑ τα αρχεία με pre-check ένα-ένα.
    Επιστρέφει: (reply_text | None, found: bool, matched_filename | None)
    ← Τώρα επιστρέφει και το όνομα του αρχείου που βρήκε
    """
    matched_files = {}

    for filename, text in context_files.items():
        print(f"[SEARCH] Ψάχνω στο: {filename}")
        if check_topic_in_single_file(question, filename, text):
            print(f"[FOUND]  Βρέθηκε στο: {filename}")
            matched_files[filename] = text

    if not matched_files:
        return None, False, None

    if len(matched_files) == 1:
        filename, text = next(iter(matched_files.items()))
        answer = answer_from_single_file(question, filename, text)
        return answer, True, filename  # ← επιστρέφει το filename

    # Πολλά αρχεία → συνδυασμένη απάντηση
    combined_context = "\n\n".join(
        f"=== ΑΡΧΕΙΟ: {fn} ===\n{txt}"
        for fn, txt in matched_files.items()
    )
    sources = ", ".join(matched_files.keys())

    system_content = (
        f"Είσαι αναλυτής εγγράφων. Χρησιμοποιείς ΑΠΟΚΛΕΙΣΤΙΚΑ τα: {sources}.\n\n"
        f"ΚΑΝΟΝΕΣ:\n"
        f"1. Απάντησε οργανωμένα — ξεχώρισε τι λέει κάθε αρχείο αν διαφέρουν.\n"
        f"2. Παραδείγματα κώδικα ΑΚΡΙΒΩΣ όπως στο κείμενο, σε markdown code block.\n"
        f"3. ΑΠΑΓΟΡΕΥΕΤΑΙ η εφεύρεση στοιχείων που δεν υπάρχουν στο κείμενο.\n"
        f"4. Στο ΤΕΛΟΣ: 'Πηγή: {sources}'\n\n"
        f"ΚΕΙΜΕΝΟ:\n\"\"\"\n{combined_context}\n\"\"\""
    )
    messages = [{"role": "system", "content": system_content}]
    recent = [m for m in conversation_history if m["role"] != "system"][-4:]
    messages.extend(recent)
    answer = call_ollama(messages)
    first_match = next(iter(matched_files.keys()))
    return answer, True, first_match  # ← επιστρέφει το πρώτο αρχείο που βρέθηκε


def perform_task(user_request: str, context_files: dict) -> str:
    num_match = re.search(r'\d+', user_request)
    num_q = int(num_match.group()) if num_match else 4

    import random
    GENERIC_KEYWORDS = ["πολλαπλής", "πολλαπλης", "quiz", "τεστ", "ερωτήσεις",
                        "ερωτησεις", "κάνε μου", "κανε μου", "φτιάξε", "φτιαξε"]
    
    is_generic = (
        "πολλαπλ" in user_request.lower() or
        "διαφορ" in user_request.lower()
    ) and not any(
        w for w in user_request.lower().split()
        if len(w) > 4 and w not in GENERIC_KEYWORDS
        and not any(x in w for x in ["αρχει", "βασ", "bas"])
    )

    if is_generic:
        sample_size = min(num_q, len(context_files))
        relevant_files = dict(random.sample(list(context_files.items()), sample_size))
    else:
        relevant_files = {}
        for filename, text in context_files.items():
            if check_topic_in_single_file(user_request, filename, text):
                relevant_files[filename] = text
            if len(relevant_files) >= num_q:
                break
        if not relevant_files:
            sample_size = min(num_q, len(context_files))
            relevant_files = dict(random.sample(list(context_files.items()), sample_size))

    sources = ", ".join(relevant_files.keys())
    combined = "\n\n".join(
        f"=== ΑΡΧΕΙΟ: {fn} ===\n{txt}"
        for fn, txt in relevant_files.items()
    )

    system_content = (
        f"Create EXACTLY {num_q} multiple choice questions from the material below.\n\n"
        f"REQUIRED FORMAT — follow EXACTLY for each question:\n\n"
        f"Ερώτηση 1: [ερώτηση;]\n"
        f"Α) [επιλογή]\n"
        f"Β) [επιλογή]\n"
        f"Γ) [επιλογή]\n"
        f"Δ) [επιλογή]\n"
        f"✅ Σωστή: [γράμμα]) [κείμενο σωστής] — [σύντομη εξήγηση]\n"
        f"📚 Πηγή: [γράψε ΑΚΡΙΒΩΣ το όνομα του αρχείου από το ΥΛΙΚΟ, π.χ. baseis7 ή baseis12]\n\n"
        f"RULES:\n"
        f"- ALWAYS 4 options Α/Β/Γ/Δ per question.\n"
        f"- NEVER write 'Απάντηση:' — ONLY ✅ Σωστή:\n"
        f"- ALWAYS write 📚 Πηγή: after EACH question.\n"
        f"- The correct answer position must vary (not always Β).\n"
        f"- Use ONLY information from the material.\n"
        f"- Answer in Greek.\n\n"
        f"MATERIAL:\n\"\"\"\n{combined}\n\"\"\""
    )

    messages = [{"role": "system", "content": system_content}]
    recent = [m for m in conversation_history if m["role"] != "system"][-4:]
    messages.extend(recent)
    messages.append({"role": "user", "content": f"Φτιάξε {num_q} ερωτήσεις πολλαπλής επιλογής."})
    return call_ollama(messages)

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
    global conversation_history, last_target_file, last_found_file
    global awaiting_fallback, last_fallback_question
    conversation_history   = [system_prompt]
    last_target_file       = None
    last_found_file        = None
    awaiting_fallback      = False
    last_fallback_question = ""
    return jsonify({"status": "ok"})


@app.route('/chat', methods=['POST'])
def process_request():
    global loaded_pdfs, last_target_file, last_found_file
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

    # ── Ορθογραφικός έλεγχος ──
    KNOWN_COMMANDS = [
        "διάβασε", "διαβασε", "φόρτωσε", "φορτωσε",
        "βγάλε", "βγαλε", "διέγραψε", "διεγραψε",
        "άδειασε", "αδειασε", "καθάρισε", "καθαρισε",
        "σύμφωνα", "συμφωνα", "από", "απο", "πες", "δώσε", "δωσε",
        "κάνε", "κανε", "φτιάξε", "φτιαξε"
    ]
    looks_like_command = any(
        kw in user_input for kw in ["αρχει", "βασ", "bas", "μνήμη", "μνημη"]
    )
    is_known = any(cmd in user_input for cmd in KNOWN_COMMANDS)
    if looks_like_command and not is_known and len(user_input) < 60:
        reply = (
            "Δεν κατάλαβα την εντολή. Μήπως υπάρχει τυπογραφικό λάθος; "
            "Παρακαλώ ξαναγράψτε. Παραδείγματα:\n"
            "• 'Διέγραψε το αρχείο baseis10'\n"
            "• 'Διάβασε το αρχείο baseis4'\n"
            "• 'Άδειασε όλα τα αρχεία'"
        )
        conversation_history.append({"role": "assistant", "content": reply})
        return jsonify({
            "reply": reply,
            "loaded_files": sorted(loaded_pdfs.keys()),
            "user_text_from_voice": voice_text_for_ui
        })

    reply = ""



    # ══════════════════════════════════════════════════════
    # Α: Fallback αναμονή
    # ══════════════════════════════════════════════════════
    print(f"[DEBUG] awaiting_fallback={awaiting_fallback}, last_target={last_target_file}, last_found={last_found_file}")

    if awaiting_fallback:
        positive = ["ναι", "αμε", "ψάξε", "ψαξε", "οκ", "κάντο", "καντο", "βεβαιως", "βεβαίως"]
        if any(w in user_input for w in positive):
            awaiting_fallback = False
            load_all_database_pdfs()
            fallback_files = {k: v for k, v in loaded_pdfs.items() if k != last_target_file}
            if not fallback_files:
                reply = "Δεν υπάρχουν άλλα αρχεία στο database για αναζήτηση."
            else:
                answer, found, matched = answer_from_pdf(last_fallback_question, fallback_files)
                if found:
                    last_found_file = matched  # ← Ενημερώνουμε ποιο αρχείο βρήκε
                    reply = answer
                else:
                    reply = "Δεν βρέθηκε πληροφορία σχετικά με αυτό σε κανένα αρχείο του database."
        else:
            awaiting_fallback = False
            reply = "Εντάξει, ακυρώθηκε η αναζήτηση στα υπόλοιπα αρχεία."

    # ══════════════════════════════════════════════════════
    # Β: Διαχείριση αρχείων
    # ══════════════════════════════════════════════════════
    elif any(kw in user_input for kw in ["καθάρισε", "καθαρισε", "άδειασε", "αδειασε"]) and \
         any(kw in user_input for kw in ["μνήμη", "μνημη", "όλα", "ολα", "αρχεία", "αρχεια"]):
        loaded_pdfs.clear()
        last_target_file = None
        last_found_file  = None
        reply = "Η μνήμη καθαρίστηκε. Έβγαλα όλα τα αρχεία."

    elif any(w in user_input for w in ["βγάλε", "βγαλε", "αφαίρεσε", "αφαιρεσε",
                                        "διέγραψε", "διεγραψε", "σβήσε", "σβησε",
                                        "διάγραψε", "διαγραψε"]):
        
        fname = get_filename_from_input(user_input)
        # Αν δεν βρέθηκε όνομα αρχείου στο κείμενο, χρησιμοποιούμε το τελευταίο ενεργό
        if not fname:
            fname = last_found_file or last_target_file
        if fname and fname in loaded_pdfs:
            del loaded_pdfs[fname]
            if fname == last_target_file: last_target_file = None
            if fname == last_found_file:  last_found_file  = None
            reply = f"Το αρχείο '{fname}' αφαιρέθηκε από τη μνήμη. Απομένουν {len(loaded_pdfs)}."
        else:
            reply = "Δεν βρέθηκε αρχείο για διαγραφή. Πες π.χ. 'Διέγραψε το αρχείο baseis4'."

    elif any(kw in user_input for kw in ["όλα", "ολα"]) and \
         any(kw in user_input for kw in ["διάβασ", "διαβασ"]):
        count = load_all_database_pdfs()
        reply = f"Φορτώθηκαν {count} νέα αρχεία. (Σύνολο: {len(loaded_pdfs)})"

    elif any(kw in user_input for kw in ["διάβασ", "διαβασ", "φορτωσ", "φόρτωσ",
                                          "πρόσθεσ", "προσθεσ", "βάλε", "βαλε",
                                          "ξαναβάλε", "ξαναβαλε", "ξαναφόρτω", "ξαναφορτω",
                                          "πρόσθεσε", "προσθεσε"]):
        fname = get_filename_from_input(user_input)
        if fname:
            if fname in loaded_pdfs:
                reply = f"Το αρχείο '{fname}' είναι ήδη φορτωμένο."
            else:
                content = read_pdf(fname)
                if content:
                    loaded_pdfs[fname]  = content
                    last_target_file    = fname
                    reply = f"Το αρχείο '{fname}' φορτώθηκε επιτυχώς!"
                else:
                    reply = f"Δεν βρέθηκε το αρχείο '{fname}' στον φάκελο database."
        else:
            reply = "Δεν κατάλαβα ποιο αρχείο να φορτώσω. Πες π.χ. 'Διάβασε το αρχείο baseis4'."


    # ══════════════════════════════════════════════════════
    # Γ: TASK REQUEST — quiz, πολλαπλής, σύνοψη κλπ
    # Ελέγχεται ΠΡΙΝ το content search — δεν χρειάζεται pre-check
    # ══════════════════════════════════════════════════════
    elif any(kw in user_input for kw in TASK_KEYWORDS) and loaded_pdfs:
        # Προτεραιότητα: last_found_file > last_target_file > όλα τα φορτωμένα
        fname = get_filename_from_input(user_input)
        if fname and fname in loaded_pdfs:
            task_files = {fname: loaded_pdfs[fname]}
        elif last_found_file and last_found_file in loaded_pdfs:
            task_files = loaded_pdfs  # ← Χρησιμοποιεί ΟΛΑ, όχι μόνο το last_found
        elif last_target_file and last_target_file in loaded_pdfs:
            task_files = loaded_pdfs  # ← Ίδιο
        else:
            task_files = loaded_pdfs

        reply = perform_task(user_input, task_files)

    # changes for pollalpis
    elif any(w in user_input for w in ["ποια", "τι", "ποιο", "πού", "που"]) and \
            any(w in user_input for w in ["αρχεία", "αρχεια", "pdf", "βρήκες", "βρηκες", "φορτωμεν"]):
        if loaded_pdfs:
            reply = f"Έχω φορτωμένα {len(loaded_pdfs)} αρχεία: {', '.join(sorted(loaded_pdfs.keys()))}"
        else:
            reply = "Δεν έχω κανένα αρχείο φορτωμένο αυτή τη στιγμή."


    # ══════════════════════════════════════════════════════
    # Δ: Ερώτηση με ρητή αναφορά σε αρχείο
    # ══════════════════════════════════════════════════════
    elif any(phrase in user_input for phrase in [
        "σύμφωνα με", "συμφωνα με", "από το αρχείο", "απο το αρχειο",
        "από τα αρχεία", "απο τα αρχεια", "βάσει", "βασει",
        "τι λέει", "τι λεει", "περίληψη", "περιληψη",
        "με βάση", "με βαση", "στα αρχεία", "στα αρχεια",
        "από τα pdf", "απο τα pdf",
    ]):
        if not loaded_pdfs:
            reply = "Δεν έχεις φορτώσει κάποιο αρχείο ακόμα. Πες π.χ. 'Διάβασε το αρχείο baseis4'."
        else:
            fname = get_filename_from_input(user_input)
            if fname and fname in loaded_pdfs:
                last_target_file = fname
                answer, found, matched = answer_from_pdf(user_input, {fname: loaded_pdfs[fname]})
                if found:
                    last_found_file = matched
                    reply = answer
                else:
                    last_fallback_question = user_input
                    awaiting_fallback      = True
                    reply = (
                        f"Δεν βρέθηκε πληροφορία για αυτό στο αρχείο '{fname}'. "
                        f"Να ψάξω στα υπόλοιπα αρχεία του database; (πείτε 'ναι')"
                    )
            else:
                answer, found, matched = answer_from_pdf(user_input, loaded_pdfs)
                if found:
                    last_found_file = matched
                    reply = answer
                else:
                    reply = "Δεν βρέθηκε πληροφορία σχετικά με αυτό σε κανένα από τα φορτωμένα αρχεία."

    # ══════════════════════════════════════════════════════
    # Ε: Follow-up ή ελεύθερη ερώτηση
    # ══════════════════════════════════════════════════════
    else:
        if loaded_pdfs:
            answer, found, matched = answer_from_pdf(user_input, loaded_pdfs)
            if found:
                last_found_file = matched
                reply = answer
            else:
                reply = chat_general(user_input)
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
# ΦΟΡΤΩΣΗ:        "Διάβασε το αρχείο baseis4"
# ΦΟΡΤΩΣΗ ΟΛΩΝ:   "Διάβασε όλα τα αρχεία"
# ΕΡΩΤΗΣΗ:        "Σύμφωνα με το αρχείο baseis4, τι είναι το ER μοντέλο;"
# FOLLOW-UP:      Ψάχνει αυτόματα στο αρχείο που βρήκε την τελευταία απάντηση
# QUIZ:           "Κάνε μου 4 πολλαπλής επιλογής" → από το αρχείο της τελευταίας απάντησης
# FALLBACK:       "ναι" → φορτώνει ΟΛΑ τα PDF και ψάχνει
# ΑΦΑΙΡΕΣΗ:       "Βγάλε το αρχείο baseis4"
# ΚΑΘΑΡΙΣΜΟΣ:     "Άδειασε όλα τα αρχεία"