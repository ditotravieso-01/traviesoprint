$(document).ready(function() {
    function actualizarContador() {
        $.get('/notificaciones/contar')
            .done(function(data) {
                if (data.total > 0) {
                    $('#notificaciones-contador').text(data.total).show();
                } else {
                    $('#notificaciones-contador').hide();
                }
            })
            .fail(function() {
                console.error('Error al obtener contador de notificaciones');
            });
    }

    function cargarLista() {
        $('#lista-notificaciones').html('<span class="dropdown-item-text">Cargando...</span>');
        $.get('/notificaciones/lista')
            .done(function(data) {
                var html = '';
                if (data.length === 0) {
                    html = '<span class="dropdown-item-text" style="color:#888;">No hay notificaciones</span>';
                } else {
                    $.each(data, function(i, notif) {
                        var leida = notif.leida ? '' : '<strong>•</strong> ';
                        var enlace = notif.enlace ? notif.enlace : '#';
                        var estilo = notif.leida ? '' : 'font-weight: bold;';
                        html += '<a class="dropdown-item" href="'+enlace+'" onclick="marcarLeida('+notif.id+')" style="'+estilo+' display: block; padding: 8px 16px; color: #333; text-decoration: none; border-bottom: 1px solid #f0ece8;">'
                            + leida + notif.mensaje + ' <small class="text-muted" style="color:#999;">'+notif.fecha+'</small></a>';
                    });
                }
                $('#lista-notificaciones').html(html);
            })
            .fail(function() {
                $('#lista-notificaciones').html('<span class="dropdown-item-text" style="color:#dc2626;">Error al cargar notificaciones</span>');
                console.error('Error al cargar lista de notificaciones');
            });
    }

    window.marcarLeida = function(id) {
        $.post('/notificaciones/marcar-leida/'+id)
            .done(function() {
                actualizarContador();
                cargarLista();
            })
            .fail(function() {
                console.error('Error al marcar notificación como leída');
            });
    }

    $('#marcar-todas-leidas').click(function(e) {
        e.preventDefault();
        $.post('/notificaciones/marcar-todas-leidas')
            .done(function() {
                actualizarContador();
                cargarLista();
            })
            .fail(function() {
                console.error('Error al marcar todas como leídas');
            });
    });

    // Al abrir el dropdown, cargar la lista
    $('#notificacionesDropdown').click(function(e) {
        e.preventDefault();
        cargarLista();
    });

    // Actualizar contador cada 30 segundos
    setInterval(actualizarContador, 30000);
    actualizarContador();
});