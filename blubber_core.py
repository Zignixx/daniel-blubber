"""
Blubberzähler – Kernlogik
=========================

Enthält das Einlesen von Word-/PDF-Dokumenten in ein gemeinsames
Kapitel-Modell sowie die Zähl-Logik. Bewusst UI-frei gehalten, damit die
Logik auch ohne Streamlit getestet/verwendet werden kann.

Datenmodell
-----------
Ein Dokument wird als Baum aus ``Chapter``-Knoten dargestellt. Jeder Knoten
kennt seinen eigenen Fließtext, seine Fußnoten und seine Unterkapitel. Beim
Zählen wird der "eigene" Count eines Kapitels und der "Gesamt"-Count
(eigener + alle Unterkapitel) getrennt ausgewiesen.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from typing import List, Optional


# --------------------------------------------------------------------------- #
# Wort- und Klammer-Logik
# --------------------------------------------------------------------------- #

# Ein "Wort": Buchstaben/Ziffern (inkl. Umlaute/Akzente), zusammengehalten
# durch Binde-/Apostroph-Striche (z. B. "E-Mail", "Peter's").
_WORD_RE = re.compile(
    r"[0-9A-Za-zÀ-ÖØ-öø-ÿ]+(?:[-'’][0-9A-Za-zÀ-ÖØ-öø-ÿ]+)*"
)


def strip_parentheses(text: str) -> str:
    """Entfernt alles in runden Klammern – auch verschachtelt.

    Für Harvard-Zitate wie ``(Müller, 2020, S. 12)``. Unbalancierte
    Klammern bleiben unangetastet (kein Datenverlust).
    """
    prev = None
    while prev != text:
        prev = text
        text = re.sub(r"\([^()]*\)", " ", text)
    return text


def count_words(text: str, *, exclude_parentheses: bool) -> int:
    """Zählt Wörter in ``text``; optional ohne Klammer-Inhalte."""
    if not text:
        return 0
    if exclude_parentheses:
        text = strip_parentheses(text)
    return len(_WORD_RE.findall(text))


# --------------------------------------------------------------------------- #
# Kapitel-Baum
# --------------------------------------------------------------------------- #

@dataclass
class Chapter:
    """Ein Kapitel/Abschnitt im Dokument."""

    title: str
    level: int                              # 1 = Hauptkapitel, 2 = Unterkapitel …
    body: List[str] = field(default_factory=list)      # Fließtext-Absätze
    footnotes: List[str] = field(default_factory=list)  # zugeordnete Fußnoten
    children: List["Chapter"] = field(default_factory=list)


@dataclass
class Item:
    """Ein Element aus dem Dokument in Lesereihenfolge."""

    kind: str      # 'heading' | 'text' | 'footnote'
    text: str
    level: int = 0  # nur relevant bei 'heading'


def build_tree(items: List[Item]) -> Chapter:
    """Baut aus einer flachen, geordneten Item-Liste den Kapitelbaum.

    Text vor der ersten Überschrift landet in einem Pseudo-Kapitel
    ``(Vorspann)``.
    """
    root = Chapter(title="__root__", level=0)
    stack: List[Chapter] = [root]
    preamble: Optional[Chapter] = None

    for item in items:
        if item.kind == "heading":
            level = max(1, item.level)
            node = Chapter(title=item.text.strip() or "(ohne Titel)", level=level)
            # Bis zum passenden Elternknoten hochlaufen.
            while len(stack) > 1 and stack[-1].level >= level:
                stack.pop()
            stack[-1].children.append(node)
            stack.append(node)
        else:
            target = stack[-1]
            if target is root:
                # Text/Fußnote vor der ersten Überschrift -> Vorspann.
                if preamble is None:
                    preamble = Chapter(title="(Vorspann)", level=1)
                    root.children.insert(0, preamble)
                target = preamble
            if item.kind == "footnote":
                target.footnotes.append(item.text)
            else:
                target.body.append(item.text)

    return root


# --------------------------------------------------------------------------- #
# Zähl-Optionen und Ergebnisknoten
# --------------------------------------------------------------------------- #

@dataclass
class CountOptions:
    exclude_parentheses: bool = True   # Klammern NICHT mitzählen
    include_headings: bool = False     # Überschriften-Wörter mitzählen
    include_footnotes: bool = False    # Fußnoten mitzählen


@dataclass
class CountNode:
    title: str
    number: str          # z. B. "1", "2.1"
    level: int
    own: int             # Wörter nur in diesem Kapitel
    total: int           # own + alle Unterkapitel
    children: List["CountNode"] = field(default_factory=list)


def _count_chapter(ch: Chapter, opts: CountOptions, number: str) -> CountNode:
    own = 0
    for para in ch.body:
        own += count_words(para, exclude_parentheses=opts.exclude_parentheses)
    if opts.include_headings:
        own += count_words(ch.title, exclude_parentheses=opts.exclude_parentheses)
    if opts.include_footnotes:
        for fn in ch.footnotes:
            own += count_words(fn, exclude_parentheses=opts.exclude_parentheses)

    child_nodes: List[CountNode] = []
    for idx, child in enumerate(ch.children, start=1):
        child_number = f"{number}.{idx}" if number else str(idx)
        child_nodes.append(_count_chapter(child, opts, child_number))

    total = own + sum(c.total for c in child_nodes)
    return CountNode(
        title=ch.title,
        number=number,
        level=ch.level,
        own=own,
        total=total,
        children=child_nodes,
    )


def count_document(
    root: Chapter,
    opts: CountOptions,
    selected_indices: Optional[List[int]] = None,
) -> List[CountNode]:
    """Zählt die (ausgewählten) Hauptkapitel.

    ``selected_indices`` bezieht sich auf ``root.children`` (0-basiert).
    ``None`` = alle Hauptkapitel.
    """
    nodes: List[CountNode] = []
    for idx, child in enumerate(root.children):
        if selected_indices is not None and idx not in selected_indices:
            continue
        nodes.append(_count_chapter(child, opts, str(idx + 1)))
    return nodes


def grand_total(nodes: List[CountNode]) -> int:
    return sum(n.total for n in nodes)


# --------------------------------------------------------------------------- #
# Word (.docx) einlesen
# --------------------------------------------------------------------------- #

_W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _heading_level_from_style(style_name: str) -> Optional[int]:
    """Liefert die Ebene, falls die Formatvorlage eine Überschrift ist."""
    if not style_name:
        return None
    name = style_name.strip().lower()
    # Deutsche und englische Namen abdecken.
    for prefix in ("heading", "überschrift", "uberschrift"):
        if name.startswith(prefix):
            m = re.search(r"(\d+)", name)
            return int(m.group(1)) if m else 1
    if name in ("title", "titel"):
        return 1
    return None


def _extract_docx_footnotes(document) -> dict:
    """Liest den Fußnoten-Teil des Dokuments: {id: text}."""
    footnotes: dict = {}
    try:
        part = document.part
        for rel in part.rels.values():
            if "footnotes" in rel.reltype:
                blob = rel.target_part.blob
                from docx.oxml import parse_xml  # gebündeltes lxml
                tree = parse_xml(blob)
                for fn in tree.findall(f"{_W_NS}footnote"):
                    fid = fn.get(f"{_W_NS}id")
                    fn_type = fn.get(f"{_W_NS}type")
                    # Trenner-/Fortsetzungs-Einträge überspringen.
                    if fn_type in ("separator", "continuationSeparator"):
                        continue
                    texts = [t.text or "" for t in fn.iter(f"{_W_NS}t")]
                    footnotes[fid] = "".join(texts)
                break
    except Exception:
        # Fußnoten sind optional – bei Problemen einfach ohne weitermachen.
        pass
    return footnotes


def parse_docx(file) -> Chapter:
    """Liest ein .docx-Dokument in den Kapitelbaum ein.

    Überschriften kommen aus den Formatvorlagen (Heading/Überschrift),
    Tabellen werden übersprungen, Fußnoten dem jeweiligen Absatz-Kapitel
    zugeordnet.
    """
    from docx import Document
    from docx.text.paragraph import Paragraph

    document = Document(file)
    footnote_map = _extract_docx_footnotes(document)

    items: List[Item] = []
    body = document.element.body

    for child in body.iterchildren():
        tag = child.tag
        if tag == f"{_W_NS}tbl":
            # Tabelle -> komplett ausschließen.
            continue
        if tag != f"{_W_NS}p":
            continue

        para = Paragraph(child, document)
        text = para.text.strip()
        style_name = para.style.name if para.style is not None else ""
        level = _heading_level_from_style(style_name)

        if level is not None and text:
            items.append(Item(kind="heading", text=text, level=level))
        elif text:
            items.append(Item(kind="text", text=text))

        # Fußnoten-Referenzen dieses Absatzes einsammeln.
        for ref in child.iter(f"{_W_NS}footnoteReference"):
            fid = ref.get(f"{_W_NS}id")
            if fid in footnote_map:
                fn_text = footnote_map[fid].strip()
                if fn_text:
                    items.append(Item(kind="footnote", text=fn_text))

    return build_tree(items)


# --------------------------------------------------------------------------- #
# PDF einlesen (heuristisch)
# --------------------------------------------------------------------------- #

_NUM_HEADING_RE = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+\S")


def _median(values: List[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2


def _bbox_intersects(a, b) -> bool:
    return not (a[2] <= b[0] or a[0] >= b[2] or a[3] <= b[1] or a[1] >= b[3])


def parse_pdf(file) -> Chapter:
    """Liest ein PDF heuristisch in den Kapitelbaum ein.

    PDFs kennen keine verlässlichen Überschriften-Formatvorlagen. Deshalb:
    - Überschrift, wenn Nummerierung (``1.2 …``) ODER deutlich größere/fette
      Schrift und kurze Zeile.
    - Tabellen werden – wenn von PyMuPDF erkannt – ausgeschlossen.
    - Fußnoten = deutlich kleinere Schrift im unteren Seitenbereich (best effort).
    Hochgestellte Fußnoten-Marker im Fließtext werden nicht mitgezählt.
    """
    import fitz  # PyMuPDF

    data = file.read()
    doc = fitz.open(stream=data, filetype="pdf")

    # --- 1. Durchgang: alle Zeilen mit Metadaten sammeln ------------------- #
    raw_lines = []  # dicts: text, size, bold, y_ratio, is_num
    all_sizes: List[float] = []

    for page in doc:
        page_height = page.rect.height or 1.0

        # Tabellen-Bounding-Boxes ermitteln (falls verfügbar).
        table_bboxes = []
        try:
            tf = page.find_tables()
            for t in tf.tables:
                table_bboxes.append(t.bbox)
        except Exception:
            pass

        page_dict = page.get_text("dict")
        for block in page_dict.get("blocks", []):
            if block.get("type") != 0:  # 0 = Text, sonst Bild etc.
                continue
            for line in block.get("lines", []):
                spans = line.get("spans", [])
                if not spans:
                    continue
                line_bbox = line.get("bbox", (0, 0, 0, 0))

                # In einer Tabelle? -> überspringen.
                if any(_bbox_intersects(line_bbox, tb) for tb in table_bboxes):
                    continue

                # Hochgestellte Marker (Fußnoten-Ziffern) nicht mitzählen.
                pieces, sizes = [], []
                for s in spans:
                    flags = s.get("flags", 0)
                    if flags & 1:  # superscript
                        continue
                    pieces.append(s.get("text", ""))
                    sizes.append(s.get("size", 0.0))
                text = "".join(pieces).strip()
                if not text or not sizes:
                    continue

                size = _median(sizes)
                bold = any((s.get("flags", 0) & 16) for s in spans)
                y_ratio = line_bbox[1] / page_height
                all_sizes.append(size)
                raw_lines.append(
                    {
                        "text": text,
                        "size": size,
                        "bold": bold,
                        "y_ratio": y_ratio,
                        "is_num": bool(_NUM_HEADING_RE.match(text)),
                    }
                )

    doc.close()

    body_size = _median(all_sizes) if all_sizes else 12.0

    # --- 2. Durchgang: klassifizieren ------------------------------------- #
    items: List[Item] = []
    for ln in raw_lines:
        text = ln["text"]
        size = ln["size"]
        words = len(text.split())

        # Fußnote: kleine Schrift, unten auf der Seite.
        if size <= body_size * 0.82 and ln["y_ratio"] >= 0.72 and words >= 2:
            items.append(Item(kind="footnote", text=text))
            continue

        # Überschrift per Nummerierung.
        m = _NUM_HEADING_RE.match(text)
        if m and words <= 15 and (size >= body_size * 0.98 or ln["bold"]):
            level = m.group(1).count(".") + 1
            items.append(Item(kind="heading", text=text, level=level))
            continue

        # Überschrift per Schriftgröße/Fettung.
        if words <= 12 and (size >= body_size * 1.2 or (ln["bold"] and size >= body_size * 1.1)):
            # Ebene grob aus der Größe ableiten.
            if size >= body_size * 1.6:
                level = 1
            elif size >= body_size * 1.3:
                level = 2
            else:
                level = 3
            items.append(Item(kind="heading", text=text, level=level))
            continue

        items.append(Item(kind="text", text=text))

    return build_tree(items)


# --------------------------------------------------------------------------- #
# Dispatch
# --------------------------------------------------------------------------- #

def parse_document(file, filename: str) -> Chapter:
    """Wählt anhand der Endung den passenden Parser."""
    name = (filename or "").lower()
    if name.endswith(".docx"):
        return parse_docx(file)
    if name.endswith(".pdf"):
        return parse_pdf(file)
    if name.endswith(".doc"):
        raise ValueError(
            "Altes .doc-Format wird nicht unterstützt – bitte als .docx speichern."
        )
    raise ValueError("Nicht unterstützter Dateityp. Bitte .docx oder .pdf hochladen.")
