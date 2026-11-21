from flask import (
    Flask, render_template, request,
    redirect, url_for, session, jsonify
)
import sqlite3
import os
import tempfile
import json
import uuid
from datetime import datetime
from functools import wraps
from werkzeug.utils import secure_filename

app = Flask(__name__)

# CONFIGURATION
app.secret_key = os.environ.get(
    "SECRET_KEY", "fallou-cle-secrete-a-changer"
)
app.config["SESSION_COOKIE_SECURE"] = False
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

# MOT DE PASSE ADMINISTRATEUR CORRIGE
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "Fallou2026@")

# CONFIGURATION DES PHOTOS
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "images")

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# BASE DE DONNEES
DB_PATH = os.path.join(
    tempfile.gettempdir(),
    "fallou_boutique.db"
)

CATEGORIES = ("garcons", "filles", "chaussures")


# CONNEXION A LA BASE DE DONNEES
def connexion_db():
    connexion = sqlite3.connect(DB_PATH)
    connexion.row_factory = sqlite3.Row
    return connexion


# VERIFIER LE FORMAT DE LA PHOTO
def photo_autorisee(nom_fichier):
    return (
        "." in nom_fichier
        and nom_fichier.rsplit(".", 1)[1].lower()
        in ALLOWED_EXTENSIONS
    )


# ENREGISTRER UNE PHOTO
def enregistrer_photo(fichier):
    if not fichier or not fichier.filename:
        return None

    nom_securise = secure_filename(fichier.filename)

    if not nom_securise or not photo_autorisee(nom_securise):
        raise ValueError(
            "Format de photo non autorisé. "
            "Utilisez JPG, JPEG, PNG, GIF ou WEBP."
        )

    extension = nom_securise.rsplit(".", 1)[1].lower()
    nouveau_nom = uuid.uuid4().hex + "." + extension

    os.makedirs(UPLOAD_FOLDER, exist_ok=True)

    chemin = os.path.join(UPLOAD_FOLDER, nouveau_nom)

    fichier.save(chemin)

    return nouveau_nom


# CREATION ET MISE A JOUR DE LA BASE
def creer_base():
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)

    connexion = connexion_db()

    connexion.execute("""
        CREATE TABLE IF NOT EXISTS produits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nom TEXT NOT NULL,
            categorie TEXT NOT NULL,
            prix INTEGER NOT NULL,
            image TEXT,
            quantite INTEGER DEFAULT 0,
            statut TEXT DEFAULT 'Disponible',
            nouveaute INTEGER DEFAULT 0,
            prix_promo INTEGER DEFAULT 0
        )
    """)

    colonnes = [
        ligne["name"]
        for ligne in connexion.execute(
            "PRAGMA table_info(produits)"
        ).fetchall()
    ]

    if "quantite" not in colonnes:
        connexion.execute(
            "ALTER TABLE produits ADD COLUMN quantite INTEGER DEFAULT 0"
        )

    if "statut" not in colonnes:
        connexion.execute(
            "ALTER TABLE produits ADD COLUMN statut TEXT DEFAULT 'Disponible'"
        )

    if "nouveaute" not in colonnes:
        connexion.execute(
            "ALTER TABLE produits ADD COLUMN nouveaute INTEGER DEFAULT 0"
        )

    if "prix_promo" not in colonnes:
        connexion.execute(
            "ALTER TABLE produits ADD COLUMN prix_promo INTEGER DEFAULT 0"
        )

    connexion.execute("""
        CREATE TABLE IF NOT EXISTS commandes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nom_client TEXT NOT NULL,
            telephone TEXT NOT NULL,
            adresse TEXT NOT NULL,
            articles TEXT NOT NULL,
            total INTEGER NOT NULL,
            date_commande TEXT NOT NULL
        )
    """)

    connexion.commit()
    connexion.close()


creer_base()


# PROTECTION ADMINISTRATEUR
def admin_requis(fonction):
    @wraps(fonction)
    def verification(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("admin"))

        return fonction(*args, **kwargs)

    return verification


# PAGE D'ACCUEIL
@app.route("/")
def accueil():
    connexion = connexion_db()

    produits = connexion.execute(
        "SELECT * FROM produits ORDER BY id DESC"
    ).fetchall()

    connexion.close()

    return render_template(
        "index.html",
        produits=produits,
        categories=CATEGORIES
    )


# CONNEXION ADMINISTRATEUR
@app.route("/admin", methods=["GET", "POST"])
def admin():
    if request.method == "POST":
        mot_de_passe = request.form.get("mot_de_passe", "")

        if mot_de_passe == ADMIN_PASSWORD:
            session["admin"] = True
            return redirect(url_for("tableau_bord"))

        return "Mot de passe incorrect !"

    return render_template("admin.html")


# TABLEAU DE BORD AVEC STATISTIQUES ET GRAPHIQUE
@app.route("/tableau-bord")
@admin_requis
def tableau_bord():
    connexion = connexion_db()

    produits = connexion.execute(
        "SELECT * FROM produits ORDER BY id DESC"
    ).fetchall()

    total_produits = connexion.execute(
        "SELECT COUNT(*) FROM produits"
    ).fetchone()[0]

    total_stock = connexion.execute(
        "SELECT COALESCE(SUM(quantite), 0) FROM produits"
    ).fetchone()[0]

    total_commandes = connexion.execute(
        "SELECT COUNT(*) FROM commandes"
    ).fetchone()[0]

    chiffre_affaires = connexion.execute(
        "SELECT COALESCE(SUM(total), 0) FROM commandes"
    ).fetchone()[0]

    # NOMBRE TOTAL D'ARTICLES VENDUS
    articles_vendus = connexion.execute(
        "SELECT articles FROM commandes"
    ).fetchall()

    nombre_articles_vendus = 0

    for commande in articles_vendus:
        try:
            articles = json.loads(commande["articles"])

            for article in articles:
                nombre_articles_vendus += int(article["quantite"])

        except (TypeError, ValueError, KeyError, json.JSONDecodeError):
            continue

    # VENTES PAR JOUR
    ventes = connexion.execute(
        "SELECT date_commande, total FROM commandes ORDER BY id ASC"
    ).fetchall()

    ventes_par_jour = {}

    for vente in ventes:
        try:
            jour = vente["date_commande"].split(" à ")[0]

            if jour not in ventes_par_jour:
                ventes_par_jour[jour] = 0

            ventes_par_jour[jour] += int(vente["total"])

        except (TypeError, ValueError, IndexError):
            continue

    stats_ventes = [
        {"jour": jour, "total": total}
        for jour, total in ventes_par_jour.items()
    ]

    stats_ventes = stats_ventes[-7:]

    # ALERTES DE STOCK
    produits_stock_faible = connexion.execute(
        """
        SELECT * FROM produits
        WHERE quantite < 5 AND quantite > 0
        ORDER BY quantite ASC
        """
    ).fetchall()

    produits_epuises = connexion.execute(
        """
        SELECT * FROM produits
        WHERE quantite = 0
        """
    ).fetchall()

    connexion.close()

    return render_template(
        "tableau_bord.html",
        produits=produits,
        total_produits=total_produits,
        total_stock=total_stock,
        total_commandes=total_commandes,
        chiffre_affaires=chiffre_affaires,
        nombre_articles_vendus=nombre_articles_vendus,
        stats_ventes=stats_ventes,
        produits_stock_faible=produits_stock_faible,
        produits_epuises=produits_epuises
    )


# HISTORIQUE DES COMMANDES
@app.route("/commandes")
@admin_requis
def commandes():
    connexion = connexion_db()

    liste_commandes = connexion.execute(
        "SELECT * FROM commandes ORDER BY id DESC"
    ).fetchall()

    connexion.close()

    commandes_affichees = []

    for commande in liste_commandes:
        commande_dict = dict(commande)

        try:
            commande_dict["articles"] = json.loads(
                commande_dict["articles"]
            )
        except (TypeError, json.JSONDecodeError):
            commande_dict["articles"] = []

        commandes_affichees.append(commande_dict)

    return render_template(
        "commandes.html",
        commandes=commandes_affichees
    )


# AJOUTER UN PRODUIT AVEC PHOTO, NOUVEAUTE ET PROMOTION
@app.route("/ajouter", methods=["POST"])
@admin_requis
def ajouter_produit():
    nom = request.form.get("nom", "").strip()
    categorie = request.form.get("categorie", "")
    prix = request.form.get("prix", "").strip()
    quantite = request.form.get("quantite", "").strip()
    prix_promo = request.form.get("prix_promo", "0").strip()

    nouveaute = 1 if request.form.get("nouveaute") == "1" else 0

    if prix_promo == "":
        prix_promo = "0"

    if (
        not nom
        or categorie not in CATEGORIES
        or not prix.isdigit()
        or not quantite.isdigit()
        or not prix_promo.isdigit()
        or int(prix) <= 0
    ):
        return "Informations du produit invalides."

    prix = int(prix)
    prix_promo = int(prix_promo)

    if prix_promo < 0 or prix_promo >= prix:
        if prix_promo != 0:
            return "Le prix promotionnel doit être inférieur au prix normal."

    try:
        image = enregistrer_photo(request.files.get("image"))
    except ValueError as erreur:
        return str(erreur), 400

    quantite = int(quantite)
    statut = "Disponible" if quantite > 0 else "Épuisé"

    connexion = connexion_db()

    connexion.execute(
        """
        INSERT INTO produits
        (nom, categorie, prix, image, statut, quantite, nouveaute, prix_promo)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            nom,
            categorie,
            prix,
            image,
            statut,
            quantite,
            nouveaute,
            prix_promo
        )
    )

    connexion.commit()
    connexion.close()

    return redirect(url_for("tableau_bord"))


# MODIFIER UN PRODUIT AVEC PHOTO, NOUVEAUTE ET PROMOTION
@app.route("/modifier/<int:id>", methods=["POST"])
@admin_requis
def modifier_produit(id):
    nom = request.form.get("nom", "").strip()
    categorie = request.form.get("categorie", "")
    prix = request.form.get("prix", "").strip()
    quantite = request.form.get("quantite", "").strip()
    prix_promo = request.form.get("prix_promo", "0").strip()

    nouveaute = 1 if request.form.get("nouveaute") == "1" else 0

    if prix_promo == "":
        prix_promo = "0"

    if (
        not nom
        or categorie not in CATEGORIES
        or not prix.isdigit()
        or not quantite.isdigit()
        or not prix_promo.isdigit()
        or int(prix) <= 0
    ):
        return "Informations de modification invalides."

    prix = int(prix)
    prix_promo = int(prix_promo)

    if prix_promo < 0 or prix_promo >= prix:
        if prix_promo != 0:
            return "Le prix promotionnel doit être inférieur au prix normal."

    connexion = connexion_db()

    produit_existant = connexion.execute(
        "SELECT image FROM produits WHERE id = ?",
        (id,)
    ).fetchone()

    if produit_existant is None:
        connexion.close()
        return "Produit introuvable.", 404

    # GARDER L'ANCIENNE PHOTO PAR DEFAUT
    image = produit_existant["image"]

    try:
        nouvelle_image = enregistrer_photo(
            request.files.get("image")
        )
    except ValueError as erreur:
        connexion.close()
        return str(erreur), 400

    # REMPLACER LA PHOTO SI UNE NOUVELLE EST CHOISIE
    if nouvelle_image:
        image = nouvelle_image

    quantite = int(quantite)
    statut = "Disponible" if quantite > 0 else "Épuisé"

    connexion.execute(
        """
        UPDATE produits
        SET nom = ?,
            categorie = ?,
            prix = ?,
            image = ?,
            quantite = ?,
            statut = ?,
            nouveaute = ?,
            prix_promo = ?
        WHERE id = ?
        """,
        (
            nom,
            categorie,
            prix,
            image,
            quantite,
            statut,
            nouveaute,
            prix_promo,
            id
        )
    )

    connexion.commit()
    connexion.close()

    return redirect(url_for("tableau_bord"))


# SUPPRIMER UN PRODUIT
@app.route("/supprimer/<int:id>", methods=["POST"])
@admin_requis
def supprimer_produit(id):
    connexion = connexion_db()

    connexion.execute(
        "DELETE FROM produits WHERE id = ?",
        (id,)
    )

    connexion.commit()
    connexion.close()

    return redirect(url_for("tableau_bord"))


# VERIFIER LE STOCK ET ENREGISTRER LA COMMANDE
@app.route("/valider-commande", methods=["POST"])
def valider_commande():
    donnees = request.get_json(silent=True)

    if not donnees or not isinstance(donnees.get("articles"), list):
        return jsonify({
            "succes": False,
            "message": "Commande invalide."
        }), 400

    client = donnees.get("client", {})

    if not isinstance(client, dict):
        return jsonify({
            "succes": False,
            "message": "Informations du client invalides."
        }), 400

    nom_client = str(client.get("nom", "")).strip()
    telephone = str(client.get("telephone", "")).strip()
    adresse = str(client.get("adresse", "")).strip()

    if not nom_client or not telephone or not adresse:
        return jsonify({
            "succes": False,
            "message": "Veuillez remplir le nom, le téléphone et l'adresse."
        }), 400

    articles = donnees["articles"]

    if not articles:
        return jsonify({
            "succes": False,
            "message": "Votre panier est vide."
        }), 400

    # REGROUPER LES PRODUITS IDENTIQUES
    quantites = {}

    for article in articles:
        try:
            produit_id = int(article["id"])
            quantite = int(article["quantite"])
        except (KeyError, TypeError, ValueError):
            return jsonify({
                "succes": False,
                "message": "Informations de commande invalides."
            }), 400

        if produit_id <= 0 or quantite <= 0:
            return jsonify({
                "succes": False,
                "message": "Quantité ou produit invalide."
            }), 400

        quantites[produit_id] = (
            quantites.get(produit_id, 0) + quantite
        )

    connexion = connexion_db()

    try:
        connexion.execute("BEGIN IMMEDIATE")

        details_commande = []
        total = 0

        # VERIFIER LES PRODUITS ET CALCULER LE TOTAL
        for produit_id, quantite_demandee in quantites.items():
            produit = connexion.execute(
                """
                SELECT id, nom, prix, prix_promo, quantite, statut
                FROM produits
                WHERE id = ?
                """,
                (produit_id,)
            ).fetchone()

            if produit is None:
                connexion.rollback()
                return jsonify({
                    "succes": False,
                    "message": "Un produit de votre panier n'existe plus."
                }), 400

            stock = int(produit["quantite"] or 0)

            if (
                stock < quantite_demandee
                or str(produit["statut"]).lower().strip() != "disponible"
            ):
                connexion.rollback()
                return jsonify({
                    "succes": False,
                    "message": (
                        "Stock insuffisant pour "
                        + produit["nom"]
                        + ". Stock disponible : "
                        + str(stock)
                    )
                }), 400

            prix_normal = int(produit["prix"])
            prix_promotionnel = int(produit["prix_promo"] or 0)

            if 0 < prix_promotionnel < prix_normal:
                prix = prix_promotionnel
            else:
                prix = prix_normal

            sous_total = prix * quantite_demandee
            total += sous_total

            details_commande.append({
                "id": produit_id,
                "nom": produit["nom"],
                "prix": prix,
                "prix_normal": prix_normal,
                "quantite": quantite_demandee,
                "sous_total": sous_total
            })

        # DIMINUER LE STOCK
        for produit_id, quantite_demandee in quantites.items():
            connexion.execute(
                """
                UPDATE produits
                SET quantite = quantite - ?,
                    statut = CASE
                        WHEN quantite - ? > 0 THEN 'Disponible'
                        ELSE 'Épuisé'
                    END
                WHERE id = ?
                """,
                (quantite_demandee, quantite_demandee, produit_id)
            )

        # ENREGISTRER LA COMMANDE
        date_commande = datetime.now().strftime("%d/%m/%Y à %H:%M")

        connexion.execute(
            """
            INSERT INTO commandes
            (nom_client, telephone, adresse, articles, total, date_commande)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                nom_client,
                telephone,
                adresse,
                json.dumps(details_commande, ensure_ascii=False),
                total,
                date_commande
            )
        )

        commande_id = connexion.execute(
            "SELECT last_insert_rowid()"
        ).fetchone()[0]

        connexion.commit()

        return jsonify({
            "succes": True,
            "message": "Commande enregistrée et stock mis à jour.",
            "commande_id": commande_id,
            "client": {
                "nom": nom_client,
                "telephone": telephone,
                "adresse": adresse
            },
            "articles": details_commande,
            "total": total
        })

    except Exception:
        connexion.rollback()

        return jsonify({
            "succes": False,
            "message": "Une erreur est survenue lors de l'enregistrement."
        }), 500

    finally:
        connexion.close()


# GESTION DES FICHIERS TROP VOLUMINEUX
@app.errorhandler(413)
def fichier_trop_volumineux(erreur):
    return "La photo est trop volumineuse. Maximum : 5 Mo.", 413


# DECONNEXION
@app.route("/deconnexion")
@admin_requis
def deconnexion():
    session.clear()
    return redirect(url_for("admin"))


# LANCEMENT DU SITE
if __name__ == "__main__":
    creer_base()

    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True
    )