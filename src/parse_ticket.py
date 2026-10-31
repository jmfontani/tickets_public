"""Parsea un ticket PDF de Mercadona y devuelve datos estructurados."""
import re
import json
import pdfplumber
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import List, Optional


@dataclass
class LineItem:
    cantidad: int
    descripcion: str
    precio_unit: float
    importe: float


@dataclass
class Ticket:
    fecha: str  # dd/mm/yyyy HH:MM
    tienda: str
    direccion: str
    telefono: str
    operador: str
    num_ticket: str
    items: List[LineItem] = field(default_factory=list)
    total: float = 0.0
    metodo_pago: str = ""
    iva_desglose: list = field(default_factory=list)
    pdf_file: str = ""
    email_account: str = ""

    def to_dict(self):
        d = asdict(self)
        return d


# Regex para línea de producto:
# "1 LECHE SEMI P6 5,04"         → qty=1 desc="LECHE SEMI P6" pu=5.04 imp=None(=pu*qty)
# "2 GAZPACHO FRESCO 1,10 2,20"   → qty=2 desc="GAZPACHO FRESCO" pu=1.10 imp=2.20
# "1 CERVEZA 6,00"                → qty=1 desc="CERVEZA" pu=6.00 imp=None
# Algunos productos pueden tener números en el nombre: "1 0% CON FRUTAS X8 2,00"
# "1 PACK 4X500 ZERO 5,40"
LINE_RE_2PRICES = re.compile(
    r"^(\d+)\s+(.+?)\s+(\d+,\d{2})\s+(\d+,\d{2})$"
)
LINE_RE_1PRICE = re.compile(
    r"^(\d+)\s+(.+?)\s+(\d+,\d{2})$"
)
# Producto de peso variable - línea 1: solo cantidad + descripción (sin precio)
LINE_RE_WEIGHT_1 = re.compile(
    r"^(\d+)\s+(.+)$"
)
# Producto de peso variable - línea 2: "0,750 kg 1,60 €/kg 1,20"
LINE_RE_WEIGHT_2 = re.compile(
    r"^(\d+[,.]?\d*)\s*kg\s+(\d+[,.]?\d*)\s*€/kg\s+(\d+[,.]?\d*)$"
)


def parse_pdf(pdf_path: str) -> Ticket:
    with pdfplumber.open(pdf_path) as pdf:
        text = pdf.pages[0].extract_text()

    lines = text.strip().split("\n")
    ticket = Ticket(
        fecha="", tienda="", direccion="", telefono="",
        operador="", num_ticket="", items=[], total=0.0
    )

    # --- Header ---
    ticket.tienda = lines[0].strip() if lines else ""
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("C/") or stripped.startswith("AVDA."):
            ticket.direccion = stripped
        elif stripped.startswith("TELÉFONO:"):
            ticket.telefono = stripped.replace("TELÉFONO:", "").strip()
        elif re.match(r"\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}", stripped):
            m = re.match(r"(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2})\s+OP:\s*(\d+)", stripped)
            if m:
                ticket.fecha = f"{m.group(1)} {m.group(2)}"
                ticket.operador = m.group(3)
        elif "FACTURA SIMPLIFICADA:" in stripped:
            ticket.num_ticket = stripped.split("FACTURA SIMPLIFICADA:")[1].strip()

    # --- Items: entre "Descripción P. Unit Importe" y "TOTAL (€)" ---
    in_items = False
    pending_weight_item = None  # Para productos de peso variable (2 líneas)

    for line in lines:
        if "Descripción" in line and "P. Unit" in line:
            in_items = True
            continue
        if "TOTAL (€)" in line:
            m = re.search(r"TOTAL\s*\(€\)\s+([\d,]+)", line)
            if m:
                ticket.total = float(m.group(1).replace(",", "."))
            in_items = False
            break
        if in_items:
            stripped = line.strip()
            if not stripped:
                continue

            # If we have a pending weight item, this line should be its weight/price
            if pending_weight_item:
                m = LINE_RE_WEIGHT_2.match(stripped)
                if m:
                    peso = float(m.group(1).replace(",", "."))
                    precio_kg = float(m.group(2).replace(",", "."))
                    importe = float(m.group(3).replace(",", "."))
                    pending_weight_item.precio_unit = precio_kg
                    pending_weight_item.importe = importe
                    ticket.items.append(pending_weight_item)
                    pending_weight_item = None
                    continue
                else:
                    # The pending item didn't get a weight line — add it as-is (edge case)
                    # and try to parse this line as a new product
                    ticket.items.append(pending_weight_item)
                    pending_weight_item = None
                    # Fall through to parse current line

            # Try 2-price format first (cantidad desc precio_unit importe)
            m = LINE_RE_2PRICES.match(stripped)
            if m:
                qty = int(m.group(1))
                desc = m.group(2).strip()
                pu = float(m.group(3).replace(",", "."))
                imp = float(m.group(4).replace(",", "."))
                ticket.items.append(LineItem(qty, desc, pu, imp))
                continue

            # Try 1-price format (cantidad desc precio_unit)
            m = LINE_RE_1PRICE.match(stripped)
            if m:
                qty = int(m.group(1))
                desc = m.group(2).strip()
                pu = float(m.group(3).replace(",", "."))
                imp = pu * qty
                ticket.items.append(LineItem(qty, desc, pu, imp))
                continue

            # Try weight-product line 1: just quantity + description, no price
            # This happens for products sold by weight (fruit, veg, fish, meat)
            m = LINE_RE_WEIGHT_1.match(stripped)
            if m:
                qty = int(m.group(1))
                desc = m.group(2).strip()
                # Don't add yet — wait for the weight line
                pending_weight_item = LineItem(qty, desc, 0.0, 0.0)
                continue

    # If there's still a pending item at end of items section, add it
    if pending_weight_item:
        ticket.items.append(pending_weight_item)

    # --- Método de pago ---
    for line in lines:
        if "TARJETA BANCARIA" in line or "TARJ. BANCARIA" in line or "TARJ BANCARIA" in line:
            ticket.metodo_pago = "Tarjeta bancaria"
            break
        elif "EFECTIVO" in line:
            ticket.metodo_pago = "Efectivo"
            break

    # --- IVA ---
    in_iva = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("IVA"):
            in_iva = True
            continue
        if in_iva and stripped.startswith("TOTAL"):
            break
        if in_iva:
            m = re.match(r"(\d+)%\s+([\d,]+)\s+([\d,]+)", stripped)
            if m:
                ticket.iva_desglose.append({
                    "tasa": int(m.group(1)),
                    "base": float(m.group(2).replace(",", ".")),
                    "cuota": float(m.group(3).replace(",", ".")),
                })

    return ticket


def parse_all(pdfs_dir: str, account_map: dict = None) -> List[Ticket]:
    """Parsea todos los PDFs en un directorio.
    
    Args:
        pdfs_dir: Directorio con los PDFs.
        account_map: Dict opcional {pdf_name: email_account} para asignar origen.
    """
    pdfs = sorted(Path(pdfs_dir).glob("*.pdf"))
    results = []
    errors = []
    for pdf in pdfs:
        try:
            ticket = parse_pdf(str(pdf))
            ticket.pdf_file = pdf.name
            if account_map and pdf.name in account_map:
                ticket.email_account = account_map[pdf.name]
            results.append(ticket)
        except Exception as e:
            errors.append({"file": pdf.name, "error": str(e)})
            print(f"Error parseando {pdf.name}: {e}")

    if errors:
        print(f"\n{len(errors)} errores de parseo:")
        for err in errors:
            print(f"  {err['file']}: {err['error']}")

    return results


def tickets_to_json(tickets: List[Ticket]) -> str:
    """Serializa lista de tickets a JSON."""
    return json.dumps([t.to_dict() for t in tickets], indent=2, ensure_ascii=False)


if __name__ == "__main__":
    import sys
    pdf_dir = sys.argv[1] if len(sys.argv) > 1 else "data/raw_pdfs"
    tickets = parse_all(pdf_dir)
    print(f"\nParseados {len(tickets)} tickets:")
    for t in tickets:
        items_total = sum(i.importe for i in t.items)
        match = "✓" if abs(items_total - t.total) < 0.02 else "✗"
        print(f"  {match} {t.fecha} | {t.num_ticket} | {len(t.items)} items | "
              f"total={t.total}€ | suma_items={items_total:.2f}€ | {t.pdf_file}")