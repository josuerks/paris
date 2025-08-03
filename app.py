import eventlet
eventlet.monkey_patch()

from flask import Flask, request, jsonify
from flask_socketio import SocketIO
import json, os, base64, time

app = Flask(__name__)
app.config["SECRET_KEY"] = "secret!"
socketio = SocketIO(app, cors_allowed_origins="*")

UPLOAD_FOLDER = "static/images"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

DATA = {
    "USERS": "users.json",
    "SHOP": "shop.json",
    "RECUS": "recus.json"
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

@app.route("/")
def home():
    return "Serveur Vente en ligne actif !"

@app.route("/send_pub", methods=["POST"])
def send_pub():
    msg = request.json.get("message", "")
    socketio.emit("pub", msg)
    return {"ok": True}

@app.route("/register", methods=["POST"])
def register():
    nom = request.json.get("nom", "").strip()
    age = int(request.json.get("age", 0))
    if age < 12:
        return {"error": "Trop jeune"}, 403
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

@app.route("/add_article", methods=["POST"])
def add_article():
    article = request.json
    shop = load(DATA["SHOP"])
    article["id"] = f"art_{len(shop)+1}"

    if "quantite" not in article:
        article["quantite"] = 1

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

    recus = load(DATA["RECUS"])
    recu = {
        "id": f"recu_{len(recus)+1}",
        "user": user,
        "article": article,  # ✅ ici on met tout l'article, pas juste description
        "devise": devise,
        "montant": prix,
        "timestamp": int(time.time()),
        "livre": False
    }
    recus.append(recu)
    save(DATA["RECUS"], recus)

    if "quantite" in article:
        article["quantite"] -= 1
        if article["quantite"] <= 0:
            shop = [a for a in shop if a["id"] != article_id]
        else:
            for i in range(len(shop)):
                if shop[i]["id"] == article_id:
                    shop[i] = article
        save(DATA["SHOP"], shop)

    return jsonify({"message": "Article acheté avec succès", "recu": recu}), 200

@app.route("/get_recus/<nom>")
def get_recus(nom):
    all_recus = load(DATA["RECUS"])
    user_recus = [r for r in all_recus if r["user"] == nom]
    return jsonify(user_recus)

@app.route("/confirmer_livraison", methods=["POST"])
def confirmer_livraison():
    id_recu = request.json.get("id")
    if not id_recu:
        return {"error": "ID requis"}, 400
    recus = load(DATA["RECUS"])
    for r in recus:
        if r.get("id") == id_recu:
            r["livre"] = True
            save(DATA["RECUS"], recus)
            return {"message": "Livraison confirmée"}, 200
    return {"error": "Reçu introuvable"}, 404

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host="0.0.0.0", port=port)

