from flask import Blueprint, render_template, request, redirect, url_for, flash
from database import obtener_conexion
from decimal import Decimal, ROUND_HALF_UP


producciones_bp = Blueprint(
    "producciones",
    __name__,
    url_prefix="/producciones"
)


# ============================================================
# UTILIDADES DE PRESENTACIÓN
# ============================================================

@producciones_bp.app_template_filter("numero_produccion")
def numero_produccion(valor):

    if valor is None:
        return "0"

    try:
        numero = Decimal(str(valor))
    except Exception:
        return str(valor)

    texto = f"{numero:.4f}".rstrip("0").rstrip(".")

    return texto if texto else "0"




# ============================================================
# LISTA DE PRODUCCIONES
# ============================================================

@producciones_bp.route("/")
def lista():

    busqueda = request.args.get(
        "q",
        ""
    ).strip()

    filtro = request.args.get(
        "filtro",
        "todos"
    ).strip().lower()

    filtros_validos = {
        "todos",
        "pendiente",
        "en_produccion",
        "terminado",
        "interna",
        "externa"
    }

    if filtro not in filtros_validos:
        filtro = "todos"


    conn = obtener_conexion()
    cursor = conn.cursor(dictionary=True)


    condiciones = []
    parametros = []


    # --------------------------------------------------------
    # BUSCADOR
    # --------------------------------------------------------

    if busqueda:

        termino = f"%{busqueda}%"

        condiciones.append("""
            (
                CAST(pr.id AS CHAR) LIKE %s
                OR pe.numero LIKE %s
                OR c.nombre LIKE %s
                OR p.nombre LIKE %s
            )
        """)

        parametros.extend([
            termino,
            termino,
            termino,
            termino
        ])


    # --------------------------------------------------------
    # FILTROS
    # --------------------------------------------------------

    if filtro == "pendiente":

        condiciones.append(
            "pr.estado = 'PENDIENTE'"
        )

    elif filtro == "en_produccion":

        condiciones.append(
            "pr.estado = 'EN_PRODUCCION'"
        )

    elif filtro == "terminado":

        condiciones.append(
            "pr.estado = 'TERMINADO'"
        )

    elif filtro == "interna":

        condiciones.append(
            "pr.tipo = 'INTERNA'"
        )

    elif filtro == "externa":

        condiciones.append(
            "pr.tipo = 'EXTERNA'"
        )


    where_sql = ""

    if condiciones:

        where_sql = (
            "WHERE "
            + " AND ".join(condiciones)
        )


    # --------------------------------------------------------
    # LISTADO
    # --------------------------------------------------------

    cursor.execute(
        f"""
        SELECT
            pr.id,
            pr.tipo,
            pr.estado,
            pr.diseno_aprobado,
            pr.fecha_inicio,
            pr.fecha_terminado,
            pr.costo_estimado,
            pr.costo_real,

            dp.id AS detalle_pedido_id,
            dp.cantidad,
            dp.precio_unitario,

            p.id AS producto_id,
            p.nombre AS producto,

            pe.id AS pedido_id,
            pe.numero AS pedido,
            pe.fecha_entrega,

            c.id AS cliente_id,
            c.nombre AS cliente

        FROM producciones pr

        INNER JOIN detalle_pedido dp
            ON pr.detalle_pedido_id = dp.id

        INNER JOIN productos p
            ON dp.producto_id = p.id

        INNER JOIN pedidos pe
            ON dp.pedido_id = pe.id

        INNER JOIN clientes c
            ON pe.cliente_id = c.id

        {where_sql}

        ORDER BY pr.id DESC
        """,
        tuple(parametros)
    )

    producciones = cursor.fetchall()


    # --------------------------------------------------------
    # CONTADORES
    # --------------------------------------------------------

    cursor.execute("""
        SELECT
            COUNT(*) AS todos,

            SUM(
                CASE
                    WHEN estado = 'PENDIENTE'
                    THEN 1
                    ELSE 0
                END
            ) AS pendientes,

            SUM(
                CASE
                    WHEN estado = 'EN_PRODUCCION'
                    THEN 1
                    ELSE 0
                END
            ) AS en_produccion,

            SUM(
                CASE
                    WHEN estado = 'TERMINADO'
                    THEN 1
                    ELSE 0
                END
            ) AS terminadas,

            SUM(
                CASE
                    WHEN tipo = 'INTERNA'
                    THEN 1
                    ELSE 0
                END
            ) AS internas,

            SUM(
                CASE
                    WHEN tipo = 'EXTERNA'
                    THEN 1
                    ELSE 0
                END
            ) AS externas

        FROM producciones
    """)

    contadores = cursor.fetchone()


    cursor.close()
    conn.close()


    return render_template(
        "producciones/lista.html",
        producciones=producciones,
        busqueda=busqueda,
        filtro=filtro,
        contadores=contadores
    )


# ============================================================
# CREAR PRODUCCIÓN DESDE UN DETALLE DE PEDIDO
# ============================================================

@producciones_bp.route(
    "/crear/<int:detalle_pedido_id>",
    methods=["POST"]
)

def crear(detalle_pedido_id):

    conn = obtener_conexion()
    cursor = conn.cursor(dictionary=True)

    detalle = None

    try:

        # ----------------------------------------------------
        # Verificar detalle del pedido
        # ----------------------------------------------------

        cursor.execute("""
            SELECT
                dp.id,
                dp.pedido_id,
                dp.producto_id,
                dp.cantidad,
                p.nombre AS producto,
                p.metodo_produccion
            FROM detalle_pedido dp

            INNER JOIN productos p
                ON dp.producto_id = p.id

            WHERE dp.id = %s
        """, (detalle_pedido_id,))

        detalle = cursor.fetchone()

        if not detalle:
            raise ValueError(
                "El producto del pedido no existe."
            )

        # ----------------------------------------------------
        # Verificar producción existente
        # ----------------------------------------------------

        cursor.execute("""
            SELECT id
            FROM producciones
            WHERE detalle_pedido_id = %s
              AND estado != 'CANCELADO'
            LIMIT 1
        """, (detalle_pedido_id,))

        produccion_existente = cursor.fetchone()

        if produccion_existente:
            raise ValueError(
                "Este producto ya tiene una producción registrada."
            )

        # ----------------------------------------------------
        # Confirmar automáticamente el pedido
        # ----------------------------------------------------

        cursor.execute("""
            SELECT estado
            FROM pedidos
            WHERE id = %s
            FOR UPDATE
        """, (detalle["pedido_id"],))

        pedido = cursor.fetchone()

        if not pedido:
            raise ValueError(
                "El pedido asociado no existe."
            )

        if pedido["estado"] == "COTIZACION":

            cursor.execute("""
                UPDATE pedidos
                SET estado = 'CONFIRMADO'
                WHERE id = %s
            """, (detalle["pedido_id"],))

        # ----------------------------------------------------
        # Determinar tipo de producción
        # ----------------------------------------------------

        tipo = detalle["metodo_produccion"]

        if tipo not in ("INTERNA", "EXTERNA"):
            tipo = "INTERNA"

        # ----------------------------------------------------
        # Crear producción
        # ----------------------------------------------------

        cursor.execute("""
            INSERT INTO producciones
            (
                detalle_pedido_id,
                tipo,
                estado,
                costo_estimado
            )
            VALUES
            (
                %s,
                %s,
                'PENDIENTE',
                0.00
            )
        """, (
            detalle_pedido_id,
            tipo
        ))

        conn.commit()

        flash(
            f"Producción creada para '{detalle['producto']}'.",
            "success"
        )

    except Exception as e:

        conn.rollback()

        flash(
            f"No se pudo crear la producción: {e}",
            "danger"
        )

    finally:

        cursor.close()
        conn.close()

    return redirect(
        url_for(
            "pedidos.detalle",
            pedido_id=detalle["pedido_id"]
            if detalle
            else 1
        )
    )

# ============================================================
# DETALLE DE PRODUCCIÓN
# ============================================================

@producciones_bp.route("/<int:produccion_id>")
def detalle(produccion_id):

    conn = obtener_conexion()
    cursor = conn.cursor(dictionary=True)

    # ========================================================
    # INFORMACIÓN PRINCIPAL
    # ========================================================

    cursor.execute("""
        SELECT
            pr.*,

            dp.cantidad,
            dp.precio_unitario,
            dp.subtotal,
            dp.costo_real AS detalle_costo_real,
            dp.ganancia AS detalle_ganancia,
            dp.texto_personalizado,
            dp.ancho,
            dp.alto,
            dp.largo,
            dp.notas AS notas_producto,

            p.id AS producto_id,
            p.nombre AS producto,

            pe.id AS pedido_id,
            pe.numero AS pedido,
            pe.estado AS estado_pedido,
            pe.fecha_entrega,

            c.id AS cliente_id,
            c.nombre AS cliente,
            c.telefono,
            c.email,

            prov.nombre AS proveedor

        FROM producciones pr

        INNER JOIN detalle_pedido dp
            ON pr.detalle_pedido_id = dp.id

        INNER JOIN productos p
            ON dp.producto_id = p.id

        INNER JOIN pedidos pe
            ON dp.pedido_id = pe.id

        INNER JOIN clientes c
            ON pe.cliente_id = c.id

        LEFT JOIN proveedores prov
            ON pr.proveedor_id = prov.id

        WHERE pr.id = %s
    """, (produccion_id,))

    produccion = cursor.fetchone()

    if not produccion:

        cursor.close()
        conn.close()

        return "Producción no encontrada", 404

    # ========================================================
    # MATERIALES DE LA RECETA
    # ========================================================

    materiales = []

    if produccion["tipo"] == "INTERNA":

        cursor.execute("""
            SELECT
                pm.id AS receta_id,
                pm.modo_seleccion,
                pm.material_id,
                pm.familia_material_id,
                pm.cantidad,
                pm.es_estimado,
                pm.notas,

                m.nombre AS material,
                m.color AS material_color,
                m.modo_control,
                m.stock_actual,
                m.cantidad_por_compra,
                m.costo_compra_referencia,
                m.unidad_consumo_id,

                u.id AS unidad_id,
                u.nombre AS unidad,
                u.abreviatura,
                u.tipo AS unidad_tipo,
                u.factor_conversion,

                fm.nombre AS familia,
                fm.codigo AS familia_codigo

            FROM producto_materiales pm

            LEFT JOIN materiales m
                ON pm.material_id = m.id

            LEFT JOIN unidades_medida u
                ON m.unidad_consumo_id = u.id

            LEFT JOIN familias_materiales fm
                ON pm.familia_material_id = fm.id

            WHERE pm.producto_id = %s

            ORDER BY pm.id ASC
        """, (
            produccion["producto_id"],
        ))

        materiales = cursor.fetchall()

        cantidad_producto = Decimal(
            str(
                produccion["cantidad"]
                or 0
            )
        )

        ancho_pedido = (
            Decimal(str(produccion["ancho"]))
            if produccion["ancho"] is not None
            else None
        )

        alto_pedido = (
            Decimal(str(produccion["alto"]))
            if produccion["alto"] is not None
            else None
        )

        costo_estimado = Decimal("0.00")

        for receta in materiales:

            receta["opciones_materiales"] = []
            receta["cantidad_necesaria"] = None
            receta["costo_total"] = None
            receta["medida_sugerida"] = False
            receta["ancho_sugerido"] = ancho_pedido
            receta["alto_sugerido"] = alto_pedido

            # ------------------------------------------------
            # MATERIAL EXACTO
            # ------------------------------------------------

            if receta["modo_seleccion"] == "EXACTO":

                if not receta["material_id"]:
                    continue

                receta["opciones_materiales"] = [{
                    "id": receta["material_id"],
                    "nombre": receta["material"],
                    "color": receta["material_color"],
                    "modo_control": receta["modo_control"],
                    "stock_actual": receta["stock_actual"],
                    "unidad_id": receta["unidad_id"],
                    "unidad": receta["unidad"],
                    "abreviatura": receta["abreviatura"],
                    "unidad_tipo": receta["unidad_tipo"],
                    "factor_conversion": receta["factor_conversion"],
                    "cantidad_por_compra": receta["cantidad_por_compra"],
                    "costo_compra_referencia": receta["costo_compra_referencia"],
                }]

                cantidad_base = Decimal(
                    str(
                        receta["cantidad"]
                        or 0
                    )
                )

                costo_unitario = Decimal("0")

                cantidad_por_compra = Decimal(
                    str(
                        receta["cantidad_por_compra"]
                        or 0
                    )
                )

                costo_compra = Decimal(
                    str(
                        receta["costo_compra_referencia"]
                        or 0
                    )
                )

                if cantidad_por_compra > 0:
                    costo_unitario = (
                        costo_compra
                        / cantidad_por_compra
                    )

                if (
                    receta["modo_control"] == "ROLLO_AREA"
                    and receta["unidad_tipo"] == "AREA"
                    and ancho_pedido is not None
                    and alto_pedido is not None
                    and ancho_pedido > 0
                    and alto_pedido > 0
                ):

                    factor = Decimal(
                        str(
                            receta["factor_conversion"]
                            or 1
                        )
                    )

                    cantidad_necesaria = (
                        ancho_pedido
                        * alto_pedido
                        / factor
                        * cantidad_producto
                    )

                    receta["medida_sugerida"] = True

                else:

                    cantidad_necesaria = (
                        cantidad_base
                        * cantidad_producto
                    )

                receta["cantidad_necesaria"] = (
                    cantidad_necesaria
                )

                receta["costo_total"] = (
                    cantidad_necesaria
                    * costo_unitario
                )

                costo_estimado += (
                    receta["costo_total"]
                )

            # ------------------------------------------------
            # FAMILIA: material real se elige al producir
            # ------------------------------------------------

            else:

                cursor.execute("""
                    SELECT
                        m.id,
                        m.nombre,
                        m.color,
                        m.modo_control,
                        m.stock_actual,
                        m.cantidad_por_compra,
                        m.costo_compra_referencia,
                        m.unidad_consumo_id,

                        u.nombre AS unidad,
                        u.abreviatura,
                        u.tipo AS unidad_tipo,
                        u.factor_conversion

                    FROM materiales m

                    INNER JOIN unidades_medida u
                        ON m.unidad_consumo_id = u.id

                    WHERE m.familia_id = %s
                      AND m.activo = 1

                    ORDER BY
                        m.nombre ASC,
                        m.color ASC
                """, (
                    receta["familia_material_id"],
                ))

                receta["opciones_materiales"] = (
                    cursor.fetchall()
                )

                # La cantidad exacta/costo dependen del material
                # que se elija en Producción.
                receta["cantidad_necesaria"] = None
                receta["costo_total"] = None

        cursor.execute("""
            UPDATE producciones
            SET costo_estimado = %s
            WHERE id = %s
        """, (
            costo_estimado,
            produccion_id
        ))

        conn.commit()

        produccion["costo_estimado"] = (
            costo_estimado
        )

    # ========================================================
    # CONSUMOS REALES DE LOTES
    # ========================================================

    cursor.execute("""
        SELECT
            cp.id,
            cp.cantidad,
            cp.costo_unitario,
            cp.costo_total,
            cp.fecha,

            m.nombre AS material,

            um.nombre AS unidad,
            um.abreviatura,

            cp.lote_id

        FROM consumos_produccion cp

        INNER JOIN materiales m
            ON cp.material_id = m.id

        INNER JOIN unidades_medida um
            ON cp.unidad_id = um.id

        WHERE cp.produccion_id = %s

        ORDER BY
            cp.fecha ASC,
            cp.id ASC
    """, (produccion_id,))

    consumos = cursor.fetchall()

    costo_consumos = sum(
        Decimal(
            str(
                consumo["costo_total"]
                or 0
            )
        )
        for consumo in consumos
    )

    # ========================================================
    # PROVEEDORES DISPONIBLES PARA PRODUCCIÓN EXTERNA
    # ========================================================

    proveedores = []

    if produccion["tipo"] == "EXTERNA":

        cursor.execute("""
            SELECT
                id,
                nombre
            FROM proveedores
            WHERE activo = 1
            ORDER BY nombre ASC
        """)

        proveedores = cursor.fetchall()

    # ========================================================
    # RENTABILIDAD DE ESTA PRODUCCIÓN
    # ========================================================

    venta = Decimal(
        str(
            produccion["subtotal"]
            or 0
        )
    )

    costo_real = (
        Decimal(
            str(produccion["costo_real"])
        )
        if produccion["costo_real"]
        is not None
        else None
    )

    if costo_real is not None:

        ganancia = venta - costo_real

        margen = (
            ganancia
            / venta
            * Decimal("100")
            if venta > 0
            else Decimal("0")
        )

    else:

        ganancia = None
        margen = None

    cursor.close()
    conn.close()

    return render_template(
        "producciones/detalle.html",

        produccion=produccion,
        materiales=materiales,
        consumos=consumos,
        costo_consumos=costo_consumos,
        proveedores=proveedores,

        ganancia_produccion=ganancia,
        margen_produccion=margen
    )


# ============================================================
# INICIAR PRODUCCIÓN
# ============================================================

@producciones_bp.route(
    "/<int:produccion_id>/iniciar",
    methods=["POST"]
)
def iniciar(produccion_id):

    conn = obtener_conexion()
    cursor = conn.cursor(dictionary=True)

    try:

        # ----------------------------------------------------
        # Obtener producción y pedido relacionado
        # ----------------------------------------------------

        cursor.execute("""
            SELECT
                pr.id,
                pr.estado,
                dp.pedido_id
            FROM producciones pr

            INNER JOIN detalle_pedido dp
                ON pr.detalle_pedido_id = dp.id

            WHERE pr.id = %s
            FOR UPDATE
        """, (produccion_id,))

        produccion = cursor.fetchone()

        if not produccion:
            raise ValueError(
                "La producción no existe."
            )

        if produccion["estado"] != "PENDIENTE":
            raise ValueError(
                "Solo se puede iniciar una producción pendiente."
            )

        pedido_id = produccion["pedido_id"]

        # ----------------------------------------------------
        # Iniciar producción
        # ----------------------------------------------------

        cursor.execute("""
            UPDATE producciones
            SET
                estado = 'EN_PRODUCCION',
                fecha_inicio = NOW()
            WHERE id = %s
        """, (produccion_id,))

        # ----------------------------------------------------
        # Actualizar estado del pedido
        # ----------------------------------------------------

        cursor.execute("""
            UPDATE pedidos
            SET estado = 'EN PRODUCCION'
            WHERE id = %s
              AND estado = 'CONFIRMADO'
        """, (pedido_id,))

        conn.commit()

        flash(
            "Producción iniciada correctamente. "
            "El pedido ahora está en producción.",
            "success"
        )

    except Exception as e:

        conn.rollback()

        flash(
            f"No se pudo iniciar la producción: {e}",
            "danger"
        )

    finally:

        cursor.close()
        conn.close()

    return redirect(
        url_for(
            "producciones.detalle",
            produccion_id=produccion_id
        )
    )

# ============================================================
# CONSUMIR MATERIALES DE LA PRODUCCIÓN
# ============================================================

@producciones_bp.route(
    "/<int:produccion_id>/consumir-materiales",
    methods=["POST"]
)
def consumir_materiales(produccion_id):

    conn = obtener_conexion()
    cursor = conn.cursor(dictionary=True)

    try:

        # ====================================================
        # PRODUCCIÓN
        # ====================================================

        cursor.execute("""
            SELECT
                pr.id,
                pr.tipo,
                pr.estado,
                pr.detalle_pedido_id,

                dp.producto_id,
                dp.cantidad,
                dp.ancho,
                dp.alto,
                dp.largo

            FROM producciones pr

            INNER JOIN detalle_pedido dp
                ON pr.detalle_pedido_id = dp.id

            WHERE pr.id = %s

            FOR UPDATE
        """, (produccion_id,))

        produccion = cursor.fetchone()

        if not produccion:
            raise ValueError(
                "La producción no existe."
            )

        if produccion["tipo"] != "INTERNA":
            raise ValueError(
                "Solo las producciones internas "
                "consumen materiales del inventario."
            )

        if produccion["estado"] != "EN_PRODUCCION":
            raise ValueError(
                "La producción debe estar en producción "
                "antes de consumir materiales."
            )

        cantidad_producto = Decimal(
            str(
                produccion["cantidad"]
                or 0
            )
        )

        # ====================================================
        # EVITAR CONSUMO DOBLE
        # ====================================================

        cursor.execute("""
            SELECT COUNT(*) AS total
            FROM movimientos_inventario
            WHERE tipo = 'CONSUMO'
              AND referencia_tipo = 'PRODUCCION'
              AND referencia_id = %s
        """, (produccion_id,))

        if cursor.fetchone()["total"] > 0:
            raise ValueError(
                "Los materiales de esta producción "
                "ya fueron consumidos."
            )

        # ====================================================
        # RECETA
        # ====================================================

        cursor.execute("""
            SELECT
                pm.id AS receta_id,
                pm.modo_seleccion,
                pm.material_id,
                pm.familia_material_id,
                pm.cantidad,
                pm.es_estimado,
                pm.notas,

                fm.nombre AS familia

            FROM producto_materiales pm

            LEFT JOIN familias_materiales fm
                ON pm.familia_material_id = fm.id

            WHERE pm.producto_id = %s

            ORDER BY pm.id ASC
        """, (
            produccion["producto_id"],
        ))

        recetas = cursor.fetchall()

        if not recetas:
            raise ValueError(
                "Este producto no tiene materiales definidos."
            )

        costo_total_real = Decimal("0.00")

        # ====================================================
        # PROCESAR CADA REQUERIMIENTO DE LA RECETA
        # ====================================================

        for receta in recetas:

            # ------------------------------------------------
            # Elegir material real
            # ------------------------------------------------

            if receta["modo_seleccion"] == "FAMILIA":

                material_real_texto = (
                    request.form.get(
                        f"material_real_{receta['receta_id']}",
                        ""
                    )
                    .strip()
                )

                if not material_real_texto:
                    raise ValueError(
                        f"Debes elegir el material real para "
                        f"la familia {receta['familia']}."
                    )

                material_real_id = int(
                    material_real_texto
                )

                cursor.execute("""
                    SELECT
                        m.id,
                        m.nombre,
                        m.color,
                        m.modo_control,
                        m.stock_actual,
                        m.unidad_consumo_id,

                        u.nombre AS unidad,
                        u.abreviatura,
                        u.tipo AS unidad_tipo,
                        u.factor_conversion

                    FROM materiales m

                    INNER JOIN unidades_medida u
                        ON m.unidad_consumo_id = u.id

                    WHERE m.id = %s
                      AND m.familia_id = %s
                      AND m.activo = 1

                    FOR UPDATE
                """, (
                    material_real_id,
                    receta["familia_material_id"]
                ))

            else:

                if not receta["material_id"]:
                    raise ValueError(
                        "Una receta de material exacto "
                        "no tiene material asociado."
                    )

                cursor.execute("""
                    SELECT
                        m.id,
                        m.nombre,
                        m.color,
                        m.modo_control,
                        m.stock_actual,
                        m.unidad_consumo_id,

                        u.nombre AS unidad,
                        u.abreviatura,
                        u.tipo AS unidad_tipo,
                        u.factor_conversion

                    FROM materiales m

                    INNER JOIN unidades_medida u
                        ON m.unidad_consumo_id = u.id

                    WHERE m.id = %s
                      AND m.activo = 1

                    FOR UPDATE
                """, (
                    receta["material_id"],
                ))

            material = cursor.fetchone()

            if not material:
                raise ValueError(
                    "El material seleccionado no existe, "
                    "está inactivo o no pertenece a la familia requerida."
                )

            material_id = material["id"]
            unidad_id = material["unidad_consumo_id"]

            # ------------------------------------------------
            # Cantidad REAL a consumir
            # ------------------------------------------------

            if material["modo_control"] == "ROLLO_AREA":

                if material["unidad_tipo"] != "AREA":
                    raise ValueError(
                        f"'{material['nombre']}' está configurado "
                        "como rollo por área, pero su unidad de "
                        "consumo no es de tipo AREA."
                    )

                ancho_texto = (
                    request.form.get(
                        f"ancho_real_{receta['receta_id']}",
                        ""
                    )
                    .strip()
                )

                alto_texto = (
                    request.form.get(
                        f"alto_real_{receta['receta_id']}",
                        ""
                    )
                    .strip()
                )

                if not ancho_texto or not alto_texto:
                    raise ValueError(
                        f"Debes indicar ancho y alto reales "
                        f"para {material['nombre']}."
                    )

                ancho_real = Decimal(
                    ancho_texto
                )

                alto_real = Decimal(
                    alto_texto
                )

                if ancho_real <= 0 or alto_real <= 0:
                    raise ValueError(
                        f"Las medidas reales de "
                        f"{material['nombre']} deben ser mayores que 0."
                    )

                factor_area = Decimal(
                    str(
                        material["factor_conversion"]
                        or 1
                    )
                )

                if factor_area <= 0:
                    raise ValueError(
                        f"La unidad de consumo de "
                        f"{material['nombre']} tiene un factor inválido."
                    )

                area_real_cm2_por_unidad = (
                    ancho_real
                    * alto_real
                )

                cantidad_necesaria = (
                    area_real_cm2_por_unidad
                    / factor_area
                    * cantidad_producto
                )

                detalle_consumo = (
                    f"Corte real: {ancho_real} x {alto_real} cm "
                    f"por unidad; cantidad producto: {cantidad_producto}"
                )

            else:

                cantidad_por_producto = Decimal(
                    str(
                        receta["cantidad"]
                        or 0
                    )
                )

                cantidad_necesaria = (
                    cantidad_por_producto
                    * cantidad_producto
                )

                detalle_consumo = (
                    f"Consumo según receta: "
                    f"{cantidad_por_producto} "
                    f"{material['abreviatura']} por unidad"
                )

            if cantidad_necesaria <= 0:
                continue

            stock_actual = Decimal(
                str(
                    material["stock_actual"]
                    or 0
                )
            )

            if cantidad_necesaria > stock_actual:
                raise ValueError(
                    f"Stock insuficiente de "
                    f"{material['nombre']}. "
                    f"Necesario: {cantidad_necesaria} "
                    f"{material['abreviatura']}. "
                    f"Disponible: {stock_actual}."
                )

            # ------------------------------------------------
            # LOTES FIFO
            # ------------------------------------------------

            cursor.execute("""
                SELECT
                    id,
                    cantidad_actual,
                    costo_unitario

                FROM lotes_inventario

                WHERE material_id = %s
                  AND activo = 1
                  AND cantidad_actual > 0

                ORDER BY id ASC

                FOR UPDATE
            """, (
                material_id,
            ))

            lotes = cursor.fetchall()

            cantidad_restante = (
                cantidad_necesaria
            )

            costo_material = Decimal("0.00")

            for lote in lotes:

                if (
                    cantidad_restante
                    <= Decimal("0.000001")
                ):
                    break

                cantidad_lote = Decimal(
                    str(
                        lote["cantidad_actual"]
                        or 0
                    )
                )

                costo_unitario = Decimal(
                    str(
                        lote["costo_unitario"]
                        or 0
                    )
                )

                cantidad_consumir = min(
                    cantidad_restante,
                    cantidad_lote
                )

                # El costo monetario de cada fragmento de lote
                # se fija a centavos. Así el desglose visible y el
                # costo real final siempre suman exactamente lo mismo.
                costo_fragmento = (
                    cantidad_consumir
                    * costo_unitario
                ).quantize(
                    Decimal("0.01"),
                    rounding=ROUND_HALF_UP
                )

                costo_material += (
                    costo_fragmento
                )

                costo_total_real += (
                    costo_fragmento
                )

                nueva_cantidad = (
                    cantidad_lote
                    - cantidad_consumir
                )

                cursor.execute("""
                    UPDATE lotes_inventario
                    SET
                        cantidad_actual = %s,
                        activo = %s
                    WHERE id = %s
                """, (
                    nueva_cantidad,
                    (
                        1
                        if nueva_cantidad
                        > Decimal("0.000001")
                        else 0
                    ),
                    lote["id"]
                ))

                cursor.execute("""
                    INSERT INTO consumos_produccion
                    (
                        produccion_id,
                        material_id,
                        lote_id,
                        cantidad,
                        unidad_id,
                        costo_unitario,
                        costo_total
                    )
                    VALUES
                    (
                        %s, %s, %s, %s,
                        %s, %s, %s
                    )
                """, (
                    produccion_id,
                    material_id,
                    lote["id"],
                    cantidad_consumir,
                    unidad_id,
                    costo_unitario,
                    costo_fragmento
                ))

                cantidad_restante -= (
                    cantidad_consumir
                )

            if (
                cantidad_restante
                > Decimal("0.000001")
            ):
                raise ValueError(
                    f"No existen lotes suficientes para "
                    f"{material['nombre']}."
                )

            # ------------------------------------------------
            # STOCK GENERAL
            # ------------------------------------------------

            nuevo_stock = (
                stock_actual
                - cantidad_necesaria
            )

            if (
                abs(nuevo_stock)
                < Decimal("0.000001")
            ):
                nuevo_stock = Decimal("0")

            cursor.execute("""
                UPDATE materiales
                SET stock_actual = %s
                WHERE id = %s
            """, (
                nuevo_stock,
                material_id
            ))

            # ------------------------------------------------
            # MOVIMIENTO GENERAL DE INVENTARIO
            # ------------------------------------------------

            costo_unitario_real = (
                costo_material
                / cantidad_necesaria
            )

            nombre_real = material["nombre"]

            if material["color"]:
                nombre_real += (
                    f" - {material['color']}"
                )

            cursor.execute("""
                INSERT INTO movimientos_inventario
                (
                    material_id,
                    variante_id,
                    tipo,
                    cantidad,
                    unidad_id,
                    costo_unitario,
                    referencia_tipo,
                    referencia_id,
                    usuario_id,
                    notas
                )
                VALUES
                (
                    %s,
                    NULL,
                    'CONSUMO',
                    %s,
                    %s,
                    %s,
                    'PRODUCCION',
                    %s,
                    %s,
                    %s
                )
            """, (
                material_id,
                cantidad_necesaria,
                unidad_id,
                costo_unitario_real,
                produccion_id,
                8,
                (
                    f"Consumo producción #{produccion_id}. "
                    f"Material real: {nombre_real}. "
                    f"{detalle_consumo}"
                )
            ))

        # ====================================================
        # COSTO REAL DE LA PRODUCCIÓN
        # ====================================================

        costo_total_real = (
            costo_total_real.quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP
            )
        )

        cursor.execute("""
            UPDATE producciones
            SET costo_real = %s
            WHERE id = %s
        """, (
            costo_total_real,
            produccion_id
        ))

        conn.commit()

        flash(
            f"Materiales consumidos correctamente. "
            f"Costo real: Q{costo_total_real:.2f}.",
            "success"
        )

    except Exception as e:

        conn.rollback()

        flash(
            f"No se pudieron consumir los materiales: {e}",
            "danger"
        )

    finally:

        cursor.close()
        conn.close()

    return redirect(
        url_for(
            "producciones.detalle",
            produccion_id=produccion_id
        )
    )


# ============================================================
# REGISTRAR COSTO REAL DE PRODUCCIÓN EXTERNA
# ============================================================

@producciones_bp.route(
    "/<int:produccion_id>/costo-externo",
    methods=["POST"]
)
def registrar_costo_externo(produccion_id):

    conn = obtener_conexion()
    cursor = conn.cursor(dictionary=True)

    try:

        costo_texto = request.form.get(
            "costo_real",
            ""
        ).strip()

        proveedor_id = request.form.get(
            "proveedor_id"
        )

        notas = request.form.get(
            "notas_externas",
            ""
        ).strip()

        if not costo_texto:

            raise ValueError(
                "Debes indicar el costo real "
                "cobrado por el proveedor."
            )

        costo_real = Decimal(
            costo_texto
        )

        if costo_real < 0:

            raise ValueError(
                "El costo real no puede ser negativo."
            )

        if proveedor_id:

            proveedor_id = int(
                proveedor_id
            )

            cursor.execute("""
                SELECT id
                FROM proveedores
                WHERE id = %s
                AND activo = 1
            """, (proveedor_id,))

            if not cursor.fetchone():

                raise ValueError(
                    "El proveedor seleccionado "
                    "no es válido."
                )

        else:

            proveedor_id = None

        cursor.execute("""
            SELECT
                id,
                tipo,
                estado
            FROM producciones
            WHERE id = %s
            FOR UPDATE
        """, (produccion_id,))

        produccion = cursor.fetchone()

        if not produccion:

            raise ValueError(
                "La producción no existe."
            )

        if produccion["tipo"] != "EXTERNA":

            raise ValueError(
                "Esta opción solo corresponde "
                "a producciones externas."
            )

        if produccion["estado"] not in (
            "PENDIENTE",
            "EN_PRODUCCION",
            "ENVIADO_PROVEEDOR",
            "PRODUCCION_EXTERNA",
            "RECIBIDO",
            "REVISION"
        ):

            raise ValueError(
                "El costo externo ya no puede modificarse "
                "en el estado actual."
            )

        cursor.execute("""
            UPDATE producciones
            SET
                costo_real = %s,
                proveedor_id = %s,
                notas = CASE
                    WHEN %s = ''
                    THEN notas
                    ELSE %s
                END
            WHERE id = %s
        """, (
            costo_real,
            proveedor_id,
            notas,
            notas,
            produccion_id
        ))

        conn.commit()

        flash(
            f"Costo externo registrado: "
            f"Q{costo_real:.2f}.",
            "success"
        )

    except Exception as e:

        conn.rollback()

        flash(
            f"No se pudo registrar el costo externo: {e}",
            "danger"
        )

    finally:

        cursor.close()
        conn.close()

    return redirect(
        url_for(
            "producciones.detalle",
            produccion_id=produccion_id
        )
    )


# ============================================================
# TERMINAR PRODUCCIÓN
# ============================================================

@producciones_bp.route(
    "/<int:produccion_id>/terminar",
    methods=["POST"]
)
def terminar(produccion_id):

    conn = obtener_conexion()
    cursor = conn.cursor(dictionary=True)

    try:

        # ====================================================
        # PRODUCCIÓN + DETALLE + PEDIDO
        # ====================================================

        cursor.execute("""
            SELECT
                pr.id,
                pr.tipo,
                pr.estado,
                pr.costo_real,
                pr.detalle_pedido_id,

                dp.pedido_id,
                dp.subtotal,
                dp.precio_unitario,
                dp.cantidad

            FROM producciones pr

            INNER JOIN detalle_pedido dp
                ON pr.detalle_pedido_id = dp.id

            WHERE pr.id = %s

            FOR UPDATE
        """, (produccion_id,))

        produccion = cursor.fetchone()

        if not produccion:

            raise ValueError(
                "La producción no existe."
            )

        if produccion["estado"] != "EN_PRODUCCION":

            raise ValueError(
                "Solo se puede terminar una producción "
                "que está en producción."
            )

        if produccion["costo_real"] is None:

            if produccion["tipo"] == "INTERNA":

                raise ValueError(
                    "Debes consumir los materiales antes "
                    "de terminar la producción."
                )

            raise ValueError(
                "Debes registrar el costo real del proveedor "
                "antes de terminar la producción externa."
            )

        pedido_id = produccion["pedido_id"]

        detalle_pedido_id = (
            produccion["detalle_pedido_id"]
        )

        costo_real = Decimal(
            str(
                produccion["costo_real"]
                or 0
            )
        )

        subtotal = Decimal(
            str(
                produccion["subtotal"]
                or 0
            )
        )

        # Ganancia bruta del detalle.
        # El descuento general del pedido se aplica después
        # en la vista de rentabilidad del pedido.
        ganancia = (
            subtotal
            - costo_real
        )

        # ====================================================
        # ACTUALIZAR DETALLE
        # ====================================================

        cursor.execute("""
            UPDATE detalle_pedido
            SET
                costo_real = %s,
                ganancia = %s
            WHERE id = %s
        """, (
            costo_real,
            ganancia,
            detalle_pedido_id
        ))

        # ====================================================
        # TERMINAR PRODUCCIÓN
        # ====================================================

        cursor.execute("""
            UPDATE producciones
            SET
                estado = 'TERMINADO',
                fecha_terminado = NOW()
            WHERE id = %s
        """, (produccion_id,))

        # ====================================================
        # VERIFICAR SI TODAS TERMINARON
        # ====================================================

        cursor.execute("""
            SELECT
                COUNT(*) AS total_producciones,

                SUM(
                    CASE
                        WHEN estado = 'TERMINADO'
                        THEN 1
                        ELSE 0
                    END
                ) AS producciones_terminadas

            FROM producciones pr

            INNER JOIN detalle_pedido dp
                ON pr.detalle_pedido_id = dp.id

            WHERE dp.pedido_id = %s
            AND pr.estado != 'CANCELADO'
        """, (pedido_id,))

        estado_producciones = (
            cursor.fetchone()
        )

        total_producciones = int(
            estado_producciones[
                "total_producciones"
            ]
            or 0
        )

        producciones_terminadas = int(
            estado_producciones[
                "producciones_terminadas"
            ]
            or 0
        )

        if (
            total_producciones > 0
            and producciones_terminadas
            == total_producciones
        ):

            cursor.execute("""
                UPDATE pedidos
                SET estado = 'LISTO'
                WHERE id = %s
            """, (pedido_id,))

            mensaje_pedido = (
                " Todas las producciones del pedido "
                "están terminadas. El pedido está LISTO."
            )

        else:

            mensaje_pedido = (
                " El pedido todavía tiene "
                "producciones pendientes."
            )

        conn.commit()

        flash(
            f"Producción marcada como terminada. "
            f"Costo real: Q{costo_real:.2f}. "
            f"Ganancia bruta del producto: "
            f"Q{ganancia:.2f}."
            f"{mensaje_pedido}",
            "success"
        )

    except Exception as e:

        conn.rollback()

        flash(
            f"No se pudo terminar la producción: {e}",
            "danger"
        )

    finally:

        cursor.close()
        conn.close()

    return redirect(
        url_for(
            "producciones.detalle",
            produccion_id=produccion_id
        )
    )