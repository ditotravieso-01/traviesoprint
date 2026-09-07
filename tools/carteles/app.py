# =============================================================================
# CairostudioKit - Calculadora de Lona / Merma
# =============================================================================
from flask import Flask, request, render_template

app = Flask(__name__)

MATERIALES = {
    'Vinilo':           {'impresion': 10, 'merma': 4},
    'Lona':             {'impresion': 12, 'merma': 5},
    'Lienzo':           {'impresion': 20, 'merma': 5},
    'Papel fotográfico':{'impresion': 16, 'merma': 5},
    'Wallpaper':        {'impresion': 12, 'merma': 5},
}

ANCHO_ROLLO_CM = 134.0

@app.route('/', methods=['GET', 'POST'])
def index():
    resultado = ""
    error = ""
    ancho = alto = ""
    material = 'Vinilo'
    girar_checked = ""

    if request.method == 'POST':
        try:
            ancho_cm = float(request.form['ancho'])
            alto_cm = float(request.form['alto'])
            material = request.form['material']
            girar = request.form.get('girar') == '1'

            if ancho_cm <= 0 or alto_cm <= 0:
                raise ValueError("Las dimensiones deben ser positivas.")
            if material not in MATERIALES:
                raise ValueError("Material no válido.")

            if girar:
                ancho_cm, alto_cm = alto_cm, ancho_cm

            if ancho_cm > ANCHO_ROLLO_CM:
                raise ValueError(f"El ancho ({ancho_cm:.1f} cm) supera el ancho del rollo (134 cm).")

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
                           materiales=MATERIALES)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True)