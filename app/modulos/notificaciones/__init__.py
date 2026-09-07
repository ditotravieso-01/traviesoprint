from flask import Blueprint, jsonify, request, render_template
from flask_login import login_required, current_user
from app.models import Notificacion, db

# ===== ESPECIFICAMOS template_folder para que busque en su propia carpeta =====
notificaciones_bp = Blueprint('notificaciones', __name__, url_prefix='/notificaciones', template_folder='templates')

@notificaciones_bp.route('/contar')
@login_required
def contar():
    total = Notificacion.query.filter_by(usuario_id=current_user.id, leida=False).count()
    return jsonify({'total': total})

@notificaciones_bp.route('/lista')
@login_required
def lista():
    notifs = Notificacion.query.filter_by(usuario_id=current_user.id).order_by(Notificacion.fecha_creacion.desc()).limit(20).all()
    data = [{
        'id': n.id,
        'mensaje': n.mensaje,
        'fecha': n.fecha_creacion.strftime('%d/%m/%Y %H:%M'),
        'leida': n.leida,
        'enlace': n.enlace
    } for n in notifs]
    return jsonify(data)

@notificaciones_bp.route('/marcar-leida/<int:notif_id>', methods=['POST'])
@login_required
def marcar_leida(notif_id):
    notif = Notificacion.query.get_or_404(notif_id)
    if notif.usuario_id != current_user.id:
        return jsonify({'error': 'No autorizado'}), 403
    notif.leida = True
    db.session.commit()
    return jsonify({'success': True})

@notificaciones_bp.route('/marcar-todas-leidas', methods=['POST'])
@login_required
def marcar_todas_leidas():
    Notificacion.query.filter_by(usuario_id=current_user.id, leida=False).update({'leida': True})
    db.session.commit()
    return jsonify({'success': True})

# ===== NUEVA RUTA: HISTORIAL =====
@notificaciones_bp.route('/historial')
@login_required
def historial():
    page = request.args.get('page', 1, type=int)
    filtro = request.args.get('filtro', 'todas')  # 'leidas', 'no_leidas', 'todas'
    per_page = 20

    query = Notificacion.query.filter_by(usuario_id=current_user.id)
    
    if filtro == 'leidas':
        query = query.filter_by(leida=True)
    elif filtro == 'no_leidas':
        query = query.filter_by(leida=False)
    
    paginacion = query.order_by(Notificacion.fecha_creacion.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    
    return render_template('historial_notificaciones.html',
                           notificaciones=paginacion.items,
                           paginacion=paginacion,
                           filtro_actual=filtro)