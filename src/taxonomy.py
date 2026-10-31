"""Taxonomía universal de 3 niveles para tickets de Mercadona.

Clasifica cada producto en:
    Categoría (5) -> Subcategoría (40+) -> Producto normalizado

A diferencia de ``normalize.py`` (que usa 2 niveles y deja muchos items en
"Otros"), este módulo:

    * Usa un matching por keywords ordenado por especificidad (el primero
      que encaje gana), case-insensitive y por substring.
    * Cubre los ~1.320 productos únicos de la BD con 5 categorías y más de
      40 subcategorías, dejando "Otros" casi vacío.
    * Permite correcciones manuales persistentes mediante la tabla
      ``taxonomy_overrides`` (overrides por descripción o por item concreto).

Tipos:
    Override de tipo ``producto``: reasigna la descripción en TODOS los items
    pasados y futuros.
    Override de tipo ``item``: reasigna UN line_item concreto (prioridad sobre
    el de producto).
"""
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .database import DB_PATH

# ---------------------------------------------------------------------------
# Taxonomía declarativa
# ---------------------------------------------------------------------------

# Categorías de nivel 1 y sus subcategorías.
CATEGORIES: Dict[str, List[str]] = {
    "Alimentación": [
        "Fruta",
        "Verdura y hortaliza",
        "Pan y bollería",
        "Lácteos",
        "Huevos",
        "Carne y charcutería",
        "Pescado y marisco",
        "Pasta, arroz y legumbres",
        "Cereales y desayuno",
        "Conservas y caldos",
        "Aceite, salsas y condimentos",
        "Harinas y repostería",
        "Snacks y frutos secos",
        "Dulces y chocolate",
        "Congelados",
        "Comida preparada",
    ],
    "Bebidas": [
        "Agua",
        "Refrescos y zumos",
        "Café, té e infusiones",
        "Cerveza",
        "Vino y licores",
    ],
    "Limpieza del hogar": [
        "Detergente y suavizante",
        "Lavavajillas",
        "Lejía y desinfectantes",
        "Limpieza cocina y baño",
        "Suelos y superficies",
        "Útiles de limpieza",
        "Bolsas de basura",
    ],
    "Papel y desechables": [
        "Papel higiénico",
        "Papel de cocina",
        "Pañuelos y servilletas",
        "Aluminio, film y bolsas",
    ],
    "Higiene personal": [
        "Champú y cuidado capilar",
        "Gel y jabón",
        "Higiene bucal",
        "Desodorante",
        "Afeitado y depilación",
        "Cuidado corporal y facial",
        "Higiene íntima",
    ],
    "Bebé": [
        "Pañales y toallitas",
        "Alimentación infantil",
        "Higiene bebé",
    ],
    "Farmacia y parafarmacia": [
        "Botiquín",
        "Medicamentos sin receta",
        "Suplementos",
        "Protección solar",
    ],
    "Mascotas": [
        "Comida para mascotas",
        "Higiene para mascotas",
        "Accesorios mascotas",
    ],
    "Hogar": [
        "Menaje y cocina",
        "Textil hogar",
        "Decoración",
        "Iluminación",
        "Ferretería y bricolaje",
    ],
    "Ropa y calzado": [
        "Ropa",
        "Calzado",
        "Complementos",
    ],
    "Otros": ["Otros"],
}
KEYWORD_RULES: List[Tuple[str, str, str, str]] = [
    ("AGUA", "Bebidas", "Agua", "Agua"),
    ("SALUD VERDE", "Bebidas", "Agua", "Agua"),
    ("COCA COLA", "Bebidas", "Refrescos y zumos", "Cola"),
    ("COLA ZERO", "Bebidas", "Refrescos y zumos", "Cola zero"),
    ("CC ZERO", "Bebidas", "Refrescos y zumos", "Cola zero"),
    ("GASEOSA", "Bebidas", "Refrescos y zumos", "Gaseosa"),
    ("LIMONADA", "Bebidas", "Refrescos y zumos", "Limonada"),
    ("BITTER", "Bebidas", "Refrescos y zumos", "Bitter"),
    ("NARANJA ZERO", "Bebidas", "Refrescos y zumos", "Naranja zero"),
    ("TRINA", "Bebidas", "Refrescos y zumos", "Trina"),
    ("TEA VERDE", "Bebidas", "Refrescos y zumos", "Té"),
    ("ICE TEA", "Bebidas", "Refrescos y zumos", "Té"),
    ("FUZE", "Bebidas", "Refrescos y zumos", "Fuze Tea"),
    ("TE AL LIMON", "Bebidas", "Refrescos y zumos", "Té"),
    ("GRANIZADO", "Bebidas", "Refrescos y zumos", "Granizado"),
    ("REFRESCANTE", "Bebidas", "Refrescos y zumos", "Refresco"),
    ("CERV", "Bebidas", "Cerveza", "Cerveza"),
    ("CERVEZA", "Bebidas", "Cerveza", "Cerveza"),
    ("MAHOU", "Bebidas", "Cerveza", "Cerveza"),
    ("LAGER", "Bebidas", "Cerveza", "Cerveza"),
    ("VINO TINTO", "Bebidas", "Vino y licores", "Vino tinto"),
    ("VINO BLANCO", "Bebidas", "Vino y licores", "Vino blanco"),
    ("BLANCO P-3", "Bebidas", "Vino y licores", "Vino blanco"),
    ("VINO", "Bebidas", "Vino y licores", "Vino"),
    ("FUENTE DEHESA", "Bebidas", "Vino y licores", "Vino"),
    ("CHARDONAY", "Bebidas", "Vino y licores", "Vino blanco"),
    ("RVA 8", "Bebidas", "Vino y licores", "Vinagre de Jerez"),
    ("YOG LIQ", "Bebidas", "Refrescos y zumos", "Yogur líquido"),
    ("YOGUR BEBER", "Bebidas", "Refrescos y zumos", "Yogur líquido"),
    ("YOGUR LIQUIDO", "Bebidas", "Refrescos y zumos", "Yogur líquido"),
    ("BATIDO", "Bebidas", "Refrescos y zumos", "Batido"),
    ("ZUMO", "Bebidas", "Refrescos y zumos", "Zumo"),
    ("PACK 4X500", "Bebidas", "Refrescos y zumos", "Pack bebidas"),
    ("BEBER", "Bebidas", "Refrescos y zumos", "Bebida láctea"),
    ("PROTE. MANGO", "Bebidas", "Refrescos y zumos", "Batido proteínas"),
    ("+PRO", "Bebidas", "Refrescos y zumos", "Batido proteínas"),
    ("YOG LIQ", "Bebidas", "Refrescos y zumos", "Yogur líquido"),
    ("HUEVO", "Alimentación", "Huevos", "Huevos"),
    ("LECHE COND", "Alimentación", "Lácteos", "Leche condensada"),
    ("LECHE EVAPORADA", "Alimentación", "Lácteos", "Leche evaporada"),
    ("LECHE FRITA", "Alimentación", "Dulces y chocolate", "Leche frita"),
    ("LECHE", "Alimentación", "Lácteos", "Leche"),
    ("BATIDO 90%", "Alimentación", "Lácteos", "Batido de leche"),
    ("GRIEGO", "Alimentación", "Lácteos", "Yogur griego"),
    ("YOGUR CABRA", "Alimentación", "Lácteos", "Yogur de cabra"),
    ("YOGUR", "Alimentación", "Lácteos", "Yogur"),
    ("YOG ", "Alimentación", "Lácteos", "Yogur"),
    ("YOGOMIX", "Alimentación", "Lácteos", "Yogur"),
    ("L.CASEI", "Alimentación", "Lácteos", "Yogur"),
    ("LCASEI", "Alimentación", "Lácteos", "Yogur"),
    ("BÍF", "Alimentación", "Lácteos", "Yogur bifidus"),
    ("BIFIDUS", "Alimentación", "Lácteos", "Yogur bifidus"),
    ("KEFIR", "Alimentación", "Lácteos", "Kéfir"),
    ("KÉFIR", "Alimentación", "Lácteos", "Kéfir"),
    ("PETIT DE BOLSILLO", "Alimentación", "Lácteos", "Petit suisse"),
    ("MASCARPONE", "Alimentación", "Lácteos", "Mascarpone"),
    ("MANTEQUILLA", "Alimentación", "Lácteos", "Mantequilla"),
    ("MARGARINA", "Alimentación", "Lácteos", "Margarina"),
    ("CUAJADA", "Alimentación", "Lácteos", "Cuajada"),
    ("NATILLA", "Alimentación", "Lácteos", "Natillas"),
    ("FLAN", "Alimentación", "Lácteos", "Flan"),
    ("BURRATA", "Alimentación", "Lácteos", "Burrata"),
    ("QUESO", "Alimentación", "Lácteos", "Queso"),
    ("Q BURGOS", "Alimentación", "Lácteos", "Queso Burgos"),
    ("Q.FRESCO", "Alimentación", "Lácteos", "Queso fresco"),
    ("Q FRESCO", "Alimentación", "Lácteos", "Queso fresco"),
    ("Q MADURADO", "Alimentación", "Lácteos", "Queso curado"),
    ("Q OVEJA", "Alimentación", "Lácteos", "Queso oveja"),
    ("Q SEMI", "Alimentación", "Lácteos", "Queso semicurado"),
    ("Q VIEJO", "Alimentación", "Lácteos", "Queso viejo"),
    ("Q. LONCHAS", "Alimentación", "Lácteos", "Queso lonchas"),
    ("Q. VIEJO", "Alimentación", "Lácteos", "Queso viejo"),
    ("Q RALLADO", "Alimentación", "Lácteos", "Queso rallado"),
    ("Q. ", "Alimentación", "Lácteos", "Queso"),
    ("QUESO RALLADO", "Alimentación", "Lácteos", "Queso rallado"),
    ("GRANA PADANO", "Alimentación", "Lácteos", "Queso parmesano"),
    ("GRANA", "Alimentación", "Lácteos", "Queso parmesano"),
    ("RULO CABRA", "Alimentación", "Lácteos", "Queso de cabra"),
    ("RULITO CABRA", "Alimentación", "Lácteos", "Queso de cabra"),
    ("RULO PRECORTADO", "Alimentación", "Lácteos", "Queso rulo"),
    ("CREMOSO", "Alimentación", "Lácteos", "Queso crema"),
    ("CREMA CAMEMBERT", "Alimentación", "Lácteos", "Queso camembert"),
    ("PERLAS MOZZARELLA", "Alimentación", "Lácteos", "Mozzarella"),
    ("MOZZARELLA", "Alimentación", "Lácteos", "Mozzarella"),
    ("NATA SPRAY", "Alimentación", "Lácteos", "Nata"),
    ("NATA PARA COCINAR", "Alimentación", "Lácteos", "Nata"),
    ("NATA", "Alimentación", "Lácteos", "Nata"),
    ("CREMA VICHYSSOISE", "Alimentación", "Conservas y caldos", "Crema vichyssoise"),
    ("LACON", "Alimentación", "Carne y charcutería", "Lacón"),
    ("LACÓN", "Alimentación", "Carne y charcutería", "Lacón"),
    ("CECINA", "Alimentación", "Carne y charcutería", "Cecina"),
    ("MORCILLA", "Alimentación", "Carne y charcutería", "Morcilla"),
    ("CARRIL", "Alimentación", "Carne y charcutería", "Carrillada"),
    ("CONTRAMUSLO", "Alimentación", "Carne y charcutería", "Contramuslo"),
    ("ALAS", "Alimentación", "Carne y charcutería", "Alas"),
    ("COSTILL", "Alimentación", "Carne y charcutería", "Costilla"),
    ("COSTILLEJA", "Alimentación", "Carne y charcutería", "Costilleja"),
    ("POLLO ASADO", "Alimentación", "Carne y charcutería", "Pollo asado"),
    ("POLLO RELLENO", "Alimentación", "Carne y charcutería", "Pollo relleno"),
    ("POLLO", "Alimentación", "Carne y charcutería", "Pollo"),
    ("CUARTO TRASERO", "Alimentación", "Carne y charcutería", "Cuarto trasero"),
    ("CUARTO CERTIFICADO", "Alimentación", "Carne y charcutería", "Cuarto de pollo"),
    ("PICADA DE VACUNO", "Alimentación", "Carne y charcutería", "Picada de vacuno"),
    ("CONEJO", "Alimentación", "Carne y charcutería", "Conejo"),
    ("BURGER", "Alimentación", "Carne y charcutería", "Hamburguesa"),
    ("HAMBURGUESA", "Alimentación", "Carne y charcutería", "Hamburguesa"),
    ("SOLOMILLO", "Alimentación", "Carne y charcutería", "Solomillo"),
    ("SECRETO", "Alimentación", "Carne y charcutería", "Secreto"),
    ("PECHUGA", "Alimentación", "Carne y charcutería", "Pechuga"),
    ("PECHU.", "Alimentación", "Carne y charcutería", "Pechuga"),
    ("CHULETA", "Alimentación", "Carne y charcutería", "Chuleta"),
    ("SALCHICHA", "Alimentación", "Carne y charcutería", "Salchichas"),
    ("S.FRANKFURT", "Alimentación", "Carne y charcutería", "Salchichas Frankfurt"),
    ("FRANKFURT", "Alimentación", "Carne y charcutería", "Salchichas Frankfurt"),
    ("LOMO SALMÓN", "Alimentación", "Pescado y marisco", "Lomo de salmón"),
    ("LOMO SALMON", "Alimentación", "Pescado y marisco", "Lomo de salmón"),
    ("LOMO ADOBADO", "Alimentación", "Carne y charcutería", "Lomo adobado"),
    ("LOMO AÑOJO", "Alimentación", "Carne y charcutería", "Lomo de añojo"),
    ("LOMO TERNERA", "Alimentación", "Carne y charcutería", "Lomo de ternera"),
    ("LOMO CERDO", "Alimentación", "Carne y charcutería", "Lomo de cerdo"),
    ("LOMO EMBUCHADO", "Alimentación", "Carne y charcutería", "Lomo embuchado"),
    ("LOMO IB", "Alimentación", "Carne y charcutería", "Lomo ibérico"),
    ("LOMO", "Alimentación", "Carne y charcutería", "Lomo"),
    ("MIGAS", "Alimentación", "Carne y charcutería", "Migas"),
    ("PAVO", "Alimentación", "Carne y charcutería", "Pavo"),
    ("PALETILLA", "Alimentación", "Carne y charcutería", "Paletilla"),
    ("CENTRO PALETILLA", "Alimentación", "Carne y charcutería", "Centro de paletilla"),
    ("JAMONCITOS", "Alimentación", "Carne y charcutería", "Jamón de pollo"),
    ("JAMÓN SERRANO", "Alimentación", "Carne y charcutería", "Jamón serrano"),
    ("JAMON SERRANO", "Alimentación", "Carne y charcutería", "Jamón serrano"),
    ("JAMÓN COCIDO", "Alimentación", "Carne y charcutería", "Jamón cocido"),
    ("JAMON COCIDO", "Alimentación", "Carne y charcutería", "Jamón cocido"),
    ("JAMÓN C", "Alimentación", "Carne y charcutería", "Jamón cocido"),
    ("JAMON C", "Alimentación", "Carne y charcutería", "Jamón cocido"),
    ("JAMÓN PAVO", "Alimentación", "Carne y charcutería", "Jamón de pavo"),
    ("JAMON PAVO", "Alimentación", "Carne y charcutería", "Jamón de pavo"),
    ("JAMÓN SÁNDWICH", "Alimentación", "Carne y charcutería", "Jamón para sándwich"),
    ("JAMON LATA", "Alimentación", "Carne y charcutería", "Jamón en lata"),
    ("JAMÓN DE PATO", "Alimentación", "Carne y charcutería", "Jamón de pato"),
    ("JAMON DE PATO", "Alimentación", "Carne y charcutería", "Jamón de pato"),
    ("JAMÓN", "Alimentación", "Carne y charcutería", "Jamón"),
    ("JAMON", "Alimentación", "Carne y charcutería", "Jamón"),
    ("HUESO JAMON", "Alimentación", "Carne y charcutería", "Hueso de jamón"),
    ("FUET", "Alimentación", "Carne y charcutería", "Fuet"),
    ("ESPETEC", "Alimentación", "Carne y charcutería", "Fuet"),
    ("SARTA", "Alimentación", "Carne y charcutería", "Salchichón sarta"),
    ("SALCHICHÓN", "Alimentación", "Carne y charcutería", "Salchichón"),
    ("SALCHICHON", "Alimentación", "Carne y charcutería", "Salchichón"),
    ("CHORIZO", "Alimentación", "Carne y charcutería", "Chorizo"),
    ("SOBRASADA", "Alimentación", "Carne y charcutería", "Sobrasada"),
    ("SALPICÓN", "Alimentación", "Carne y charcutería", "Salpicón"),
    ("LONGANIZA", "Alimentación", "Carne y charcutería", "Longaniza"),
    ("BANDERILLAS", "Alimentación", "Carne y charcutería", "Banderillas"),
    ("MAGRO", "Alimentación", "Carne y charcutería", "Carne magra"),
    ("PINCHO", "Alimentación", "Carne y charcutería", "Pincho"),
    ("TACOS AÑOJO", "Alimentación", "Carne y charcutería", "Tacos de añojo"),
    ("FILETE", "Alimentación", "Carne y charcutería", "Filete"),
    ("BROCHETA", "Alimentación", "Carne y charcutería", "Brocheta"),
    ("ALBONDIGAS", "Alimentación", "Carne y charcutería", "Albóndigas"),
    ("MUSLO", "Alimentación", "Carne y charcutería", "Muslo"),
    ("PANCETA", "Alimentación", "Carne y charcutería", "Panceta"),
    ("BACON", "Alimentación", "Carne y charcutería", "Bacon"),
    ("BACON", "Alimentación", "Carne y charcutería", "Bacon"),
    ("CINTAS DE BACON", "Alimentación", "Carne y charcutería", "Bacon"),
    ("CODILLO", "Alimentación", "Carne y charcutería", "Codillo"),
    ("ESPINAZO", "Alimentación", "Carne y charcutería", "Espinazo de cerdo"),
    ("CARCASA", "Alimentación", "Carne y charcutería", "Carcasa de pollo"),
    ("CORTADO A MANO", "Alimentación", "Carne y charcutería", "Embutido cortado"),
    ("TAQUITOS", "Alimentación", "Carne y charcutería", "Taquitos"),
    ("MOUSSE PATO", "Alimentación", "Carne y charcutería", "Paté de pato"),
    ("PATÉ", "Alimentación", "Carne y charcutería", "Paté"),
    ("PATE", "Alimentación", "Carne y charcutería", "Paté"),
    ("RESERVA LONCHAS", "Alimentación", "Carne y charcutería", "Lonchas reserva"),
    ("PORCIONES BAC", "Alimentación", "Carne y charcutería", "Porciones de bacon"),
    ("PORCIONES", "Alimentación", "Carne y charcutería", "Porciones"),
    ("CARN", "Alimentación", "Carne y charcutería", "Carne"),
    ("CONTRA DES", "Alimentación", "Carne y charcutería", "Contramuslo deshuesado"),
    ("PULLED PORK", "Alimentación", "Carne y charcutería", "Pulled pork"),
    ("SAN JACOBO", "Alimentación", "Carne y charcutería", "San Jacobo"),
    ("DELICIAS DE POLLO", "Alimentación", "Carne y charcutería", "Delicias de pollo"),
    ("TIRAS POLLO", "Alimentación", "Carne y charcutería", "Tiras de pollo"),
    ("MEDALLONES MER", "Alimentación", "Pescado y marisco", "Medallones de merluza"),
    ("SEPPIA", "Alimentación", "Carne y charcutería", "Preparado de pollo"),
    ("SALMÓN", "Alimentación", "Pescado y marisco", "Salmón"),
    ("SALMON", "Alimentación", "Pescado y marisco", "Salmón"),
    ("DORADA", "Alimentación", "Pescado y marisco", "Dorada"),
    ("CHIRLA", "Alimentación", "Pescado y marisco", "Chirla"),
    ("GAMBAS", "Alimentación", "Pescado y marisco", "Gambas"),
    ("CAMARÓN", "Alimentación", "Pescado y marisco", "Camarón"),
    ("LANGOSTINO", "Alimentación", "Pescado y marisco", "Langostino"),
    ("BOQUERON", "Alimentación", "Pescado y marisco", "Boquerones"),
    ("BOQ ", "Alimentación", "Pescado y marisco", "Boquerones"),
    ("BOQ. ", "Alimentación", "Pescado y marisco", "Boquerones"),
    ("LUBINA", "Alimentación", "Pescado y marisco", "Lubina"),
    ("MERLUZA", "Alimentación", "Pescado y marisco", "Merluza"),
    ("FUMET", "Alimentación", "Pescado y marisco", "Fumet"),
    ("BACALAO", "Alimentación", "Pescado y marisco", "Bacalao"),
    ("ATÚN", "Alimentación", "Pescado y marisco", "Atún"),
    ("ATUN", "Alimentación", "Pescado y marisco", "Atún"),
    ("VENTRESCA", "Alimentación", "Pescado y marisco", "Ventresca"),
    ("BONITO", "Alimentación", "Pescado y marisco", "Bonito"),
    ("ALMEJA", "Alimentación", "Pescado y marisco", "Almeja"),
    ("MEJILLÓN", "Alimentación", "Pescado y marisco", "Mejillón"),
    ("MEJILLON", "Alimentación", "Pescado y marisco", "Mejillón"),
    ("MEJ. ", "Alimentación", "Pescado y marisco", "Mejillón"),
    ("NUGGETS SALMON", "Alimentación", "Pescado y marisco", "Nuggets de salmón"),
    ("ESCALOPIN", "Alimentación", "Pescado y marisco", "Escalopín de salmón"),
    ("RODAJA", "Alimentación", "Pescado y marisco", "Rodaja de pescado"),
    ("ARREGLO PELADO", "Alimentación", "Pescado y marisco", "Preparado pescado"),
    ("SEPIA", "Alimentación", "Pescado y marisco", "Sepia"),
    ("CHIPIRON", "Alimentación", "Pescado y marisco", "Chipirón"),
    ("RABAS", "Alimentación", "Pescado y marisco", "Rabas"),
    ("FIDEUA", "Alimentación", "Comida preparada", "Fideuá"),
    ("GALLO ", "Alimentación", "Pescado y marisco", "Gallo"),
    ("EMPERADOR", "Alimentación", "Pescado y marisco", "Emperador"),
    ("POKE", "Alimentación", "Comida preparada", "Poke"),
    ("TORTILLITAS CAMARON", "Alimentación", "Pescado y marisco", "Tortillitas de camarón"),
    ("SARDINILLAS", "Alimentación", "Conservas y caldos", "Sardinas"),
    ("MEJ. CHILE", "Alimentación", "Pescado y marisco", "Mejillones al chile"),
    ("WAKAME", "Alimentación", "Pescado y marisco", "Alga wakame"),
    ("PALITOS DE MERLUZA", "Alimentación", "Pescado y marisco", "Palitos de merluza"),
    ("TAQUITOS SALMÓN", "Alimentación", "Pescado y marisco", "Taquitos de salmón"),
    ("CARCASA Y ESPINAZO", "Alimentación", "Pescado y marisco", "Espinazo de pescado"),
    ("FLTE", "Alimentación", "Pescado y marisco", "Filete de pescado"),
    ("RODAJAS DE MERLUZA", "Alimentación", "Pescado y marisco", "Merluza en rodajas"),
    ("SALTEADO DE GAMBAS", "Alimentación", "Pescado y marisco", "Salteado de gambas"),
    ("AGUACATE", "Alimentación", "Fruta", "Aguacate"),
    ("ALBARICOQUE", "Alimentación", "Fruta", "Albaricoque"),
    ("ARANDANO", "Alimentación", "Fruta", "Arándanos"),
    ("ARÁNDANO", "Alimentación", "Fruta", "Arándanos"),
    ("PLATANO", "Alimentación", "Fruta", "Plátano"),
    ("BANANA", "Alimentación", "Fruta", "Plátano"),
    ("MANGO", "Alimentación", "Fruta", "Mango"),
    ("PERA", "Alimentación", "Fruta", "Pera"),
    ("PIÑA", "Alimentación", "Fruta", "Piña"),
    ("FRESÓN", "Alimentación", "Fruta", "Fresón"),
    ("FRESO", "Alimentación", "Fruta", "Fresón"),
    ("FRESA", "Alimentación", "Fruta", "Fresa"),
    ("KIWI", "Alimentación", "Fruta", "Kiwi"),
    ("MANDARINA", "Alimentación", "Fruta", "Mandarina"),
    ("CLEMENTINA", "Alimentación", "Fruta", "Clementina"),
    ("MELON", "Alimentación", "Fruta", "Melón"),
    ("MELÓN", "Alimentación", "Fruta", "Melón"),
    ("SANDÍA", "Alimentación", "Fruta", "Sandía"),
    ("MANZANA", "Alimentación", "Fruta", "Manzana"),
    ("MANZ. ", "Alimentación", "Fruta", "Manzana"),
    ("CEREZA", "Alimentación", "Fruta", "Cerezas"),
    ("LIMON", "Alimentación", "Fruta", "Limón"),
    ("NARANJA", "Alimentación", "Fruta", "Naranja"),
    ("NECTARINA", "Alimentación", "Fruta", "Nectarina"),
    ("MELOCOTON", "Alimentación", "Fruta", "Melocotón"),
    ("MELOCOTÓN", "Alimentación", "Fruta", "Melocotón"),
    ("PARAGUAYO", "Alimentación", "Fruta", "Paraguayo"),
    ("CIRUELA", "Alimentación", "Fruta", "Ciruela"),
    ("UVA", "Alimentación", "Fruta", "Uva"),
    ("ROJA DULCE", "Alimentación", "Fruta", "Manzana roja dulce"),
    ("PIP CALABAZA", "Alimentación", "Fruta", "Semillas calabaza"),
    ("GRANIZADO LIMÓN", "Bebidas", "Refrescos y zumos", "Granizado de limón"),
    ("GAZPACHO", "Alimentación", "Verdura y hortaliza", "Gazpacho"),
    ("SALMOREJO", "Alimentación", "Verdura y hortaliza", "Salmorejo"),
    ("TOMATE", "Alimentación", "Verdura y hortaliza", "Tomate"),
    ("TOM. RECETA", "Alimentación", "Conservas y caldos", "Tomate receta"),
    ("TOM.RECETA", "Alimentación", "Conservas y caldos", "Tomate receta"),
    ("TOM.FRITO", "Alimentación", "Conservas y caldos", "Tomate frito"),
    ("TOM. FRITO", "Alimentación", "Conservas y caldos", "Tomate frito"),
    ("TOMATE FRITO", "Alimentación", "Conservas y caldos", "Tomate frito"),
    ("TOMATE CONCENTRADO", "Alimentación", "Conservas y caldos", "Tomate concentrado"),
    ("TOMATE TAMIZADO", "Alimentación", "Conservas y caldos", "Tomate tamizado"),
    ("TOMATE TROCEADO", "Alimentación", "Conservas y caldos", "Tomate troceado"),
    ("TOMATE NATURAL", "Alimentación", "Conservas y caldos", "Tomate natural rallado"),
    ("TOMATE SECO", "Alimentación", "Conservas y caldos", "Tomate seco"),
    ("CALABACIN", "Alimentación", "Verdura y hortaliza", "Calabacín"),
    ("CALABAZA", "Alimentación", "Verdura y hortaliza", "Calabaza"),
    ("PIMIENTO", "Alimentación", "Verdura y hortaliza", "Pimiento"),
    ("PIM PIQ", "Alimentación", "Verdura y hortaliza", "Pimiento piquillo"),
    ("PUERRO", "Alimentación", "Verdura y hortaliza", "Puerro"),
    ("JUDIA", "Alimentación", "Verdura y hortaliza", "Judías"),
    ("JUDÍA", "Alimentación", "Verdura y hortaliza", "Judías"),
    ("GUISANTE", "Alimentación", "Verdura y hortaliza", "Guisantes"),
    ("ESPINACA", "Alimentación", "Verdura y hortaliza", "Espinacas"),
    ("ESPÁRRAGO", "Alimentación", "Verdura y hortaliza", "Espárragos"),
    ("ESPARRAGO", "Alimentación", "Verdura y hortaliza", "Espárragos"),
    ("BERENJENA", "Alimentación", "Verdura y hortaliza", "Berenjena"),
    ("ZANAHORIA", "Alimentación", "Verdura y hortaliza", "Zanahoria"),
    ("CEBOLLINO", "Alimentación", "Verdura y hortaliza", "Cebollino"),
    ("CEBOLLA", "Alimentación", "Verdura y hortaliza", "Cebolla"),
    ("CHAMPIÑON", "Alimentación", "Verdura y hortaliza", "Champiñón"),
    ("SETA", "Alimentación", "Verdura y hortaliza", "Setas"),
    ("PATATA", "Alimentación", "Verdura y hortaliza", "Patata"),
    ("BROTES", "Alimentación", "Verdura y hortaliza", "Brotes"),
    ("ICEBERG", "Alimentación", "Verdura y hortaliza", "Lechuga iceberg"),
    ("EDAMAME", "Alimentación", "Verdura y hortaliza", "Edamame"),
    ("BROCOLI", "Alimentación", "Verdura y hortaliza", "Brócoli"),
    ("BRÓCOLI", "Alimentación", "Verdura y hortaliza", "Brócoli"),
    ("COLIFLOR", "Alimentación", "Verdura y hortaliza", "Coliflor"),
    ("ALCACHOFA", "Alimentación", "Verdura y hortaliza", "Alcachofa"),
    ("COL LOMBARDA", "Alimentación", "Verdura y hortaliza", "Col lombarda"),
    ("REPOLLO", "Alimentación", "Verdura y hortaliza", "Repollo"),
    ("COLES DE BRUSELAS", "Alimentación", "Verdura y hortaliza", "Coles de Bruselas"),
    ("COLES BRUSELAS", "Alimentación", "Verdura y hortaliza", "Coles de Bruselas"),
    ("PEPINO", "Alimentación", "Verdura y hortaliza", "Pepino"),
    ("MENESTRA", "Alimentación", "Verdura y hortaliza", "Menestra"),
    ("PISTO", "Alimentación", "Verdura y hortaliza", "Pisto"),
    ("PARRILLADA VERDURA", "Alimentación", "Verdura y hortaliza", "Verduras a la parrilla"),
    ("WOK VERDURAS", "Alimentación", "Verdura y hortaliza", "Wok de verduras"),
    ("ACELGA", "Alimentación", "Verdura y hortaliza", "Acelga"),
    ("APIO", "Alimentación", "Verdura y hortaliza", "Apio"),
    ("CANÓNIGOS", "Alimentación", "Verdura y hortaliza", "Canónigos"),
    ("RÚCULA", "Alimentación", "Verdura y hortaliza", "Rúcula"),
    ("RUCULA", "Alimentación", "Verdura y hortaliza", "Rúcula"),
    ("ENDIBIA", "Alimentación", "Verdura y hortaliza", "Endibia"),
    ("ESCAROLA", "Alimentación", "Verdura y hortaliza", "Escarola"),
    ("ROMANA", "Alimentación", "Verdura y hortaliza", "Lechuga romana"),
    ("PURÉ DE PATATAS", "Alimentación", "Verdura y hortaliza", "Puré de patatas"),
    ("PURE DE PATATAS", "Alimentación", "Verdura y hortaliza", "Puré de patatas"),
    ("MAIZ DULCE", "Alimentación", "Conservas y caldos", "Maíz dulce"),
    ("MAÍZ DULCE", "Alimentación", "Conservas y caldos", "Maíz dulce"),
    ("MAIZ COCIDO", "Alimentación", "Conservas y caldos", "Maíz cocido"),
    ("MAÍZ COCIDO", "Alimentación", "Conservas y caldos", "Maíz cocido"),
    ("TABULÉ", "Alimentación", "Comida preparada", "Tabulé"),
    ("TABULE", "Alimentación", "Comida preparada", "Tabulé"),
    ("VERDURAS ASADAS", "Alimentación", "Verdura y hortaliza", "Verduras asadas"),
    ("VERDURAS", "Alimentación", "Verdura y hortaliza", "Verduras"),
    ("SALTEADO DE VERDURAS", "Alimentación", "Verdura y hortaliza", "Salteado de verduras"),
    ("MEZCLA DE VERDURAS", "Alimentación", "Verdura y hortaliza", "Mezcla de verduras"),
    ("3 VEGETALES", "Alimentación", "Verdura y hortaliza", "3 vegetales"),
    ("PIMIENTO BACALAO", "Alimentación", "Comida preparada", "Pimiento relleno de bacalao"),
    ("REMOLL", "Alimentación", "Verdura y hortaliza", "Remolacha"),
    ("COLES", "Alimentación", "Verdura y hortaliza", "Coles"),
    ("BATATA", "Alimentación", "Verdura y hortaliza", "Batata"),
    ("CEBOLLA CARAMELIZADA", "Alimentación", "Verdura y hortaliza", "Cebolla caramelizada"),
    ("ESP VERDE", "Alimentación", "Verdura y hortaliza", "Espárrago verde"),
    ("PANECILLO", "Alimentación", "Pan y bollería", "Panecillo"),
    ("PANEC.", "Alimentación", "Pan y bollería", "Panecillo"),
    ("PAN TOST", "Alimentación", "Pan y bollería", "Pan tostado"),
    ("PAN TOSTADO", "Alimentación", "Pan y bollería", "Pan tostado"),
    ("PAN RALLADO", "Alimentación", "Pan y bollería", "Pan rallado"),
    ("PAN DE MOLDE", "Alimentación", "Pan y bollería", "Pan de molde"),
    ("PAN M.", "Alimentación", "Pan y bollería", "Pan de molde"),
    ("PAN DE LECHE", "Alimentación", "Pan y bollería", "Pan de leche"),
    ("PAN DE PUEBLO", "Alimentación", "Pan y bollería", "Pan de pueblo"),
    ("PAN DE ESPIGA", "Alimentación", "Pan y bollería", "Pan de espiga"),
    ("PAN DE FIBRA", "Alimentación", "Pan y bollería", "Pan de fibra"),
    ("PAN CENTENO", "Alimentación", "Pan y bollería", "Pan de centeno"),
    ("PAN INTEGRAL", "Alimentación", "Pan y bollería", "Pan integral"),
    ("PAN ESPELTA", "Alimentación", "Pan y bollería", "Pan de espelta"),
    ("PAN AVENA", "Alimentación", "Pan y bollería", "Pan de avena"),
    ("PAN MAÍZ", "Alimentación", "Pan y bollería", "Pan de maíz"),
    ("PAN TORRIJAS", "Alimentación", "Pan y bollería", "Pan de torrijas"),
    ("PAN HOT DOG", "Alimentación", "Pan y bollería", "Pan de hot dog"),
    ("PAN VIENA", "Alimentación", "Pan y bollería", "Pan de Viena"),
    ("PAN BRIOCHE", "Alimentación", "Pan y bollería", "Pan brioche"),
    ("PAN CEREAL", "Alimentación", "Pan y bollería", "Pan de cereales"),
    ("PAN RUSTICA", "Alimentación", "Pan y bollería", "Pan rústico"),
    ("PAN RÚSTICA", "Alimentación", "Pan y bollería", "Pan rústico"),
    ("PAN 30%", "Alimentación", "Pan y bollería", "Pan integral"),
    ("PAN 51%", "Alimentación", "Pan y bollería", "Pan integral"),
    ("PAN BLANCO", "Alimentación", "Pan y bollería", "Pan blanco"),
    ("PAN", "Alimentación", "Pan y bollería", "Pan"),
    ("BARRA CAMPESINA", "Alimentación", "Pan y bollería", "Barra campesina"),
    ("BARRA RUSTICA", "Alimentación", "Pan y bollería", "Barra rústica"),
    ("BARRA RÚSTICA", "Alimentación", "Pan y bollería", "Barra rústica"),
    ("BARRA DE PAN", "Alimentación", "Pan y bollería", "Barra de pan"),
    ("BARRA", "Alimentación", "Pan y bollería", "Barra de pan"),
    ("BAGUETTE", "Alimentación", "Pan y bollería", "Baguette"),
    ("BAGEL", "Alimentación", "Pan y bollería", "Bagel"),
    ("TXAPATA", "Alimentación", "Pan y bollería", "Chapata"),
    ("CROISSANT", "Alimentación", "Pan y bollería", "Croissant"),
    ("M.CROISS", "Alimentación", "Pan y bollería", "Croissant"),
    ("HOJALDRE", "Alimentación", "Pan y bollería", "Hojaldre"),
    ("MAGDALENA", "Alimentación", "Pan y bollería", "Magdalena"),
    ("SOBAOS", "Alimentación", "Pan y bollería", "Sobaos"),
    ("ROSQUILLA", "Alimentación", "Pan y bollería", "Rosquilla"),
    ("ROSQ ", "Alimentación", "Pan y bollería", "Rosquilla"),
    ("BERLINA", "Alimentación", "Pan y bollería", "Berlinesa"),
    ("BIZCOCHO", "Alimentación", "Pan y bollería", "Bizcocho"),
    ("BIZCOCHOS", "Alimentación", "Pan y bollería", "Bizcochos"),
    ("MANTECADAS", "Alimentación", "Pan y bollería", "Mantecadas"),
    ("ENSAIMADAS", "Alimentación", "Pan y bollería", "Ensaïmada"),
    ("PANDORO", "Alimentación", "Pan y bollería", "Pandoro"),
    ("NAPOLITANA", "Alimentación", "Pan y bollería", "Napolitana"),
    ("SUPERSANDWICH", "Alimentación", "Pan y bollería", "Super sándwich"),
    ("MINI SANDWICH", "Alimentación", "Pan y bollería", "Mini sándwich"),
    ("SÁNDWICH", "Alimentación", "Pan y bollería", "Sándwich"),
    ("SANDWICH", "Alimentación", "Pan y bollería", "Sándwich"),
    ("MINISANDWICH", "Alimentación", "Pan y bollería", "Mini sándwich"),
    ("BOCAD.", "Alimentación", "Pan y bollería", "Bocadillo"),
    ("BOCADILLOS", "Alimentación", "Pan y bollería", "Bocadillos"),
    ("TORTITA", "Alimentación", "Pan y bollería", "Tortitas"),
    ("BISCOTTE", "Alimentación", "Pan y bollería", "Biscotes"),
    ("BISC. ", "Alimentación", "Pan y bollería", "Biscotes"),
    ("MINI BISC", "Alimentación", "Pan y bollería", "Biscotes"),
    ("TOSTAS", "Alimentación", "Pan y bollería", "Tostadas"),
    ("PICATOSTE", "Alimentación", "Pan y bollería", "Picatostes"),
    ("PICOS", "Alimentación", "Pan y bollería", "Picos"),
    ("PIQUITOS", "Alimentación", "Pan y bollería", "Piquitos"),
    ("REGAÑ", "Alimentación", "Pan y bollería", "Regañá"),
    ("PAJARITAS", "Alimentación", "Pan y bollería", "Pajaritas"),
    ("GRISSINI", "Alimentación", "Pan y bollería", "Grissini"),
    ("CRAKERS", "Alimentación", "Pan y bollería", "Crackers"),
    ("CRACKERS", "Alimentación", "Pan y bollería", "Crackers"),
    ("PIADINA", "Alimentación", "Pan y bollería", "Piadina"),
    ("GALLETAS SALADAS", "Alimentación", "Pan y bollería", "Galletas saladas"),
    ("MINI SALADAS", "Alimentación", "Pan y bollería", "Mini salados"),
    ("SERRANOS", "Alimentación", "Pan y bollería", "Serranitos"),
    ("SURTIDO PICOS", "Alimentación", "Pan y bollería", "Surtido picos"),
    ("PALOMIT", "Alimentación", "Snacks y frutos secos", "Palomitas"),
    ("FIDEO", "Alimentación", "Pasta, arroz y legumbres", "Fideos"),
    ("MACARRON", "Alimentación", "Pasta, arroz y legumbres", "Macarrones"),
    ("MACARRÓN", "Alimentación", "Pasta, arroz y legumbres", "Macarrones"),
    ("PENNE", "Alimentación", "Pasta, arroz y legumbres", "Penne"),
    ("LINGUINE", "Alimentación", "Pasta, arroz y legumbres", "Linguine"),
    ("NOODLES", "Alimentación", "Pasta, arroz y legumbres", "Noodles"),
    ("TORTELLONI", "Alimentación", "Pasta, arroz y legumbres", "Tortelloni"),
    ("SPAGHETTI", "Alimentación", "Pasta, arroz y legumbres", "Spaghetti"),
    ("PASTA INFANTIL", "Alimentación", "Pasta, arroz y legumbres", "Pasta infantil"),
    ("LASAÑA", "Alimentación", "Comida preparada", "Lasaña"),
    ("ENSAPASTA", "Alimentación", "Pasta, arroz y legumbres", "Ensalada de pasta"),
    ("COUS COUS", "Alimentación", "Pasta, arroz y legumbres", "Cuscús"),
    ("ARROZ CON POLLO", "Alimentación", "Comida preparada", "Arroz con pollo"),
    ("ARROZ TRES DELICIAS", "Alimentación", "Comida preparada", "Arroz tres delicias"),
    ("ARROZ", "Alimentación", "Pasta, arroz y legumbres", "Arroz"),
    ("QUINOA", "Alimentación", "Pasta, arroz y legumbres", "Quinoa"),
    ("ALUBIA", "Alimentación", "Pasta, arroz y legumbres", "Alubias"),
    ("GARBANZO", "Alimentación", "Pasta, arroz y legumbres", "Garbanzos"),
    ("LENTEJA", "Alimentación", "Pasta, arroz y legumbres", "Lentejas"),
    ("LENTEJA PARDINA", "Alimentación", "Pasta, arroz y legumbres", "Lenteja pardina"),
    ("FABADA", "Alimentación", "Pasta, arroz y legumbres", "Fabada"),
    ("RIOJANA", "Alimentación", "Pasta, arroz y legumbres", "Garbanzos riojana"),
    ("JARDINERA", "Alimentación", "Pasta, arroz y legumbres", "Lentejas jardinera"),
    ("COCINA DE LEGUMBRES", "Alimentación", "Pasta, arroz y legumbres", "Legumbres"),
    ("LEGUMBRE", "Alimentación", "Pasta, arroz y legumbres", "Legumbres"),
    ("HUMMUS", "Alimentación", "Comida preparada", "Hummus"),
    ("COCKTAIL GALL SALADA", "Alimentación", "Conservas y caldos", "Cocktail de gall"),
    ("COCKTAIL", "Alimentación", "Conservas y caldos", "Cocktail de mariscos"),
    ("ACEITUNA", "Alimentación", "Conservas y caldos", "Aceitunas"),
    ("ACEITUNAS", "Alimentación", "Conservas y caldos", "Aceitunas"),
    ("BONITO NORTE", "Alimentación", "Conservas y caldos", "Bonito en conserva"),
    ("BONITO MIGAS", "Alimentación", "Conservas y caldos", "Bonito en conserva"),
    ("ATUN CLARO", "Alimentación", "Conservas y caldos", "Atún en conserva"),
    ("ATÚN CLARO", "Alimentación", "Conservas y caldos", "Atún en conserva"),
    ("PEPINILLO", "Alimentación", "Conservas y caldos", "Pepinillos"),
    ("JALAPEÑOS", "Alimentación", "Conservas y caldos", "Jalapeños"),
    ("CHOPPED LATA", "Alimentación", "Conservas y caldos", "Champiñón en lata"),
    ("MIX FRUTOS ROJOS", "Alimentación", "Conservas y caldos", "Mix de frutos rojos"),
    ("CALDO", "Alimentación", "Conservas y caldos", "Caldo"),
    ("CREMA DE CALABAZA", "Alimentación", "Conservas y caldos", "Crema de calabaza"),
    ("CREMA CALABACÍN", "Alimentación", "Conservas y caldos", "Crema de calabacín"),
    ("CREMA DE VERDURAS", "Alimentación", "Conservas y caldos", "Crema de verduras"),
    ("CREMA SETAS", "Alimentación", "Conservas y caldos", "Crema de setas"),
    ("CREMA MARISCO", "Alimentación", "Conservas y caldos", "Crema de marisco"),
    ("SOPA", "Alimentación", "Conservas y caldos", "Sopa"),
    ("VICHYSSOISE", "Alimentación", "Conservas y caldos", "Vichyssoise"),
    ("MISO", "Alimentación", "Conservas y caldos", "Sopa de miso"),
    ("ACEITE DE OLIVA", "Alimentación", "Aceite, salsas y condimentos", "Aceite de oliva"),
    ("ACEITE OLIVA", "Alimentación", "Aceite, salsas y condimentos", "Aceite de oliva"),
    ("ACEITE GIRASOL", "Alimentación", "Aceite, salsas y condimentos", "Aceite de girasol"),
    ("VIRGEN EXTRA", "Alimentación", "Aceite, salsas y condimentos", "Aceite virgen extra"),
    ("ACEITE", "Alimentación", "Aceite, salsas y condimentos", "Aceite"),
    ("SAL ", "Alimentación", "Aceite, salsas y condimentos", "Sal"),
    ("SALERO", "Alimentación", "Aceite, salsas y condimentos", "Sal"),
    ("SAL 60%", "Alimentación", "Aceite, salsas y condimentos", "Sal"),
    ("AJO SECO", "Alimentación", "Aceite, salsas y condimentos", "Ajo seco"),
    ("AJO GRANULADO", "Alimentación", "Aceite, salsas y condimentos", "Ajo granulado"),
    ("AJO", "Alimentación", "Aceite, salsas y condimentos", "Ajo"),
    ("LAUREL", "Alimentación", "Aceite, salsas y condimentos", "Laurel"),
    ("TOMILLO", "Alimentación", "Aceite, salsas y condimentos", "Tomillo"),
    ("ORÉGANO", "Alimentación", "Aceite, salsas y condimentos", "Orégano"),
    ("OREGANO", "Alimentación", "Aceite, salsas y condimentos", "Orégano"),
    ("PEREJIL", "Alimentación", "Aceite, salsas y condimentos", "Perejil"),
    ("COMINOS", "Alimentación", "Aceite, salsas y condimentos", "Comino"),
    ("AZAFRÁN", "Alimentación", "Aceite, salsas y condimentos", "Azafrán"),
    ("CURRY", "Alimentación", "Aceite, salsas y condimentos", "Curry"),
    ("ÑORAS", "Alimentación", "Aceite, salsas y condimentos", "Ñoras"),
    ("ALIÑO", "Alimentación", "Aceite, salsas y condimentos", "Aliño"),
    ("ESPECIAS", "Alimentación", "Aceite, salsas y condimentos", "Especias"),
    ("HIERBAS PROVENZAL", "Alimentación", "Aceite, salsas y condimentos", "Hierbas provenzales"),
    ("SÉSAMO", "Alimentación", "Aceite, salsas y condimentos", "Sésamo"),
    ("AJONJOLÍ", "Alimentación", "Aceite, salsas y condimentos", "Sésamo"),
    ("VINAGRE JEREZ", "Alimentación", "Aceite, salsas y condimentos", "Vinagre de Jerez"),
    ("VINAGRE", "Alimentación", "Aceite, salsas y condimentos", "Vinagre"),
    ("BICARBONATO", "Alimentación", "Aceite, salsas y condimentos", "Bicarbonato"),
    ("MENTA POLEO", "Alimentación", "Aceite, salsas y condimentos", "Menta poleo"),
    ("POLEO MENTA", "Alimentación", "Aceite, salsas y condimentos", "Menta poleo"),
    ("SALSA BARBACOA", "Alimentación", "Aceite, salsas y condimentos", "Salsa barbacoa"),
    ("SALSA BBQ", "Alimentación", "Aceite, salsas y condimentos", "Salsa barbacoa"),
    ("SALSA MEXICANA", "Alimentación", "Aceite, salsas y condimentos", "Salsa mexicana"),
    ("SALSA DE SOJA", "Alimentación", "Aceite, salsas y condimentos", "Salsa de soja"),
    ("SALSA TERIYAKI", "Alimentación", "Aceite, salsas y condimentos", "Salsa teriyaki"),
    ("SALSA CARBONARA", "Alimentación", "Aceite, salsas y condimentos", "Salsa carbonara"),
    ("SALSA MIEL Y MOSTAZA", "Alimentación", "Aceite, salsas y condimentos", "Salsa miel y mostaza"),
    ("SALSA FRESCA QUESOS", "Alimentación", "Aceite, salsas y condimentos", "Salsa de quesos"),
    ("SALSA LIGERA", "Alimentación", "Aceite, salsas y condimentos", "Salsa ligera"),
    ("KÉTCHUP", "Alimentación", "Aceite, salsas y condimentos", "Kétchup"),
    ("KETCHUP", "Alimentación", "Aceite, salsas y condimentos", "Kétchup"),
    ("MAHONES", "Alimentación", "Aceite, salsas y condimentos", "Mayonesa"),
    ("MAYONESA", "Alimentación", "Aceite, salsas y condimentos", "Mayonesa"),
    ("MOSTAZA", "Alimentación", "Aceite, salsas y condimentos", "Mostaza"),
    ("MOJO", "Alimentación", "Aceite, salsas y condimentos", "Mojo"),
    ("RANCH", "Alimentación", "Aceite, salsas y condimentos", "Salsa ranch"),
    ("SALSA", "Alimentación", "Aceite, salsas y condimentos", "Salsa"),
    ("PIZZA", "Alimentación", "Comida preparada", "Pizza"),
    ("PAELLA", "Alimentación", "Comida preparada", "Paella"),
    ("PRE.PAELLA", "Alimentación", "Comida preparada", "Paella preparada"),
    ("ARREGL.PAELLA", "Alimentación", "Comida preparada", "Paella preparada"),
    ("COCIDO", "Alimentación", "Comida preparada", "Cocido"),
    ("CHILI", "Alimentación", "Comida preparada", "Chili con carne"),
    ("FAJITAS", "Alimentación", "Comida preparada", "Fajitas"),
    ("KEBAB", "Alimentación", "Comida preparada", "Kebab"),
    ("NUGGETS", "Alimentación", "Comida preparada", "Nuggets"),
    ("TORTILLA DE MAIZ", "Alimentación", "Comida preparada", "Tortilla de maíz"),
    ("TORTILLA TRIGO", "Alimentación", "Comida preparada", "Tortilla de trigo"),
    ("TORTILLAS MEXICANAS", "Alimentación", "Comida preparada", "Tortillas mexicanas"),
    ("TORTILLA ", "Alimentación", "Comida preparada", "Tortilla de patatas"),
    ("TORTITAS DE ARROZ", "Alimentación", "Cereales y desayuno", "Tortitas de arroz"),
    ("TORTITAS DE MAIZ", "Alimentación", "Cereales y desayuno", "Tortitas de maíz"),
    ("TORTITA CAMPESTRE", "Alimentación", "Cereales y desayuno", "Tortita campestre"),
    ("EMPANADA", "Alimentación", "Comida preparada", "Empanada"),
    ("EMPANADILLAS", "Alimentación", "Comida preparada", "Empanadillas"),
    ("POKE", "Alimentación", "Comida preparada", "Poke"),
    ("PARMIGIANA", "Alimentación", "Comida preparada", "Parmigiana"),
    ("CARPACCIO", "Alimentación", "Comida preparada", "Carpaccio"),
    ("QUICHE", "Alimentación", "Comida preparada", "Quiche"),
    ("PURE", "Alimentación", "Comida preparada", "Puré"),
    ("SAN JACOBO", "Alimentación", "Comida preparada", "San Jacobo"),
    ("DELICIA", "Alimentación", "Comida preparada", "Delicia"),
    ("PREPALIMEN CACAO", "Alimentación", "Comida preparada", "Preparado"),
    ("PREPARADO CRUJIENTE", "Alimentación", "Comida preparada", "Preparado crujiente"),
    ("MENESTRA", "Alimentación", "Comida preparada", "Menestra"),
    ("GRANIZADO", "Bebidas", "Refrescos y zumos", "Granizado"),
    ("ENSALADA", "Alimentación", "Comida preparada", "Ensalada preparada"),
    ("ENS. ", "Alimentación", "Comida preparada", "Ensalada preparada"),
    ("ENS.", "Alimentación", "Comida preparada", "Ensalada preparada"),
    ("ENSALADILLA", "Alimentación", "Comida preparada", "Ensaladilla"),
    ("GUACAMOLE", "Alimentación", "Comida preparada", "Guacamole"),
    ("MAIZ DULCE", "Alimentación", "Conservas y caldos", "Maíz dulce"),
    ("NESCAFÉ", "Bebidas", "Café, té e infusiones", "Nescafé"),
    ("NESCAFE", "Bebidas", "Café, té e infusiones", "Nescafé"),
    ("DESCAF.NATURAL", "Bebidas", "Café, té e infusiones", "Café descafeinado"),
    ("DESCAFEINADO", "Bebidas", "Café, té e infusiones", "Café descafeinado"),
    ("DESCAF.", "Bebidas", "Café, té e infusiones", "Café descafeinado"),
    ("C 0,0", "Bebidas", "Café, té e infusiones", "Café descafeinado"),
    ("C. TOSTADO", "Bebidas", "Café, té e infusiones", "Café tostado"),
    ("C TOSTADO", "Bebidas", "Café, té e infusiones", "Café tostado"),
    ("CAFE", "Bebidas", "Café, té e infusiones", "Café"),
    ("CAFÉ", "Bebidas", "Café, té e infusiones", "Café"),
    ("CAPSULA CAFE", "Bebidas", "Café, té e infusiones", "Cápsulas de café"),
    ("CAP. ", "Bebidas", "Café, té e infusiones", "Cápsulas de café"),
    ("ESPRESSO", "Bebidas", "Café, té e infusiones", "Café espresso"),
    ("CAPUCCINO", "Bebidas", "Café, té e infusiones", "Capuccino"),
    ("CAPPUCCINO", "Bebidas", "Café, té e infusiones", "Cappuccino"),
    ("SOLUBLE DESC", "Bebidas", "Café, té e infusiones", "Café soluble descafeinado"),
    ("SOLUBLE", "Bebidas", "Café, té e infusiones", "Café soluble"),
    ("INFUSION", "Bebidas", "Café, té e infusiones", "Infusión"),
    ("MANZANILLA", "Bebidas", "Café, té e infusiones", "Manzanilla"),
    ("MANZANILLA ANIS", "Bebidas", "Café, té e infusiones", "Manzanilla con anís"),
    ("TEA ", "Bebidas", "Café, té e infusiones", "Té"),
    ("TÉ ", "Bebidas", "Café, té e infusiones", "Té"),
    ("CHOCOLATE", "Alimentación", "Dulces y chocolate", "Chocolate"),
    ("CHOCO", "Alimentación", "Dulces y chocolate", "Chocolate"),
    ("CHOC", "Alimentación", "Dulces y chocolate", "Chocolate"),
    ("COOKIES", "Alimentación", "Dulces y chocolate", "Cookies"),
    ("COOKIE", "Alimentación", "Dulces y chocolate", "Cookies"),
    ("CREMA CACAO", "Alimentación", "Dulces y chocolate", "Crema de cacao"),
    ("NOCILLA", "Alimentación", "Dulces y chocolate", "Crema de cacao"),
    ("CACAO", "Alimentación", "Dulces y chocolate", "Cacao"),
    ("TURRON", "Alimentación", "Dulces y chocolate", "Turrón"),
    ("TURRÓN", "Alimentación", "Dulces y chocolate", "Turrón"),
    ("POLVORON", "Alimentación", "Dulces y chocolate", "Polvorón"),
    ("MAZAPÁN", "Alimentación", "Dulces y chocolate", "Mazapán"),
    ("TARTA", "Alimentación", "Dulces y chocolate", "Tarta"),
    ("TORTA ", "Alimentación", "Dulces y chocolate", "Tarta"),
    ("TIRAMISU", "Alimentación", "Dulces y chocolate", "Tiramisú"),
    ("TIRAMISÚ", "Alimentación", "Dulces y chocolate", "Tiramisú"),
    ("HELADO", "Alimentación", "Dulces y chocolate", "Helado"),
    ("MINI HELADOS", "Alimentación", "Dulces y chocolate", "Mini helados"),
    ("CONO ", "Alimentación", "Dulces y chocolate", "Cono"),
    ("CONOS", "Alimentación", "Dulces y chocolate", "Conos"),
    ("MINICONO", "Alimentación", "Dulces y chocolate", "Mini cono"),
    ("OBLEAS", "Alimentación", "Dulces y chocolate", "Obleas"),
    ("SORBETE", "Alimentación", "Dulces y chocolate", "Sorbete"),
    ("COULANT", "Alimentación", "Dulces y chocolate", "Coulant"),
    ("TOPPING", "Alimentación", "Dulces y chocolate", "Topping"),
    ("SIROPE", "Alimentación", "Dulces y chocolate", "Sirope"),
    ("MARMELADA", "Alimentación", "Dulces y chocolate", "Mermelada"),
    ("MERMELADA", "Alimentación", "Dulces y chocolate", "Mermelada"),
    ("MERM. ", "Alimentación", "Dulces y chocolate", "Mermelada"),
    ("MERM.", "Alimentación", "Dulces y chocolate", "Mermelada"),
    ("MIEL", "Alimentación", "Dulces y chocolate", "Miel"),
    ("AZUCAR", "Alimentación", "Dulces y chocolate", "Azúcar"),
    ("AZÚCAR", "Alimentación", "Dulces y chocolate", "Azúcar"),
    ("SACARINA", "Alimentación", "Dulces y chocolate", "Sacarina"),
    ("STEVIA", "Alimentación", "Dulces y chocolate", "Stevia"),
    ("GALLETA", "Alimentación", "Dulces y chocolate", "Galletas"),
    ("GALLETA ", "Alimentación", "Dulces y chocolate", "Galletas"),
    ("GALL ", "Alimentación", "Dulces y chocolate", "Galletas"),
    ("GALL. ", "Alimentación", "Dulces y chocolate", "Galletas"),
    ("DIGESTIVE", "Alimentación", "Dulces y chocolate", "Galletas digestive"),
    ("DIG ", "Alimentación", "Dulces y chocolate", "Galletas digestive"),
    ("DIGES", "Alimentación", "Dulces y chocolate", "Galletas digestive"),
    ("MAGDALENA", "Alimentación", "Pan y bollería", "Magdalena"),
    ("BARRITA", "Alimentación", "Dulces y chocolate", "Barrita"),
    ("BARR ", "Alimentación", "Dulces y chocolate", "Barra de cereales"),
    ("BARRA COLOR", "Higiene personal", "Cuidado corporal y facial", "Barra de color"),
    ("PALITO", "Alimentación", "Dulces y chocolate", "Palito"),
    ("PALITOS FRUTOS", "Alimentación", "Dulces y chocolate", "Palitos frutos"),
    ("GOMINOLA", "Alimentación", "Dulces y chocolate", "Gominolas"),
    ("CARAMELO", "Alimentación", "Dulces y chocolate", "Caramelos"),
    ("CHICLE", "Alimentación", "Dulces y chocolate", "Chicle"),
    ("REGALIZ", "Alimentación", "Dulces y chocolate", "Regaliz"),
    ("BOMBÓN", "Alimentación", "Dulces y chocolate", "Bombones"),
    ("BOMBON", "Alimentación", "Dulces y chocolate", "Bombones"),
    ("BASTONCILLO", "Alimentación", "Dulces y chocolate", "Bastón de caramelo"),
    ("COCO RALLADO", "Alimentación", "Harinas y repostería", "Coco rallado"),
    ("CABELLO DE ANGEL", "Alimentación", "Dulces y chocolate", "Cabello de ángel"),
    ("CHOCOLATE A GOTAS", "Alimentación", "Dulces y chocolate", "Gotas de chocolate"),
    ("BISCUIT", "Alimentación", "Dulces y chocolate", "Biscuit"),
    ("REBUENAS", "Alimentación", "Dulces y chocolate", "Rebuenas"),
    ("BALLS", "Alimentación", "Dulces y chocolate", "Bolas de chocolate"),
    ("CHOCODAYS", "Alimentación", "Dulces y chocolate", "ChocoDays"),
    ("CHOCOIRIS", "Alimentación", "Dulces y chocolate", "ChocoIris"),
    ("CHOCOMINIS", "Alimentación", "Dulces y chocolate", "ChocoMinis"),
    ("POPITOS", "Alimentación", "Dulces y chocolate", "Popitos"),
    ("PALITOS", "Alimentación", "Dulces y chocolate", "Palitos"),
    ("GALLETITAS", "Alimentación", "Dulces y chocolate", "Galletitas"),
    ("DELIZZE", "Alimentación", "Dulces y chocolate", "Delizze"),
    ("HALLOWEEN", "Alimentación", "Dulces y chocolate", "Surtido Halloween"),
    ("ADVIENTO", "Alimentación", "Dulces y chocolate", "Calendario de adviento"),
    ("MELOCOTÓN AMARILLO", "Alimentación", "Fruta", "Melocotón"),
    ("FIGURITAS", "Alimentación", "Dulces y chocolate", "Figuritas"),
    ("REGAÑA", "Alimentación", "Pan y bollería", "Regañá"),
    ("CAITA", "Alimentación", "Dulces y chocolate", "Galletas"),
    ("CEREAL", "Alimentación", "Cereales y desayuno", "Cereales"),
    ("MUESLI", "Alimentación", "Cereales y desayuno", "Muesli"),
    ("AVENA", "Alimentación", "Cereales y desayuno", "Avena"),
    ("COPOS DE AVENA", "Alimentación", "Cereales y desayuno", "Copos de avena"),
    ("COPO INTEGRAL", "Alimentación", "Cereales y desayuno", "Copos integrales"),
    ("INTEGRAL TRIGO", "Alimentación", "Cereales y desayuno", "Copos de trigo"),
    ("30% INTEGRAL", "Alimentación", "Cereales y desayuno", "Copos integrales"),
    ("ESPELTA", "Alimentación", "Cereales y desayuno", "Cereales de espelta"),
    ("CHOCOIRIS", "Alimentación", "Dulces y chocolate", "ChocoIris"),
    ("T. SUCHARD", "Alimentación", "Cereales y desayuno", "Cereales Suchard"),
    ("CACAHUETE", "Alimentación", "Snacks y frutos secos", "Cacahuetes"),
    ("ANACARDO", "Alimentación", "Snacks y frutos secos", "Anacardos"),
    ("PIÑONES", "Alimentación", "Snacks y frutos secos", "Piñones"),
    ("NUEZ", "Alimentación", "Snacks y frutos secos", "Nueces"),
    ("PISTACHO", "Alimentación", "Snacks y frutos secos", "Pistachos"),
    ("ALMENDRA", "Alimentación", "Snacks y frutos secos", "Almendras"),
    ("PASAS", "Alimentación", "Snacks y frutos secos", "Pasas"),
    ("CHÍA", "Alimentación", "Snacks y frutos secos", "Chía"),
    ("PIPA", "Alimentación", "Snacks y frutos secos", "Pipas"),
    ("FRUTOS SECOS", "Alimentación", "Snacks y frutos secos", "Frutos secos"),
    ("COCKTAIL TOST", "Alimentación", "Snacks y frutos secos", "Frutos secos"),
    ("NUEZ", "Alimentación", "Snacks y frutos secos", "Nueces"),
    ("PATATAS EXTRACRUNCH", "Alimentación", "Snacks y frutos secos", "Patatas fritas"),
    ("PATATINA EXTRACRUNCH", "Alimentación", "Snacks y frutos secos", "Patatas fritas"),
    ("STICKS DE PATATA", "Alimentación", "Snacks y frutos secos", "Sticks de patata"),
    ("TWISTER FRIES", "Alimentación", "Snacks y frutos secos", "Patatas twist"),
    ("WAFFLE FRIES", "Alimentación", "Snacks y frutos secos", "Patatas waffle"),
    ("PAT. CLASSICAS", "Alimentación", "Snacks y frutos secos", "Patatas clásicas"),
    ("PATATAS GAJO", "Alimentación", "Snacks y frutos secos", "Patatas gajo"),
    ("PATATAS HORNO", "Alimentación", "Snacks y frutos secos", "Patatas al horno"),
    ("PATATAS CON PIEL", "Alimentación", "Snacks y frutos secos", "Patatas con piel"),
    ("PALOMIT", "Alimentación", "Snacks y frutos secos", "Palomitas"),
    ("PALOMITAS", "Alimentación", "Snacks y frutos secos", "Palomitas"),
    ("NACHOS", "Alimentación", "Snacks y frutos secos", "Nachos"),
    ("AROS DE MAÍZ", "Alimentación", "Snacks y frutos secos", "Aros de maíz"),
    ("DORITOS", "Alimentación", "Snacks y frutos secos", "Doritos"),
    ("CHEETOS", "Alimentación", "Snacks y frutos secos", "Cheetos"),
    ("TIRAS FRITAS", "Alimentación", "Snacks y frutos secos", "Tiras fritas"),
    ("MINI BOOM", "Alimentación", "Snacks y frutos secos", "Snacks"),
    ("SNACK 100% ESP", "Alimentación", "Snacks y frutos secos", "Snacks"),
    ("CUQUITOS", "Alimentación", "Snacks y frutos secos", "Snacks"),
    ("SUPER CUQUIS", "Alimentación", "Snacks y frutos secos", "Snacks"),
    ("DIVERXUXES", "Alimentación", "Snacks y frutos secos", "Snacks"),
    ("DIVERKAO", "Alimentación", "Snacks y frutos secos", "Snacks"),
    ("BLOQUE TRES GUSTOS", "Alimentación", "Snacks y frutos secos", "Bloque de snacks"),
    ("BLOQUE TURRON", "Alimentación", "Dulces y chocolate", "Bloque de turrón"),
    ("STICKS VEGETALES", "Alimentación", "Snacks y frutos secos", "Sticks vegetales"),
    ("PAJARITAS VEGETALES", "Alimentación", "Snacks y frutos secos", "Pajaritas vegetales"),
    ("HARINA", "Alimentación", "Harinas y repostería", "Harina"),
    ("IMPULSOR", "Alimentación", "Harinas y repostería", "Impulsor"),
    ("AZÚCAR GLAS", "Alimentación", "Dulces y chocolate", "Azúcar glas"),
    ("AZUCARITOS", "Alimentación", "Dulces y chocolate", "Azucarillos"),
    ("MOLDE", "Alimentación", "Harinas y repostería", "Molde"),
    ("FUNDIR", "Alimentación", "Dulces y chocolate", "Chocolate para fundir"),
    ("CHOCO GOTAS", "Alimentación", "Dulces y chocolate", "Gotas de chocolate"),
    ("DET LIQ", "Limpieza del hogar", "Detergente y suavizante", "Detergente líquido"),
    ("DET ", "Limpieza del hogar", "Detergente y suavizante", "Detergente"),
    ("DETERGENTE", "Limpieza del hogar", "Detergente y suavizante", "Detergente"),
    ("DETERG", "Limpieza del hogar", "Detergente y suavizante", "Detergente"),
    ("SUAVIZANTE", "Limpieza del hogar", "Detergente y suavizante", "Suavizante"),
    ("CÁPSULA ROPA", "Limpieza del hogar", "Detergente y suavizante", "Cápsulas detergente"),
    ("CAPSULA ROPA", "Limpieza del hogar", "Detergente y suavizante", "Cápsulas detergente"),
    ("CÁPSULAS TODO", "Limpieza del hogar", "Detergente y suavizante", "Cápsulas detergente"),
    ("LEJIA", "Limpieza del hogar", "Lejía y desinfectantes", "Lejía"),
    ("LEJÍA", "Limpieza del hogar", "Lejía y desinfectantes", "Lejía"),
    ("LAVAVAJILLA", "Limpieza del hogar", "Lavavajillas", "Lavavajillas"),
    ("LAVAVAJILLAS", "Limpieza del hogar", "Lavavajillas", "Lavavajillas"),
    ("SAL LAVAVAJILLAS", "Limpieza del hogar", "Lavavajillas", "Sal lavavajillas"),
    ("ABRILLANTADOR", "Limpieza del hogar", "Detergente y suavizante", "Abrillantador"),
    ("REC.AUT.ROPA", "Limpieza del hogar", "Detergente y suavizante", "Recarga detergente"),
    ("REC AUT ROPA", "Limpieza del hogar", "Detergente y suavizante", "Recarga detergente"),
    ("FAIRY", "Limpieza del hogar", "Detergente y suavizante", "Lavavajillas Fairy"),
    ("ACT.BLANQUEANTE", "Limpieza del hogar", "Suelos y superficies", "Blanqueante"),
    ("PERCARBONATO", "Limpieza del hogar", "Suelos y superficies", "Blanqueante"),
    ("DISUELVEMANCHAS", "Limpieza del hogar", "Detergente y suavizante", "Quitamanchas"),
    ("LIMPIA LAVADORAS", "Limpieza del hogar", "Suelos y superficies", "Limpiador lavadoras"),
    ("LIMPIADOR DESINFECTA", "Limpieza del hogar", "Lejía y desinfectantes", "Limpiador desinfectante"),
    ("LIMPIADOR JABONOSO", "Limpieza del hogar", "Suelos y superficies", "Limpiador jabonoso"),
    ("LIMPIADOR PLACAS", "Limpieza del hogar", "Suelos y superficies", "Limpiador placas"),
    ("LIMPIAHOGAR", "Limpieza del hogar", "Suelos y superficies", "Limpiador multiusos"),
    ("LIMPIAMAQUINAS", "Limpieza del hogar", "Suelos y superficies", "Limpiador"),
    ("LIMPIAMUEBLE", "Limpieza del hogar", "Suelos y superficies", "Limpiador muebles"),
    ("LIMPIATAPICERIAS", "Limpieza del hogar", "Suelos y superficies", "Limpiador tapicerías"),
    ("LIMPIADOR", "Limpieza del hogar", "Suelos y superficies", "Limpiador"),
    ("LIMPIA", "Limpieza del hogar", "Suelos y superficies", "Limpieza"),
    ("LIMP. BAÑOS", "Limpieza del hogar", "Limpieza cocina y baño", "Limpiador baño"),
    ("LIMP. ", "Limpieza del hogar", "Suelos y superficies", "Limpieza"),
    ("LIMP ", "Limpieza del hogar", "Suelos y superficies", "Limpieza"),
    ("QUITAGRASA", "Limpieza del hogar", "Suelos y superficies", "Quitagrasas"),
    ("AMONIACO", "Limpieza del hogar", "Lejía y desinfectantes", "Amoníaco"),
    ("DESENGR.", "Limpieza del hogar", "Suelos y superficies", "Desengrasante"),
    ("DESINFECTANT TEJIDOS", "Limpieza del hogar", "Lejía y desinfectantes", "Desinfectante"),
    ("DESINFECTANTE", "Limpieza del hogar", "Lejía y desinfectantes", "Desinfectante"),
    ("ELIMINADOR OLORES", "Hogar", "Decoración", "Eliminador de olores"),
    ("ABSORBEOLOR", "Hogar", "Decoración", "Absorbedor de olores"),
    ("MAX FRESH", "Hogar", "Decoración", "Ambientador"),
    ("SPRAY ROPA LIMPIA", "Limpieza del hogar", "Suelos y superficies", "Frescor para ropa"),
    ("REC.AUT.ROPA", "Limpieza del hogar", "Detergente y suavizante", "Recarga de detergente"),
    ("PAPEL HIGIÉNICO", "Papel y desechables", "Papel higiénico", "Papel higiénico"),
    ("PAPEL HIGIENICO", "Papel y desechables", "Papel higiénico", "Papel higiénico"),
    ("HIGIENICO DOBLE", "Papel y desechables", "Papel higiénico", "Papel higiénico"),
    ("HIGIENICO", "Papel y desechables", "Papel higiénico", "Papel higiénico"),
    ("ROLLO HOGAR", "Papel y desechables", "Papel de cocina", "Rollo de cocina"),
    ("PAPEL ALUMINIO", "Papel y desechables", "Aluminio, film y bolsas", "Papel de aluminio"),
    ("PAPEL VEGETAL", "Papel y desechables", "Aluminio, film y bolsas", "Papel vegetal"),
    ("PAPEL HUMEDO", "Papel y desechables", "Aluminio, film y bolsas", "Papel húmedo"),
    ("FILM TRANSPARENTE", "Papel y desechables", "Aluminio, film y bolsas", "Film transparente"),
    ("BOLSA BASURA", "Limpieza del hogar", "Bolsas de basura", "Bolsas de basura"),
    ("B.ENVASES", "Limpieza del hogar", "Bolsas de basura", "Bolsas de basura"),
    ("B.CIERRA", "Limpieza del hogar", "Bolsas de basura", "Bolsas de basura"),
    ("B.MINI PAPELERA", "Papel y desechables", "Aluminio, film y bolsas", "Bolsas basura mini"),
    ("SACOS", "Limpieza del hogar", "Bolsas de basura", "Sacos de basura"),
    ("BOLSAS ZIP", "Limpieza del hogar", "Bolsas de basura", "Bolsas zip"),
    ("BOLSAS ", "Limpieza del hogar", "Bolsas de basura", "Bolsas"),
    ("BOLSA RAFIA", "Limpieza del hogar", "Bolsas de basura", "Bolsa de rafia"),
    ("BOLSA PLASTICO", "Limpieza del hogar", "Bolsas de basura", "Bolsa de plástico"),
    ("BOLSA ISOTÉRMICA", "Limpieza del hogar", "Bolsas de basura", "Bolsa isotérmica"),
    ("BOLSA", "Limpieza del hogar", "Bolsas de basura", "Bolsa"),
    ("PAPEL", "Papel y desechables", "Aluminio, film y bolsas", "Papel"),
    ("SERVILLETA", "Papel y desechables", "Pañuelos y servilletas", "Servilletas"),
    ("CUBO PEDAL", "Limpieza del hogar", "Útiles de limpieza", "Cubo pedal"),
    ("FREGONA", "Limpieza del hogar", "Útiles de limpieza", "Fregona"),
    ("BAYETA", "Limpieza del hogar", "Útiles de limpieza", "Bayeta"),
    ("ESTROPAJO", "Limpieza del hogar", "Útiles de limpieza", "Estropajo"),
    ("ESPONJA", "Limpieza del hogar", "Útiles de limpieza", "Esponja"),
    ("ESCOBA", "Limpieza del hogar", "Útiles de limpieza", "Escoba"),
    ("RECOGEDOR", "Limpieza del hogar", "Útiles de limpieza", "Recogedor"),
    ("GUANTES", "Limpieza del hogar", "Útiles de limpieza", "Guantes"),
    ("RASQUETA", "Limpieza del hogar", "Útiles de limpieza", "Rasqueta"),
    ("LOTE 3 BAYETAS", "Limpieza del hogar", "Útiles de limpieza", "Bayetas"),
    ("FIBRA BLANCA", "Limpieza del hogar", "Útiles de limpieza", "Estropajo"),
    ("RECIPIENTES", "Limpieza del hogar", "Útiles de limpieza", "Recipientes"),
    ("CÁPSULA ROPA", "Limpieza del hogar", "Detergente y suavizante", "Cápsulas detergente"),
    ("VELA TE CHAI", "Hogar", "Decoración", "Vela"),
    ("VELA MATCHA", "Hogar", "Decoración", "Vela"),
    ("VELA", "Hogar", "Decoración", "Vela"),
    ("AMBIENTADOR", "Hogar", "Decoración", "Ambientador"),
    ("AMB ", "Hogar", "Decoración", "Ambientador"),
    ("AMB.", "Hogar", "Decoración", "Ambientador"),
    ("AMB COCHE", "Hogar", "Decoración", "Ambientador coche"),
    ("VARITAS DIF", "Hogar", "Decoración", "Difusor"),
    ("VARITAS MAGNOLIA", "Hogar", "Decoración", "Difusor"),
    ("VARITAS", "Hogar", "Decoración", "Difusor"),
    ("DIFUSOR", "Hogar", "Decoración", "Difusor"),
    ("ANTIPOLI", "Hogar", "Decoración", "Antipolillas"),
    ("ANTIPOLILLAS", "Hogar", "Decoración", "Antipolillas"),
    ("ANTIPOLILLA", "Hogar", "Decoración", "Antipolillas"),
    ("PULSERA CITRONELA", "Hogar", "Decoración", "Pulsera citronela"),
    ("REPELENTE", "Hogar", "Decoración", "Repelente"),
    ("ELIMINADOR OLORES", "Hogar", "Decoración", "Eliminador de olores"),
    ("CARBON VEGETAL", "Hogar", "Menaje y cocina", "Carbón"),
    ("HIELO", "Hogar", "Menaje y cocina", "Hielo"),
    ("BENTO", "Hogar", "Menaje y cocina", "Fiambrera bento"),
    ("PILA", "Hogar", "Ferretería y bricolaje", "Pilas"),
    ("PILA ALCALINA", "Hogar", "Ferretería y bricolaje", "Pilas alcalinas"),
    ("CHAMPU", "Higiene personal", "Champú y cuidado capilar", "Champú"),
    ("CHAMPÚ", "Higiene personal", "Champú y cuidado capilar", "Champú"),
    ("GEL-CHAMPÚ", "Higiene personal", "Champú y cuidado capilar", "Gel y champú"),
    ("ACONDICIONADOR", "Higiene personal", "Champú y cuidado capilar", "Acondicionador"),
    ("LACA", "Higiene personal", "Champú y cuidado capilar", "Laca"),
    ("LACTOVIT", "Higiene personal", "Champú y cuidado capilar", "Lactovit"),
    ("MASCARA PLEX", "Higiene personal", "Champú y cuidado capilar", "Máscara capilar"),
    ("ESPUMA RIZO", "Higiene personal", "Champú y cuidado capilar", "Espuma para rizos"),
    ("EXFOLIANTE ARCILLA", "Higiene personal", "Cuidado corporal y facial", "Exfoliante de arcilla"),
    ("REFILL DERMO", "Higiene personal", "Cuidado corporal y facial", "Recambio corporal"),
    ("AMPOLLAS RESCATE", "Higiene personal", "Champú y cuidado capilar", "Ampollas capilares"),
    ("ACTIVADOR R COLOR", "Higiene personal", "Champú y cuidado capilar", "Activador de color"),
    ("TINTE", "Higiene personal", "Champú y cuidado capilar", "Tinte"),
    ("COLORACION", "Higiene personal", "Champú y cuidado capilar", "Coloración"),
    ("GEL ", "Higiene personal", "Gel y jabón", "Gel de ducha"),
    ("GEL CORPORAL", "Higiene personal", "Gel y jabón", "Gel corporal"),
    ("GELLY", "Higiene personal", "Cuidado corporal y facial", "Gel de ducha"),
    ("JABON", "Higiene personal", "Gel y jabón", "Jabón"),
    ("JABÓN", "Higiene personal", "Gel y jabón", "Jabón"),
    ("CREMA DE MANOS", "Higiene personal", "Cuidado corporal y facial", "Crema de manos"),
    ("CREMA MANOS", "Higiene personal", "Cuidado corporal y facial", "Crema de manos"),
    ("T. CARA Y MANOS", "Higiene personal", "Cuidado corporal y facial", "Crema cara y manos"),
    ("CREMA ESFERAS", "Higiene personal", "Cuidado corporal y facial", "Crema facial"),
    ("CREMA HIDRA", "Higiene personal", "Cuidado corporal y facial", "Crema hidratante"),
    ("CREMA REVITALIZANTE", "Higiene personal", "Cuidado corporal y facial", "Crema revitalizante"),
    ("CREMA ANTIARRUGAS", "Higiene personal", "Cuidado corporal y facial", "Crema antiarrugas"),
    ("CREMA", "Higiene personal", "Cuidado corporal y facial", "Crema"),
    ("HIDRATANTE SOFT", "Higiene personal", "Cuidado corporal y facial", "Hidratante"),
    ("LOCIÓN CALM", "Higiene personal", "Cuidado corporal y facial", "Loción calmante"),
    ("LOCIÓN NUTRE", "Higiene personal", "Cuidado corporal y facial", "Loción nutritiva"),
    ("LOCION", "Higiene personal", "Cuidado corporal y facial", "Loción"),
    ("EXFOLIANTE", "Higiene personal", "Cuidado corporal y facial", "Exfoliante"),
    ("DESMAQ", "Higiene personal", "Cuidado corporal y facial", "Desmaquillante"),
    ("ESPUMA", "Higiene personal", "Cuidado corporal y facial", "Espuma"),
    ("GEL UREA", "Higiene personal", "Gel y jabón", "Gel de urea"),
    ("GEL ALOE VERA", "Higiene personal", "Gel y jabón", "Gel de aloe vera"),
    ("GEL C/CAFEINA", "Higiene personal", "Gel y jabón", "Gel corporal"),
    ("GEL HIALURONICO", "Higiene personal", "Gel y jabón", "Gel hidratante"),
    ("GEL OLIVA", "Higiene personal", "Gel y jabón", "Gel de oliva"),
    ("GEL REFRESCANTE PIES", "Higiene personal", "Gel y jabón", "Gel refrescante"),
    ("GEL T RECUERDOS", "Higiene personal", "Gel y jabón", "Gel"),
    ("GEL EFECTO MOJADO", "Higiene personal", "Champú y cuidado capilar", "Gel para el pelo"),
    ("GEL CUCHILLA", "Higiene personal", "Gel y jabón", "Gel de afeitado"),
    ("BODY DEPIL", "Higiene personal", "Afeitado y depilación", "Depiladora"),
    ("CREMA DEPILATORIA", "Higiene personal", "Afeitado y depilación", "Crema depilatoria"),
    ("DUCHA", "Higiene personal", "Gel y jabón", "Gel de ducha"),
    ("JABON DE MANOS", "Higiene personal", "Gel y jabón", "Jabón de manos"),
    ("COLGATE", "Higiene personal", "Higiene bucal", "Pasta dental"),
    ("COLG.", "Higiene personal", "Higiene bucal", "Pasta dental"),
    ("CEPILLO", "Higiene personal", "Higiene bucal", "Cepillo dental"),
    ("SPRAY BUCAL", "Higiene personal", "Higiene bucal", "Spray bucal"),
    ("KIT H BUCAL", "Higiene personal", "Higiene bucal", "Kit higiene bucal"),
    ("HILO DENTAL", "Higiene personal", "Higiene bucal", "Hilo dental"),
    ("ARCOS DENTALES", "Higiene personal", "Higiene bucal", "Arcos dentales"),
    ("ENJUAGUE BUCAL", "Higiene personal", "Higiene bucal", "Enjuague bucal"),
    ("HIGIENE BUCAL", "Higiene personal", "Higiene bucal", "Producto bucal"),
    ("PASTA DENTAL", "Higiene personal", "Higiene bucal", "Pasta dental"),
    ("DENTIFRICO", "Higiene personal", "Higiene bucal", "Pasta dental"),
    ("TAMPON", "Higiene personal", "Higiene íntima", "Tampón"),
    ("TAMPÓN", "Higiene personal", "Higiene íntima", "Tampón"),
    ("COMPRESA", "Higiene personal", "Higiene íntima", "Compresas"),
    ("PROTEGESLIP", "Higiene personal", "Higiene íntima", "Protegeslip"),
    ("PROTEG.COTTON", "Higiene personal", "Higiene íntima", "Protegeslip"),
    ("TOALLITA INTIMA", "Higiene personal", "Higiene íntima", "Toallita íntima"),
    ("TOALL.INTIMA", "Higiene personal", "Higiene íntima", "Toallita íntima"),
    ("GEL HIG.INTIMO", "Higiene personal", "Higiene íntima", "Gel íntimo"),
    ("GEL INTIMO", "Higiene personal", "Higiene íntima", "Gel íntimo"),
    ("INTIMA", "Higiene personal", "Higiene íntima", "Cuidado íntimo"),
    ("T.INTIMAS", "Higiene personal", "Higiene íntima", "Toallitas íntimas"),
    ("PAÑUELO", "Papel y desechables", "Pañuelos y servilletas", "Pañuelos"),
    ("PAÑUELO", "Papel y desechables", "Pañuelos y servilletas", "Pañuelos"),
    ("TOALLITAS", "Papel y desechables", "Pañuelos y servilletas", "Toallitas"),
    ("TOALLITA BEBE", "Bebé", "Pañales y toallitas", "Toallitas para bebé"),
    ("TOALL.BEBE", "Bebé", "Pañales y toallitas", "Toallitas para bebé"),
    ("TOALLITA REFRESCANTE", "Papel y desechables", "Pañuelos y servilletas", "Toallitas refrescantes"),
    ("TOALLAS", "Higiene personal", "Cuidado corporal y facial", "Toallas"),
    ("TOALLA", "Higiene personal", "Cuidado corporal y facial", "Toalla"),
    ("MAQUILLAJE", "Higiene personal", "Cuidado corporal y facial", "Maquillaje"),
    ("PINTALABIOS", "Higiene personal", "Cuidado corporal y facial", "Pintalabios"),
    ("LABIAL", "Higiene personal", "Cuidado corporal y facial", "Labial"),
    ("BARRA COLOR BALM", "Higiene personal", "Cuidado corporal y facial", "Barra de color"),
    ("COLOR BALM", "Higiene personal", "Cuidado corporal y facial", "Barra de color"),
    ("LIQUID BLUSH", "Higiene personal", "Cuidado corporal y facial", "Rubor líquido"),
    ("PERF. CEJAS", "Higiene personal", "Cuidado corporal y facial", "Perfilador de cejas"),
    ("PERF.LABIOS", "Higiene personal", "Cuidado corporal y facial", "Perfilador de labios"),
    ("MASCARA LONG", "Higiene personal", "Cuidado corporal y facial", "Máscara de pestañas"),
    ("MÁSCARA SERUM", "Higiene personal", "Cuidado corporal y facial", "Máscara"),
    ("MASCARA", "Higiene personal", "Cuidado corporal y facial", "Máscara"),
    ("SOMBRA", "Higiene personal", "Cuidado corporal y facial", "Sombra de ojos"),
    ("SOMBRA STICK", "Higiene personal", "Cuidado corporal y facial", "Sombra de ojos"),
    ("BB MEDIUM", "Higiene personal", "Cuidado corporal y facial", "BB cream"),
    ("BB MEDIUM", "Higiene personal", "Cuidado corporal y facial", "BB cream"),
    ("CONTORNO OJOS", "Higiene personal", "Cuidado corporal y facial", "Contorno de ojos"),
    ("SERUM BE RADIANT", "Higiene personal", "Cuidado corporal y facial", "Sérum"),
    ("SERUM PLEX", "Higiene personal", "Cuidado corporal y facial", "Sérum"),
    ("SERUM", "Higiene personal", "Cuidado corporal y facial", "Sérum"),
    ("ROJO GEL", "Higiene personal", "Cuidado corporal y facial", "Esmalte de uñas"),
    ("TOP COAT", "Higiene personal", "Cuidado corporal y facial", "Esmalte de uñas"),
    ("ESMALTE", "Higiene personal", "Cuidado corporal y facial", "Esmalte de uñas"),
    ("QUITAESMALTE", "Higiene personal", "Cuidado corporal y facial", "Quitaesmalte"),
    ("QUIT.ACETONA", "Higiene personal", "Cuidado corporal y facial", "Quitaesmalte"),
    ("DISCOS DESMA", "Higiene personal", "Cuidado corporal y facial", "Discos desmaquillantes"),
    ("VOLUMIZER", "Higiene personal", "Cuidado corporal y facial", "Volumizador"),
    ("LACA", "Higiene personal", "Champú y cuidado capilar", "Laca"),
    ("DEO ", "Higiene personal", "Desodorante", "Desodorante"),
    ("DEO ", "Higiene personal", "Desodorante", "Desodorante"),
    ("DESODORANTE", "Higiene personal", "Desodorante", "Desodorante"),
    ("ROLLON", "Higiene personal", "Desodorante", "Desodorante"),
    ("ROLL-ON", "Higiene personal", "Desodorante", "Desodorante"),
    ("ROLL ON", "Higiene personal", "Desodorante", "Desodorante"),
    ("ANTITRANSPIRANTE", "Higiene personal", "Desodorante", "Desodorante"),
    ("SPF", "Farmacia y parafarmacia", "Protección solar", "Protector solar"),
    ("FPS", "Farmacia y parafarmacia", "Protección solar", "Protector solar"),
    ("PROTECTOR SOLAR", "Farmacia y parafarmacia", "Protección solar", "Protector solar"),
    ("SOLAR", "Farmacia y parafarmacia", "Protección solar", "Protector solar"),
    ("BRONCEADOR", "Farmacia y parafarmacia", "Protección solar", "Bronceador"),
    ("SPRAY FPS", "Farmacia y parafarmacia", "Protección solar", "Protector solar"),
    ("SPF50", "Farmacia y parafarmacia", "Protección solar", "Protector solar"),
    ("MASCARA", "Higiene personal", "Champú y cuidado capilar", "Mascarilla capilar"),
    ("MASK", "Farmacia y parafarmacia", "Botiquín", "Mascarilla"),
    ("T.HIDROALC", "Farmacia y parafarmacia", "Botiquín", "Gel hidroalcohólico"),
    ("HIDROALC", "Farmacia y parafarmacia", "Botiquín", "Gel hidroalcohólico"),
    ("ALIVIO PICOR", "Farmacia y parafarmacia", "Botiquín", "Alivio picor"),
    ("APOSITO", "Farmacia y parafarmacia", "Botiquín", "Apósito"),
    ("APÓSITO", "Farmacia y parafarmacia", "Botiquín", "Apósito"),
    ("APÓSITOS", "Farmacia y parafarmacia", "Botiquín", "Apósitos"),
    ("GASAS", "Farmacia y parafarmacia", "Botiquín", "Gasas"),
    ("MASCARILLA QUIRÚR.", "Farmacia y parafarmacia", "Botiquín", "Mascarilla quirúrgica"),
    ("PROTECCIÓN OJOS", "Farmacia y parafarmacia", "Botiquín", "Protección de ojos"),
    ("T. HIDROALC.", "Farmacia y parafarmacia", "Botiquín", "Toallitas hidroalcohólicas"),
    ("CURA", "Farmacia y parafarmacia", "Botiquín", "Cura"),
    ("STICK ÁRNICA", "Farmacia y parafarmacia", "Botiquín", "Stick de árnica"),
    ("0% CON FRUTAS", "Alimentación", "Lácteos", "Yogur 0% con frutas"),
    ("0%0%", "Alimentación", "Lácteos", "Yogur 0%"),
    ("BIF 0%", "Alimentación", "Lácteos", "Yogur bifidus 0%"),
    ("1/2 VIEJO INTENSO", "Alimentación", "Lácteos", "Queso viejo"),
    ("Q.MADURADO EN MADERA", "Alimentación", "Lácteos", "Queso curado en madera"),
    ("PORCIÓN LIGHT", "Alimentación", "Lácteos", "Queso porción light"),
    ("100% INTEGRAL FINO", "Alimentación", "Pan y bollería", "Pan integral"),
    ("T. 100%INTEGRALES", "Alimentación", "Pan y bollería", "Pan integral"),
    ("T. CREAM AVELLANA", "Alimentación", "Dulces y chocolate", "Crema de cacao y avellana"),
    ("T.CHERRY", "Alimentación", "Verdura y hortaliza", "Tomate cherry"),
    ("12H LASTING LIPS", "Higiene personal", "Cuidado corporal y facial", "Labial de larga duración"),
    ("40 B. BASURA", "Limpieza del hogar", "Bolsas de basura", "Bolsas de basura"),
    ("30 B.ENVASES", "Limpieza del hogar", "Bolsas de basura", "Bolsas de basura"),
    ("ARREGLO PUCHERO", "Alimentación", "Verdura y hortaliza", "Preparado de pochero"),
    ("BARQUILLO", "Alimentación", "Dulces y chocolate", "Barquillos"),
    ("BARQUI.", "Alimentación", "Dulces y chocolate", "Barquillo"),
    ("C. AMARILLA BANDEJA", "Alimentación", "Fruta", "Melocotón amarillo"),
    ("C. CALABACÍN", "Alimentación", "Conservas y caldos", "Crema de calabacín"),
    ("COLGADOR WC", "Limpieza del hogar", "Útiles de limpieza", "Colgador para el baño"),
    ("COST FINAS HIERBAS", "Alimentación", "Carne y charcutería", "Costillas finas hierbas"),
    ("CRUNCHY CHICKEN", "Alimentación", "Carne y charcutería", "Pollo crujiente"),
    ("CRUNCHY PICANTE", "Alimentación", "Snacks y frutos secos", "Snack crujiente picante"),
    ("D. MEMBRILLO", "Alimentación", "Dulces y chocolate", "Dulce de membrillo"),
    ("D.MEMBRILLO", "Alimentación", "Dulces y chocolate", "Dulce de membrillo"),
    ("MASA QUEBRADA", "Alimentación", "Harinas y repostería", "Masa quebrada"),
    ("MASA EMPANADA", "Alimentación", "Harinas y repostería", "Masa de empanada"),
    ("MASA DE HOJALDRE", "Alimentación", "Harinas y repostería", "Masa de hojaldre"),
    ("MINI VOL", "Alimentación", "Pan y bollería", "Vol-au-vent"),
    ("VOL-AV-VENT", "Alimentación", "Pan y bollería", "Vol-au-vent"),
    ("MIX TROPICAL", "Alimentación", "Fruta", "Mix tropical"),
    ("EXPLOSION ACTION ENJ", "Higiene personal", "Higiene bucal", "Enjuague bucal"),
    ("INSTANT COND.PROTECT", "Higiene personal", "Champú y cuidado capilar", "Acondicionador"),
    ("ACOND.PROTECT", "Higiene personal", "Champú y cuidado capilar", "Acondicionador"),
    ("OIL ESPUMSOSO", "Higiene personal", "Cuidado corporal y facial", "Aceite de baño"),
    ("J. PASTILLA", "Higiene personal", "Cuidado corporal y facial", "Jabón en pastilla"),
    ("SÉRUM PLEX", "Higiene personal", "Champú y cuidado capilar", "Sérum capilar"),
    ("KIDS +2", "Higiene personal", "Higiene bucal", "Pasta dental infantil"),
    ("KIDS +6", "Higiene personal", "Higiene bucal", "Pasta dental infantil"),
    ("ISO LIMÓN", "Bebidas", "Refrescos y zumos", "Isotónico"),
    ("ISOTONICO", "Bebidas", "Refrescos y zumos", "Isotónico"),
    ("ISOTÓNICO", "Bebidas", "Refrescos y zumos", "Isotónico"),
    ("VALENCIANA", "Bebidas", "Cerveza", "Cerveza Valenciana"),
    ("PALILLOS REDONDOS", "Alimentación", "Snacks y frutos secos", "Palitos de pan"),
    ("MINI BOCADOS", "Alimentación", "Snacks y frutos secos", "Snacks"),
    ("PULGUITA", "Alimentación", "Snacks y frutos secos", "Patatas fritas"),
    ("PULGUITAS", "Alimentación", "Snacks y frutos secos", "Patatas fritas"),
    ("DIVERTIDAS", "Alimentación", "Snacks y frutos secos", "Galletas"),
    ("ESTRELLAS", "Alimentación", "Snacks y frutos secos", "Snacks"),
    ("BINKIES", "Alimentación", "Dulces y chocolate", "Gominolas"),
    ("DUO FRUTA", "Alimentación", "Fruta", "Dúo de fruta"),
    ("HUESITOS", "Alimentación", "Dulces y chocolate", "Huesitos de chocolate"),
    ("P. RALLADO CRUJIENTE", "Alimentación", "Pan y bollería", "Pan rallado"),
    ("G. PEDROSILLANO", "Alimentación", "Pasta, arroz y legumbres", "Garbanzos de Pedrosillano"),
    ("GARBANZ PEDROSILLANO", "Alimentación", "Pasta, arroz y legumbres", "Garbanzos"),
    ("GARBANZOS RIOJANA", "Alimentación", "Pasta, arroz y legumbres", "Garbanzos a la riojana"),
    ("ENS NUEVA TIERNA", "Alimentación", "Comida preparada", "Ensalada"),
    ("LS MEDIA", "Alimentación", "Comida preparada", "Plato preparado"),
    ("LS 6", "Alimentación", "Comida preparada", "Croquetas"),
    ("LS TORTILLA", "Alimentación", "Comida preparada", "Tortilla preparada"),
    ("CRUJIENTE", "Alimentación", "Comida preparada", "Preparado crujiente"),
    ("RED BARBACOA", "Alimentación", "Aceite, salsas y condimentos", "Salsa barbacoa"),
    ("REDUC.V.P.XIMENEZ", "Alimentación", "Aceite, salsas y condimentos", "Reducción de vino"),
    ("REMOLLA EN TIRAS", "Alimentación", "Verdura y hortaliza", "Remolacha"),
    ("SALTEADO VERD. ASADA", "Alimentación", "Verdura y hortaliza", "Verduras asadas"),
    ("TOALLITA BEBÉ", "Bebé", "Pañales y toallitas", "Toallitas para bebé"),
    ("SOLUCIÓN ÚNICA", "Limpieza del hogar", "Suelos y superficies", "Limpiador"),
    ("SOLUCION UNICA", "Limpieza del hogar", "Suelos y superficies", "Limpiador"),
    ("SPRAY ESSENCE", "Higiene personal", "Cuidado corporal y facial", "Spray facial"),
    ("WOK", "Alimentación", "Verdura y hortaliza", "Preparado wok"),
    ("LLUVIA", "Alimentación", "Dulces y chocolate", "Gominolas"),
    ("OIL ESPUMOSO", "Higiene personal", "Cuidado corporal y facial", "Aceite de baño"),
    ("PERLAS TIERNOS", "Alimentación", "Verdura y hortaliza", "Brotes tiernos"),
    ("PINTAROLAS", "Higiene personal", "Cuidado corporal y facial", "Pintalabios"),
    ("PROTEG. COTTON", "Higiene personal", "Higiene íntima", "Protegeslip"),
    ("REGA RED MIX", "Alimentación", "Pan y bollería", "Regañás"),
    ("REMOLACHA", "Alimentación", "Verdura y hortaliza", "Remolacha"),
    ("PARKING", "Otros", "Otros", "Parking"),
    ("BOLSA PLASTICO", "Limpieza del hogar", "Bolsas de basura", "Bolsa de plástico"),
    ("BOLSA RAFIA", "Limpieza del hogar", "Bolsas de basura", "Bolsa de rafia"),
    ("HIELO", "Hogar", "Menaje y cocina", "Hielo"),
    ("MESA PLEGABLE", "Hogar", "Decoración", "Mesa plegable"),
    ("MESA ", "Hogar", "Decoración", "Mesa"),
    ("SILLÓN", "Hogar", "Decoración", "Sillón"),
    ("SILLON", "Hogar", "Decoración", "Sillón"),
    ("SILLA", "Hogar", "Decoración", "Silla"),
    ("SOFÁ", "Hogar", "Decoración", "Sofá"),
    ("SOFA", "Hogar", "Decoración", "Sofá"),
    ("ARMARIO", "Hogar", "Decoración", "Armario"),
    ("ESTANTERÍA", "Hogar", "Decoración", "Estantería"),
    ("ESTANTERIA", "Hogar", "Decoración", "Estantería"),
    ("CAMA", "Hogar", "Decoración", "Cama"),
    ("COLCHÓN", "Hogar", "Decoración", "Colchón"),
    ("COLCHON", "Hogar", "Decoración", "Colchón"),
    ("ESPEJO", "Hogar", "Decoración", "Espejo"),
    ("LÁMPARA", "Hogar", "Iluminación", "Lámpara"),
    ("LAMPARA", "Hogar", "Iluminación", "Lámpara"),
    ("PERCHERO", "Hogar", "Decoración", "Perchero"),
    ("BANQUETA", "Hogar", "Decoración", "Banqueta"),
    ("TABURETE", "Hogar", "Decoración", "Taburete"),
    ("FUNDA PROTECTORA", "Hogar", "Textil hogar", "Funda"),
    ("FUNDA", "Hogar", "Textil hogar", "Funda"),
    ("TOALLA", "Higiene personal", "Cuidado corporal y facial", "Toalla"),
    ("SÁBANA", "Hogar", "Textil hogar", "Sábana"),
    ("SABANA", "Hogar", "Textil hogar", "Sábana"),
    ("ALMOHADA", "Hogar", "Textil hogar", "Almohada"),
    ("EDREDÓN", "Hogar", "Textil hogar", "Edredón"),
    ("EDREDON", "Hogar", "Textil hogar", "Edredón"),
    ("MANTA", "Hogar", "Textil hogar", "Manta"),
    ("CORTINA", "Hogar", "Textil hogar", "Cortina"),
    ("CALCETÍN", "Ropa y calzado", "Ropa", "Calcetín"),
    ("CALCETIN", "Ropa y calzado", "Ropa", "Calcetín"),
    ("CAMISETA", "Ropa y calzado", "Ropa", "Camiseta"),
    ("CAMISA", "Ropa y calzado", "Ropa", "Camisa"),
    ("PANTALÓN", "Ropa y calzado", "Ropa", "Pantalón"),
    ("PANTALON", "Ropa y calzado", "Ropa", "Pantalón"),
    ("CHAQUETA", "Ropa y calzado", "Ropa", "Chaqueta"),
    ("ABRIGO", "Ropa y calzado", "Ropa", "Abrigo"),
    ("JERSEY", "Ropa y calzado", "Ropa", "Jersey"),
    ("PIENSO", "Mascotas", "Comida para mascotas", "Piensos"),
    ("COMIDA PERRO", "Mascotas", "Comida para mascotas", "Comida de perro"),
    ("COMIDA GATO", "Mascotas", "Comida para mascotas", "Comida de gato"),
    ("ARENA GATO", "Mascotas", "Higiene para mascotas", "Arena de gato"),
    ("PAÑAL", "Bebé", "Pañales y toallitas", "Pañales"),
    ("PAPILLA", "Bebé", "Alimentación infantil", "Papilla"),
    ("TARrito", "Bebé", "Alimentación infantil", "Tarrito"),
    ("BIBERON", "Bebé", "Alimentación infantil", "Biberón"),
    ("CONGELADO", "Alimentación", "Congelados", "Congelado"),
    ("PARACETAMOL", "Farmacia y parafarmacia", "Medicamentos sin receta", "Paracetamol"),
    ("IBUPROFENO", "Farmacia y parafarmacia", "Medicamentos sin receta", "Ibuprofeno"),
    ("VITAMINA", "Farmacia y parafarmacia", "Suplementos", "Vitaminas"),
    ("MAGNESIO", "Farmacia y parafarmacia", "Suplementos", "Magnesio"),
]

# La clave de los sobreescritos por descripción tiene que ser exacta.
# Columnas normalizadas para la tabla de overrides.
OVERRIDE_TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS taxonomy_overrides (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo TEXT NOT NULL,
    descripcion TEXT,
    item_id INTEGER,
    categoria_general TEXT NOT NULL,
    subcategoria TEXT NOT NULL,
    producto_norm TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(descripcion)
)
"""


def _normalize_upper(text: str) -> str:
    """Devuelve el texto en mayúsculas sin espacios extra para el matching."""
    return " ".join(text.upper().split())


def _canonical_product(nombre, overrides_by_descripcion=None) -> str:
    """Devuelve el nombre canónico de un producto a partir de un nombre cualquiera.

    Sirve para unificar variantes que solo difieren en mayúsculas/minúsculas
    (p.ej. 'CERVEZA' vs 'Cerveza'). NO usa el diccionario de overrides para
    decidir: solo consulta las reglas de keywords, que son las que definen el
    nombre canónico del catálogo.
    """
    if not nombre or not nombre.strip():
        return ""
    # Atajo: el nombre canónico coincide con su versión en mayúsculas
    for keyword, _cat, _sub, producto in KEYWORD_RULES:
        if keyword == _normalize_upper(nombre):
            return producto
    # Si no, probar si el nombre "contiene" una keyword (mismo criterio que las reglas)
    desc_upper = _normalize_upper(nombre)
    for keyword, _cat, _sub, producto in KEYWORD_RULES:
        if keyword in desc_upper:
            return producto
    return nombre


def normalize_product(
    descripcion: str,
    overrides_by_descripcion: Optional[Dict[str, Tuple[str, str, str]]] = None,
) -> Tuple[str, str, str]:
    """Devuelve (categoria, subcategoria, producto_norm) para una descripción.

    Si se pasa un dict de overrides por descripcion (mapeado de descripcion a
    (categoria, subcategoria, producto_norm)), se consulta primero.
    """
    if not descripcion or not descripcion.strip():
        return "Otros", "Varios", ""
    key = descripcion
    if overrides_by_descripcion and key in overrides_by_descripcion:
        return overrides_by_descripcion[key]
    desc_upper = _normalize_upper(descripcion)
    for keyword, categoria, subcategoria, producto in KEYWORD_RULES:
        if keyword in desc_upper:
            return categoria, subcategoria, producto
    return "Otros", "Varios", descripcion


# ---------------------------------------------------------------------------
# Overrides manuales
# ---------------------------------------------------------------------------

def _get_conn(db_path):
    """Devuelve una conexión sqlite con row_factory y la tabla de overrides creada."""
    path = Path(db_path) if db_path else DB_PATH
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(OVERRIDE_TABLE_SCHEMA)
    conn.commit()
    return conn


def get_overrides(db_path=None) -> List[dict]:
    """Devuelve todos los overrides activos."""
    conn = _get_conn(db_path)
    rows = conn.execute(
        "SELECT * FROM taxonomy_overrides ORDER BY id"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _apply_override(conn, categoria, subcategoria, producto_norm, item_id=None,
                    descripcion=None):
    """Aplica un override a un item concreto (item_id) o por descripcion."""
    if item_id is not None:
        conn.execute(
            """UPDATE line_items SET categoria_general=?, subcategoria=?, producto_norm=?
               WHERE id=?""",
            (categoria, subcategoria, producto_norm, item_id),
        )
    elif descripcion is not None:
        conn.execute(
            """UPDATE line_items SET categoria_general=?, subcategoria=?, producto_norm=?
               WHERE descripcion=?""",
            (categoria, subcategoria, producto_norm, descripcion),
        )


def add_override(db_path, tipo, categoria_general, subcategoria,
                 descripcion=None, item_id=None, producto_norm=None):
    """Inserta o reemplaza un override y re-aplica la taxonomía.

    tipo: 'producto' (por descripcion) o 'item' (por item_id).
    """
    if tipo == "producto":
        if not descripcion:
            raise ValueError("Override tipo 'producto' requiere descripcion")
    elif tipo == "item":
        if item_id is None:
            raise ValueError("Override tipo 'item' requiere item_id")
    else:
        raise ValueError("tipo debe ser 'producto' o 'item'")

    conn = _get_conn(db_path)
    # upsert
    if tipo == "producto":
        conn.execute(
            """INSERT INTO taxonomy_overrides
               (tipo, descripcion, categoria_general, subcategoria, producto_norm)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(descripcion) DO UPDATE SET
                 tipo=excluded.tipo,
                 categoria_general=excluded.categoria_general,
                 subcategoria=excluded.subcategoria,
                 producto_norm=excluded.producto_norm,
                 created_at=datetime('now')""",
            (tipo, descripcion, categoria_general, subcategoria, producto_norm),
        )
    else:
        conn.execute(
            """INSERT INTO taxonomy_overrides
               (tipo, descripcion, item_id, categoria_general, subcategoria, producto_norm)
               VALUES (?, NULL, ?, ?, ?, ?)""",
            (tipo, item_id, categoria_general, subcategoria, producto_norm),
        )
    conn.commit()

    # Re-aplicar
    if tipo == "producto":
        apply_taxonomy_to_db(db_path or DB_PATH)
    else:
        apply_taxonomy_to_item(db_path or DB_PATH, item_id)
    conn.close()


def remove_override(db_path, override_id):
    """Elimina un override y re-aplica la taxonomía."""
    conn = _get_conn(db_path)
    row = conn.execute(
        "SELECT * FROM taxonomy_overrides WHERE id=?", (override_id,)
    ).fetchone()
    if row is None:
        conn.close()
        return False
    item_id = row["item_id"]
    descripcion = row["descripcion"]
    conn.execute("DELETE FROM taxonomy_overrides WHERE id=?", (override_id,))
    conn.commit()
    conn.close()

    # Re-aplicar (elimina el override manual y rehace con reglas normales)
    if item_id is not None:
        apply_taxonomy_to_item(db_path or DB_PATH, item_id)
    else:
        apply_taxonomy_to_db(db_path or DB_PATH)
    return True


def reassign_product(db_path, descripcion, categoria_general, subcategoria,
                     producto_norm=None):
    """Atajo para añadir un override de tipo 'producto' (afecta a todos los items)."""
    return add_override(db_path, "producto", descripcion=descripcion,
                        categoria_general=categoria_general,
                        subcategoria=subcategoria, producto_norm=producto_norm)


def reassign_item(db_path, item_id, categoria_general, subcategoria,
                  producto_norm=None):
    """Atajo para añadir un override de tipo 'item' (solo ese line item)."""
    return add_override(db_path, "item", item_id=item_id,
                        categoria_general=categoria_general,
                        subcategoria=subcategoria, producto_norm=producto_norm)


# ---------------------------------------------------------------------------
# Normalización de tiendas
# ---------------------------------------------------------------------------

def normalize_store(direccion: str) -> str:
    """Unifica direcciones de tienda duplicadas.

    Ejemplos:
        "C/ DE LA HULLA 21" == "C/ DE LA HULLA, 21" -> "C/ De La Hulla, 21"
        "AVDA. DE LOS ROSALES 26" == "AVDA. DE LOS ROSALES, 26"
            -> "Avda. De Los Rosales, 26"
        "" -> "Sin especificar"
    """
    if not direccion or not direccion.strip():
        return "Sin especificar"
    # Colapsa espacios en blanco
    addr = " ".join(direccion.split())
    # title-case por palabra (mantiene números y abreviaturas)
    parts = addr.split()
    title = [p[:1].upper() + p[1:].lower() for p in parts]
    # Asegura una coma antes del número de portal final
    if len(title) > 1 and title[-1].isdigit():
        prev = title[-2]
        if not prev.endswith(","):
            title[-2] = prev + ","
    return " ".join(title)


# ---------------------------------------------------------------------------
# Aplicación a la BD
# ---------------------------------------------------------------------------

def _load_override_maps(conn):
    """Devuelve (overrides_por_descripcion, overrides_por_item)."""
    overrides_by_desc = {}
    overrides_by_item = {}
    rows = conn.execute(
        "SELECT tipo, descripcion, item_id, categoria_general, subcategoria, producto_norm "
        "FROM taxonomy_overrides"
    ).fetchall()
    for r in rows:
        if r["tipo"] == "producto" and r["descripcion"]:
            # Si el override no fija un producto_norm explícito, NO se propaga la
            # descripción cruda del ticket (eso creaba duplicados tipo 'CERVEZA' vs
            # 'Cerveza'). Se deriva el nombre canónico con las reglas del catálogo.
            nom = r["producto_norm"] or _canonical_product(r["descripcion"])
            overrides_by_desc[r["descripcion"]] = (
                r["categoria_general"], r["subcategoria"], nom)
        elif r["tipo"] == "item" and r["item_id"] is not None:
            overrides_by_item[r["item_id"]] = (
                r["categoria_general"], r["subcategoria"],
                r["producto_norm"])
    return overrides_by_desc, overrides_by_item


def apply_taxonomy_to_item(db_path, item_id):
    """Normaliza un solo item aplicando overrides y reglas."""
    conn = _get_conn(db_path)
    overrides_by_desc, overrides_by_item = _load_override_maps(conn)
    row = conn.execute(
        "SELECT id, descripcion FROM line_items WHERE id=?", (item_id,)
    ).fetchone()
    if row is None:
        conn.close()
        return
    # Prioridad: override de item > override de descripcion > reglas
    if item_id in overrides_by_item:
        cat, sub, prod = overrides_by_item[item_id]
    else:
        cat, sub, prod = normalize_product(
            row["descripcion"], overrides_by_desc)
    conn.execute(
        "UPDATE line_items SET categoria_general=?, subcategoria=?, producto_norm=? WHERE id=?",
        (cat, sub, prod, item_id))
    conn.commit()
    conn.close()


def _rule_products() -> set:
    """Nombres de producto que las reglas del catálogo definen como canónicos."""
    return {producto for _kw, _cat, _sub, producto in KEYWORD_RULES if producto}


def _prefiere_forma(nombres: list) -> str:
    """Elige entre variantes de case la forma más presentable.

    Preferencia: Forma Título ('Cerveza') > minúsculas > MAYÚSCULAS, y a igualdad
    la más usada. Evita elegir 'MELOCOTÓN AMARILLO' frente a 'Melocotón amarillo'.
    """
    def score(par):
        nombre, n = par
        if nombre.istitle():
            forma = 2
        elif nombre.isupper():
            forma = 0
        else:
            forma = 1
        return (forma, n)

    return max(nombres, key=score)[0]


def unify_product_case(conn, dry_run: bool = False) -> int:
    """Unifica nombres de producto que solo difieren en mayúsculas/minúsculas.

    'CERVEZA' y 'Cerveza' son el mismo producto: se quedan con el nombre canónico
    (el que definen las reglas del catálogo; si ninguna variante es canónica, la
    forma más presentable y usada). Devuelve cuántas filas se han reasignado.
    """
    rows = conn.execute(
        """SELECT producto_norm, COUNT(*) n FROM line_items
           WHERE producto_norm IS NOT NULL AND producto_norm <> ''
           GROUP BY producto_norm"""
    ).fetchall()

    grupos: Dict[str, list] = {}
    for r in rows:
        grupos.setdefault((r["producto_norm"] or "").lower(), []).append(
            (r["producto_norm"], r["n"]))

    canonicos = _rule_products()
    total = 0

    # --- Paso 1: variantes múltiples del mismo nombre ('CERVEZA' + 'Cerveza') ---
    for _clave, variantes in grupos.items():
        if len(variantes) < 2:
            continue
        # Solo es canónico una variante que las reglas del catálogo nombren así.
        # (Antes se comparaba contra el propio nombre, con lo que la primera
        # variante ganaba siempre, aunque fuera la fea en MAYÚSCULAS.)
        candidatos = [v for v in variantes if v[0] in canonicos]
        if candidatos:
            canonico = max(candidatos, key=lambda x: x[1])[0]
        else:
            canonico = _prefiere_forma(variantes)

        for nombre, _n in variantes:
            if nombre == canonico:
                continue
            if dry_run:
                afectadas = conn.execute(
                    "SELECT COUNT(*) FROM line_items WHERE producto_norm=?",
                    (nombre,)).fetchone()[0]
                print(f"    '{nombre}' -> '{canonico}'  ({afectadas} filas)")
                total += afectadas
            else:
                print(f"    '{nombre}' -> '{canonico}'")
                cur = conn.execute(
                    "UPDATE line_items SET producto_norm=? WHERE producto_norm=?",
                    (canonico, nombre))
                total += cur.rowcount

    # --- Paso 2: nombre único que solo difiere en case del canónico del catálogo ---
    # Cubre el caso de las líneas clasificadas por LLM, que quedan con la
    # descripción cruda ('PATATA') y a las que las reglas no tocan. Sin esto, el
    # siguiente ingesta volvería a desdoblar el producto.
    for variantes in grupos.values():
        if len(variantes) != 1:
            continue
        nombre = variantes[0][0]
        prop = _canonical_product(nombre)
        if prop == nombre or prop not in canonicos:
            continue
        if prop.lower() != nombre.lower():
            continue          # solo se corrige el case, no la identidad
        afectadas = conn.execute(
            "SELECT COUNT(*) FROM line_items WHERE producto_norm=?",
            (nombre,)).fetchone()[0]
        if dry_run:
            print(f"    '{nombre}' -> '{prop}'  ({afectadas} filas) [unica]")
            total += afectadas
        else:
            print(f"    '{nombre}' -> '{prop}'  [unica]")
            cur = conn.execute(
                "UPDATE line_items SET producto_norm=? WHERE producto_norm=?",
                (prop, nombre))
            total += cur.rowcount

    return total


def apply_taxonomy_to_db(db_path=None):
    """Aplica la taxonomía a todos los items y añade las columnas si no existen.

    El orden: primero se aplican las reglas de keywords automáticas y después
    se re-aplican los overrides (que tienen prioridad).
    Los items marcados como clasificados por LLM (llm_classified=1) no se
    sobreescriben con las reglas, solo con overrides manuales.
    """
    path = Path(db_path) if db_path else DB_PATH
    conn = _get_conn(path)

    # Asegurar columnas
    cols = [r[1] for r in conn.execute("PRAGMA table_info(line_items)").fetchall()]
    if "categoria_general" not in cols:
        conn.execute("ALTER TABLE line_items ADD COLUMN categoria_general TEXT")
    if "subcategoria" not in cols:
        conn.execute("ALTER TABLE line_items ADD COLUMN subcategoria TEXT")
    if "llm_classified" not in cols:
        conn.execute("ALTER TABLE line_items ADD COLUMN llm_classified INTEGER DEFAULT 0")

    overrides_by_desc, overrides_by_item = _load_override_maps(conn)

    # 1) Reglas automáticas (solo items no clasificados por LLM ni de tiendas no-Mercadona)
    # Las reglas están pensadas para productos de Mercadona; las tiendas no-Mercadona
    # (Action, Jysk, Simply Business, Mad Factory, El Jamón, Lidl, Primaprix)
    # se clasifican con LLM para evitar falsos positivos de keywords.
    rows = conn.execute(
        """SELECT li.id, li.descripcion, t.tienda FROM line_items li
           JOIN tickets t ON li.ticket_id = t.id
           WHERE (li.llm_classified = 0 OR li.llm_classified IS NULL)
             AND t.tienda LIKE '%MERCADONA%'
           ORDER BY li.id""").fetchall()
    for r in rows:
        cat, sub, prod = normalize_product(r["descripcion"], overrides_by_desc)
        conn.execute(
            "UPDATE line_items SET categoria_general=?, subcategoria=?, producto_norm=? WHERE id=?",
            (cat, sub, prod, r["id"]))

    # 1b) Items de tiendas no-Mercadona sin clasificar LLM -> marcar para LLM
    non_mercadona = conn.execute(
        """SELECT li.id, li.descripcion FROM line_items li
           JOIN tickets t ON li.ticket_id = t.id
           WHERE (li.llm_classified = 0 OR li.llm_classified IS NULL)
             AND t.tienda NOT LIKE '%MERCADONA%'
           ORDER BY li.id""").fetchall()
    if non_mercadona:
        print(f"  Items de tiendas no-Mercadona pendientes de LLM: {len(non_mercadona)}")
        # Clasificar con LLM
        valid_cats = set(CATEGORIES.keys())
        valid_subs = {c: list(subs) for c, subs in CATEGORIES.items()}
        batch_size = 10
        for i in range(0, len(non_mercadona), batch_size):
            batch = non_mercadona[i:i + batch_size]
            descriptions = [r["descripcion"] for r in batch]
            print(f"    Lote {i // batch_size + 1}/{(len(non_mercadona) + batch_size - 1) // batch_size} ({len(batch)} items)...")
            try:
                results = _llm_classify_batch(descriptions, CATEGORIES)
            except LLMConfigError as e:
                print(f"  ⚠ LLM no disponible, se dejan sin clasificar "
                      f"{len(non_mercadona) - i} items (reintentables): {e}")
                break
            for (item_id, desc), (cat, sub, prod) in zip(batch, results):
                cat, sub = _resolve_cat_sub(cat, sub, CATEGORIES)
                # No marcar como clasificado si el LLM tampoco supo (Otros):
                # así se reintenta en la próxima ingesta en vez de quedar fijado.
                already_done = 0 if cat == "Otros" else 1
                conn.execute(
                    "UPDATE line_items SET categoria_general=?, subcategoria=?, producto_norm=?, llm_classified=? WHERE id=?",
                    (cat, sub, prod, already_done, item_id))

    # 1c) Items de Mercadona que las reglas ponen en "Otros" -> LLM
    otros_mercadona = conn.execute(
        """SELECT li.id, li.descripcion FROM line_items li
           JOIN tickets t ON li.ticket_id = t.id
           WHERE (li.llm_classified = 0 OR li.llm_classified IS NULL)
             AND (li.categoria_general = 'Otros' OR li.categoria_general IS NULL)
             AND t.tienda LIKE '%MERCADONA%'
           ORDER BY li.id""").fetchall()
    if otros_mercadona:
        print(f"  Items de Mercadona en 'Otros' pendientes de LLM: {len(otros_mercadona)}")
        valid_cats = set(CATEGORIES.keys())
        valid_subs = {c: list(subs) for c, subs in CATEGORIES.items()}
        batch_size = 10
        for i in range(0, len(otros_mercadona), batch_size):
            batch = otros_mercadona[i:i + batch_size]
            descriptions = [r["descripcion"] for r in batch]
            print(f"    Lote {i // batch_size + 1}/{(len(otros_mercadona) + batch_size - 1) // batch_size} ({len(batch)} items)...")
            try:
                results = _llm_classify_batch(descriptions, CATEGORIES)
            except LLMConfigError as e:
                print(f"  ⚠ LLM no disponible, se dejan sin clasificar "
                      f"{len(otros_mercadona) - i} items (reintentables): {e}")
                break
            for (item_id, desc), (cat, sub, prod) in zip(batch, results):
                cat, sub = _resolve_cat_sub(cat, sub, CATEGORIES)
                # Mismo criterio que 1b: si el LLM devuelve "Otros", dejar
                # llm_classified=0 para reintentar en la próxima ingesta.
                already_done = 0 if cat == "Otros" else 1
                conn.execute(
                    "UPDATE line_items SET categoria_general=?, subcategoria=?, producto_norm=?, llm_classified=? WHERE id=?",
                    (cat, sub, prod, already_done, item_id))

    # 2) Overrides de tipo 'item' (prioridad máxima, sobreescribe todo incluido LLM)
    for item_id, (cat, sub, prod) in overrides_by_item.items():
        conn.execute(
            "UPDATE line_items SET categoria_general=?, subcategoria=?, producto_norm=? WHERE id=?",
            (cat, sub, prod, item_id))

    # 3) Unificar variantes que solo difieren en mayúsculas/minúsculas
    #    ('CERVEZA' vs 'Cerveza'). Último paso, para que ninguna de las fases
    #    anteriores pueda volver a introducir un desdoble.
    fusionadas = unify_product_case(conn)
    if fusionadas:
        print(f"  Productos unificados por case: {fusionadas}")

    conn.commit()
    conn.close()
    return _summary(path)


# --------------------------------------------------------------------------- #
# Clasificación con LLM local (Ollama) para items no categorizados por reglas
# --------------------------------------------------------------------------- #

import json as _json
import os as _os
import urllib.request as _urllib_request
import urllib.error as _urllib_error
import difflib as _difflib


def _resolve_cat_sub(cat: str, sub: str, categories: dict = None) -> tuple:
    """Valida y corrige (cat, sub) contra la taxonomía.

    - Categoría inválida → ("Otros", "Otros").
    - Subcategoría exacta → se acepta.
    - Subcategoría aproximada ("Refrescos" vs "Refrescos y zumos") →
      difflib fuzzy (cutoff 0.45).
    - Sin match → mantiene la categoría válida y pone sub="Otros"
      (NUNCA subs[0], que asignaría "Fruta" a unas croquetas).
    """
    categories = categories if categories is not None else CATEGORIES
    if cat not in categories:
        return ("Otros", "Otros")
    valid_subs = categories[cat]
    if sub in valid_subs:
        return (cat, sub)
    matches = _difflib.get_close_matches(sub, valid_subs, n=1, cutoff=0.45)
    if matches:
        return (cat, matches[0])
    return (cat, "Otros")


class LLMConfigError(RuntimeError):
    """El LLM rechaza la petición por configuración o plan (401/402/403).

    No se reintenta por bisección: dividir el lote no arregla una clave inválida
    ni un modelo que no está incluido en el plan de la cuenta.
    """


def _classify_mode() -> str:
    """'local' (Ollama en tu máquina, sin cuenta) o 'cloud' (Ollama Cloud, con API key).

    Por defecto local: el proyecto no exige ninguna suscripción para funcionar.
    """
    mode = (_os.environ.get("CLASSIFY_MODE") or "local").strip().lower()
    return "cloud" if mode == "cloud" else "local"


def _llm_chat(prompt: str) -> str:
    """Devuelve el texto del modelo (local o cloud) para el prompt dado."""
    if _classify_mode() == "cloud":
        return _llm_chat_cloud(prompt)
    return _llm_chat_local(prompt)


def _llm_chat_cloud(prompt: str) -> str:
    """Vía Ollama Cloud, API compatible con OpenAI (`/v1/chat/completions`)."""
    base = _os.environ.get("OLLAMA_BASE_URL", "https://ollama.com/v1").rstrip("/")
    key = (_os.environ.get("OLLAMA_API_KEY") or "").strip()
    model = _os.environ.get("TICKET_CLASSIFY_MODEL", "deepseek-v4.1-flash")
    if not key:
        raise LLMConfigError(
            "CLASSIFY_MODE=cloud pero OLLAMA_API_KEY está vacía: configura una API key "
            "de Ollama Cloud o vuelve a CLASSIFY_MODE=local (sin cuenta).")
    payload = _json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "temperature": 0.1,
        "max_tokens": 2000,
        # Los modelos de razonamiento se comen el presupuesto de salida pensando
        # y devuelven contenido vacío: se desactiva el razonamiento (igual que
        # hace src/ocr_llm.py en su vía cloud).
        "reasoning_effort": "none",
    }).encode()
    req = _urllib_request.Request(
        f"{base}/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {key}"},
    )
    try:
        with _urllib_request.urlopen(req, timeout=120) as resp:
            data = _json.loads(resp.read())
    except _urllib_error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:400]
        if e.code in (401, 402, 403):
            raise LLMConfigError(
                f"Ollama Cloud rechazó la petición (HTTP {e.code}): revisa OLLAMA_API_KEY "
                f"y que el modelo '{model}' esté incluido en el plan de la cuenta. {body}"
            ) from None
        raise ConnectionError(f"Error HTTP {e.code} de Ollama Cloud: {body}") from None
    except _urllib_error.URLError as e:
        raise ConnectionError(f"No se pudo conectar a Ollama Cloud ({base}): {e}") from None
    try:
        text = (data["choices"][0]["message"]["content"] or "").strip()
    except (KeyError, IndexError, TypeError):
        raise ValueError("respuesta de Ollama Cloud sin la estructura esperada") from None
    if not text:
        raise ValueError("respuesta vacía del modelo cloud")
    return text


def _llm_chat_local(prompt: str) -> str:
    """Vía Ollama local (`/api/chat`), sin cuenta ni coste."""
    ollama_url = _os.environ.get("LOCAL_OLLAMA_URL", "http://host.docker.internal:11434")
    model = _os.environ.get("LOCAL_CLASSIFY_MODEL", "qwen2.5:7b")
    payload = _json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": {"temperature": 0.1, "num_predict": 2000},
    }).encode()
    req = _urllib_request.Request(
        f"{ollama_url}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with _urllib_request.urlopen(req, timeout=120) as resp:
        data = _json.loads(resp.read())
    text = (data.get("message", {}).get("content") or "").strip()
    if not text:
        raise ValueError("respuesta vacía del modelo (¿thinking sin content?)")
    return text


def _llm_classify_once(descriptions: list, categories: dict) -> list:
    """Una llamada al LLM. Lanza excepción si la respuesta no es válida."""
    # Construir lista de categorías válidas para el prompt
    cats_str = _json.dumps(categories, ensure_ascii=False, indent=2)

    # Prompt: el LLM debe devolver JSON con la clasificación
    items_json = _json.dumps(descriptions, ensure_ascii=False)
    prompt = f"""Clasifica cada producto de tickets de compra en una categoría y subcategoría.

Categorías y subcategorías VÁLIDAS — usa EXCLUSIVAMENTE valores de esta lista,
copia las cadenas EXACTAS (categoría de la clave, subcategoría de su lista):
{cats_str}

Reglas:
- Si el producto es un alimento, la categoría es "Alimentación" y la
  subcategoría es UNA de la lista de "Alimentación" (Frutas, Verduras,
  Embutidos, Lácteos, ...). NO inventes subcategorías nuevas.
- Promociones, parking, entrega, bolsas → "Otros"/"Otros".
- Responde un objeto por producto, EN EL MISMO ORDEN.

Productos a clasificar (en orden):
{items_json}

Cada objeto: {{"categoria": "...", "subcategoria": "...", "producto": "nombre corto"}}
Responde SOLO el array JSON, sin texto adicional."""

    text = _llm_chat(prompt)

    # Extraer el JSON del texto (puede tener texto extra)
    start = text.find("[")
    end = text.rfind("]") + 1
    if start < 0 or end <= start:
        # Con un solo item el modelo puede devolver un objeto suelto {...}
        s2, e2 = text.find("{"), text.rfind("}") + 1
        if len(descriptions) == 1 and s2 >= 0 and e2 > s2:
            text = "[" + text[s2:e2] + "]"
            start, end = 0, len(text)
        else:
            raise ValueError(f"no se encontró array JSON: {text[:120]!r}")
    results = _json.loads(text[start:end])
    if not isinstance(results, list):
        raise ValueError("la respuesta no es una lista")
    # El modelo a veces devuelve strings JSON en vez de objetos
    if results and all(isinstance(r, str) for r in results):
        try:
            results = [_json.loads(r) for r in results]
        except (ValueError, TypeError):
            raise ValueError("elementos de la lista no son objetos JSON")
    if len(results) != len(descriptions):
        raise ValueError(
            f"el modelo devolvió {len(results)} items, se esperaban {len(descriptions)}")
    out = []
    for r, desc in zip(results, descriptions):
        if not isinstance(r, dict):
            raise ValueError(f"elemento no es objeto: {r!r}")
        out.append((r.get("categoria", "Otros"),
                    r.get("subcategoria", "Otros"),
                    r.get("producto", desc)))
    return out


def _llm_classify_batch(descriptions: list, categories: dict) -> list:
    """Clasifica una lista de descripciones, degradando por bisección.

    qwen2.5:7b es inestable con lotes: trunca JSON, devuelve arrays de
    strings o cuenta distinta de items. Estrategia: probar el lote entero;
    si falla, dividir en dos mitades y reintentar (recursivo) hasta item
    individual. Un item suelto casi siempre sale bien.
    """
    try:
        return _llm_classify_once(descriptions, categories)
    except LLMConfigError:
        # Clave/plan/modelo: dividir el lote no ayuda, que decida quien llama.
        raise
    except Exception as e:
        if len(descriptions) == 1:
            print(f"  Error LLM (item único '{descriptions[0][:30]}', a Otros): {e}")
            return [("Otros", "Otros", descriptions[0])]
        mid = len(descriptions) // 2
        print(f"  Lote de {len(descriptions)} falló ({e}); dividiendo en {mid}+{len(descriptions) - mid}")
        left = _llm_classify_batch(descriptions[:mid], categories)
        right = _llm_classify_batch(descriptions[mid:], categories)
        return left + right


def llm_classify_uncategorized(db_path=None, batch_size: int = 10):
    """Reclasifica con LLM los items que están en 'Otros' o sin categoría.

    Solo procesa los que normalize_product() no pudo clasificar.
    """
    path = Path(db_path) if db_path else DB_PATH
    conn = _get_conn(path)

    # Obtener items sin categorizar (categoria_general IS NULL o 'Otros')
    rows = conn.execute(
        "SELECT id, descripcion FROM line_items "
        "WHERE categoria_general IS NULL OR categoria_general = 'Otros' "
        "ORDER BY id"
    ).fetchall()

    if not rows:
        print("  No hay items sin categorizar.")
        conn.close()
        return 0

    print(f"  Items sin categorizar: {len(rows)} (usando LLM en lotes de {batch_size})")

    total_classified = 0
    # Procesar en lotes
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        descriptions = [r["descripcion"] for r in batch]

        print(f"  Lote {i // batch_size + 1}/{(len(rows) + batch_size - 1) // batch_size} ({len(batch)} items)...")

        # Llamar al LLM
        try:
            results = _llm_classify_batch(descriptions, CATEGORIES)
        except LLMConfigError as e:
            print(f"  ⚠ LLM no disponible, se dejan sin clasificar "
                  f"{len(rows) - i} items (reintentables): {e}")
            break

        # Validar y aplicar
        valid_cats = set(CATEGORIES.keys())
        valid_subs = {c: set(subs) for c, subs in CATEGORIES.items()}

        for (item_id, desc), (cat, sub, prod) in zip(batch, results):
            cat, sub = _resolve_cat_sub(cat, sub, CATEGORIES)

            conn.execute(
                "UPDATE line_items SET categoria_general=?, subcategoria=?, producto_norm=?, llm_classified=? WHERE id=?",
                (cat, sub, prod, 0 if cat == "Otros" else 1, item_id)
            )
            total_classified += 1

        conn.commit()

    conn.close()
    print(f"  LLM clasificó {total_classified} items.")
    return total_classified


def _summary(path):
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    lines = []
    lines.append("\n===== RESUMEN TAXONOMÍA =====")
    lines.append("\nItems por categoria_general:")
    for r in conn.execute(
            "SELECT COALESCE(categoria_general,'(sin cat)') c, COUNT(*) n "
            "FROM line_items GROUP BY 1 ORDER BY n DESC"):
        lines.append(f"  {r['c']:35s} {r['n']:5d}")
    lines.append("\nItems por subcategoria:")
    for r in conn.execute(
            "SELECT COALESCE(subcategoria,'(sin sub)') c, COUNT(*) n "
            "FROM line_items GROUP BY 1 ORDER BY n DESC"):
        lines.append(f"  {r['c']:30s} {r['n']:5d}")
    others = conn.execute(
        "SELECT COUNT(*) n, COUNT(DISTINCT descripcion) d FROM line_items "
        "WHERE categoria_general='Otros'").fetchone()
    lines.append(f"\nItems restantes en 'Otros': {others['n']} items, "
                 f"{others['d']} productos únicos")
    lines.append("\n=====resumen TIENDAS =====")
    for r in conn.execute(
            "SELECT direccion, COUNT(*) n FROM tickets GROUP BY 1 ORDER BY n DESC"):
        lines.append(f"  {r['direccion']!r:45s} {r['n']:4d}")
    conn.close()
    text = "\n".join(lines)
    print(text)
    return text


def apply_store_normalization_to_db(db_path=None):
    """Aplica normalize_store a la columna direccion de tickets."""
    path = Path(db_path) if db_path else DB_PATH
    conn = sqlite3.connect(str(path))
    rows = conn.execute("SELECT id, direccion FROM tickets").fetchall()
    updated = 0
    for tid, direccion in rows:
        nuevo = normalize_store(direccion)
        if nuevo != direccion:
            conn.execute("UPDATE tickets SET direccion=? WHERE id=?", (nuevo, tid))
            updated += 1
    conn.commit()
    conn.close()
    print(f"Direcciones actualizadas: {updated} de {len(rows)} tickets")
    return updated


if __name__ == "__main__":
    apply_taxonomy_to_db()
    apply_store_normalization_to_db()
