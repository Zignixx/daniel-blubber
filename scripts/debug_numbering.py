"""
Diagnose-Skript fuer die Kapitelnummerierung.

Zeigt pro Ueberschrift: Titel, Formatvorlage, direkte numPr (falls vorhanden)
und die daraus berechnete Nummer. Zeigt KEINEN Fliesstext - nur Ueberschriften
und Formatierungs-Metadaten, damit auch reale/sensible Dokumente gefahrlos
geprueft werden koennen.

Aufruf:
    python scripts/debug_numbering.py pfad/zum/dokument.docx
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docx import Document
from docx.text.paragraph import Paragraph

from blubber_core import (
    _W_NS,
    _DocxNumbering,
    _heading_level_from_style,
    _paragraph_numbering,
)


def main(path: str) -> None:
    document = Document(path)
    numbering = _DocxNumbering(document)

    print(f"{'Titel':<45} {'Formatvorlage':<20} {'direkte numPr':<18} {'berechnete Nr.'}")
    print("-" * 100)

    for child in document.element.body.iterchildren():
        if child.tag != f"{_W_NS}p":
            continue
        para = Paragraph(child, document)
        text = para.text.strip()
        style_name = para.style.name if para.style is not None else ""
        level = _heading_level_from_style(style_name)
        if level is None or not text:
            continue

        direct = _paragraph_numbering(para)
        direct_str = f"numId={direct[0]}, ilvl={direct[1]}" if direct else "-"
        label = numbering.label_for(para)

        print(f"{text[:43]:<45} {style_name[:18]:<20} {direct_str:<18} {label or '(keine)'}")

        if direct is not None and not label:
            num_id = direct[0]
            num_data = numbering._nums.get(num_id)
            if num_data is None:
                print(f"    -> numId={num_id} NICHT in numbering.xml gefunden (self._nums)")
            else:
                abstract_id, _ = num_data
                abstract = numbering._abstract.get(abstract_id)
                print(f"    -> numId={num_id} -> abstractNumId={abstract_id} "
                      f"({'gefunden' if abstract is not None else 'FEHLT in self._abstract'})")
                if abstract is not None:
                    child_tags = sorted({c.tag.split('}')[-1] for c in abstract})
                    print(f"    -> abstractNum-Kindelemente: {child_tags}")
                    lvl0 = numbering._find_level(abstract, direct[1] or 0)
                    if lvl0 is None:
                        print(f"    -> KEIN <w:lvl ilvl={direct[1] or 0}> im abstractNum gefunden")
                        num_style_link = abstract.find(f"{_W_NS}numStyleLink")
                        style_link = abstract.find(f"{_W_NS}styleLink")
                        if num_style_link is not None:
                            print(f"    -> abstractNum verweist per numStyleLink auf Listen-Formatvorlage: "
                                  f"{num_style_link.get(f'{_W_NS}val')}")
                        if style_link is not None:
                            print(f"    -> abstractNum ist selbst eine Listen-Formatvorlage (styleLink): "
                                  f"{style_link.get(f'{_W_NS}val')}")
                    else:
                        lvl_children = sorted({c.tag.split('}')[-1] for c in lvl0})
                        print(f"    -> <w:lvl> gefunden, Kindelemente: {lvl_children}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Aufruf: python scripts/debug_numbering.py pfad/zum/dokument.docx")
        sys.exit(1)
    main(sys.argv[1])
