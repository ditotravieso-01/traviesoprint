"""
Servicio de cálculo para etiquetas.
Reutilizable por los módulos de etiquetas y órdenes.
"""
import math

# Constantes
MARGEN_CORTE_MM = 20.0
MARGEN_MESA_MM = 2.0
PRECIO_POR_M2_DEFAULT = 10.0

def calcular_metros_desde_unidades(ancho_cm, alto_cm, unidades, ancho_rollo_m):
    """
    Calcula los metros lineales necesarios para producir 'unidades' etiquetas
    de dimensiones ancho_cm x alto_cm en un rollo de ancho_rollo_m metros.
    Retorna: { 'por_m2': int, 'metros': float, 'area_m2': float }
    """
    if ancho_cm <= 0 or alto_cm <= 0 or unidades <= 0 or ancho_rollo_m <= 0:
        return {'por_m2': 0, 'metros': 0.0, 'area_m2': 0.0}

    margen = MARGEN_MESA_MM / 10.0  # convertir a cm
    ancho_total = ancho_cm + margen
    alto_total = alto_cm + margen

    ancho_rollo_cm = ancho_rollo_m * 100
    por_fila = int(ancho_rollo_cm // ancho_total)
    por_columna = int(100 // alto_total)
    if por_fila == 0 or por_columna == 0:
        return {'por_m2': 0, 'metros': 0.0, 'area_m2': 0.0}

    etiquetas_por_m2 = por_fila * por_columna
    area_etiqueta_cm2 = ancho_cm * alto_cm
    area_total_cm2 = unidades * area_etiqueta_cm2
    area_m2 = area_total_cm2 / 10000.0
    area_por_metro_lineal_cm2 = ancho_rollo_cm * 100
    metros = area_total_cm2 / area_por_metro_lineal_cm2
    metros = math.ceil(metros * 100) / 100.0  # redondear hacia arriba

    return {'por_m2': etiquetas_por_m2, 'metros': metros, 'area_m2': area_m2}


def calcular_unidades_desde_metros(ancho_cm, alto_cm, metros, ancho_rollo_m):
    """
    Calcula cuántas etiquetas caben en 'metros' lineales de un rollo
    de ancho_rollo_m metros.
    Retorna: { 'por_m2': int, 'unidades': int, 'area_m2': float }
    """
    if ancho_cm <= 0 or alto_cm <= 0 or metros <= 0 or ancho_rollo_m <= 0:
        return {'por_m2': 0, 'unidades': 0, 'area_m2': 0.0}

    margen = MARGEN_MESA_MM / 10.0
    ancho_total = ancho_cm + margen
    alto_total = alto_cm + margen

    ancho_rollo_cm = ancho_rollo_m * 100
    por_fila = int(ancho_rollo_cm // ancho_total)
    por_columna = int(100 // alto_total)
    if por_fila == 0 or por_columna == 0:
        return {'por_m2': 0, 'unidades': 0, 'area_m2': 0.0}

    etiquetas_por_m2 = por_fila * por_columna
    area_etiqueta_cm2 = ancho_cm * alto_cm
    area_por_metro_lineal_cm2 = ancho_rollo_cm * 100
    area_total_cm2 = metros * area_por_metro_lineal_cm2
    area_m2 = area_total_cm2 / 10000.0
    unidades = area_total_cm2 / area_etiqueta_cm2
    unidades = int(unidades)  # redondear hacia abajo (etiquetas completas)

    return {'por_m2': etiquetas_por_m2, 'unidades': unidades, 'area_m2': area_m2}


def calcular_costo_estimado(area_m2, precio_por_m2=PRECIO_POR_M2_DEFAULT):
    """
    Calcula el costo estimado redondeando el área al siguiente metro cuadrado completo (paño).
    """
    if area_m2 <= 0:
        return 0.0
    paños = math.ceil(area_m2)
    return paños * precio_por_m2


def calcular_desde_parametros(ancho_cm, alto_cm, modo, cantidad, tipo_rollo, precio_m2=PRECIO_POR_M2_DEFAULT,
                              mesa_activo=True, girar_activo=False, auto_girar_activo=False):
    """
    Función unificada que recibe los parámetros de etiquetas y devuelve:
    - metros_lineales (cantidad de material en metros)
    - area_m2 (área total en metros cuadrados)
    - etiquetas_por_m2
    - unidades_estimadas (si modo=area, calcula cuántas etiquetas caben)
    - costo_estimado (basado en paños completos)
    - mensaje de orientación, etc.
    """
    # Importar la función de cálculo del módulo de etiquetas para reutilizar la lógica completa
    # Pero para simplificar, usamos las funciones básicas y calculamos orientación manualmente
    # Ya que la lógica de orientación es compleja, la dejamos para el módulo de etiquetas.
    # En este servicio solo haremos el cálculo básico sin orientación automática (se puede añadir después).
    # Para la integración en órdenes, usaremos el cálculo simple sin orientación automática.
    # Si se necesita orientación, se llamará a la función del módulo de etiquetas.
    # Por ahora, asumimos que el usuario elige manualmente si gira o no.
    
    # Determinar tipo de rollo
    rollo_ancho_mm = 1300.0 if tipo_rollo == '1.3m' else 1000.0
    # Largo de 1 m² en mm
    largo_1m2_mm = 769.230769 if tipo_rollo == '1.3m' else 1000.0
    
    ancho_mm = ancho_cm * 10.0
    alto_mm = alto_cm * 10.0
    ancho_util_mm = rollo_ancho_mm - 2 * MARGEN_CORTE_MM
    if ancho_util_mm <= 0:
        return {'error': 'Marca de corte demasiado grande para el papel.'}
    
    # Si se gira manualmente, intercambiar dimensiones
    if girar_activo:
        ancho_mm, alto_mm = alto_mm, ancho_mm
        ancho_cm, alto_cm = alto_cm, ancho_cm
    
    ancho_efectivo = ancho_mm + (MARGEN_MESA_MM if mesa_activo else 0)
    alto_efectivo = alto_mm + (MARGEN_MESA_MM if mesa_activo else 0)
    
    columnas = int(ancho_util_mm // ancho_efectivo) if ancho_efectivo > 0 else 0
    filas_por_metro = int(largo_1m2_mm // alto_efectivo) if alto_efectivo > 0 else 0
    etiquetas_por_m2 = columnas * filas_por_metro
    
    if columnas <= 0 or filas_por_metro <= 0:
        return {'error': 'La etiqueta no cabe en el área útil.'}
    
    # Calcular área y metros según modo
    if modo == 'cantidad':
        # cantidad es el número de etiquetas
        unidades = cantidad
        area_etiqueta_cm2 = ancho_cm * alto_cm
        area_total_cm2 = unidades * area_etiqueta_cm2
        area_m2 = area_total_cm2 / 10000.0
        # Metros lineales: área total / ancho del rollo en metros
        ancho_rollo_m = rollo_ancho_mm / 1000.0
        metros_lineales = area_total_cm2 / (ancho_rollo_m * 100 * 100)  # porque 1 m = 100 cm, área en cm²
        metros_lineales = math.ceil(metros_lineales * 100) / 100.0
        unidades_estimadas = unidades
    else:  # modo == 'area'
        # cantidad es el área en m²
        area_m2 = cantidad
        ancho_rollo_m = rollo_ancho_mm / 1000.0
        # Metros lineales = area_m2 / ancho_rollo_m
        metros_lineales = area_m2 / ancho_rollo_m
        metros_lineales = math.ceil(metros_lineales * 100) / 100.0
        # Calcular unidades estimadas
        area_etiqueta_cm2 = ancho_cm * alto_cm
        area_total_cm2 = area_m2 * 10000.0
        unidades_estimadas = int(area_total_cm2 / area_etiqueta_cm2)
    
    # Costo estimado (paños completos)
    costo_estimado = math.ceil(area_m2) * precio_m2
    
    return {
        'metros_lineales': metros_lineales,
        'area_m2': area_m2,
        'etiquetas_por_m2': etiquetas_por_m2,
        'unidades_estimadas': unidades_estimadas,
        'costo_estimado': costo_estimado,
        'columnas': columnas,
        'filas_por_metro': filas_por_metro,
        'orientacion': 'girada' if girar_activo else 'normal'
    }