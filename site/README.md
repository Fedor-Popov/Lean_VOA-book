# Website

A static site with the full text of the book *Vertex Operator Algebras in Lean*, chapter by chapter, as an
interactive page: every quoted Lean declaration and every Lean name in the text is linked to its line on GitHub,
every cross-reference is a link with a preview, and the text is searchable.

All content is generated from the repository by `build.py`:

- the text, from `Notes/Textbook/book.tex` and the chapter files it inputs. Chapters, sections, statements,
  equations and tables carry the book's numbers, so every reference reads as in the PDF;
- the index of Lean declarations, from the book's own index (`chapters/index.tex`);
- the main results on the overview page, from the tables in `README.md`;
- file and line of every declaration, from the sources under `VOA/`. A quoted declaration is linked only when the
  quotation matches the file at that line (whitespace and comments ignored); a name in the text is linked only to the
  declaration with exactly that full name, or to the only one whose full name ends with it;
- the Lean and Mathlib versions, from `lean-toolchain` and `lake-manifest.json`.

The site shows no history of the project. `history-edits.json` lists, per chapter file, replacements and hidden
regions that `build.py` applies to the chapter's source before converting it; the book's sources are not changed.
Remarks on how or when something changed are removed; a limit on what was verified is kept and stated in the present
tense ("not re-checked for this release"), so that no claim becomes stronger than in the book. Hidden regions are still
numbered, so all numbers stay those of the PDF. Each entry must match the source exactly once; after a new release of
the book, check the list with `python3 site/build.py --check-edits site/history-edits.json`.

Source links point at the tag at `HEAD` if there is one, otherwise at the commit, so line numbers always match the
code the site was built from. Set `LEANVOA_REF` to override.

## Local preview

`build.py` runs from the root of a clone of Lean_VOA, with `site/` copied into it:

```sh
git clone --branch v1.05 https://github.com/Fedor-Popov/Lean_VOA.git book
cp -R site book/site
cd book
python3 site/build.py
python3 -m http.server 8765 --directory site
```

Then open <http://localhost:8765>. Only Python 3.10+ is needed; no Lean build and no TeX. The first build reads every
Lean file (about 20 seconds) and caches the declarations in `site/.cache/`.

## Publishing on GitHub Pages

1. In this repository: Settings → Pages → Build and deployment → Source: **GitHub Actions** (once).
2. Push to `main`, or run the **Website** workflow by hand from the Actions tab. The workflow fetches Lean_VOA at
   `BOOK_REF`, builds the site and deploys it; the generated `data.js`, `book/`, `search.json` and `.cache/` are never
   committed.

The site is then at `https://<owner>.github.io/<repository>/`. A Pages site is public even when the repository is
private (except on GitHub Enterprise). Every link inside it is relative and navigation uses the `#` fragment, so it
works under that sub-path without server configuration.

For a new release of the book: set `BOOK_REF` in `.github/workflows/website.yml` to the new tag, check the editorial
layer against it with `python3 site/build.py --check-edits site/history-edits.json` (in a clone at that tag), and push.

## Files

| File | Role |
|---|---|
| `build.py` | converts the book, locates the Lean declarations, writes the generated files |
| `history-edits.json` | the editorial layer that removes project history from the text |
| `index.html`, `style.css`, `app.js` | the page; KaTeX renders the mathematics |
| `data.js` | generated: contents, statements, index, main results |
| `book/<chapter>.json` | generated: the text of each chapter, loaded when it is opened |
| `search.json` | generated: the text by section, loaded on the first full-text search |
| `.nojekyll` | stops GitHub Pages from running Jekyll |
