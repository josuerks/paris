import eventlet
eventlet.monkey_patch()

from flask import Flask, request, jsonify, send_from_directory
from flask_socketio import SocketIO
import json, os, base64, time

app = Flask(__name__)
app.config["SECRET_KEY"] = "secret!"
socketio = SocketIO(app, cors_allowed_origins="*")

UPLOAD_FOLDER = "static/images"
RECU_FOLDER = "recus.json"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

DATA = {
    "MATCHS": "matchs.json",
    "PARIS": "paris.json",
    "RESULTS": "resultats.json",
    "USERS": "users.json",
    "SHOP": "shop.json",
    "RECUS": RECU_FOLDER
}

for f in DATA.values():
    if not os.path.exists(f):
        with open(f, "w") as fp:
            fp.write("[]")

def load(path):
    if not os.path.exists(path) or os.stat(path).st_size == 0:
        return []
    with open(path, "r") as fp:
        return json.load(fp)

def save(path, data):
    with open(path, "w") as fp:
        json.dump(data, fp, indent=2)

def user_obj(name):
    users = load(DATA["USERS"])
    return next((u for u in users if u["nom"] == name), None)

@app.route('/')
def home():
    return "Serveur Paris actif !"

@app.route("/send_pub", methods=["POST"])
def send_pub():
    msg = request.json.get("message", "")
    socketio.emit("pub", msg)
    return {"ok": True}

@app.route("/register", methods=["POST"])
def register():
    nom = request.json.get("nom", "").strip()
    age = int(request.json.get("age", 0))
    if age < 18:
        return {"error": "Interdit aux moins de 18 ans"}, 403
    users = load(DATA["USERS"])
    if any(u["nom"] == nom for u in users):
        return {"message": "Déjà inscrit"}, 200
    users.append({"nom": nom, "age": age, "fc": 0, "usd": 0})
    save(DATA["USERS"], users)
    return {"message": f"Bienvenue {nom}"}, 201

@app.route("/deposit", methods=["POST"])
def deposit():
    nom = request.json.get("nom")
    fc = int(request.json.get("fc", 0))
    usd = int(request.json.get("usd", 0))
    users = load(DATA["USERS"])
    user = next((u for u in users if u["nom"] == nom), None)
    if not user:
        return {"error": "Utilisateur inconnu"}, 404
    user["fc"] += fc
    user["usd"] += usd
    save(DATA["USERS"], users)
    return {"message": "Dépôt enregistré", "solde": user}, 200

@app.route("/balance/<nom>")
def balance(nom):
    user = user_obj(nom)
    if not user:
        return {"error": "Utilisateur inconnu"}, 404
    return {"fc": user["fc"], "usd": user["usd"]}

@app.route("/add_match", methods=["POST"])
def add_match():
    d = request.json
    matchs = load(DATA["MATCHS"])
    m_id = f"match_{len(matchs) + 1}"
    new_match = {"id": m_id, "equipe1": d["equipe1"], "equipe2": d["equipe2"]}
    matchs.append(new_match)
    save(DATA["MATCHS"], matchs)
    socketio.emit("new_match", new_match)
    return {"match": new_match}, 201

@app.route("/get_matchs")
def get_matchs():
    return jsonify(load(DATA["MATCHS"]))

@app.route("/parier", methods=["POST"])
def parier():
    d = request.json
    user_name = d["user"]
    match_id = d["match_id"]
    choix = d["choix"]
    devise = d["devise"]
    montant = int(d["montant"])
    users = load(DATA["USERS"])
    user = next((u for u in users if u["nom"] == user_name), None)
    if not user:
        return {"error": "Utilisateur inconnu"}, 404
    if user[devise] < montant:
        return {"error": "Solde insuffisant"}, 400
    paris = load(DATA["PARIS"])
    if any(p for p in paris if p["user"] == user_name and p["match_id"] == match_id):
        return {"error": "Déjà parié"}, 400
    user[devise] -= montant
    save(DATA["USERS"], users)
    paris.append({
        "user": user_name,
        "match_id": match_id,
        "choix": choix,
        "mise": montant,
        "devise": devise
    })
    save(DATA["PARIS"], paris)
    return {"ok": True}

@app.route("/add_resultat", methods=["POST"])
def add_result():
    r = request.json
    resultats = load(DATA["RESULTS"])
    resultats.append(r)
    save(DATA["RESULTS"], resultats)
    paris = load(DATA["PARIS"])
    users = load(DATA["USERS"])
    for p in paris:
        if p["match_id"] == r["match_id"]:
            if p["choix"] == r["gagnant"]:
                user = next((u for u in users if u["nom"] == p["user"]), None)
                if user:
                    gain = p["mise"] * 2
                    user[p["devise"]] += gain
    save(DATA["USERS"], users)
    socketio.emit("pub", f"Résultat publié pour {r['match_id']}")
    return {"ok": True}

@app.route("/get_resultat/<user>")
def get_res(user):
    paris = load(DATA["PARIS"])
    resultats = load(DATA["RESULTS"])
    matchs = load(DATA["MATCHS"])
    retour = []
    for p in paris:
        if p["user"] == user:
            match = next((m for m in matchs if m["id"] == p["match_id"]), None)
            resultat = next((r for r in resultats if r["match_id"] == p["match_id"]), None)
            if match and resultat:
                etat = "gagné" if p["choix"] == resultat["gagnant"] else "perdu"
                retour.append({
                    "match": f'{match["equipe1"]} vs {match["equipe2"]}',
                    "choix": p["choix"],
                    "gagnant": resultat["gagnant"],
                    "résultat": etat,
                    "mise": p["mise"],
                    "devise": p["devise"]
                })
    return jsonify(retour)

# --- Boutique
@app.route("/add_article", methods=["POST"])
def add_article():
    article = request.json
    shop = load(DATA["SHOP"])
    article["id"] = f"art_{len(shop)+1}"
    if "image" in article:
        try:
            img_data = base64.b64decode(article["image"])
            filename = f"image_{int(time.time())}.png"
            filepath = os.path.join(UPLOAD_FOLDER, filename)
            with open(filepath, "wb") as f:
                f.write(img_data)
            article["image"] = f"{request.url_root}static/images/{filename}"
        except Exception as e:
            return {"error": "Image invalide", "details": str(e)}, 400
    if "prix" in article and not ("prix_fc" in article or "prix_usd" in article):
        article["prix_fc"] = int(article["prix"])
        article["prix_usd"] = int(article["prix"])
    shop.append(article)
    save(DATA["SHOP"], shop)
    socketio.emit("shop_update", article)
    return jsonify(article), 201

@app.route("/get_articles")
def get_articles():
    return jsonify(load(DATA["SHOP"]))

@app.route("/acheter", methods=["POST"])
def acheter():
    data = request.get_json()
    user = data.get("user")
    article_id = data.get("article_id")
    devise = data.get("devise")

    if not user or not article_id or devise not in ["usd", "fc"]:
        return jsonify({"error": "Requête invalide"}), 400

    users = load(DATA["USERS"])
    user_data = next((u for u in users if u["nom"] == user), None)
    if not user_data:
        return jsonify({"error": "Utilisateur introuvable"}), 404

    shop = load(DATA["SHOP"])
    article = next((a for a in shop if a["id"] == article_id), None)
    if not article:
        return jsonify({"error": "Article introuvable"}), 404

    prix = article.get(f"prix_{devise}", None)
    if prix is None:
        return jsonify({"error": f"Prix non défini pour {devise.upper()}"}), 400

    prix = int(prix)
    solde = user_data.get(devise, 0)

    if solde < prix:
        return jsonify({"error": f"Solde insuffisant en {devise.upper()}"}), 400

    user_data[devise] -= prix
    save(DATA["USERS"], users)

    # --- Nouveau reçu ---
    recus = load(DATA["RECUS"])
    recu = {
        "user": user,
        "article": article,
        "devise": devise,
        "prix": prix,
        "timestamp": int(time.time())
    }
    recus.append(recu)
    save(DATA["RECUS"], recus)

    return jsonify({"message": "Article acheté avec succès", "recu": recu}), 200

@app.route("/get_recus")
def get_recus():
    user = request.args.get("user")
    if not user:
        return jsonify({"error": "Nom d'utilisateur requis"}), 400
    recus = load(DATA["RECUS"])
    return jsonify([r for r in recus if r["user"] == user])

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host="0.0.0.0", port=port)
