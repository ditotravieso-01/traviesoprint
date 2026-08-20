from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import login_required, current_user
from app import db
from app.models import User, Empleado, Asistencia, PeriodoNomina, DetalleNomina
from datetime import datetime, timedelta
import json

empleados_bp = Blueprint('empleados', __name__, url_prefix='/empleados', template_folder='templates')


# ============================================================
#  FUNCIONES AUXILIARES (reutilizan la lógica de la demo)
# ============================================================

TARIFA_NORMAL = 1.00
TARIFA_NOCTURNA = 1.30
TARIFA_FIN_SEMANA = 1.50
INICIO_NOCTURNO = 18.0

def es_fin_semana(fecha):
    return fecha.weekday() in (5, 6)  # sábado=5, domingo=6

def calcular_pago_dia(entrada, salida):
    """entrada y salida son objetos datetime."""
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
    """Recibe una lista de objetos Asistencia ordenados por timestamp.
       Devuelve (horas_totales, salario_bruto).
    """
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
    """Retorna el objeto Empleado del usuario autenticado, o None si no existe."""
    if current_user.role != 'empleado':
        return None
    empleado = Empleado.query.filter_by(user_id=current_user.id).first()
    return empleado


def get_periodo_actual():
    """Retorna el periodo de nómina actual (crea uno si no existe)."""
    return PeriodoNomina.crear_periodo_actual()


def calcular_nomina_empleado(empleado_id, periodo_id):
    """Calcula las horas y salario de un empleado en un periodo y guarda/actualiza el detalle."""
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
    """Redirige según el rol del usuario."""
    if current_user.role == 'empleado':
        return redirect(url_for('empleados.panel_empleado'))
    elif current_user.role in ('economico', 'admin'):
        return redirect(url_for('empleados.panel_economico'))
    else:
        flash('No tienes permiso para acceder a este módulo.', 'danger')
        return redirect(url_for('home.index'))


@empleados_bp.route('/fichar', methods=['GET', 'POST'])
@login_required
def fichar():
    """Página para fichar entrada/salida (accesible desde móvil)."""
    if current_user.role != 'empleado':
        flash('Solo los empleados pueden fichar.', 'danger')
        return redirect(url_for('empleados.index'))

    empleado = get_empleado_actual()
    if not empleado:
        flash('Tu usuario no está asociado a un empleado. Contacta con el administrador.', 'danger')
        return redirect(url_for('home.index'))

    if request.method == 'POST':
        # Obtener última marca del día
        hoy = datetime.utcnow().date()
        ultima = Asistencia.query.filter(
            Asistencia.empleado_id == empleado.id,
            db.func.date(Asistencia.timestamp) == hoy
        ).order_by(Asistencia.timestamp.desc()).first()

        tipo = 'salida' if ultima and ultima.tipo == 'entrada' else 'entrada'
        nueva = Asistencia(empleado_id=empleado.id, tipo=tipo, timestamp=datetime.utcnow())
        db.session.add(nueva)
        db.session.commit()

        flash(f'✅ {tipo.capitalize()} registrada a las {datetime.utcnow().strftime("%H:%M")}', 'success')
        return redirect(url_for('empleados.fichar'))

    # GET: mostrar página para fichar
    return render_template('empleado/fichar.html', empleado=empleado)


@empleados_bp.route('/panel/empleado')
@login_required
def panel_empleado():
    """Panel del empleado: resumen de hoy y semana actual."""
    if current_user.role != 'empleado':
        flash('Acceso denegado.', 'danger')
        return redirect(url_for('empleados.index'))

    empleado = get_empleado_actual()
    if not empleado:
        flash('Tu usuario no está asociado a un empleado.', 'danger')
        return redirect(url_for('home.index'))

    periodo = get_periodo_actual()
    # Calcular nómina actual (si no existe, se calcula)
    detalle = calcular_nomina_empleado(empleado.id, periodo.id)

    # Asistencias de hoy
    hoy = datetime.utcnow().date()
    manana = hoy + timedelta(days=1)
    asistencias_hoy = empleado.get_asistencias_periodo(
        datetime.combine(hoy, datetime.min.time()),
        datetime.combine(manana, datetime.min.time())
    )

    # Calcular horas de hoy
    horas_hoy, salario_hoy = calcular_horas_salario(asistencias_hoy)

    # Historial de marcas de hoy (para mostrar lista)
    marcas_hoy = [{
        'tipo': a.tipo,
        'timestamp': a.timestamp,
        'hora': a.timestamp.strftime('%H:%M'),
        'fecha': a.timestamp.strftime('%d/%m')
    } for a in asistencias_hoy]

    return render_template('empleado/panel.html',
                           empleado=empleado,
                           periodo=periodo,
                           detalle=detalle,
                           horas_hoy=horas_hoy,
                           salario_hoy=salario_hoy,
                           marcas_hoy=marcas_hoy)


@empleados_bp.route('/panel/economico')
@login_required
def panel_economico():
    """Panel del económico: resumen de todos los empleados y aprobación."""
    if current_user.role not in ('economico', 'admin'):
        flash('Acceso denegado.', 'danger')
        return redirect(url_for('empleados.index'))

    periodo = get_periodo_actual()

    # Obtener todos los empleados con sus detalles de nómina
    empleados = Empleado.query.all()
    resumen = []
    for emp in empleados:
        detalle = calcular_nomina_empleado(emp.id, periodo.id)
        resumen.append({
            'empleado': emp,
            'detalle': detalle
        })

    return render_template('economico/panel.html',
                           periodo=periodo,
                           resumen=resumen)


@empleados_bp.route('/api/aprobar', methods=['POST'])
@login_required
def aprobar_nomina():
    """Aprobar el detalle de nómina de un empleado para el periodo actual."""
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
    detalle.fecha_aprobacion = datetime.utcnow()
    db.session.commit()
    return jsonify({'success': True, 'empleado_id': empleado_id, 'aprobado': True})


@empleados_bp.route('/api/detalle/<int:empleado_id>')
@login_required
def detalle_empleado(empleado_id):
    """Devuelve las asistencias de un empleado en el periodo actual (para el económico)."""
    if current_user.role not in ('economico', 'admin'):
        return jsonify({'error': 'No autorizado'}), 403

    empleado = Empleado.query.get_or_404(empleado_id)
    periodo = get_periodo_actual()
    asistencias = empleado.get_asistencias_periodo(periodo.fecha_inicio, periodo.fecha_fin)

    data = []
    for a in asistencias:
        data.append({
            'tipo': a.tipo,
            'timestamp': a.timestamp.isoformat(),
            'hora': a.timestamp.strftime('%H:%M'),
            'fecha': a.timestamp.strftime('%d/%m/%Y')
        })
    return jsonify(data)


@empleados_bp.route('/api/exportar')
@login_required
def exportar():
    """Exportar resumen semanal a CSV (ejemplo)."""
    if current_user.role not in ('economico', 'admin'):
        return jsonify({'error': 'No autorizado'}), 403

    periodo = get_periodo_actual()
    empleados = Empleado.query.all()
    lines = []
    lines.append('Empleado,Horas,Salario,Aprobado')
    for emp in empleados:
        detalle = calcular_nomina_empleado(emp.id, periodo.id)
        lines.append(f'{emp.user.username},{detalle.horas_totales:.2f},{detalle.salario_bruto:.2f},{"Sí" if detalle.aprobado else "No"}')

    csv_data = '\n'.join(lines)
    return csv_data, 200, {
        'Content-Type': 'text/csv',
        'Content-Disposition': f'attachment; filename=nomina_{periodo.fecha_inicio}_a_{periodo.fecha_fin}.csv'
    }


# ============================================================
#  FUNCIÓN PARA CREAR EMPLEADOS DESDE LA CONSOLA (opcional)
# ============================================================
def create_empleado(username):
    """Asocia un usuario existente a un empleado (para usar desde flask shell)."""
    user = User.query.filter_by(username=username).first()
    if not user:
        print(f'Usuario {username} no encontrado.')
        return
    if user.role != 'empleado':
        print(f'El usuario {username} no tiene rol "empleado".')
        return
    empleado = Empleado.query.filter_by(user_id=user.id).first()
    if empleado:
        print(f'El usuario {username} ya es un empleado.')
        return
    empleado = Empleado(user_id=user.id)
    db.session.add(empleado)
    db.session.commit()
    print(f'✅ Empleado {username} creado correctamente.')