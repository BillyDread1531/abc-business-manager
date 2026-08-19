from flask import Blueprint, render_template, request, redirect, url_for
from database import obtener_conexion


def normalizar_nombre_cliente(nombre):

    if not nombre:
        return ""

    palabras = nombre.strip().split()

    resultado = []

    for palabra in palabras:

        if palabra.isupper() and len(palabra) <= 4:

            resultado.append(
                palabra
            )

        else:

            resultado.append(
                palabra[:1].upper()
                + palabra[1:].lower()
            )

    return " ".join(resultado)


clientes_bp = Blueprint(
    "clientes",
    __name__,
    url_prefix="/clientes"
)


# ============================================================
# LISTA DE CLIENTES
# ============================================================

@clientes_bp.route("/")
def listar():

    busqueda = request.args.get(
        "q",
        ""
    ).strip()

    estado_filtro = request.args.get(
        "estado",
        "todos"
    ).strip().lower()

    estados_validos = {
        "todos",
        "activos",
        "inactivos",
        "saldo"
    }

    if estado_filtro not in estados_validos:
        estado_filtro = "todos"

    conexion = obtener_conexion()
    cursor = conexion.cursor(dictionary=True)

    condiciones = []
    parametros = []

    # --------------------------------------------------------
    # BUSCADOR
    # --------------------------------------------------------

    if busqueda:

        termino = f"%{busqueda}%"

        condiciones.append("""
            (
                c.nombre LIKE %s
                OR c.telefono LIKE %s
                OR c.email LIKE %s
            )
        """)

        parametros.extend([
            termino,
            termino,
            termino
        ])

    # --------------------------------------------------------
    # FILTRO DE ESTADO
    # --------------------------------------------------------

    if estado_filtro == "activos":

        condiciones.append(
            "c.activo = 1"
        )

    elif estado_filtro == "inactivos":

        condiciones.append(
            "c.activo = 0"
        )

    elif estado_filtro == "saldo":

        condiciones.append("""
            COALESCE(
                resumen.saldo_pendiente,
                0
            ) > 0
        """)

    where_sql = ""

    if condiciones:

        where_sql = (
            "WHERE "
            + " AND ".join(condiciones)
        )

    # --------------------------------------------------------
    # CLIENTES + RESUMEN FINANCIERO
    # --------------------------------------------------------

    cursor.execute(
        f"""
        SELECT
            c.id,
            c.nombre,
            c.telefono,
            c.email,
            c.direccion,
            c.notas,
            c.activo,

            COALESCE(
                resumen.total_pedidos,
                0
            ) AS total_pedidos,

            COALESCE(
                resumen.total_comprado,
                0
            ) AS total_comprado,

            COALESCE(
                resumen.total_pagado,
                0
            ) AS total_pagado,

            COALESCE(
                resumen.saldo_pendiente,
                0
            ) AS saldo_pendiente

        FROM clientes c

        LEFT JOIN (

            SELECT
                p.cliente_id,

                COUNT(*) AS total_pedidos,

                SUM(
                    CASE
                        WHEN p.estado != 'CANCELADO'
                        THEN p.total
                        ELSE 0
                    END
                ) AS total_comprado,

                SUM(
                    CASE
                        WHEN p.estado != 'CANCELADO'
                        THEN COALESCE(
                            pg.total_pagado,
                            0
                        )
                        ELSE 0
                    END
                ) AS total_pagado,

                SUM(
                    CASE
                        WHEN p.estado != 'CANCELADO'
                        THEN GREATEST(
                            p.total
                            -
                            COALESCE(
                                pg.total_pagado,
                                0
                            ),
                            0
                        )
                        ELSE 0
                    END
                ) AS saldo_pendiente

            FROM pedidos p

            LEFT JOIN (
                SELECT
                    pedido_id,
                    SUM(monto) AS total_pagado
                FROM pagos
                GROUP BY pedido_id
            ) pg
                ON pg.pedido_id = p.id

            GROUP BY p.cliente_id

        ) resumen
            ON resumen.cliente_id = c.id

        {where_sql}

        ORDER BY
            c.activo DESC,
            c.nombre ASC
        """,
        tuple(parametros)
    )

    clientes = cursor.fetchall()

    # --------------------------------------------------------
    # CONTADORES
    # --------------------------------------------------------

    cursor.execute("""
        SELECT

            COUNT(*) AS todos,

            SUM(
                CASE
                    WHEN activo = 1
                    THEN 1
                    ELSE 0
                END
            ) AS activos,

            SUM(
                CASE
                    WHEN activo = 0
                    THEN 1
                    ELSE 0
                END
            ) AS inactivos

        FROM clientes
    """)

    contadores = cursor.fetchone()

    cursor.execute("""
        SELECT
            COUNT(*) AS con_saldo

        FROM (

            SELECT
                p.cliente_id,

                SUM(
                    GREATEST(
                        p.total
                        -
                        COALESCE(
                            pg.total_pagado,
                            0
                        ),
                        0
                    )
                ) AS saldo_pendiente

            FROM pedidos p

            LEFT JOIN (
                SELECT
                    pedido_id,
                    SUM(monto) AS total_pagado
                FROM pagos
                GROUP BY pedido_id
            ) pg
                ON pg.pedido_id = p.id

            WHERE p.estado != 'CANCELADO'

            GROUP BY p.cliente_id

            HAVING saldo_pendiente > 0

        ) pendientes
    """)

    resultado_saldo = cursor.fetchone()

    contadores["con_saldo"] = (
        resultado_saldo["con_saldo"]
        if resultado_saldo
        else 0
    )

    cursor.close()
    conexion.close()

    return render_template(
        "clientes/lista.html",

        clientes=clientes,

        busqueda=busqueda,
        estado_filtro=estado_filtro,

        contadores=contadores
    )


# ============================================================
# DETALLE / ESTADO DE CUENTA DEL CLIENTE
# ============================================================

@clientes_bp.route("/<int:cliente_id>")
def detalle(cliente_id):

    conexion = obtener_conexion()
    cursor = conexion.cursor(dictionary=True)

    # --------------------------------------------------------
    # DATOS DEL CLIENTE
    # --------------------------------------------------------

    cursor.execute("""
        SELECT
            id,
            nombre,
            telefono,
            email,
            direccion,
            notas,
            activo,
            creado_en,
            actualizado_en
        FROM clientes
        WHERE id = %s
    """, (cliente_id,))

    cliente = cursor.fetchone()

    if not cliente:

        cursor.close()
        conexion.close()

        return "Cliente no encontrado", 404

    # --------------------------------------------------------
    # PEDIDOS DEL CLIENTE
    # --------------------------------------------------------

    cursor.execute("""
        SELECT
            p.id,
            p.numero,
            p.fecha,
            p.fecha_entrega,
            p.total,
            p.estado,

            COALESCE(
                pagos.total_pagado,
                0
            ) AS total_pagado,

            CASE
                WHEN p.estado = 'CANCELADO'
                THEN 0
                ELSE GREATEST(
                    p.total
                    -
                    COALESCE(
                        pagos.total_pagado,
                        0
                    ),
                    0
                )
            END AS saldo_pendiente

        FROM pedidos p

        LEFT JOIN (
            SELECT
                pedido_id,
                SUM(monto) AS total_pagado
            FROM pagos
            GROUP BY pedido_id
        ) pagos
            ON pagos.pedido_id = p.id

        WHERE p.cliente_id = %s

        ORDER BY
            p.fecha DESC,
            p.id DESC
    """, (cliente_id,))

    pedidos = cursor.fetchall()

    # --------------------------------------------------------
    # RESUMEN FINANCIERO
    # --------------------------------------------------------

    cursor.execute("""
        SELECT

            COALESCE(
                SUM(
                    CASE
                        WHEN p.estado != 'CANCELADO'
                        THEN p.total
                        ELSE 0
                    END
                ),
                0
            ) AS total_comprado,

            COALESCE(
                SUM(
                    CASE
                        WHEN p.estado != 'CANCELADO'
                        THEN COALESCE(
                            pagos.total_pagado,
                            0
                        )
                        ELSE 0
                    END
                ),
                0
            ) AS total_pagado,

            COALESCE(
                SUM(
                    CASE
                        WHEN p.estado != 'CANCELADO'
                        THEN GREATEST(
                            p.total
                            -
                            COALESCE(
                                pagos.total_pagado,
                                0
                            ),
                            0
                        )
                        ELSE 0
                    END
                ),
                0
            ) AS saldo_pendiente,

            COUNT(
                CASE
                    WHEN p.estado != 'CANCELADO'
                    THEN 1
                END
            ) AS total_pedidos,

            COUNT(
                CASE
                    WHEN p.estado != 'CANCELADO'
                    AND (
                        p.total
                        -
                        COALESCE(
                            pagos.total_pagado,
                            0
                        )
                    ) > 0
                    THEN 1
                END
            ) AS pedidos_con_saldo

        FROM pedidos p

        LEFT JOIN (
            SELECT
                pedido_id,
                SUM(monto) AS total_pagado
            FROM pagos
            GROUP BY pedido_id
        ) pagos
            ON pagos.pedido_id = p.id

        WHERE p.cliente_id = %s
    """, (cliente_id,))

    resumen = cursor.fetchone()

    total_comprado = resumen["total_comprado"]
    total_pagado = resumen["total_pagado"]
    saldo_pendiente = resumen["saldo_pendiente"]
    total_pedidos = resumen["total_pedidos"]
    pedidos_con_saldo = resumen["pedidos_con_saldo"]

    # --------------------------------------------------------
    # ÚLTIMO PEDIDO VÁLIDO
    # --------------------------------------------------------

    ultimo_pedido = next(
        (
            pedido
            for pedido in pedidos
            if pedido["estado"] != "CANCELADO"
        ),
        None
    )

    # --------------------------------------------------------
    # PEDIDOS CON SALDO
    # --------------------------------------------------------

    pedidos_pendientes = [
        pedido
        for pedido in pedidos
        if (
            pedido["estado"] != "CANCELADO"
            and float(
                pedido["saldo_pendiente"] or 0
            ) > 0
        )
    ]

    # --------------------------------------------------------
    # DISTRIBUCIÓN DE PEDIDOS POR ESTADO
    # --------------------------------------------------------

    estados = {
        "cotizacion": 0,
        "confirmado": 0,
        "produccion": 0,
        "listo": 0,
        "entregado": 0,
        "cancelado": 0
    }

    for pedido in pedidos:

        estado = pedido["estado"]

        if estado == "COTIZACION":
            estados["cotizacion"] += 1

        elif estado == "CONFIRMADO":
            estados["confirmado"] += 1

        elif estado == "EN PRODUCCION":
            estados["produccion"] += 1

        elif estado == "LISTO":
            estados["listo"] += 1

        elif estado == "ENTREGADO":
            estados["entregado"] += 1

        elif estado == "CANCELADO":
            estados["cancelado"] += 1

    cursor.close()
    conexion.close()

    return render_template(
        "clientes/detalle.html",

        cliente=cliente,
        pedidos=pedidos,
        pedidos_pendientes=pedidos_pendientes,

        total_comprado=total_comprado,
        total_pagado=total_pagado,
        saldo_pendiente=saldo_pendiente,

        total_pedidos=total_pedidos,
        pedidos_con_saldo=pedidos_con_saldo,

        ultimo_pedido=ultimo_pedido,
        estados=estados
    )


# ============================================================
# EDITAR CLIENTE
# ============================================================

@clientes_bp.route(
    "/<int:cliente_id>/editar",
    methods=["GET", "POST"]
)
def editar(cliente_id):

    conexion = obtener_conexion()
    cursor = conexion.cursor(dictionary=True)

    # --------------------------------------------------------
    # GUARDAR CAMBIOS
    # --------------------------------------------------------

    if request.method == "POST":

        try:

            nombre = normalizar_nombre_cliente(
                request.form.get(
                    "nombre",
                    ""
                )
            )

            telefono = request.form.get(
                "telefono",
                ""
            ).strip()

            email = request.form.get(
                "email",
                ""
            ).strip()

            direccion = request.form.get(
                "direccion",
                ""
            ).strip()

            notas = request.form.get(
                "notas",
                ""
            ).strip()

            if not nombre:

                return (
                    "El nombre del cliente es obligatorio",
                    400
                )

            cursor.execute("""
                UPDATE clientes
                SET
                    nombre = %s,
                    telefono = %s,
                    email = %s,
                    direccion = %s,
                    notas = %s
                WHERE id = %s
            """, (
                nombre,
                telefono if telefono else None,
                email if email else None,
                direccion if direccion else None,
                notas if notas else None,
                cliente_id
            ))

            conexion.commit()

            cursor.close()
            conexion.close()

            return redirect(
                url_for(
                    "clientes.detalle",
                    cliente_id=cliente_id
                )
            )

        except Exception:

            conexion.rollback()

            cursor.close()
            conexion.close()

            raise

    # --------------------------------------------------------
    # OBTENER CLIENTE
    # --------------------------------------------------------

    cursor.execute("""
        SELECT
            id,
            nombre,
            telefono,
            email,
            direccion,
            notas,
            activo
        FROM clientes
        WHERE id = %s
    """, (cliente_id,))

    cliente = cursor.fetchone()

    cursor.close()
    conexion.close()

    if not cliente:

        return "Cliente no encontrado", 404

    return render_template(
        "clientes/editar.html",
        cliente=cliente
    )


# ============================================================
# NUEVO CLIENTE
# ============================================================

@clientes_bp.route(
    "/nuevo",
    methods=["GET", "POST"]
)
def nuevo():

    if request.method == "POST":

        nombre = normalizar_nombre_cliente(
            request.form.get(
                "nombre",
                ""
            )
        )

        telefono = request.form.get(
            "telefono"
        )

        email = request.form.get(
            "email"
        )

        direccion = request.form.get(
            "direccion"
        )

        notas = request.form.get(
            "notas"
        )

        if not nombre:

            return (
                "El nombre del cliente es obligatorio",
                400
            )

        conexion = obtener_conexion()
        cursor = conexion.cursor()

        try:

            cursor.execute("""
                INSERT INTO clientes
                (
                    nombre,
                    telefono,
                    email,
                    direccion,
                    notas
                )
                VALUES (
                    %s,
                    %s,
                    %s,
                    %s,
                    %s
                )
            """, (
                nombre,
                telefono.strip()
                if telefono and telefono.strip()
                else None,

                email.strip()
                if email and email.strip()
                else None,

                direccion.strip()
                if direccion and direccion.strip()
                else None,

                notas.strip()
                if notas and notas.strip()
                else None
            ))

            conexion.commit()

        except Exception:

            conexion.rollback()
            raise

        finally:

            cursor.close()
            conexion.close()

        return redirect(
            url_for("clientes.listar")
        )

    return render_template(
        "clientes/nuevo.html"
    )