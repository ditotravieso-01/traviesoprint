from flask import Blueprint, request, render_template, jsonify
import math

# ==========================================
# CONSTANTES
# ==========================================
ROLLOS = {
    '1.3m': {
        'ancho_mm': 1300.0,
        'largo_1m2_mm': 769.230769,
        'nombre': 'Rollo 1.3 m'
    },
    '1m': {
        'ancho_mm': 1000.0,
        'largo_1m2_mm': 1000.0,
        'nombre': 'Rollo 1 m'
    }
}
MARCA_CORTE_DEFAULT = 20.0
MARGEN_MESA_MM = 2.0
PRECIO_POR_DEFECTO = 10.0

# ==========================================
# BLUEPRINT
# ==========================================
etiquetas_bp = Blueprint('etiquetas', __name__, url_prefix='/etiquetas', template_folder='templates')

# ==========================================
# FUNCIÓN AUXILIAR DE CÁLCULO
# ==========================================
def calcular_datos(ancho_cm, alto_cm, precio_m2, mesa_activo, girar_activo, auto_girar_activo,
                   cantidad_str, area_str, tipo_rollo):
    """
    Retorna un diccionario con todos los datos calculados y la simulación.
    """
    rollo = ROLLOS.get(tipo_rollo, ROLLOS['1.3m'])
    ANCHO_PAPEL_MM = rollo['ancho_mm']
    LARGO_1M2_MM = rollo['largo_1m2_mm']

    resultado = ""
    detalles = ""
    error = None
    simData = {
        'columnas': 0,
        'filasPorMetro': 0,
        'filasUsadas': 0,
        'celdasTotales': 0,
        'areaTotal': 0.0,
        'esCompleto': False,
        'anchoCm': 0.0,
        'altoCm': 0.0,
        'orientacion': 'normal',
        'mesa': mesa_activo
    }

    try:
        if ancho_cm <= 0 or alto_cm <= 0 or precio_m2 <= 0:
            raise ValueError("Medidas y precio deben ser positivos.")
        if not cantidad_str and not area_str:
            raise ValueError("Introduce una cantidad de etiquetas o un área.")

        ancho_mm = ancho_cm * 10.0
        alto_mm = alto_cm * 10.0

        ancho_util_mm = ANCHO_PAPEL_MM - 2 * MARCA_CORTE_DEFAULT
        if ancho_util_mm <= 0:
            raise ValueError("Marca de corte demasiado grande para el papel.")

        orientacion_texto = "normal"
        mensaje_orientacion = ""

        if auto_girar_activo:
            # Normal
            ancho_eff_norm = ancho_mm + (MARGEN_MESA_MM if mesa_activo else 0)
            alto_eff_norm = alto_mm + (MARGEN_MESA_MM if mesa_activo else 0)
            col_norm = int(ancho_util_mm // ancho_eff_norm) if ancho_eff_norm > 0 else 0
            fil_m2_norm = int(LARGO_1M2_MM // alto_eff_norm) if alto_eff_norm > 0 else 0
            etiq_norm = col_norm * fil_m2_norm

            # Girada
            ancho_eff_gir = alto_mm + (MARGEN_MESA_MM if mesa_activo else 0)
            alto_eff_gir = ancho_mm + (MARGEN_MESA_MM if mesa_activo else 0)
            col_gir = int(ancho_util_mm // ancho_eff_gir) if ancho_eff_gir > 0 else 0
            fil_m2_gir = int(LARGO_1M2_MM // alto_eff_gir) if alto_eff_gir > 0 else 0
            etiq_gir = col_gir * fil_m2_gir

            if etiq_gir > etiq_norm:
                mejor = "girada 90°"
                orientacion_texto = "girada"
                ancho_efectivo = ancho_eff_gir
                alto_efectivo = alto_eff_gir
                columnas = col_gir
                filas_por_metro = fil_m2_gir
                etiquetas_por_m2 = etiq_gir
            else:
                mejor = "normal"
                orientacion_texto = "normal"
                ancho_efectivo = ancho_eff_norm
                alto_efectivo = alto_eff_norm
                columnas = col_norm
                filas_por_metro = fil_m2_norm
                etiquetas_por_m2 = etiq_norm

            mensaje_orientacion = f"🤖 Optimización IA: mejor orientación **{mejor}** ({etiquetas_por_m2} etiquetas/m²)"
        else:
            if girar_activo:
                ancho_mm, alto_mm = alto_mm, ancho_mm
                ancho_cm, alto_cm = alto_cm, ancho_cm
                orientacion_texto = "girada manual"
            ancho_efectivo = ancho_mm + (MARGEN_MESA_MM if mesa_activo else 0)
            alto_efectivo = alto_mm + (MARGEN_MESA_MM if mesa_activo else 0)
            columnas = int(ancho_util_mm // ancho_efectivo) if ancho_efectivo > 0 else 0
            filas_por_metro = int(LARGO_1M2_MM // alto_efectivo) if alto_efectivo > 0 else 0
            etiquetas_por_m2 = columnas * filas_por_metro
            mensaje_orientacion = f"Orientación: {orientacion_texto}"

        if columnas <= 0 or filas_por_metro <= 0:
            raise ValueError("La etiqueta no cabe en el área útil.")

        area_total = 0.0
        es_completo = False
        filas_usadas = 0
        celdas_totales = 0

        if cantidad_str:
            cant_deseada = int(float(cantidad_str))
            metros_completos = cant_deseada // etiquetas_por_m2
            resto = cant_deseada % etiquetas_por_m2

            if resto == 0:
                area_total = metros_completos * 1.0
                precio_total = area_total * precio_m2
                filas_usadas = metros_completos * filas_por_metro
                celdas_totales = columnas * filas_usadas
                es_completo = True
                resultado = f"""
                <strong>📊 Capacidad por m²:</strong> {etiquetas_por_m2} etiquetas<br>
                {mensaje_orientacion}<br>
                ✅ {metros_completos} metros completos exactos<br>
                • Área total: {area_total:.4f} m²<br>
                • Precio: <strong>${precio_total:.2f} USD</strong>
                """
                detalles = f"""
                • Modo: Cantidad ({cant_deseada} etiquetas)<br>
                • Columnas: {columnas}<br>
                • Filas por metro: {filas_por_metro}<br>
                • Filas usadas: {filas_usadas}<br>
                • Margen de mesa: {'Sí (2mm)' if mesa_activo else 'No'}<br>
                • Orientación: {orientacion_texto}<br>
                • Metros completos: {metros_completos}<br>
                • Resto: 0
                """
            else:
                filas_extra = math.ceil(resto / columnas)
                etiquetas_extra = filas_extra * columnas
                area_parcial = (ANCHO_PAPEL_MM / 1000.0) * (filas_extra * alto_efectivo / 1000.0)
                area_total = metros_completos * 1.0 + area_parcial
                precio_total = area_total * precio_m2
                filas_usadas = (metros_completos * filas_por_metro) + filas_extra
                celdas_totales = columnas * filas_usadas
                es_completo = False
                resultado = f"""
                <strong>📊 Capacidad por m²:</strong> {etiquetas_por_m2} etiquetas<br>
                {mensaje_orientacion}<br>
                ✅ {metros_completos} metros completos + {etiquetas_extra} etiquetas adicionales<br>
                • Las {etiquetas_extra} etiquetas ocupan {filas_extra} fila(s) extra<br>
                • Área total: {area_total:.4f} m²<br>
                • Precio: <strong>${precio_total:.2f} USD</strong>
                """
                detalles = f"""
                • Modo: Cantidad ({cant_deseada} etiquetas)<br>
                • Columnas: {columnas}<br>
                • Filas por metro: {filas_por_metro}<br>
                • Filas usadas: {filas_usadas}<br>
                • Margen de mesa: {'Sí (2mm)' if mesa_activo else 'No'}<br>
                • Orientación: {orientacion_texto}<br>
                • Metros completos: {metros_completos}<br>
                • Etiquetas extra: {etiquetas_extra}<br>
                • Filas extra: {filas_extra}
                """

        else:
            # --- MODO ÁREA (modificado para paños completos) ---
            area_total_ingresada = float(area_str)
            metros_completos = int(area_total_ingresada)  # Parte entera
            area_resto = area_total_ingresada - metros_completos

            # Filas de los metros completos
            filas = metros_completos * filas_por_metro

            # Filas del área fraccionaria (si existe)
            if area_resto > 0:
                largo_resto_mm = (area_resto / (ANCHO_PAPEL_MM / 1000.0)) * 1000.0
                filas_resto = int(largo_resto_mm // alto_efectivo)
                filas += filas_resto

            cantidad_etiq = filas * columnas
            # El área total real (para mostrar en resultado y precio) sigue siendo el área ingresada
            area_total = area_total_ingresada
            precio_total = area_total * precio_m2
            filas_usadas = filas
            celdas_totales = columnas * filas_usadas
            es_completo = False  # Porque puede haber fracción

            resultado = f"""
            <strong>📊 Distribución en {area_total:.2f} m²:</strong><br>
            {mensaje_orientacion}<br>
            • Ancho útil: {ancho_util_mm/10:.2f} cm, Columnas: {columnas}<br>
            • Alto por etiqueta: {alto_efectivo/10:.2f} cm, Filas: {filas}<br>
            • Total etiquetas: <strong>{cantidad_etiq}</strong><br>
            • Precio: <strong>${precio_total:.2f} USD</strong>
            """
            detalles = f"""
            • Modo: Área ({area_total:.2f} m²)<br>
            • Columnas: {columnas}<br>
            • Filas totales: {filas}<br>
            • Alto por etiqueta: {alto_efectivo/10:.2f} cm<br>
            • Ancho útil: {ancho_util_mm/10:.2f} cm<br>
            • Margen de mesa: {'Sí (2mm)' if mesa_activo else 'No'}<br>
            • Orientación: {orientacion_texto}
            """
            area = area_str
            cantidad = ""  # Limpiamos el campo cantidad

        simData = {
            'columnas': columnas,
            'filasPorMetro': filas_por_metro,
            'filasUsadas': filas_usadas,
            'celdasTotales': celdas_totales,
            'areaTotal': area_total,
            'esCompleto': es_completo,
            'anchoCm': ancho_efectivo / 10.0,
            'altoCm': alto_efectivo / 10.0,
            'orientacion': orientacion_texto,
            'mesa': mesa_activo
        }

    except Exception as e:
        error = str(e)

    return {
        'resultado': resultado,
        'detalles': detalles,
        'error': error,
        'simData': simData
    }


# ==========================================
# RUTA PRINCIPAL (GET y POST)
# ==========================================
@etiquetas_bp.route('/', methods=['GET', 'POST'])
def index():
    ancho = ''
    alto = ''
    precio = PRECIO_POR_DEFECTO
    cantidad = ''
    area = '1'
    mesa_checked = 'checked'
    girar_checked = ''
    auto_girar_checked = ''
    tipo_rollo = '1.3m'

    resultado = ''
    detalles = ''
    error = ''
    simData = {
        'columnas': 0,
        'filasPorMetro': 0,
        'filasUsadas': 0,
        'celdasTotales': 0,
        'areaTotal': 0.0,
        'esCompleto': False,
        'anchoCm': 0.0,
        'altoCm': 0.0,
        'orientacion': 'normal',
        'mesa': False
    }

    if request.method == 'POST':
        ancho_cm = float(request.form.get('ancho', 0))
        alto_cm = float(request.form.get('alto', 0))
        precio_m2 = float(request.form.get('precio', PRECIO_POR_DEFECTO))
        mesa_activo = request.form.get('mesa') == '1'
        girar_activo = request.form.get('girar') == '1'
        auto_girar_activo = request.form.get('auto_girar') == '1'
        cantidad_str = request.form.get('cantidad', '').strip()
        area_str = request.form.get('area', '').strip()
        tipo_rollo = request.form.get('tipo_rollo', '1.3m')

        data = calcular_datos(ancho_cm, alto_cm, precio_m2, mesa_activo, girar_activo,
                              auto_girar_activo, cantidad_str, area_str, tipo_rollo)

        resultado = data['resultado']
        detalles = data['detalles']
        error = data['error']
        simData = data['simData']

        ancho = request.form.get('ancho', '')
        alto = request.form.get('alto', '')
        precio = precio_m2
        cantidad = request.form.get('cantidad', '')
        area = request.form.get('area', '1')
        mesa_checked = "checked" if mesa_activo else ""
        girar_checked = "checked" if girar_activo else ""
        auto_girar_checked = "checked" if auto_girar_activo else ""

    return render_template('etiquetas.html',
                           resultado=resultado,
                           detalles=detalles,
                           error=error,
                           ancho=ancho,
                           alto=alto,
                           precio=precio,
                           cantidad=cantidad,
                           area=area,
                           mesa_checked=mesa_checked,
                           girar_checked=girar_checked,
                           auto_girar_checked=auto_girar_checked,
                           tipo_rollo=tipo_rollo,
                           simData=simData,
                           rollos=ROLLOS)


# ==========================================
# ENDPOINT PARA CÁLCULO EN VIVO (AJAX)
# ==========================================
@etiquetas_bp.route('/calcular', methods=['POST'])
def calcular_ajax():
    try:
        ancho_cm = float(request.form.get('ancho', 0))
        alto_cm = float(request.form.get('alto', 0))
        precio_m2 = float(request.form.get('precio', PRECIO_POR_DEFECTO))
        mesa_activo = request.form.get('mesa') == '1'
        girar_activo = request.form.get('girar') == '1'
        auto_girar_activo = request.form.get('auto_girar') == '1'
        cantidad_str = request.form.get('cantidad', '').strip()
        area_str = request.form.get('area', '').strip()
        tipo_rollo = request.form.get('tipo_rollo', '1.3m')

        data = calcular_datos(ancho_cm, alto_cm, precio_m2, mesa_activo, girar_activo,
                              auto_girar_activo, cantidad_str, area_str, tipo_rollo)
        return jsonify({
            'resultado': data['resultado'],
            'detalles': data['detalles'],
            'error': data['error'],
            'simData': data['simData']
        })
    except Exception as e:
        return jsonify({'error': str(e)})