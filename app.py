
import os
from datetime import datetime
from functools import wraps

from flask import (
    Flask, render_template, request,
    redirect, url_for, session, jsonify
)

from supabase import create_client
import cloudinary
import cloudinary.uploader


app = Flask(__name__)

# =====================================
# CONFIGURATION
# =====================================

app.secret_key = os.environ.get("SECRET_KEY")

if not app.secret_key:
    raise RuntimeError("La variable SECRET_KEY manque dans Render.")

app.config["SESSION_COOKIE_SECURE"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")

if not ADMIN_PASSWORD:
    raise RuntimeError("La variable ADMIN_PASSWORD manque dans Render.")

CATEGORIES = ("garcons", "filles", "chaussures")

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}


# =====================================
# CONNEXION SUPABASE
# =====================================

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("Configuration Supabase incomplète.")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


# =====================================
# CONFIGURATION CLOUDINARY
# =====================================

CLOUDINARY_CLOUD_NAME = os.environ.get("CLOUDINARY_CLOUD_NAME")
CLOUDINARY_API_KEY = os.environ.get("CLOUDINARY_API_KEY")
CLOUDINARY_API_SECRET = os.environ.get("CLOUDINARY_API_SECRET")

if not all([
    CLOUDINARY_CLOUD_NAME,
    CLOUDINARY_API_KEY,
    CLOUDINARY_API_SECRET
]):
    raise RuntimeError("Configuration Cloudinary incomplète.")

cloudinary.config(
    cloud_name=CLOUDINARY_CLOUD_NAME,
    api_key=CLOUDINARY_API_KEY,
    api_secret=CLOUDINARY_API_SECRET,
    secure=True
)


# =====================================
# GESTION DES PHOTOS
# =====================================

def photo_autorisee(nom_fichier):
    return (
        "." in nom_fichier
        and nom_fichier.rsplit(".", 1)[1].lower()
        in ALLOWED_EXTENSIONS
    )


def enregistrer_photo(fichier):

    if not fichier or not fichier.filename:
        return None

    if not photo_autorisee(fichier.filename):
        raise ValueError(
            "Format de photo non autorisé. "
            "Utilisez JPG, JPEG, PNG, GIF ou WEBP."
        )

    resultat = cloudinary.uploader.upload(
        fichier.stream,
        folder="fallou_globale_business/produits",
        resource_type="image"
    )

    return resultat.get("secure_url")


# =====================================
# FONCTIONS SUPABASE
# =====================================

def recuperer_produits():

    resultat = (
        supabase.table("produits")
        .select("*")
        .order("id", desc=True)
        .execute()
    )

    return resultat.data or []


def recuperer_commandes():

    resultat = (
        supabase.table("commandes")
        .select("*")
        .order("id", desc=True)
        .execute()
    )

    return resultat.data or []


def statut_stock(quantite):

    return "Disponible" if int(quantite) > 0 else "Épuisé"


def articles_commande(commande):

    articles = commande.get("articles", [])

    if isinstance(articles, str):
        import json

        try:
            articles = json.loads(articles)
        except (ValueError, TypeError):
            articles = []

    return articles if isinstance(articles, list) else []


# =====================================
# PROTECTION ADMINISTRATEUR
# =====================================

def admin_requis(fonction):

    @wraps(fonction)
    def verification(*args, **kwargs):

        if not session.get("admin"):
            return redirect(url_for("admin"))

        return fonction(*args, **kwargs)

    return verification


# =====================================
# PAGE ACCUEIL
# =====================================

@app.route("/")
def accueil():

    produits = recuperer_produits()

    return render_template(
        "index.html",
        produits=produits,
        categories=CATEGORIES
    )


# =====================================
# CONNEXION ADMIN
# =====================================

@app.route("/admin", methods=["GET", "POST"])
def admin():

    if request.method == "POST":

        mot_de_passe = request.form.get(
            "mot_de_passe", ""
        )

        if mot_de_passe == ADMIN_PASSWORD:

            session["admin"] = True

            return redirect(url_for("tableau_bord"))

        return "Mot de passe incorrect !", 401

    return render_template("admin.html")


# =====================================
# TABLEAU DE BORD
# =====================================

@app.route("/tableau-bord")
@admin_requis
def tableau_bord():

    produits = recuperer_produits()
    commandes = recuperer_commandes()

    total_produits = len(produits)

    total_stock = sum(
        int(p.get("quantite") or 0)
        for p in produits
    )

    total_commandes = len(commandes)

    chiffre_affaires = sum(
        int(c.get("total") or 0)
        for c in commandes
    )

    nombre_articles_vendus = 0
    ventes_par_jour = {}

    for commande in commandes:

        for article in articles_commande(commande):

            try:
                nombre_articles_vendus += int(
                    article.get("quantite", 0)
                )
            except (ValueError, TypeError):
                pass

        date = str(
            commande.get("date_commande", "")
        )

        jour = date.split(" à ")[0]

        if jour:

            ventes_par_jour[jour] = (
                ventes_par_jour.get(jour, 0)
                + int(commande.get("total") or 0)
            )

    stats_ventes = [
        {"jour": jour, "total": total}
        for jour, total in list(ventes_par_jour.items())[-7:]
    ]

    produits_stock_faible = [
        p for p in produits
        if 0 < int(p.get("quantite") or 0) < 5
    ]

    produits_epuises = [
        p for p in produits
        if int(p.get("quantite") or 0) == 0
    ]

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


# =====================================
# HISTORIQUE DES COMMANDES
# =====================================

@app.route("/commandes")
@admin_requis
def commandes():

    liste_commandes = recuperer_commandes()

    commandes_affichees = []

    for commande in liste_commandes:

        commande_dict = dict(commande)

        commande_dict["articles"] = articles_commande(
            commande_dict
        )

        commandes_affichees.append(commande_dict)

    return render_template(
        "commandes.html",
        commandes=commandes_affichees
    )


# =====================================
# AJOUTER UN PRODUIT
# =====================================

@app.route("/ajouter", methods=["POST"])
@admin_requis
def ajouter_produit():

    nom = request.form.get("nom", "").strip()
    categorie = request.form.get("categorie", "")
    prix = request.form.get("prix", "").strip()
    quantite = request.form.get("quantite", "").strip()

    prix_promo = request.form.get(
        "prix_promo", "0"
    ).strip()

    nouveaute = (
        1 if request.form.get("nouveaute") == "1"
        else 0
    )

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
        return "Informations du produit invalides.", 400

    prix = int(prix)
    quantite = int(quantite)
    prix_promo = int(prix_promo)

    if prix_promo != 0 and prix_promo >= prix:
        return (
            "Le prix promotionnel doit être inférieur au prix normal.",
            400
        )

    try:

        image = enregistrer_photo(
            request.files.get("image")
        )

    except ValueError as erreur:

        return str(erreur), 400

    except Exception:

        app.logger.exception(
            "Erreur pendant l'envoi de la photo"
        )

        return "Impossible d'envoyer la photo.", 500

    nouveau_produit = {
        "nom": nom,
        "categorie": categorie,
        "prix": prix,
        "image": image,
        "quantite": quantite,
        "statut": statut_stock(quantite),
        "nouveaute": nouveaute,
        "prix_promo": prix_promo
    }

    try:

        supabase.table("produits").insert(
            nouveau_produit
        ).execute()

    except Exception:

        app.logger.exception("Erreur ajout produit")

        return "Impossible d'enregistrer le produit.", 500

    return redirect(url_for("tableau_bord"))


# =====================================
# MODIFIER UN PRODUIT
# =====================================

@app.route("/modifier/<int:id>", methods=["POST"])
@admin_requis
def modifier_produit(id):

    nom = request.form.get("nom", "").strip()
    categorie = request.form.get("categorie", "")
    prix = request.form.get("prix", "").strip()
    quantite = request.form.get("quantite", "").strip()

    prix_promo = request.form.get(
        "prix_promo", "0"
    ).strip()

    nouveaute = (
        1 if request.form.get("nouveaute") == "1"
        else 0
    )

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
        return "Informations de modification invalides.", 400

    prix = int(prix)
    quantite = int(quantite)
    prix_promo = int(prix_promo)

    if prix_promo != 0 and prix_promo >= prix:
        return (
            "Le prix promotionnel doit être inférieur au prix normal.",
            400
        )

    try:

        resultat = (
            supabase.table("produits")
            .select("*")
            .eq("id", id)
            .execute()
        )

        if not resultat.data:
            return "Produit introuvable.", 404

        produit_existant = resultat.data[0]

        image = produit_existant.get("image")

        nouvelle_image = enregistrer_photo(
            request.files.get("image")
        )

        if nouvelle_image:
            image = nouvelle_image

        modifications = {
            "nom": nom,
            "categorie": categorie,
            "prix": prix,
            "image": image,
            "quantite": quantite,
            "statut": statut_stock(quantite),
            "nouveaute": nouveaute,
            "prix_promo": prix_promo
        }

        (
            supabase.table("produits")
            .update(modifications)
            .eq("id", id)
            .execute()
        )

    except ValueError as erreur:

        return str(erreur), 400

    except Exception:

        app.logger.exception(
            "Erreur modification produit"
        )

        return "Impossible de modifier le produit.", 500

    return redirect(url_for("tableau_bord"))


# =====================================
# SUPPRIMER UN PRODUIT
# =====================================

@app.route("/supprimer/<int:id>", methods=["POST"])
@admin_requis
def supprimer_produit(id):

    try:

        supabase.table("produits").delete().eq(
            "id", id
        ).execute()

    except Exception:

        app.logger.exception(
            "Erreur suppression produit"
        )

        return "Impossible de supprimer le produit.", 500

    return redirect(url_for("tableau_bord"))


# =====================================
# VALIDER UNE COMMANDE
# =====================================

@app.route("/valider-commande", methods=["POST"])
def valider_commande():

    donnees = request.get_json(silent=True)

    if (
        not donnees
        or not isinstance(donnees.get("articles"), list)
    ):
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

    nom_client = str(
        client.get("nom", "")
    ).strip()

    telephone = str(
        client.get("telephone", "")
    ).strip()

    adresse = str(
        client.get("adresse", "")
    ).strip()

    if not nom_client or not telephone or not adresse:
        return jsonify({
            "succes": False,
            "message": (
                "Veuillez remplir le nom, le téléphone et l'adresse."
            )
        }), 400

    articles = donnees["articles"]

    if not articles:
        return jsonify({
            "succes": False,
            "message": "Votre panier est vide."
        }), 400

    # REGROUPER LES QUANTITES DES PRODUITS IDENTIQUES

    quantites = {}

    try:

        for article in articles:

            produit_id = int(article["id"])
            quantite = int(article["quantite"])

            if produit_id <= 0 or quantite <= 0:
                raise ValueError()

            quantites[produit_id] = (
                quantites.get(produit_id, 0) + quantite
            )

        articles_valides = [
            {
                "id": produit_id,
                "quantite": quantite
            }
            for produit_id, quantite in quantites.items()
        ]

    except (KeyError, TypeError, ValueError):

        return jsonify({
            "succes": False,
            "message": "Informations de commande invalides."
        }), 400

    date_commande = datetime.now().strftime(
        "%d/%m/%Y à %H:%M"
    )

    try:

        resultat = supabase.rpc(
            "valider_commande",
            {
                "p_nom_client": nom_client,
                "p_telephone": telephone,
                "p_adresse": adresse,
                "p_articles": articles_valides,
                "p_date_commande": date_commande
            }
        ).execute()

        donnees_resultat = resultat.data

        if isinstance(donnees_resultat, list):

            donnees_resultat = donnees_resultat[0]

        if not isinstance(donnees_resultat, dict):
            raise ValueError("Réponse Supabase invalide.")

        return jsonify({
            "succes": True,
            "message": "Commande enregistrée et stock mis à jour.",
            "commande_id": donnees_resultat.get("commande_id"),
            "client": {
                "nom": nom_client,
                "telephone": telephone,
                "adresse": adresse
            },
            "articles": donnees_resultat.get("articles", []),
            "total": donnees_resultat.get("total", 0)
        })

    except Exception:

        app.logger.exception(
            "Erreur validation commande"
        )

        return jsonify({
            "succes": False,
            "message": (
                "Impossible d'enregistrer la commande. "
                "Vérifiez le stock ou réessayez."
            )
        }), 400


# =====================================
# GESTION DES FICHIERS TROP VOLUMINEUX
# =====================================

@app.errorhandler(413)
def fichier_trop_volumineux(erreur):

    return (
        "La photo est trop volumineuse. Maximum : 5 Mo.",
        413
    )


# =====================================
# DECONNEXION
# =====================================

@app.route("/deconnexion")
@admin_requis
def deconnexion():

    session.clear()

    return redirect(url_for("admin"))


# =====================================
# LANCEMENT
# =====================================

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=5000,
        debug=False
    )
