# Vertex Operator Algebras in Lean: website

The book *Vertex Operator Algebras in Lean* as an interactive page: every quoted Lean declaration and every Lean name
in the text is linked to its line on GitHub, every cross-reference is a link with a preview, and the text is
searchable.

This repository holds only the website's code (`site/`) and the workflow that publishes it. The content is built from
the public library [Fedor-Popov/Lean_VOA](https://github.com/Fedor-Popov/Lean_VOA) at the release tag named in
`.github/workflows/website.yml`; every push to `main` rebuilds and redeploys the site with GitHub Pages. See
`site/README.md`.

Local build (Python 3.10+ only; no Lean, no TeX):

```sh
git clone --branch v1.05 https://github.com/Fedor-Popov/Lean_VOA.git book
cp -R site book/site
cd book
python3 site/build.py
python3 -m http.server 8765 --directory site
```

Then open <http://localhost:8765>.
