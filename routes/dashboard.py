from flask import Blueprint, render_template, url_for
from database import obtener_conexion
from decimal import Decimal


dashboard_bp = Blueprint(
    "dashboard",
    __name__,
    url_prefix="/dashboard"
)


@dashboard_bp.route("/")
def index():

    conn = obtener_conexion()
    cursor = conn.cursor(dictionary=True)

    # ============================================================
    # FINANZAS DEL MES
    # ============================================================

    cursor.execute("""
        SELECT
            COALESCE(SUM(monto), 0) AS total
        FROM ingresos
        WHERE YEAR(fecha) = YEAR(CURDATE())
        AND MONTH(fecha) = MONTH(CURDATE())
    """)

    ingresos_mes = cursor.fetchone()["total"]


    cursor.execute("""
        SELECT
            COALESCE(SUM(monto), 0) AS total
        FROM egresos
        WHERE YEAR(fecha) = YEAR(CURDATE())
        AND MONTH(fecha) = MONTH(CURDATE())
    """)

    egresos_mes = cursor.fetchone()["total"]


    resultado_mes = (
        Decimal(str(ingresos_mes))
        - Decimal(str(egresos_mes))
    )


    # ============================================================
    # SALDO PENDIENTE POR COBRAR
    # ============================================================

    cursor.execute("""
        SELECT
            COALESCE(
                SUM(
                    GREATEST(
                        p.total
                        -
                        COALESCE(
                            (
                                SELECT SUM(pg.monto)
                                FROM pagos pg
                                WHERE pg.pedido_id = p.id
                            ),
                            0
                        ),
                        0
                    )
                ),
                0
            ) AS saldo

        FROM pedidos p

        WHERE p.estado != 'CANCELADO'
    """)

    saldo_por_cobrar = cursor.fetchone()["saldo"]


    # ============================================================
    # PEDIDOS EN PRODUCCIÓN
    # ============================================================

    cursor.execute("""
        SELECT COUNT(*) AS total
        FROM pedidos
        WHERE estado = 'EN PRODUCCION'
    """)

    pedidos_produccion = cursor.fetchone()["total"]


    # ============================================================
    # PEDIDOS LISTOS
    # ============================================================

    cursor.execute("""
        SELECT COUNT(*) AS total
        FROM pedidos
        WHERE estado = 'LISTO'
    """)

    pedidos_listos = cursor.fetchone()["total"]


    # ============================================================
    # PRODUCCIONES ACTIVAS
    # ============================================================

    cursor.execute("""
        SELECT COUNT(*) AS total
        FROM producciones
        WHERE estado IN (
            'PENDIENTE',
            'EN_PRODUCCION'
        )
    """)

    producciones_activas = cursor.fetchone()["total"]


    # ============================================================
    # COMPRAS PENDIENTES DE PAGO
    # ============================================================

    cursor.execute("""
        SELECT
            c.id,
            c.numero,
            c.total,

            COALESCE(
                SUM(pc.monto),
                0
            ) AS total_pagado,

            GREATEST(
                c.total
                -
                COALESCE(
                    SUM(pc.monto),
                    0
                ),
                0
            ) AS saldo_pendiente

        FROM compras c

        LEFT JOIN pagos_compras pc
            ON pc.compra_id = c.id

        WHERE c.estado != 'CANCELADA'

        GROUP BY
            c.id,
            c.numero,
            c.total

        HAVING saldo_pendiente > 0

        ORDER BY saldo_pendiente DESC
    """)

    compras_pendientes = cursor.fetchall()

    compras_pendientes_pago = len(
        compras_pendientes
    )


    # ============================================================
    # MATERIALES CON STOCK BAJO
    # ============================================================

    cursor.execute("""
        SELECT
            m.id,
            m.nombre,
            m.color,
            m.stock_actual,
            m.stock_minimo,
            u.abreviatura

        FROM materiales m

        LEFT JOIN unidades_medida u
            ON u.id = m.unidad_consumo_id

        WHERE m.activo = 1
        AND m.stock_minimo IS NOT NULL
        AND m.stock_minimo > 0
        AND m.stock_actual <= m.stock_minimo

        ORDER BY
            CASE
                WHEN m.stock_actual <= 0 THEN 0
                ELSE 1
            END ASC,
            m.stock_actual ASC
    """)

    materiales_alerta = cursor.fetchall()

    materiales_stock_bajo = len(
        materiales_alerta
    )


    # ============================================================
    # ENTREGAS VENCIDAS
    # ============================================================

    cursor.execute("""
        SELECT
            p.id,
            p.numero,
            p.fecha_entrega,
            p.estado,
            c.nombre AS cliente

        FROM pedidos p

        INNER JOIN clientes c
            ON p.cliente_id = c.id

        WHERE p.fecha_entrega IS NOT NULL
        AND p.fecha_entrega < NOW()

        AND p.estado NOT IN (
            'ENTREGADO',
            'CANCELADO'
        )

        ORDER BY p.fecha_entrega ASC
    """)

    entregas_vencidas = cursor.fetchall()

    total_entregas_vencidas = len(
        entregas_vencidas
    )


    # ============================================================
    # ENTREGAS DE HOY
    # ============================================================

    cursor.execute("""
        SELECT
            p.id,
            p.numero,
            p.fecha_entrega,
            p.estado,
            c.nombre AS cliente

        FROM pedidos p

        INNER JOIN clientes c
            ON p.cliente_id = c.id

        WHERE p.fecha_entrega IS NOT NULL

        AND DATE(p.fecha_entrega) = CURDATE()

        AND p.fecha_entrega >= NOW()

        AND p.estado NOT IN (
            'ENTREGADO',
            'CANCELADO'
        )

        ORDER BY p.fecha_entrega ASC
    """)

    entregas_hoy = cursor.fetchall()


    # ============================================================
    # PRÓXIMAS ENTREGAS
    # ============================================================

    cursor.execute("""
        SELECT
            p.id,
            p.numero,
            p.fecha_entrega,
            p.estado,
            c.nombre AS cliente

        FROM pedidos p

        INNER JOIN clientes c
            ON p.cliente_id = c.id

        WHERE p.estado NOT IN (
            'ENTREGADO',
            'CANCELADO'
        )

        AND p.fecha_entrega IS NOT NULL
        AND p.fecha_entrega >= NOW()

        ORDER BY p.fecha_entrega ASC

        LIMIT 5
    """)

    proximas_entregas = cursor.fetchall()


    # ============================================================
    # CLIENTES CON SALDO PENDIENTE
    # ============================================================

    cursor.execute("""
        SELECT
            c.id,
            c.nombre,
            c.telefono,

            COALESCE(
                SUM(p.total),
                0
            ) AS total_comprado,

            COALESCE(
                SUM(
                    COALESCE(
                        pg.total_pagado,
                        0
                    )
                ),
                0
            ) AS total_pagado,

            COALESCE(
                SUM(p.total),
                0
            )
            -
            COALESCE(
                SUM(
                    COALESCE(
                        pg.total_pagado,
                        0
                    )
                ),
                0
            ) AS saldo_pendiente

        FROM clientes c

        INNER JOIN pedidos p
            ON p.cliente_id = c.id

        LEFT JOIN (
            SELECT
                pedido_id,
                SUM(monto) AS total_pagado
            FROM pagos
            GROUP BY pedido_id
        ) pg
            ON pg.pedido_id = p.id

        WHERE p.estado != 'CANCELADO'

        GROUP BY
            c.id,
            c.nombre,
            c.telefono

        HAVING saldo_pendiente > 0

        ORDER BY saldo_pendiente DESC
    """)

    clientes_con_saldo = cursor.fetchall()

    total_clientes_con_saldo = len(
        clientes_con_saldo
    )


    # ============================================================
    # MOVIMIENTOS FINANCIEROS RECIENTES
    # ============================================================

    cursor.execute("""
        SELECT
            i.id,
            i.fecha,
            'INGRESO' AS tipo,
            i.categoria,
            i.descripcion,
            i.monto,
            i.pedido_id,
            NULL AS compra_id

        FROM ingresos i

        UNION ALL

        SELECT
            e.id,
            e.fecha,
            'EGRESO' AS tipo,
            e.categoria,
            e.descripcion,
            e.monto,
            e.pedido_id,
            e.compra_id

        FROM egresos e

        ORDER BY fecha DESC

        LIMIT 8
    """)

    movimientos = cursor.fetchall()


    # ============================================================
    # CENTRO DE ALERTAS
    # ============================================================

    alertas = []


    # ------------------------------------------------------------
    # ENTREGAS VENCIDAS
    # ------------------------------------------------------------

    for pedido in entregas_vencidas[:3]:

        alertas.append({
            "prioridad": 1,
            "nivel": "danger",
            "icono": "⏰",
            "tipo": "ENTREGA VENCIDA",

            "titulo": (
                f"{pedido['numero']} está atrasado"
            ),

            "descripcion": (
                f"{pedido['cliente']} · "
                f"Debía entregarse el "
                f"{pedido['fecha_entrega'].strftime('%d/%m/%Y %H:%M')}"
            ),

            "accion": "Ver pedido",

            "url": url_for(
                "pedidos.detalle",
                pedido_id=pedido["id"]
            )
        })


    # ------------------------------------------------------------
    # MATERIALES SIN STOCK
    # ------------------------------------------------------------

    for material in materiales_alerta:

        stock_actual = Decimal(
            str(
                material["stock_actual"]
                or 0
            )
        )

        if stock_actual <= 0:

            nombre_material = material["nombre"]

            if material["color"]:

                nombre_material += (
                    f" - {material['color']}"
                )

            alertas.append({
                "prioridad": 1,
                "nivel": "danger",
                "icono": "🚨",
                "tipo": "SIN STOCK",

                "titulo": nombre_material,

                "descripcion": (
                    "El material se quedó sin existencias."
                ),

                "accion": "Ver material",

                "url": url_for(
                    "materiales.editar",
                    material_id=material["id"]
                )
            })


    # ------------------------------------------------------------
    # ENTREGAS DE HOY
    # ------------------------------------------------------------

    for pedido in entregas_hoy[:3]:

        alertas.append({
            "prioridad": 2,
            "nivel": "warning",
            "icono": "📅",
            "tipo": "ENTREGA HOY",

            "titulo": (
                f"{pedido['numero']} se entrega hoy"
            ),

            "descripcion": (
                f"{pedido['cliente']} · "
                f"{pedido['fecha_entrega'].strftime('%H:%M')}"
            ),

            "accion": "Ver pedido",

            "url": url_for(
                "pedidos.detalle",
                pedido_id=pedido["id"]
            )
        })


    # ------------------------------------------------------------
    # STOCK BAJO
    # ------------------------------------------------------------

    stock_bajo_agregados = 0

    for material in materiales_alerta:

        stock_actual = Decimal(
            str(
                material["stock_actual"]
                or 0
            )
        )

        if stock_actual <= 0:
            continue

        if stock_bajo_agregados >= 3:
            break


        nombre_material = material["nombre"]

        if material["color"]:

            nombre_material += (
                f" - {material['color']}"
            )


        abreviatura = (
            material["abreviatura"]
            or ""
        )


        alertas.append({
            "prioridad": 2,
            "nivel": "warning",
            "icono": "⚠️",
            "tipo": "STOCK BAJO",

            "titulo": nombre_material,

            "descripcion": (
                f"Stock actual: "
                f"{material['stock_actual']} "
                f"{abreviatura} · "
                f"Mínimo: "
                f"{material['stock_minimo']} "
                f"{abreviatura}"
            ),

            "accion": "Ver material",

            "url": url_for(
                "materiales.editar",
                material_id=material["id"]
            )
        })

        stock_bajo_agregados += 1


    # ------------------------------------------------------------
    # CLIENTES CON SALDO
    # ------------------------------------------------------------

    for cliente in clientes_con_saldo[:2]:

        saldo = Decimal(
            str(
                cliente["saldo_pendiente"]
                or 0
            )
        )

        alertas.append({
            "prioridad": 2,
            "nivel": "warning",
            "icono": "💰",
            "tipo": "COBRO PENDIENTE",

            "titulo": cliente["nombre"],

            "descripcion": (
                f"Tiene Q {saldo:.2f} "
                "pendientes de pago."
            ),

            "accion": "Ver cliente",

            "url": url_for(
                "clientes.detalle",
                cliente_id=cliente["id"]
            )
        })


    # ------------------------------------------------------------
    # COMPRAS PENDIENTES
    # ------------------------------------------------------------

    for compra in compras_pendientes[:2]:

        saldo = Decimal(
            str(
                compra["saldo_pendiente"]
                or 0
            )
        )

        alertas.append({
            "prioridad": 3,
            "nivel": "info",
            "icono": "🛒",
            "tipo": "PAGO DE COMPRA",

            "titulo": (
                f"{compra['numero']} tiene saldo pendiente"
            ),

            "descripcion": (
                f"Faltan por pagar Q {saldo:.2f}."
            ),

            "accion": "Ver compra",

            "url": url_for(
                "compras.detalle",
                compra_id=compra["id"]
            )
        })


    # ============================================================
    # ORDENAR ALERTAS
    # ============================================================

    alertas.sort(
        key=lambda alerta:
            alerta["prioridad"]
    )


    # Mostrar como máximo 8 alertas

    alertas_dashboard = alertas[:8]


    # ============================================================
    # TOTAL DE SITUACIONES ACTIVAS
    # ============================================================

    total_alertas = (
        total_entregas_vencidas
        + len(entregas_hoy)
        + materiales_stock_bajo
        + total_clientes_con_saldo
        + compras_pendientes_pago
    )


    # ============================================================
    # CERRAR CONEXIÓN
    # ============================================================

    cursor.close()
    conn.close()


    # ============================================================
    # RENDER
    # ============================================================

    return render_template(
        "dashboard/index.html",

        # Finanzas
        ingresos_mes=ingresos_mes,
        egresos_mes=egresos_mes,
        resultado_mes=resultado_mes,
        saldo_por_cobrar=saldo_por_cobrar,

        # Operación
        pedidos_produccion=pedidos_produccion,
        pedidos_listos=pedidos_listos,
        producciones_activas=producciones_activas,

        # Compras
        compras_pendientes_pago=compras_pendientes_pago,

        # Materiales
        materiales_stock_bajo=materiales_stock_bajo,

        # Entregas
        proximas_entregas=proximas_entregas,
        entregas_vencidas=entregas_vencidas,
        total_entregas_vencidas=total_entregas_vencidas,

        # Clientes
        clientes_con_saldo=clientes_con_saldo,
        total_clientes_con_saldo=total_clientes_con_saldo,

        # Finanzas recientes
        movimientos=movimientos,

        # Alertas
        alertas=alertas_dashboard,
        total_alertas=total_alertas
    )