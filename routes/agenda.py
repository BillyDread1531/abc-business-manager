from flask import Blueprint, render_template, request
from database import obtener_conexion

from datetime import date, datetime, timedelta


agenda_bp = Blueprint(
    "agenda",
    __name__,
    url_prefix="/agenda"
)


# ============================================================
# AGENDA
# ============================================================

@agenda_bp.route("/")
def index():

    # ========================================================
    # FILTROS
    # ========================================================

    filtro = request.args.get(
        "filtro",
        "semana"
    ).strip().lower()

    filtros_validos = {
        "hoy",
        "semana",
        "mes",
        "vencidos",
        "todos"
    }

    if filtro not in filtros_validos:
        filtro = "semana"


    hoy = date.today()

    # Lunes de la semana actual
    inicio_semana = (
        hoy
        - timedelta(
            days=hoy.weekday()
        )
    )

    fin_semana = (
        inicio_semana
        + timedelta(days=6)
    )

    inicio_mes = hoy.replace(
        day=1
    )

    if hoy.month == 12:

        inicio_mes_siguiente = date(
            hoy.year + 1,
            1,
            1
        )

    else:

        inicio_mes_siguiente = date(
            hoy.year,
            hoy.month + 1,
            1
        )

    fin_mes = (
        inicio_mes_siguiente
        - timedelta(days=1)
    )


    conexion = obtener_conexion()
    cursor = conexion.cursor(
        dictionary=True
    )


    # ========================================================
    # CONDICIONES
    # ========================================================

    condiciones = [
        "p.fecha_entrega IS NOT NULL",
        "p.estado != 'CANCELADO'"
    ]

    parametros = []


    if filtro == "hoy":

        condiciones.append(
            "DATE(p.fecha_entrega) = %s"
        )

        parametros.append(
            hoy.isoformat()
        )


    elif filtro == "semana":

        condiciones.append(
            "DATE(p.fecha_entrega) BETWEEN %s AND %s"
        )

        parametros.extend([
            inicio_semana.isoformat(),
            fin_semana.isoformat()
        ])


    elif filtro == "mes":

        condiciones.append(
            "DATE(p.fecha_entrega) BETWEEN %s AND %s"
        )

        parametros.extend([
            inicio_mes.isoformat(),
            fin_mes.isoformat()
        ])


    elif filtro == "vencidos":

        condiciones.append(
            "p.fecha_entrega < NOW()"
        )

        condiciones.append(
            "p.estado NOT IN ('ENTREGADO', 'CANCELADO')"
        )


    # "todos" no agrega condición adicional


    where_sql = (
        "WHERE "
        + " AND ".join(
            condiciones
        )
    )


    # ========================================================
    # PEDIDOS
    # ========================================================

    cursor.execute(
        f"""
        SELECT
            p.id,
            p.numero,
            p.fecha,
            p.fecha_entrega,
            p.subtotal,
            p.descuento,
            p.total,
            p.estado,
            p.notas,

            c.id AS cliente_id,
            c.nombre AS cliente,
            c.telefono,

            COALESCE(
                resumen_productos.productos,
                0
            ) AS productos,

            COALESCE(
                resumen_productos.unidades,
                0
            ) AS unidades,

            COALESCE(
                pagos.total_pagado,
                0
            ) AS total_pagado,

            GREATEST(
                p.total
                -
                COALESCE(
                    pagos.total_pagado,
                    0
                ),
                0
            ) AS saldo_pendiente

        FROM pedidos p

        INNER JOIN clientes c
            ON c.id = p.cliente_id


        LEFT JOIN (

            SELECT
                pedido_id,

                COUNT(*) AS productos,

                SUM(cantidad) AS unidades

            FROM detalle_pedido

            GROUP BY pedido_id

        ) resumen_productos
            ON resumen_productos.pedido_id = p.id


        LEFT JOIN (

            SELECT
                pedido_id,

                SUM(monto) AS total_pagado

            FROM pagos

            GROUP BY pedido_id

        ) pagos
            ON pagos.pedido_id = p.id


        {where_sql}

        ORDER BY
            p.fecha_entrega ASC,
            p.id ASC
        """,
        tuple(parametros)
    )

    pedidos = cursor.fetchall()


    # ========================================================
    # PREPARAR INFORMACIÓN PARA LA VISTA
    # ========================================================

    ahora = datetime.now()

    for pedido in pedidos:

        fecha_entrega = (
            pedido["fecha_entrega"]
        )

        pedido["vencido"] = False
        pedido["es_hoy"] = False

        if fecha_entrega:

            pedido["es_hoy"] = (
                fecha_entrega.date()
                == hoy
            )

            pedido["vencido"] = (
                fecha_entrega < ahora
                and pedido["estado"]
                not in (
                    "ENTREGADO",
                    "CANCELADO"
                )
            )


    # ========================================================
    # AGRUPAR POR DÍA
    # ========================================================

    agenda_dias = []

    for pedido in pedidos:

        fecha = (
            pedido["fecha_entrega"].date()
        )

        grupo_existente = next(
            (
                grupo
                for grupo in agenda_dias
                if grupo["fecha"] == fecha
            ),
            None
        )

        if grupo_existente:

            grupo_existente[
                "pedidos"
            ].append(
                pedido
            )

        else:

            agenda_dias.append({
                "fecha": fecha,
                "pedidos": [
                    pedido
                ]
            })


    # ========================================================
    # CONTADORES GENERALES
    # ========================================================

    cursor.execute("""
        SELECT

            SUM(
                CASE
                    WHEN DATE(fecha_entrega) = CURDATE()
                    AND estado != 'CANCELADO'
                    THEN 1
                    ELSE 0
                END
            ) AS hoy,

            SUM(
                CASE
                    WHEN DATE(fecha_entrega)
                    BETWEEN %s AND %s
                    AND estado != 'CANCELADO'
                    THEN 1
                    ELSE 0
                END
            ) AS semana,

            SUM(
                CASE
                    WHEN DATE(fecha_entrega)
                    BETWEEN %s AND %s
                    AND estado != 'CANCELADO'
                    THEN 1
                    ELSE 0
                END
            ) AS mes,

            SUM(
                CASE
                    WHEN fecha_entrega < NOW()
                    AND estado NOT IN (
                        'ENTREGADO',
                        'CANCELADO'
                    )
                    THEN 1
                    ELSE 0
                END
            ) AS vencidos,

            SUM(
                CASE
                    WHEN fecha_entrega IS NOT NULL
                    AND estado != 'CANCELADO'
                    THEN 1
                    ELSE 0
                END
            ) AS todos

        FROM pedidos
    """, (
        inicio_semana.isoformat(),
        fin_semana.isoformat(),

        inicio_mes.isoformat(),
        fin_mes.isoformat()
    ))

    contadores = cursor.fetchone()


    # ========================================================
    # PEDIDOS SIN FECHA DE ENTREGA
    # ========================================================

    cursor.execute("""
        SELECT COUNT(*) AS total
        FROM pedidos
        WHERE fecha_entrega IS NULL
        AND estado NOT IN (
            'ENTREGADO',
            'CANCELADO'
        )
    """)

    pedidos_sin_fecha = (
        cursor.fetchone()["total"]
    )


    cursor.close()
    conexion.close()


    # ========================================================
    # RENDER
    # ========================================================

    return render_template(
        "agenda/index.html",

        filtro=filtro,

        hoy=hoy,

        inicio_semana=inicio_semana,
        fin_semana=fin_semana,

        inicio_mes=inicio_mes,
        fin_mes=fin_mes,

        pedidos=pedidos,
        agenda_dias=agenda_dias,

        contadores=contadores,

        pedidos_sin_fecha=pedidos_sin_fecha
    )