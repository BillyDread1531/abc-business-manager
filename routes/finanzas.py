from flask import Blueprint, render_template, request, redirect, url_for, flash
from database import obtener_conexion
from decimal import Decimal, ROUND_HALF_UP
from datetime import date, timedelta


finanzas_bp = Blueprint(
    "finanzas",
    __name__,
    url_prefix="/finanzas"
)


# ============================================================
# PANEL PRINCIPAL
# ============================================================


@finanzas_bp.route("/")
def index():

    conn = obtener_conexion()
    cursor = conn.cursor(dictionary=True)

    hoy = date.today()

    # ========================================================
    # CONFIGURACIÓN DE DISTRIBUCIÓN
    # ========================================================

    cursor.execute("""
        SELECT
            porcentaje_propietario,
            porcentaje_reinversion,
            porcentaje_reserva
        FROM configuracion_negocio
        ORDER BY id ASC
        LIMIT 1
    """)

    configuracion_utilidad = cursor.fetchone() or {}

    porcentaje_propietario = Decimal(
        str(
            configuracion_utilidad.get(
                "porcentaje_propietario",
                50
            ) or 50
        )
    )

    porcentaje_reinversion = Decimal(
        str(
            configuracion_utilidad.get(
                "porcentaje_reinversion",
                30
            ) or 30
        )
    )

    porcentaje_reserva = Decimal(
        str(
            configuracion_utilidad.get(
                "porcentaje_reserva",
                20
            ) or 20
        )
    )

    # ========================================================
    # UTILIDAD: SEMANA / MES
    # ========================================================

    periodo_utilidad = request.args.get(
        "periodo_utilidad",
        "SEMANA"
    ).strip().upper()

    if periodo_utilidad not in {
        "SEMANA",
        "MES"
    }:
        periodo_utilidad = "SEMANA"

    if periodo_utilidad == "MES":

        utilidad_desde = hoy.replace(day=1)
        utilidad_hasta = hoy

    else:

        utilidad_desde = (
            hoy
            - timedelta(days=hoy.weekday())
        )
        utilidad_hasta = hoy

    etiqueta_periodo_utilidad = (
        utilidad_desde.strftime("%d/%m/%Y")
        + " - "
        + utilidad_hasta.strftime("%d/%m/%Y")
    )

    def calcular_utilidad_periodo(desde, hasta):

        # Ventas cobradas en el período.
        cursor.execute("""
            SELECT
                COALESCE(SUM(i.monto), 0) AS total
            FROM ingresos i
            WHERE UPPER(i.categoria) = 'VENTA'
              AND DATE(i.fecha) BETWEEN %s AND %s
        """, (
            desde,
            hasta
        ))

        ventas = Decimal(
            str(cursor.fetchone()["total"] or 0)
        )

        # Otros ingresos se muestran como referencia, pero no se
        # consideran automáticamente utilidad por ventas.
        cursor.execute("""
            SELECT
                COALESCE(SUM(i.monto), 0) AS total
            FROM ingresos i
            WHERE UPPER(i.categoria) != 'VENTA'
              AND DATE(i.fecha) BETWEEN %s AND %s
        """, (
            desde,
            hasta
        ))

        otros_ingresos_periodo = Decimal(
            str(cursor.fetchone()["total"] or 0)
        )

        # Las compras de inventario reducen caja, pero no se vuelven
        # a restar de la utilidad. El material se reconoce como costo
        # cuando se utiliza para producir lo vendido.
        cursor.execute("""
            SELECT
                COALESCE(SUM(e.monto), 0) AS total
            FROM egresos e
            WHERE UPPER(e.categoria) != 'COMPRA'
              AND DATE(e.fecha) BETWEEN %s AND %s
        """, (
            desde,
            hasta
        ))

        gastos_operativos = Decimal(
            str(cursor.fetchone()["total"] or 0)
        )

        # Costo asociado a lo efectivamente cobrado en el período.
        # Si un pedido se cobró parcialmente, solo se reconoce la
        # misma proporción del costo total del pedido.
        cursor.execute("""
            SELECT
                COALESCE(
                    SUM(
                        CASE
                            WHEN p.total > 0
                            THEN
                                LEAST(
                                    cobros.cobrado_periodo / p.total,
                                    1
                                )
                                * COALESCE(costos.costo_pedido, 0)
                            ELSE 0
                        END
                    ),
                    0
                ) AS costo_asociado

            FROM (
                SELECT
                    i.pedido_id,
                    SUM(i.monto) AS cobrado_periodo
                FROM ingresos i
                WHERE UPPER(i.categoria) = 'VENTA'
                  AND i.pedido_id IS NOT NULL
                  AND DATE(i.fecha) BETWEEN %s AND %s
                GROUP BY i.pedido_id
            ) cobros

            INNER JOIN pedidos p
                ON p.id = cobros.pedido_id

            LEFT JOIN (
                SELECT
                    dp.pedido_id,
                    SUM(
                        COALESCE(
                            dp.costo_real,
                            pr.costo_real,
                            NULLIF(pr.costo_estimado, 0),
                            NULLIF(dp.costo_estimado, 0),
                            0
                        )
                    ) AS costo_pedido
                FROM detalle_pedido dp

                LEFT JOIN producciones pr
                    ON pr.detalle_pedido_id = dp.id
                   AND pr.estado != 'CANCELADO'

                GROUP BY dp.pedido_id
            ) costos
                ON costos.pedido_id = p.id

            WHERE p.estado != 'CANCELADO'
        """, (
            desde,
            hasta
        ))

        costo_ventas = Decimal(
            str(
                cursor.fetchone()["costo_asociado"]
                or 0
            )
        ).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP
        )

        utilidad = (
            ventas
            - costo_ventas
            - gastos_operativos
        ).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP
        )

        distribuible = max(
            utilidad,
            Decimal("0.00")
        )

        propietario = (
            distribuible
            * porcentaje_propietario
            / Decimal("100")
        ).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP
        )

        reinversion = (
            distribuible
            * porcentaje_reinversion
            / Decimal("100")
        ).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP
        )

        # La reserva absorbe cualquier centavo de redondeo para que
        # propietario + reinversión + reserva sea exactamente la utilidad.
        reserva = (
            distribuible
            - propietario
            - reinversion
        ).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP
        )

        return {
            "ventas": ventas,
            "otros_ingresos": otros_ingresos_periodo,
            "gastos_operativos": gastos_operativos,
            "costo_ventas": costo_ventas,
            "utilidad": utilidad,
            "distribuible": distribuible,
            "propietario": propietario,
            "reinversion": reinversion,
            "reserva": reserva,
        }

    utilidad_periodo = calcular_utilidad_periodo(
        utilidad_desde,
        utilidad_hasta
    )

    ventas_cobradas_utilidad = utilidad_periodo["ventas"]
    otros_ingresos_utilidad = utilidad_periodo["otros_ingresos"]
    costo_ventas_utilidad = utilidad_periodo["costo_ventas"]
    gastos_operativos_utilidad = utilidad_periodo["gastos_operativos"]
    utilidad_real = utilidad_periodo["utilidad"]
    utilidad_distribuible = utilidad_periodo["distribuible"]
    ganancia_propietario = utilidad_periodo["propietario"]
    monto_reinversion = utilidad_periodo["reinversion"]
    monto_reserva = utilidad_periodo["reserva"]

    # ========================================================
    # SEPARACIÓN ACUMULADA POR SEMANAS
    # ========================================================
    #
    # Esta parte permite tratar tu porcentaje como dinero separado.
    # Las compras posteriores de inventario sí reducen la caja de ABC,
    # pero no disminuyen la utilidad positiva que ya generaste en semanas
    # anteriores.

    cursor.execute("""
        SELECT
            i.fecha,
            i.pedido_id,
            i.monto,
            p.total AS total_pedido
        FROM ingresos i
        LEFT JOIN pedidos p
            ON p.id = i.pedido_id
        WHERE UPPER(i.categoria) = 'VENTA'
          AND DATE(i.fecha) <= %s
        ORDER BY i.fecha ASC, i.id ASC
    """, (hoy,))

    cobros_historicos = cursor.fetchall()

    cursor.execute("""
        SELECT
            dp.pedido_id,
            SUM(
                COALESCE(
                    dp.costo_real,
                    pr.costo_real,
                    NULLIF(pr.costo_estimado, 0),
                    NULLIF(dp.costo_estimado, 0),
                    0
                )
            ) AS costo_pedido
        FROM detalle_pedido dp
        LEFT JOIN producciones pr
            ON pr.detalle_pedido_id = dp.id
           AND pr.estado != 'CANCELADO'
        GROUP BY dp.pedido_id
    """)

    costos_por_pedido = {
        fila["pedido_id"]: Decimal(
            str(fila["costo_pedido"] or 0)
        )
        for fila in cursor.fetchall()
    }

    cursor.execute("""
        SELECT
            e.fecha,
            e.monto
        FROM egresos e
        WHERE UPPER(e.categoria) != 'COMPRA'
          AND DATE(e.fecha) <= %s
        ORDER BY e.fecha ASC, e.id ASC
    """, (hoy,))

    egresos_operativos_historicos = cursor.fetchall()

    ventas_por_semana = {}
    gastos_por_semana = {}
    cobros_semana_pedido = {}
    total_pedido_por_id = {}

    def fecha_simple(valor):
        if hasattr(valor, "date"):
            return valor.date()
        return valor

    def inicio_semana(valor_fecha):
        valor_fecha = fecha_simple(valor_fecha)
        return (
            valor_fecha
            - timedelta(days=valor_fecha.weekday())
        )

    for cobro in cobros_historicos:

        semana = inicio_semana(cobro["fecha"])
        monto = Decimal(str(cobro["monto"] or 0))

        ventas_por_semana[semana] = (
            ventas_por_semana.get(
                semana,
                Decimal("0.00")
            )
            + monto
        )

        pedido_id = cobro.get("pedido_id")
        total_pedido = cobro.get("total_pedido")

        if pedido_id and total_pedido:

            total_pedido_decimal = Decimal(
                str(total_pedido)
            )

            if total_pedido_decimal > 0:

                clave = (
                    semana,
                    pedido_id
                )

                cobros_semana_pedido[clave] = (
                    cobros_semana_pedido.get(
                        clave,
                        Decimal("0.00")
                    )
                    + monto
                )

                total_pedido_por_id[pedido_id] = (
                    total_pedido_decimal
                )

    for egreso in egresos_operativos_historicos:

        semana = inicio_semana(egreso["fecha"])
        monto = Decimal(str(egreso["monto"] or 0))

        gastos_por_semana[semana] = (
            gastos_por_semana.get(
                semana,
                Decimal("0.00")
            )
            + monto
        )

    costos_por_semana = {}

    for (
        semana,
        pedido_id
    ), cobrado_semana in cobros_semana_pedido.items():

        total_pedido = total_pedido_por_id.get(
            pedido_id,
            Decimal("0.00")
        )

        costo_pedido = costos_por_pedido.get(
            pedido_id,
            Decimal("0.00")
        )

        if total_pedido <= 0:
            continue

        proporcion = (
            cobrado_semana
            / total_pedido
        )

        if proporcion > Decimal("1"):
            proporcion = Decimal("1")

        costo_semana = (
            costo_pedido
            * proporcion
        )

        costos_por_semana[semana] = (
            costos_por_semana.get(
                semana,
                Decimal("0.00")
            )
            + costo_semana
        )

    semanas = set(ventas_por_semana.keys())
    semanas.update(gastos_por_semana.keys())
    semanas.update(costos_por_semana.keys())

    ganancia_propietario_acumulada = Decimal("0.00")
    reinversion_acumulada = Decimal("0.00")
    reserva_acumulada = Decimal("0.00")
    utilidad_distribuida_acumulada = Decimal("0.00")

    for semana in sorted(semanas):

        utilidad_semana = (
            ventas_por_semana.get(
                semana,
                Decimal("0.00")
            )
            - costos_por_semana.get(
                semana,
                Decimal("0.00")
            )
            - gastos_por_semana.get(
                semana,
                Decimal("0.00")
            )
        ).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP
        )

        if utilidad_semana <= 0:
            continue

        utilidad_distribuida_acumulada += utilidad_semana

        propietario_semana = (
            utilidad_semana
            * porcentaje_propietario
            / Decimal("100")
        ).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP
        )

        reinversion_semana = (
            utilidad_semana
            * porcentaje_reinversion
            / Decimal("100")
        ).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP
        )

        reserva_semana = (
            utilidad_semana
            - propietario_semana
            - reinversion_semana
        ).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP
        )

        ganancia_propietario_acumulada += propietario_semana
        reinversion_acumulada += reinversion_semana
        reserva_acumulada += reserva_semana

    ganancia_propietario_acumulada = (
        ganancia_propietario_acumulada.quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP
        )
    )

    reinversion_acumulada = (
        reinversion_acumulada.quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP
        )
    )

    reserva_acumulada = (
        reserva_acumulada.quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP
        )
    )

    utilidad_distribuida_acumulada = (
        utilidad_distribuida_acumulada.quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP
        )
    )

    # ========================================================
    # CAJA REAL DEL NEGOCIO
    # ========================================================

    cursor.execute("""
        SELECT
            COALESCE(SUM(monto), 0) AS total
        FROM ingresos
    """)

    ingresos_acumulados = Decimal(
        str(cursor.fetchone()["total"] or 0)
    )

    cursor.execute("""
        SELECT
            COALESCE(SUM(monto), 0) AS total
        FROM egresos
    """)

    egresos_acumulados = Decimal(
        str(cursor.fetchone()["total"] or 0)
    )

    efectivo_neto_registrado = (
        ingresos_acumulados
        - egresos_acumulados
    ).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP
    )

    dinero_abc_disponible = (
        efectivo_neto_registrado
        - ganancia_propietario_acumulada
    ).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP
    )

    # ========================================================
    # FILTRO DE MOVIMIENTOS: MES / AÑO
    # ========================================================

    try:
        mes_filtro = int(
            request.args.get(
                "mes",
                hoy.month
            )
        )
    except (TypeError, ValueError):
        mes_filtro = hoy.month

    try:
        anio_filtro = int(
            request.args.get(
                "anio",
                hoy.year
            )
        )
    except (TypeError, ValueError):
        anio_filtro = hoy.year

    if mes_filtro < 1 or mes_filtro > 12:
        mes_filtro = hoy.month

    if anio_filtro < 2000 or anio_filtro > 2100:
        anio_filtro = hoy.year

    tipo = request.args.get(
        "tipo",
        ""
    ).strip().upper()

    if tipo not in (
        "",
        "INGRESO",
        "EGRESO"
    ):
        tipo = ""

    fecha_desde = date(
        anio_filtro,
        mes_filtro,
        1
    )

    if mes_filtro == 12:
        siguiente_mes = date(
            anio_filtro + 1,
            1,
            1
        )
    else:
        siguiente_mes = date(
            anio_filtro,
            mes_filtro + 1,
            1
        )

    fecha_hasta = (
        siguiente_mes
        - timedelta(days=1)
    )

    meses = [
        (1, "Enero"),
        (2, "Febrero"),
        (3, "Marzo"),
        (4, "Abril"),
        (5, "Mayo"),
        (6, "Junio"),
        (7, "Julio"),
        (8, "Agosto"),
        (9, "Septiembre"),
        (10, "Octubre"),
        (11, "Noviembre"),
        (12, "Diciembre"),
    ]

    cursor.execute("""
        SELECT
            MIN(fecha_minima) AS fecha_minima,
            MAX(fecha_maxima) AS fecha_maxima
        FROM (
            SELECT
                MIN(fecha) AS fecha_minima,
                MAX(fecha) AS fecha_maxima
            FROM ingresos

            UNION ALL

            SELECT
                MIN(fecha) AS fecha_minima,
                MAX(fecha) AS fecha_maxima
            FROM egresos
        ) fechas
    """)

    rango_fechas = cursor.fetchone() or {}

    fecha_minima = fecha_simple(
        rango_fechas.get("fecha_minima")
    )
    fecha_maxima = fecha_simple(
        rango_fechas.get("fecha_maxima")
    )

    anio_minimo = (
        fecha_minima.year
        if fecha_minima
        else hoy.year
    )

    anio_maximo = max(
        hoy.year,
        fecha_maxima.year
        if fecha_maxima
        else hoy.year
    )

    anios_disponibles = list(
        range(
            anio_maximo,
            anio_minimo - 1,
            -1
        )
    )

    if anio_filtro not in anios_disponibles:
        anios_disponibles.append(anio_filtro)
        anios_disponibles.sort(reverse=True)

    condiciones_ingresos = [
        "DATE(i.fecha) BETWEEN %s AND %s"
    ]
    parametros_ingresos = [
        fecha_desde,
        fecha_hasta
    ]

    condiciones_egresos = [
        "DATE(e.fecha) BETWEEN %s AND %s"
    ]
    parametros_egresos = [
        fecha_desde,
        fecha_hasta
    ]

    where_ingresos = (
        "WHERE "
        + " AND ".join(condiciones_ingresos)
    )

    where_egresos = (
        "WHERE "
        + " AND ".join(condiciones_egresos)
    )

    # ========================================================
    # RESUMEN DEL MES SELECCIONADO
    # ========================================================

    cursor.execute(
        f"""
        SELECT
            COALESCE(SUM(i.monto), 0) AS total
        FROM ingresos i
        {where_ingresos}
        """,
        tuple(parametros_ingresos)
    )

    total_ingresos = cursor.fetchone()["total"]

    cursor.execute(
        f"""
        SELECT
            COALESCE(SUM(e.monto), 0) AS total
        FROM egresos e
        {where_egresos}
        """,
        tuple(parametros_egresos)
    )

    total_egresos = cursor.fetchone()["total"]

    cursor.execute(
        f"""
        SELECT
            COALESCE(
                SUM(
                    CASE
                        WHEN UPPER(i.categoria) = 'VENTA'
                        THEN i.monto
                        ELSE 0
                    END
                ),
                0
            ) AS ventas_cobradas,

            COALESCE(
                SUM(
                    CASE
                        WHEN UPPER(i.categoria) != 'VENTA'
                        THEN i.monto
                        ELSE 0
                    END
                ),
                0
            ) AS otros_ingresos

        FROM ingresos i
        {where_ingresos}
        """,
        tuple(parametros_ingresos)
    )

    resumen_ingresos = cursor.fetchone()
    ventas_cobradas = resumen_ingresos["ventas_cobradas"]
    otros_ingresos = resumen_ingresos["otros_ingresos"]

    cursor.execute(
        f"""
        SELECT
            COALESCE(
                SUM(
                    CASE
                        WHEN UPPER(e.categoria) = 'COMPRA'
                        THEN e.monto
                        ELSE 0
                    END
                ),
                0
            ) AS compras_pagadas,

            COALESCE(
                SUM(
                    CASE
                        WHEN UPPER(e.categoria) != 'COMPRA'
                        THEN e.monto
                        ELSE 0
                    END
                ),
                0
            ) AS otros_egresos

        FROM egresos e
        {where_egresos}
        """,
        tuple(parametros_egresos)
    )

    resumen_egresos = cursor.fetchone()
    compras_pagadas = resumen_egresos["compras_pagadas"]
    otros_egresos = resumen_egresos["otros_egresos"]

    # ========================================================
    # MOVIMIENTOS DEL MES SELECCIONADO
    # ========================================================

    consultas = []
    parametros_movimientos = []

    if tipo in (
        "",
        "INGRESO"
    ):

        consultas.append(
            f"""
            SELECT
                i.id,
                i.fecha,
                'INGRESO' AS tipo,
                i.categoria,
                i.descripcion,
                i.monto,
                i.pedido_id,
                i.pago_id AS pago_id,
                NULL AS compra_id,
                p.numero AS pedido_numero,
                NULL AS compra_numero

            FROM ingresos i

            LEFT JOIN pedidos p
                ON i.pedido_id = p.id

            {where_ingresos}
            """
        )

        parametros_movimientos.extend(
            parametros_ingresos
        )

    if tipo in (
        "",
        "EGRESO"
    ):

        consultas.append(
            f"""
            SELECT
                e.id,
                e.fecha,
                'EGRESO' AS tipo,
                e.categoria,
                e.descripcion,
                e.monto,
                e.pedido_id,
                NULL AS pago_id,
                e.compra_id,
                p.numero AS pedido_numero,
                c.numero AS compra_numero

            FROM egresos e

            LEFT JOIN pedidos p
                ON e.pedido_id = p.id

            LEFT JOIN compras c
                ON e.compra_id = c.id

            {where_egresos}
            """
        )

        parametros_movimientos.extend(
            parametros_egresos
        )

    movimientos = []

    if consultas:

        sql_movimientos = (
            " UNION ALL ".join(consultas)
            + " ORDER BY fecha DESC, id DESC"
        )

        cursor.execute(
            sql_movimientos,
            tuple(parametros_movimientos)
        )

        movimientos = cursor.fetchall()

    resultado = (
        Decimal(str(total_ingresos))
        - Decimal(str(total_egresos))
    ).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP
    )

    cursor.close()
    conn.close()

    return render_template(
        "finanzas/index.html",

        # Filtro mensual.
        mes_filtro=mes_filtro,
        anio_filtro=anio_filtro,
        meses=meses,
        anios_disponibles=anios_disponibles,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        tipo_filtro=tipo,

        # Resumen del mes.
        total_ingresos=total_ingresos,
        total_egresos=total_egresos,
        resultado=resultado,
        movimientos=movimientos,
        ventas_cobradas=ventas_cobradas,
        otros_ingresos=otros_ingresos,
        compras_pagadas=compras_pagadas,
        otros_egresos=otros_egresos,

        # Utilidad del período corto.
        periodo_utilidad=periodo_utilidad,
        utilidad_desde=utilidad_desde,
        utilidad_hasta=utilidad_hasta,
        etiqueta_periodo_utilidad=etiqueta_periodo_utilidad,
        ventas_cobradas_utilidad=ventas_cobradas_utilidad,
        otros_ingresos_utilidad=otros_ingresos_utilidad,
        costo_ventas_utilidad=costo_ventas_utilidad,
        gastos_operativos_utilidad=gastos_operativos_utilidad,
        utilidad_real=utilidad_real,
        utilidad_distribuible=utilidad_distribuible,
        ganancia_propietario=ganancia_propietario,
        monto_reinversion=monto_reinversion,
        monto_reserva=monto_reserva,

        # Porcentajes.
        porcentaje_propietario=porcentaje_propietario,
        porcentaje_reinversion=porcentaje_reinversion,
        porcentaje_reserva=porcentaje_reserva,

        # Separación acumulada y caja real.
        utilidad_distribuida_acumulada=utilidad_distribuida_acumulada,
        ganancia_propietario_acumulada=ganancia_propietario_acumulada,
        reinversion_acumulada=reinversion_acumulada,
        reserva_acumulada=reserva_acumulada,
        ingresos_acumulados=ingresos_acumulados,
        egresos_acumulados=egresos_acumulados,
        efectivo_neto_registrado=efectivo_neto_registrado,
        dinero_abc_disponible=dinero_abc_disponible,
    )


# ============================================================
# NUEVO INGRESO MANUAL
# ============================================================

@finanzas_bp.route(
    "/ingresos/nuevo",
    methods=["GET", "POST"]
)
def nuevo_ingreso():

    if request.method == "POST":

        conn = obtener_conexion()
        cursor = conn.cursor()

        try:

            monto = Decimal(
                request.form.get("monto", "0")
            )

            categoria = request.form.get(
                "categoria",
                ""
            ).strip().title()

            fecha = request.form.get(
                "fecha"
            ) or None

            descripcion = request.form.get(
                "descripcion",
                ""
            ).strip() or None


            if monto <= 0:

                raise ValueError(
                    "El monto debe ser mayor que cero."
                )


            if not categoria:

                raise ValueError(
                    "La categoría es obligatoria."
                )


            cursor.execute("""
                INSERT INTO ingresos (
                    pedido_id,
                    pago_id,
                    usuario_id,
                    categoria,
                    monto,
                    fecha,
                    descripcion
                )
                VALUES (
                    NULL,
                    NULL,
                    %s,
                    %s,
                    %s,
                    COALESCE(%s, NOW()),
                    %s
                )
            """, (
                8,
                categoria,
                monto,
                fecha,
                descripcion
            ))

            conn.commit()

            flash(
                "Ingreso registrado correctamente.",
                "success"
            )

            return redirect(
                url_for("finanzas.index")
            )


        except Exception as e:

            conn.rollback()

            flash(
                f"No se pudo registrar el ingreso: {e}",
                "danger"
            )


        finally:

            cursor.close()
            conn.close()


    return render_template(
        "finanzas/nuevo_ingreso.html"
    )


# ============================================================
# NUEVO EGRESO MANUAL
# ============================================================

@finanzas_bp.route(
    "/egresos/nuevo",
    methods=["GET", "POST"]
)
def nuevo_egreso():

    if request.method == "POST":

        conn = obtener_conexion()
        cursor = conn.cursor()

        try:

            monto = Decimal(
                request.form.get("monto", "0")
            )

            categoria = request.form.get(
                "categoria",
                ""
            ).strip().title()

            fecha = request.form.get(
                "fecha"
            ) or None

            descripcion = request.form.get(
                "descripcion",
                ""
            ).strip() or None


            if monto <= 0:

                raise ValueError(
                    "El monto debe ser mayor que cero."
                )


            if not categoria:

                raise ValueError(
                    "La categoría es obligatoria."
                )


            cursor.execute("""
                INSERT INTO egresos (
                    pedido_id,
                    proveedor_id,
                    compra_id,
                    usuario_id,
                    categoria,
                    monto,
                    fecha,
                    descripcion
                )
                VALUES (
                    NULL,
                    NULL,
                    NULL,
                    %s,
                    %s,
                    %s,
                    COALESCE(%s, NOW()),
                    %s
                )
            """, (
                8,
                categoria,
                monto,
                fecha,
                descripcion
            ))

            conn.commit()

            flash(
                "Egreso registrado correctamente.",
                "success"
            )

            return redirect(
                url_for("finanzas.index")
            )


        except Exception as e:

            conn.rollback()

            flash(
                f"No se pudo registrar el egreso: {e}",
                "danger"
            )


        finally:

            cursor.close()
            conn.close()


    return render_template(
        "finanzas/nuevo_egreso.html"
    )

# ============================================================
# EDITAR INGRESO MANUAL
# ============================================================

@finanzas_bp.route(
    "/ingresos/<int:ingreso_id>/editar",
    methods=["GET", "POST"]
)
def editar_ingreso(ingreso_id):

    conn = obtener_conexion()
    cursor = conn.cursor(dictionary=True)

    try:

        cursor.execute("""
            SELECT
                id,
                pedido_id,
                pago_id,
                categoria,
                monto,
                fecha,
                descripcion
            FROM ingresos
            WHERE id = %s
        """, (ingreso_id,))

        ingreso = cursor.fetchone()

        if not ingreso:
            raise ValueError(
                "El ingreso no existe."
            )

        if ingreso["pedido_id"] is not None or ingreso["pago_id"] is not None:
            raise ValueError(
                "Este ingreso fue generado automáticamente "
                "y no puede editarse desde Finanzas."
            )

        if request.method == "POST":

            monto = Decimal(
                request.form.get("monto", "0")
            )

            categoria = request.form.get(
                "categoria",
                ""
            ).strip().title()

            fecha = request.form.get("fecha") or None

            descripcion = request.form.get(
                "descripcion",
                ""
            ).strip() or None

            if monto <= 0:
                raise ValueError(
                    "El monto debe ser mayor que cero."
                )

            if not categoria:
                raise ValueError(
                    "La categoría es obligatoria."
                )

            cursor.execute("""
                UPDATE ingresos
                SET
                    categoria = %s,
                    monto = %s,
                    fecha = COALESCE(%s, fecha),
                    descripcion = %s
                WHERE id = %s
            """, (
                categoria,
                monto,
                fecha,
                descripcion,
                ingreso_id
            ))

            conn.commit()

            flash(
                "Ingreso actualizado correctamente.",
                "success"
            )

            return redirect(
                url_for("finanzas.index")
            )

        return render_template(
            "finanzas/editar_ingreso.html",
            ingreso=ingreso
        )

    except Exception as e:

        conn.rollback()

        flash(
            f"No se pudo editar el ingreso: {e}",
            "danger"
        )

        return redirect(
            url_for("finanzas.index")
        )

    finally:

        cursor.close()
        conn.close()


# ============================================================
# ELIMINAR INGRESO MANUAL
# ============================================================

@finanzas_bp.route(
    "/ingresos/<int:ingreso_id>/eliminar",
    methods=["POST"]
)
def eliminar_ingreso(ingreso_id):

    conn = obtener_conexion()
    cursor = conn.cursor(dictionary=True)

    try:

        cursor.execute("""
            SELECT
                id,
                pedido_id,
                pago_id
            FROM ingresos
            WHERE id = %s
        """, (ingreso_id,))

        ingreso = cursor.fetchone()

        if not ingreso:
            raise ValueError(
                "El ingreso no existe."
            )

        if ingreso["pedido_id"] is not None or ingreso["pago_id"] is not None:
            raise ValueError(
                "Este ingreso fue generado automáticamente "
                "y no puede eliminarse."
            )

        cursor.execute("""
            DELETE FROM ingresos
            WHERE id = %s
        """, (ingreso_id,))

        conn.commit()

        flash(
            "Ingreso eliminado correctamente.",
            "success"
        )

    except Exception as e:

        conn.rollback()

        flash(
            f"No se pudo eliminar el ingreso: {e}",
            "danger"
        )

    finally:

        cursor.close()
        conn.close()

    return redirect(
        url_for("finanzas.index")
    )


# ============================================================
# EDITAR EGRESO MANUAL
# ============================================================

@finanzas_bp.route(
    "/egresos/<int:egreso_id>/editar",
    methods=["GET", "POST"]
)
def editar_egreso(egreso_id):

    conn = obtener_conexion()
    cursor = conn.cursor(dictionary=True)

    try:

        cursor.execute("""
            SELECT
                id,
                pedido_id,
                proveedor_id,
                compra_id,
                categoria,
                monto,
                fecha,
                descripcion
            FROM egresos
            WHERE id = %s
        """, (egreso_id,))

        egreso = cursor.fetchone()

        if not egreso:
            raise ValueError(
                "El egreso no existe."
            )

        if egreso["compra_id"] is not None or egreso["pedido_id"] is not None:
            raise ValueError(
                "Este egreso fue generado automáticamente "
                "y no puede editarse desde Finanzas."
            )

        if request.method == "POST":

            monto = Decimal(
                request.form.get("monto", "0")
            )

            categoria = request.form.get(
                "categoria",
                ""
            ).strip().title()

            fecha = request.form.get("fecha") or None

            descripcion = request.form.get(
                "descripcion",
                ""
            ).strip() or None

            if monto <= 0:
                raise ValueError(
                    "El monto debe ser mayor que cero."
                )

            if not categoria:
                raise ValueError(
                    "La categoría es obligatoria."
                )

            cursor.execute("""
                UPDATE egresos
                SET
                    categoria = %s,
                    monto = %s,
                    fecha = COALESCE(%s, fecha),
                    descripcion = %s
                WHERE id = %s
            """, (
                categoria,
                monto,
                fecha,
                descripcion,
                egreso_id
            ))

            conn.commit()

            flash(
                "Egreso actualizado correctamente.",
                "success"
            )

            return redirect(
                url_for("finanzas.index")
            )

        return render_template(
            "finanzas/editar_egreso.html",
            egreso=egreso
        )

    except Exception as e:

        conn.rollback()

        flash(
            f"No se pudo editar el egreso: {e}",
            "danger"
        )

        return redirect(
            url_for("finanzas.index")
        )

    finally:

        cursor.close()
        conn.close()


# ============================================================
# ELIMINAR EGRESO MANUAL
# ============================================================

@finanzas_bp.route(
    "/egresos/<int:egreso_id>/eliminar",
    methods=["POST"]
)
def eliminar_egreso(egreso_id):

    conn = obtener_conexion()
    cursor = conn.cursor(dictionary=True)

    try:

        cursor.execute("""
            SELECT
                id,
                pedido_id,
                compra_id
            FROM egresos
            WHERE id = %s
        """, (egreso_id,))

        egreso = cursor.fetchone()

        if not egreso:
            raise ValueError(
                "El egreso no existe."
            )

        if egreso["compra_id"] is not None or egreso["pedido_id"] is not None:
            raise ValueError(
                "Este egreso fue generado automáticamente "
                "y no puede eliminarse."
            )

        cursor.execute("""
            DELETE FROM egresos
            WHERE id = %s
        """, (egreso_id,))

        conn.commit()

        flash(
            "Egreso eliminado correctamente.",
            "success"
        )

    except Exception as e:

        conn.rollback()

        flash(
            f"No se pudo eliminar el egreso: {e}",
            "danger"
        )

    finally:

        cursor.close()
        conn.close()

    return redirect(
        url_for("finanzas.index")
    )