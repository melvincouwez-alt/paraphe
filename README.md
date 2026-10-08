# Paraphe

[English](README.en.md)

Éditeur de PDF pour elementary OS, écrit en Python avec GTK 4 et Granite. L'interface est en français.

- Annoter : surligner (couleurs pastel), souligner, barrer, écrire du texte directement sur la page (taille au choix, de 8 à 24 pt, retour à la ligne automatique), ajouter des notes, dessiner à main levée, encadrer. Chaque outil garde sa couleur. Avec l'outil de sélection, on peut déplacer, modifier ou supprimer une annotation (touche Suppr). La gomme efface les annotations sur lesquelles on passe.
- Enregistrement automatique, à activer dans le menu.
- Remplir les formulaires : champs texte sur une ou plusieurs lignes, cases à cocher, boutons radio, listes.
- Signer à la main : dessiner une signature, ou importer un scan dont le fond devient transparent. Les signatures sont gardées dans `~/.local/share/paraphe/signatures/` et se posent d'un clic ou en traçant leur taille.
- Signer avec un certificat : fichier PKCS#12 (.p12, .pfx), signature visible (cachet en Noto Sans) ou invisible, grâce à pyHanko. Tant que le fichier reste le même, l'enregistrement est incrémental et garde les signatures existantes valides.
- Mode « Pages » (Ctrl+Maj+P, bouton dans la barre d'en-tête) : toutes les pages en grand, à réordonner par glisser-déposer, avec une barre d'actions sur la sélection (ajouter un PDF, découper, y compris après les pages choisies, extraire, dupliquer, pivoter, supprimer). On peut aussi déposer un fichier entre deux pages. La colonne des miniatures du mode « Annoter » garde les mêmes actions dans son menu.
- Fusionner plusieurs PDF, découper un document (une page par fichier, toutes les N pages ou selon des plages), enregistrer une copie aplatie où annotations et champs sont figés.
- Imprimer (Ctrl+P, bouton imprimante) le document tel qu'il s'affiche, annotations, champs remplis et signatures compris.
- Annuler et rétablir chaque modification (Ctrl+Z, Ctrl+Maj+Z).

## Installer

Télécharger le `.deb` de la [dernière version](https://github.com/melvincouwez-alt/paraphe/releases/latest), puis :

```
sudo apt install ./paraphe_<version>_amd64.deb
```

## Lancer depuis les sources

```
python3 -m venv --system-site-packages .venv
.venv/bin/pip install pymupdf "pyhanko[opentype]"
./run.sh fichier.pdf
```

Il faut `python3-gi`, `python3-gi-cairo`, `gir1.2-gtk-4.0` et `gir1.2-granite-7.0`.

## Paquet

`packaging/build-deb.sh` produit `dist/paraphe_<version>_amd64.deb`. PyMuPDF et pyHanko y sont embarqués dans `/usr/lib/paraphe/vendor`.

## Tests

`tests/samples.py <dossier>` crée des PDF d'exemple (texte, formulaire, page pivotée). Pour lancer l'appli sans fenêtre visible, on peut la démarrer dans un gala headless sur une session D-Bus privée (`tests/nested.sh`). `PARAPHE_DEV_SCRIPT` exécute alors un script Python qui reçoit la fenêtre, et `PARAPHE_DEV_CAPTURE` enregistre une capture PNG avant de quitter.

## Licence et crédits

AGPL-3.0 ou ultérieure, la licence de PyMuPDF (Artifex) sur lequel Paraphe repose.

- [PyMuPDF](https://github.com/pymupdf/PyMuPDF) (Artifex) : AGPL-3.0
- [pyHanko](https://github.com/MatthiasValvekens/pyHanko) (Matthias Valvekens) : MIT
- [uharfbuzz](https://github.com/harfbuzz/uharfbuzz) : Apache-2.0, et [fontTools](https://github.com/fonttools/fonttools) : MIT, pour le cachet de signature
- GTK et [Granite](https://github.com/elementary/granite) (elementary)
- L'icône reprend la courbe du symbole PDF des [icônes elementary](https://github.com/elementary/icons) (GPL-3.0)

La liste complète des bibliothèques embarquées dans le paquet `.deb`, avec leurs textes de licence, est dans [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Le paquet l'installe aussi dans `/usr/share/doc/paraphe/`.
