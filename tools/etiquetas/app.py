# =============================================================================
# CairostudioKit - Calculadora de Etiquetas
# =============================================================================
from flask import Flask, request, render_template
import math

app = Flask(__name__)

# Constantes físicas
ANCHO_PAPEL_MM = 1300.0
MARCA_CORTE_DEFAULT = 20.0
MARGEN_MESA_MM = 2.0
PRECIO_POR_DEFECTO = 10.0
LARGO_1M2_MM = 769.230769  # 1 m² / 1.3 m = 0.76923 m = 769.23 mm

@app.route('/', methods=['GET', 'POST'])
def index():
    resultado = ""
    error = ""
    ancho = alto = ""
    precio = PRECIO_POR_DEFECTO
    cantidad = area = ""
    mesa_checked = "checked"
    girar_checked = ""

    if request.method == 'POST':
        try:
            ancho_cm = float(request.form['ancho'])
            alto_cm = float(request.form['alto'])
            precio_m2 = float(request.form['precio'])
            mesa_activo = request.form.get('mesa') == '1'
            girar_activo = request.form.get('girar') == '1'
            cantidad_str = request.form['cantidad'].strip()
            area_str = request.form['area'].strip()

            if ancho_cm <= 0 or alto_cm <= 0 or precio_m2 <= 0:
                raise ValueError("Medidas y precio deben ser positivos.")
            if not cantidad_str and not area_str:
                raise ValueError("Introduce una cantidad de etiquetas o un área.")

            # Aplicar giro si se solicita
            if girar_activo:
                ancho_cm, alto_cm = alto_cm, ancho_cm

            # Convertir a mm y aplicar margen de mesa
            ancho_mm = ancho_cm * 10.0
            alto_mm = alto_cm * 10.0
            if mesa_activo:
                ancho_efectivo = ancho_mm + MARGEN_MESA_MM
                alto_efectivo = alto_mm + MARGEN_MESA_MM
            else:
                ancho_efectivo = ancho_mm
                alto_efectivo = alto_mm

            ancho_util_mm = ANCHO_PAPEL_MM - 2 * MARCA_CORTE_DEFAULT
            if ancho_util_mm <= 0:
                raise ValueError("Marca de corte demasiado grande para el papel.")

            # Columnas (ancho)
            columnas = int(ancho_util_mm // ancho_efectivo)
            if columnas <= 0:
                raise ValueError("La etiqueta no cabe en el ancho útil.")

            # Filas por metro (basado en largo de 1 m²)
            filas_por_metro = int(LARGO_1M2_MM // alto_efectivo)
            if filas_por_metro <= 0:
                raise ValueError("La etiqueta es más alta que el largo de 1 m².")

            etiquetas_por_m2 = columnas * filas_por_metro

            if cantidad_str:
                # ----- NUEVA LÓGICA: METROS COMPLETOS + ETIQUETAS ADICIONALES -----
                cant_deseada = int(float(cantidad_str))
                if cant_deseada <= 0:
                    raise ValueError("La cantidad debe ser un número positivo.")

                metros_completos = cant_deseada // etiquetas_por_m2
                resto = cant_deseada % etiquetas_por_m2

                if resto == 0:
                    filas_extra = 0
                    etiquetas_extra = 0
                    area_parcial = 0.0
                else:
                    # Calcular filas necesarias para el resto (completando la última fila)
                    filas_extra = math.ceil(resto / columnas)
                    etiquetas_extra = filas_extra * columnas
                    # Área parcial = ancho papel (1.3 m) * (filas_extra * alto_efectivo en metros)
                    area_parcial = (ANCHO_PAPEL_MM / 1000.0) * (filas_extra * alto_efectivo / 1000.0)

                area_total = metros_completos * 1.0 + area_parcial
                precio_total = area_total * precio_m2
                total_etiquetas = metros_completos * etiquetas_por_m2 + etiquetas_extra

                # Construir resultado
                if resto == 0:
                    resultado = f"""
                    <strong>📊 Capacidad por m²:</strong> {etiquetas_por_m2} etiquetas<br>
                    <strong>📈 Para {cant_deseada} etiquetas:</strong><br>
                    ✅ {metros_completos} metros completos exactos<br>
                    • Área total: {area_total:.4f} m²<br>
                    • Precio estimado: <strong>${precio_total:.2f} USD</strong>
                    """
                else:
                    resultado = f"""
                    <strong>📊 Capacidad por m²:</strong> {etiquetas_por_m2} etiquetas<br>
                    <strong>📈 Para {cant_deseada} etiquetas:</strong><br>
                    ✅ {metros_completos} metros completos + {etiquetas_extra} etiquetas adicionales<br>
                    • Las {etiquetas_extra} etiquetas adicionales ocupan {filas_extra} fila(s) extra<br>
                    • Área total: {area_total:.4f} m²<br>
                    • Precio estimado: <strong>${precio_total:.2f} USD</strong>
                    """
                cantidad = cantidad_str
            else:
                # ----- CÁLCULO POR ÁREA (sin cambios) -----
                area_total = float(area_str)
                if area_total <= 0:
                    raise ValueError("El área debe ser positiva.")
                largo_total_mm = (area_total / (ANCHO_PAPEL_MM / 1000.0)) * 1000.0
                filas = int(largo_total_mm // alto_efectivo)
                cantidad_etiq = filas * columnas
                precio_total = area_total * precio_m2

                resultado = f"""
                <strong>📊 Distribución en el rollo:</strong><br>
                • Ancho útil del papel: {ancho_util_mm/10:.2f} cm<br>
                • Columnas: {columnas} (cada etiqueta ocupa {ancho_efectivo/10:.2f} cm de ancho efectivo)<br>
                • Alto por etiqueta: {alto_efectivo/10:.2f} cm<br><br>
                <strong>📈 En {area_total} m² de papel:</strong><br>
                • Largo del rollo: {largo_total_mm/1000:.3f} m<br>
                • Filas completas: {filas}<br>
                • Total etiquetas: <strong>{cantidad_etiq}</strong><br>
                • Precio: <strong>${precio_total:.2f} USD</strong>
                """
                area = area_str

            # Conservar valores del formulario
            ancho = request.form['ancho']
            alto = request.form['alto']
            precio = precio_m2
            mesa_checked = "checked" if mesa_activo else ""
            girar_checked = "checked" if girar_activo else ""

        except Exception as e:
            error = f"❌ {e}"
            ancho = request.form.get('ancho', '')
            alto = request.form.get('alto', '')
            precio = request.form.get('precio', PRECIO_POR_DEFECTO)
            cantidad = request.form.get('cantidad', '')
            area = request.form.get('area', '')
            mesa_checked = "checked" if request.form.get('mesa') == '1' else ""
            girar_checked = "checked" if request.form.get('girar') == '1' else ""

    return render_template('calculadora.html',
                           resultado=resultado,
                           error=error,
                           ancho=ancho,
                           alto=alto,
                           precio=precio,
                           cantidad=cantidad,
                           area=area,
                           mesa_checked=mesa_checked,
                           girar_checked=girar_checked)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)