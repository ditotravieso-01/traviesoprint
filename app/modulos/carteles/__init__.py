from flask import Blueprint, render_template, request, jsonify, session
from flask_login import login_required, current_user
from app import db
import json
import math
from datetime import datetime

carteles_bp = Blueprint('carteles', __name__, url_prefix='/carteles', template_folder='templates')

# ==========================================
# CONSTANTES Y MATERIALES
# ==========================================
MATERIALES = {
    'Vinilo':             {'impresion': 10, 'merma': 4, 'nombre': 'Vinilo'},
    'Vinilo transparente':{'impresion': 14, 'merma': 5, 'nombre': 'Vinilo transparente'},
    'Vinilo backlit':     {'impresion': 15, 'merma': 5, 'nombre': 'Vinilo backlit'},
    'Lona':               {'impresion': 12, 'merma': 5, 'nombre': 'Lona'},
    'Lienzo':             {'impresion': 20, 'merma': 5, 'nombre': 'Lienzo'},
    'Papel fotográfico':  {'impresion': 16, 'merma': 5, 'nombre': 'Papel fotográfico'},
    'Wallpaper':          {'impresion': 12, 'merma': 5, 'nombre': 'Wallpaper'},
}

ANCHO_ROLLO_DEFAULT = 134.0


# ==========================================
# HELPERS DE PARSEO SEGURO
# ==========================================
def _safe_float(value, default=0.0):
    """Convierte a float de forma segura. Vacío/None/inválido → default."""
    try:
        if value is None or value == '':
            return default
        return float(value)
    except (ValueError, TypeError):
        return default


def _safe_int(value, default=1):
    """Convierte a int de forma segura. Acepta '3', '3.0', 3. Vacío/None → default."""
    try:
        if value is None or value == '':
            return default
        return int(float(value))
    except (ValueError, TypeError):
        return default


# ==========================================
# FUNCIÓN PARA CALCULAR DISTRIBUCIÓN AUTOMÁTICA
# ==========================================
def calcular_distribucion(ancho_cm, alto_cm, cantidad, ancho_rollo_cm, girar=False):
    """
    Calcula la distribución óptima de las piezas en el rollo.
    Retorna: (cols, filas, alto_total_cm, ancho_efectivo_cm, alto_efectivo_cm, orientacion)
    """
    if cantidad == 1:
        # Verificar que la pieza cabe
        ancho_pieza = alto_cm if girar else ancho_cm
        if ancho_pieza > ancho_rollo_cm:
            return (0, 0, 0, ancho_cm, alto_cm, 'error')
        if girar:
            return (1, 1, ancho_cm, alto_cm, ancho_cm, 'girada_manual')
        else:
            return (1, 1, alto_cm, ancho_cm, alto_cm, 'normal')

    opciones = []
    orientaciones_a_probar = ['girada'] if girar else ['normal', 'girada']

    for orientacion in orientaciones_a_probar:
        if orientacion == 'normal':
            ancho_pieza = ancho_cm
            alto_pieza = alto_cm
        else:
            ancho_pieza = alto_cm
            alto_pieza = ancho_cm

        if ancho_pieza > ancho_rollo_cm:
            continue

        max_cols = int(ancho_rollo_cm // ancho_pieza)
        if max_cols == 0:
            max_cols = 1

        mejor_opcion = None
        mejor_alto = float('inf')
        for cols in range(max_cols, 0, -1):
            filas = math.ceil(cantidad / cols)
            alto_total = filas * alto_pieza
            area_rollo = ancho_rollo_cm * alto_total
            area_piezas = cantidad * ancho_pieza * alto_pieza
            merma = area_rollo - area_piezas
            if (mejor_opcion is None) or (alto_total < mejor_alto) or (alto_total == mejor_alto and merma < mejor_opcion['merma']):
                mejor_opcion = {
                    'cols': cols,
                    'filas': filas,
                    'alto_total': alto_total,
                    'ancho_efectivo': ancho_pieza,
                    'alto_efectivo': alto_pieza,
                    'orientacion': orientacion,
                    'merma': merma
                }
                mejor_alto = alto_total

        if mejor_opcion:
            opciones.append(mejor_opcion)

    if not opciones:
        return (0, 0, 0, ancho_cm, alto_cm, 'error')

    mejor = min(opciones, key=lambda x: (x['alto_total'], x['merma']))
    return (mejor['cols'], mejor['filas'], mejor['alto_total'],
            mejor['ancho_efectivo'], mejor['alto_efectivo'], mejor['orientacion'])


# ==========================================
# HELPERS INTERNOS DE CÁLCULO
# ==========================================
def _calcular_payload(ancho_cm, alto_cm, cantidad, material, ancho_rollo,
                     precio_impresion, precio_merma, girar):
    """
    Devuelve un dict con todos los campos calculados.
    Lanza ValueError si algo está mal.
    """
    if ancho_cm <= 0 or alto_cm <= 0:
        raise ValueError("Las dimensiones deben ser positivas.")
    if cantidad < 1:
        raise ValueError("La cantidad debe ser al menos 1.")
    if ancho_rollo <= 0:
        raise ValueError("El ancho del rollo debe ser mayor a 0.")
    if precio_impresion < 0:
        raise ValueError("El precio de impresión no puede ser negativo.")
    if precio_merma < 0:
        raise ValueError("El precio de merma no puede ser negativo.")

    if cantidad > 1:
        cols, filas, alto_total, ancho_efectivo, alto_efectivo, orientacion = calcular_distribucion(
            ancho_cm, alto_cm, cantidad, ancho_rollo, girar
        )
    else:
        if girar:
            ancho_efectivo = alto_cm
            alto_efectivo = ancho_cm
            orientacion = 'girada_manual'
        else:
            ancho_efectivo = ancho_cm
            alto_efectivo = alto_cm
            orientacion = 'normal'
        cols = 1
        filas = 1
        alto_total = alto_efectivo

        # Validar que la pieza cabe en el rollo (caso cantidad=1)
        if ancho_efectivo > ancho_rollo:
            raise ValueError(
                f"El cartel de {ancho_cm:.1f}×{alto_cm:.1f} cm no cabe en el rollo "
                f"de {ancho_rollo:.1f} cm, ni siquiera girado."
            )

    if orientacion == 'error':
        raise ValueError(
            f"El cartel de {ancho_cm:.1f}×{alto_cm:.1f} cm no cabe en el rollo "
            f"de {ancho_rollo:.1f} cm, ni siquiera girado."
        )

    area_pieza_m2 = (ancho_cm * alto_cm) / 10000.0
    area_total_m2 = area_pieza_m2 * cantidad
    area_rollo_m2 = (ancho_rollo * alto_total) / 10000.0
    merma_m2 = max(0.0, area_rollo_m2 - area_total_m2)

    costo_impresion = area_total_m2 * precio_impresion
    costo_merma = merma_m2 * precio_merma
    costo_total = costo_impresion + costo_merma

    return {
        'anchoCm': ancho_cm,
        'altoCm': alto_cm,
        'material': material,
        'areaM2': area_total_m2,
        'mermaM2': merma_m2,
        'costoTotal': costo_total,
        'costoImpresion': costo_impresion,
        'costoMerma': costo_merma,
        'girar': girar,
        'cantidad': cantidad,
        'anchoRollo': ancho_rollo,
        'cols': cols,
        'filas': filas,
        'orientacion': orientacion,
        'anchoEfectivo': ancho_efectivo,
        'altoEfectivo': alto_efectivo,
        'precioImpresion': precio_impresion,
        'precioMerma': precio_merma,
    }


def _render_resultado(sim):
    """Genera el HTML del resultado. Sin emojis (el frontend no los necesita)."""
    cols = sim['cols']
    filas = sim['filas']
    orientacion = sim['orientacion']
    girada = 'girada' in orientacion
    return (
        f"<strong>{sim['cantidad']} pieza(s) de {sim['anchoCm']:.1f}×{sim['altoCm']:.1f} cm</strong><br>"
        f"<strong>Distribución:</strong> {cols} columna(s) × {filas} fila(s){' (giradas)' if girada else ''}<br>"
        f"<strong>Alto total utilizado:</strong> {filas * (sim['altoEfectivo'] or 0):.1f} cm<br>"
        f"<strong>Área total impresa:</strong> {sim['areaM2']:.4f} m²<br>"
        f"<strong>Merma total:</strong> {sim['mermaM2']:.4f} m²<br>"
        f"<strong>Costo impresión ({sim['material']}):</strong> ${sim['costoImpresion']:.2f} USD (${sim['precioImpresion']:.2f}/m²)<br>"
        f"<strong>Costo merma:</strong> ${sim['costoMerma']:.2f} USD (${sim['precioMerma']:.2f}/m²)<br>"
        f"<strong>Costo total:</strong> ${sim['costoTotal']:.2f} USD"
    )


# ==========================================
# RUTA PRINCIPAL (GET y POST)
# ==========================================
@carteles_bp.route('/', methods=['GET', 'POST'])
@login_required
def index():
    resultado = ""
    error = ""
    ancho = ""
    alto = ""
    cantidad = 1
    material = 'Vinilo'
    ancho_rollo = ANCHO_ROLLO_DEFAULT
    precio_impresion = MATERIALES['Vinilo']['impresion']
    precio_merma = MATERIALES['Vinilo']['merma']
    girar_checked = ""

    if request.method == 'POST':
        try:
            ancho_cm = _safe_float(request.form.get('ancho'), 0)
            alto_cm = _safe_float(request.form.get('alto'), 0)
            cantidad = _safe_int(request.form.get('cantidad'), 1)
            material = request.form.get('material', 'Vinilo')
            if material not in MATERIALES:
                material = 'Vinilo'
            ancho_rollo = _safe_float(request.form.get('ancho_rollo'), ANCHO_ROLLO_DEFAULT)
            precio_impresion = _safe_float(
                request.form.get('precio_impresion'),
                MATERIALES[material]['impresion']
            )
            precio_merma = _safe_float(
                request.form.get('precio_merma'),
                MATERIALES[material]['merma']
            )
            girar = request.form.get('girar') == '1'

            sim = _calcular_payload(
                ancho_cm, alto_cm, cantidad, material, ancho_rollo,
                precio_impresion, precio_merma, girar
            )
            resultado = _render_resultado(sim)

            ancho = request.form.get('ancho', '')
            alto = request.form.get('alto', '')
            girar_checked = "checked" if girar else ""

            guardar_historial(current_user.id, ancho_cm, alto_cm, material, girar,
                              sim['areaM2'], sim['costoTotal'], cantidad)

        except Exception as e:
            error = str(e)
            ancho = request.form.get('ancho', '')
            alto = request.form.get('alto', '')
            cantidad = _safe_int(request.form.get('cantidad'), 1)
            ancho_rollo = _safe_float(request.form.get('ancho_rollo'), ANCHO_ROLLO_DEFAULT)
            material = request.form.get('material', 'Vinilo')
            if material not in MATERIALES:
                material = 'Vinilo'
            precio_impresion = _safe_float(
                request.form.get('precio_impresion'),
                MATERIALES[material]['impresion']
            )
            precio_merma = _safe_float(
                request.form.get('precio_merma'),
                MATERIALES[material]['merma']
            )
            girar_checked = "checked" if request.form.get('girar') == '1' else ""

    return render_template('carteles.html',
                           resultado=resultado,
                           error=error,
                           ancho=ancho,
                           alto=alto,
                           cantidad=cantidad,
                           material=material,
                           ancho_rollo=ancho_rollo,
                           precio_impresion=precio_impresion,
                           precio_merma=precio_merma,
                           girar_checked=girar_checked,
                           materiales=MATERIALES,
                           simData={})


# ==========================================
# AJAX PARA CÁLCULO EN VIVO
# ==========================================
@carteles_bp.route('/calcular', methods=['POST'])
@login_required
def calcular_ajax():
    try:
        ancho_cm = _safe_float(request.form.get('ancho'), 0)
        alto_cm = _safe_float(request.form.get('alto'), 0)
        cantidad = _safe_int(request.form.get('cantidad'), 1)
        material = request.form.get('material', 'Vinilo')
        if material not in MATERIALES:
            material = 'Vinilo'
        ancho_rollo = _safe_float(request.form.get('ancho_rollo'), ANCHO_ROLLO_DEFAULT)
        precio_impresion = _safe_float(
            request.form.get('precio_impresion'),
            MATERIALES[material]['impresion']
        )
        precio_merma = _safe_float(
            request.form.get('precio_merma'),
            MATERIALES[material]['merma']
        )
        girar = request.form.get('girar') == '1'

        sim = _calcular_payload(
            ancho_cm, alto_cm, cantidad, material, ancho_rollo,
            precio_impresion, precio_merma, girar
        )

        guardar_historial(current_user.id, ancho_cm, alto_cm, material, girar,
                          sim['areaM2'], sim['costoTotal'], cantidad)

        return jsonify({
            'resultado': _render_resultado(sim),
            'simData': sim,
        })

    except Exception as e:
        return jsonify({'error': str(e)})


# ==========================================
# HISTORIAL Y FAVORITOS (session)
# ==========================================
def guardar_historial(user_id, ancho, alto, material, girar, area, costo, cantidad=1):
    if 'historial_carteles' not in session:
        session['historial_carteles'] = []
    historial = session['historial_carteles']
    historial.insert(0, {
        'fecha': datetime.now().isoformat(),
        'ancho': ancho,
        'alto': alto,
        'material': material,
        'girar': girar,
        'area': area,
        'costo': costo,
        'cantidad': cantidad,
        'usuario': current_user.username
    })
    if len(historial) > 50:
        historial = historial[:50]
    session['historial_carteles'] = historial
    session.modified = True


@carteles_bp.route('/historial', methods=['GET'])
@login_required
def get_historial():
    return jsonify(session.get('historial_carteles', []))


@carteles_bp.route('/historial/limpiar', methods=['POST'])
@login_required
def limpiar_historial():
    session['historial_carteles'] = []
    session.modified = True
    return jsonify({'success': True})


@carteles_bp.route('/favoritos', methods=['GET', 'POST'])
@login_required
def favoritos():
    if request.method == 'POST':
        nombre = request.form.get('nombre')
        ancho = _safe_float(request.form.get('ancho'), 0)
        alto = _safe_float(request.form.get('alto'), 0)
        material = request.form.get('material', 'Vinilo')
        ancho_rollo = _safe_float(request.form.get('ancho_rollo'), ANCHO_ROLLO_DEFAULT)
        girar = request.form.get('girar') == '1'
        cantidad = _safe_int(request.form.get('cantidad'), 1)

        if not nombre:
            return jsonify({'error': 'Nombre requerido'}), 400

        if 'favoritos_carteles' not in session:
            session['favoritos_carteles'] = []
        favoritos_list = session['favoritos_carteles']
        favoritos_list.append({
            'id': len(favoritos_list) + 1,
            'nombre': nombre,
            'ancho': ancho,
            'alto': alto,
            'material': material,
            'ancho_rollo': ancho_rollo,
            'girar': girar,
            'cantidad': cantidad
        })
        session['favoritos_carteles'] = favoritos_list
        session.modified = True
        return jsonify({'success': True})

    return jsonify(session.get('favoritos_carteles', []))


@carteles_bp.route('/favoritos/<int:fav_id>', methods=['DELETE'])
@login_required
def eliminar_favorito(fav_id):
    favoritos_list = session.get('favoritos_carteles', [])
    favoritos_list = [f for f in favoritos_list if f.get('id') != fav_id]
    session['favoritos_carteles'] = favoritos_list
    session.modified = True
    return jsonify({'success': True})