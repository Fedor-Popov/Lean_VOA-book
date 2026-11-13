#!/usr/bin/env python3
"""Build the LeanVOA website from the book.

The book (Notes/Textbook/book.tex and the chapter files it inputs) is converted chapter by chapter to HTML.
The numbering of chapters, sections, statements, equations and tables is the book's, so that every cross-reference
reads as in the PDF and becomes a link. Every quoted Lean declaration is located in the library and linked to its
source line; a link is kept only when the quotation is verified against the file at that line.

    python3 site/build.py            # from the repository root

Output: site/data.js (contents, statements, index), site/book/<chapter>.json (the text), site/search.json.
"""
from __future__ import annotations

import html
import json
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

SITE = Path(__file__).resolve().parent  # outputs go next to this script
ROOT = SITE.parent
TEXDIR = ROOT / "Notes" / "Textbook"
BOOK = TEXDIR / "book.tex"
README = ROOT / "README.md"
OUT = SITE / "data.js"
CACHE = SITE / ".cache"

REPO = os.environ.get("LEANVOA_REPO", "Fedor-Popov/Lean_VOA")

warnings: list[str] = []
unknown_cmds: Counter = Counter()


def warn(msg: str) -> None:
    warnings.append(msg)


def git(*args: str) -> str | None:
    try:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def source_ref() -> tuple[str, str]:
    """The ref the source links point at: a tag exactly at HEAD if there is one, else the commit itself."""
    commit = git("rev-parse", "HEAD") or "main"
    ref = os.environ.get("LEANVOA_REF") or git("describe", "--tags", "--exact-match", "HEAD") or commit
    return ref, commit


def toolchain() -> dict:
    lean = (ROOT / "lean-toolchain").read_text().strip().split(":")[-1]
    mathlib = ""
    try:
        for p in json.loads((ROOT / "lake-manifest.json").read_text())["packages"]:
            if p["name"] == "mathlib":
                mathlib = p.get("inputRev") or p.get("rev", "")[:10]
    except (OSError, KeyError, ValueError):
        pass
    return {"lean": lean, "mathlib": mathlib}


# --------------------------------------------------------------------------------------------------------------
# Brace utilities
# --------------------------------------------------------------------------------------------------------------

def match_brace(s: str, i: int, open_: str = "{", close: str = "}") -> int:
    """s[i] == open_; return the index just past the matching close."""
    assert s[i] == open_, (s[i:i + 40], open_)
    depth = 0
    j = i
    n = len(s)
    while j < n:
        c = s[j]
        if c == "\\":
            j += 2
            continue
        if c == open_:
            depth += 1
        elif c == close:
            depth -= 1
            if depth == 0:
                return j + 1
        elif open_ == "[" and c == "{":  # brackets inside a brace group do not count
            j = match_brace(s, j)
            continue
        j += 1
    raise ValueError("unbalanced: " + s[i:i + 80])


def skip_ws(s: str, i: int) -> int:
    while i < len(s) and s[i] in " \t\n":
        i += 1
    return i


def read_arg(s: str, i: int) -> tuple[str, int]:
    """One macro argument from s[i] (spaces skipped): a brace group or a single token."""
    i = skip_ws(s, i)
    if i >= len(s):
        return "", i
    if s[i] == "{":
        j = match_brace(s, i)
        return s[i + 1:j - 1], j
    if s[i] == "\\":
        m = re.match(r"\\([A-Za-z]+|.)", s[i:], re.S)
        return m.group(0), i + len(m.group(0))
    return s[i], i + 1


def read_opt(s: str, i: int) -> tuple[str | None, int]:
    j = skip_ws(s, i)
    if j < len(s) and s[j] == "[":
        k = match_brace(s, j, "[", "]")
        return s[j + 1:k - 1], k
    return None, i


def find_env_end(s: str, j: int, env: str) -> int:
    depth = 1
    pat = re.compile(r"\\(begin|end)\{" + re.escape(env) + r"\}")
    for m in pat.finditer(s, j):
        depth += 1 if m.group(1) == "begin" else -1
        if depth == 0:
            return m.start()
    raise ValueError("no end of " + env)


# --------------------------------------------------------------------------------------------------------------
# Verbatim, comments, macros
# --------------------------------------------------------------------------------------------------------------

def extract_verbatim(s: str, store: list) -> str:
    """leancode/plaincode environments and \\verb become placeholders \\x03N\\x03 (before anything else)."""
    def env_rep(m):
        store.append(("block", m.group(1), m.group(2).strip("\n")))
        return "\x03%d\x03" % (len(store) - 1)
    s = re.sub(r"\\begin\{(leancode|plaincode)\}(.*?)\\end\{\1\}", env_rep, s, flags=re.S)

    def verb_rep(m):
        store.append(("inline", "verb", m.group(2)))
        return "\x03%d\x03" % (len(store) - 1)
    return re.sub(r"\\verb\*?([^A-Za-z\s])(.*?)\1", verb_rep, s)


def strip_tex_comments(s: str) -> str:
    """A % (not \\%) removes the rest of the line, the newline and the next line's leading spaces."""
    return re.sub(r"(?<!\\)%[^\n]*(\n[ \t]*)?", "", s)


def parse_providecommands(body: str) -> tuple[dict, str]:
    macros: dict[str, tuple[int, str]] = {}
    out = []
    i = 0
    pat = re.compile(r"\\(?:providecommand|newcommand|renewcommand)\s*\{?\\([A-Za-z]+)\}?")
    while True:
        m = pat.search(body, i)
        if not m:
            out.append(body[i:])
            break
        out.append(body[i:m.start()])
        j = m.end()
        nargs_s, j = read_opt(body, j)
        nargs = int(nargs_s) if nargs_s else 0
        j = skip_ws(body, j)
        if j >= len(body) or body[j] != "{":
            out.append(body[m.start():j])
            i = j
            continue
        k = match_brace(body, j)
        defn = body[j + 1:k - 1]
        if "\\directlua" in defn:
            defn = "\\lean{#1}"  # these macros only typeset a Lean name or a file name with break points
        elif m.group(1) != "arraystretch":
            macros[m.group(1)] = (nargs, defn)
        if "\\directlua" in body[j + 1:k - 1]:
            macros[m.group(1)] = (nargs, defn)
        i = k
    return macros, "".join(out)


def _needs_group(rep: str) -> bool:
    return bool(rep) and not rep.startswith("{") and ("^" in rep or "_" in rep or " " in rep.strip())


def expand_macros(s: str, macros: dict) -> str:
    if not macros:
        return s
    names = sorted(macros, key=len, reverse=True)
    pat = re.compile(r"\\(" + "|".join(re.escape(n) for n in names) + r")(?![A-Za-z])")
    for _ in range(12):
        if not pat.search(s):
            return s
        out = []
        i = 0
        while True:
            m = pat.search(s, i)
            if not m:
                out.append(s[i:])
                break
            out.append(s[i:m.start()])
            nargs, defn = macros[m.group(1)]
            j = m.end()
            args = []
            for _a in range(nargs):
                a, j = read_arg(s, j)
                args.append(a)
            rep = defn
            for n_, a in enumerate(args, 1):
                rep = rep.replace("#%d" % n_, a)
            if nargs == 0 and j < len(s) and s[j] == "{" and s[j:j + 2] == "{}":
                j += 2  # \bookrelease{}
            if nargs == 0 and j < len(s) and s[j].isalpha() and re.search(r"\\[A-Za-z]+$", rep):
                rep += " "
            if rep[:1].isalpha() and out and re.search(r"\\[A-Za-z]+$", out[-1]):
                rep = " " + rep
            out.append(rep if nargs else "{" + rep + "}" if _needs_group(rep) else rep)
            i = j
        s = "".join(out)
    warn("macro expansion did not terminate")
    return s


# --------------------------------------------------------------------------------------------------------------
# Editorial layer: the site shows no project history
# --------------------------------------------------------------------------------------------------------------
#
# site/history-edits.json lists, per chapter file, replacements {"old", "new"} and hidden regions {"start", "end"}
# applied to the chapter's source before conversion; the book's sources are not changed. "old", "start" and "end"
# are exact substrings occurring once in the file. A hidden region is converted (so that numbering stays the
# book's) but not shown.

EDITS = SITE / "history-edits.json"
HIDE_OPEN, HIDE_CLOSE = "\x0eHIDE\x0e", "\x0fHIDE\x0f"


def verbatim_spans(text: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in re.finditer(r"\\begin\{(leancode|plaincode)\}.*?\\end\{\1\}", text, re.S)]


def balanced(t: str) -> str | None:
    """None if braces and environments balance in t, else what is wrong."""
    u = re.sub(r"\\[{}]", "", t)
    d = 0
    for c in u:
        d += (c == "{") - (c == "}")
        if d < 0:
            return "a } closes a group opened before"
    if d:
        return "%d unclosed {" % d
    stack = []
    for m in re.finditer(r"\\(begin|end)\{([^}]*)\}", t):
        if m.group(1) == "begin":
            stack.append(m.group(2))
        elif not stack or stack.pop() != m.group(2):
            return "\\end{%s} without its \\begin" % m.group(2)
    if stack:
        return "\\begin{%s} without its \\end" % stack[-1]
    return None


def plan_edits(fname: str, text: str, entries: list[dict]) -> tuple[list[tuple[int, int, str, str]], list[str]]:
    """Spans (start, end, kind, new) on the original text, and the errors."""
    spans, errors = [], []
    verb = verbatim_spans(text)

    def once(sub: str, what: str) -> int | None:
        if not sub:
            errors.append("%s: empty %s" % (fname, what))
            return None
        n = text.count(sub)
        if n != 1:
            errors.append("%s: %s occurs %d times: %s" % (fname, what, n, sub[:90].replace("\n", " ")))
            return None
        return text.index(sub)
    for e in entries:
        if "old" in e:
            i = once(e["old"], "old")
            if i is None:
                continue
            j = i + len(e["old"])
            new = e.get("new", "")
            b1, b2 = balanced(e["old"]), balanced(new)
            if (b1 is None) != (b2 is None) or (b1 and b1 != b2):
                errors.append("%s: replacement changes the grouping (%s / %s): %s" % (fname, b1, b2, e["old"][:80]))
                continue
            spans.append((i, j, "edit", new))
        elif "start" in e:
            i = once(e["start"], "start")
            k = once(e["end"], "end")
            if i is None or k is None:
                continue
            j = k + len(e["end"])
            if j <= i:
                errors.append("%s: hidden region ends before it starts: %s" % (fname, e["start"][:60]))
                continue
            b = balanced(text[i:j])
            if b:
                errors.append("%s: hidden region is not a whole unit (%s): %s" % (fname, b, e["start"][:60]))
                continue
            spans.append((i, j, "hide", ""))
        else:
            errors.append("%s: entry without old or start" % fname)
    spans.sort()
    for a, b in zip(spans, spans[1:]):
        if a[1] > b[0]:
            errors.append("%s: overlapping entries at %r and %r" % (fname, text[a[0]:a[0] + 50], text[b[0]:b[0] + 50]))
    for a, b, kind, _n in spans:
        if kind == "edit" and any(v0 < b and a < v1 for v0, v1 in verb):
            errors.append("%s: an edit touches quoted Lean or verbatim text: %r" % (fname, text[a:a + 60]))
    return spans, errors


def apply_edits(text: str, spans: list) -> str:
    out = []
    last = 0
    for a, b, kind, new in spans:
        if a < last:
            continue  # overlapping: reported, skipped
        out.append(text[last:a])
        out.append(HIDE_OPEN + text[a:b] + HIDE_CLOSE if kind == "hide" else new)
        last = b
    out.append(text[last:])
    return "".join(out)


def load_edits(paths: list[Path]) -> dict[str, list[dict]]:
    merged: dict[str, list[dict]] = {}
    for p in paths:
        if not p.is_file():
            continue
        data = json.loads(p.read_text(encoding="utf-8"))
        for f, entries in data.items():
            merged.setdefault(f, []).extend(entries)
    return merged


def check_edits(paths: list[Path]) -> int:
    """python3 site/build.py --check-edits FILE...: report errors and references left pointing at removed labels."""
    edits = load_edits(paths)
    chdir = TEXDIR / "chapters"
    removed: dict[str, str] = {}
    errors: list[str] = []
    texts = {p.name: p.read_text(encoding="utf-8") for p in sorted(chdir.glob("*.tex"))}
    kept: dict[str, str] = {}
    for f, t in texts.items():
        spans, errs = plan_edits(f, t, edits.get(f, []))
        errors += errs
        for f2 in edits:
            if f2 not in texts:
                errors.append("unknown file " + f2)
        for a, b, kind, new in spans:
            gone = set(re.findall(r"\\label\{([^}]*)\}", t[a:b])) - set(re.findall(r"\\label\{([^}]*)\}", new))
            for g in gone:
                removed[g] = f
        kept[f] = apply_edits(t, spans)
        kept[f] = re.sub(re.escape(HIDE_OPEN) + ".*?" + re.escape(HIDE_CLOSE), "", kept[f], flags=re.S)
    for f, t in kept.items():
        for m in re.finditer(r"\\(?:ref|eqref|pageref)\{([^}]*)\}", t):
            if m.group(1) in removed:
                line = t[:m.start()].count("\n") + 1
                errors.append("%s (about line %d of the edited text): still refers to %s, removed in %s" % (
                    f, line, m.group(1), removed[m.group(1)]))
    for e in sorted(set(errors)):
        print(e)
    n = sum(len(v) for v in edits.values())
    print("%d entries checked, %d problems" % (n, len(set(errors))))
    return 1 if errors else 0


# --------------------------------------------------------------------------------------------------------------
# Labels and numbering
# --------------------------------------------------------------------------------------------------------------

LABELS: dict[str, dict] = {}       # key -> {ch, num, id, sec}
STATEMENTS: list[dict] = []
THEOREM_KINDS = {"definition": "Definition", "example": "Example", "remark": "Remark", "theorem": "Theorem",
                 "proposition": "Proposition", "lemma": "Lemma", "corollary": "Corollary", "conjecture": "Conjecture"}
BOXES = {"dictionary": "From the mathematics to the Lean statement", "warning": "Trap / dead end",
         "status": "What the machine verified", "physics": "Physical meaning"}


def anchor_of(key: str) -> str:
    return "l-" + re.sub(r"[^A-Za-z0-9_-]", "-", key)


# --------------------------------------------------------------------------------------------------------------
# Math
# --------------------------------------------------------------------------------------------------------------

NUMBERED = {"equation", "align", "gather", "multline"}
STARRED = {"equation*", "align*", "gather*", "multline*"}


def clean_math(m: str) -> str:
    m = m.replace("\\allowbreak", "")

    def lean_in_math(mm):
        name = mm.group(1).replace("\\_", "_").replace("_", "\\_").replace("#", "\\#")
        return "\\text{\\texttt{" + name + "}}"
    m = re.sub(r"\\lean\{([^{}]*)\}", lean_in_math, m)
    m = re.sub(r"\\textup\{", r"\\text{", m)
    m = m.replace("\\textsc{", "\\text{")
    m = m.replace("\\mathscr{", "\\mathcal{")
    m = re.sub(r"\\(big|Big|bigg|Bigg)([lrm]?)\s*\\\{", r"\\\1\2\\{", m)
    # KaTeX has no psmallmatrix
    m = m.replace("\\begin{psmallmatrix}", "\\left(\\begin{smallmatrix}").replace("\\end{psmallmatrix}", "\\end{smallmatrix}\\right)")
    m = m.replace("\\begin{bsmallmatrix}", "\\left[\\begin{smallmatrix}").replace("\\end{bsmallmatrix}", "\\end{smallmatrix}\\right]")
    m = re.sub(r"\\(math[a-z]+)\s*\\\1\b", r"\\\1", m)  # a doubled font command in the source
    m = re.sub(r"\\qed\b", r"\\square", m)
    # references inside a formula become the plain number (resolved with the others, see resolve_refs)
    m = re.sub(r"\\(eqref|ref)\{([^}]*)\}", lambda r: "\x04m%s:%s\x04" % (r.group(1), r.group(2)), m)
    return m


def split_rows(body: str) -> list[str]:
    """Split an align/gather body at top-level \\\\ (not inside braces or nested environments)."""
    rows, depth, envd, cur, i = [], 0, 0, [], 0
    while i < len(body):
        if body.startswith("\\begin{", i):
            envd += 1
        elif body.startswith("\\end{", i):
            envd -= 1
        c = body[i]
        if c == "\\" and i + 1 < len(body) and body[i + 1] == "\\" and depth == 0 and envd == 0:
            rows.append("".join(cur))
            cur = []
            i += 2
            opt = re.match(r"\s*\[[^\]]*\]", body[i:])
            if opt:
                i += opt.end()
            continue
        if c == "\\":
            cur.append(body[i:i + 2])
            i += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        cur.append(c)
        i += 1
    rows.append("".join(cur))
    if rows and not rows[-1].strip():
        rows.pop()
    return rows


class MathCtx:
    def __init__(self, conv: "Converter"):
        self.conv = conv

    def protect(self, s: str) -> str:
        """Replace math by placeholders \\x00N\\x00 (in document order, numbering equations as the book does)."""
        conv = self.conv
        store = conv.math

        def put(tex: str, display: bool, labels=(), num=None) -> str:
            store.append({"tex": tex, "display": display, "labels": list(labels), "num": num})
            return "\x00%d\x00" % (len(store) - 1)

        envs = "|".join(re.escape(e) for e in NUMBERED | STARRED)
        pat = re.compile(r"\\begin\{(" + envs + r")\}(.*?)\\end\{\1\}", re.S)
        out = []
        i = 0
        # display environments are numbered in order of appearance; \[ \] and $ do not take numbers, so the
        # relative order between those and the numbered ones does not matter for the counter.
        for m in pat.finditer(s):
            out.append(s[i:m.start()])
            env, body = m.group(1), m.group(2)
            base = env.rstrip("*")
            starred = env.endswith("*")
            labels: list[tuple[str, str]] = []
            last = None
            if base in ("align", "gather"):
                rows = split_rows(body)
                new_rows = []
                for r in rows:
                    tag = None
                    labs = re.findall(r"\\label\{([^}]*)\}", r)
                    r = re.sub(r"\\label\{[^}]*\}", "", r)
                    t = re.search(r"\\tag\*?\{([^}]*)\}", r)
                    if t:
                        tag = t.group(1)
                        r = r[:t.start()] + r[t.end():]
                    elif not starred and not re.search(r"\\(nonumber|notag)\b", r):
                        conv.eq += 1
                        tag = conv.eqnum()
                    r = re.sub(r"\\(nonumber|notag)\b", "", r)
                    if tag is not None:
                        last = tag
                        r = r + "\\tag{%s}" % tag
                    for lb in labs:
                        labels.append((lb, last or conv.cur_label))
                    new_rows.append(r)
                tex = "\\begin{%s*}%s\\end{%s*}" % ("align" if base == "align" else "gather", "\\\\".join(new_rows),
                                                      "align" if base == "align" else "gather")
            else:
                labs = re.findall(r"\\label\{([^}]*)\}", body)
                body2 = re.sub(r"\\label\{[^}]*\}", "", body)
                t = re.search(r"\\tag\*?\{([^}]*)\}", body2)
                tag = None
                if t:
                    tag = t.group(1)
                    body2 = body2[:t.start()] + body2[t.end():]
                elif not starred and not re.search(r"\\(nonumber|notag)\b", body2):
                    conv.eq += 1
                    tag = conv.eqnum()
                body2 = re.sub(r"\\(nonumber|notag)\b", "", body2)
                if base == "multline":
                    rows = split_rows(body2)
                    body2 = "\\begin{gathered}" + "\\\\".join(rows) + "\\end{gathered}"
                tex = body2 + ("\\tag{%s}" % tag if tag is not None else "")
                last = tag
                for lb in labs:
                    labels.append((lb, tag or conv.cur_label))
            out.append(put(clean_math(tex), True, labels, last))
            i = m.end()
        out.append(s[i:])
        s = "".join(out)

        def lab_free(t):
            labs = re.findall(r"\\label\{([^}]*)\}", t)
            if labs:
                warn("label inside unnumbered math: " + ", ".join(labs))
            return re.sub(r"\\label\{[^}]*\}", "", t)
        s = re.sub(r"\\\[(.*?)\\\]", lambda m: put(clean_math(lab_free(m.group(1))), True), s, flags=re.S)
        s = re.sub(r"\$\$(.*?)\$\$", lambda m: put(clean_math(lab_free(m.group(1))), True), s, flags=re.S)
        s = re.sub(r"\\\((.*?)\\\)", lambda m: put(clean_math(m.group(1)), False), s, flags=re.S)
        out = []
        i = 0
        n = len(s)
        while i < n:
            c = s[i]
            if c == "\\" and i + 1 < n:
                out.append(s[i:i + 2])
                i += 2
                continue
            if c == "$":
                j = i + 1
                depth = 0
                while j < n:
                    if s[j] == "\\":
                        j += 2
                        continue
                    if s[j] == "{":
                        depth += 1
                    elif s[j] == "}":
                        depth -= 1
                    elif s[j] == "$" and depth <= 0:
                        break
                    j += 1
                out.append(put(clean_math(s[i + 1:j]), False))
                i = j + 1
                continue
            out.append(c)
            i += 1
        return "".join(out)


# --------------------------------------------------------------------------------------------------------------
# Lean highlighting
# --------------------------------------------------------------------------------------------------------------

LEAN_KW = set(("theorem lemma def abbrev structure class instance inductive where extends fun by have let show from at "
               "with match if then else do open namespace section end variable universe noncomputable private "
               "protected example deriving notation infix infixl infixr prefix postfix macro syntax set_option "
               "attribute local scoped in calc Type Prop Sort mutual partial unsafe opaque axiom termination_by "
               "decreasing_by omit include irreducible_def export").split())
LEAN_TOK = re.compile(r"(/-.*?-/|--[^\n]*)|(\"(?:\\.|[^\"\\])*\")|(\b\d+(?:\.\d+)?\b)|([A-Za-z_][A-Za-z_0-9!?']*)", re.S)


def lean_hl(code: str) -> str:
    out = []
    last = 0
    for m in LEAN_TOK.finditer(code):
        out.append(html.escape(code[last:m.start()], quote=False))
        g = m.group(0)
        prev = code[m.start() - 1] if m.start() else ""
        nxt = code[m.end()] if m.end() < len(code) else ""
        if m.group(1):
            out.append('<span class="c">%s</span>' % html.escape(g, quote=False))
        elif m.group(2):
            out.append('<span class="s">%s</span>' % html.escape(g, quote=False))
        elif m.group(3):
            out.append(g if re.match(r"[\w.₀-₉']", prev) else '<span class="n">%s</span>' % g)
        else:
            if g in LEAN_KW and prev != "." and not re.match(r"[\w']", prev) and nxt != ".":
                out.append('<span class="k">%s</span>' % g)
            else:
                out.append(html.escape(g, quote=False))
        last = m.end()
    out.append(html.escape(code[last:], quote=False))
    return "".join(out)


# --------------------------------------------------------------------------------------------------------------
# The Lean library: declarations with their full names
# --------------------------------------------------------------------------------------------------------------

DECL_RE = re.compile(
    r"^\s*(?:@\[[^\]]*\]\s*)?(?:(?:private|protected|noncomputable|partial|unsafe|nonrec|scoped|local|public)\s+)*"
    r"(?:theorem|lemma|def|abbrev|structure|class|instance|inductive|opaque|axiom|irreducible_def|"
    r"class\s+inductive)\s+([^\s:({\[]+)")
NS_RE = re.compile(r"^\s*(?:(?:noncomputable|public|private)\s+)*(namespace|section|mutual|end)\b\s*([^\s]*)")


def blank_lean_comments(text: str) -> str:
    text = re.sub(r"/-.*?-/", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)
    return re.sub(r"--[^\n]*", "", text)


class Library:
    def __init__(self, root: Path, commit: str):
        self.root = root
        self.files: dict[str, list[str]] = {}
        self.by_base: dict[str, list[str]] = {}
        self.all_files: set[str] = set()
        for p in sorted((root / "VOA").rglob("*.lean")):
            rel = p.relative_to(root).as_posix()
            self.by_base.setdefault(p.name, []).append(rel)
            self.all_files.add(rel)
        self.by_base.setdefault("VOA.lean", []).append("VOA.lean")
        self.all_files.add("VOA.lean")
        self.full: dict[str, tuple[str, int]] = {}
        self.short: dict[str, list[str]] = {}
        self._index(commit)
        self._name_cache: dict = {}

    def _index(self, commit: str) -> None:
        CACHE.mkdir(exist_ok=True)
        cf = CACHE / ("decls-%s.json" % commit[:12])
        if cf.is_file():
            self.full = {k: tuple(v) for k, v in json.loads(cf.read_text()).items()}
        else:
            for old in CACHE.glob("decls-*.json"):
                old.unlink()
            for rel in sorted(self.all_files):
                try:
                    text = (self.root / rel).read_text(encoding="utf-8")
                except (UnicodeDecodeError, FileNotFoundError):
                    continue
                stack: list[tuple[str, str]] = []
                for ln, line in enumerate(blank_lean_comments(text).split("\n"), 1):
                    m = NS_RE.match(line)
                    if m:
                        kw, name = m.group(1), m.group(2)
                        if kw == "namespace":
                            stack.append(("ns", name))
                        elif kw in ("section", "mutual"):
                            stack.append(("sec", name))
                        elif stack:
                            stack.pop()
                        continue
                    m = DECL_RE.match(line)
                    if m:
                        tok = m.group(1)
                        full = tok[len("_root_."):] if tok.startswith("_root_.") else \
                            ".".join([p for k, nm in stack if k == "ns" for p in nm.split(".")] + [tok])
                        self.full.setdefault(full, (rel, ln))
            cf.write_text(json.dumps(self.full, separators=(",", ":")))
        for full in self.full:
            self.short.setdefault(full.split(".")[-1], []).append(full)

    def lines(self, rel: str) -> list[str]:
        if rel not in self.files:
            try:
                self.files[rel] = (self.root / rel).read_text(encoding="utf-8").split("\n")
            except (FileNotFoundError, UnicodeDecodeError):
                self.files[rel] = []
        return self.files[rel]

    def resolve_file(self, path: str) -> str | None:
        path = re.sub(r"\s", "", path).strip(".,;:")
        if not path.endswith(".lean") or "*" in path:
            return None
        if path in self.all_files:
            return path
        if not path.startswith("VOA/") and ("VOA/" + path) in self.all_files:
            return "VOA/" + path
        base = path.split("/")[-1]
        cands = [c for c in self.by_base.get(base, []) if c.endswith("/" + path) or c == path]
        return cands[0] if len(cands) == 1 else None

    def resolve_dir(self, path: str) -> str | None:
        path = re.sub(r"\s", "", path).strip(".,;:")
        if path.endswith("/") and (self.root / path).is_dir():
            return path
        return None

    # -- names in the prose ----------------------------------------------------------------------------------

    def resolve_name(self, name: str, files: list[str]) -> tuple[str, str, int] | None:
        """The declaration a name in the text denotes: the exact full name, or the only declaration whose full
        name ends with '.name' (among the given files first, when the whole library has several)."""
        name = name.strip()
        if not re.fullmatch(r"[A-Za-z_\u0370-\u03ff\u1d00-\u1dbf\u2070-\u209f\u2100-\u214f'!?₀-₉ᵢ-ᵪ\.0-9]+", name) or \
                name.endswith(".") or name.startswith("."):
            return None
        key = (name, tuple(files))
        if key in self._name_cache:
            return self._name_cache[key]
        res = None
        if name in self.full:
            res = (name,) + self.full[name]
        elif "VOA." + name in self.full:
            res = ("VOA." + name,) + self.full["VOA." + name]
        else:
            cands = [f for f in self.short.get(name.split(".")[-1], []) if f.endswith("." + name)]
            if len(cands) > 1:
                fs = set(files)
                cands = [f for f in cands if self.full[f][0] in fs]
            if len(cands) == 1:
                res = (cands[0],) + self.full[cands[0]]
        self._name_cache[key] = res
        return res

    # -- quotations ------------------------------------------------------------------------------------------

    @staticmethod
    def _norm(t: str) -> str:
        return re.sub(r"\s+", " ", t).strip()

    def matches_quote(self, rel: str, ln: int, chunk: str) -> bool:
        """The file, read from line ln, begins with the quoted declaration (whitespace and comments ignored)."""
        q = [l for l in strip_comments(chunk).split("\n") if l.strip()]
        if not q:
            return False
        k = next((i for i, l in enumerate(q) if DECL_RE.match(l)), 0)
        rest = q[k + 1:]
        stop = next((i for i, l in enumerate(rest) if DECL_RE.match(l) and not l.startswith((" ", "\t"))), len(rest))
        quote = self._norm(" ".join([q[k]] + rest[:stop]))
        quote = re.split(r"\s:=|\.\.\.|…|\bwhere\b", quote)[0].strip()[:200]
        lines = self.lines(rel)
        window = "\n".join(lines[ln - 1:ln - 1 + 4 * max(len(q) - k, 1) + 20])
        text = self._norm(strip_comments(window))
        if not quote.startswith("@[") and text.startswith("@["):
            text = re.sub(r"^@\[[^\]]*\]\s*", "", text)  # an attribute the quotation leaves out
        return bool(quote) and text.startswith(quote)

    def locate_chunk(self, chunk: str, files: list[str]) -> tuple[str, int] | None:
        first = first_decl_line(chunk)
        m = DECL_RE.match(first)
        cands: list[tuple[str, int]] = []
        if m:
            tok = m.group(1)
            short = tok.split(".")[-1]
            for rel in files:
                for ln, line in enumerate(self.lines(rel), 1):
                    mm = DECL_RE.match(line)
                    if mm and mm.group(1) == tok:
                        cands.append((rel, ln))
            cands += [self.full[f] for f in self.short.get(short, [])
                      if (f == tok or f.endswith("." + tok)) and self.full[f] not in cands]
        else:
            key = self._norm(first)[:80]
            if len(key) < 8:
                return None
            for rel in files:
                for ln, line in enumerate(self.lines(rel), 1):
                    if self._norm(line).startswith(key):
                        cands.append((rel, ln))
        for c in cands:
            if self.matches_quote(c[0], c[1], chunk):
                return c
        return None


def strip_comments(chunk: str) -> str:
    chunk = re.sub(r"/-.*?-/", "", chunk, flags=re.S)
    return "\n".join(l for l in chunk.split("\n") if not l.strip().startswith("--"))


def first_decl_line(chunk: str) -> str:
    lines = [l.strip() for l in strip_comments(chunk).split("\n") if l.strip()]
    for l in lines:
        if DECL_RE.match(l):
            return l
    for l in lines:
        if not l.startswith("@[") and not re.match(r"open\b.*\bin$", l):
            return l
    return lines[0] if lines else ""


def split_decls(code: str) -> list[str]:
    """Split a quotation into declarations at blank lines, never inside a comment or a declaration."""
    raw = re.split(r"\n\s*\n", code.strip("\n"))
    chunks: list[str] = []
    for c in raw:
        if not c.strip():
            continue
        if chunks:
            prev = chunks[-1]
            open_comment = prev.count("/-") > prev.count("-/")
            body = strip_comments(c).strip()
            starts_decl = bool(DECL_RE.match(first_decl_line(c))) or body.startswith((
                "open ", "variable", "namespace", "section", "end ", "example", "set_option", "attribute", "notation",
                "local ", "@[", "scoped ", "#"))
            if open_comment or (body and not starts_decl and not strip_comments(prev).strip() == ""
                                and not c.lstrip().startswith(("/-", "--"))):
                chunks[-1] = prev + "\n\n" + c
                continue
        chunks.append(c)
    out: list[str] = []
    for c in chunks:
        out += split_adjacent(c)
    return out


def split_adjacent(chunk: str) -> list[str]:
    lines = chunk.split("\n")
    pieces: list[list[str]] = [[]]
    seen_decl = False
    in_comment = False
    pending: list[str] = []
    for line in lines:
        starts_comment = line.startswith("/-") and not in_comment
        if starts_comment or line.startswith("@["):
            pending.append(line)
            in_comment = in_comment or (line.count("/-") > line.count("-/"))
            continue
        if in_comment:
            pending.append(line) if pending else pieces[-1].append(line)
            if "-/" in line:
                in_comment = False
            continue
        if line and not line[0].isspace() and DECL_RE.match(line):
            if seen_decl:
                pieces.append([])
            pieces[-1] += pending + [line]
            pending = []
            seen_decl = True
            continue
        pieces[-1] += pending + [line]
        pending = []
    pieces[-1] += pending
    return ["\n".join(p).strip("\n") for p in pieces if "\n".join(p).strip()]


# --------------------------------------------------------------------------------------------------------------
# LaTeX to HTML
# --------------------------------------------------------------------------------------------------------------

WRAP_CMDS = {"emph": ("<em>", "</em>"), "textit": ("<em>", "</em>"), "textbf": ("<strong>", "</strong>"),
             "textsc": ('<span class="sc">', "</span>"), "textup": ("", ""), "textrm": ("", ""),
             "textnormal": ("", ""), "mbox": ("", ""), "text": ("", ""), "underline": ("<u>", "</u>"),
             "textsf": ("", ""), "textsl": ("<em>", "</em>"), "normalsize": ("", ""), "hbox": ("", "")}
DROP_CMDS = {"noindent", "raggedright", "small", "footnotesize", "scriptsize", "normalsize", "large", "Large",
             "medskip", "smallskip", "bigskip", "leavevmode", "allowbreak", "centering", "sloppy", "fussy", "hfill",
             "relax", "normalfont", "rm", "bfseries", "itshape", "ttfamily", "toprule", "midrule", "bottomrule",
             "hline", "phantomsection", "linebreak", "newline", "break", "nopagebreak", "pagebreak", "newpage",
             "clearpage", "begingroup", "endgroup", "endhead", "endfirsthead", "endfoot", "endlastfoot",
             "arraybackslash", "protect", "selectfont", "indent", "addlinespace", "frenchspacing", "null", "strut",
             "unskip", "ignorespaces", "nobreak", "hss", "vfill", "displaystyle", "textstyle"}
DROP_ONE_ARG = {"label", "index", "hspace", "vspace", "hspace*", "vspace*", "addtocounter", "setcounter",
                "pagestyle", "thispagestyle", "enlargethispage", "cmidrule", "markboth", "markright", "phantom",
                "nolinebreak", "color", "addvspace", "chaptermark", "sectionmark"}
SYMBOLS = {"S": "§", "dots": "…", "ldots": "…", "textendash": "–", "textemdash": "—", "&": "&amp;", "%": "%",
           "_": "_", "#": "#", "$": "$", "{": "{", "}": "}", " ": " ", ",": "&thinsp;", ";": " ", "!": "", ":": " ",
           "-": "", "/": "", "@": "", "textbackslash": "\\", "textasciitilde": "~", "textasciicircum": "^",
           "P": "¶", "ss": "ß", "\n": " ", "\t": " ", "quad": "&emsp;", "qquad": "&emsp;&emsp;", "o": "ø",
           "O": "Ø", "ae": "æ", "AE": "Æ", "oe": "œ", "l": "ł", "L": "Ł", "i": "ı", "aa": "å", "AA": "Å",
           "textbar": "|", "textless": "&lt;", "textgreater": "&gt;", "textbullet": "•", "copyright": "©",
           "textdegree": "°", "LaTeX": "LaTeX", "TeX": "TeX", "enspace": "&ensp;", "thinspace": "&thinsp;",
           "qed": " □", "checkmark": "✓", "times": "×", "textquoteright": "’", "textquoteleft": "‘",
           "textregistered": "®", "dag": "†", "ddag": "‡", "textsuperscript": "", "textonehalf": "½",
           "slash": "/", "nobreakspace": "&nbsp;", "textvisiblespace": "␣", "textquotedbl": "\""}
ACCENTS = {"'": "\u0301", "`": "\u0300", "\"": "\u0308", "~": "\u0303", "c": "\u0327", "v": "\u030c",
           "H": "\u030b", "k": "\u0328", "d": "\u0323", "^": "\u0302", "=": "\u0304", "u": "\u0306", ".": "\u0307",
           "r": "\u030a"}
BLOCK_START = ("<div", "<ol", "<ul", "<dl", "<table", "<h2", "<h3", "<h4", "<pre", "<aside", "<figure", "<blockquote",
               "<section", "<hr")
ROMAN = ["", "i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x", "xi", "xii", "xiii", "xiv", "xv", "xvi",
         "xvii", "xviii", "xix", "xx", "xxi", "xxii", "xxiii", "xxiv", "xxv"]


def alph(n: int) -> str:
    return chr(ord("a") + n - 1) if 1 <= n <= 26 else str(n)


class Converter:
    """Converts one chapter. State: counters, the current \\label value, the Lean files in context."""

    def __init__(self, ch: dict, lib: Library, book_macros: dict):
        self.ch = ch
        self.lib = lib
        self.book_macros = book_macros
        self.math: list[dict] = []
        self.verb: list = []
        self.eq = 0
        self.thm = 0
        self.table = 0
        self.sec = 0
        self.sub = 0
        self.cur_label = ch["num"] or ""
        self.cur_anchor = "top"
        self.cur_sec = ch["num"] or ""
        self.toc: list[list] = []
        self.paths: list[str] = []       # Lean files named in the text, most recent last
        self.list_stack: list[dict] = []
        self.stmt_stack: list[dict] = []
        self.decl_count = 0
        self.decl_ok = 0
        self.names_total = 0
        self.names_ok = 0
        self.quoted: list[dict] = []
        self.in_longtable = False
        self.nbox = 0
        self.pending: list[tuple[str, list[str]]] = []
        self.all_paths: list[str] = []
        self.hidden = 0
        self.hidden_store: list[str] = []

    # -- numbering helpers --------------------------------------------------------------------------------

    def prefix(self) -> str:
        return self.ch["num"]

    def eqnum(self) -> str:
        return "%s.%d" % (self.prefix(), self.eq) if self.prefix() else str(self.eq)

    def set_label(self, value: str, anchor: str) -> None:
        self.cur_label = value
        self.cur_anchor = anchor

    def register(self, key: str) -> None:
        if key in LABELS:
            if LABELS[key]["ch"] == self.ch["key"] and LABELS[key]["id"] == "top":
                return  # the chapter label, registered when the book was read
            warn("duplicate label " + key)
        LABELS[key] = {"ch": self.ch["key"], "num": self.cur_label, "id": self.cur_anchor, "sec": self.cur_sec,
                       "hidden": bool(self.hidden)}

    # -- top level ------------------------------------------------------------------------------------------

    def chapter_html(self, body: str) -> str:
        body = extract_verbatim(body, self.verb)
        body = strip_tex_comments(body)
        body = re.sub(r"\\ifdefined.*?\\fi\b", "", body, flags=re.S)
        macros, body = parse_providecommands(body)
        allm = dict(self.book_macros)
        allm.update(macros)
        self.macros = allm
        body = expand_macros(body, allm)
        body = MathCtx(self).protect(body)

        def hide(m):
            self.hidden_store.append(m.group(1))
            return "\x0e%d\x0e" % (len(self.hidden_store) - 1)
        body = re.sub(re.escape(HIDE_OPEN) + "(.*?)" + re.escape(HIDE_CLOSE), hide, body, flags=re.S)
        h = self.resolve_names(self.blocks(body))
        # wrap sections, so that the reader can typeset math section by section
        parts = re.split(r"(?=<h2 )", h)
        out = []
        for p in parts:
            if not p.strip():
                continue
            m = re.match(r'<h2 id="([^"]+)"', p)
            out.append('<section class="sec"%s>%s</section>' % (' data-sec="%s"' % m.group(1) if m else "", p))
        return "".join(out)

    # -- tokens -> blocks -----------------------------------------------------------------------------------

    def blocks(self, s: str) -> str:
        """Block-level content: paragraphs and block elements."""
        toks = self.tokens(s)
        out, buf = [], []

        def flush():
            t = "".join(buf).strip()
            buf.clear()
            if t:
                t = re.sub(r"\s*\n\s*", " ", t)
                out.append("<p>" + t + "</p>")
        for kind, val in toks:
            if kind == "par":
                flush()
            elif kind == "block":
                flush()
                out.append(val)
            else:
                buf.append(val)
        flush()
        return "".join(out)

    def title_html(self, t: str) -> str:
        """A chapter title, with this chapter's macros and math."""
        t = expand_macros(strip_tex_comments(t), getattr(self, "macros", self.book_macros))
        return self.inline(MathCtx(self).protect(t))

    def inline(self, s: str) -> str:
        toks = self.tokens(s)
        t = "".join(v if k != "par" else " " for k, v in toks)
        return re.sub(r"\s*\n\s*", " ", t).strip()

    def tokens(self, s: str) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        text: list[str] = []

        def emit_text(t):
            text.append(t)

        def emit(kind, val=""):
            if text:
                out.append(("text", "".join(text)))
                text.clear()
            out.append((kind, val))

        i = 0
        n = len(s)
        while i < n:
            c = s[i]
            if c == "\x00":
                j = s.index("\x00", i + 1)
                emit_text(self.math_html(int(s[i + 1:j])))
                i = j + 1
                continue
            if c == "\x0e":
                j = s.index("\x0e", i + 1)
                self.hidden += 1
                self.blocks(self.hidden_store[int(s[i + 1:j])])  # numbered as in the book, not shown
                self.hidden -= 1
                i = j + 1
                continue
            if c == "\x03":
                j = s.index("\x03", i + 1)
                v = self.verb[int(s[i + 1:j])]
                if v[0] == "block":
                    emit("block", self.code_block(v[1], v[2]))
                else:
                    emit_text("<code>%s</code>" % html.escape(v[2]))
                i = j + 1
                continue
            if c == "\n":
                m = re.match(r"\n[ \t]*\n\s*", s[i:])
                if m:
                    emit("par")
                    i += m.end()
                    continue
                emit_text(" ")
                i += 1
                continue
            if c == "\\":
                if i + 1 < n and s[i + 1] == "\\":
                    i += 2
                    _o, i = read_opt(s, i)
                    emit_text("<br>")
                    continue
                m = re.match(r"\\([A-Za-z@]+)(\*?)|\\(.)", s[i:], re.S)
                name = m.group(1) or m.group(3)
                star = m.group(2) or ""
                j = i + len(m.group(0))
                if m.group(1):
                    while j < n and s[j] in " \t":
                        j += 1
                    if j < n and s[j] == "\n" and not re.match(r"\n[ \t]*\n", s[j:]):
                        j += 1
                        while j < n and s[j] in " \t":
                            j += 1
                i = self.command(name, star, s, j, emit, emit_text)
                continue
            if c in "{}":
                i += 1
                continue
            if c == "~":
                emit_text("&nbsp;")
                i += 1
                continue
            if s.startswith("---", i):
                emit_text("—")
                i += 3
                continue
            if s.startswith("--", i):
                emit_text("–")
                i += 2
                continue
            if s.startswith("``", i):
                emit_text("“")
                i += 2
                continue
            if s.startswith("''", i):
                emit_text("”")
                i += 2
                continue
            if c == "`":
                emit_text("‘")
                i += 1
                continue
            if c == "'":
                emit_text("’")
                i += 1
                continue
            emit_text(html.escape(c, quote=False))
            i += 1
        if text:
            out.append(("text", "".join(text)))
        return out

    # -- commands -------------------------------------------------------------------------------------------

    def command(self, name: str, star: str, s: str, j: int, emit, emit_text) -> int:
        if name in ("section", "subsection", "subsubsection", "paragraph", "subparagraph", "chapter", "part"):
            short, j = read_opt(s, j)
            title, j = read_arg(s, j)
            self.heading(name, star, title, emit, emit_text)
            return j
        if name == "begin":
            env, j = read_arg(s, j)
            return self.environment(env, s, j, emit, emit_text)
        if name == "end":
            env, j = read_arg(s, j)
            warn("stray \\end{%s} in %s" % (env, self.ch["key"]))
            return j
        if name == "label":
            key, j = read_arg(s, j)
            self.register(key.strip())
            return j
        if name in ("ref", "eqref", "pageref", "cref", "Cref", "autoref", "nameref"):
            key, j = read_arg(s, j)
            emit_text("\x04%s:%s\x04" % (name, key.strip()))
            return j
        if name == "lean":
            parts = []
            a, j = read_arg(s, j)
            parts.append(a)
            while True:
                m = re.match(r"(?:\\allowbreak(?:\{\})?\s*)?\\lean\{", s[j:])
                if not m:
                    break
                a, j = read_arg(s, j + m.end() - 1)
                parts.append(a)
            emit_text(self.lean_name("".join(parts)))
            return j
        if name == "leanpath":
            a, j = read_arg(s, j)
            emit_text(self.leanpath(a))
            return j
        if name in ("texttt", "nolinkurl", "mathtt", "url", "path"):
            a, j = read_arg(s, j)
            raw = a.replace("\\allowbreak", "").replace("{}", "")
            if "\\" in raw and name == "texttt":
                inner = self.inline(raw)
                emit_text("<code>%s</code>" % inner)
            else:
                raw = raw.replace("\\_", "_").replace("\\#", "#").replace("\\&", "&").replace("\\%", "%") \
                    .replace("\\$", "$").replace("\\{", "{").replace("\\}", "}").replace("\\textbackslash", "\\") \
                    .replace("\\textasciitilde", "~").replace("\\textasciicircum", "^").replace("\\ ", " ")
                emit_text("<code>%s</code>" % html.escape(re.sub(r"\s+", " ", raw).strip(), quote=False))
            return j
        if name == "href":
            url, j = read_arg(s, j)
            txt, j = read_arg(s, j)
            emit_text('<a href="%s" target="_blank" rel="noopener">%s</a>' % (html.escape(url), self.inline(txt)))
            return j
        if name in WRAP_CMDS:
            a, j = read_arg(s, j)
            o, cl = WRAP_CMDS[name]
            emit_text(o + self.inline(a) + cl)
            return j
        if name == "texorpdfstring":
            a, j = read_arg(s, j)
            _b, j = read_arg(s, j)
            emit_text(self.inline(a))
            return j
        if name in DROP_ONE_ARG:
            _o, j = read_opt(s, j)
            _a, j = read_arg(s, j)
            return j
        if name in ("setlength", "addtolength", "renewcommand", "newcommand", "providecommand", "definecolor",
                    "addcontentsline", "newcolumntype", "settowidth"):
            nargs = {"addcontentsline": 3, "definecolor": 3}.get(name, 2)
            for _ in range(nargs):
                _o, j = read_opt(s, j)
                _a, j = read_arg(s, j)
            return j
        if name in ("hangindent", "parindent", "parskip", "columnsep", "leftskip", "rightskip", "emergencystretch",
                    "tabcolsep", "arraystretch", "baselineskip"):
            m = re.match(r"\s*=?\s*-?[\d.]+\s*(em|ex|pt|cm|mm|in|\\[A-Za-z]+)?", s[j:])
            return j + (m.end() if m else 0)
        if name == "caption":
            _o, j = read_opt(s, j)
            a, j = read_arg(s, j)
            if not self.in_longtable:
                self.table += 1
            num = "%s.%d" % (self.prefix(), self.table)
            aid = "tab-" + num
            self.set_label(num, aid)
            emit("block", '<div class="caption" id="%s"><b>Table %s.</b> %s</div>' % (aid, num, self.inline(a)))
            return j
        if name == "item":
            emit_text("\x01item\x01")
            return j
        if name == "par":
            emit("par")
            return j
        if name in DROP_CMDS:
            return j
        if name in ACCENTS and len(name) == 1 and not name.isalpha() or name in ("c", "v", "H", "k", "u", "d", "r"):
            a, j = read_arg(s, j)
            a = a.strip("{}")
            if a.startswith("\\"):
                a = {"\\i": "ı", "\\j": "ȷ"}.get(a, a)
            emit_text(html.escape(a[:1]) + ACCENTS[name] + html.escape(a[1:]))
            return j
        if name in SYMBOLS:
            emit_text(SYMBOLS[name])
            return j
        if name in ("C", "Z", "Q", "N", "R"):
            emit_text({"C": "ℂ", "Z": "ℤ", "Q": "ℚ", "N": "ℕ", "R": "ℝ"}[name])
            return j
        if name in ("mathfrak", "mathbb", "mathcal", "mathrm", "overline", "mathbf"):
            a, j = read_arg(s, j)
            emit_text(html.escape("\\(\\%s{%s}\\)" % (name, a), quote=False))
            return j
        if name in ("Lambda", "theta", "natural", "lambda", "alpha", "beta", "gamma", "omega", "sigma", "tau"):
            emit_text(html.escape("\\(\\%s\\)" % name, quote=False))
            return j
        if name == "multicolumn":
            _a, j = read_arg(s, j)
            _b, j = read_arg(s, j)
            c3, j = read_arg(s, j)
            emit_text(self.inline(c3))
            return j
        unknown_cmds[name] += 1
        emit_text(html.escape(name))
        return j

    # -- headings -------------------------------------------------------------------------------------------

    def heading(self, name: str, star: str, title: str, emit, emit_text) -> None:
        t = self.inline(title)
        if name in ("chapter", "part"):
            return  # the chapter title is rendered by the page; the label after it takes the chapter number
        if name in ("paragraph", "subparagraph"):
            emit("par")
            emit_text('<strong class="runin">%s</strong> ' % t)
            return
        if name == "subsubsection":
            aid = "h-%d" % len(self.toc)
            emit("block", '<h4 id="%s">%s</h4>' % (aid, t))
            self.toc.append([3, "", t, aid]) if not self.hidden else None
            return
        if name == "section":
            if star:
                aid = "h-%d" % len(self.toc)
                emit("block", '<h2 id="%s">%s</h2>' % (aid, t))
                self.toc.append([1, "", t, aid]) if not self.hidden else None
                return
            self.sec += 1
            self.sub = 0
            num = "%s.%d" % (self.prefix(), self.sec) if self.prefix() else str(self.sec)
            aid = "sec-" + num
            self.set_label(num, aid)
            self.cur_sec = num
            emit("block", '<h2 id="%s"><span class="secnum">%s</span> %s</h2>' % (aid, num, t))
            self.toc.append([1, num, t, aid]) if not self.hidden else None
            return
        if name == "subsection":
            if star:
                aid = "h-%d" % len(self.toc)
                emit("block", '<h3 id="%s">%s</h3>' % (aid, t))
                self.toc.append([2, "", t, aid]) if not self.hidden else None
                return
            self.sub += 1
            num = "%s.%d.%d" % (self.prefix(), self.sec, self.sub) if self.prefix() else "%d.%d" % (self.sec, self.sub)
            aid = "sec-" + num
            self.set_label(num, aid)
            self.cur_sec = num
            emit("block", '<h3 id="%s"><span class="secnum">%s</span> %s</h3>' % (aid, num, t))
            self.toc.append([2, num, t, aid]) if not self.hidden else None

    # -- environments ---------------------------------------------------------------------------------------

    def environment(self, env: str, s: str, j: int, emit, emit_text) -> int:
        k = find_env_end(s, j, env)
        inner = s[j:k]
        end = k + len("\\end{%s}" % env)
        saved = (self.cur_label, self.cur_anchor)
        self.env_body(env, inner, emit)
        self.cur_label, self.cur_anchor = saved
        return end

    def env_body(self, env: str, inner: str, emit) -> None:
        base = env.rstrip("*")
        if base in THEOREM_KINDS:
            title, p = read_opt(inner, 0)
            emit("block", self.theorem(base, title, inner[p:]))
        elif env == "proof":
            title, p = read_opt(inner, 0)
            body = self.blocks(inner[p:])
            head = self.inline(title) if title else "Proof"
            body = re.sub(r"(</p>)?$", lambda m: ' <span class="qed">□</span>' + (m.group(1) or ""), body, count=1) \
                if "□" not in body[-80:] else body
            emit("block", '<div class="proof"><span class="proof-h">%s.</span>%s</div>' % (head, body))
        elif env in BOXES:
            self.nbox += 1
            bid = "box-%d" % self.nbox
            self.cur_anchor = bid  # a label in the box keeps the current number but links to the box
            opts, p = read_opt(inner, 0)
            title = BOXES[env]
            if opts:
                m = re.search(r"title\s*=\s*", opts)
                if m:
                    q = skip_ws(opts, m.end())
                    title = read_arg(opts, q)[0] if opts[q] == "{" else opts[q:].split(",")[0]
                    title = self.inline(title)
            body = self.blocks(inner[p:])
            emit("block", '<aside class="box box-%s" id="%s"><div class="box-h">%s</div>%s</aside>' % (env, bid, title, body))
        elif env in ("enumerate", "itemize", "description"):
            opt, p = read_opt(inner, 0)
            emit("block", self.list_env(env, opt, inner[p:]))
        elif env == "longtable":
            self.table += 1  # every longtable steps the table counter, with or without a caption
            num = "%s.%d" % (self.prefix(), self.table)
            self.set_label(num, "tab-" + num)
            _o, p = read_opt(inner, 0)
            _spec, p = read_arg(inner, p)
            body = inner[p:]
            cap = ""
            m = re.search(r"\\caption\b", body)
            if m:
                q = m.end()
                _o, q = read_opt(body, q)
                a, q = read_arg(body, q)
                lm = re.match(r"\s*\\label\{([^}]*)\}", body[q:])
                if lm:
                    self.register(lm.group(1))
                    q += lm.end()
                rm = re.match(r"\s*\\\\", body[q:])
                if rm:
                    q += rm.end()
                cap = '<div class="caption"><b>Table %s.</b> %s</div>' % (num, self.inline(a))
                body = body[:m.start()] + body[q:]
            self.in_longtable = True
            emit("block", '<div class="float" id="tab-%s">%s%s</div>' % (num, cap, self.table_html(body)))
            self.in_longtable = False
        elif env in ("tabular", "tabular*", "array"):
            p = 0
            if env == "tabular*":
                _w, p = read_arg(inner, p)
            _o, p = read_opt(inner, p)
            _spec, p = read_arg(inner, p)
            emit("block", self.table_html(inner[p:]))
        elif env in ("table", "table*", "figure"):
            _o, p = read_opt(inner, 0)
            emit("block", '<div class="float">%s</div>' % self.blocks(inner[p:]))
        elif env in ("center", "flushleft", "flushright", "sloppypar", "minipage", "multicols", "small",
                     "footnotesize", "raggedright"):
            p = 0
            if env in ("minipage", "multicols"):
                _o, p = read_opt(inner, p)
                _a, p = read_arg(inner, p)
            emit("block", '<div class="%s">%s</div>' % ("center" if env == "center" else "blk", self.blocks(inner[p:])))
        elif env in ("quote", "quotation"):
            emit("block", "<blockquote>%s</blockquote>" % self.blocks(inner))
        else:
            warn("unknown environment %s in %s" % (env, self.ch["key"]))
            emit("block", '<div class="blk">%s</div>' % self.blocks(inner))

    def theorem(self, kind: str, title: str | None, body: str) -> str:
        self.thm += 1
        num = "%s.%d" % (self.prefix(), self.thm)
        aid = "s-" + num
        self.set_label(num, aid)
        label = THEOREM_KINDS[kind]
        st = {"ch": self.ch["key"], "num": num, "kind": label, "id": aid, "title": "", "text": ""}
        if not self.hidden:
            STATEMENTS.append(st)
        t = self.inline(title) if title else ""
        st["title"] = t
        inner = self.blocks(body)
        st["text"] = plain_text(inner)[:320]
        head = '<span class="kind">%s %s</span>%s' % (label, num, ' <span class="ttl">(%s)</span>' % t if t else "")
        perma = ('<button type="button" class="permalink" data-perma="%s" title="Copy a link to this statement" '
                 'aria-label="Copy a link">#</button>' % aid)
        return '<div class="thm thm-%s" id="%s"><div class="thm-h">%s%s</div><div class="thm-b">%s</div></div>' % (
            kind, aid, head, perma, inner)

    def list_env(self, env: str, opt: str | None, body: str) -> str:
        level = sum(1 for l in self.list_stack if l["env"] == "enumerate") + (1 if env == "enumerate" else 0)
        fmt = None
        if opt:
            m = re.search(r"label\s*=\s*", opt)
            if m:
                q = skip_ws(opt, m.end())
                fmt = read_arg(opt, q)[0] if opt[q] == "{" else re.split(r",(?![^{]*\})", opt[q:])[0]
        start = 0
        if opt and "resume" in opt and self.ch.get("_last_enum"):
            start = self.ch["_last_enum"]
        ctx = {"env": env, "fmt": fmt, "level": level, "count": start,
               "parent": self.list_stack[-1]["ref"] if self.list_stack and self.list_stack[-1]["env"] == "enumerate" else ""}
        self.list_stack.append(ctx)
        # split at top-level \item
        items = []
        depth = 0
        pos = 0
        starts = []
        for m in re.finditer(r"\\begin\{(enumerate|itemize|description)\}|\\end\{(enumerate|itemize|description)\}|\\item\b", body):
            if m.group(1):
                depth += 1
            elif m.group(2):
                depth -= 1
            elif depth == 0:
                starts.append(m)
        for idx, m in enumerate(starts):
            end = starts[idx + 1].start() if idx + 1 < len(starts) else len(body)
            items.append(body[m.end():end])
        lis = []
        for it in items:
            lab, p = read_opt(it, 0)
            rest = it[p:]
            if env == "enumerate":
                ctx["count"] += 1
                marker, ref = self.enum_label(ctx)
                ctx["ref"] = ref
                aid = "it-%s-%d" % (re.sub(r"[^A-Za-z0-9]", "", ref) or "x", len(self.toc) * 1000 + ctx["count"] + id(ctx) % 997)
                if lab is not None:
                    marker = self.inline(lab)
                else:
                    self.set_label(ref, aid)
                content = self.blocks(rest)
                lis.append('<li id="%s"><span class="lbl">%s</span><div>%s</div></li>' % (aid, marker, content))
            elif env == "itemize":
                marker = self.inline(lab) if lab is not None else "•"
                lis.append('<li><span class="lbl">%s</span><div>%s</div></li>' % (marker, self.blocks(rest)))
            else:
                lis.append('<li class="desc"><span class="dt">%s</span> <div>%s</div></li>' % (
                    self.inline(lab) if lab else "", self.blocks(rest)))
        self.list_stack.pop()
        if env == "enumerate":
            self.ch["_last_enum"] = ctx["count"]
        return '<ol class="list list-%s">%s</ol>' % (env, "".join(lis))

    def enum_label(self, ctx: dict) -> tuple[str, str]:
        n = ctx["count"]
        fmt = ctx["fmt"]
        if fmt:
            def rep(m):
                return {"\\alph*": alph(n), "\\Alph*": alph(n).upper(), "\\roman*": ROMAN[n] if n < len(ROMAN) else str(n),
                        "\\Roman*": (ROMAN[n] if n < len(ROMAN) else str(n)).upper(), "\\arabic*": str(n)}[m.group(0)]
            raw = re.sub(r"\\(alph|Alph|roman|Roman|arabic)\*", rep, fmt)
            marker = self.inline(raw)
            ref = plain_text(marker)
            return marker, ref
        lvl = ctx["level"]
        if lvl <= 1:
            return "%d." % n, str(n)
        if lvl == 2:
            return "(%s)" % alph(n), ctx["parent"] + alph(n)
        if lvl == 3:
            return "%s." % ROMAN[n], ctx["parent"] + "." + ROMAN[n]
        return "%s." % alph(n).upper(), ctx["parent"] + alph(n).upper()

    def table_html(self, body: str) -> str:
        body = re.sub(r"\\(toprule|midrule|bottomrule|hline|endhead|endfirsthead|endfoot|endlastfoot)\b", "\n", body)
        body = re.sub(r"\\cmidrule(\([^)]*\))?\{[^}]*\}", "", body)
        rows = split_rows(body)
        out = ['<div class="tablewrap"><table>']
        first = True
        seen = set()
        for row in rows:
            r = row.strip()
            if not r:
                continue
            cells = split_cells(r)
            tag = "th" if first else "td"
            tds = []
            for c in cells:
                mc = re.match(r"\s*\\multicolumn\{(\d+)\}\{[^}]*\}\{", c)
                span = ""
                if mc:
                    k = match_brace(c, mc.end() - 1)
                    span = ' colspan="%s"' % mc.group(1)
                    c = c[mc.end():k - 1]
                tds.append("<%s%s>%s</%s>" % (tag, span, self.inline(c), tag))
            key = "".join(tds)
            if first:
                seen.add(key)
            elif key in seen:  # longtable repeats its head
                continue
            out.append("<tr>" + key + "</tr>")
            first = False
        out.append("</table></div>")
        return "".join(out)

    # -- math -----------------------------------------------------------------------------------------------

    def math_html(self, idx: int) -> str:
        m = self.math[idx]
        if m["display"]:
            ids = ""
            extra = ""
            for key, num in m["labels"]:
                if key in LABELS:
                    warn("duplicate label " + key)
                aid = anchor_of(key)
                LABELS[key] = {"ch": self.ch["key"], "num": num, "id": aid, "sec": self.cur_sec,
                               "hidden": bool(self.hidden)}
                if not ids:
                    ids = ' id="%s"' % aid
                else:
                    extra += '<span class="anchor" id="%s"></span>' % aid
            return '%s<span class="eq"%s>%s</span>' % (extra, ids, html.escape("\\[" + m["tex"] + "\\]", quote=False))
        return html.escape("\\(" + m["tex"] + "\\)", quote=False)

    # -- Lean -----------------------------------------------------------------------------------------------

    def lean_name(self, raw: str) -> str:
        name = raw.replace("\\allowbreak", "").replace("{}", "").replace("\\_", "_").replace("\\#", "#") \
            .replace("\\&", "&").replace("\\%", "%").replace("\\{", "{").replace("\\}", "}").replace("\\ ", " ")
        name = re.sub(r"\s+", " ", name).strip()
        shown = html.escape(name, quote=False)
        looks_like_name = bool(re.fullmatch(r"[^\s\[\](){},:=]+", name))
        if looks_like_name:
            # resolved when the whole chapter is known (see resolve_names)
            self.pending.append((name, list(self.paths[-8:])))
            return '<code class="ln" data-k="%d">%s</code>' % (len(self.pending) - 1, shown.replace(".", ".<wbr>"))
        return '<code class="ln">%s</code>' % shown

    def resolve_names(self, h: str) -> str:
        """Names in the text: the exact full name, else the only declaration with that tail -- among the files the
        nearby text names, else among the files of this chapter, if the library has several."""
        chfiles = list(dict.fromkeys([q["file"] for q in self.quoted] + self.all_paths))

        def rep(m):
            name, near = self.pending[int(m.group(1))]
            self.names_total += 1
            hit = self.lib.resolve_name(name, near)
            if hit is None:
                hit = self.lib.resolve_name(name, chfiles)
            if not hit:
                return '<code class="ln">'
            self.names_ok += 1
            full, rel, ln = hit
            return '<code class="ln" data-n="%s" data-f="%s" data-l="%d">' % (html.escape(full), html.escape(rel), ln)
        return re.sub(r'<code class="ln" data-k="(\d+)">', rep, h)

    def leanpath(self, raw: str) -> str:
        path = re.sub(r"\s|\\allowbreak|\{\}", "", raw).replace("\\_", "_")
        rel = self.lib.resolve_file(path)
        shown = html.escape(path, quote=False).replace("/", "/<wbr>")
        if rel:
            self.paths.append(rel)
            self.all_paths.append(rel)
            if len(self.paths) > 40:
                self.paths = self.paths[-40:]
            return '<code class="path" data-f="%s">%s</code>' % (html.escape(rel), shown)
        d = self.lib.resolve_dir(path)
        if d:
            return '<code class="path" data-d="%s">%s</code>' % (html.escape(d), shown)
        return '<code class="path">%s</code>' % shown

    def code_block(self, kind: str, code: str) -> str:
        if kind == "plaincode":
            return ('<div class="code plain"><div class="code-h"><span>text</span><button type="button" '
                    'class="mini-btn" data-copycode>Copy</button></div><pre><code>%s</code></pre></div>'
                    % html.escape(code, quote=False))
        decls = []
        files = list(dict.fromkeys(reversed(self.paths[-12:])))
        for chunk in split_decls(code):
            self.decl_count += 1
            loc = self.lib.locate_chunk(chunk, files)
            if loc:
                self.decl_ok += 1
                full = self.lib_full_name(loc)
                if full:
                    if not self.hidden:
                        self.quoted.append({"name": full, "file": loc[0], "line": loc[1], "anchor": self.cur_anchor})
            else:
                first = first_decl_line(chunk)
                if DECL_RE.match(first):
                    warn("no verified source line in %s: %s" % (self.ch["key"], first[:100]))
            head = ('<a class="src" href="#" data-f="%s" data-l="%d" title="Open on GitHub">%s<span class="ln-no">:%d</span> ↗</a>'
                    % (html.escape(loc[0]), loc[1], html.escape(loc[0]), loc[1])) if loc else '<span class="src none">Lean</span>'
            decls.append('<div class="decl"><div class="code-h">%s<button type="button" class="mini-btn" data-copycode>'
                         'Copy</button></div><pre><code>%s</code></pre></div>' % (head, lean_hl(chunk)))
        return '<div class="code lean">%s</div>' % "".join(decls)

    def lib_full_name(self, loc: tuple[str, int]) -> str | None:
        line = self.lib.lines(loc[0])[loc[1] - 1]
        m = DECL_RE.match(line)
        if not m:
            return None
        tok = m.group(1)
        for full in self.lib.short.get(tok.split(".")[-1], []):
            if self.lib.full[full] == loc:
                return full
        return None


def split_cells(row: str) -> list[str]:
    cells, depth, cur, i = [], 0, [], 0
    while i < len(row):
        c = row[i]
        if c == "\\":
            cur.append(row[i:i + 2])
            i += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        elif c == "&" and depth == 0:
            cells.append("".join(cur))
            cur = []
            i += 1
            continue
        cur.append(c)
        i += 1
    cells.append("".join(cur))
    return cells


def plain_text(h: str) -> str:
    t = re.sub(r"<[^>]+>", " ", h)
    t = html.unescape(t)
    t = re.sub(r"\x04[a-zA-Z]+:([^\x04]*)\x04", lambda m: LABELS.get(m.group(1), {}).get("num", ""), t)
    return re.sub(r"\s+", " ", t).strip()


# --------------------------------------------------------------------------------------------------------------
# Cross-references
# --------------------------------------------------------------------------------------------------------------

def present_wording(h: str) -> str:
    """A documentation defect is described by what it is now: a "stale" docstring is a wrong one.
    Only running text is touched, never code, quoted Lean or formulas."""
    parts = re.split(r"(<pre>.*?</pre>|<code[^>]*>.*?</code>|\\\(.*?\\\)|\\\[.*?\\\])", h, flags=re.S)
    for i in range(0, len(parts), 2):
        parts[i] = re.sub(r"\bstale\b", "wrong", parts[i])
        parts[i] = re.sub(r"\bStale\b", "Wrong", parts[i])
    return "".join(parts)


def resolve_refs(h: str, missing: Counter) -> str:
    def rep(m):
        kind, key = m.group(1), m.group(2)
        lab = LABELS.get(key)
        if not lab:
            missing[key] += 1
            return "??"
        if lab.get("hidden") and kind not in ("mref", "meqref"):
            warn("reference to a hidden place: " + key)
            num = html.escape(str(lab["num"]), quote=False)
            return "(%s)" % num if kind == "eqref" else num
        if kind in ("mref", "meqref"):  # inside a formula: the number only
            num = re.sub(r"\$(.*?)\$", r"\1", str(lab["num"]))
            return html.escape(num if kind == "mref" else "(%s)" % num, quote=False)
        href = "#/c/%s/%s" % (lab["ch"], lab["id"])
        if kind == "pageref":
            return '<a class="xref" href="%s">§%s</a>' % (href, html.escape(lab["sec"]))
        num = html.escape(str(lab["num"]), quote=False)
        num = re.sub(r"\$(.*?)\$", r"\\(\1\\)", num)
        if kind == "eqref":
            num = "(%s)" % num
        return '<a class="xref" href="%s">%s</a>' % (href, num)
    # "p.~\pageref{x}" and "pp.~\pageref{x}": the page becomes a link to the place
    h = re.sub(r"\b(?:p|pp)\.(?:&nbsp;|\s)*(?=\x04pageref:)", "", h)
    return re.sub(r"\x04([a-zA-Z]+):([^\x04]*)\x04", rep, h)


# --------------------------------------------------------------------------------------------------------------
# The book
# --------------------------------------------------------------------------------------------------------------

EDITS_BY_FILE: dict[str, list[dict]] = {}
EDIT_STATS: Counter = Counter()


def read_book() -> tuple[list[dict], list[dict], dict]:
    tex = BOOK.read_text(encoding="utf-8")
    tex = strip_tex_comments(tex)
    book_macros, _ = parse_providecommands(tex[:tex.index("\\begin{document}")])
    for k in list(book_macros):
        if k not in ("bookrelease", "bookcommit", "bookdate"):
            del book_macros[k]
    release = book_macros.get("bookrelease", (0, ""))[1]
    tag = release.split()[-1] if release else ""
    commit = git("rev-list", "-n", "1", tag) if tag else None
    if commit:
        book_macros["bookcommit"] = (0, commit[:12])
    body = tex[tex.index("\\begin{document}"):tex.index("\\end{document}")]
    parts: list[dict] = []
    chapters: list[dict] = []
    matter = "front"
    num = 0
    app = 0
    for m in re.finditer(r"\\(frontmatter|mainmatter|appendix|backmatter)\b|\\part\{([^}]*)\}|\\input\{([^}]*)\}", body):
        if m.group(1):
            matter = {"frontmatter": "front", "mainmatter": "main", "appendix": "app", "backmatter": "back"}[m.group(1)]
            if matter == "app":
                parts.append({"title": "Appendices", "chapters": []})
            continue
        if m.group(2) is not None:
            parts.append({"title": m.group(2), "chapters": []})
            continue
        f = m.group(3)
        fname = f.split("/")[-1] + ("" if f.endswith(".tex") else ".tex")
        src = (TEXDIR / (f if f.endswith(".tex") else f + ".tex")).read_text(encoding="utf-8")
        if EDITS_BY_FILE.get(fname):
            spans, errs = plan_edits(fname, src, EDITS_BY_FILE[fname])
            for e in errs:
                warn("history edit not applied: " + e)
            EDIT_STATS["applied"] += sum(1 for sp in spans if sp[2] == "edit")
            EDIT_STATS["hidden"] += sum(1 for sp in spans if sp[2] == "hide")
            src = apply_edits(src, spans)
        cm = re.search(r"\\chapter(\*?)\s*(?:\[([^\]]*)\])?\s*\{", src)
        if not cm:
            continue
        k = match_brace(src, cm.end() - 1)
        long_ = src[cm.end():k - 1]
        short = cm.group(2) or long_
        if cm.group(1):
            cnum, key = "", Path(f).stem
        elif matter == "app":
            app += 1
            cnum = chr(ord("A") + app - 1)
            key = cnum
        else:
            num += 1
            cnum = str(num)
            key = cnum
        ch = {"key": key, "num": cnum, "file": Path(f).stem, "src": src[k:], "long": long_, "short": short,
              "part": len(parts) - 1 if parts and matter != "front" else None, "matter": matter}
        chapters.append(ch)
        if ch["part"] is not None:
            parts[ch["part"]]["chapters"].append(key)
        # the label right after \chapter takes the chapter number
        lm = re.match(r"\s*\\label\{([^}]*)\}", src[k:])
        if lm:
            LABELS[lm.group(1)] = {"ch": key, "num": cnum, "id": "top", "sec": cnum}
    return parts, chapters, book_macros


def parse_index(src: str) -> list[tuple[str, str]]:
    """The book's index of Lean declarations: (name as written, label of the statement)."""
    out = []
    for m in re.finditer(r"\\lean\{((?:[^{}]|\{[^{}]*\})*)\}\s*\\quad\s*((?:\\ref\{[^}]*\}[,;\s]*)+)", src):
        name = m.group(1).replace("\\_", "_").replace("\\allowbreak", "")
        for key in re.findall(r"\\ref\{([^}]*)\}", m.group(2)):
            out.append((name, key))
    return out


def md_inline(s: str) -> str:
    s = html.escape(s, quote=False)
    s = re.sub(r"&lt;(/?)(sub|sup)&gt;", r"<\1\2>", s)
    s = re.sub(r"`([^`]+)`", r'<code class="ln">\1</code>', s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    return s.replace("\\|", "|")


def parse_readme() -> list[dict]:
    md = README.read_text(encoding="utf-8")
    groups = []
    for sec in re.finditer(r"^### (.+?)\n(.*?)(?=^#{2,3} |\Z)", md, flags=re.S | re.M):
        rows = []
        for line in sec.group(2).split("\n"):
            if not line.startswith("| **"):
                continue
            cells = re.split(r"(?<!\\)\|", line.strip().strip("|"))
            if len(cells) < 2:
                continue
            desc, names = cells[0].strip(), cells[1].strip()
            m = re.match(r"\*\*(.+?)\*\*\s*(.*)", desc)
            head, rest = (m.group(1), m.group(2)) if m else ("", desc)
            rows.append({"head": md_inline(head.rstrip(".")), "body": md_inline(rest),
                         "names": re.findall(r"`([^`]+)`", names)})
        if rows:
            groups.append({"title": html.escape(sec.group(1).strip()), "rows": rows})
    return groups


def main() -> None:
    if len(sys.argv) > 2 and sys.argv[1] == "--check-edits":
        return check_edits([Path(p) for p in sys.argv[2:]])
    EDITS_BY_FILE.update(load_edits([EDITS]))
    ref, commit = source_ref()
    lib = Library(ROOT, commit)
    parts, chapters, book_macros = read_book()
    (SITE / "book").mkdir(exist_ok=True)

    index_src = None
    rendered = {}
    totals = Counter()
    quoted: list[dict] = []
    for ch in chapters:
        if ch["file"] == "index":
            index_src = ch["src"]
            ch["is_index"] = True
            conv = Converter(ch, lib, book_macros)
            ch["title"] = ch["shortTitle"] = conv.title_html(ch["long"])
            continue
        conv = Converter(ch, lib, book_macros)
        conv.set_label(ch["num"], "top")
        rendered[ch["key"]] = conv.chapter_html(ch["src"])
        ch["title"] = conv.title_html(ch["long"])
        ch["shortTitle"] = conv.title_html(ch["short"])
        ch["toc"] = conv.toc
        totals["decls"] += conv.decl_count
        totals["decls_ok"] += conv.decl_ok
        totals["names"] += conv.names_total
        totals["names_ok"] += conv.names_ok
        for q in conv.quoted:
            q["ch"] = ch["key"]
        quoted += conv.quoted

    missing: Counter = Counter()
    search = []
    for ch in chapters:
        if ch.get("is_index"):
            continue
        h = present_wording(resolve_refs(rendered[ch["key"]], missing))
        ch["title"] = present_wording(resolve_refs(ch["title"], missing))
        ch["shortTitle"] = resolve_refs(ch["shortTitle"], missing)
        labels = {k: v["id"] for k, v in LABELS.items() if v["ch"] == ch["key"] and v["id"] != "top"}
        (SITE / "book" / ("%s.json" % ch["key"])).write_text(
            json.dumps({"key": ch["key"], "html": h, "labels": labels}, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8")
        for sec in re.finditer(r'<section class="sec"(?: data-sec="([^"]*)")?>(.*?)</section>', h, flags=re.S):
            body = re.sub(r'<div class="code lean">.*?</div></div></div>', " ", sec.group(2), flags=re.S)
            title = ""
            tm = re.match(r"<h2[^>]*>(.*?)</h2>", sec.group(2))
            if tm:
                title = plain_text(tm.group(1))
            search.append([ch["key"], sec.group(1) or "top", title, plain_text(body)])
    for st in STATEMENTS:
        st["title"] = present_wording(resolve_refs(st["title"], missing))
        st["text"] = plain_text(resolve_refs(st["text"], missing))

    # index of Lean declarations (the book's own index, linked to the statements and the source)
    index = []
    if index_src:
        stmt_by_anchor = {(s["ch"], s["id"]): s for s in STATEMENTS}
        for name, key in parse_index(index_src):
            lab = LABELS.get(key)
            if not lab:
                missing[key] += 1
                continue
            st = stmt_by_anchor.get((lab["ch"], lab["id"]))
            files = [q["file"] for q in quoted if q["ch"] == lab["ch"]]
            hit = lib.resolve_name(name, files)
            index.append([name, lab["ch"], lab["id"], (st["kind"] + " " if st else "") + str(lab["num"]),
                          hit[0] if hit else None, hit[1] if hit else None, hit[2] if hit else None])

    headlines = parse_readme()
    by_full: dict[str, list] = {}
    for e in index:
        if e[4]:
            by_full.setdefault(e[4], []).append(e)
    for g in headlines:
        for r in g["rows"]:
            r["links"] = []
            for nme in r["names"]:
                hit = lib.resolve_name(nme, [])
                e = by_full.get(hit[0], [None])[0] if hit else None
                if hit and not e:  # not in the index: the place where the book quotes it
                    q = next((q for q in quoted if q["name"] == hit[0]), None)
                    if q:
                        e = [nme, q["ch"], q["anchor"], "In the book"]
                r["links"].append({"name": nme, "full": hit[0] if hit else None, "file": hit[1] if hit else None,
                                   "line": hit[2] if hit else None, "ch": e[1] if e else None,
                                   "id": e[2] if e else None, "label": e[3] if e else None})
                if not hit:
                    warn("headline name not found: " + nme)
                elif not e:
                    warn("headline name not quoted in the book: " + nme)

    for ch in chapters:
        for k in ("src", "long", "short", "_last_enum"):
            ch.pop(k, None)
    data = {
        "repo": REPO, "ref": ref, "commit": commit, "toolchain": toolchain(),
        "release": book_macros.get("bookrelease", (0, ""))[1], "date": book_macros.get("bookdate", (0, ""))[1],
        "stats": {"chapters": sum(1 for c in chapters if c["matter"] == "main"),
                  "statements": len(STATEMENTS), "quoted": totals["decls_ok"],
                  "leanFiles": sum(1 for f in lib.all_files if f.startswith("VOA/")), "index": len(index)},
        "parts": parts, "chapters": chapters,
        "statements": [[s["ch"], s["num"], s["kind"], s["title"], s["id"], s["text"]] for s in STATEMENTS],
        "index": index, "headlines": headlines,
    }
    OUT.write_text("window.LEANVOA = " + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";\n",
                   encoding="utf-8")
    (CACHE / "labels.json").write_text(json.dumps(LABELS))
    (SITE / "search.json").write_text(json.dumps(search, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    size = sum(p.stat().st_size for p in (SITE / "book").glob("*.json"))
    print("chapters %d, statements %d, labels %d" % (len(chapters), len(STATEMENTS), len(LABELS)))
    print("quoted Lean declarations: %d of %d located and verified" % (totals["decls_ok"], totals["decls"]))
    print("Lean names in the text: %d of %d linked" % (totals["names_ok"], totals["names"]))
    print("history edits: %d replacements, %d hidden regions" % (EDIT_STATS["applied"], EDIT_STATS["hidden"]))
    print("index entries %d; book %.1f MB, data.js %.1f MB, search.json %.1f MB" % (
        len(index), size / 1e6, OUT.stat().st_size / 1e6, (SITE / "search.json").stat().st_size / 1e6))
    if missing:
        print("undefined references: %d (%s)" % (len(missing), ", ".join(list(missing)[:12])))
    if unknown_cmds:
        print("unknown commands: " + ", ".join("%s×%d" % kv for kv in unknown_cmds.most_common(40)))
    uniq = sorted(set(warnings))
    print("%d warnings" % len(uniq))
    for w in uniq[:60]:
        print("  " + w)


if __name__ == "__main__":
    sys.exit(main())
