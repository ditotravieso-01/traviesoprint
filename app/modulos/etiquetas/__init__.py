from flask import Blueprint, request, render_template, jsonify
from flask_login import login_required
import math
from app.services.calculadora_etiquetas import (
    calcular_metros_desde_unidades,
    calcular_unidades_desde_metros,
    MARGEN_CORTE_MM,
    MARGEN_MESA_MM
)

# ==========================================
# CONSTANTES
# ==========================================
ANCHO_ROLLO_DEFECTO_M = 1.3
PRECIO_POR_DEFECTO = 10.0

etiquetas_bp = Blueprint('etiquetas', __name__, url_prefix='/etiquetas', template_folder='templates')


# ==========================================
# FUNCIÓN AUXILIAR DE CÁLCULO
# ==========================================
def calcular_datos(ancho_cm, alto_cm, precio_m2, mesa_activo, girar_activo, auto_girar_activo,
                   cantidad_str, area_str, ancho_rollo_m=ANCHO_ROLLO_DEFECTO_M):
    """
    Calcula todos los datos de impresión de etiquetas.
    - ancho_rollo_m: ancho del rollo en metros (por defecto 1.3).
      El largo del paño de 1 m² se calcula como 1 / ancho_rollo_m.
    """
    # Normalizar ancho del rollo
    try:
        ancho_rollo_m = float(ancho_rollo_m) if ancho_rollo_m else ANCHO_ROLLO_DEFECTO_M
    except (TypeError, ValueError):
        ancho_rollo_m = ANCHO_ROLLO_DEFECTO_M
    if ancho_rollo_m <= 0:
        ancho_rollo_m = ANCHO_ROLLO_DEFECTO_M

    # Área del paño = ancho_rollo_m × largo_paño_m = 1 m²  →  largo_paño_m = 1 / ancho_rollo_m
    ANCHO_PAPEL_MM = ancho_rollo_m * 1000.0
    LARGO_1M2_MM = 1000.0 / ancho_rollo_m

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
        'mesa': mesa_activo,
        'anchoRolloM': ancho_rollo_m
    }

    try:
        if ancho_cm <= 0 or alto_cm <= 0 or precio_m2 <= 0:
            raise ValueError("Medidas y precio deben ser positivos.")
        if not cantidad_str and not area_str:
            raise ValueError("Introduce una cantidad de etiquetas o un área.")

        ancho_mm = ancho_cm * 10.0
        alto_mm = alto_cm * 10.0

        ancho_util_mm = ANCHO_PAPEL_MM - 2 * MARGEN_CORTE_MM
        if ancho_util_mm <= 0:
            raise ValueError("Marca de corte demasiado grande para el papel.")

        orientacion_texto = "normal"
        mensaje_orientacion = ""

        # ---- Lógica de orientación ----
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

            mensaje_orientacion = f"Optimización IA: mejor orientación **{mejor}** ({etiquetas_por_m2} etiquetas/m²)"
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
                #Redondear a 2 decimales ANTES de multiplicar por precio
                precio_total = round(area_total, 2) * precio_m2
                filas_usadas = metros_completos * filas_por_metro
                celdas_totales = columnas * filas_usadas
                es_completo = True
                resultado = f"""
                <strong>Capacidad por m²:</strong> {etiquetas_por_m2} etiquetas<br>
                {mensaje_orientacion}<br>
                {metros_completos} metros completos exactos<br>
                • Área total: {area_total:.2f} m²<br>
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
                #Redondear a 2 decimales ANTES de multiplicar por precio
                precio_total = round(area_total, 2) * precio_m2
                filas_usadas = (metros_completos * filas_por_metro) + filas_extra
                celdas_totales = columnas * filas_usadas
                es_completo = False
                resultado = f"""
                <strong>Capacidad por m²:</strong> {etiquetas_por_m2} etiquetas<br>
                {mensaje_orientacion}<br>
                {metros_completos} metros completos + {etiquetas_extra} etiquetas adicionales<br>
                • Las {etiquetas_extra} etiquetas ocupan {filas_extra} fila(s) extra<br>
                • Área total: {area_total:.2f} m²<br>
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
            # ---- MODO ÁREA ----
            area_total_ingresada = float(area_str)
            metros_completos = int(area_total_ingresada)
            area_resto = area_total_ingresada - metros_completos

            filas = metros_completos * filas_por_metro

            if area_resto > 0:
                largo_resto_mm = (area_resto / (ANCHO_PAPEL_MM / 1000.0)) * 1000.0
                filas_resto = int(largo_resto_mm // alto_efectivo)
                filas += filas_resto

            cantidad_etiq = filas * columnas
            area_total = area_total_ingresada
            #Redondear a 2 decimales ANTES de multiplicar por precio
            precio_total = round(area_total, 2) * precio_m2
            filas_usadas = filas
            celdas_totales = columnas * filas_usadas
            es_completo = False

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

        # Redondeo a 2 decimales en simData
        simData = {
            'columnas': columnas,
            'filasPorMetro': filas_por_metro,
            'filasUsadas': filas_usadas,
            'celdasTotales': celdas_totales,
            'areaTotal': round(area_total, 2),
            'esCompleto': es_completo,
            'anchoCm': round(ancho_efectivo / 10.0, 2),
            'altoCm': round(alto_efectivo / 10.0, 2),
            'orientacion': orientacion_texto,
            'mesa': mesa_activo,
            'anchoRolloM': ancho_rollo_m
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
@login_required
def index():
    ancho = ''
    alto = ''
    precio = PRECIO_POR_DEFECTO
    cantidad = ''
    area = '1'
    mesa_checked = 'checked'
    girar_checked = ''
    auto_girar_checked = ''
    ancho_rollo_m = ANCHO_ROLLO_DEFECTO_M

    resultado = ''
    detalles = ''
    error = ''
    simData = {
        'columnas': 0, 'filasPorMetro': 0, 'filasUsadas': 0, 'celdasTotales': 0,
        'areaTotal': 0.0, 'esCompleto': False, 'anchoCm': 0.0, 'altoCm': 0.0,
        'orientacion': 'normal', 'mesa': False, 'anchoRolloM': ANCHO_ROLLO_DEFECTO_M
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
        try:
            ancho_rollo_m = float(request.form.get('ancho_rollo', ANCHO_ROLLO_DEFECTO_M))
        except (TypeError, ValueError):
            ancho_rollo_m = ANCHO_ROLLO_DEFECTO_M

        data = calcular_datos(ancho_cm, alto_cm, precio_m2, mesa_activo, girar_activo,
                              auto_girar_activo, cantidad_str, area_str, ancho_rollo_m)

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
                           ancho_rollo_m=ancho_rollo_m,
                           simData=simData)


# ==========================================
# ENDPOINT PARA CÁLCULO EN VIVO (AJAX)
# ==========================================
@etiquetas_bp.route('/calcular', methods=['POST'])
@login_required
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

        # Aceptar ancho_rollo (nuevo) o tipo_rollo (compatibilidad)
        ancho_rollo_m = None
        ancho_rollo_form = request.form.get('ancho_rollo')
        if ancho_rollo_form:
            try:
                ancho_rollo_m = float(ancho_rollo_form)
            except (TypeError, ValueError):
                ancho_rollo_m = None
        if ancho_rollo_m is None:
            tipo_rollo = request.form.get('tipo_rollo', '').strip()
            if tipo_rollo == '1.3m':
                ancho_rollo_m = 1.3
            elif tipo_rollo == '1m':
                ancho_rollo_m = 1.0
            else:
                ancho_rollo_m = ANCHO_ROLLO_DEFECTO_M

        data = calcular_datos(ancho_cm, alto_cm, precio_m2, mesa_activo, girar_activo,
                              auto_girar_activo, cantidad_str, area_str, ancho_rollo_m)
        return jsonify({
            'resultado': data['resultado'],
            'detalles': data['detalles'],
            'error': data['error'],
            'simData': data['simData']
        })
    except Exception as e:
        return jsonify({'error': str(e)})