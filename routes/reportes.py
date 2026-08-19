from flask import Blueprint, render_template, request
from database import obtener_conexion
from datetime import date, datetime
from decimal import Decimal


reportes_bp = Blueprint(
    "reportes",
    __name__,
    url_prefix="/reportes"
)


def _decimal(valor):
    return Decimal(str(valor if valor is not None else 0))


@reportes_bp.route("/")
def index():

    desde = request.args.get("desde", "").strip()
    hasta = request.args.get("hasta", "").strip()

    hoy = date.today()

    if not desde:
        desde = hoy.replace(day=1).isoformat()

    if not hasta:
        hasta = hoy.isoformat()

    try:
        desde_fecha = datetime.strptime(desde, "%Y-%m-%d").date()
        hasta_fecha = datetime.strptime(hasta, "%Y-%m-%d").date()
    except ValueError:
        desde_fecha = hoy.replace(day=1)
        hasta_fecha = hoy
        desde = desde_fecha.isoformat()
        hasta = hasta_fecha.isoformat()

    if desde_fecha > hasta_fecha:
        desde_fecha, hasta_fecha = hasta_fecha, desde_fecha
        desde = desde_fecha.isoformat()
        hasta = hasta_fecha.isoformat()

    conexion = obtener_conexion()
    cursor = conexion.cursor(dictionary=True)

    # ========================================================
    # RESUMEN FINANCIERO
    # ========================================================

    cursor.execute("""
        SELECT COALESCE(SUM(monto), 0) AS total
        FROM ingresos
        WHERE DATE(fecha) BETWEEN %s AND %s
    """, (desde, hasta))
    total_ingresos = _decimal(cursor.fetchone()["total"])

    cursor.execute("""
        SELECT COALESCE(SUM(monto), 0) AS total
        FROM egresos
        WHERE DATE(fecha) BETWEEN %s AND %s
    """, (desde, hasta))
    total_egresos = _decimal(cursor.fetchone()["total"])

    resultado = total_ingresos - total_egresos

    cursor.execute("""
        SELECT COALESCE(SUM(total), 0) AS total
        FROM pedidos
        WHERE DATE(fecha) BETWEEN %s AND %s
        AND estado != 'CANCELADO'
    """, (desde, hasta))
    ventas_generadas = _decimal(cursor.fetchone()["total"])

    cursor.execute("""
        SELECT COUNT(*) AS total
        FROM pedidos
        WHERE DATE(fecha) BETWEEN %s AND %s
        AND estado != 'CANCELADO'
    """, (desde, hasta))
    total_pedidos = cursor.fetchone()["total"]

    ticket_promedio = (
        ventas_generadas / Decimal(str(total_pedidos))
        if total_pedidos > 0
        else Decimal("0")
    )

    # ========================================================
    # PEDIDOS
    # ========================================================

    cursor.execute("""
        SELECT COUNT(*) AS total
        FROM pedidos
        WHERE DATE(fecha) BETWEEN %s AND %s
        AND estado = 'ENTREGADO'
    """, (desde, hasta))
    pedidos_entregados = cursor.fetchone()["total"]

    cursor.execute("""
        SELECT COUNT(*) AS total
        FROM pedidos
        WHERE DATE(fecha) BETWEEN %s AND %s
        AND estado = 'CANCELADO'
    """, (desde, hasta))
    pedidos_cancelados = cursor.fetchone()["total"]

    cursor.execute("""
        SELECT
            estado,
            COUNT(*) AS total
        FROM pedidos
        WHERE DATE(fecha) BETWEEN %s AND %s
        GROUP BY estado
        ORDER BY total DESC
    """, (desde, hasta))
    pedidos_por_estado = cursor.fetchall()

    # ========================================================
    # SALDO PENDIENTE GLOBAL
    # ========================================================

    cursor.execute("""
        SELECT
            COALESCE(
                SUM(
                    GREATEST(
                        p.total - COALESCE(pg.total_pagado, 0),
                        0
                    )
                ),
                0
            ) AS saldo
        FROM pedidos p
        LEFT JOIN (
            SELECT pedido_id, SUM(monto) AS total_pagado
            FROM pagos
            GROUP BY pedido_id
        ) pg
            ON pg.pedido_id = p.id
        WHERE p.estado != 'CANCELADO'
    """)
    saldo_pendiente = _decimal(cursor.fetchone()["saldo"])

    # ========================================================
    # RENTABILIDAD REAL DEL PERÍODO
    # ========================================================

    cursor.execute("""
        SELECT
            COUNT(*) AS lineas_totales,

            SUM(
                CASE
                    WHEN dp.costo_real IS NULL
                    THEN 1
                    ELSE 0
                END
            ) AS lineas_pendientes,

            COALESCE(
                SUM(
                    CASE
                        WHEN dp.costo_real IS NOT NULL
                        THEN
                            dp.subtotal
                            -
                            CASE
                                WHEN p.subtotal > 0
                                THEN (
                                    p.descuento
                                    * dp.subtotal
                                    / p.subtotal
                                )
                                ELSE 0
                            END
                        ELSE 0
                    END
                ),
                0
            ) AS venta_con_costo,

            COALESCE(
                SUM(
                    CASE
                        WHEN dp.costo_real IS NOT NULL
                        THEN dp.costo_real
                        ELSE 0
                    END
                ),
                0
            ) AS costo_real

        FROM detalle_pedido dp
        INNER JOIN pedidos p
            ON p.id = dp.pedido_id

        WHERE DATE(p.fecha) BETWEEN %s AND %s
        AND p.estado != 'CANCELADO'
    """, (desde, hasta))

    rentabilidad = cursor.fetchone()

    lineas_totales = int(rentabilidad["lineas_totales"] or 0)
    lineas_costo_pendiente = int(rentabilidad["lineas_pendientes"] or 0)

    venta_con_costo = _decimal(rentabilidad["venta_con_costo"])
    costo_real_periodo = _decimal(rentabilidad["costo_real"])

    ganancia_real_periodo = venta_con_costo - costo_real_periodo

    margen_real_periodo = (
        ganancia_real_periodo
        / venta_con_costo
        * Decimal("100")
        if venta_con_costo > 0
        else Decimal("0")
    )

    costos_completos_periodo = (
        lineas_totales > 0
        and lineas_costo_pendiente == 0
    )

    # ========================================================
    # INGRESOS / EGRESOS POR CATEGORÍA
    # ========================================================

    cursor.execute("""
        SELECT categoria, SUM(monto) AS total
        FROM ingresos
        WHERE DATE(fecha) BETWEEN %s AND %s
        GROUP BY categoria
        ORDER BY total DESC
    """, (desde, hasta))
    ingresos_categoria = cursor.fetchall()

    cursor.execute("""
        SELECT categoria, SUM(monto) AS total
        FROM egresos
        WHERE DATE(fecha) BETWEEN %s AND %s
        GROUP BY categoria
        ORDER BY total DESC
    """, (desde, hasta))
    egresos_categoria = cursor.fetchall()

    # ========================================================
    # INGRESOS / EGRESOS POR DÍA
    # ========================================================

    cursor.execute("""
        SELECT DATE(fecha) AS fecha, SUM(monto) AS total
        FROM ingresos
        WHERE DATE(fecha) BETWEEN %s AND %s
        GROUP BY DATE(fecha)
        ORDER BY fecha ASC
    """, (desde, hasta))
    ingresos_por_dia = cursor.fetchall()

    cursor.execute("""
        SELECT DATE(fecha) AS fecha, SUM(monto) AS total
        FROM egresos
        WHERE DATE(fecha) BETWEEN %s AND %s
        GROUP BY DATE(fecha)
        ORDER BY fecha ASC
    """, (desde, hasta))
    egresos_por_dia = cursor.fetchall()

    # ========================================================
    # CLIENTES
    # ========================================================

    cursor.execute("""
        SELECT
            c.id,
            c.nombre,
            COUNT(p.id) AS pedidos,
            COALESCE(SUM(p.total), 0) AS total_comprado
        FROM clientes c
        INNER JOIN pedidos p
            ON p.cliente_id = c.id
        WHERE DATE(p.fecha) BETWEEN %s AND %s
        AND p.estado != 'CANCELADO'
        GROUP BY c.id, c.nombre
        ORDER BY total_comprado DESC
        LIMIT 10
    """, (desde, hasta))
    mejores_clientes = cursor.fetchall()

    cursor.execute("""
        SELECT
            c.id,
            c.nombre,
            COALESCE(
                SUM(
                    GREATEST(
                        p.total - COALESCE(pg.total_pagado, 0),
                        0
                    )
                ),
                0
            ) AS saldo_pendiente
        FROM clientes c
        INNER JOIN pedidos p
            ON p.cliente_id = c.id
        LEFT JOIN (
            SELECT pedido_id, SUM(monto) AS total_pagado
            FROM pagos
            GROUP BY pedido_id
        ) pg
            ON pg.pedido_id = p.id
        WHERE p.estado != 'CANCELADO'
        GROUP BY c.id, c.nombre
        HAVING saldo_pendiente > 0
        ORDER BY saldo_pendiente DESC
        LIMIT 10
    """)
    clientes_con_mayor_saldo = cursor.fetchall()

    # ========================================================
    # PRODUCTOS MÁS VENDIDOS
    # ========================================================

    cursor.execute("""
        SELECT
            pr.id,
            pr.nombre,
            SUM(dp.cantidad) AS unidades_vendidas,
            COUNT(DISTINCT dp.pedido_id) AS pedidos,
            SUM(dp.subtotal) AS total_generado
        FROM detalle_pedido dp
        INNER JOIN pedidos p
            ON p.id = dp.pedido_id
        INNER JOIN productos pr
            ON pr.id = dp.producto_id
        WHERE DATE(p.fecha) BETWEEN %s AND %s
        AND p.estado != 'CANCELADO'
        GROUP BY pr.id, pr.nombre
        ORDER BY unidades_vendidas DESC, total_generado DESC
        LIMIT 10
    """, (desde, hasta))
    productos_mas_vendidos = cursor.fetchall()

    # ========================================================
    # PRODUCTOS MÁS RENTABLES
    # ========================================================

    cursor.execute("""
        SELECT
            pr.id,
            pr.nombre,
            SUM(dp.cantidad) AS unidades,
            COUNT(DISTINCT dp.pedido_id) AS pedidos,

            SUM(
                dp.subtotal
                -
                CASE
                    WHEN p.subtotal > 0
                    THEN (
                        p.descuento
                        * dp.subtotal
                        / p.subtotal
                    )
                    ELSE 0
                END
            ) AS venta_neta,

            SUM(dp.costo_real) AS costo_real,

            SUM(
                (
                    dp.subtotal
                    -
                    CASE
                        WHEN p.subtotal > 0
                        THEN (
                            p.descuento
                            * dp.subtotal
                            / p.subtotal
                        )
                        ELSE 0
                    END
                )
                -
                dp.costo_real
            ) AS ganancia_real

        FROM detalle_pedido dp
        INNER JOIN pedidos p
            ON p.id = dp.pedido_id
        INNER JOIN productos pr
            ON pr.id = dp.producto_id

        WHERE DATE(p.fecha) BETWEEN %s AND %s
        AND p.estado != 'CANCELADO'
        AND dp.costo_real IS NOT NULL

        GROUP BY pr.id, pr.nombre
        ORDER BY ganancia_real DESC, venta_neta DESC
        LIMIT 10
    """, (desde, hasta))

    productos_rentables = cursor.fetchall()

    for producto in productos_rentables:

        venta_neta_producto = _decimal(producto["venta_neta"])
        ganancia_producto = _decimal(producto["ganancia_real"])

        producto["margen"] = (
            ganancia_producto
            / venta_neta_producto
            * Decimal("100")
            if venta_neta_producto > 0
            else Decimal("0")
        )

    # ========================================================
    # INVENTARIO
    # ========================================================

    cursor.execute("""
        SELECT
            m.id,
            m.nombre,
            m.color,
            um.abreviatura,
            SUM(mi.cantidad) AS cantidad_consumida,
            SUM(
                mi.cantidad
                * COALESCE(mi.costo_unitario, 0)
            ) AS costo_consumido
        FROM movimientos_inventario mi
        INNER JOIN materiales m
            ON m.id = mi.material_id
        INNER JOIN unidades_medida um
            ON um.id = mi.unidad_id
        WHERE DATE(mi.fecha) BETWEEN %s AND %s
        AND mi.tipo IN (
            'CONSUMO',
            'VENTA',
            'AJUSTE_SALIDA',
            'MERMA'
        )
        GROUP BY
            m.id,
            m.nombre,
            m.color,
            um.id,
            um.abreviatura
        ORDER BY costo_consumido DESC, cantidad_consumida DESC
        LIMIT 10
    """, (desde, hasta))
    materiales_mas_consumidos = cursor.fetchall()

    cursor.execute("""
        SELECT
            COUNT(*) AS movimientos,
            COALESCE(
                SUM(
                    cantidad
                    * COALESCE(costo_unitario, 0)
                ),
                0
            ) AS costo_mermas
        FROM movimientos_inventario
        WHERE DATE(fecha) BETWEEN %s AND %s
        AND tipo = 'MERMA'
    """, (desde, hasta))

    resumen_mermas = cursor.fetchone()

    movimientos_merma = int(resumen_mermas["movimientos"] or 0)
    costo_mermas = _decimal(resumen_mermas["costo_mermas"])

    cursor.close()
    conexion.close()

    return render_template(
        "reportes/index.html",

        desde=desde,
        hasta=hasta,

        ventas_generadas=ventas_generadas,
        total_ingresos=total_ingresos,
        total_egresos=total_egresos,
        resultado=resultado,
        ticket_promedio=ticket_promedio,
        saldo_pendiente=saldo_pendiente,

        total_pedidos=total_pedidos,
        pedidos_entregados=pedidos_entregados,
        pedidos_cancelados=pedidos_cancelados,
        pedidos_por_estado=pedidos_por_estado,

        venta_con_costo=venta_con_costo,
        costo_real_periodo=costo_real_periodo,
        ganancia_real_periodo=ganancia_real_periodo,
        margen_real_periodo=margen_real_periodo,
        costos_completos_periodo=costos_completos_periodo,
        lineas_totales=lineas_totales,
        lineas_costo_pendiente=lineas_costo_pendiente,

        ingresos_categoria=ingresos_categoria,
        egresos_categoria=egresos_categoria,
        ingresos_por_dia=ingresos_por_dia,
        egresos_por_dia=egresos_por_dia,

        productos_mas_vendidos=productos_mas_vendidos,
        productos_rentables=productos_rentables,

        mejores_clientes=mejores_clientes,
        clientes_con_mayor_saldo=clientes_con_mayor_saldo,

        materiales_mas_consumidos=materiales_mas_consumidos,
        movimientos_merma=movimientos_merma,
        costo_mermas=costo_mermas,
    )