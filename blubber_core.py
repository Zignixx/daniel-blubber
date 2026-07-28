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
    number: str = ""                        # sichtbare Nummer aus dem Dokument
    body: List[str] = field(default_factory=list)      # Fließtext-Absätze
    footnotes: List[str] = field(default_factory=list)  # zugeordnete Fußnoten
    children: List["Chapter"] = field(default_factory=list)


@dataclass
class Item:
    """Ein Element aus dem Dokument in Lesereihenfolge."""

    kind: str      # 'heading' | 'text' | 'footnote'
    text: str
    level: int = 0  # nur relevant bei 'heading'
    number: str = ""  # sichtbare Nummer aus dem Dokument


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
            node = Chapter(
                title=item.text.strip() or "(ohne Titel)",
                level=level,
                number=item.number,
            )
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
    number: str          # Originalbezeichnung, z. B. "Kapitel 3", "3.2" oder ""
    level: int
    own: int             # Wörter nur in diesem Kapitel
    total: int           # own + alle Unterkapitel
    children: List["CountNode"] = field(default_factory=list)


def _count_chapter(ch: Chapter, opts: CountOptions) -> CountNode:
    own = 0
    for para in ch.body:
        own += count_words(para, exclude_parentheses=opts.exclude_parentheses)
    if opts.include_headings:
        own += count_words(ch.title, exclude_parentheses=opts.exclude_parentheses)
    if opts.include_footnotes:
        for fn in ch.footnotes:
            own += count_words(fn, exclude_parentheses=opts.exclude_parentheses)

    child_nodes: List[CountNode] = []
    for child in ch.children:
        child_nodes.append(_count_chapter(child, opts))

    total = own + sum(c.total for c in child_nodes)
    return CountNode(
        title=ch.title,
        number=ch.number,
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
        nodes.append(_count_chapter(child, opts))
    return nodes


def grand_total(nodes: List[CountNode]) -> int:
    return sum(n.total for n in nodes)


# --------------------------------------------------------------------------- #
# Word (.docx) einlesen
# --------------------------------------------------------------------------- #

_W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _split_number_from_heading(text: str) -> tuple[str, str]:
    """Trennt eine ausgeschriebene Nummer vom eigentlichen Überschriftentext.

    Das betrifft vor allem PDF-Überschriften und manuell eingetippte Nummern
    in Word. Automatische Word-Nummern sind nicht in ``Paragraph.text``
    enthalten und werden separat aus ``numbering.xml`` gelesen.
    """
    match = re.match(r"^(\d+(?:\.\d+)*[.)]?)\s+(.+)$", text.strip())
    if not match:
        return "", text.strip()
    return match.group(1), match.group(2).strip()


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


def _xml_val(element, child_name: str, default=None):
    """Liest ein ``w:val``-Attribut eines direkten XML-Kindelements."""
    if element is None:
        return default
    child = element.find(f"{_W_NS}{child_name}")
    if child is None:
        return default
    return child.get(f"{_W_NS}val", default)


def _paragraph_numbering(paragraph) -> Optional[tuple[int, Optional[int]]]:
    """Liefert ``(numId, ilvl)`` inklusive geerbter Style-Einstellungen."""
    num_id = None
    ilvl = None

    # Direkte Absatzformatierung hat Vorrang vor der Formatvorlage.
    p_pr = paragraph._p.pPr
    num_pr = p_pr.numPr if p_pr is not None else None
    if num_pr is not None:
        num_id = _xml_val(num_pr, "numId")
        ilvl = _xml_val(num_pr, "ilvl")

    # Word hinterlegt die Nummerierung häufig an der Überschrift-Formatvorlage.
    style = paragraph.style
    while style is not None and (num_id is None or ilvl is None):
        style_p_pr = style.element.pPr
        style_num_pr = style_p_pr.numPr if style_p_pr is not None else None
        if style_num_pr is not None:
            if num_id is None:
                num_id = _xml_val(style_num_pr, "numId")
            if ilvl is None:
                ilvl = _xml_val(style_num_pr, "ilvl")
        style = style.base_style

    if num_id is None:
        return None
    try:
        parsed_num_id = int(num_id)
        if parsed_num_id == 0:  # w:numId="0" schaltet Nummerierung aus.
            return None
        return parsed_num_id, int(ilvl) if ilvl is not None else None
    except (TypeError, ValueError):
        return None


def _to_roman(value: int) -> str:
    if value <= 0:
        return str(value)
    result = []
    for number, numeral in (
        (1000, "M"), (900, "CM"), (500, "D"), (400, "CD"),
        (100, "C"), (90, "XC"), (50, "L"), (40, "XL"),
        (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"),
    ):
        while value >= number:
            result.append(numeral)
            value -= number
    return "".join(result)


def _to_letters(value: int) -> str:
    """1 -> A, 26 -> Z, 27 -> AA."""
    if value <= 0:
        return str(value)
    result = []
    while value:
        value, remainder = divmod(value - 1, 26)
        result.append(chr(ord("A") + remainder))
    return "".join(reversed(result))


def _format_list_value(value: int, number_format: str) -> str:
    if number_format == "upperRoman":
        return _to_roman(value)
    if number_format == "lowerRoman":
        return _to_roman(value).lower()
    if number_format == "upperLetter":
        return _to_letters(value)
    if number_format == "lowerLetter":
        return _to_letters(value).lower()
    if number_format == "decimalZero":
        return f"{value:02d}"
    if number_format == "none":
        return ""
    return str(value)


class _DocxNumbering:
    """Rekonstruiert die von Word gerenderten Listennummern."""

    def __init__(self, document):
        self._nums = {}
        self._abstract = {}
        self._counters = {}
        self._numbering_style_num_id = {}  # Listen-Formatvorlage (styleId) -> numId

        try:
            numbering = document.part.numbering_part.element
        except Exception:
            numbering = None

        if numbering is not None:
            for abstract in numbering.findall(f"{_W_NS}abstractNum"):
                abstract_id = abstract.get(f"{_W_NS}abstractNumId")
                if abstract_id is not None:
                    self._abstract[int(abstract_id)] = abstract

            for num in numbering.findall(f"{_W_NS}num"):
                num_id = num.get(f"{_W_NS}numId")
                abstract_id = _xml_val(num, "abstractNumId")
                if num_id is not None and abstract_id is not None:
                    self._nums[int(num_id)] = (int(abstract_id), num)

        # Manche abstractNum-Definitionen enthalten keine eigenen <w:lvl>-Level,
        # sondern verweisen per numStyleLink auf eine Listen-Formatvorlage in
        # styles.xml. Dafür brauchen wir die Zuordnung Formatvorlage -> numId.
        try:
            styles_root = document.styles.element
        except Exception:
            styles_root = None
        if styles_root is not None:
            for style in styles_root.findall(f"{_W_NS}style"):
                if style.get(f"{_W_NS}type") != "numbering":
                    continue
                style_id = style.get(f"{_W_NS}styleId")
                style_p_pr = style.find(f"{_W_NS}pPr")
                num_pr = style_p_pr.find(f"{_W_NS}numPr") if style_p_pr is not None else None
                num_id_val = _xml_val(num_pr, "numId") if num_pr is not None else None
                if style_id and num_id_val is not None:
                    try:
                        self._numbering_style_num_id[style_id] = int(num_id_val)
                    except ValueError:
                        pass

    @staticmethod
    def _find_level(parent, level: int):
        if parent is None:
            return None
        for candidate in parent.findall(f"{_W_NS}lvl"):
            if candidate.get(f"{_W_NS}ilvl") == str(level):
                return candidate
        return None

    def _resolve_abstract(self, abstract_id: int, _seen: Optional[set] = None):
        """Folgt ``numStyleLink``-Verweisen bis zum abstractNum mit echten Levels.

        Manche Word-Vorlagen definieren eine Liste nicht direkt, sondern binden
        sie über eine Listen-Formatvorlage ein (z. B. eigene Uni-Vorlagen wie
        "Hausarbeit"). Die eigentlichen ``<w:lvl>``-Definitionen stecken dann
        im abstractNum der verlinkten Formatvorlage.
        """
        if _seen is None:
            _seen = set()
        abstract = self._abstract.get(abstract_id)
        if abstract is None or abstract_id in _seen:
            return abstract
        _seen.add(abstract_id)

        link = abstract.find(f"{_W_NS}numStyleLink")
        if link is None:
            return abstract
        linked_num_id = self._numbering_style_num_id.get(link.get(f"{_W_NS}val"))
        if linked_num_id is None:
            return abstract
        linked_num_data = self._nums.get(linked_num_id)
        if linked_num_data is None:
            return abstract
        linked_abstract_id, _ = linked_num_data
        resolved = self._resolve_abstract(linked_abstract_id, _seen)
        return resolved if resolved is not None else abstract

    def _level_definition(self, num_id: int, level: int):
        num_data = self._nums.get(num_id)
        if num_data is None:
            return None, None
        abstract_id, num = num_data

        override = None
        for candidate in num.findall(f"{_W_NS}lvlOverride"):
            if candidate.get(f"{_W_NS}ilvl") == str(level):
                override = candidate
                break

        overridden_level = self._find_level(override, level)
        abstract_level = self._find_level(self._resolve_abstract(abstract_id), level)
        if overridden_level is not None:
            return overridden_level, override
        return abstract_level, override

    def _numbering_for(self, paragraph) -> Optional[tuple[int, int]]:
        direct = _paragraph_numbering(paragraph)
        if direct is None:
            return None
        num_id, level = direct
        # w:ilvl fehlt am Absatz -> laut OOXML-Spezifikation Ebene 0.
        return num_id, level if level is not None else 0

    def _start(self, num_id: int, level: int) -> int:
        level_def, override = self._level_definition(num_id, level)
        value = _xml_val(override, "startOverride")
        if value is None:
            value = _xml_val(level_def, "start", "1")
        try:
            return int(value)
        except (TypeError, ValueError):
            return 1

    def label_for(self, paragraph) -> str:
        numbering = self._numbering_for(paragraph)
        if numbering is None:
            return ""
        num_id, level = numbering
        level_def, _ = self._level_definition(num_id, level)
        if level_def is None:
            return ""

        counters = self._counters.setdefault(num_id, {})
        counters[level] = counters.get(level, self._start(num_id, level) - 1) + 1
        for deeper_level in [key for key in counters if key > level]:
            del counters[deeper_level]

        pattern = _xml_val(level_def, "lvlText", f"%{level + 1}")
        if pattern is None:
            return ""

        for referenced_level in range(9):
            placeholder = f"%{referenced_level + 1}"
            if placeholder not in pattern:
                continue
            value = counters.get(
                referenced_level,
                self._start(num_id, referenced_level),
            )
            referenced_def, _ = self._level_definition(num_id, referenced_level)
            number_format = _xml_val(referenced_def, "numFmt", "decimal")
            pattern = pattern.replace(
                placeholder,
                _format_list_value(value, number_format),
            )
        return pattern.strip()


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
    numbering = _DocxNumbering(document)

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
        # Für eine korrekte Fortschreibung müssen auch nummerierte
        # Nicht-Überschriften am Zähler vorbeilaufen.
        rendered_number = numbering.label_for(para)

        if level is not None and text:
            if rendered_number:
                title = text
                heading_number = rendered_number
            else:
                heading_number, title = _split_number_from_heading(text)
            items.append(
                Item(
                    kind="heading",
                    text=title,
                    level=level,
                    number=heading_number,
                )
            )
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

_NUM_HEADING_RE = re.compile(r"^(\d+(?:\.\d+)*[.)]?)\s+(\S.*)$")


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
            normalized_number = m.group(1).rstrip(".)")
            level = normalized_number.count(".") + 1
            items.append(
                Item(
                    kind="heading",
                    text=m.group(2).strip(),
                    level=level,
                    number=m.group(1),
                )
            )
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
