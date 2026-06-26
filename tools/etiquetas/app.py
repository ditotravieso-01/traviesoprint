from flask import Flask, request, render_template
import math

app = Flask(__name__)

ANCHO_PAPEL_MM = 1300.0
MARCA_CORTE_DEFAULT = 20.0
MARGEN_MESA_MM = 2.0
PRECIO_POR_DEFECTO = 10.0
LARGO_1M2_MM = 769.230769   # 1 m² / 1.3 m

@app.route('/', methods=['GET', 'POST'])
def index():
    resultado = ""
    error = ""
    ancho = alto = ""
    precio = PRECIO_POR_DEFECTO
    cantidad = ""
    area = "1"               # valor por defecto
    mesa_checked = "checked"
    girar_checked = ""
    auto_girar_checked = ""

    if request.method == 'POST':
        try:
            ancho_cm = float(request.form['ancho'])
            alto_cm = float(request.form['alto'])
            precio_m2 = float(request.form['precio'])
            mesa_activo = request.form.get('mesa') == '1'
            girar_activo = request.form.get('girar') == '1'
            auto_girar_activo = request.form.get('auto_girar') == '1'
            cantidad_str = request.form['cantidad'].strip()
            area_str = request.form['area'].strip()

            if ancho_cm <= 0 or alto_cm <= 0 or precio_m2 <= 0:
                raise ValueError("Medidas y precio deben ser positivos.")
            if not cantidad_str and not area_str:
                raise ValueError("Introduce una cantidad de etiquetas o un área.")

            # Convertir a mm
            ancho_mm = ancho_cm * 10.0
            alto_mm = alto_cm * 10.0

            ancho_util_mm = ANCHO_PAPEL_MM - 2 * MARCA_CORTE_DEFAULT
            if ancho_util_mm <= 0:
                raise ValueError("Marca de corte demasiado grande para el papel.")

            mensaje_orientacion = ""

            if auto_girar_activo:
                # ---- Calcular orientación normal ----
                ancho_eff_norm = ancho_mm + MARGEN_MESA_MM if mesa_activo else ancho_mm
                alto_eff_norm = alto_mm + MARGEN_MESA_MM if mesa_activo else alto_mm
                col_norm = int(ancho_util_mm // ancho_eff_norm) if ancho_eff_norm > 0 else 0
                fil_m2_norm = int(LARGO_1M2_MM // alto_eff_norm) if alto_eff_norm > 0 else 0
                etiq_norm = col_norm * fil_m2_norm

                # ---- Calcular orientación girada 90° ----
                ancho_eff_gir = alto_mm + MARGEN_MESA_MM if mesa_activo else alto_mm
                alto_eff_gir = ancho_mm + MARGEN_MESA_MM if mesa_activo else ancho_mm
                col_gir = int(ancho_util_mm // ancho_eff_gir) if ancho_eff_gir > 0 else 0
                fil_m2_gir = int(LARGO_1M2_MM // alto_eff_gir) if alto_eff_gir > 0 else 0
                etiq_gir = col_gir * fil_m2_gir

                if etiq_gir > etiq_norm:
                    mejor = "girada 90°"
                    ancho_efectivo = ancho_eff_gir
                    alto_efectivo = alto_eff_gir
                    columnas = col_gir
                    filas_por_metro = fil_m2_gir
                    etiquetas_por_m2 = etiq_gir
                else:
                    mejor = "normal"
                    ancho_efectivo = ancho_eff_norm
                    alto_efectivo = alto_eff_norm
                    columnas = col_norm
                    filas_por_metro = fil_m2_norm
                    etiquetas_por_m2 = etiq_norm

                mensaje_orientacion = f"🤖 Mejor orientación: **{mejor}** ({etiquetas_por_m2} etiquetas/m²)"
            else:
                # ---- Comportamiento manual ----
                if girar_activo:
                    ancho_mm, alto_mm = alto_mm, ancho_mm
                    ancho_cm, alto_cm = alto_cm, ancho_cm

                ancho_efectivo = ancho_mm + (MARGEN_MESA_MM if mesa_activo else 0)
                alto_efectivo = alto_mm + (MARGEN_MESA_MM if mesa_activo else 0)

                columnas = int(ancho_util_mm // ancho_efectivo) if ancho_efectivo > 0 else 0
                filas_por_metro = int(LARGO_1M2_MM // alto_efectivo) if alto_efectivo > 0 else 0
                etiquetas_por_m2 = columnas * filas_por_metro

            if columnas <= 0 or filas_por_metro <= 0:
                raise ValueError("La etiqueta no cabe en el área útil.")

            # ---- Cálculo según cantidad o área ----
            if cantidad_str:
                cant_deseada = int(float(cantidad_str))
                metros_completos = cant_deseada // etiquetas_por_m2
                resto = cant_deseada % etiquetas_por_m2

                if resto == 0:
                    area_total = metros_completos * 1.0
                    precio_total = area_total * precio_m2
                    resultado = f"""
                    <strong>📊 Capacidad por m²:</strong> {etiquetas_por_m2} etiquetas<br>
                    {mensaje_orientacion}<br>
                    ✅ {metros_completos} metros completos exactos<br>
                    • Área total: {area_total:.4f} m²<br>
                    • Precio: <strong>${precio_total:.2f} USD</strong>
                    """
                else:
                    filas_extra = math.ceil(resto / columnas)
                    etiquetas_extra = filas_extra * columnas
                    area_parcial = (ANCHO_PAPEL_MM / 1000.0) * (filas_extra * alto_efectivo / 1000.0)
                    area_total = metros_completos * 1.0 + area_parcial
                    precio_total = area_total * precio_m2
                    resultado = f"""
                    <strong>📊 Capacidad por m²:</strong> {etiquetas_por_m2} etiquetas<br>
                    {mensaje_orientacion}<br>
                    ✅ {metros_completos} metros completos + {etiquetas_extra} etiquetas adicionales<br>
                    • Las {etiquetas_extra} etiquetas ocupan {filas_extra} fila(s) extra<br>
                    • Área total: {area_total:.4f} m²<br>
                    • Precio: <strong>${precio_total:.2f} USD</strong>
                    """
                cantidad = cantidad_str
            else:
                area_total = float(area_str)
                largo_total_mm = (area_total / (ANCHO_PAPEL_MM / 1000.0)) * 1000.0
                filas = int(largo_total_mm // alto_efectivo)
                cantidad_etiq = filas * columnas
                precio_total = area_total * precio_m2
                resultado = f"""
                <strong>📊 Distribución en {area_total} m²:</strong><br>
                {mensaje_orientacion}<br>
                • Ancho útil: {ancho_util_mm/10:.2f} cm, Columnas: {columnas}<br>
                • Alto por etiqueta: {alto_efectivo/10:.2f} cm, Filas: {filas}<br>
                • Total etiquetas: <strong>{cantidad_etiq}</strong><br>
                • Precio: <strong>${precio_total:.2f} USD</strong>
                """
                area = area_str

            # Preservar valores del formulario
            ancho = request.form['ancho']
            alto = request.form['alto']
            precio = precio_m2
            mesa_checked = "checked" if mesa_activo else ""
            girar_checked = "checked" if girar_activo else ""
            auto_girar_checked = "checked" if auto_girar_activo else ""

        except Exception as e:
            error = f"❌ {e}"
            ancho = request.form.get('ancho', '')
            alto = request.form.get('alto', '')
            precio = request.form.get('precio', PRECIO_POR_DEFECTO)
            cantidad = request.form.get('cantidad', '')
            area = request.form.get('area', '1')
            mesa_checked = "checked" if request.form.get('mesa') == '1' else ""
            girar_checked = "checked" if request.form.get('girar') == '1' else ""
            auto_girar_checked = "checked" if request.form.get('auto_girar') == '1' else ""

    return render_template('etiquetas.html',
                           resultado=resultado,
                           error=error,
                           ancho=ancho,
                           alto=alto,
                           precio=precio,
                           cantidad=cantidad,
                           area=area,
                           mesa_checked=mesa_checked,
                           girar_checked=girar_checked,
                           auto_girar_checked=auto_girar_checked)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)