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
    'Vinilo': {'impresion': 10, 'merma': 4, 'nombre': 'Vinilo'},
    'Lona': {'impresion': 12, 'merma': 5, 'nombre': 'Lona'},
    'Lienzo': {'impresion': 20, 'merma': 5, 'nombre': 'Lienzo'},
    'Papel fotográfico': {'impresion': 16, 'merma': 5, 'nombre': 'Papel fotográfico'},
    'Wallpaper': {'impresion': 12, 'merma': 5, 'nombre': 'Wallpaper'},
}

ANCHO_ROLLO_CM = 134.0

# ==========================================
# RUTA PRINCIPAL
# ==========================================
@carteles_bp.route('/', methods=['GET', 'POST'])
@login_required
def index():
    resultado = ""
    error = ""
    ancho = ""
    alto = ""
    material = 'Vinilo'
    girar_checked = ""
    simData = {
        'anchoCm': 0,
        'altoCm': 0,
        'material': 'Vinilo',
        'areaM2': 0,
        'mermaM2': 0,
        'costoTotal': 0,
        'costoImpresion': 0,
        'costoMerma': 0,
        'girar': False
    }

    if request.method == 'POST':
        try:
            ancho_cm = float(request.form['ancho'])
            alto_cm = float(request.form['alto'])
            material = request.form.get('material', 'Vinilo')
            girar = request.form.get('girar') == '1'

            if ancho_cm <= 0 or alto_cm <= 0:
                raise ValueError("Las dimensiones deben ser positivas.")
            if material not in MATERIALES:
                raise ValueError("Material no válido.")

            if girar:
                ancho_cm, alto_cm = alto_cm, ancho_cm

            if ancho_cm > ANCHO_ROLLO_CM:
                raise ValueError(f"El ancho ({ancho_cm:.1f} cm) supera el ancho del rollo ({ANCHO_ROLLO_CM} cm).")

            area_pieza_m2 = (ancho_cm * alto_cm) / 10000.0

            merma_cm2 = (ANCHO_ROLLO_CM - ancho_cm) * alto_cm
            merma_m2 = merma_cm2 / 10000.0

            precio_impresion = MATERIALES[material]['impresion']
            precio_merma = MATERIALES[material]['merma']

            costo_impresion = area_pieza_m2 * precio_impresion
            costo_merma = merma_m2 * precio_merma
            costo_total = costo_impresion + costo_merma

            resultado = f"""
            <strong>📊 Dimensiones finales de la pieza:</strong> {ancho_cm:.1f} cm × {alto_cm:.1f} cm<br>
            <strong>📏 Área a imprimir:</strong> {area_pieza_m2:.4f} m²<br>
            <strong>💵 Costo de impresión ({material}):</strong> ${costo_impresion:.2f} USD<br>
            <br>
            <strong>🗑️ Merma (desperdicio lateral):</strong> {merma_m2:.4f} m²<br>
            <strong>💵 Costo de la merma:</strong> ${costo_merma:.2f} USD<br>
            <br>
            <strong>💰 Costo total:</strong> ${costo_total:.2f} USD
            """

            ancho = request.form['ancho']
            alto = request.form['alto']
            girar_checked = "checked" if girar else ""

            simData = {
                'anchoCm': ancho_cm,
                'altoCm': alto_cm,
                'material': material,
                'areaM2': area_pieza_m2,
                'mermaM2': merma_m2,
                'costoTotal': costo_total,
                'costoImpresion': costo_impresion,
                'costoMerma': costo_merma,
                'girar': girar
            }

            # Guardar en historial (automático)
            guardar_historial(current_user.id, ancho_cm, alto_cm, material, girar, area_pieza_m2, costo_total)

        except Exception as e:
            error = f"❌ {e}"
            ancho = request.form.get('ancho', '')
            alto = request.form.get('alto', '')
            girar_checked = "checked" if request.form.get('girar') == '1' else ""

    return render_template('carteles.html',
                           resultado=resultado,
                           error=error,
                           ancho=ancho,
                           alto=alto,
                           material=material,
                           girar_checked=girar_checked,
                           materiales=MATERIALES,
                           simData=simData)

# ==========================================
# AJAX PARA CÁLCULO EN VIVO (sin recargar)
# ==========================================
@carteles_bp.route('/calcular', methods=['POST'])
@login_required
def calcular_ajax():
    try:
        ancho_cm = float(request.form.get('ancho', 0))
        alto_cm = float(request.form.get('alto', 0))
        material = request.form.get('material', 'Vinilo')
        girar = request.form.get('girar') == '1'

        if ancho_cm <= 0 or alto_cm <= 0:
            return jsonify({'error': 'Las dimensiones deben ser positivas.'})
        if material not in MATERIALES:
            return jsonify({'error': 'Material no válido.'})

        if girar:
            ancho_cm, alto_cm = alto_cm, ancho_cm

        if ancho_cm > ANCHO_ROLLO_CM:
            return jsonify({'error': f'El ancho ({ancho_cm:.1f} cm) supera el ancho del rollo ({ANCHO_ROLLO_CM} cm).'})

        area_pieza_m2 = (ancho_cm * alto_cm) / 10000.0
        merma_cm2 = (ANCHO_ROLLO_CM - ancho_cm) * alto_cm
        merma_m2 = merma_cm2 / 10000.0

        precio_impresion = MATERIALES[material]['impresion']
        precio_merma = MATERIALES[material]['merma']

        costo_impresion = area_pieza_m2 * precio_impresion
        costo_merma = merma_m2 * precio_merma
        costo_total = costo_impresion + costo_merma

        resultado = f"""
        <strong>📊 Dimensiones finales:</strong> {ancho_cm:.1f} cm × {alto_cm:.1f} cm<br>
        <strong>📏 Área:</strong> {area_pieza_m2:.4f} m²<br>
        <strong>💵 Impresión:</strong> ${costo_impresion:.2f} USD<br>
        <strong>🗑️ Merma:</strong> {merma_m2:.4f} m² (${costo_merma:.2f})<br>
        <strong>💰 Total:</strong> ${costo_total:.2f} USD
        """

        simData = {
            'anchoCm': ancho_cm,
            'altoCm': alto_cm,
            'material': material,
            'areaM2': area_pieza_m2,
            'mermaM2': merma_m2,
            'costoTotal': costo_total,
            'costoImpresion': costo_impresion,
            'costoMerma': costo_merma,
            'girar': girar
        }

        # Guardar historial (si hay cálculo)
        guardar_historial(current_user.id, ancho_cm, alto_cm, material, girar, area_pieza_m2, costo_total)

        return jsonify({
            'resultado': resultado,
            'simData': simData
        })

    except Exception as e:
        return jsonify({'error': str(e)})

# ==========================================
# FUNCIONES PARA HISTORIAL (global por usuario)
# ==========================================
def guardar_historial(user_id, ancho, alto, material, girar, area, costo):
    """Guarda el cálculo en el historial del usuario (usando sesión o DB)"""
    # Usamos la sesión para simplificar (en producción usar DB)
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
        'usuario': current_user.username
    })
    # Limitar a 50 registros
    if len(historial) > 50:
        historial = historial[:50]
    session['historial_carteles'] = historial
    session.modified = True

@carteles_bp.route('/historial', methods=['GET'])
@login_required
def get_historial():
    historial = session.get('historial_carteles', [])
    return jsonify(historial)

@carteles_bp.route('/historial/limpiar', methods=['POST'])
@login_required
def limpiar_historial():
    session['historial_carteles'] = []
    session.modified = True
    return jsonify({'success': True})

# ==========================================
# FAVORITOS (guardar configuraciones)
# ==========================================
@carteles_bp.route('/favoritos', methods=['GET', 'POST'])
@login_required
def favoritos():
    if request.method == 'POST':
        nombre = request.form.get('nombre')
        ancho = float(request.form.get('ancho'))
        alto = float(request.form.get('alto'))
        material = request.form.get('material')
        girar = request.form.get('girar') == '1'

        if not nombre:
            return jsonify({'error': 'Nombre requerido'}), 400

        if 'favoritos_carteles' not in session:
            session['favoritos_carteles'] = []
        favoritos = session['favoritos_carteles']
        favoritos.append({
            'id': len(favoritos) + 1,
            'nombre': nombre,
            'ancho': ancho,
            'alto': alto,
            'material': material,
            'girar': girar
        })
        session['favoritos_carteles'] = favoritos
        session.modified = True
        return jsonify({'success': True})

    # GET: obtener lista
    favoritos = session.get('favoritos_carteles', [])
    return jsonify(favoritos)

@carteles_bp.route('/favoritos/<int:fav_id>', methods=['DELETE'])
@login_required
def eliminar_favorito(fav_id):
    favoritos = session.get('favoritos_carteles', [])
    favoritos = [f for f in favoritos if f.get('id') != fav_id]
    session['favoritos_carteles'] = favoritos
    session.modified = True
    return jsonify({'success': True})
