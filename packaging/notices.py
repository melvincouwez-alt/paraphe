#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Paraphe contributors
"""Write THIRD_PARTY_NOTICES.md (in French) from the bundled Python packages:
notices.py <vendor dir> > THIRD_PARTY_NOTICES.md. The license texts are the
files each package ships in its .dist-info folder, copied as they are."""

import email.parser
import pathlib
import sys

GPL3 = pathlib.Path("/usr/share/common-licenses/GPL-3")

HEAD = """\
# Composants tiers

Paraphe est publié sous licence AGPL-3.0 ou ultérieure (fichier `LICENSE`).
Le paquet `.deb` embarque, dans `/usr/lib/paraphe/vendor`, les bibliothèques
Python ci-dessous, installées telles quelles avec pip. Toutes ont une licence
compatible avec l'AGPL-3.0. Leurs textes de licence d'origine suivent, en
anglais, sans modification.

| Paquet | Version | Licence |
|---|---|---|
"""

NATIVE = """
## Bibliothèques natives incluses dans ces paquets

Certains paquets contiennent du code compilé qui reprend d'autres projets :

- PyMuPDF contient MuPDF (Artifex, AGPL-3.0) et les bibliothèques que MuPDF
  intègre (FreeType, HarfBuzz, jbig2dec, lcms2, libjpeg, OpenJPEG, zlib,
  Gumbo, Tesseract, Leptonica, Brotli), chacune sous sa propre licence libre.
  Voir https://mupdf.com/licensing et le dossier `thirdparty` des sources de
  MuPDF.
- cryptography contient OpenSSL (Apache-2.0) et des modules Rust sous licences
  MIT ou Apache-2.0.
- lxml contient libxml2 et libxslt (MIT), voir son fichier `LICENSES.txt`.
- uharfbuzz contient HarfBuzz (licence MIT « Old MIT »).

## Icône de l'application

La courbe du symbole PDF vient de l'icône `application-pdf` du thème
[elementary icons](https://github.com/elementary/icons), sous GPL-3.0. Le mot
« PDF » est tracé en chemins vectoriels à partir de la police Inter Display
(SIL Open Font License 1.1) : la police elle-même n'est pas distribuée.
Le texte de la GPL-3.0 figure à la fin de ce fichier.
"""


def main(vendor):
    rows, texts = [], []
    for info in sorted(pathlib.Path(vendor).glob("*.dist-info"), key=lambda p: p.name.lower()):
        meta = email.parser.Parser().parsestr((info / "METADATA").read_text(errors="replace"))
        name, version = meta["Name"], meta["Version"]
        lic = meta["License-Expression"] or (meta["License"] or "").splitlines()[0]
        urls = dict(u.split(", ", 1) for u in meta.get_all("Project-URL") or [])
        url = next((urls[k] for k in urls if k.lower() in ("source", "source code", "github", "repository", "homepage", "code")),
                   meta["Home-page"] or "")
        if name.lower() == "pymupdf":
            lic = "AGPL-3.0 (double licence, Paraphe suit l'AGPL)"
        rows.append(f"| [{name}]({url}) | {version} | {lic} |" if url else f"| {name} | {version} | {lic} |")
        files = sorted(f for f in info.rglob("*") if f.is_file() and f.name.upper().startswith(("LICEN", "COPYING", "NOTICE")))
        texts.append(f"\n## {name} {version}\n")
        for f in files:
            body = f.read_text(errors="replace").strip()
            if name.lower() == "pymupdf" and "AFFERO" in body[:400]:
                body = "Texte de la GNU AGPL-3.0, identique au fichier LICENSE de Paraphe."
            texts.append(f"\n`{f.relative_to(info)}`\n\n````text\n{body}\n````\n")
    out = [HEAD, "\n".join(rows), "\n", NATIVE, "\n# Textes de licence\n", *texts]
    if GPL3.exists():
        out.append(f"\n## GPL-3.0 (icônes elementary)\n\n````text\n{GPL3.read_text().strip()}\n````\n")
    sys.stdout.write("".join(out))


if __name__ == "__main__":
    main(sys.argv[1])
