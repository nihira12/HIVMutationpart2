import os
import sys
from threading import Timer

import pandas as pd
from flask import Flask, jsonify, request

app = Flask(__name__, static_folder='.', static_url_path='')

# -------------------------------------------------------------------
# Mutation database (loaded from mutations.csv instead of being
# hardcoded, so all 26 curated mutations are actually available)
# -------------------------------------------------------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(BASE_DIR, 'mutations.csv')
COOCCURRENCE_CSV_PATH = os.path.join(BASE_DIR, 'cooccurrence.csv')
INTERACTIONS_CSV_PATH = os.path.join(BASE_DIR, 'interactions.csv')


def load_mutation_database():
    df = pd.read_csv(CSV_PATH)

    # The frontend expects a "Recommendation" field. Derive it from the
    # Resistance level so every row (not just two hardcoded ones) has one.
    def recommend(resistance):
        resistance = str(resistance).strip().lower()
        if resistance == 'high':
            return 'Avoid'
        if resistance == 'intermediate':
            return 'Use With Caution'
        return 'Likely Effective'

    df['Recommendation'] = df['Resistance'].apply(recommend)
    return df


mutation_database = load_mutation_database()
cooccurrence_database = pd.read_csv(COOCCURRENCE_CSV_PATH)
interaction_database = pd.read_csv(INTERACTIONS_CSV_PATH)

SEVERITY_WEIGHT = {'Critical': 40, 'High': 25, 'Moderate': 12, 'Low': 5}

# -------------------------------------------------------------------
# Page Navigation Routes
# -------------------------------------------------------------------

@app.route('/')
def serve_landing():
    """First page user sees (http://localhost:5000/)"""
    return app.send_static_file('landing.html')


@app.route('/app')
def serve_index():
    """Main application page (http://localhost:5000/app)"""
    return app.send_static_file('index.html')

# -------------------------------------------------------------------
# API Endpoints
# -------------------------------------------------------------------

@app.route('/api/mutations', methods=['GET'])
def get_mutations():
    """Return the full mutation database."""
    return jsonify(mutation_database.to_dict(orient='records'))


@app.route('/api/search', methods=['GET'])
def search_mutations():
    """Search the mutation database by mutation, gene, drug, or drug class."""
    query = request.args.get('q', '').strip().upper()

    if query == '':
        return jsonify(mutation_database.to_dict(orient='records'))

    mask = (
        mutation_database['Mutation'].str.upper().str.contains(query, na=False)
        | mutation_database['Gene'].str.upper().str.contains(query, na=False)
        | mutation_database['Drug'].str.upper().str.contains(query, na=False)
        | mutation_database['Drug_Class'].str.upper().str.contains(query, na=False)
    )
    results = mutation_database[mask]
    return jsonify(results.to_dict(orient='records'))


@app.route('/api/analyze', methods=['POST'])
def analyze():
    """
    Look for known resistance mutations inside a submitted sequence /
    mutation list and return a real risk score instead of a fixed
    canned response.

    Accepts JSON body: {"sequence": "...", "mutations": ["M184V", ...]}
    Either field is optional but at least one should be present.
    """
    data = request.get_json(silent=True) or {}
    sequence = str(data.get('sequence', '') or '').upper()
    submitted = [str(m).strip().upper() for m in data.get('mutations', []) if str(m).strip()]

    # Detect any known mutation codes that appear as substrings of the
    # free-text sequence (e.g. pasted FASTA/notes), in addition to any
    # explicitly submitted mutation list.
    found = set(submitted)
    for code in mutation_database['Mutation']:
        if code.upper() in sequence:
            found.add(code.upper())

    matches = mutation_database[mutation_database['Mutation'].str.upper().isin(found)]

    risk = min(100, sum(SEVERITY_WEIGHT.get(s, 5) for s in matches['Severity']))
    if not len(matches):
        risk = 5  # baseline residual risk when nothing recognized

    return jsonify({
        'status': 'success',
        'risk': risk,
        'mutations': matches.to_dict(orient='records'),
    })


@app.route('/api/cooccurrence', methods=['GET'])
def get_cooccurrence():
    """
    Return the curated mutation co-occurrence dataset used to draw the
    resistance-pathway network. Optionally filter to only pairs where at
    least one mutation is in the given comma-separated `mutations` list.
    """
    only = request.args.get('mutations', '').strip()
    df = cooccurrence_database
    if only:
        wanted = {m.strip().upper() for m in only.split(',') if m.strip()}
        mask = (
            df['Mutation_A'].str.upper().isin(wanted)
            | df['Mutation_B'].str.upper().isin(wanted)
        )
        df = df[mask]
    return jsonify(df.to_dict(orient='records'))


@app.route('/api/interactions', methods=['GET', 'POST'])
def get_interactions():
    """
    Cross-check a submitted list of drugs against the curated drug-drug
    interaction table. Accepts either a GET with ?drugs=a,b,c or a POST
    body of {"drugs": ["a", "b", "c"]}. With no drugs submitted, returns
    the full interaction reference table.
    """
    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        drugs = [str(d).strip() for d in data.get('drugs', []) if str(d).strip()]
    else:
        raw = request.args.get('drugs', '').strip()
        drugs = [d.strip() for d in raw.split(',') if d.strip()]

    if not drugs:
        return jsonify(interaction_database.to_dict(orient='records'))

    wanted = {d.upper() for d in drugs}
    mask = (
        interaction_database['Drug_A'].str.upper().isin(wanted)
        & interaction_database['Drug_B'].str.upper().isin(wanted)
    )
    flagged = interaction_database[mask]
    return jsonify(flagged.to_dict(orient='records'))


@app.route('/api/chat', methods=['POST'])
def chat():
    """
    Very small rules-based assistant: if the user's message mentions a
    known mutation, answer with real data from the database instead of
    an unconditional canned reply.
    """
    data = request.get_json(silent=True) or {}
    message = str(data.get('message', '') or '')
    message_upper = message.upper()

    hit = mutation_database[
        mutation_database['Mutation'].str.upper().apply(lambda m: m in message_upper)
    ]

    if len(hit):
        row = hit.iloc[0]
        response = (
            f"{row['Mutation']} is a {row['Severity'].lower()}-severity {row['Drug_Class']} "
            f"mutation ({row['Gene']}, codon {row['Codon']}). {row['Description']} "
            f"Recommendation: {row['Recommendation']} regarding {row['Drug']}."
        )
    else:
        response = (
            "I don't have a specific match for that in the current mutation database. "
            "Try asking about a specific mutation (e.g. 'M184V') or drug class "
            "(NRTI, NNRTI, PI, INSTI)."
        )

    return jsonify({'response': response})

# -------------------------------------------------------------------
# Execution Entry Point
# -------------------------------------------------------------------

def open_browser():
    url = 'http://127.0.0.1:5000/'
    import webbrowser
    if not webbrowser.open(url):
        if sys.platform == 'win32':
            os.system(f'start {url}')


if __name__ == '__main__':
    print("=" * 50)
    print(" HIV Resistance Intelligence Server")
    print(f" Mutations      : {len(mutation_database)}")
    print(f" Co-occurrences : {len(cooccurrence_database)}")
    print(f" Interactions   : {len(interaction_database)}")
    print(" Landing : http://127.0.0.1:5000/")
    print(" App     : http://127.0.0.1:5000/app")
    print("=" * 50)

    app.run(
        host='127.0.0.1',
        port=5000,
        debug=True,
        use_reloader=False
    )