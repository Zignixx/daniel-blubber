"""
Blubberzähler 🫧
================

Streamlit-Oberfläche: Word/PDF hochladen, Kapitel auswählen, Wörter zählen –
mit Ausschluss von Klammer-Zitaten und Tabellen sowie Optionen für
Überschriften und Fußnoten.

Start:
    streamlit run blubberzaehler.py
"""

import csv
import io
import time

import streamlit as st
import streamlit.components.v1 as components

from blubber_core import (
    CountNode,
    CountOptions,
    count_document,
    grand_total,
    parse_document,
)


st.set_page_config(page_title="Blubberzähler 🫧", page_icon="🫧", layout="centered")


# --------------------------------------------------------------------------- #
# Blubber-Animation + "-XXXX tokens" Damage-Effekt (nur zum Spaß 🫧💥)
# --------------------------------------------------------------------------- #
_BLUBBER_HTML = """
<style>
  .blubber-stage {
    position: relative; height: 210px; width: 100%;
    border-radius: 16px; overflow: hidden;
    background: radial-gradient(120% 140% at 50% 120%,
      rgba(31,111,235,0.22) 0%, rgba(31,111,235,0.06) 45%, rgba(31,111,235,0) 70%);
    font-family: -apple-system, "Segoe UI", system-ui, sans-serif;
  }
  .bubble {
    position: absolute; bottom: -40px; border-radius: 50%;
    background: radial-gradient(circle at 30% 30%,
      rgba(255,255,255,0.9), rgba(120,190,255,0.55) 45%, rgba(31,111,235,0.15) 70%);
    box-shadow: inset 0 0 6px rgba(255,255,255,0.6), 0 0 8px rgba(120,190,255,0.35);
    animation-name: rise; animation-timing-function: ease-in;
    animation-iteration-count: infinite; opacity: 0;
  }
  @keyframes rise {
    0%   { transform: translateY(0) scale(0.6); opacity: 0; }
    12%  { opacity: 0.9; }
    70%  { opacity: 0.8; }
    100% { transform: translateY(-250px) scale(1.15); opacity: 0; }
  }
  .damage {
    position: absolute; left: 50%; top: 46%;
    transform: translate(-50%, -50%);
    font-weight: 900; font-size: 46px; letter-spacing: -1px;
    color: #ffd23f;
    text-shadow:
      -2px -2px 0 #b3001b, 2px -2px 0 #b3001b,
      -2px  2px 0 #b3001b, 2px  2px 0 #b3001b,
       0 6px 14px rgba(179,0,27,0.55);
    animation: dmg 1.9s cubic-bezier(.2,.9,.25,1) forwards;
    white-space: nowrap;
  }
  @keyframes dmg {
    0%   { transform: translate(-50%, 10%)  scale(0.3) rotate(-8deg); opacity: 0; }
    18%  { transform: translate(-50%, -35%) scale(1.35) rotate(3deg); opacity: 1; }
    32%  { transform: translate(-50%, -55%) scale(1.0)  rotate(-2deg); opacity: 1; }
    100% { transform: translate(-50%, -160%) scale(0.95) rotate(0deg); opacity: 0; }
  }
  .crit {
    position: absolute; font-weight: 800; font-size: 20px; color: #ff6b6b;
    text-shadow: 0 2px 6px rgba(0,0,0,0.4); opacity: 0;
    animation: crit 1.9s ease-out forwards; white-space: nowrap;
  }
  @keyframes crit {
    0%   { transform: translateY(20px) scale(0.5); opacity: 0; }
    25%  { opacity: 1; }
    100% { transform: translateY(-90px) scale(1); opacity: 0; }
  }
  .hpbar-wrap {
    position: absolute; left: 50%; bottom: 16px; transform: translateX(-50%);
    width: 78%; text-align: left;
  }
  .hpbar-label {
    font-size: 12px; font-weight: 700; margin-bottom: 4px;
    color: #6b7280; letter-spacing: 0.5px; text-transform: uppercase;
    display: flex; justify-content: space-between;
  }
  .hpbar {
    height: 14px; border-radius: 8px; overflow: hidden;
    background: rgba(120,120,120,0.25);
    box-shadow: inset 0 1px 3px rgba(0,0,0,0.25);
  }
  .hpfill {
    height: 100%; width: 100%;
    background: linear-gradient(90deg, #22c55e, #eab308 55%, #ef4444);
    animation: drain 1.4s ease-out forwards;
  }
  @keyframes drain {
    from { width: 100%; }
    to   { width: var(--target, 60%); }
  }
  @media (prefers-color-scheme: dark) { .hpbar-label { color: #9aa4b2; } }
</style>
<div class="blubber-stage">
  __BUBBLES__
  <span class="crit" style="left:30%; top:60%; animation-delay:.15s">blubb!</span>
  <span class="crit" style="left:64%; top:64%; animation-delay:.35s">blubb blubb!</span>
  <div class="damage">-__TOKENS__ tokens</div>
  <div class="hpbar-wrap">
    <div class="hpbar-label"><span>🧠 AI-Tokens</span><span>__REMAIN__ übrig</span></div>
    <div class="hpbar"><div class="hpfill" style="--target: __PCT__%"></div></div>
  </div>
</div>
"""

# Feste Blasen-Positionen (kein Zufall nötig): left%, größe px, delay s, dauer s
_BUBBLES = [
    (6, 22, 0.0, 3.4), (14, 12, 0.9, 2.6), (23, 28, 0.3, 4.0),
    (34, 10, 1.4, 2.2), (44, 18, 0.6, 3.1), (52, 14, 1.1, 2.8),
    (61, 26, 0.2, 3.9), (70, 12, 1.6, 2.4), (79, 20, 0.8, 3.3),
    (88, 16, 0.4, 2.9), (94, 10, 1.2, 2.5),
]


def _fmt(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def render_blubber_damage(total_words: int) -> None:
    """Zeigt die Blubber-Animation samt "-tokens"-Damage-Effekt."""
    tokens = max(1, round(total_words / 0.75))          # grobe Token-Schätzung
    energy_max = max(tokens * 4, 8000)                   # "HP"-Pool
    pct = max(8, round(100 * (energy_max - tokens) / energy_max))
    remaining = _fmt(energy_max - tokens)

    bubbles = "".join(
        f'<span class="bubble" style="left:{l}%;width:{s}px;height:{s}px;'
        f'animation-delay:{d}s;animation-duration:{u}s"></span>'
        for (l, s, d, u) in _BUBBLES
    )
    html = (
        _BLUBBER_HTML
        .replace("__BUBBLES__", bubbles)
        .replace("__TOKENS__", _fmt(tokens))
        .replace("__PCT__", str(pct))
        .replace("__REMAIN__", remaining)
    )
    components.html(html, height=225)

st.title("Blubberzähler 🫧")
st.caption(
    "Wörter zählen nach formatierten Kapiteln – ohne Klammer-Zitate, ohne Tabellen."
)


# --------------------------------------------------------------------------- #
# 1. Upload
# --------------------------------------------------------------------------- #
uploaded = st.file_uploader(
    "Dokument hochladen (.docx oder .pdf)",
    type=["docx", "pdf"],
)

if uploaded is None:
    st.info("👆 Lade ein Word- oder PDF-Dokument hoch, um zu blubbern.")
    st.stop()


@st.cache_data(show_spinner="Blubbere durch das Dokument …")
def _load(file_bytes: bytes, filename: str):
    """Parst das Dokument (gecached, damit Checkbox-Klicks schnell bleiben)."""
    root = parse_document(io.BytesIO(file_bytes), filename)
    # Nur die für die UI nötigen Titel der Hauptkapitel extrahieren.
    titles = [c.title for c in root.children]
    return root, titles


try:
    root, main_titles = _load(uploaded.getvalue(), uploaded.name)
except Exception as exc:  # noqa: BLE001
    st.error(f"Konnte das Dokument nicht lesen: {exc}")
    st.stop()

if not main_titles:
    st.warning(
        "Es wurden keine Kapitel/Überschriften gefunden. "
        "Bei Word: sind die Überschriften als Formatvorlage (Überschrift 1/2 …) formatiert? "
        "Bei PDF ist die Erkennung heuristisch."
    )
    st.stop()

if uploaded.name.lower().endswith(".pdf"):
    st.warning(
        "ℹ️ PDF-Erkennung ist heuristisch (Schriftgröße/Nummerierung). "
        "Für exakte Ergebnisse ist ein .docx mit echten Überschriften-Formatvorlagen zuverlässiger.",
        icon="⚠️",
    )


# --------------------------------------------------------------------------- #
# 2. Optionen (Checkboxen)
# --------------------------------------------------------------------------- #
st.subheader("Optionen")
col1, col2, col3 = st.columns(3)
with col1:
    include_headings = st.checkbox("Überschriften mitzählen", value=False)
with col2:
    include_parentheses = st.checkbox("Klammern mitzählen", value=False)
with col3:
    include_footnotes = st.checkbox("Fußnoten mitzählen", value=False)

opts = CountOptions(
    exclude_parentheses=not include_parentheses,
    include_headings=include_headings,
    include_footnotes=include_footnotes,
)


# --------------------------------------------------------------------------- #
# 3. Kapitel-Auswahl
# --------------------------------------------------------------------------- #
st.subheader("Kapitel-Auswahl")


def _chapter_label(number: str, title: str) -> str:
    """Kapitel genau mit der aus dem Dokument gelesenen Nummer anzeigen."""
    return f"{number} {title}".strip()


labels = [_chapter_label(ch.number, ch.title) for ch in root.children]
mode = st.radio(
    "Was soll gezählt werden?",
    ["Alle Kapitel", "Bereich (von–bis)", "Einzelauswahl"],
    horizontal=True,
)

selected_indices = list(range(len(main_titles)))

if mode == "Bereich (von–bis)":
    c1, c2 = st.columns(2)
    with c1:
        i_start = st.selectbox(
            "Von Kapitel",
            range(len(labels)),
            index=0,
            format_func=lambda index: labels[index],
        )
    with c2:
        i_end = st.selectbox(
            "Bis Kapitel",
            range(len(labels)),
            index=len(labels) - 1,
            format_func=lambda index: labels[index],
        )
    if i_start > i_end:
        i_start, i_end = i_end, i_start
    selected_indices = list(range(i_start, i_end + 1))
elif mode == "Einzelauswahl":
    selected_indices = st.multiselect(
        "Kapitel wählen",
        range(len(labels)),
        default=list(range(len(labels))),
        format_func=lambda index: labels[index],
    )

if not selected_indices:
    st.warning("Bitte mindestens ein Kapitel auswählen.")
    st.stop()


# --------------------------------------------------------------------------- #
# 4. Zählen & Ausgabe
# --------------------------------------------------------------------------- #
with st.spinner("🫧 Blubbere durch die Kapitel …"):
    nodes = count_document(root, opts, selected_indices)
    total = grand_total(nodes)
    time.sleep(0.45)  # kurz, damit man das Blubbern auch sieht

st.divider()
render_blubber_damage(total)
st.metric("Gesamtwortzahl (Auswahl)", f"{total:,}".replace(",", "."))


def _fmt_n(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def _md_lines(node: CountNode, depth: int = 0):
    """Erzeugt verschachtelte Markdown-Listenzeilen für ein Kapitel."""
    pad = "  " * depth  # 2 Leerzeichen pro Ebene -> saubere Markdown-Liste
    heading = _chapter_label(node.number, node.title)
    if depth == 0:
        lines = [f"{pad}- **{heading} — {_fmt_n(node.total)} Wörter**"]
    else:
        lines = [f"{pad}- {heading} — {_fmt_n(node.total)}"]

    # Eigenen Fließtext des Kapitels als eigene Zeile zeigen, wenn es
    # Unterkapitel gibt (sonst "verschwindet" er optisch in der Summe).
    if node.children and node.own > 0:
        cpad = "  " * (depth + 1)
        lines.append(f"{cpad}- _↳ Fließtext direkt — {_fmt_n(node.own)}_")

    for child in node.children:
        lines.extend(_md_lines(child, depth + 1))
    return lines


st.subheader("Kapitel im Detail")
for node in nodes:
    st.markdown("\n".join(_md_lines(node)))


# --------------------------------------------------------------------------- #
# 5. Export
# --------------------------------------------------------------------------- #
st.divider()
st.subheader("Export")

_opts_label = (
    f"Überschriften={'ja' if include_headings else 'nein'}, "
    f"Klammern={'ja' if include_parentheses else 'nein'}, "
    f"Fußnoten={'ja' if include_footnotes else 'nein'}"
)


def _flatten(nodes):
    """Kapitelbaum in flache Zeilen umwandeln (für CSV/Excel)."""
    rows = []

    def walk(node: CountNode, is_main: bool):
        rows.append(
            {
                "Nummer": node.number,
                "Ebene": node.level,
                "Hauptkapitel": "ja" if is_main else "nein",
                "Kapitel": node.title,
                "Woerter_direkt": node.own,
                "Woerter_gesamt": node.total,
            }
        )
        for child in node.children:
            walk(child, False)

    for n in nodes:
        walk(n, True)
    return rows


rows = _flatten(nodes)
columns = ["Nummer", "Ebene", "Hauptkapitel", "Kapitel", "Woerter_direkt", "Woerter_gesamt"]


# ---- TXT ---------------------------------------------------------------- #
def _report_lines(node: CountNode, depth: int = 0):
    indent = "    " * depth
    heading = _chapter_label(node.number, node.title)
    lines = [f"{indent}{heading}: {node.total} Wörter"]
    if node.children and node.own > 0:
        lines.append(f"{indent}    Fließtext direkt: {node.own} Wörter")
    for child in node.children:
        lines.extend(_report_lines(child, depth + 1))
    return lines


report = [
    "Blubberzähler – Auswertung",
    f"Datei: {uploaded.name}",
    f"Optionen: {_opts_label}",
    "",
    f"GESAMTWORTZAHL (Auswahl): {total}",
    "",
]
for node in nodes:
    report.extend(_report_lines(node))
    report.append("")
txt_bytes = "\n".join(report).encode("utf-8")


# ---- CSV (Semikolon + BOM, damit Excel Umlaute richtig zeigt) ----------- #
def _build_csv() -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    writer.writerow([f"Blubberzähler – {uploaded.name}"])
    writer.writerow([f"Optionen: {_opts_label}"])
    writer.writerow([])
    writer.writerow(columns)
    for r in rows:
        writer.writerow([r[c] for c in columns])
    writer.writerow([])
    writer.writerow(["", "", "", "GESAMT (Auswahl)", "", total])
    return ("﻿" + buf.getvalue()).encode("utf-8")


# ---- Excel -------------------------------------------------------------- #
def _build_xlsx() -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    wb = Workbook()
    ws = wb.active
    ws.title = "Wortzählung"

    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", fgColor="1F6FEB")
    main_font = Font(bold=True)

    ws.append(["Blubberzähler-Auswertung"])
    ws["A1"].font = Font(bold=True, size=14)
    ws.append([f"Datei: {uploaded.name}"])
    ws.append([f"Optionen: {_opts_label}"])
    ws.append([])

    header_row = ws.max_row + 1
    ws.append(columns)
    for cell in ws[header_row]:
        cell.font = header_font
        cell.fill = header_fill

    for r in rows:
        ws.append([r[c] for c in columns])
        if r["Hauptkapitel"] == "ja":
            for cell in ws[ws.max_row]:
                cell.font = main_font
        else:
            # Unterkapitel im Titel einrücken.
            ws.cell(row=ws.max_row, column=4).alignment = Alignment(indent=r["Ebene"] - 1)

    ws.append([])
    ws.append(["", "", "", "GESAMT (Auswahl)", "", total])
    for cell in ws[ws.max_row]:
        cell.font = main_font

    widths = {"A": 8, "B": 7, "C": 13, "D": 42, "E": 15, "F": 15}
    for col, w in widths.items():
        ws.column_dimensions[col].width = w
    ws.freeze_panes = ws.cell(row=header_row + 1, column=1)

    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


c1, c2, c3 = st.columns(3)
with c1:
    st.download_button(
        "📄 .txt",
        data=txt_bytes,
        file_name="blubberzaehler_report.txt",
        mime="text/plain",
        use_container_width=True,
    )
with c2:
    st.download_button(
        "📊 .csv",
        data=_build_csv(),
        file_name="blubberzaehler.csv",
        mime="text/csv",
        use_container_width=True,
    )
with c3:
    st.download_button(
        "📗 .xlsx",
        data=_build_xlsx(),
        file_name="blubberzaehler.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )
