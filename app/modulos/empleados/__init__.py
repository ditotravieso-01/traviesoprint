from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from app import db
from app.models import User, Empleado, Asistencia, PeriodoNomina, DetalleNomina
from datetime import datetime, timedelta
from sqlalchemy import func
import json

empleados_bp = Blueprint('empleados', __name__, url_prefix='/empleados', template_folder='templates')


# ============================================================
#  CONSTANTES Y FUNCIONES AUXILIARES
# ============================================================

TARIFA_NORMAL = 1.00
TARIFA_NOCTURNA = 1.30
TARIFA_FIN_SEMANA = 1.50
INICIO_NOCTURNO = 18.0

def es_fin_semana(fecha):
    return fecha.weekday() in (5, 6)

def calcular_pago_dia(entrada, salida):
    ent_dec = entrada.hour + entrada.minute / 60.0
    sal_dec = salida.hour + salida.minute / 60.0
    if es_fin_semana(entrada):
        horas = sal_dec - ent_dec
        return horas * TARIFA_FIN_SEMANA
    if sal_dec <= INICIO_NOCTURNO:
        horas = sal_dec - ent_dec
        return horas * TARIFA_NORMAL
    elif ent_dec >= INICIO_NOCTURNO:
        horas = sal_dec - ent_dec
        return horas * TARIFA_NOCTURNA
    else:
        horas_normales = INICIO_NOCTURNO - ent_dec
        horas_nocturnas = sal_dec - INICIO_NOCTURNO
        return (horas_normales * TARIFA_NORMAL) + (horas_nocturnas * TARIFA_NOCTURNA)

def calcular_horas_salario(asistencias):
    total_horas = 0.0
    total_salario = 0.0
    entrada = None
    for a in asistencias:
        if a.tipo == 'entrada':
            entrada = a.timestamp
        elif a.tipo == 'salida' and entrada is not None:
            salida = a.timestamp
            if salida > entrada:
                horas = (salida - entrada).total_seconds() / 3600.0
                salario = calcular_pago_dia(entrada, salida)
                total_horas += horas
                total_salario += salario
            entrada = None
    return total_horas, total_salario

def get_empleado_actual():
    if current_user.role not in ('operario', 'admin', 'disenador', 'disennador', 'comercial', 'economico'):
        return None
    return Empleado.query.filter_by(user_id=current_user.id).first()

def get_periodo_actual():
    return PeriodoNomina.crear_periodo_actual()

def calcular_nomina_empleado(empleado_id, periodo_id):
    periodo = PeriodoNomina.query.get_or_404(periodo_id)
    empleado = Empleado.query.get_or_404(empleado_id)
    asistencias = empleado.get_asistencias_periodo(periodo.fecha_inicio, periodo.fecha_fin)
    horas, salario = calcular_horas_salario(asistencias)
    detalle = DetalleNomina.query.filter_by(periodo_id=periodo_id, empleado_id=empleado_id).first()
    if not detalle:
        detalle = DetalleNomina(periodo_id=periodo_id, empleado_id=empleado_id)
        db.session.add(detalle)
    detalle.horas_totales = horas
    detalle.salario_bruto = salario
    db.session.commit()
    return detalle


# ============================================================
#  RUTAS
# ============================================================

@empleados_bp.route('/')
@login_required
def index():
    empleado = get_empleado_actual()
    if empleado:
        return redirect(url_for('empleados.panel_empleado'))
    if current_user.role in ('economico', 'admin'):
        return redirect(url_for('empleados.panel_economico'))
    else:
        flash('No tienes permiso para acceder a este módulo.', 'danger')
        return redirect(url_for('home.index'))


@empleados_bp.route('/panel/empleado')
@login_required
def panel_empleado():
    empleado = get_empleado_actual()
    if not empleado:
        flash('No tienes un empleado asociado.', 'danger')
        return redirect(url_for('home.index'))

    periodo = get_periodo_actual()
    detalle = calcular_nomina_empleado(empleado.id, periodo.id)

    hoy = datetime.now().date()
    inicio_mes = hoy.replace(day=1)
    fin_mes = (inicio_mes + timedelta(days=32)).replace(day=1)
    asistencias_mes = empleado.get_asistencias_periodo(
        datetime.combine(inicio_mes, datetime.min.time()),
        datetime.combine(fin_mes, datetime.min.time())
    )
    horas_mes, salario_mes = calcular_horas_salario(asistencias_mes)

    manana = hoy + timedelta(days=1)
    asistencias_hoy = empleado.get_asistencias_periodo(
        datetime.combine(hoy, datetime.min.time()),
        datetime.combine(manana, datetime.min.time())
    )
    horas_hoy, salario_hoy = calcular_horas_salario(asistencias_hoy)

    historial_7d = []
    for i in range(6, -1, -1):
        dia = hoy - timedelta(days=i)
        dia_sig = dia + timedelta(days=1)
        asis_dia = empleado.get_asistencias_periodo(
            datetime.combine(dia, datetime.min.time()),
            datetime.combine(dia_sig, datetime.min.time())
        )
        h, _ = calcular_horas_salario(asis_dia)
        historial_7d.append({
            'fecha': dia.strftime('%a %d'),
            'horas': round(h, 2)
        })

    marcas_hoy = [{
        'tipo': a.tipo,
        'timestamp': a.timestamp,
        'hora': a.timestamp.strftime('%H:%M'),
        'fecha': a.timestamp.strftime('%d/%m'),
        'comentario': a.comentario or ''
    } for a in asistencias_hoy]

    estado = 'dentro' if marcas_hoy and marcas_hoy[-1]['tipo'] == 'entrada' else 'libre'
    jornada_actual = None
    if estado == 'dentro' and marcas_hoy:
        entrada_actual = marcas_hoy[-1]['timestamp']
        jornada_actual = str(datetime.now() - entrada_actual).split('.')[0]

    puede_ver_economico = current_user.role in ('economico', 'admin')

    return render_template('panel_empleado.html',
                           empleado=empleado,
                           periodo=periodo,
                           detalle=detalle,
                           horas_hoy=horas_hoy,
                           salario_hoy=salario_hoy,
                           horas_mes=horas_mes,
                           salario_mes=salario_mes,
                           historial_7d=json.dumps(historial_7d),
                           marcas_hoy=marcas_hoy,
                           estado=estado,
                           jornada_actual=jornada_actual,
                           puede_ver_economico=puede_ver_economico)


@empleados_bp.route('/panel/economico')
@login_required
def panel_economico():
    if current_user.role not in ('economico', 'admin'):
        flash('No tienes permiso para ver esta vista.', 'danger')
        return redirect(url_for('home.index'))

    periodo_filtro = request.args.get('periodo', 'semana_actual')
    empleado_id = request.args.get('empleado_id', type=int)
    view = request.args.get('view', 'dashboard')

    hoy = datetime.now().date()
    if periodo_filtro == 'semana_actual':
        dia = hoy.weekday()
        if dia >= 4:
            diff = dia - 4
        else:
            diff = dia + 3
        inicio = hoy - timedelta(days=diff)
        fin = inicio + timedelta(days=6)
    elif periodo_filtro == 'semana_pasada':
        inicio = hoy - timedelta(days=7)
        fin = hoy - timedelta(days=1)
    else:  # mes
        inicio = hoy.replace(day=1)
        fin = (inicio + timedelta(days=32)).replace(day=1) - timedelta(days=1)

    periodo = PeriodoNomina.query.filter_by(fecha_inicio=inicio, fecha_fin=fin).first()
    if not periodo:
        periodo = PeriodoNomina(fecha_inicio=inicio, fecha_fin=fin, estado='abierto')
        db.session.add(periodo)
        db.session.commit()

    empleados = Empleado.query.all()
    if empleado_id:
        empleados = [e for e in empleados if e.id == empleado_id]

    resumen = []
    for emp in empleados:
        detalle = calcular_nomina_empleado(emp.id, periodo.id)
        asistencias = emp.get_asistencias_periodo(inicio, fin)
        dias_trabajados = len(set([a.timestamp.date() for a in asistencias if a.tipo == 'entrada']))
        promedio = round(detalle.horas_totales / dias_trabajados, 2) if dias_trabajados > 0 else 0
        resumen.append({
            'empleado': emp,
            'detalle': detalle,
            'dias_trabajados': dias_trabajados,
            'promedio_diario': promedio
        })

    labels = [r['empleado'].user.username for r in resumen]
    values = [round(r['detalle'].horas_totales, 2) for r in resumen]

    # KPIs
    hoy_inicio = datetime.combine(hoy, datetime.min.time())
    hoy_fin = datetime.combine(hoy + timedelta(days=1), datetime.min.time())
    asistencias_hoy = Asistencia.query.filter(
        Asistencia.timestamp >= hoy_inicio,
        Asistencia.timestamp < hoy_fin
    ).all()
    empleados_activos_hoy = len(set([a.empleado_id for a in asistencias_hoy]))
    total_empleados = Empleado.query.count()
    ausentes_hoy = total_empleados - empleados_activos_hoy

    horas_hoy = 0.0
    for emp in empleados:
        asis_hoy = emp.get_asistencias_periodo(hoy_inicio, hoy_fin)
        h, _ = calcular_horas_salario(asis_hoy)
        horas_hoy += h

    evolucion_labels = []
    evolucion_values = []
    for i in range(6, -1, -1):
        dia = hoy - timedelta(days=i)
        dia_inicio = datetime.combine(dia, datetime.min.time())
        dia_fin = datetime.combine(dia + timedelta(days=1), datetime.min.time())
        total_dia = 0.0
        for emp in empleados:
            asis_dia = emp.get_asistencias_periodo(dia_inicio, dia_fin)
            h, _ = calcular_horas_salario(asis_dia)
            total_dia += h
        evolucion_labels.append(dia.strftime('%a %d'))
        evolucion_values.append(round(total_dia, 2))

    empleados_ausentes = []
    for emp in empleados:
        asis_hoy = emp.get_asistencias_periodo(hoy_inicio, hoy_fin)
        if not asis_hoy:
            empleados_ausentes.append(emp.user.username)

    # Datos para tabla de empleados
    empleados_list = []
    for emp in empleados:
        detalle = calcular_nomina_empleado(emp.id, periodo.id)
        asistencias_periodo = emp.get_asistencias_periodo(inicio, fin)
        dias_trabajados = len(set([a.timestamp.date() for a in asistencias_periodo if a.tipo == 'entrada']))
        empleados_list.append({
            'id': emp.id,
            'nombre': emp.user.username,
            'area': getattr(emp, 'area', None) or '',
            'horas': detalle.horas_totales,
            'salario': detalle.salario_bruto,
            'dias': dias_trabajados,
            'promedio': detalle.horas_totales / dias_trabajados if dias_trabajados > 0 else 0,
            'revisado': detalle.aprobado
        })

    # Áreas únicas para el filtro
    areas = sorted(set([getattr(emp, 'area', None) for emp in empleados if getattr(emp, 'area', None)]))

    empleado = get_empleado_actual()
    puede_ver_empleado = empleado is not None

    return render_template('panel_economico.html',
                           periodo=periodo,
                           resumen=resumen,
                           labels=json.dumps(labels),
                           values=json.dumps(values),
                           periodo_filtro=periodo_filtro,
                           empleado_seleccionado=empleado_id,
                           puede_ver_empleado=puede_ver_empleado,
                           view=view,
                           total_empleados=total_empleados,
                           empleados_activos_hoy=empleados_activos_hoy,
                           ausentes_hoy=ausentes_hoy,
                           horas_hoy=round(horas_hoy, 2),
                           evolucion_labels=json.dumps(evolucion_labels),
                           evolucion_values=json.dumps(evolucion_values),
                           empleados_ausentes=empleados_ausentes,
                           empleados_list=empleados_list,
                           areas=areas)


# ============================================================
#  RUTAS API
# ============================================================

@empleados_bp.route('/marcar', methods=['POST'])
@login_required
def marcar():
    if current_user.role not in ('operario', 'admin', 'disenador', 'disennador', 'comercial', 'economico'):
        return jsonify({'error': 'No autorizado'}), 403

    empleado = get_empleado_actual()
    if not empleado:
        return jsonify({'error': 'No tienes un empleado asociado.'}), 400

    data = request.get_json() or {}
    comentario = data.get('comentario', '').strip()

    hoy = datetime.now().date()
    ultima = Asistencia.query.filter(
        Asistencia.empleado_id == empleado.id,
        db.func.date(Asistencia.timestamp) == hoy
    ).order_by(Asistencia.timestamp.desc()).first()

    tipo = 'salida' if ultima and ultima.tipo == 'entrada' else 'entrada'
    nueva = Asistencia(empleado_id=empleado.id, tipo=tipo, timestamp=datetime.now(), comentario=comentario)
    db.session.add(nueva)
    db.session.commit()

    return jsonify({'success': True, 'tipo': tipo, 'hora': datetime.now().strftime('%H:%M')})


@empleados_bp.route('/api/detalle_completo/<int:empleado_id>')
@login_required
def detalle_completo(empleado_id):
    if current_user.role not in ('economico', 'admin'):
        return jsonify({'error': 'No autorizado'}), 403

    empleado = Empleado.query.get_or_404(empleado_id)
    hoy = datetime.now().date()
    inicio = hoy - timedelta(days=30)
    asistencias = empleado.get_asistencias_periodo(
        datetime.combine(inicio, datetime.min.time()),
        datetime.combine(hoy + timedelta(days=1), datetime.min.time())
    )

    data = []
    for a in asistencias:
        data.append({
            'tipo': a.tipo,
            'timestamp': a.timestamp.isoformat(),
            'hora': a.timestamp.strftime('%H:%M'),
            'fecha': a.timestamp.strftime('%d/%m/%Y'),
            'comentario': a.comentario or ''
        })
    return jsonify(data)


@empleados_bp.route('/api/aprobar', methods=['POST'])
@login_required
def aprobar_nomina():
    if current_user.role not in ('economico', 'admin'):
        return jsonify({'error': 'No autorizado'}), 403

    data = request.get_json()
    empleado_id = data.get('empleado_id')
    if not empleado_id:
        return jsonify({'error': 'Falta empleado_id'}), 400

    periodo = get_periodo_actual()
    detalle = DetalleNomina.query.filter_by(periodo_id=periodo.id, empleado_id=empleado_id).first()
    if not detalle:
        return jsonify({'error': 'No existe detalle de nómina para este empleado'}), 404

    detalle.aprobado = True
    detalle.fecha_aprobacion = datetime.now()
    db.session.commit()
    return jsonify({'success': True, 'empleado_id': empleado_id, 'aprobado': True})


@empleados_bp.route('/api/exportar')
@login_required
def exportar():
    if current_user.role not in ('economico', 'admin'):
        return jsonify({'error': 'No autorizado'}), 403

    periodo = get_periodo_actual()
    empleados = Empleado.query.all()
    lines = ['Empleado,Horas,Salario,Aprobado']
    for emp in empleados:
        detalle = calcular_nomina_empleado(emp.id, periodo.id)
        lines.append(f'{emp.user.username},{detalle.horas_totales:.2f},{detalle.salario_bruto:.2f},{"Sí" if detalle.aprobado else "No"}')

    csv_data = '\n'.join(lines)
    return csv_data, 200, {
        'Content-Type': 'text/csv',
        'Content-Disposition': f'attachment; filename=nomina_{periodo.fecha_inicio}_a_{periodo.fecha_fin}.csv'
    }


@empleados_bp.route('/api/recalcular', methods=['POST'])
@login_required
def recalcular_nomina():
    if current_user.role not in ('economico', 'admin'):
        return jsonify({'error': 'No autorizado'}), 403

    data = request.get_json() or {}
    periodo_filtro = data.get('periodo', 'semana_actual')

    hoy = datetime.now().date()
    if periodo_filtro == 'semana_actual':
        dia = hoy.weekday()
        if dia >= 4:
            diff = dia - 4
        else:
            diff = dia + 3
        inicio = hoy - timedelta(days=diff)
        fin = inicio + timedelta(days=6)
    elif periodo_filtro == 'semana_pasada':
        inicio = hoy - timedelta(days=7)
        fin = hoy - timedelta(days=1)
    else:  # mes
        inicio = hoy.replace(day=1)
        fin = (inicio + timedelta(days=32)).replace(day=1) - timedelta(days=1)

    periodo = PeriodoNomina.query.filter_by(fecha_inicio=inicio, fecha_fin=fin).first()
    if not periodo:
        periodo = PeriodoNomina(fecha_inicio=inicio, fecha_fin=fin, estado='abierto')
        db.session.add(periodo)
        db.session.commit()

    empleados = Empleado.query.all()
    for emp in empleados:
        calcular_nomina_empleado(emp.id, periodo.id)

    return jsonify({'success': True, 'periodo': periodo_filtro})


@empleados_bp.route('/api/empleados/asignar-area', methods=['POST'])
@login_required
def asignar_area():
    if current_user.role not in ('economico', 'admin'):
        return jsonify({'error': 'No autorizado'}), 403
    data = request.get_json()
    empleado_id = data.get('empleado_id')
    area = data.get('area', '').strip()
    if not empleado_id:
        return jsonify({'error': 'Falta empleado_id'}), 400
    empleado = Empleado.query.get_or_404(empleado_id)
    empleado.area = area if area else None
    db.session.commit()
    return jsonify({'success': True})


# ============================================================
#  FUNCIÓN PARA CREAR EMPLEADOS (desde consola)
# ============================================================
def create_empleado(username):
    user = User.query.filter_by(username=username).first()
    if not user:
        print(f'Usuario {username} no encontrado.')
        return
    if user.role not in ('operario', 'admin', 'disenador', 'disennador', 'comercial', 'economico'):
        print(f'El usuario {username} debe tener un rol válido.')
        return
    empleado = Empleado.query.filter_by(user_id=user.id).first()
    if empleado:
        print(f'El usuario {username} ya es un empleado.')
        return
    empleado = Empleado(user_id=user.id)
    db.session.add(empleado)
    db.session.commit()
    print(f'✅ Empleado {username} creado correctamente.')