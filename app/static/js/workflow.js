$(document).ready(function() {
    console.log('🚀 Workflow JS iniciado');

    function inicializarSortable() {
        const columnas = document.querySelectorAll('.card-list');
        console.log(`📋 Columnas encontradas: ${columnas.length}`);
        columnas.forEach(col => {
            new Sortable(col, {
                group: 'kanban',
                animation: 150,
                easing: 'cubic-bezier(0.4, 0, 0.2, 1)',
                onEnd: function(evt) {
                    console.log('🔄 Tarjeta arrastrada');
                    const item = evt.item;
                    const orderId = item.dataset.id;
                    const nuevaColumna = evt.to.closest('.board-column').dataset.columna;
                    console.log(`📦 Orden ${orderId} → ${nuevaColumna}`);
                    // Actualizar contadores
                    const colOrigen = evt.from.closest('.board-column');
                    const colDestino = evt.to.closest('.board-column');
                    actualizarContador(colOrigen.dataset.columna);
                    actualizarContador(colDestino.dataset.columna);
                    moverTarjeta(orderId, nuevaColumna);
                }
            });
        });
    }

    function moverTarjeta(orderId, columna) {
        console.log(`📤 Enviando movimiento: orden ${orderId} a ${columna}`);
        $.ajax({
            url: '/workflow/mover/' + orderId,
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ columna: columna }),
            success: function(response) {
                console.log('✅ Respuesta:', response);
                if (response.success) {
                    mostrarNotificacion('✅ ' + response.mensaje);
                } else {
                    alert('❌ Error: ' + response.error);
                    recargarTablero();
                }
            },
            error: function(xhr, status, error) {
                console.error('❌ Error en la petición:', status, error);
                console.log('📄 Respuesta del servidor:', xhr.responseText);
                alert('❌ Error al mover la orden. Recargando...');
                recargarTablero();
            }
        });
    }

    window.moverSiguiente = function(orderId) {
        console.log(`➡️ Botón "Hecho" para orden ${orderId}`);
        $.ajax({
            url: '/workflow/siguiente/' + orderId,
            method: 'POST',
            contentType: 'application/json',
            success: function(response) {
                console.log('✅ Respuesta:', response);
                if (response.success) {
                    mostrarNotificacion('✅ ' + response.mensaje);
                    recargarTablero();
                } else {
                    alert('❌ Error: ' + response.error);
                }
            },
            error: function(xhr, status, error) {
                console.error('❌ Error en la petición:', status, error);
                console.log('📄 Respuesta del servidor:', xhr.responseText);
                alert('❌ Error al avanzar la orden.');
            }
        });
    };

    window.recargarTablero = function() {
        console.log('🔄 Recargando tablero...');
        const url = window.location.href;
        $.get(url, function(data) {
            const nuevoContenido = $(data).find('.board-container').html();
            $('.board-container').html(nuevoContenido);
            inicializarSortable();
            // Actualizar contadores
            const columnas = document.querySelectorAll('.board-column');
            columnas.forEach(col => {
                const colName = col.dataset.columna;
                actualizarContador(colName);
            });
            const ahora = new Date().toLocaleTimeString();
            $('#ultima-actualizacion').text('Última actualización: ' + ahora);
        });
    };

    function actualizarContador(columna) {
        const list = document.getElementById('list-' + columna);
        const count = list ? list.children.length : 0;
        const badge = document.getElementById('count-' + columna);
        if (badge) badge.textContent = count;
    }

    function mostrarNotificacion(mensaje) {
        const notif = $('<div>', {
            text: mensaje,
            css: {
                position: 'fixed',
                bottom: '20px',
                right: '20px',
                background: '#10b981',
                color: 'white',
                padding: '10px 20px',
                borderRadius: '8px',
                boxShadow: '0 4px 12px rgba(0,0,0,0.1)',
                zIndex: 9999,
                fontSize: '14px'
            }
        });
        $('body').append(notif);
        setTimeout(() => {
            notif.fadeOut(500, function() { $(this).remove(); });
        }, 3000);
    }

    // Inicializar
    inicializarSortable();
    // Actualizar contadores iniciales
    document.querySelectorAll('.board-column').forEach(col => {
        actualizarContador(col.dataset.columna);
    });

    // Polling cada 30 segundos
    setInterval(recargarTablero, 30000);
});