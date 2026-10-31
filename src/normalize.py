"""Normalización de descripciones de productos de Mercadona.
Mapea descripciones de ticket a nombres canónicos y categorías."""
import re
from typing import Optional


# Reglas ordenadas por especificidad: las más específicas primero.
# Cada regla: (keyword_upper, categoria, producto_norm)
# El matching es case-insensitive y busca el keyword como substring.

CATEGORY_RULES = [
    ("LIMP. BAÑOS", "Limpieza", "Limpieza baño"),
    # === CAFÉ ===
    ("NESCAFÉ", "Café", "Nescafé"),
    ("CAPSULA CAFÉ C/LECHE", "Café", "Cápsula café con leche"),
    ("CAPSULA CAFE C/LECHE", "Café", "Cápsula café con leche"),
    ("CAPSULA", "Café", "Cápsula café"),
    ("CAFE ", "Café", "Café"),
    ("CAFÉ ", "Café", "Café"),
    ("C. TOSTADO", "Café", "Café tostado"),
    ("C 0,0 TOSTADA", "Café", "Café descafeinado"),
    ("ESPRESSO", "Café", "Café espresso"),
    ("SOLUBLE DESC", "Café", "Café soluble descafeinado"),
    ("SOLUBLE", "Café", "Café soluble"),

    # === BEBIDAS (refrescos, cerveza, vino, isotónicos) ===
    ("COLA ZERO", "Bebidas", "Cola zero"),
    ("COCA COLA", "Bebidas", "Cola"),
    ("CERV", "Bebidas", "Cerveza"),
    ("MAHOU", "Bebidas", "Cerveza"),
    ("CERVEZA", "Bebidas", "Cerveza"),
    ("VINO TINTO", "Bebidas", "Vino tinto"),
    ("VINO BLANCO", "Bebidas", "Vino blanco"),
    ("BLANCO P-3", "Bebidas", "Vino blanco"),
    ("VINO ", "Bebidas", "Vino"),
    ("FUENTE DEHESA", "Bebidas", "Vino"),
    ("ISOTONICO", "Bebidas", "Isotónico"),
    ("ISOTÓNICO", "Bebidas", "Isotónico"),
    ("LIMONADA", "Bebidas", "Limonada"),
    ("GASEOSA", "Bebidas", "Gaseosa"),
    ("BEBER ", "Bebidas", "Bebida isotónica"),
    ("YOG LIQ", "Bebidas", "Yogur líquido"),
    ("FUZE", "Bebidas", "Fuze Tea"),
    ("ZUMO", "Bebidas", "Zumo"),
    ("ISO ", "Bebidas", "Iso"),
    ("AGUA", "Bebidas", "Agua"),
    ("PACK 4X500 ZERO", "Bebidas", "Pack bebidas zero"),

    # === LÁCTEOS (leche, yogur, queso, huevos, nata) ===
    ("LECHE", "Lácteos", "Leche"),
    ("GRIEGO", "Lácteos", "Yogur griego"),
    ("YOGUR", "Lácteos", "Yogur"),
    ("L.CASEI", "Lácteos", "Yogur"),
    ("LCASEI", "Lácteos", "Yogur"),
    ("BÍF", "Lácteos", "Yogur bifidus"),
    ("BIF ", "Lácteos", "Yogur bifidus"),
    ("0% CON FRUTAS", "Lácteos", "Yogur 0%"),
    ("0%0% NAT", "Lácteos", "Yogur 0%"),
    ("KÉFIR", "Lácteos", "Kéfir"),
    ("KEFIR", "Lácteos", "Kéfir"),
    ("YOGOMIX", "Lácteos", "Yogur"),
    ("YOG ", "Lácteos", "Yogur"),
    ("PETIT DE BOLSILLO", "Lácteos", "Petit suisse"),
    ("QUESO", "Lácteos", "Queso"),
    ("Q. VIEJO", "Lácteos", "Queso viejo"),
    ("Q.MADURADO", "Lácteos", "Queso curado"),
    ("RULO CABRA", "Lácteos", "Queso de cabra"),
    ("RULITO CABRA", "Lácteos", "Queso de cabra"),
    ("GRANA PADANO", "Lácteos", "Queso parmesano"),
    ("CREMOSO", "Lácteos", "Queso crema"),
    ("DESNAT", "Lácteos", "Queso desnatado"),
    ("PORCIÓN LIGHT", "Lácteos", "Queso porción"),
    ("PORCIÓN ", "Lácteos", "Queso porción"),
    ("NATA SPRAY", "Lácteos", "Nata"),
    ("NATA PARA COCINAR", "Lácteos", "Nata"),
    ("HUEVO", "Lácteos", "Huevos"),

    # === CARNE (incluye embutidos, salchichas) ===
    ("CARRILLADA", "Carne", "Carrillada"),
    ("CONTRAMUSLO", "Carne", "Contramuslo"),
    ("ALAS ADOBADAS", "Carne", "Alas adobadas"),
    ("ALAS PARTIDAS", "Carne", "Alas"),
    ("COSTILLA", "Carne", "Costilla"),
    ("POLLO ASADO", "Carne", "Pollo asado"),
    ("CUARTO TRASERO", "Carne", "Cuarto trasero"),
    ("PICADA DE VACUNO", "Carne", "Picada de vacuno"),
    ("CONEJO", "Carne", "Conejo"),
    ("C. CARRILLERA", "Carne", "Carrillera"),
    ("BURGER", "Carne", "Hamburguesas"),
    ("HAMBURGUESA", "Carne", "Hamburguesas"),
    ("P. PAV RED", "Carne", "Pavo reducido sal"),
    ("SOLOMILLO", "Carne", "Solomillo"),
    ("SECRETO", "Carne", "Secreto"),
    ("PECHUGA", "Carne", "Pechuga"),
    ("CHULETA", "Carne", "Chuleta"),
    ("SALCHICHA", "Carne", "Salchichas"),
    ("LOMO SALMÓN", "Pescado", "Lomo de salmón"),
    ("LOMO", "Carne", "Lomo"),
    ("MIGAS", "Carne", "Migas"),
    ("PAVO", "Carne", "Pavo"),
    ("PALETILLA", "Carne", "Paletilla"),
    ("JAMÓN", "Carne", "Jamón"),
    ("JAMON", "Carne", "Jamón"),
    ("FUET", "Carne", "Fuet"),
    ("ESPETEC", "Carne", "Fuet"),
    ("SARTA DULCE", "Carne", "Salchichón sarta"),
    ("CHORIZO", "Carne", "Chorizo"),
    ("SOBRASADA", "Carne", "Sobrasada"),
    ("SALPICÓN", "Carne", "Salpicón"),
    ("S.FRANKFURT", "Carne", "Salchichas Frankfurt"),
    ("FRANKFURT", "Carne", "Salchichas Frankfurt"),
    ("BANDERILLAS", "Carne", "Banderillas"),
    ("MAGRO", "Carne", "Carne magra"),
    ("PINCHO SIN VARILLA", "Carne", "Pincho"),
    ("MINI CHORIZO", "Carne", "Chorizo mini"),

    # === PESCADO Y MARISCO ===
    ("SALMÓN", "Pescado", "Salmón"),
    ("SALMON", "Pescado", "Salmón"),
    ("DORADA", "Pescado", "Dorada"),
    ("CHIRLA", "Pescado", "Chirla"),
    ("GAMBAS", "Pescado", "Gambas"),
    ("CAMARÓN", "Pescado", "Camarón"),
    ("LANGOSTINO", "Pescado", "Langostino"),
    ("BOQUERON", "Pescado", "Boquerones"),
    ("BOQ. AL VINAGRE", "Pescado", "Boquerones vinagre"),
    ("LUBINA", "Pescado", "Lubina"),
    ("MERLUZA", "Pescado", "Merluza"),
    ("FUMET", "Pescado", "Fumet"),
    ("BACALAO", "Pescado", "Bacalao"),
    ("FIDEUA", "Pescado", "Fideuá"),
    ("ATÚN", "Pescado", "Atún"),
    ("ATUN ", "Pescado", "Atún"),
    ("VENTRESCA", "Pescado", "Ventresca"),
    ("BONITO", "Pescado", "Bonito"),
    ("ALMEJA", "Pescado", "Almeja"),
    ("MEJILLÓN", "Pescado", "Mejillón"),
    ("MEJ.", "Pescado", "Mejillón"),
    ("NUGGETS SALMON", "Pescado", "Nuggets de salmón"),
    ("ESCALOPIN SALMON", "Pescado", "Escalopín salmón"),
    ("RODAJA SALMÓN", "Pescado", "Salmón rodaja"),
    ("ARREGL", "Pescado", "Preparado pescado"),
    ("CHOCO ", "Pescado", "Sepia"),

    # === FRESROS (fruta y verdura) ===
    ("GAZPACHO", "Frescos", "Gazpacho"),
    ("SALMOREJO", "Frescos", "Salmorejo"),
    ("TOMATE", "Frescos", "Tomate"),
    ("T.CHERRY", "Frescos", "Tomate cherry"),
    ("T. 100%INTEGRALES", "Panadería", "Pan integral"),  # seems like bread
    ("CALABACIN", "Frescos", "Calabacín"),
    ("CALABAZA", "Frescos", "Calabaza"),
    ("PIMIENTO", "Frescos", "Pimiento"),
    ("PUERRO", "Frescos", "Puerros"),
    ("JUDIA", "Frescos", "Judías"),
    ("JUDÍA", "Frescos", "Judías"),
    ("GUISANTE", "Frescos", "Guisantes"),
    ("ESPINACA", "Frescos", "Espinacas"),
    ("ESPARRAGO", "Frescos", "Espárragos"),
    ("ESPÁRRAGO", "Frescos", "Espárragos"),
    ("BERENJENA", "Frescos", "Berenjena"),
    ("ZANAHORIA", "Frescos", "Zanahoria"),
    ("CEBOLLINO", "Frescos", "Cebollino"),
    ("CEBOLLA", "Frescos", "Cebolla"),
    ("CHAMPIÑON", "Frescos", "Champiñón"),
    ("SETA", "Frescos", "Setas"),
    ("PATATA", "Frescos", "Patata"),
    ("BROTES TIERNOS", "Frescos", "Brotes tiernos"),
    ("BROTES", "Frescos", "Brotes"),
    ("ICEBERG", "Frescos", "Lechuga iceberg"),
    ("EDAMAME", "Frescos", "Edamame"),
    ("FLORETAS DE BROCOLI", "Frescos", "Brócoli"),
    ("ALCACHOFA", "Frescos", "Alcachofa"),
    ("COL LOMBARDA", "Frescos", "Col lombarda"),
    ("COL ", "Frescos", "Col"),
    ("PEPINO", "Frescos", "Pepino"),
    ("MENESTRA", "Frescos", "Menestra"),
    ("PISTO", "Frescos", "Pisto"),
    ("PARRILLADA VERDURA", "Frescos", "Verduras parrilla"),
    ("WOK VERDURAS", "Frescos", "Wok verduras"),
    ("UVA", "Frescos", "Uva"),
    ("MANGO", "Frescos", "Mango"),
    ("AGUACATE", "Frescos", "Aguacate"),
    ("PERA", "Frescos", "Pera"),
    ("PIÑA", "Frescos", "Piña"),
    ("FRESÓN", "Frescos", "Fresones"),
    ("FRESO", "Frescos", "Fresones"),
    ("KIWI", "Frescos", "Kiwi"),
    ("MANDARINA", "Frescos", "Mandarina"),
    ("MELON", "Frescos", "Melón"),
    ("MELÓN", "Frescos", "Melón"),
    ("SANDÍA", "Frescos", "Sandía"),
    ("PLATANO", "Frescos", "Plátano"),
    ("BANANA", "Frescos", "Plátano"),
    ("MANZANA", "Frescos", "Manzana"),
    ("CEREZA", "Frescos", "Cerezas"),
    ("ENSALADA", "Frescos", "Ensalada"),
    ("ENS ", "Frescos", "Ensalada"),
    ("ENSALADILLA", "Frescos", "Ensaladilla"),
    ("GUACAMOLE", "Frescos", "Guacamole"),
    ("PERLAS TIERNOS", "Frescos", "Brotes tiernos"),
    ("MAIZ DULCE", "Frescos", "Maíz dulce"),
    ("MAÍZ DULCE", "Frescos", "Maíz dulce"),
    ("MAIZ COCIDO", "Frescos", "Maíz cocido"),
    ("MAÍZ COCIDO", "Frescos", "Maíz cocido"),
    ("TABULÉ", "Frescos", "Tabulé"),

    # === PANADERÍA Y BOLLERÍA ===
    ("PAN", "Panadería", "Pan"),
    ("BARRA", "Panadería", "Pan barra"),
    ("BAGUETTE", "Panadería", "Baguette"),
    ("M.CROISS", "Panadería", "Croissants"),
    ("CROISSANT", "Panadería", "Croissants"),
    ("HOJALDRE", "Panadería", "Hojaldre"),
    ("MAGDALENA", "Panadería", "Magdalenas"),
    ("SOBAOS", "Panadería", "Sobaos"),
    ("ROSQUILLA", "Panadería", "Rosquillas"),
    ("BERLINA", "Panadería", "Berlinesa"),
    ("MINI VOL", "Panadería", "Vol-au-vent"),
    ("VOL-AV-VENT", "Panadería", "Vol-au-vent"),
    ("TORTITA", "Panadería", "Tortitas"),
    ("BISCOTTE", "Panadería", "Biscottes"),
    ("BISC.", "Panadería", "Biscottes"),
    ("TOSTAS", "Panadería", "Tostadas"),
    ("CONOS", "Panadería", "Conos"),
    ("MASA", "Panadería", "Masa"),
    ("CROQUETA", "Panadería", "Croquetas"),
    ("MINISANDWICH", "Panadería", "Mini sándwich"),
    ("SÁNDWICH", "Panadería", "Sándwich"),
    ("SANDWICH", "Panadería", "Sándwich"),
    ("PICATOSTE", "Panadería", "Picatostes"),
    ("PICOS 100%", "Panadería", "Picos"),
    ("PICOS", "Panadería", "Picos"),
    ("REGAÑÁ", "Panadería", "Regañás"),
    ("REGA RED", "Panadería", "Regañás"),
    ("BOLSA RAFIA", "Otros", "Bolsa"),

    # === SNACKS ===
    ("PATATAS EXTRACRUNCH", "Snacks", "Patatas fritas"),
    ("STICKS DE PATATA", "Snacks", "Snacks patata"),
    ("TWISTER FRIES", "Snacks", "Patatas twist"),
    ("PREPARADO CRUJIENTE", "Snacks", "Preparado crujiente"),
    ("PALOMIT", "Snacks", "Palomitas"),
    ("NACHOS", "Snacks", "Nachos"),
    ("AROS DE MAÍZ", "Snacks", "Aros de maíz"),
    ("DORITOS", "Snacks", "Doritos"),
    ("CHEETOS", "Snacks", "Cheetos"),
    ("TIRAS FRITAS", "Snacks", "Tiras fritas"),
    ("CACAHUETE", "Snacks", "Cacahuetes"),
    ("ANACARDO", "Snacks", "Anacardos"),
    ("PIÑONES", "Snacks", "Piñones"),
    ("COCKTAIL TOST", "Snacks", "Frutos secos"),
    ("CHICLES", "Snacks", "Chicles"),
    ("CHICLE", "Snacks", "Chicles"),
    ("CARAMELO", "Snacks", "Caramelos"),
    ("PIPA", "Snacks", "Pipas"),

    # === DULCES Y CHOCOLATE ===
    ("CHOCOLATE", "Dulces", "Chocolate"),
    ("CHOCO ", "Dulces", "Chocolate"),
    ("CHOC ", "Dulces", "Chocolate"),
    ("CHOC S/", "Dulces", "Chocolate sin azúcar"),
    ("NEGRO 99%", "Dulces", "Chocolate negro"),
    ("BOMBÓN", "Dulces", "Bombones"),
    ("BOMBON", "Dulces", "Bombones"),
    ("T. CREAM", "Dulces", "Crema cacao"),
    ("CREMA CACAO", "Dulces", "Crema cacao"),
    ("NOCILLA", "Dulces", "Crema cacao"),
    ("TURRON", "Dulces", "Turrón"),
    ("TARTA", "Dulces", "Tarta"),
    ("TORTA DE", "Dulces", "Tarta de almendra"),
    ("GALLETA", "Dulces", "Galletas"),
    ("GALL.", "Dulces", "Galletas"),
    ("GALL CERE", "Dulces", "Galletas cereales"),
    ("MERMELADA", "Dulces", "Mermelada"),
    ("MERM.", "Dulces", "Mermelada"),
    ("MIEL", "Dulces", "Miel"),
    ("AZUCAR", "Dulces", "Azúcar"),
    ("AZÚCAR", "Dulces", "Azúcar"),
    ("TIRAMISU", "Dulces", "Tiramisú"),
    ("FLAN", "Dulces", "Flan"),
    ("HELADO", "Dulces", "Helado"),
    ("D.MEMBRILLO", "Dulces", "Dulce de membrillo"),
    ("BASTONCILLO", "Dulces", "Bastón"),
    ("BARRITA", "Dulces", "Barrita"),
    ("B. LINEA", "Dulces", "Barrita línea"),
    ("DIG ", "Dulces", "Digestive"),
    ("PALITO FRUTOS", "Dulces", "Palito frutos secos"),
    ("PALITO", "Dulces", "Palito"),
    ("BOMBON ALMENDRADO", "Dulces", "Bombones almendra"),
    ("MINI CARITA", "Dulces", "Chocolate mini"),
    ("MINI BOMBON", "Dulces", "Bombones mini"),
    ("GASEOSA", "Bebidas", "Gaseosa"),  # moved up via bebidas

    # === COMIDA PREPARADA ===
    ("PIZZA", "Comida preparada", "Pizza"),
    ("PRE.PAELLA", "Comida preparada", "Paella preparada"),
    ("PRE.PAELLA", "Comida preparada", "Paella preparada"),
    ("ARREGL.PAELLA", "Comida preparada", "Paella preparada"),
    ("COCIDO", "Comida preparada", "Cocido"),
    ("CHILI CON CARNE", "Comida preparada", "Chili con carne"),
    ("RELLENO FAJITAS", "Comida preparada", "Fajitas"),
    ("RELLENO KEBAB", "Comida preparada", "Kebab"),
    ("SALSA BARBACOA", "Comida preparada", "Salsa barbacoa"),
    ("SALSA MEXICANA", "Comida preparada", "Salsa mexicana"),
    ("SALSA DE SOJA", "Comida preparada", "Salsa de soja"),
    ("SALSA TERIYAKI", "Comida preparada", "Salsa teriyaki"),
    ("SALSA LIGERA", "Comida preparada", "Salsa ligera"),
    ("KÉTCHUP", "Comida preparada", "Kétchup"),
    ("KETCHUP", "Comida preparada", "Kétchup"),
    ("NUGGETS", "Comida preparada", "Nuggets"),
    ("TORTILLA", "Comida preparada", "Tortilla"),

    # === PASTA Y LEGUMBRES ===
    ("FIDEO", "Pasta y legumbres", "Fideos"),
    ("MACARRON", "Pasta y legumbres", "Macarrones"),
    ("MACARRÓN", "Pasta y legumbres", "Macarrones"),
    ("PENNE", "Pasta y legumbres", "Penne"),
    ("LINGUINE", "Pasta y legumbres", "Linguine"),
    ("NOODLES", "Pasta y legumbres", "Noodles"),
    ("TORTELLONI", "Pasta y legumbres", "Tortelloni"),
    ("ARROZ", "Pasta y legumbres", "Arroz"),
    ("FIDEUA", "Pasta y legumbres", "Fideuá"),
    ("ALUBIA", "Pasta y legumbres", "Alubias"),
    ("GARBANZO", "Pasta y legumbres", "Garbanzos"),

    # === ACEITES Y CONDIMENTOS ===
    ("ACEITE", "Aceites y salsas", "Aceite"),
    ("SAL FINA", "Aceites y salsas", "Sal"),
    ("SALERO", "Aceites y salsas", "Sal"),
    ("AJO SECO", "Aceites y salsas", "Ajo"),
    ("AJO GRANULADO", "Aceites y salsas", "Ajo granulado"),
    ("LAUREL", "Aceites y salsas", "Laurel"),
    ("TOMILLO", "Aceites y salsas", "Tomillo"),
    ("PEREJIL", "Aceites y salsas", "Perejil"),
    ("ÑORAS", "Aceites y salsas", "Ñoras"),
    ("ALIÑO", "Aceites y salsas", "Aliño"),
    ("ESPECIAS", "Aceites y salsas", "Especias"),
    ("SALSA", "Aceites y salsas", "Salsa"),

    # === CONSERVAS ===
    ("TOM.RECETA", "Conservas", "Tomate receta"),
    ("TOM. RECETA", "Conservas", "Tomate receta"),
    ("TOM.FRITO", "Conservas", "Tomate frito"),
    ("COCKTAIL NATURAL", "Conservas", "Cocktail"),
    ("COCKTAIL", "Conservas", "Cocktail"),
    ("ACEITUNA", "Conservas", "Aceitunas"),
    ("BONITO NORTE", "Conservas", "Bonito en conserva"),
    ("ATUN CLARO NATURAL", "Conservas", "Atún en conserva"),
    ("ATÚN CLARO GIRAS", "Conservas", "Atún en conserva"),
    ("CHAMPIÑON LIMPIO", "Conservas", "Champiñón en conserva"),

    # === SOPAS Y CREMAS ===
    ("CALDO", "Sopas y cremas", "Caldo"),
    ("C. COCIDO", "Sopas y cremas", "Crema cocido"),
    ("C. CALABACÍN", "Sopas y cremas", "Crema calabacín"),
    ("C. POLLO", "Sopas y cremas", "Crema pollo"),
    ("CREMA DE CALABAZA", "Sopas y cremas", "Crema calabaza"),
    ("SOPA", "Sopas y cremas", "Sopa"),

    # === LIMPIEZA Y HOGAR ===
    ("LIMPIA", "Limpieza", "Limpieza"),
    ("LIMPIAHOGAR", "Limpieza", "Limpieza"),
    ("LIMP. ", "Limpieza", "Limpieza"),
    ("DET ", "Limpieza", "Detergente"),
    ("DETERGENTE", "Limpieza", "Detergente"),
    ("DETERG", "Limpieza", "Detergente"),
    ("LAVAVAJILLA", "Limpieza", "Lavavajillas"),
    ("SUAVIZANTE", "Limpieza", "Suavizante"),
    ("LEJIA", "Limpieza", "Lejía"),
    ("QUITAGRASA", "Limpieza", "Quitagrasa"),
    ("ABRILLANTADOR", "Limpieza", "Abrillantador"),
    ("AMONIACO", "Limpieza", "Amoníaco"),
    ("ACT.BLANQUEANTE", "Limpieza", "Blanqueante"),
    ("ELIMINADOR OLORES", "Limpieza", "Eliminador olores"),
    ("PAPEL ALUMINIO", "Limpieza", "Papel aluminio"),
    ("PAPEL VEGETAL", "Limpieza", "Papel vegetal"),
    ("PAPEL HUMEDO", "Limpieza", "Papel húmedo"),
    ("ROLLO HOGAR", "Limpieza", "Rollo hogar"),
    ("BOLSAS ZIP", "Limpieza", "Bolsas zip"),
    ("BOLSAS ", "Limpieza", "Bolsas"),
    ("BOLSA PLASTICO", "Limpieza", "Bolsa plástico"),
    ("BOLSA RAFIA", "Limpieza", "Bolsa"),
    ("FREGONA", "Limpieza", "Fregona"),
    ("ESTROPAJO", "Limpieza", "Estropajo"),
    ("FIBRA BLANCA", "Limpieza", "Estropajo"),
    ("FIBRA", "Limpieza", "Estropajo"),
    ("BAYETA", "Limpieza", "Bayeta"),
    ("SAL LAVAVAJILLAS", "Limpieza", "Sal lavavajillas"),
    ("CÁPSULA ROPA", "Limpieza", "Cápsula detergente"),
    ("CAPSULA ROPA", "Limpieza", "Cápsula detergente"),
    ("30 B.ENVASES", "Limpieza", "Bolsas basura"),
    ("40 B.", "Limpieza", "Bolsas basura"),
    ("VARITAS DIF", "Limpieza", "Difusor"),
    ("CARBON VEGETAL", "Limpieza", "Carbón"),
    ("AMB ", "Limpieza", "Ambientador"),
    ("AMB. ", "Limpieza", "Ambientador"),
    ("AMB COCHE", "Limpieza", "Ambientador"),
    ("BOLSAS ", "Limpieza", "Bolsas"),
    ("HIELO", "Limpieza", "Hielo"),

    # === HIGIENE Y CUIDADO PERSONAL ===
    ("CHAMPU", "Higiene", "Champú"),
    ("CHAMPÚ", "Higiene", "Champú"),
    ("CHAMPU ", "Higiene", "Champú"),
    ("GEL ", "Higiene", "Gel"),
    ("GELLY", "Higiene", "Gel"),
    ("JABON", "Higiene", "Jabón"),
    ("JABÓN", "Higiene", "Jabón"),
    ("TAMPON", "Higiene", "Tampón"),
    ("COMPRESA", "Higiene", "Compresa"),
    ("MASK", "Higiene", "Mascarilla"),
    ("HIGIENICO", "Higiene", "Pañuelo higiénico"),
    ("PAÑUELO", "Higiene", "Pañuelos"),
    ("TOALL", "Higiene", "Toallitas"),
    ("COLGATE", "Higiene", "Pasta dental"),
    ("CEPILLO", "Higiene", "Cepillo dental"),
    ("COLG. ", "Higiene", "Pasta dental"),
    ("CREMA ESFERAS", "Higiene", "Crema facial"),
    ("CREMA ", "Higiene", "Crema"),
    ("EXFOLIANTE", "Higiene", "Exfoliante"),
    ("T. CARA Y MANOS", "Higiene", "Crema manos"),
    ("T.CARA", "Higiene", "Crema facial"),
    ("SPRAY ESSENCE", "Higiene", "Spray facial"),
    ("GUANTES", "Higiene", "Guantes"),
    ("PAPEL HUMEDO WC", "Limpieza", "Papel húmedo WC"),
    ("PINTAROLAS", "Higiene", "Pintalabios"),

    # === DESAYUNO ===
    ("CEREAL", "Desayuno", "Cereales"),
    ("MUESLI", "Desayuno", "Muesli"),
    ("AVENA", "Desayuno", "Avena"),

    # === FRUTOS SECOS ===
    ("72% ALMENDRA", "Dulces", "Chocolate almendra"),
    ("ALMENDRA", "Snacks", "Almendras"),

    # Casos especiales que no deben quedar en Otros
    ("PARKING", "Otros", "Parking"),
    ("BOLSA PLASTICO", "Otros", "Bolsa plástico"),

    # === ROPA Y TEXTIL HOGAR ===
    ("TOALLA", "Ropa y hogar", "Toalla"),
    ("SÁBANA", "Ropa y hogar", "Sábana"),
    ("SABANA", "Ropa y hogar", "Sábana"),
    ("FUNDA", "Ropa y hogar", "Funda"),
    ("ALMOHADA", "Ropa y hogar", "Almohada"),
    ("EDREDÓN", "Ropa y hogar", "Edredón"),
    ("EDREDON", "Ropa y hogar", "Edredón"),
    ("MANTA", "Ropa y hogar", "Manta"),
    ("CORTINA", "Ropa y hogar", "Cortina"),
    ("ALFOMBRA", "Ropa y hogar", "Alfombra"),
    ("CAMISA", "Ropa", "Camisa"),
    ("PANTALÓN", "Ropa", "Pantalón"),
    ("PANTALON", "Ropa", "Pantalón"),
    ("VESTIDO", "Ropa", "Vestido"),
    ("CHAQUETA", "Ropa", "Chaqueta"),
    ("ABRIGO", "Ropa", "Abrigo"),
    ("CAMISETA", "Ropa", "Camiseta"),
    ("JERSEY", "Ropa", "Jersey"),
    ("JERSEY ", "Ropa", "Jersey"),
    ("CALZÓN", "Ropa", "Calzón"),
    ("CALZON", "Ropa", "Calzón"),
    ("CALCETÍN", "Ropa", "Calcetín"),
    ("CALCETIN", "Ropa", "Calcetín"),
    ("ROPA ", "Ropa", "Ropa"),

    # === MOBILIARIO Y DECORACIÓN ===
    ("MESA", "Mobiliario", "Mesa"),
    ("SILLA", "Mobiliario", "Silla"),
    ("SILLÓN", "Mobiliario", "Sillón"),
    ("SILLON", "Mobiliario", "Sillón"),
    ("SOFÁ", "Mobiliario", "Sofá"),
    ("SOFÁ ", "Mobiliario", "Sofá"),
    ("SOFA", "Mobiliario", "Sofá"),
    ("ARMARIO", "Mobiliario", "Armario"),
    ("ESTANTERÍA", "Mobiliario", "Estantería"),
    ("ESTANTERIA", "Mobiliario", "Estantería"),
    ("CAMA", "Mobiliario", "Cama"),
    ("COLCHÓN", "Mobiliario", "Colchón"),
    ("COLCHON", "Mobiliario", "Colchón"),
    ("ESPEJO", "Mobiliario", "Espejo"),
    ("LÁMPARA", "Mobiliario", "Lámpara"),
    ("LAMPARA", "Mobiliario", "Lámpara"),
    ("PERCHERO", "Mobiliario", "Perchero"),
    ("BANQUETA", "Mobiliario", "Banqueta"),
    ("TABURETE", "Mobiliario", "Taburete"),
    ("ESCABEA", "Mobiliario", "Escobera"),
]


def normalize_product(descripcion: str) -> tuple:
    """Devuelve (categoria, producto_norm) para una descripción dada."""
    desc_upper = descripcion.upper()
    for keyword, categoria, producto in CATEGORY_RULES:
        if keyword in desc_upper:
            return categoria, producto
    return "Otros", descripcion


def normalize_all_in_db(db_path=None):
    """Aplica normalización a todos los items en la BD.

    DEPRECADO: `taxonomy.apply_taxonomy_to_db()` es la fuente de verdad (respeta
    overrides y llm_classified, y usa KEYWORD_RULES, mucho más completo). Se
    mantiene porque `ingest.py` la llama en la Fase 3 antes de aplicar la
    taxonomía. No introduzcas aquí lógica nueva: añade reglas a
    taxonomy.KEYWORD_RULES.
    """
    import sqlite3
    from .database import DB_PATH
    path = db_path or DB_PATH
    conn = sqlite3.connect(str(path))

    # Se delega en la taxonomía (KEYWORD_RULES) en vez de usar las reglas
    # antiguas de este módulo, que no cubren muchos productos y devolvían la
    # descripción cruda del ticket (origen de los duplicados 'CERVEZA'/'Cerveza').
    try:
        from .taxonomy import normalize_product as _tax_normalize
    except Exception:
        _tax_normalize = None

    rows = conn.execute(
        "SELECT id, descripcion FROM line_items "
        "WHERE producto_norm IS NULL OR producto_norm = ''"
    ).fetchall()
    updated = 0
    for item_id, desc in rows:
        if _tax_normalize is not None:
            cat, _sub, prod = _tax_normalize(desc)
        else:
            cat, prod = normalize_product(desc)
        conn.execute(
            "UPDATE line_items SET producto_norm = ?, categoria = ? WHERE id = ?",
            (prod, cat, item_id)
        )
        updated += 1
    conn.commit()
    conn.close()
    print(f"Normalizados {updated} items (solo los que faltaban)")

    # Print category summary
    conn = sqlite3.connect(str(path))
    cats = conn.execute(
        "SELECT categoria, COUNT(*), SUM(importe) FROM line_items GROUP BY categoria ORDER BY SUM(importe) DESC"
    ).fetchall()
    conn.close()
    print("\nResumen por categoría:")
    for cat, count, gasto in cats:
        print(f"  {cat or 'NULL':25s} | {count:4d} items | {gasto:8.2f}€")

    return updated