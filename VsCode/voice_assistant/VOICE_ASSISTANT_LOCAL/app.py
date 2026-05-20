from flask import Flask, request, jsonify, render_template
import speech_recognition as sr
import os
import fitz  # PyMuPDF
import requests
import re

app = Flask(__name__)

# --- ΚΑΘΟΛΙΚΕΣ ΜΕΤΑΒΛΗΤΕΣ ---
conversation_history = [
    {
        "role": "system", 
        "content": "Είσαι ένας έξυπνος βοηθός. Απάντησε σε άπταιστα Ελληνικά. Αν δεν γνωρίζεις κάτι, πες 'Δεν γνωρίζω'."
    }
]
loaded_pdfs = {}
awaiting_global_search = False
last_pdf_question = ""

# --- ΒΟΗΘΗΤΙΚΕΣ ΣΥΝΑΡΤΗΣΕΙΣ (Όπως τις είχες) ---
def listen():
    recognizer = sr.Recognizer()
    recognizer.pause_threshold = 2.0 
    with sr.Microphone() as source:
        print("Μικρόφωνο ανοιχτό...")
        recognizer.adjust_for_ambient_noise(source, duration=1)
        audio = recognizer.listen(source)
    try:
        return recognizer.recognize_google(audio, language='el-GR').lower()
    except:
        return None

def read_pdf(filename):
    if not filename.endswith('.pdf'): filename += '.pdf'
    script_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(script_dir, "database", filename)
    if not os.path.exists(file_path): return None
    text_content = ""
    try:
        doc = fitz.open(file_path)
        for page in doc: text_content += page.get_text()
        doc.close()
        return text_content if text_content.strip() else None
    except:
        return None

def chat_with_ollama(user_text, restrict_to_pdf=False, custom_context="", target_file_name=None):
    global conversation_history
    
    if restrict_to_pdf:
        if target_file_name:
            message_content = (
                f"ΕΙΣΑΙ ΕΝΑ ΡΟΜΠΟΤ ΧΩΡΙΣ ΔΙΚΗ ΤΟΥ ΜΝΗΜΗ. Απάντησε ΑΥΣΤΗΡΑ ΚΑΙ ΜΟΝΟ με βάση το κείμενο του αρχείου {target_file_name}.\n"
                f"Στην ΑΡΧΗ της απάντησής σου, γράψε ΠΑΝΤΑ: 'Βάσει του αρχείου {target_file_name}:'.\n"
                f"ΚΑΝΟΝΑΣ: Αν το κείμενο δεν περιέχει ΕΤΟΙΜΟ ΠΑΡΑΔΕΙΓΜΑ ΚΩΔΙΚΑ, ΑΠΑΓΟΡΕΥΕΤΑΙ να επινοήσεις δικό σου.\n"
                f"Αν η πληροφορία ΔΕΝ υπάρχει μέσα, πες ΑΚΡΙΒΩΣ: 'Στο αρχείο {target_file_name} δεν βρέθηκαν πληροφορίες για αυτό, αλλά μπορώ να ψάξω στα υπόλοιπα αρχεία του database. Θέλεις;'\n\n"
                f"ΚΕΙΜΕΝΟ ΑΡΧΕΙΟΥ:\n{custom_context}\n\nΕΡΩΤΗΣΗ: {user_text}"
            )
        else:
            message_content = (
                f"Απάντησε χρησιμοποιώντας ΑΠΟΚΛΕΙΣΤΙΚΑ τα παρακάτω κείμενα. Στο ΤΕΛΟΣ γράψε ΟΠΩΣΔΗΠΟΤΕ: 'Πηγές: [ονόματα αρχείων]'.\n\n"
                f"ΚΕΙΜΕΝΑ ΑΡΧΕΙΩΝ:\n{custom_context}\n\nΕΡΩΤΗΣΗ: {user_text}"
            )
        messages_to_send = [conversation_history[0], {"role": "user", "content": message_content}]
    else:
        conversation_history.append({"role": "user", "content": user_text})
        messages_to_send = conversation_history

    url = "http://localhost:11434/api/chat"
    payload = { "model": "llama3.1", "messages": messages_to_send, "stream": False, "options": { "temperature": 0.0, "num_ctx": 16384 } }
    
    try:
        response = requests.post(url, json=payload)
        if response.status_code == 200:
            ai_reply = response.json().get('message', {}).get('content', 'Σφάλμα.')
            if not restrict_to_pdf: conversation_history.append({"role": "assistant", "content": ai_reply})
            return ai_reply
        return "❌ Σφάλμα επικοινωνίας με Ollama."
    except:
        return "❌ Αδυναμία σύνδεσης στο Ollama."

def get_filename_from_input(user_input):
    if "βασ" in user_input or "bas" in user_input:
        match = re.search(r'\d+', user_input)
        if match: return f"baseis{match.group()}"
        word_to_num = {"ένα": "1", "ενα": "1", "δύο": "2", "δυο": "2", "τρία": "3", "τρια": "3", "τέσσερα": "4", "τεσσερα": "4"}
        for word, num in word_to_num.items():
            if word in user_input.split(): return f"baseis{num}"
        return "baseis"
    words = user_input.split()
    idx = -1
    if "αρχείο" in words: idx = words.index("αρχείο")
    elif "αρχειο" in words: idx = words.index("αρχειο")
    if idx != -1 and idx + 1 < len(words): return words[idx + 1].strip("?;.,!")
    return None

# --- FLASK ROUTES ---
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/chat', methods=['POST'])
def process_request():
    global loaded_pdfs, awaiting_global_search, last_pdf_question
    
    data = request.json
    is_voice = data.get('is_voice', False)
    
    # Αν πατήθηκε το μικρόφωνο, τρέχει η Python STT λειτουργία
    if is_voice:
        user_input = listen()
        if not user_input:
            return jsonify({"reply": "Δεν μπόρεσα να ακούσω τι είπες. Δοκίμασε ξανά.", "loaded_files": list(loaded_pdfs.keys())})
    else:
        user_input = data.get('text', '').lower()

    reply = ""

    # Η έξυπνη λογική ακριβώς όπως την είχαμε
    if awaiting_global_search:
        if any(w in user_input for w in ["ναι", "αμε", "ψάξε", "οκ", "κάντο", "νι"]):
            awaiting_global_search = False
            context = "\n\n".join([f"--- ΠΗΓΗ ΑΡΧΕΙΟΥ: {k} ---\n{v}" for k, v in loaded_pdfs.items()])
            reply = chat_with_ollama(last_pdf_question, restrict_to_pdf=True, custom_context=context)
        else:
            awaiting_global_search = False
            reply = "ΟΚ, ακυρώθηκε η αναζήτηση."

    elif any(w in user_input for w in ["καθάρισε", "άδειασε"]) and any(w in user_input for w in ["μνήμη", "όλα"]):
        loaded_pdfs.clear()
        reply = "Η μνήμη καθαρίστηκε πλήρως!"

    elif any(w in user_input for w in ["βγάλε", "σβήσε", "διέγραψε"]):
        fname = get_filename_from_input(user_input)
        if fname and fname in loaded_pdfs:
            del loaded_pdfs[fname]
            reply = f"Αφαιρέθηκε το αρχείο {fname}."
        else:
            reply = "Το αρχείο δεν βρέθηκε στη μνήμη."

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
        reply = f"Φορτώθηκαν επιτυχώς {count} νέα αρχεία! (Σύνολο: {len(loaded_pdfs)})"

    elif any(phrase in user_input for phrase in ["σύμφωνα με", "από το αρχείο", "βάσει", "τι λέει", "περίληψη"]):
        if not loaded_pdfs:
            reply = "Δεν έχεις φορτώσει κάποιο αρχείο ακόμα."
        else:
            target_file = get_filename_from_input(user_input)
            if target_file and target_file in loaded_pdfs:
                context = f"--- ΠΗΓΗ: {target_file} ---\n{loaded_pdfs[target_file]}"
                reply = chat_with_ollama(user_input, restrict_to_pdf=True, custom_context=context, target_file_name=target_file)
                if "στα υπόλοιπα αρχεία" in reply:
                    awaiting_global_search = True
                    clean_q = user_input.replace(target_file, "").replace("από το αρχείο", "")
                    last_pdf_question = f"Σύμφωνα με τα αρχεία, {clean_q}"
            else:
                context = "\n\n".join([f"--- ΠΗΓΗ: {k} ---\n{v}" for k, v in loaded_pdfs.items()])
                reply = chat_with_ollama(user_input, restrict_to_pdf=True, custom_context=context)

    elif any(kw in user_input for kw in ["διάβασ", "αρχείο"]):
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

    # Αν η είσοδος έγινε με φωνή, πρέπει να στείλουμε στο UI τι "άκουσε"
    response_data = {"reply": reply, "loaded_files": list(loaded_pdfs.keys())}
    if is_voice and user_input:
        response_data["user_text_from_voice"] = user_input

    return jsonify(response_data)

if __name__ == '__main__':
    # Τρέχει τον διακομιστή στην πόρτα 5000
    app.run(debug=True, port=5000)