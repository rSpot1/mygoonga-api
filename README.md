# MyGoonga — API (FastAPI)

API backend de MyGoonga, application de vérification collaborative de médias et
d'événements locaux. Ce dépôt contient uniquement l'API (le client Flutter fait
l'objet d'un livrable séparé).

L'API implémente les deux piliers du cahier des charges :
- **Pilier 1** — indices de cohérence technique d'un média (métadonnées EXIF, analyse
  ELA, recherche d'image inversée via Hugging Face)
- **Pilier 2** — confirmation d'événements locaux par des utilisateurs vérifiés à
  proximité (flags pondérés, statut agrégé transparent)

Elle ne rend jamais de verdict binaire ("ceci est faux") et ne prend jamais de décision
automatique sur les demandes de statut vérificateur : l'algorithme signale, le
modérateur décide.

---

## 1. Démarrage rapide (sans rien configurer)

L'API démarre par défaut en **mode test** : base de données en mémoire, stockage de
fichiers en local, authentification simulable via des en-têtes de debug. Vous pouvez
donc tester toutes les routes immédiatement, sans compte Firebase ni token Hugging Face.

```bash
cd mygoonga-api
python3 -m venv .venv
source .venv/bin/activate        # Windows : .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Ou simplement :

```bash
./scripts/run_dev.sh
```

Ouvrez ensuite `http://localhost:8000/docs` : documentation interactive Swagger, avec
toutes les routes du cahier des charges, testables directement dans le navigateur.

### Authentification en mode test

Sans Firebase configuré, remplacez l'en-tête `Authorization: Bearer <token>` par :

| En-tête | Rôle |
|---|---|
| `X-Debug-Uid: alice` | identifiant de l'utilisateur simulé |
| `X-Debug-Role: verifier` | optionnel — rôle attribué à la création du compte (`standard`, `verifier`, `moderator`, `admin`) |

Exemple :

```bash
curl -X POST http://localhost:8000/auth/sync -H "X-Debug-Uid: alice"

curl http://localhost:8000/users/me -H "X-Debug-Uid: alice"

curl -X POST http://localhost:8000/auth/sync -H "X-Debug-Uid: momo" -H "X-Debug-Role: moderator"
curl http://localhost:8000/verifiers/applications -H "X-Debug-Uid: momo" -H "X-Debug-Role: moderator"
```

**Important** : ce mode debug n'est actif que si `DEBUG_MODE=true` (valeur par défaut
en local). Sur Render, `DEBUG_MODE=false` désactive complètement ce chemin — seuls les
vrais tokens Firebase sont acceptés.

### Données de test envoyées avec de vrais fichiers

Pour tester l'analyse de média ou la demande de statut vérificateur (upload multipart) :

```bash
curl -X POST http://localhost:8000/media/analyze \
  -H "X-Debug-Uid: alice" \
  -F "file=@photo.jpg" \
  -F "context=reçu sur WhatsApp"

curl -X POST http://localhost:8000/verifiers/apply \
  -H "X-Debug-Uid: alice" \
  -F "phoneNumber=+237600000000" \
  -F "cniFront=@cni_recto.jpg" \
  -F "cniBack=@cni_verso.jpg" \
  -F "verificationPhoto=@selfie.jpg"
```

---

## 2. Passer en configuration réelle (Firebase + Google Sign-In)

### 2.1 Créer le projet Firebase

1. Allez sur [console.firebase.google.com](https://console.firebase.google.com) → *Ajouter un projet*.
2. Dans **Authentication → Sign-in method**, activez :
   - **E-mail/Mot de passe**
   - **Google** — renseignez un nom public et une adresse de support ; Firebase génère
     automatiquement l'OAuth Client ID web nécessaire.
3. Dans **Firestore Database**, créez une base en mode production (les règles de
   sécurité Firestore par défaut bloquent tout accès client direct — c'est voulu :
   toutes les écritures/lectures sensibles passent par cette API, pas par le client
   Flutter directement).
4. Dans **Storage**, activez le bucket par défaut.

### 2.2 Générer la clé de service (Admin SDK)

Dans **Paramètres du projet → Comptes de service → Générer une nouvelle clé privée**.
Cela télécharge un fichier JSON. Deux façons de le fournir à l'API :

- **En local** : enregistrez-le (ex: `secrets/firebase-service-account.json`), puis
  dans `.env` :
  ```
  FIREBASE_CREDENTIALS_PATH=./secrets/firebase-service-account.json
  ```
- **Sur Render** (ou tout hébergeur sans système de fichiers persistant pratique) :
  collez le **contenu JSON complet** dans la variable d'environnement
  `FIREBASE_CREDENTIALS_JSON` (voir section Render plus bas).

Ne commitez jamais ce fichier dans git — `secrets/` est déjà ignoré par `.gitignore`.

### 2.3 Variables à renseigner

```
USE_MOCK_DB=false
STORAGE_MODE=firebase
FIREBASE_PROJECT_ID=votre-projet-id
FIREBASE_STORAGE_BUCKET=votre-projet-id.appspot.com
FIREBASE_CREDENTIALS_JSON={"type":"service_account", ... }
DEBUG_MODE=false
```

### 2.4 Règles de sécurité Firebase Storage (CNI restreintes)

Le principe de confidentialité du cahier des charges (§6, §11) exige que les documents
d'identité ne soient **jamais** accessibles autrement que par un modérateur, via cette
API. Dans **Storage → Rules**, appliquez :

```
rules_version = '2';
service firebase.storage {
  match /b/{bucket}/o {
    // Dossier CNI : aucune lecture/écriture directe depuis le client.
    // Seule cette API (Admin SDK, qui contourne les règles Storage) y accède.
    match /cni/{allPaths=**} {
      allow read, write: if false;
    }
    // Médias soumis à analyse : lecture publique, écriture réservée aux utilisateurs
    // authentifiés (ici aussi, en pratique, tout passe par l'API).
    match /media/{allPaths=**} {
      allow read: if true;
      allow write: if false;
    }
  }
}
```

L'API utilise le SDK Admin côté serveur, qui n'est **pas soumis** à ces règles : elle
seule peut lire/écrire dans `cni/`. Le client Flutter n'a donc jamais d'accès direct
au bucket Storage — il passe toujours par les endpoints `/verifiers/apply` et
`/verifiers/applications/{id}` (URLs signées, expirantes, journalisées).

### 2.5 Règles Firestore

Puisque toute la logique métier (rôles, agrégation des flags, confidentialité CNI)
est appliquée côté API, les règles Firestore côté client doivent rester fermées :

```
rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {
    match /{document=**} {
      allow read, write: if false;
    }
  }
}
```

Le client Flutter ne parle jamais directement à Firestore : uniquement à cette API,
avec le token Firebase Auth en en-tête `Authorization: Bearer <token>`.

### 2.6 Rôles utilisateurs

Contrairement à une approche par *custom claims* Firebase, le rôle (`standard`,
`verifier`, `moderator`, `admin`) est stocké dans le document Firestore
`users/{uid}` et contrôlé côté serveur à chaque requête (dépendance
`require_roles(...)` dans `app/core/security.py`). C'est cette API qui fait foi, pas
le token du client. Pour créer votre premier compte admin, deux options :

- promouvoir un compte existant directement dans la console Firestore
  (`users/{uid}.role = "admin"`),
- ou temporairement démarrer en `USE_MOCK_DB=true` pour créer un admin de test via
  `X-Debug-Role: admin`, valider le flux, puis repasser en configuration réelle.

---

## 3. Intégration Hugging Face

Utilisée pour la recherche d'image inversée (Pilier 1, fonctionnalité "nice to have"
du MVP) et, en option, la transcription audio et la similarité de texte.

1. Créez un compte sur [huggingface.co](https://huggingface.co).
2. Générez un token d'accès : **Settings → Access Tokens → New token** (droits *Read*
   suffisent pour l'API d'inférence).
3. Renseignez dans `.env` :
   ```
   HUGGINGFACE_API_TOKEN=hf_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   HF_CLIP_MODEL=openai/clip-vit-base-patch32
   HF_WHISPER_MODEL=openai/whisper-small
   HF_SENTENCE_MODEL=sentence-transformers/all-MiniLM-L6-v2
   ```

Sans ce token, l'API reste pleinement fonctionnelle : l'analyse de cohérence
(métadonnées + ELA) continue de fonctionner normalement, et la réponse indique
simplement que la recherche d'image inversée n'est pas disponible plutôt que
d'échouer.

**Limite assumée du MVP** : la recherche d'image inversée compare l'image soumise aux
embeddings des médias déjà analysés par MyGoonga (pas un index Web externe type Google
Images). Elle détecte donc la réutilisation d'un contenu déjà vu par l'application,
pas encore une réutilisation trouvée ailleurs sur le Web — cette extension figure dans
la roadmap du cahier des charges.

---

## 4. Déploiement sur Render

### Option A — via `render.yaml` (recommandé)

1. Poussez ce dépôt sur GitHub.
2. Sur [render.com](https://render.com) : **New → Blueprint**, sélectionnez le dépôt.
   Render détecte `render.yaml` et crée le service automatiquement.
3. Render vous demandera de renseigner les variables marquées `sync: false` :
   `FIREBASE_CREDENTIALS_JSON`, `FIREBASE_PROJECT_ID`, `FIREBASE_STORAGE_BUCKET`,
   `HUGGINGFACE_API_TOKEN`.
4. Déployez. Render exécute automatiquement :
   - Build : `pip install -r requirements.txt`
   - Démarrage : `uvicorn app.main:app --host 0.0.0.0 --port $PORT`

### Option B — service Web manuel

1. **New → Web Service**, connectez le dépôt.
2. Runtime : *Python 3*.
3. Build command : `pip install -r requirements.txt`
4. Start command : `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
5. Onglet **Environment**, ajoutez les variables listées dans `.env.example`
   (au minimum celles de la section 2.3 ci-dessus, plus `DEBUG_MODE=false`).

### Option C — Docker

Un `Dockerfile` est fourni si vous préférez déployer un conteneur (Render détecte
aussi automatiquement un `Dockerfile` présent à la racine si vous choisissez
*Runtime: Docker* lors de la création du service).

Une fois déployée, l'URL Render (ex: `https://mygoonga-api.onrender.com`) est celle à
renseigner côté client Flutter comme URL de base de l'API.

---

## 5. Structure du projet

```
app/
  main.py                 point d'entrée FastAPI, montage des routeurs
  config.py                configuration (variables d'environnement)
  core/
    security.py            vérification du token Firebase, contrôle des rôles
    database.py             abstraction base de données (mémoire ou Firestore)
    firebase_admin_client.py initialisation paresseuse du SDK Firebase Admin
  services/
    storage.py               stockage de fichiers (local ou Firebase Storage)
    exif_utils.py            extraction EXIF + heuristiques de modération
    ela.py                   analyse par niveaux d'erreur (ELA)
    huggingface.py           appels à l'API d'inférence Hugging Face
    scoring.py                calcul du statut agrégé des événements locaux
  models/
    schemas.py                schémas Pydantic des requêtes/réponses
  routers/
    auth.py, users.py, verifiers.py, media.py, events.py, admin.py, files.py
```

## 6. Vue d'ensemble des endpoints

Toutes les routes (sauf `/`, `/health`, `/docs`) exigent
`Authorization: Bearer <token Firebase>` (ou les en-têtes `X-Debug-*` en mode test).

| Méthode | Route | Rôle requis |
|---|---|---|
| POST | `/auth/sync` | authentifié |
| GET/PATCH | `/users/me` | authentifié |
| POST | `/verifiers/apply` | authentifié |
| GET | `/verifiers/applications` | modérateur, admin |
| GET | `/verifiers/applications/{id}` | modérateur, admin |
| POST | `/verifiers/applications/{id}/review` | modérateur, admin |
| POST | `/media/analyze` | authentifié |
| GET | `/media/analyze/{id}` | authentifié |
| POST | `/media/analyze/{id}/request-human-review` | authentifié |
| POST | `/events/report` | authentifié |
| GET | `/events/nearby` | authentifié |
| GET | `/events/{id}` | authentifié |
| POST | `/events/{id}/flag` | authentifié |
| GET | `/admin/users` | admin |
| PATCH | `/admin/users/{id}/role` | admin |
| GET | `/admin/audit-log` | admin |

La documentation Swagger complète (schémas de requêtes/réponses, essai en direct) est
disponible sur `/docs` une fois le serveur démarré.

## 7. Limites connues du MVP (assumées, cf. cahier des charges §12)

- L'analyse ELA et l'extraction EXIF ne couvrent que les images (pas la vidéo/audio) ;
  les autres formats reçoivent une extraction de métadonnées minimale.
- La recherche d'image inversée compare uniquement aux médias déjà soumis à MyGoonga,
  pas à un index Web externe.
- Le rapprochement fin entre la position géographique récente d'un vérificateur et la
  zone d'un événement (mentionné en `/events/{id}/flag`) applique une pondération
  simple par rôle dans ce MVP ; le calcul géographique fin est laissé à la roadmap.
- La notification des utilisateurs (résultat de demande vérificateur, etc.) est
  enregistrée en base (`notifications`) mais n'est pas encore reliée à un canal push
  réel — à connecter selon le choix retenu côté Flutter (Firebase Cloud Messaging).
