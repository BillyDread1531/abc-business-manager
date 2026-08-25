
from database import obtener_conexion
from decimal import Decimal
import os
import uuid
from flask import Blueprint, render_template, request, redirect, url_for, flash


pedidos_bp = Blueprint(
    "pedidos",
    __name__,
    url_prefix="/pedidos"
)


# ============================================================
# COSTO ESTIMADO DE PRODUCCIÓN EXTERNA
# ============================================================

def calcular_costo_externo_estimado(
    producto,
    cantidad,
    ancho=None,
    alto=None,
    largo=None
):

    if not producto:
        return Decimal("0.00")

    if producto.get("metodo_produccion") != "EXTERNA":
        return Decimal("0.00")

    costo_ref = Decimal(
        str(
            producto.get(
                "costo_externo_referencia",
                0
            )
            or 0
        )
    )

    cantidad_dec = Decimal(
        str(cantidad or 0)
    )

    tipo_calculo = (
        producto.get("tipo_calculo_precio")
        or "FIJO"
    ).strip().upper()

    if costo_ref <= 0 or cantidad_dec <= 0:
        return Decimal("0.00")

    if tipo_calculo == "M2":

        ancho_dec = Decimal(str(ancho or 0))
        alto_dec = Decimal(str(alto or 0))

        if ancho_dec <= 0 or alto_dec <= 0:
            return Decimal("0.00")

        area_m2 = (
            ancho_dec
            * alto_dec
            / Decimal("10000")
        )

        return (
            area_m2
            * costo_ref
            * cantidad_dec
        )

    if tipo_calculo == "METRO_LINEAL":

        largo_dec = Decimal(str(largo or 0))

        if largo_dec <= 0:
            return Decimal("0.00")

        metros = (
            largo_dec
            / Decimal("100")
        )

        return (
            metros
            * costo_ref
            * cantidad_dec
        )

    return (
        costo_ref
        * cantidad_dec
    )


# ============================================================
# RECALCULAR TOTALES DEL PEDIDO
# ============================================================

def recalcular_totales_pedido(cursor, pedido_id):
    """
    Recalcula el resumen del pedido usando los detalles:

    subtotal  = suma antes de descuentos
    descuento = suma de descuentos de las líneas
    total     = subtotal - descuento
    """

    cursor.execute("""
        SELECT
            COALESCE(
                SUM(cantidad * precio_unitario),
                0
            ) AS subtotal_bruto,

            COALESCE(
                SUM(descuento),
                0
            ) AS descuento_total

        FROM detalle_pedido

        WHERE pedido_id = %s
    """, (pedido_id,))

    resumen = cursor.fetchone() or {}

    subtotal_bruto = Decimal(
        str(
            resumen.get("subtotal_bruto", 0)
            or 0
        )
    )

    descuento_total = Decimal(
        str(
            resumen.get("descuento_total", 0)
            or 0
        )
    )

    if descuento_total < 0:
        descuento_total = Decimal("0.00")

    if descuento_total > subtotal_bruto:
        descuento_total = subtotal_bruto

    total = (
        subtotal_bruto
        - descuento_total
    )

    cursor.execute("""
        UPDATE pedidos
        SET
            subtotal = %s,
            descuento = %s,
            total = %s
        WHERE id = %s
    """, (
        subtotal_bruto,
        descuento_total,
        total,
        pedido_id
    ))

    return (
        subtotal_bruto,
        descuento_total,
        total
    )


@pedidos_bp.route("/")
def listar():

    busqueda = request.args.get("q", "").strip()

    conexion = obtener_conexion()
    cursor = conexion.cursor(dictionary=True)

    if busqueda:

        cursor.execute("""
            SELECT
                p.id,
                p.numero,
                p.fecha,
                p.fecha_entrega,
                p.subtotal,
                p.descuento,
                p.total,
                p.estado,
                c.id AS cliente_id,
                c.nombre AS cliente,

                COALESCE(
                    SUM(pg.monto),
                    0
                ) AS total_pagado

            FROM pedidos p

            INNER JOIN clientes c
                ON p.cliente_id = c.id

            LEFT JOIN pagos pg
                ON pg.pedido_id = p.id

            WHERE c.nombre LIKE %s
               OR p.numero LIKE %s

            GROUP BY
                p.id,
                p.numero,
                p.fecha,
                p.fecha_entrega,
                p.subtotal,
                p.descuento,
                p.total,
                p.estado,
                c.id,
                c.nombre

            ORDER BY p.fecha DESC

        """, (
            f"%{busqueda}%",
            f"%{busqueda}%"
        ))

    else:

        cursor.execute("""
            SELECT
                p.id,
                p.numero,
                p.fecha,
                p.fecha_entrega,
                p.subtotal,
                p.descuento,
                p.total,
                p.estado,
                c.id AS cliente_id,
                c.nombre AS cliente,

                COALESCE(
                    SUM(pg.monto),
                    0
                ) AS total_pagado

            FROM pedidos p

            INNER JOIN clientes c
                ON p.cliente_id = c.id

            LEFT JOIN pagos pg
                ON pg.pedido_id = p.id

            GROUP BY
                p.id,
                p.numero,
                p.fecha,
                p.fecha_entrega,
                p.subtotal,
                p.descuento,
                p.total,
                p.estado,
                c.nombre

            ORDER BY p.fecha DESC

        """)

    pedidos = cursor.fetchall()

    cursor.close()
    conexion.close()

    return render_template(
        "pedidos/lista.html",
        pedidos=pedidos,
        busqueda=busqueda
    )

@pedidos_bp.route("/nuevo", methods=["GET", "POST"])
def nuevo():

    conexion = obtener_conexion()
    cursor = conexion.cursor(dictionary=True)

    if request.method == "POST":

        try:

            cliente_id = request.form["cliente_id"]
            fecha_entrega = request.form.get("fecha_entrega") or None
            notas = request.form.get("notas", "").strip()

            usuario_id = 8

            # ------------------------------------------------
            # Prefijo configurado para nuevos pedidos
            # ------------------------------------------------

            cursor.execute("""
                SELECT prefijo_pedido
                FROM configuracion_negocio
                ORDER BY id ASC
                LIMIT 1
            """)

            configuracion = cursor.fetchone()

            prefijo_pedido = (
                configuracion["prefijo_pedido"]
                if configuracion
                and configuracion["prefijo_pedido"]
                else "PED-"
            )

            # Usamos el siguiente ID global para conservar
            # la numeración que ya maneja el sistema.
            cursor.execute("""
                SELECT id
                FROM pedidos
                ORDER BY id DESC
                LIMIT 1
            """)

            ultimo = cursor.fetchone()

            siguiente = ultimo["id"] + 1 if ultimo else 1

            numero = f"{prefijo_pedido}{siguiente:04d}"

            cursor.execute("""
                INSERT INTO pedidos
                (
                    numero,
                    cliente_id,
                    usuario_id,
                    fecha_entrega,
                    notas
                )
                VALUES (%s, %s, %s, %s, %s)
            """, (
                numero,
                cliente_id,
                usuario_id,
                fecha_entrega,
                notas
            ))

            conexion.commit()

            pedido_id = cursor.lastrowid

            cursor.close()
            conexion.close()

            return redirect(
                url_for(
                    "pedidos.detalle",
                    pedido_id=pedido_id
                )
            )

        except Exception:

            conexion.rollback()
            cursor.close()
            conexion.close()

            raise

    cursor.execute("""
        SELECT
            c.id,
            c.nombre,
            c.telefono,
            c.email,

            (
                SELECT COUNT(*)
                FROM pedidos p
                WHERE p.cliente_id = c.id
            ) AS total_pedidos,

            GREATEST(
                (
                    SELECT COALESCE(SUM(p.total), 0)
                    FROM pedidos p
                    WHERE p.cliente_id = c.id
                      AND p.estado != 'CANCELADO'
                )
                -
                (
                    SELECT COALESCE(SUM(pg.monto), 0)
                    FROM pagos pg
                    INNER JOIN pedidos p2
                        ON pg.pedido_id = p2.id
                    WHERE p2.cliente_id = c.id
                      AND p2.estado != 'CANCELADO'
                ),
                0
            ) AS saldo_pendiente

        FROM clientes c
        WHERE c.activo = 1
        ORDER BY c.nombre ASC
    """)

    clientes = cursor.fetchall()

    cursor.close()
    conexion.close()

    return render_template(
        "pedidos/nuevo.html",
        clientes=clientes
    )


@pedidos_bp.route("/<int:pedido_id>")
def detalle(pedido_id):

    conexion = obtener_conexion()
    cursor = conexion.cursor(dictionary=True)

    # ========================================================
    # PEDIDO
    # ========================================================

    cursor.execute("""
        SELECT
            p.*,
            c.nombre AS cliente,
            c.telefono,
            c.email
        FROM pedidos p
        INNER JOIN clientes c
            ON p.cliente_id = c.id
        WHERE p.id = %s
    """, (pedido_id,))

    pedido = cursor.fetchone()

    if not pedido:

        cursor.close()
        conexion.close()

        return "Pedido no encontrado", 404

    # ========================================================
    # PRODUCTOS + PRODUCCIÓN + COSTOS
    # ========================================================

    cursor.execute("""
        SELECT
            d.*,

            pr.nombre AS producto,
            pr.metodo_produccion,

            v.nombre AS variante,
            v.sku AS variante_sku,
            v.talla AS variante_talla,
            v.color AS variante_color,

            prod.id AS produccion_id,
            prod.tipo AS produccion_tipo,
            prod.estado AS produccion_estado,
            prod.costo_estimado AS produccion_costo_estimado,
            prod.costo_real AS produccion_costo_real

        FROM detalle_pedido d

        INNER JOIN productos pr
            ON d.producto_id = pr.id

        LEFT JOIN variantes_producto v
            ON d.variante_id = v.id

        LEFT JOIN producciones prod
            ON prod.detalle_pedido_id = d.id
            AND prod.estado != 'CANCELADO'

        WHERE d.pedido_id = %s

        ORDER BY d.id ASC
    """, (pedido_id,))

    detalles = cursor.fetchall()

    # ========================================================
    # RENTABILIDAD POR DETALLE
    # ========================================================

    subtotal_pedido = Decimal(
        str(
            pedido["subtotal"]
            or 0
        )
    )

    descuento_pedido = Decimal(
        str(
            pedido["descuento"]
            or 0
        )
    )

    total_venta = Decimal(
        str(
            pedido["total"]
            or 0
        )
    )

    costo_estimado_total = Decimal("0.00")
    costo_real_conocido = Decimal("0.00")

    detalles_con_costo_real = 0

    for detalle_item in detalles:

        subtotal_detalle = Decimal(
            str(
                detalle_item["subtotal"]
                or 0
            )
        )

        costo_estimado = Decimal(
            str(
                detalle_item["costo_estimado"]
                or 0
            )
        )

        costo_estimado_total += costo_estimado

        # ----------------------------------------------------
        # Descuento real de ESTA línea del pedido.
        # ----------------------------------------------------

        descuento_asignado = Decimal(
            str(
                detalle_item.get(
                    "descuento",
                    0
                )
                or 0
            )
        )

        if descuento_asignado < 0:
            descuento_asignado = Decimal("0.00")

        if descuento_asignado > subtotal_detalle:
            descuento_asignado = subtotal_detalle

        venta_neta = (
            subtotal_detalle
            - descuento_asignado
        )

        detalle_item["descuento_asignado"] = (
            descuento_asignado
        )

        detalle_item["venta_neta"] = venta_neta

        # El costo real definitivo vive en detalle_pedido.
        # Si todavía no existe, NO mostramos Q0 como si fuera
        # un costo conocido.
        costo_real = detalle_item["costo_real"]

        if costo_real is not None:

            costo_real_decimal = Decimal(
                str(costo_real)
            )

            costo_real_conocido += (
                costo_real_decimal
            )

            detalles_con_costo_real += 1

            ganancia_neta = (
                venta_neta
                - costo_real_decimal
            )

            margen = (
                ganancia_neta
                / venta_neta
                * Decimal("100")
                if venta_neta > 0
                else Decimal("0")
            )

            detalle_item["ganancia_neta"] = (
                ganancia_neta
            )

            detalle_item["margen_neto"] = margen

        else:

            detalle_item["ganancia_neta"] = None
            detalle_item["margen_neto"] = None

    costos_completos = (
        len(detalles) > 0
        and detalles_con_costo_real
        == len(detalles)
    )

    # ========================================================
    # COSTOS ESTIMADOS PENDIENTES
    # ========================================================
    # Se usa en pedidos/detalle.html para mostrar una advertencia
    # cuando todavía hay productos cuyo costo estimado no está
    # disponible o sigue en cero.
    #
    # Un pedido sin productos debe quedar en 0 para que pueda
    # abrirse normalmente y luego agregar sus productos.
    # ========================================================

    costos_estimados_pendientes = sum(
        1
        for detalle_item in detalles
        if (
            detalle_item.get("costo_estimado") is None
            or Decimal(
                str(
                    detalle_item.get(
                        "costo_estimado",
                        0
                    )
                    or 0
                )
            ) <= Decimal("0.00")
        )
    )

    if costos_completos:

        ganancia_real_pedido = (
            total_venta
            - costo_real_conocido
        )

        margen_real_pedido = (
            ganancia_real_pedido
            / total_venta
            * Decimal("100")
            if total_venta > 0
            else Decimal("0")
        )

    else:

        ganancia_real_pedido = None
        margen_real_pedido = None

    # ========================================================
    # PAGOS DEL PEDIDO
    # ========================================================

    cursor.execute("""
        SELECT
            p.id,
            p.fecha,
            p.monto,
            p.metodo_pago,
            p.referencia,
            p.notas
        FROM pagos p
        WHERE p.pedido_id = %s
        ORDER BY p.fecha DESC
    """, (pedido_id,))

    pagos = cursor.fetchall()

    # Obtener comprobantes de cada pago
    for pago in pagos:

        cursor.execute("""
            SELECT
                id,
                nombre_original,
                ruta,
                tipo_archivo,
                tamano_bytes,
                fecha_subida
            FROM comprobantes_pago
            WHERE pago_id = %s
            ORDER BY fecha_subida DESC
        """, (pago["id"],))

        pago["comprobantes"] = (
            cursor.fetchall()
        )

    total_pagado = sum(
        (
            Decimal(
                str(
                    pago["monto"]
                    or 0
                )
            )
            for pago in pagos
        ),
        Decimal("0.00")
    )

    saldo_pendiente = (
        total_venta
        - total_pagado
    )

    if saldo_pendiente < 0:
        saldo_pendiente = Decimal("0.00")

    cursor.close()
    conexion.close()

    return render_template(
        "pedidos/detalle.html",

        pedido=pedido,
        detalles=detalles,

        pagos=pagos,
        total_pagado=total_pagado,
        saldo_pendiente=saldo_pendiente,

        costo_estimado_total=costo_estimado_total,
        costo_real_conocido=costo_real_conocido,
        costos_completos=costos_completos,
        costos_estimados_pendientes=costos_estimados_pendientes,
        ganancia_real_pedido=ganancia_real_pedido,
        margen_real_pedido=margen_real_pedido
    )


# ============================================================
# COTIZACIÓN DEL PEDIDO
# ============================================================

@pedidos_bp.route("/<int:pedido_id>/cotizacion")
def cotizacion(pedido_id):

    conexion = obtener_conexion()
    cursor = conexion.cursor(dictionary=True)

    try:

        cursor.execute("""
            SELECT
                p.*,
                c.nombre AS cliente,
                c.telefono AS cliente_telefono,
                c.email AS cliente_email,
                c.direccion AS cliente_direccion
            FROM pedidos p
            INNER JOIN clientes c
                ON p.cliente_id = c.id
            WHERE p.id = %s
        """, (pedido_id,))

        pedido = cursor.fetchone()

        if not pedido:
            return "Pedido no encontrado", 404

        cursor.execute("""
            SELECT
                d.id,
                d.producto_id,
                d.variante_id,
                d.cantidad,
                d.precio_unitario,
                d.descuento,
                d.subtotal,
                d.texto_personalizado,
                d.ancho,
                d.alto,
                d.largo,
                d.notas,
                pr.nombre AS producto,
                v.nombre AS variante,
                v.sku AS variante_sku,
                v.talla AS variante_talla,
                v.color AS variante_color
            FROM detalle_pedido d
            INNER JOIN productos pr
                ON d.producto_id = pr.id
            LEFT JOIN variantes_producto v
                ON d.variante_id = v.id
            WHERE d.pedido_id = %s
            ORDER BY d.id ASC
        """, (pedido_id,))

        detalles = cursor.fetchall()

        cursor.execute("""
            SELECT
                COALESCE(SUM(monto), 0) AS total_pagado
            FROM pagos
            WHERE pedido_id = %s
        """, (pedido_id,))

        resultado_pago = cursor.fetchone()

        total_pagado = (
            resultado_pago["total_pagado"]
            if resultado_pago
            else Decimal("0.00")
        )

        if total_pagado is None:
            total_pagado = Decimal("0.00")

        saldo_pendiente = (
            pedido["total"]
            - total_pagado
        )

        cursor.execute("""
            SELECT
                nombre_negocio,
                logo,
                telefono,
                whatsapp,
                email,
                direccion,
                moneda,
                porcentaje_anticipo,
                dias_vigencia_cotizacion,
                banco,
                tipo_cuenta,
                numero_cuenta,
                titular_cuenta,
                notas_pago
            FROM configuracion_negocio
            ORDER BY id ASC
            LIMIT 1
        """)

        configuracion = cursor.fetchone()

        porcentaje_anticipo = Decimal("60.00")

        if (
            configuracion
            and configuracion["porcentaje_anticipo"] is not None
        ):
            porcentaje_anticipo = Decimal(
                str(configuracion["porcentaje_anticipo"])
            )

        anticipo_sugerido = (
            pedido["total"]
            * porcentaje_anticipo
            / Decimal("100")
        )

        saldo_despues_anticipo = (
            pedido["total"]
            - anticipo_sugerido
        )

        return render_template(
            "pedidos/cotizacion.html",
            pedido=pedido,
            detalles=detalles,
            configuracion=configuracion,
            porcentaje_anticipo=porcentaje_anticipo,
            anticipo_sugerido=anticipo_sugerido,
            saldo_despues_anticipo=saldo_despues_anticipo,
            total_pagado=total_pagado,
            saldo_pendiente=saldo_pendiente
        )

    finally:

        cursor.close()
        conexion.close()


@pedidos_bp.route("/<int:pedido_id>/pago", methods=["GET", "POST"])
def registrar_pago(pedido_id):

    conexion = obtener_conexion()
    cursor = conexion.cursor(dictionary=True)

    if request.method == "POST":

        try:

            monto = Decimal(
                request.form.get("monto", "0")
            )

            metodo_pago = request.form.get("metodo_pago")

            referencia = request.form.get(
                "referencia",
                ""
            ).strip()

            notas = request.form.get(
                "notas",
                ""
            ).strip()

            if monto <= Decimal("0"):
                return "El monto debe ser mayor que 0", 400

            metodos_validos = [
                "EFECTIVO",
                "TRANSFERENCIA",
                "TARJETA",
                "OTRO"
            ]

            if metodo_pago not in metodos_validos:
                return "Método de pago no válido", 400

            # Por ahora usamos el usuario 8,
            # igual que en tu función nuevo()
            usuario_id = 8

            cursor.execute("""
                SELECT
                    id,
                    numero,
                    total
                FROM pedidos
                WHERE id = %s
            """, (pedido_id,))

            pedido = cursor.fetchone()

            if not pedido:

                cursor.close()
                conexion.close()

                return "Pedido no encontrado", 404

            cursor.execute("""
                SELECT
                    COALESCE(SUM(monto), 0) AS pagado
                FROM pagos
                WHERE pedido_id = %s
            """, (pedido_id,))

            resultado = cursor.fetchone()

            pagado = resultado["pagado"]

            if pagado is None:
                pagado = Decimal("0.00")

            saldo_pendiente = pedido["total"] - pagado

            if monto > saldo_pendiente:

                cursor.close()
                conexion.close()

                return (
                    "El pago no puede ser mayor "
                    "al saldo pendiente.",
                    400
                )

            cursor.execute("""
                INSERT INTO pagos
                (
                    pedido_id,
                    usuario_id,
                    monto,
                    metodo_pago,
                    referencia,
                    notas
                )
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (
                pedido_id,
                usuario_id,
                monto,
                metodo_pago,
                referencia or None,
                notas or None
            ))

            pago_id = cursor.lastrowid

            cursor.execute("""
                INSERT INTO ingresos
                (
                    pedido_id,
                    pago_id,
                    usuario_id,
                    categoria,
                    monto,
                    descripcion
                )
                VALUES
                (
                    %s,
                    %s,
                    %s,
                    'VENTA',
                    %s,
                    %s
                )
            """, (
                pedido_id,
                pago_id,
                usuario_id,
                monto,
                f"Pago recibido del pedido {pedido['numero']}"
            ))

            conexion.commit()

            cursor.close()
            conexion.close()

            return redirect(
                url_for(
                    "pedidos.detalle",
                    pedido_id=pedido_id
                )
            )

        except Exception:

            conexion.rollback()
            cursor.close()
            conexion.close()

            raise

    # Obtener información del pedido
    cursor.execute("""
        SELECT
            id,
            numero,
            total
        FROM pedidos
        WHERE id = %s
    """, (pedido_id,))

    pedido = cursor.fetchone()

    if not pedido:

        cursor.close()
        conexion.close()

        return "Pedido no encontrado", 404

    # Obtener cuánto lleva pagado
    cursor.execute("""
        SELECT
            COALESCE(SUM(monto), 0) AS pagado
        FROM pagos
        WHERE pedido_id = %s
    """, (pedido_id,))

    resultado = cursor.fetchone()

    total_pagado = resultado["pagado"]

    if total_pagado is None:
        total_pagado = Decimal("0.00")

    saldo_pendiente = pedido["total"] - total_pagado

    cursor.close()
    conexion.close()

    return render_template(
        "pedidos/registrar_pago.html",
        pedido=pedido,
        total_pagado=total_pagado,
        saldo_pendiente=saldo_pendiente
    )

@pedidos_bp.route(
    "/pago/<int:pago_id>/comprobante",
    methods=["POST"]
)
def subir_comprobante(pago_id):

    archivo = request.files.get("comprobante")

    if not archivo or archivo.filename == "":
        return "No se seleccionó ningún archivo", 400

    extensiones_permitidas = {
        "jpg",
        "jpeg",
        "png",
        "webp",
        "pdf"
    }

    nombre_original = archivo.filename

    extension = (
        nombre_original.rsplit(".", 1)[1].lower()
        if "." in nombre_original
        else ""
    )

    if extension not in extensiones_permitidas:
        return (
            "Tipo de archivo no permitido. "
            "Solo se permiten JPG, JPEG, PNG, WEBP y PDF.",
            400
        )

    conexion = obtener_conexion()
    cursor = conexion.cursor(dictionary=True)

    try:

        # Verificar que el pago exista
        cursor.execute("""
            SELECT
                id,
                pedido_id
            FROM pagos
            WHERE id = %s
        """, (pago_id,))

        pago = cursor.fetchone()

        if not pago:
            cursor.close()
            conexion.close()
            return "Pago no encontrado", 404

        # Carpeta donde se guardarán los comprobantes
        carpeta = os.path.join(
            "uploads",
            "comprobantes_pagos"
        )

        os.makedirs(
            carpeta,
            exist_ok=True
        )

        # Generar nombre único
        nombre_archivo = (
            f"{uuid.uuid4().hex}.{extension}"
        )

        ruta_archivo = os.path.join(
            carpeta,
            nombre_archivo
        )

        archivo.save(ruta_archivo)

        # Obtener tamaño
        tamano_bytes = os.path.getsize(
            ruta_archivo
        )

        # Guardar información en la BD
        cursor.execute("""
            INSERT INTO comprobantes_pago
            (
                pago_id,
                nombre_original,
                ruta,
                tipo_archivo,
                tamano_bytes
            )
            VALUES (%s, %s, %s, %s, %s)
        """, (
            pago_id,
            nombre_original,
            ruta_archivo,
            archivo.content_type,
            tamano_bytes
        ))

        conexion.commit()

        cursor.close()
        conexion.close()

        return redirect(
            url_for(
                "pedidos.detalle",
                pedido_id=pago["pedido_id"]
            )
        )

    except Exception:

        conexion.rollback()
        cursor.close()
        conexion.close()

        raise

@pedidos_bp.route("/<int:pedido_id>/editar", methods=["GET", "POST"])
def editar(pedido_id):

    conexion = obtener_conexion()
    cursor = conexion.cursor(dictionary=True)

    if request.method == "POST":

        try:

            cliente_id = int(request.form["cliente_id"])

            fecha_entrega = (
                request.form.get("fecha_entrega")
                or None
            )

            estado = request.form.get("estado")

            from decimal import Decimal
            descuento = Decimal(
    request.form.get("descuento", "0")
)
            

            notas = request.form.get(
                "notas",
                ""
            ).strip()

            estados_validos = [
                "COTIZACION",
                "CONFIRMADO",
                "EN PRODUCCION",
                "LISTO",
                "ENTREGADO",
                "CANCELADO"
            ]

            if estado not in estados_validos:
                return "Estado no válido", 400

            # Obtener subtotal actual
            cursor.execute("""
                SELECT
                    COALESCE(SUM(subtotal), 0) AS subtotal
                FROM detalle_pedido
                WHERE pedido_id = %s
            """, (pedido_id,))

            resultado = cursor.fetchone()

            subtotal = resultado["subtotal"]

            # Evitar descuentos negativos
            if descuento < 0:
                descuento = 0

            # Evitar que el descuento sea mayor al subtotal
            if descuento > subtotal:
                descuento = subtotal

            total = subtotal - descuento

            cursor.execute("""
                UPDATE pedidos
                SET
                    cliente_id = %s,
                    fecha_entrega = %s,
                    estado = %s,
                    descuento = %s,
                    subtotal = %s,
                    total = %s,
                    notas = %s
                WHERE id = %s
            """, (
                cliente_id,
                fecha_entrega,
                estado,
                descuento,
                subtotal,
                total,
                notas,
                pedido_id
            ))

            conexion.commit()

            cursor.close()
            conexion.close()

            return redirect(
                url_for(
                    "pedidos.detalle",
                    pedido_id=pedido_id
                )
            )

        except Exception:

            conexion.rollback()
            cursor.close()
            conexion.close()

            raise

    # Obtener pedido
    cursor.execute("""
        SELECT *
        FROM pedidos
        WHERE id = %s
    """, (pedido_id,))

    pedido = cursor.fetchone()

    if not pedido:

        cursor.close()
        conexion.close()

        return "Pedido no encontrado", 404

    # Obtener clientes
    cursor.execute("""
        SELECT
            id,
            nombre
        FROM clientes
        WHERE activo = 1
        ORDER BY nombre ASC
    """)

    clientes = cursor.fetchall()

    cursor.close()
    conexion.close()

    return render_template(
        "pedidos/editar.html",
        pedido=pedido,
        clientes=clientes
    )

@pedidos_bp.route(
    "/<int:pedido_id>/agregar-producto",
    methods=["GET", "POST"]
)
def agregar_producto(pedido_id):

    conexion = obtener_conexion()
    cursor = conexion.cursor(dictionary=True)

    if request.method == "POST":

        try:

            producto_id = int(
                request.form["producto_id"]
            )

            variante_id = request.form.get(
                "variante_id"
            )

            if variante_id:
                variante_id = int(variante_id)
            else:
                variante_id = None

            cantidad = float(
                request.form.get("cantidad", 1)
            )

            precio_unitario = float(
                request.form.get(
                    "precio_unitario",
                    0
                )
            )

            texto_personalizado = request.form.get(
                "texto_personalizado",
                ""
            ).strip()

            ancho = request.form.get("ancho") or None
            alto = request.form.get("alto") or None
            largo = request.form.get("largo") or None

            notas = request.form.get(
                "notas",
                ""
            ).strip()

            subtotal = cantidad * precio_unitario

            # Obtener costo de la variante o producto
            costo_estimado = 0

            if variante_id:

                cursor.execute("""
                    SELECT costo_base
                    FROM variantes_producto
                    WHERE id = %s
                      AND producto_id = %s
                      AND activo = 1
                """, (
                    variante_id,
                    producto_id
                ))

                variante = cursor.fetchone()

                if not variante:
                    return "Variante no válida", 400

                costo_estimado = (
                    Decimal(
                        str(
                            variante["costo_base"]
                            or 0
                        )
                    )
                    * Decimal(str(cantidad))
                )

            else:

                cursor.execute("""
                    SELECT
                        precio_base,
                        metodo_produccion,
                        tipo_calculo_precio,
                        costo_externo_referencia
                    FROM productos
                    WHERE id = %s
                      AND activo = 1
                      AND vendible = 1
                """, (producto_id,))

                producto = cursor.fetchone()

                if not producto:
                    return "Producto no encontrado", 404

                costo_estimado = (
                    calcular_costo_externo_estimado(
                        producto,
                        cantidad,
                        ancho,
                        alto,
                        largo
                    )
                )

            cursor.execute("""
                INSERT INTO detalle_pedido
                (
                    pedido_id,
                    producto_id,
                    variante_id,
                    cantidad,
                    precio_unitario,
                    descuento,
                    subtotal,
                    costo_estimado,
                    texto_personalizado,
                    ancho,
                    alto,
                    largo,
                    notas
                )
                VALUES
                (
                    %s, %s, %s, %s, %s,
                    0, %s, %s, %s, %s,
                    %s, %s, %s
                )
            """, (
                pedido_id,
                producto_id,
                variante_id,
                cantidad,
                precio_unitario,
                subtotal,
                costo_estimado,
                texto_personalizado,
                ancho,
                alto,
                largo,
                notas
            ))

            recalcular_totales_pedido(
                cursor,
                pedido_id
            )

            conexion.commit()

            cursor.close()
            conexion.close()

            return redirect(
                url_for(
                    "pedidos.detalle",
                    pedido_id=pedido_id
                )
            )

        except Exception:

            conexion.rollback()
            cursor.close()
            conexion.close()

            raise

    # Obtener productos
    cursor.execute("""
        SELECT
            id,
            nombre,
            tipo,
            metodo_produccion,
            precio_base
        FROM productos
        WHERE activo = 1
          AND vendible = 1
        ORDER BY nombre ASC
    """)

    productos = cursor.fetchall()


    # Obtener variantes
    cursor.execute("""
        SELECT
            id,
            producto_id,
            sku,
            nombre,
            talla,
            color,
            precio,
            costo_base
        FROM variantes_producto
        WHERE activo = 1
        ORDER BY nombre ASC
    """)

    variantes = cursor.fetchall()

    cursor.close()
    conexion.close()

    return render_template(
        "pedidos/agregar_producto.html",
        pedido_id=pedido_id,
        productos=productos,
        variantes=variantes
    )

@pedidos_bp.route(
    "/<int:pedido_id>/producto/<int:detalle_id>/editar",
    methods=["GET", "POST"]
)
def editar_producto(pedido_id, detalle_id):

    conexion = obtener_conexion()
    cursor = conexion.cursor(dictionary=True)

    if request.method == "POST":

        try:

            producto_id = int(
                request.form["producto_id"]
            )

            cantidad = Decimal(
                str(
                    request.form.get(
                        "cantidad",
                        "1"
                    )
                    or "1"
                )
            )

            precio_unitario = Decimal(
                str(
                    request.form.get(
                        "precio_unitario",
                        "0"
                    )
                    or "0"
                )
            )

            descuento = Decimal(
                str(
                    request.form.get(
                        "descuento",
                        "0"
                    )
                    or "0"
                )
            )

            if cantidad <= 0:
                raise ValueError(
                    "La cantidad debe ser mayor que cero."
                )

            if precio_unitario < 0:
                raise ValueError(
                    "El precio no puede ser negativo."
                )

            if descuento < 0:
                descuento = Decimal("0.00")

            subtotal_bruto = (
                cantidad
                * precio_unitario
            )

            if descuento > subtotal_bruto:
                descuento = subtotal_bruto

            # detalle_pedido.subtotal conserva el valor ANTES
            # del descuento. Así el resumen puede mostrar:
            # subtotal, descuentos y total por separado.
            subtotal = subtotal_bruto

            texto_personalizado = request.form.get(
                "texto_personalizado",
                ""
            ).strip()

            ancho = (
                request.form.get("ancho")
                or None
            )

            alto = (
                request.form.get("alto")
                or None
            )

            largo = (
                request.form.get("largo")
                or None
            )

            notas = request.form.get(
                "notas",
                ""
            ).strip()

            cursor.execute("""
                SELECT
                    metodo_produccion,
                    tipo_calculo_precio,
                    costo_externo_referencia
                FROM productos
                WHERE id = %s
                  AND activo = 1
                  AND vendible = 1
            """, (producto_id,))

            producto = cursor.fetchone()

            if not producto:
                raise ValueError(
                    "Producto no encontrado."
                )

            costo_estimado = (
                calcular_costo_externo_estimado(
                    producto,
                    cantidad,
                    ancho,
                    alto,
                    largo
                )
            )

            cursor.execute("""
                UPDATE detalle_pedido
                SET
                    producto_id = %s,
                    cantidad = %s,
                    precio_unitario = %s,
                    descuento = %s,
                    subtotal = %s,
                    costo_estimado = %s,
                    texto_personalizado = %s,
                    ancho = %s,
                    alto = %s,
                    largo = %s,
                    notas = %s
                WHERE id = %s
                  AND pedido_id = %s
            """, (
                producto_id,
                cantidad,
                precio_unitario,
                descuento,
                subtotal,
                costo_estimado,
                texto_personalizado,
                ancho,
                alto,
                largo,
                notas,
                detalle_id,
                pedido_id
            ))

            recalcular_totales_pedido(
                cursor,
                pedido_id
            )

            conexion.commit()

            flash(
                "Producto actualizado correctamente.",
                "success"
            )

            return redirect(
                url_for(
                    "pedidos.detalle",
                    pedido_id=pedido_id
                )
            )

        except Exception as e:

            conexion.rollback()

            flash(
                f"No se pudo actualizar el producto: {e}",
                "danger"
            )

        finally:

            cursor.close()
            conexion.close()

    # ========================================================
    # GET
    # ========================================================

    cursor.execute("""
        SELECT *
        FROM detalle_pedido
        WHERE id = %s
          AND pedido_id = %s
    """, (
        detalle_id,
        pedido_id
    ))

    detalle = cursor.fetchone()

    if not detalle:

        cursor.close()
        conexion.close()

        return (
            "Producto del pedido no encontrado",
            404
        )

    cursor.execute("""
        SELECT
            id,
            nombre,
            tipo,
            metodo_produccion,
            precio_base,
            tipo_calculo_precio
        FROM productos
        WHERE activo = 1
          AND vendible = 1
        ORDER BY nombre ASC
    """)

    productos = cursor.fetchall()

    # ========================================================
    # VARIANTES DEL PRODUCTO
    # ========================================================

    cursor.execute("""
        SELECT
            id,
            producto_id,
            sku,
            nombre,
            talla,
            color,
            precio,
            costo_base
        FROM variantes_producto
        WHERE activo = 1
        ORDER BY nombre ASC
    """)

    variantes = cursor.fetchall()

    cursor.close()
    conexion.close()

    return render_template(
        "pedidos/editar_producto.html",
        pedido_id=pedido_id,
        detalle=detalle,
        productos=productos,
        variantes=variantes
    )


@pedidos_bp.route(
    "/<int:pedido_id>/producto/<int:detalle_id>/eliminar",
    methods=["POST"]
)
def eliminar_producto(pedido_id, detalle_id):

    conexion = obtener_conexion()
    cursor = conexion.cursor(dictionary=True)

    try:

        # ----------------------------------------------------
        # Verificar que el producto pertenece al pedido
        # ----------------------------------------------------

        cursor.execute("""
            SELECT
                id,
                producto_id,
                cantidad
            FROM detalle_pedido
            WHERE id = %s
              AND pedido_id = %s
        """, (
            detalle_id,
            pedido_id
        ))

        detalle = cursor.fetchone()

        if not detalle:
            raise ValueError(
                "El producto no existe en este pedido."
            )

        # ----------------------------------------------------
        # Verificar producción asociada
        # ----------------------------------------------------

        cursor.execute("""
            SELECT
                id,
                estado
            FROM producciones
            WHERE detalle_pedido_id = %s
              AND estado != 'CANCELADO'
            LIMIT 1
            FOR UPDATE
        """, (detalle_id,))

        produccion = cursor.fetchone()

        # ----------------------------------------------------
        # Si existe producción, validar su estado
        # ----------------------------------------------------

        if produccion:

            if produccion["estado"] == "EN_PRODUCCION":

                raise ValueError(
                    "No puedes eliminar este producto porque "
                    "su producción está actualmente en proceso."
                )

            if produccion["estado"] == "TERMINADO":

                raise ValueError(
                    "No puedes eliminar este producto porque "
                    "su producción ya fue terminada."
                )

            if produccion["estado"] == "PENDIENTE":

                # Cancelar la producción antes de eliminar
                cursor.execute("""
                    UPDATE producciones
                    SET estado = 'CANCELADO'
                    WHERE id = %s
                """, (
                    produccion["id"],
                ))

        # ----------------------------------------------------
        # Eliminar producto
        # ----------------------------------------------------

        cursor.execute("""
            DELETE FROM detalle_pedido
            WHERE id = %s
              AND pedido_id = %s
        """, (
            detalle_id,
            pedido_id
        ))

        # ----------------------------------------------------
        # Recalcular subtotal, descuentos y total
        # ----------------------------------------------------

        recalcular_totales_pedido(
            cursor,
            pedido_id
        )

        conexion.commit()

        flash(
            "Producto eliminado correctamente.",
            "success"
        )

    except Exception as e:

        conexion.rollback()

        flash(
            f"No se pudo eliminar el producto: {e}",
            "danger"
        )

    finally:

        cursor.close()
        conexion.close()

    return redirect(
        url_for(
            "pedidos.detalle",
            pedido_id=pedido_id
        )
    )

@pedidos_bp.route("/<int:pedido_id>/estado", methods=["POST"])
def cambiar_estado(pedido_id):

    nuevo_estado = request.form.get("estado")

    estados_validos = [
        "COTIZACION",
        "CONFIRMADO",
        "EN PRODUCCION",
        "LISTO",
        "ENTREGADO",
        "CANCELADO"
    ]

    if nuevo_estado not in estados_validos:
        flash(
            "❌ El estado seleccionado no es válido.",
            "error"
        )
        return redirect(
            url_for(
                "pedidos.detalle",
                pedido_id=pedido_id
            )
        )

    conexion = obtener_conexion()
    cursor = conexion.cursor(dictionary=True)

    # Obtener estado actual
    cursor.execute("""
        SELECT estado
        FROM pedidos
        WHERE id = %s
    """, (pedido_id,))

    pedido = cursor.fetchone()

    if not pedido:
        cursor.close()
        conexion.close()

        flash(
            "❌ El pedido no existe.",
            "error"
        )

        return redirect(
            url_for("pedidos.lista")
        )

    estado_actual = pedido["estado"]

    # Estados permitidos desde cada estado
    transiciones = {

        "COTIZACION": [
            "CONFIRMADO",
            "CANCELADO"
        ],

        "CONFIRMADO": [
            "EN PRODUCCION",
            "CANCELADO"
        ],

        "EN PRODUCCION": [
            "LISTO",
            "CANCELADO"
        ],

        "LISTO": [
            "ENTREGADO"
        ],

        "ENTREGADO": [],

        "CANCELADO": []
    }

    if nuevo_estado not in transiciones.get(
        estado_actual,
        []
    ):

        cursor.close()
        conexion.close()

        flash(
            f"⚠️ No puedes cambiar el pedido "
            f"de '{estado_actual}' a '{nuevo_estado}'.",
            "warning"
        )

        return redirect(
            url_for(
                "pedidos.detalle",
                pedido_id=pedido_id
            )
        )

    cursor.execute("""
        UPDATE pedidos
        SET estado = %s
        WHERE id = %s
    """, (nuevo_estado, pedido_id))

    conexion.commit()

    cursor.close()
    conexion.close()

    flash(
        f"✅ Estado actualizado a '{nuevo_estado}'.",
        "success"
    )

    return redirect(
        url_for(
            "pedidos.detalle",
            pedido_id=pedido_id
        )
    )

@pedidos_bp.route(
    "/<int:pedido_id>/eliminar",
    methods=["POST"]
)
def eliminar_pedido(pedido_id):

    conexion = obtener_conexion()
    cursor = conexion.cursor(dictionary=True)

    try:

        # Verificar que el pedido exista
        cursor.execute("""
            SELECT
                id,
                numero,
                estado
            FROM pedidos
            WHERE id = %s
        """, (pedido_id,))

        pedido = cursor.fetchone()

        if not pedido:
            return "Pedido no encontrado", 404

        # SOLO se pueden eliminar cotizaciones
        if pedido["estado"] != "COTIZACION":
            return (
                "Solo se pueden eliminar pedidos "
                "que estén en estado COTIZACION.",
                400
            )

        # Eliminar pedido
        # Los detalles y pagos se eliminarán
        # automáticamente por ON DELETE CASCADE.
        cursor.execute("""
            DELETE FROM pedidos
            WHERE id = %s
        """, (pedido_id,))

        conexion.commit()

        cursor.close()
        conexion.close()

        return redirect(
            url_for("pedidos.listar")
        )

    except Exception:

        conexion.rollback()
        cursor.close()
        conexion.close()

        raise