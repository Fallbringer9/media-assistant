

# Media Assistant

## Présentation

Media Assistant est un projet backend serverless conçu pour générer automatiquement une voix synthétique et des sous‑titres à partir d’un texte.

L’objectif principal de ce projet n’est pas de créer un produit commercial mais de pratiquer la conception d’une architecture cloud moderne en utilisant les services managés d’AWS.

Le système prend un texte en entrée et génère automatiquement :

- un fichier audio (.mp3) grâce à Amazon Polly
- un fichier de sous‑titres en français (.srt)
- un fichier de sous‑titres en anglais (.srt) généré via Amazon Translate

Le traitement est entièrement **asynchrone et scalable**, basé sur une architecture événementielle.

Ce projet a été conçu dans une démarche d’apprentissage. Je me suis aidé d’outils d’intelligence artificielle pour certaines parties de génération de code et pour accélérer certaines implémentations, mais l’architecture, la logique du système et les choix techniques ont été réfléchis et construits manuellement.

Je suis actuellement en **apprentissage autodidacte du cloud et du développement backend**, et ce projet fait partie de mon travail personnel pour comprendre comment construire des systèmes distribués modernes.

---

## Architecture

Le projet repose sur une architecture serverless orientée événements.

Client → API Gateway → Lambda API → DynamoDB + SQS → Lambda Processor → Polly / Translate → S3 → URL signées

Flux détaillé :

1. Le client envoie une requête HTTP pour créer un job.
2. La Lambda API valide la requête et enregistre le job dans DynamoDB avec le statut **PENDING**.
3. L’identifiant du job est envoyé dans une file **SQS**.
4. Une Lambda worker (processor) consomme le message.
5. Le processor :

   - récupère le texte
   - génère l’audio avec Amazon Polly
   - traduit le texte avec Amazon Translate
   - génère les fichiers de sous‑titres

6. Les fichiers générés sont stockés dans **Amazon S3**.
7. Le statut du job est mis à jour en **DONE** dans DynamoDB.
8. L’utilisateur peut récupérer les fichiers via des **URLs S3 pré‑signées**.

---

## Services AWS utilisés

Le projet utilise volontairement des briques cloud fondamentales :

- AWS API Gateway (HTTP API)
- AWS Lambda
- Amazon SQS
- Amazon DynamoDB
- Amazon S3
- Amazon Polly
- Amazon Translate
- AWS CloudWatch
- AWS CDK (Infrastructure as Code)

---

## Endpoints Backend

### POST /jobs

Crée un nouveau job de génération.

Exemple de requête :

{ "text": "Bonjour et bienvenue dans mon projet cloud.", "voice": "female" }

Réponse :

{ "jobId": "...", "status": "PENDING" }

---

### GET /jobs/{jobId}

Permet de récupérer le statut du job.

Exemple de réponse :

{ "jobId": "...", "status": "DONE", "voice": "female", "audioUrl": "...", "subtitleFrUrl": "...", "subtitleEnUrl": "..." }

Les URLs retournées sont des **URLs S3 pré‑signées temporaires**.

---

## Infrastructure

Toute l’infrastructure est définie en **Infrastructure as Code avec AWS CDK (Python)**.

La stack déploie automatiquement :

- une table DynamoDB pour stocker les jobs
- une file SQS avec Dead Letter Queue
- un bucket S3 pour stocker les fichiers générés
- une Lambda API
- une Lambda worker pour le traitement
- un endpoint API Gateway
- les rôles et permissions IAM nécessaires

---

## Structure du projet

frontend/

Interface frontend minimale (placeholder).

infra/

Infrastructure cloud définie avec AWS CDK.

services/api/

Lambda responsable de la création des jobs et de la récupération de leur statut.

services/processor/

Lambda worker responsable de la génération audio et des sous‑titres.

---

## Concepts cloud pratiqués dans ce projet

Ce projet illustre plusieurs patterns backend classiques :

- architecture serverless
- traitement asynchrone
- pattern queue / worker
- architecture événementielle
- Infrastructure as Code
- génération d’URLs pré‑signées pour l’accès sécurisé aux fichiers

---

## Objectif du projet

Ce projet est avant tout **un projet d’apprentissage personnel**.

Il m’a permis de pratiquer :

- la conception d’architectures cloud
- l’utilisation de plusieurs services AWS ensemble
- la mise en place d’un backend scalable
- la construction d’une infrastructure complète avec CDK

L’objectif n’est pas de créer un produit fini mais de **comprendre comment les systèmes backend cloud sont réellement construits**.

---

## Améliorations possibles

Extensions possibles du projet :

- ajout d’une authentification avec Amazon Cognito
- mise en place de rate limiting et protection API
- pipeline CI/CD
- amélioration de la génération des sous‑titres
- interface frontend complète

---

## Auteur

Projet réalisé dans le cadre de mon apprentissage autodidacte du développement backend et du cloud.

Certaines parties du code ont été générées avec l’aide d’outils d’intelligence artificielle, utilisés comme assistance pour accélérer le développement et approfondir ma compréhension des architectures cloud.